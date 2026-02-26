"""LLM adjudication for ambiguous advisory helpfulness events.

Consumes watcher queue rows from:
  ~/.spark/advisor/helpfulness_llm_queue.jsonl

Writes reviewed decisions to:
  ~/.spark/advisor/helpfulness_llm_reviews.jsonl

This module is intentionally narrow:
- Only adjudicates already-queued ambiguous/conflict rows
- Keeps deterministic watcher outputs as baseline
- Emits explicit status/confidence for safe downstream override logic
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

try:
    import httpx as _httpx
except Exception:
    _httpx = None


REVIEW_SCHEMA_VERSION = 1
ALLOWED_LABELS = {"helpful", "unhelpful", "harmful", "not_followed", "unknown", "abstain"}

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class LLMAdjudicatorConfig:
    spark_dir: Path
    provider: str = "auto"  # auto|minimax|kimi
    timeout_s: float = 16.0
    temperature: float = 0.0
    max_output_tokens: int = 220
    min_review_confidence: float = 0.65
    max_queue_rows: int = 2000
    max_reviews_rows: int = 20000
    max_events: int = 120
    force: bool = False
    write_files: bool = True


@dataclass(frozen=True)
class LLMPaths:
    queue_file: Path
    reviews_file: Path


def _paths(spark_dir: Path) -> LLMPaths:
    return LLMPaths(
        queue_file=spark_dir / "advisor" / "helpfulness_llm_queue.jsonl",
        reviews_file=spark_dir / "advisor" / "helpfulness_llm_reviews.jsonl",
    )


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _tail_jsonl(path: Path, max_rows: int) -> List[Dict[str, Any]]:
    if not path.exists() or max_rows <= 0:
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-max_rows:]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _write_jsonl_atomic(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(str(tmp), str(path))


def _strip_think(text: str) -> str:
    return _THINK_TAG_RE.sub("", str(text or "")).strip()


def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    try:
        maybe = json.loads(text)
        return maybe if isinstance(maybe, dict) else None
    except Exception:
        pass
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = re.sub(r"^json\s*", "", cleaned, flags=re.IGNORECASE)
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _choose_provider(preferred: str) -> Optional[str]:
    p = _norm_text(preferred).lower() or "auto"
    if p in {"minimax", "kimi"}:
        return p
    has_minimax = bool(os.getenv("SPARK_MINIMAX_API_KEY") or os.getenv("MINIMAX_API_KEY"))
    has_kimi = bool(os.getenv("SPARK_KIMI_API_KEY") or os.getenv("KIMI_API_KEY"))
    if has_minimax:
        return "minimax"
    if has_kimi:
        return "kimi"
    return None


def _provider_settings(provider: str) -> Dict[str, str]:
    p = _norm_text(provider).lower()
    if p == "minimax":
        key = _norm_text(os.getenv("SPARK_MINIMAX_API_KEY") or os.getenv("MINIMAX_API_KEY"))
        base = _norm_text(os.getenv("SPARK_MINIMAX_BASE_URL") or "https://api.minimax.io/v1").rstrip("/")
        model = _norm_text(os.getenv("SPARK_MINIMAX_MODEL") or "MiniMax-M2.5")
        return {"provider": p, "api_key": key, "base_url": base, "model": model}
    if p == "kimi":
        key = _norm_text(os.getenv("SPARK_KIMI_API_KEY") or os.getenv("KIMI_API_KEY"))
        base = _norm_text(os.getenv("SPARK_KIMI_BASE_URL") or "https://api.moonshot.cn/v1").rstrip("/")
        model = _norm_text(os.getenv("SPARK_KIMI_MODEL") or "kimi-k2.5")
        return {"provider": p, "api_key": key, "base_url": base, "model": model}
    return {"provider": p, "api_key": "", "base_url": "", "model": ""}


def _query_openai_style_chat(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    timeout_s: float,
    temperature: float,
    max_tokens: int,
) -> Dict[str, Any]:
    if _httpx is None:
        return {"ok": False, "error": "httpx_unavailable"}
    if not api_key:
        return {"ok": False, "error": f"{provider}_api_key_missing"}
    if not base_url:
        return {"ok": False, "error": f"{provider}_base_url_missing"}

    url = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": max(0.0, min(1.0, float(temperature))),
        "max_tokens": max(80, int(max_tokens)),
    }
    try:
        with _httpx.Client(timeout=max(3.0, float(timeout_s))) as client:
            resp = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if resp.status_code != 200:
            return {"ok": False, "error": f"http_{resp.status_code}", "body": resp.text[:400]}
        data = resp.json()
    except Exception as e:
        return {"ok": False, "error": f"request_failed:{type(e).__name__}"}

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return {"ok": False, "error": "missing_choices"}
    msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = msg.get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                txt = item.get("text")
                if txt:
                    parts.append(str(txt))
        content = "\n".join(parts)
    text = _strip_think(str(content or ""))
    return {"ok": True, "raw": text, "provider": provider, "model": model}


def _build_prompt(event: Dict[str, Any]) -> str:
    compact = {
        "event_id": _norm_text(event.get("event_id")),
        "tool": _norm_text(event.get("tool")),
        "source_hint": _norm_text(event.get("source_hint")),
        "base_label": _norm_text(event.get("helpful_label")),
        "base_confidence": _safe_float(event.get("confidence"), 0.0),
        "implicit_signal": _norm_text(event.get("implicit_signal")),
        "explicit_status": _norm_text(event.get("explicit_status")),
        "conflict": bool(event.get("conflict")),
        "followed": event.get("followed"),
        "evidence_refs": list((event.get("evidence_refs") or [])[:4]),
    }
    return (
        "You are adjudicating one advisory helpfulness event.\n"
        "Pick the most defensible label from: helpful, unhelpful, harmful, not_followed, unknown, abstain.\n"
        "Rules:\n"
        "- explicit feedback is stronger than implicit success.\n"
        "- unhelpful signal means failed outcome after exposure.\n"
        "- if evidence is insufficient, return unknown or abstain.\n"
        "Return STRICT JSON only with keys:\n"
        '{"label":"...","confidence":0.0,"rationale":"..."}\n'
        f"Event:\n{json.dumps(compact, ensure_ascii=False)}"
    )


def _parse_judgement(raw_text: str) -> Dict[str, Any]:
    parsed = _extract_json_obj(raw_text)
    if not parsed:
        return {"ok": False, "status": "parse_error", "error": "no_json_object"}
    label = _norm_text(parsed.get("label")).lower()
    if label not in ALLOWED_LABELS:
        return {"ok": False, "status": "parse_error", "error": f"invalid_label:{label}"}
    confidence = max(0.0, min(1.0, _safe_float(parsed.get("confidence"), 0.0)))
    rationale = _norm_text(parsed.get("rationale"))[:400]
    if label == "abstain":
        return {"ok": True, "status": "abstain", "label": label, "confidence": confidence, "rationale": rationale}
    return {"ok": True, "status": "ok", "label": label, "confidence": confidence, "rationale": rationale}


def _default_judge(event: Dict[str, Any], cfg: LLMAdjudicatorConfig) -> Dict[str, Any]:
    provider = _choose_provider(cfg.provider)
    if not provider:
        return {"ok": False, "status": "provider_unavailable", "error": "no_supported_provider_keys"}
    ps = _provider_settings(provider)
    prompt = _build_prompt(event)
    query = _query_openai_style_chat(
        provider=provider,
        api_key=ps["api_key"],
        base_url=ps["base_url"],
        model=ps["model"],
        prompt=prompt,
        timeout_s=cfg.timeout_s,
        temperature=cfg.temperature,
        max_tokens=cfg.max_output_tokens,
    )
    if not query.get("ok"):
        return {
            "ok": False,
            "status": "provider_error",
            "provider": provider,
            "model": ps.get("model", ""),
            "error": _norm_text(query.get("error")),
        }
    judged = _parse_judgement(_norm_text(query.get("raw")))
    judged["provider"] = provider
    judged["model"] = ps.get("model", "")
    judged["raw_excerpt"] = _norm_text(query.get("raw"))[:400]
    return judged


def run_helpfulness_llm_adjudicator(
    cfg: LLMAdjudicatorConfig,
    *,
    judge_fn: Optional[Callable[[Dict[str, Any], LLMAdjudicatorConfig], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    paths = _paths(cfg.spark_dir)
    judge = judge_fn or _default_judge

    queue_rows = _tail_jsonl(paths.queue_file, cfg.max_queue_rows)
    reviews_existing = _tail_jsonl(paths.reviews_file, cfg.max_reviews_rows)
    reviews_by_event: Dict[str, Dict[str, Any]] = {}
    for row in reviews_existing:
        eid = _norm_text(row.get("event_id"))
        if not eid:
            continue
        prior = reviews_by_event.get(eid)
        if not prior or _safe_float(row.get("reviewed_at"), 0.0) >= _safe_float(prior.get("reviewed_at"), 0.0):
            reviews_by_event[eid] = row

    reviewed_now = 0
    skipped_existing = 0
    processed = 0
    for row in queue_rows:
        if processed >= max(1, int(cfg.max_events)):
            break
        event_id = _norm_text(row.get("event_id"))
        if not event_id:
            continue
        existing = reviews_by_event.get(event_id)
        if existing and not cfg.force:
            status = _norm_text(existing.get("status"))
            if status in {"ok", "abstain"}:
                skipped_existing += 1
                continue

        judged = judge(row, cfg)
        processed += 1
        reviewed_at = time.time()
        status = _norm_text(judged.get("status")) or ("ok" if judged.get("ok") else "error")
        label = _norm_text(judged.get("label")).lower()
        confidence = max(0.0, min(1.0, _safe_float(judged.get("confidence"), 0.0)))

        review_row = {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "event_id": event_id,
            "trace_id": _norm_text(row.get("trace_id")),
            "tool": _norm_text(row.get("tool")),
            "request_ts": _safe_float(row.get("request_ts"), 0.0),
            "provider": _norm_text(judged.get("provider")),
            "model": _norm_text(judged.get("model")),
            "status": status,
            "label": label if label in ALLOWED_LABELS else "",
            "confidence": round(confidence, 3),
            "rationale": _norm_text(judged.get("rationale"))[:400],
            "raw_excerpt": _norm_text(judged.get("raw_excerpt"))[:400],
            "error": _norm_text(judged.get("error"))[:200],
            "reviewed_at": reviewed_at,
        }
        reviews_by_event[event_id] = review_row
        reviewed_now += 1

    merged = sorted(reviews_by_event.values(), key=lambda r: (_safe_float(r.get("reviewed_at"), 0.0), _norm_text(r.get("event_id"))))
    if cfg.write_files:
        _write_jsonl_atomic(paths.reviews_file, merged)

    by_status: Dict[str, int] = {}
    by_label: Dict[str, int] = {}
    for row in merged:
        st = _norm_text(row.get("status")) or "unknown"
        by_status[st] = by_status.get(st, 0) + 1
        lb = _norm_text(row.get("label")).lower()
        if lb:
            by_label[lb] = by_label.get(lb, 0) + 1

    return {
        "ok": True,
        "paths": {
            "queue_file": str(paths.queue_file),
            "reviews_file": str(paths.reviews_file),
        },
        "queue_rows": len(queue_rows),
        "processed": processed,
        "reviewed_now": reviewed_now,
        "skipped_existing": skipped_existing,
        "total_reviews": len(merged),
        "by_status": by_status,
        "by_label": by_label,
    }


def run_helpfulness_llm_adjudicator_default(
    *,
    spark_dir: Optional[Path] = None,
    provider: str = "auto",
    timeout_s: float = 16.0,
    temperature: float = 0.0,
    max_output_tokens: int = 220,
    min_review_confidence: float = 0.65,
    max_queue_rows: int = 2000,
    max_reviews_rows: int = 20000,
    max_events: int = 120,
    force: bool = False,
    write_files: bool = True,
    judge_fn: Optional[Callable[[Dict[str, Any], LLMAdjudicatorConfig], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    cfg = LLMAdjudicatorConfig(
        spark_dir=(spark_dir or (Path.home() / ".spark")),
        provider=provider,
        timeout_s=timeout_s,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        min_review_confidence=min_review_confidence,
        max_queue_rows=max_queue_rows,
        max_reviews_rows=max_reviews_rows,
        max_events=max_events,
        force=force,
        write_files=write_files,
    )
    return run_helpfulness_llm_adjudicator(cfg, judge_fn=judge_fn)

