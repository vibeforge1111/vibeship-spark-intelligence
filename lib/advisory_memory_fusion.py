"""
Memory fusion adapter for advisory.

Phase 1 scope:
- Build an evidence bundle across available Spark memory sources
- Degrade gracefully when sources are missing
- Expose `memory_absent_declared` for deterministic fallback behavior
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .outcome_log import read_outcomes
from .primitive_filter import is_primitive_text
from .advisory_quarantine import record_quarantine_item
from .spark_memory_spine import load_cognitive_insights_runtime_snapshot
CHIP_INSIGHTS_DIR = Path.home() / ".spark" / "chip_insights"
CHIP_TELEMETRY_BLOCKLIST = {"spark-core", "bench_core"}
CHIP_TELEMETRY_MARKERS = (
    "post_tool",
    "pre_tool",
    "tool_name:",
    "file_path:",
    "event_type:",
    "user_prompt_signal",
    "status: success",
    "cwd:",
)
ORCHESTRATION_DIR = Path.home() / ".spark" / "orchestration"
_NOISE_PATTERNS = (
    re.compile(r"\btool[_\s-]*\d+[_\s-]*error\b", re.I),
    re.compile(r"\bi struggle with tool_", re.I),
    re.compile(r"\berror_pattern:", re.I),
    re.compile(r"\brequest failed with status code\s+404\b", re.I),
)
_TOKEN_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "your",
    "have",
    "when",
    "what",
    "should",
    "would",
    "could",
    "about",
    "there",
    "here",
    "were",
    "been",
    "will",
    "just",
    "they",
    "them",
    "then",
    "than",
    "also",
    "only",
    "much",
    "more",
    "very",
    "some",
    "like",
    "into",
    "across",
    "using",
    "use",
    "used",
    "run",
    "runs",
}


def _is_noise_evidence(text: str) -> bool:
    sample = str(text or "").strip()
    if not sample:
        return True
    if is_primitive_text(sample):
        return True
    return any(rx.search(sample) for rx in _NOISE_PATTERNS)


def _tail_jsonl(path: Path, limit: int) -> List[Dict[str, Any]]:
    if limit <= 0 or not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines[-limit:]:
            line = (line or "").strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    out.append(row)
            except Exception:
                continue
    except Exception:
        return []
    return out


def _coerce_ts(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value or "").strip()
        if not text:
            return float(default)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return float(datetime.fromisoformat(text).timestamp())
    except Exception:
        try:
            return float(value)
        except Exception:
            return float(default)


def _chips_disabled() -> bool:
    return str(os.environ.get("SPARK_ADVISORY_DISABLE_CHIPS", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _premium_tools_enabled() -> bool:
    return str(os.environ.get("SPARK_PREMIUM_TOOLS", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _chips_enabled() -> bool:
    if _chips_disabled():
        return False
    if not _premium_tools_enabled():
        return False
    return str(os.environ.get("SPARK_CHIPS_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _chip_domain_match(chip_id: str, intent_text: str, intent_family: str, tool_name: str) -> float:
    chip = str(chip_id or "").strip().lower()
    text = f"{intent_text} {intent_family} {tool_name}".strip().lower()
    if not chip or not text:
        return 0.0

    social_query = any(t in text for t in ("social", "x ", "twitter", "engagement", "tweet"))
    coding_query = any(t in text for t in ("code", "python", "debug", "test", "refactor", "repo"))
    marketing_query = any(t in text for t in ("marketing", "campaign", "conversion", "audience", "brand"))
    memory_query = any(t in text for t in ("memory", "retrieval", "cross-session", "stale", "distillation"))

    social_chip = any(t in chip for t in ("social", "x_", "x-", "engagement"))
    coding_chip = any(t in chip for t in ("vibecoding", "api-design", "game_dev"))
    marketing_chip = any(t in chip for t in ("marketing", "market-intel", "biz-ops"))
    memory_chip = any(t in chip for t in ("vibecoding", "api-design"))

    score = 0.0
    if social_query and social_chip:
        score += 0.45
    if coding_query and coding_chip:
        score += 0.35
    if marketing_query and marketing_chip:
        score += 0.35
    if memory_query and memory_chip:
        score += 0.25
    if (not social_query) and social_chip:
        score -= 0.15
    return max(-0.25, min(1.0, score))


def _is_telemetry_chip_row(chip_id: str, text: str) -> bool:
    chip = str(chip_id or "").strip().lower()
    if chip in CHIP_TELEMETRY_BLOCKLIST:
        return True
    payload = str(text or "").strip().lower()
    if not payload:
        return True
    if any(marker in payload for marker in CHIP_TELEMETRY_MARKERS):
        return True
    return False


def _tokenize_text(text: str) -> List[str]:
    parts = re.split(r"[^a-z0-9_]+", str(text or "").lower())
    out: List[str] = []
    for token in parts:
        token = token.strip()
        if len(token) < 3:
            continue
        if token in _TOKEN_STOPWORDS:
            continue
        out.append(token)
    return out


def _intent_relevance_score(intent_tokens: set[str], text: str) -> float:
    if not intent_tokens:
        return 0.0
    tokens = set(_tokenize_text(text))
    if not tokens:
        return 0.0
    overlap = len(intent_tokens & tokens)
    if overlap > 0:
        return float(overlap)

    weak = 0
    for needle in intent_tokens:
        for token in tokens:
            if needle in token or token in needle:
                weak += 1
                break
    if weak > 0:
        return 0.2 + min(0.6, weak * 0.1)
    return 0.0


def _coerce_readiness(row: Dict[str, Any], confidence: float = 0.0) -> float:
    """Compute advisory readiness for a memory row without hard failures."""
    try:
        meta = row.get("meta") if isinstance(row, dict) else {}
        if isinstance(meta, dict):
            direct = meta.get("advisory_readiness")
            if direct is not None:
                return max(0.0, min(1.0, float(direct)))

        adv_q = row.get("advisory_quality") or {}
        if isinstance(adv_q, dict):
            unified = adv_q.get("unified_score")
            if unified is not None:
                return max(0.0, min(1.0, float(unified)))
            domain = str(adv_q.get("domain") or "").strip()
            if domain:
                return 0.55

        meta_readiness = row.get("advisory_readiness")
        if meta_readiness is not None:
            return max(0.0, min(1.0, float(meta_readiness)))
    except Exception:
        pass

    return max(0.0, min(1.0, float(confidence or 0.0)))


def _collect_cognitive(limit: int = 6) -> List[Dict[str, Any]]:
    data = load_cognitive_insights_runtime_snapshot()
    if not data:
        return []

    rows: List[Dict[str, Any]] = []
    if isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        if isinstance(data.get("insights"), dict):
            rows = [r for r in data.get("insights", {}).values() if isinstance(r, dict)]
        elif isinstance(data.get("insights"), list):
            rows = [r for r in data.get("insights", []) if isinstance(r, dict)]
        else:
            rows = [r for r in data.values() if isinstance(r, dict)]

    rows = rows[-max(0, limit):]
    evidence: List[Dict[str, Any]] = []
    for row in rows:
        text = str(row.get("insight") or row.get("text") or "").strip()
        if not text:
            continue
        if _is_noise_evidence(text):
            record_quarantine_item(
                source="cognitive",
                stage="collect_cognitive",
                reason="noise_evidence",
                text=text,
            )
            continue

        # Read embedded advisory quality if available
        adv_q = row.get("advisory_quality") or {}
        if isinstance(adv_q, dict) and adv_q.get("suppressed"):
            record_quarantine_item(
                source="cognitive",
                stage="collect_cognitive",
                reason="transformer_suppressed",
                text=text,
                advisory_quality=adv_q,
                advisory_readiness=row.get("advisory_readiness"),
            )
            continue  # Skip insights suppressed by distillation transformer

        # Use unified_score from transformer when available, fallback to reliability
        confidence = float(row.get("reliability") or row.get("confidence") or 0.5)
        if isinstance(adv_q, dict) and adv_q.get("unified_score"):
            unified = float(adv_q["unified_score"])
            # Blend: transformer score weighted higher than raw reliability
            confidence = max(confidence, 0.60 * unified + 0.40 * confidence)
        readiness = _coerce_readiness({"advisory_quality": adv_q}, confidence=confidence)

        evidence.append(
            {
                "source": "cognitive",
                "id": str(row.get("key") or row.get("insight_key") or text[:48]),
                "text": text,
                "confidence": confidence,
                "created_at": _coerce_ts(row.get("timestamp") or row.get("created_at") or 0.0, 0.0),
                "meta": {
                    "advisory_quality": adv_q,
                    "advisory_readiness": round(readiness, 4),
                    "source_mode": "cognitive",
                },
            }
        )
    return evidence


def _collect_eidos(intent_text: str, limit: int = 5) -> List[Dict[str, Any]]:
    if not intent_text.strip():
        return []
    try:
        from .eidos import get_retriever

        retriever = get_retriever()
        items = retriever.retrieve_for_intent(intent_text)[:limit]
    except Exception:
        return []

    evidence: List[Dict[str, Any]] = []
    for item in items:
        statement = str(getattr(item, "statement", "") or "").strip()
        if not statement:
            continue
        if _is_noise_evidence(statement):
            record_quarantine_item(
                source="eidos",
                stage="collect_eidos",
                reason="noise_evidence",
                text=statement,
            )
            continue
        evidence.append(
            {
                "source": "eidos",
                "id": str(getattr(item, "distillation_id", "") or statement[:48]),
                "text": statement,
                "confidence": float(getattr(item, "confidence", 0.6) or 0.6),
                "created_at": float(getattr(item, "created_at", 0.0) or 0.0),
                "meta": {"source_mode": "eidos"},
            }
        )
    return evidence


def _collect_chips(
    limit: int = 6,
    *,
    intent_text: str = "",
    intent_family: str = "",
    tool_name: str = "",
) -> List[Dict[str, Any]]:
    if _chips_disabled() or (not CHIP_INSIGHTS_DIR.exists()):
        return []
    files = sorted(CHIP_INSIGHTS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:6]
    min_quality = 0.30
    min_confidence = 0.45
    intent_tokens = set(_tokenize_text(intent_text))
    scored: List[tuple[float, float, float, Dict[str, Any]]] = []
    for fp in files:
        for row in _tail_jsonl(fp, limit=max(24, limit * 12)):
            captured = row.get("captured_data") or {}
            quality = (captured.get("quality_score") or {}) if isinstance(captured, dict) else {}
            quality_total = float(quality.get("total", 0.0) or 0.0)
            conf = float(row.get("confidence") or row.get("score") or quality_total or 0.0)
            if quality_total < min_quality and conf < min_confidence:
                continue
            text = str(
                row.get("insight")
                or row.get("text")
                or row.get("summary")
                or row.get("content")
                or (captured.get("summary") if isinstance(captured, dict) else "")
                or ""
            ).strip()
            if (not text) and isinstance(captured, dict):
                for key in ("signal", "trend", "pattern", "topic"):
                    if captured.get(key):
                        text = f"{key}: {captured.get(key)}"
                        break
            if not text:
                continue
            chip_id = str(row.get("chip_id") or fp.stem).strip()
            if _is_telemetry_chip_row(chip_id, text):
                record_quarantine_item(
                    source="chips",
                    stage="collect_chips",
                    reason="telemetry_marker",
                    text=text,
                    meta={"chip_id": chip_id, "file": fp.name},
                )
                continue
            if _is_noise_evidence(text):
                record_quarantine_item(
                    source="chips",
                    stage="collect_chips",
                    reason="noise_evidence",
                    text=text,
                    meta={"chip_id": chip_id, "file": fp.name},
                )
                continue
            relevance = _intent_relevance_score(intent_tokens, text) if intent_tokens else 0.0
            domain_match = _chip_domain_match(chip_id, intent_text, intent_family, tool_name)
            if intent_tokens and relevance <= 0.0 and domain_match < 0.20:
                continue
            if domain_match < -0.05 and relevance < 0.10:
                continue
            effective_conf = max(
                quality_total,
                min(1.0, (0.55 * conf) + (0.30 * quality_total) + (0.15 * max(relevance, 0.0))),
            )
            rank = (0.50 * max(relevance, 0.0)) + (0.30 * max(domain_match, 0.0)) + (0.20 * effective_conf)
            scored.append(
                (
                    rank,
                    effective_conf,
                    _coerce_ts(row.get("ts") or row.get("timestamp") or row.get("created_at") or 0.0),
                    {
                        "source": "chips",
                        "id": str(
                            row.get("insight_key")
                            or row.get("id")
                            or chip_id
                            or f"{fp.stem}:{len(scored)}"
                        ),
                        "text": text,
                        "confidence": effective_conf,
                        "created_at": _coerce_ts(row.get("ts") or row.get("timestamp") or row.get("created_at") or 0.0),
                        "meta": {
                            "file": fp.name,
                            "chip_id": chip_id,
                            "observer": row.get("observer") or row.get("observer_name"),
                            "quality_total": quality_total,
                            "intent_relevance": round(float(relevance), 4),
                            "domain_match": round(float(domain_match), 4),
                            "source_mode": "chip",
                        },
                    },
                )
            )

    scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for _, _, _, row in scored:
        text_key = str(row.get("text") or "")[:180].strip().lower()
        if text_key in seen:
            continue
        seen.add(text_key)
        deduped.append(row)
        if len(deduped) >= limit:
            break
    return deduped


def _collect_outcomes(intent_text: str, limit: int = 6) -> List[Dict[str, Any]]:
    cutoff = time.time() - (14 * 24 * 3600.0)
    rows = read_outcomes(limit=max(12, limit * 10), since=cutoff)
    intent_tokens = set(_tokenize_text(intent_text))
    scored_rows: List[tuple[float, float, Dict[str, Any]]] = []
    fallback_rows: List[tuple[float, Dict[str, Any]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or row.get("result") or "").strip()
        if not text:
            continue
        if _is_noise_evidence(text):
            record_quarantine_item(
                source="outcomes",
                stage="collect_outcomes",
                reason="noise_evidence",
                text=text,
                meta={"outcome_id": row.get("outcome_id"), "polarity": row.get("polarity")},
            )
            continue
        created_at = float(row.get("created_at") or 0.0)
        if not intent_tokens:
            fallback_rows.append((created_at, row))
            continue
        tokens = set(_tokenize_text(text))
        overlap = len(intent_tokens & tokens)
        if overlap > 0:
            scored_rows.append((float(overlap), created_at, row))
        else:
            # Keep lexical-near rows as weak fallback only when no direct match exists.
            weak_overlap = 0
            for token in intent_tokens:
                if any(token in t or t in token for t in tokens):
                    weak_overlap += 1
            if weak_overlap > 0:
                scored_rows.append((0.5 + min(0.4, weak_overlap * 0.1), created_at, row))
            else:
                fallback_rows.append((created_at, row))

    selected_rows: List[Dict[str, Any]]
    if scored_rows:
        scored_rows.sort(key=lambda t: (t[0], t[1]), reverse=True)
        selected_rows = [row for _, _, row in scored_rows[: max(1, limit)]]
    else:
        fallback_rows.sort(key=lambda t: t[0], reverse=True)
        selected_rows = [row for _, row in fallback_rows[: max(1, min(limit, 2))]]

    evidence: List[Dict[str, Any]] = []
    for row in selected_rows:
        text = str(row.get("text") or row.get("result") or "").strip()
        if not text:
            continue
        if _is_noise_evidence(text):
            continue
        polarity = str(row.get("polarity") or "neutral")
        confidence = 0.7 if polarity == "pos" else (0.45 if polarity == "neutral" else 0.8)
        evidence.append(
            {
                "source": "outcomes",
                "id": str(row.get("outcome_id") or f"outcome:{len(evidence)}"),
                "text": text,
                "confidence": confidence,
                "created_at": float(row.get("created_at") or 0.0),
                "meta": {
                    "polarity": polarity,
                    "event_type": row.get("event_type"),
                    "source_mode": "outcome",
                },
            }
        )
    return evidence


def _collect_orchestration(limit: int = 5) -> List[Dict[str, Any]]:
    handoffs = ORCHESTRATION_DIR / "handoffs.jsonl"
    if not handoffs.exists():
        return []
    evidence: List[Dict[str, Any]] = []
    for row in _tail_jsonl(handoffs, limit=limit):
        ctx = row.get("context") or {}
        prompt = str(ctx.get("prompt") or ctx.get("task") or ctx.get("summary") or "").strip()
        if not prompt:
            continue
        if _is_noise_evidence(prompt):
            record_quarantine_item(
                source="orchestration",
                stage="collect_orchestration",
                reason="noise_evidence",
                text=prompt,
                meta={"handoff_id": row.get("handoff_id")},
            )
            continue
        evidence.append(
            {
                "source": "orchestration",
                "id": str(row.get("handoff_id") or f"handoff:{len(evidence)}"),
                "text": prompt,
                "confidence": 0.55,
                "created_at": float(row.get("timestamp") or 0.0),
                "meta": {"to_agent": row.get("to_agent"), "success": row.get("success"), "source_mode": "orchestration"},
            }
        )
    return evidence


def _collect_mind(intent_text: str, limit: int = 4) -> List[Dict[str, Any]]:
    if not intent_text.strip():
        return []
    try:
        from .mind_bridge import get_mind_bridge

        bridge = get_mind_bridge()
        memories = bridge.retrieve_relevant(intent_text, limit=limit)
    except Exception:
        return []
    evidence: List[Dict[str, Any]] = []
    for mem in memories:
        if not isinstance(mem, dict):
            continue
        text = str(mem.get("content") or mem.get("text") or "").strip()
        if not text:
            continue
        mem_meta = mem.get("meta")
        if not isinstance(mem_meta, dict):
            mem_meta = {}
        advisory_quality = mem.get("advisory_quality")
        if not isinstance(advisory_quality, dict):
            advisory_quality = mem_meta.get("advisory_quality")
        if not isinstance(advisory_quality, dict):
            advisory_quality = {}
        if _is_noise_evidence(text):
            record_quarantine_item(
                source="mind",
                stage="collect_mind",
                reason="noise_evidence",
                text=text,
                meta=mem_meta,
                advisory_quality=advisory_quality,
                advisory_readiness=mem_meta.get("advisory_readiness"),
            )
            continue
        confidence = float(mem.get("salience") or mem.get("score") or mem.get("confidence") or 0.6)
        readiness = _coerce_readiness(
            {
                "advisory_quality": advisory_quality,
                "advisory_readiness": mem_meta.get("advisory_readiness"),
            },
            confidence=confidence,
        )
        row_meta = dict(mem_meta)
        row_meta["advisory_quality"] = advisory_quality
        row_meta["advisory_readiness"] = round(readiness, 4)
        row_meta["source_mode"] = row_meta.get("source_mode") or "mind"
        evidence.append(
            {
                "source": "mind",
                "id": str(mem.get("memory_id") or mem.get("id") or f"mind:{len(evidence)}"),
                "text": text,
                "confidence": confidence,
                "created_at": float(mem.get("created_at") or 0.0),
                "meta": row_meta,
            }
        )
    return evidence


def _collect_with_status(fetcher: Callable[[], List[Dict[str, Any]]]) -> Dict[str, Any]:
    try:
        rows = fetcher()
        return {"available": True, "rows": list(rows or [])}
    except Exception as exc:
        return {"available": False, "rows": [], "error": str(exc)}


def _collect_chips_for_intent(
    *,
    limit: int,
    intent_text: str,
    intent_family: str,
    tool_name: str,
) -> List[Dict[str, Any]]:
    """Compat wrapper so tests monkeypatching old _collect_chips(limit=...) keep working."""
    try:
        return _collect_chips(
            limit=limit,
            intent_text=intent_text,
            intent_family=intent_family,
            tool_name=tool_name,
        )
    except TypeError:
        return _collect_chips(limit=limit)


def build_memory_bundle(
    *,
    session_id: str,
    intent_text: str,
    intent_family: str,
    tool_name: str,
    include_mind: bool = False,
) -> Dict[str, Any]:
    """
    Build a single memory evidence bundle for advisory decisions.
    """
    source_results = {
        "cognitive": _collect_with_status(lambda: _collect_cognitive(limit=6)),
        "eidos": _collect_with_status(lambda: _collect_eidos(intent_text, limit=5)),
        "chips": _collect_with_status(
            lambda: _collect_chips_for_intent(
                limit=6,
                intent_text=intent_text,
                intent_family=intent_family,
                tool_name=tool_name,
            )
        ),
        "outcomes": _collect_with_status(lambda: _collect_outcomes(intent_text, limit=6)),
        "orchestration": _collect_with_status(lambda: _collect_orchestration(limit=5)),
    }
    if include_mind:
        source_results["mind"] = _collect_with_status(lambda: _collect_mind(intent_text, limit=4))

    evidence: List[Dict[str, Any]] = []
    missing_sources: List[str] = []
    source_summary: Dict[str, Dict[str, Any]] = {}

    for source_name, result in source_results.items():
        rows = result.get("rows") or []
        available = bool(result.get("available", True))
        if not available:
            missing_sources.append(source_name)
        source_summary[source_name] = {
            "available": available,
            "count": len(rows),
            "error": result.get("error"),
        }
        evidence.extend(rows)

    intent_tokens = set(_tokenize_text(intent_text))
    scored: List[tuple[float, float, float, Dict[str, Any]]] = []
    for row in evidence:
        text = str((row or {}).get("text") or "").strip()
        if not text:
            continue
        # Skip suppressed items from any source
        meta = row.get("meta") or {}
        adv_q = meta.get("advisory_quality") or {}
        if isinstance(adv_q, dict) and adv_q.get("suppressed"):
            record_quarantine_item(
                source=str(row.get("source") or "unknown"),
                stage="build_memory_bundle",
                reason="transformer_suppressed",
                text=text,
                advisory_quality=adv_q,
                advisory_readiness=meta.get("advisory_readiness"),
                meta=dict(meta),
            )
            continue
        intent_relevance = _intent_relevance_score(intent_tokens, text)
        relevance = intent_relevance
        # Boost relevance with advisory quality structure match
        readiness = _coerce_readiness(meta, float(row.get("confidence") or 0.0))
        if isinstance(adv_q, dict) and adv_q.get("unified_score"):
            relevance += float(adv_q["unified_score"]) * 0.15
        relevance += 0.12 * readiness
        meta["intent_relevance"] = round(float(intent_relevance), 4)
        if readiness and not meta.get("advisory_readiness"):
            meta["advisory_readiness"] = round(readiness, 4)
        row["meta"] = meta
        scored.append(
            (
                relevance,
                max(0.0, min(1.0, float(row.get("confidence") or 0.0) + 0.1 * readiness)),
                float(row.get("created_at") or 0.0),
                row,
            )
        )

    if scored and intent_tokens:
        relevant = [
            entry
            for entry in scored
            if float(((entry[3] or {}).get("meta") or {}).get("intent_relevance", 0.0)) > 0.0
        ]
        if relevant:
            scored = relevant

    scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    evidence = [row for _, _, _, row in scored]

    deduped: List[Dict[str, Any]] = []
    seen_text = set()
    for row in evidence:
        text = str((row or {}).get("text") or "").strip()
        if not text or _is_noise_evidence(text):
            continue
        key = " ".join(text.lower().split())[:180]
        if key in seen_text:
            continue
        seen_text.add(key)
        deduped.append(row)
        if len(deduped) >= 24:
            break
    evidence = deduped

    memory_absent = len(evidence) == 0

    return {
        "session_id": session_id,
        "intent_family": intent_family or "emergent_other",
        "tool_name": tool_name,
        "intent_text": intent_text,
        "generated_ts": time.time(),
        "sources": source_summary,
        "missing_sources": missing_sources,
        "evidence": evidence,
        "evidence_count": len(evidence),
        "memory_absent_declared": memory_absent,
    }
