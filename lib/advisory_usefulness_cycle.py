"""4-hour advisory usefulness cycle with context-first rating and feedback writes.

Builds a trace-rich rating queue, emits a hard-question prompt for external LLMs,
applies ratings into explicit feedback, and refreshes quality/helpfulness streams.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


KNOWN_HELPFULNESS_LABELS = {"helpful", "unhelpful", "harmful"}
VALID_RATING_LABELS = {"helpful", "unhelpful", "harmful", "not_followed", "unknown"}


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_ts(row: Dict[str, Any], keys: Sequence[str]) -> float:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        text = _norm_text(value)
        if not text:
            continue
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return float(text)
        except Exception:
            pass
        try:
            from datetime import datetime

            return float(datetime.fromisoformat(text).timestamp())
        except Exception:
            continue
    return 0.0


def _tail_jsonl(path: Path, max_rows: int) -> List[Dict[str, Any]]:
    if not path.exists() or max_rows <= 0:
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for raw in lines[-max_rows:]:
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            if not isinstance(row, dict):
                continue
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(str(tmp), str(path))


def _index_by_trace(rows: Iterable[Dict[str, Any]], trace_key: str = "trace_id") -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        trace = _norm_text(row.get(trace_key))
        if not trace:
            continue
        out.setdefault(trace, []).append(row)
    for trace in list(out.keys()):
        out[trace] = sorted(out[trace], key=lambda r: _to_ts(r, ("ts", "timestamp", "created_at")))
    return out


def _pick_implicit_signal(
    implicit_rows: List[Dict[str, Any]],
    *,
    tool: str,
    emitted_ts: float,
    advice_id: str,
) -> str:
    best = ""
    best_dist = 10**18
    tool_norm = _norm_text(tool).lower()
    for row in implicit_rows:
        row_tool = _norm_text(row.get("tool")).lower()
        if tool_norm and row_tool and row_tool != tool_norm:
            continue
        ids = row.get("advice_ids")
        if isinstance(ids, list) and advice_id and advice_id not in {str(x) for x in ids}:
            continue
        signal = _norm_text(row.get("signal")).lower()
        if not signal:
            continue
        ts = _to_ts(row, ("timestamp", "created_at", "ts"))
        if ts <= 0:
            continue
        dist = abs(ts - emitted_ts)
        if dist < best_dist:
            best = signal
            best_dist = dist
    return best


def _post_tool_success(engine_rows: List[Dict[str, Any]]) -> Optional[bool]:
    for row in reversed(engine_rows):
        if _norm_text(row.get("event")).lower() != "post_tool_recorded":
            continue
        extra = row.get("extra")
        if isinstance(extra, dict) and "success" in extra:
            return bool(extra.get("success"))
    return None


def _heuristic_rating(
    *,
    implicit_signal: str,
    post_success: Optional[bool],
    timing_bucket: str,
    impact_score: float,
) -> Tuple[str, float, str]:
    sig = _norm_text(implicit_signal).lower()
    timing = _norm_text(timing_bucket).lower()

    if sig in {"unhelpful"}:
        return "unhelpful", 0.88, "implicit_unhelpful_signal"
    if sig in {"followed", "helpful"} and post_success is True:
        return "helpful", 0.84, "implicit_followed_plus_success"
    if sig in {"followed", "helpful"} and post_success is False:
        return "unhelpful", 0.78, "implicit_followed_but_failure"
    if sig in {"not_followed", "ignored"}:
        return "not_followed", 0.82, "implicit_not_followed_signal"
    if post_success is True and timing in {"right_on_time", "near_time"} and impact_score >= 0.75:
        return "helpful", 0.66, "timely_high_impact_success_proxy"
    if post_success is False and impact_score >= 0.7:
        return "unhelpful", 0.64, "high_impact_failure_proxy"
    return "unknown", 0.0, "insufficient_context"


def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    payload = _norm_text(text)
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    start = payload.find("{")
    end = payload.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(payload[start : end + 1])
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_llm_ratings(text: str) -> List[Dict[str, Any]]:
    obj = _extract_json_obj(text)
    if not isinstance(obj, dict):
        return []
    rows = obj.get("ratings")
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_id = _norm_text(row.get("event_id"))
        label = _norm_text(row.get("label")).lower()
        if not event_id or label not in VALID_RATING_LABELS:
            continue
        confidence = max(0.0, min(1.0, _safe_float(row.get("confidence"), 0.0)))
        notes = _norm_text(row.get("notes"))[:200]
        out.append(
            {
                "event_id": event_id,
                "label": label,
                "confidence": confidence,
                "notes": notes,
            }
        )
    return out


def _resolve_providers(raw: str) -> List[str]:
    txt = _norm_text(raw).lower()
    if not txt or txt == "auto":
        out: List[str] = []
        if _norm_text(os.getenv("MINIMAX_API_KEY") or os.getenv("SPARK_MINIMAX_API_KEY")):
            out.append("minimax")
        out.append("claude")
        return out
    providers: List[str] = []
    for token in [x.strip().lower() for x in txt.split(",")]:
        if token and token not in providers:
            providers.append(token)
    return providers


def _run_provider(provider: str, prompt: str, timeout_s: float) -> Tuple[str, str]:
    try:
        if provider == "claude":
            from .llm import ask_claude

            text = ask_claude(
                prompt,
                system_prompt=(
                    "You are a strict advisory usefulness reviewer. "
                    "Return only valid JSON for the requested schema."
                ),
                max_tokens=3200,
                timeout_s=max(30, int(timeout_s)),
            )
            return _norm_text(text), ""
        if provider == "minimax":
            from .advisory_synthesizer import _query_minimax

            text = _query_minimax(prompt, timeout_s=max(30.0, float(timeout_s)))
            return _norm_text(text), ""
        from .advisory_synthesizer import _query_provider

        text = _query_provider(provider, prompt)
        return _norm_text(text), ""
    except Exception as exc:
        return "", f"{type(exc).__name__}:{exc}"


def build_candidates(
    *,
    spark_dir: Path,
    window_hours: float,
    max_candidates: int,
) -> List[Dict[str, Any]]:
    now_ts = time.time()
    window_s = max(600.0, float(window_hours) * 3600.0)
    cutoff = now_ts - window_s

    quality_rows = _tail_jsonl(spark_dir / "advisor" / "advisory_quality_events.jsonl", 50000)
    ratings_rows = _tail_jsonl(spark_dir / "advisor" / "advisory_quality_ratings.jsonl", 80000)
    engine_rows = _tail_jsonl(spark_dir / "advisory_engine_alpha.jsonl", 80000)
    implicit_rows = _tail_jsonl(spark_dir / "advisor" / "implicit_feedback.jsonl", 80000)

    rated_ids = {_norm_text(r.get("event_id")) for r in ratings_rows if _norm_text(r.get("event_id"))}
    engine_by_trace = _index_by_trace(engine_rows, trace_key="trace_id")
    implicit_by_trace = _index_by_trace(implicit_rows, trace_key="trace_id")

    out: List[Dict[str, Any]] = []
    ordered = sorted(
        quality_rows,
        key=lambda r: _to_ts(r, ("emitted_ts", "recorded_at", "signal_ts")),
        reverse=True,
    )
    for row in ordered:
        emitted_ts = _to_ts(row, ("emitted_ts", "recorded_at", "signal_ts"))
        if emitted_ts <= 0 or emitted_ts < cutoff:
            continue
        event_id = _norm_text(row.get("event_id"))
        if not event_id or event_id in rated_ids:
            continue
        label = _norm_text(row.get("helpfulness_label")).lower()
        if label in KNOWN_HELPFULNESS_LABELS:
            continue
        trace_id = _norm_text(row.get("trace_id"))
        if not trace_id:
            continue

        advice_id = _norm_text(row.get("advice_id"))
        tool = _norm_text(row.get("tool"))
        provider = _norm_text(row.get("provider")) or "unknown"
        timing_bucket = _norm_text(row.get("timing_bucket")).lower()
        impact_score = _safe_float(row.get("impact_score"), 0.0)
        engine_trace_rows = engine_by_trace.get(trace_id, [])
        implicit_signal = _pick_implicit_signal(
            implicit_by_trace.get(trace_id, []),
            tool=tool,
            emitted_ts=emitted_ts,
            advice_id=advice_id,
        )
        post_success = _post_tool_success(engine_trace_rows)
        h_label, h_conf, h_reason = _heuristic_rating(
            implicit_signal=implicit_signal,
            post_success=post_success,
            timing_bucket=timing_bucket,
            impact_score=impact_score,
        )
        out.append(
            {
                "event_id": event_id,
                "trace_id": trace_id,
                "advice_id": advice_id,
                "tool": tool,
                "provider": provider,
                "current_label": label or "unknown",
                "current_confidence": _safe_float(row.get("confidence"), 0.0),
                "timing_bucket": timing_bucket or "unknown",
                "impact_score": impact_score,
                "advice_text": _norm_text(row.get("advice_text"))[:260],
                "implicit_signal": implicit_signal or "none",
                "post_tool_success": post_success,
                "engine_path": [_norm_text(r.get("event")) for r in engine_trace_rows[-14:] if _norm_text(r.get("event"))],
                "heuristic_label": h_label,
                "heuristic_confidence": h_conf,
                "heuristic_reason": h_reason,
            }
        )
        if len(out) >= max(1, int(max_candidates)):
            break
    return out


def build_prompt(*, candidates: List[Dict[str, Any]], window_hours: float) -> str:
    compact = json.dumps(candidates, indent=2, ensure_ascii=False)
    if len(compact) > 52000:
        compact = compact[:52000] + "\n...<truncated>..."
    return (
        "You are acting as a world-class Systems Architect + QA Lead + AGI Engineer.\n\n"
        "Goal:\n"
        "Rate advisory usefulness with context-first rigor, not vanity metrics.\n"
        "Trace each candidate through event capture -> advisory emission -> post-tool outcome.\n\n"
        "Hard constraints:\n"
        "- Be skeptical and falsifiable.\n"
        "- If confidence is low, return label=unknown.\n"
        "- Prefer harmful/unhelpful when evidence shows regression risk.\n"
        "- Notes must explain stage-level root cause in <=25 words.\n\n"
        "Required JSON output schema (no markdown):\n"
        "{\n"
        '  "ratings":[{"event_id":"...", "label":"helpful|unhelpful|harmful|not_followed|unknown", "confidence":0.0, "notes":"..."}],\n'
        '  "system_findings":["..."],\n'
        '  "flow_gaps":[{"stage":"capture|queue|pipeline|memory|meta_ralph|retrieval|advisory|promotion", "issue":"...", "action":"..."}]\n'
        "}\n\n"
        f"Window hours: {window_hours}\n"
        "Candidate contexts:\n"
        f"{compact}\n"
    )


def run_usefulness_cycle(
    *,
    spark_dir: Path,
    window_hours: float = 4.0,
    max_candidates: int = 80,
    run_llm: bool = True,
    providers: str = "auto",
    llm_timeout_s: float = 180.0,
    min_confidence: float = 0.72,
    apply_limit: int = 40,
    source: str = "usefulness_cycle",
) -> Dict[str, Any]:
    advisor_dir = spark_dir / "advisor"
    queue_file = advisor_dir / "usefulness_cycle_queue.jsonl"
    prompt_file = advisor_dir / "usefulness_cycle_prompt.md"
    summary_file = advisor_dir / "usefulness_cycle_summary.json"
    history_file = advisor_dir / "usefulness_cycle_history.jsonl"
    review_file = advisor_dir / f"usefulness_cycle_review_{int(time.time())}.json"

    candidates = build_candidates(
        spark_dir=spark_dir,
        window_hours=window_hours,
        max_candidates=max(1, int(max_candidates)),
    )
    _write_jsonl(queue_file, candidates)
    prompt = build_prompt(candidates=candidates, window_hours=window_hours)
    prompt_file.write_text(prompt, encoding="utf-8")

    provider_attempts: List[Dict[str, Any]] = []
    llm_ratings: List[Dict[str, Any]] = []
    if run_llm and candidates:
        for provider in _resolve_providers(providers):
            started = time.time()
            response, error = _run_provider(provider, prompt, llm_timeout_s)
            parsed = _parse_llm_ratings(response)
            provider_attempts.append(
                {
                    "provider": provider,
                    "ok": bool(parsed),
                    "latency_ms": round((time.time() - started) * 1000.0, 1),
                    "error": error,
                    "parsed_ratings": len(parsed),
                }
            )
            if parsed:
                for row in parsed:
                    item = dict(row)
                    item["provider"] = provider
                    llm_ratings.append(item)
                break

    llm_adjudication_missing = bool(run_llm and candidates and (not llm_ratings))
    heuristic_helpful_downgraded = 0

    by_event: Dict[str, Dict[str, Any]] = {}
    for c in candidates:
        event_id = _norm_text(c.get("event_id"))
        if not event_id:
            continue
        h_label = _norm_text(c.get("heuristic_label")).lower()
        h_conf = max(0.0, min(1.0, _safe_float(c.get("heuristic_confidence"), 0.0)))
        h_notes = _norm_text(c.get("heuristic_reason"))[:200]
        # Avoid mass-positive auto-labeling when provider adjudication fails.
        if llm_adjudication_missing and h_label == "helpful":
            h_conf = min(h_conf, 0.69)
            h_notes = (h_notes + "; downgraded_without_llm_review").strip("; ")
            heuristic_helpful_downgraded += 1
        by_event[event_id] = {
            "event_id": event_id,
            "label": h_label if h_label in VALID_RATING_LABELS else "unknown",
            "confidence": h_conf,
            "notes": h_notes,
            "source_provider": "heuristic",
        }
    for row in llm_ratings:
        event_id = _norm_text(row.get("event_id"))
        if not event_id:
            continue
        by_event[event_id] = {
            "event_id": event_id,
            "label": _norm_text(row.get("label")).lower(),
            "confidence": max(0.0, min(1.0, _safe_float(row.get("confidence"), 0.0))),
            "notes": _norm_text(row.get("notes"))[:200],
            "source_provider": _norm_text(row.get("provider")) or "llm",
        }

    rating_plan = list(by_event.values())
    rating_plan.sort(key=lambda r: (_safe_float(r.get("confidence"), 0.0), _norm_text(r.get("event_id"))), reverse=True)

    applied: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    from .advisory_quality_rating import rate_event

    for row in rating_plan:
        if len(applied) >= max(1, int(apply_limit)):
            skipped.append({"event_id": row.get("event_id"), "reason": "apply_limit"})
            continue
        label = _norm_text(row.get("label")).lower()
        conf = _safe_float(row.get("confidence"), 0.0)
        if label not in VALID_RATING_LABELS or label == "unknown":
            skipped.append({"event_id": row.get("event_id"), "reason": "unknown_label"})
            continue
        if conf < float(min_confidence):
            skipped.append({"event_id": row.get("event_id"), "reason": "below_confidence", "confidence": conf})
            continue
        result = rate_event(
            spark_dir=spark_dir,
            event_id=_norm_text(row.get("event_id")),
            label=label,
            notes=_norm_text(row.get("notes")),
            source=f"{source}:{_norm_text(row.get('source_provider'))[:32]}",
            count_effectiveness=True,
            refresh_spine=False,
        )
        applied.append(
            {
                "event_id": row.get("event_id"),
                "label": label,
                "confidence": conf,
                "ok": bool(result.get("ok")),
            }
        )

    refresh_quality = {}
    refresh_helpfulness = {}
    try:
        from .advisory_quality_spine import run_advisory_quality_spine_default

        quality_out = run_advisory_quality_spine_default(spark_dir=spark_dir, write_files=True)
        if isinstance(quality_out, dict):
            refresh_quality = quality_out.get("summary") if isinstance(quality_out.get("summary"), dict) else {}
    except Exception:
        refresh_quality = {}

    try:
        from .helpfulness_watcher import run_helpfulness_watcher_default

        watch_out = run_helpfulness_watcher_default(spark_dir=spark_dir, write_files=True)
        if isinstance(watch_out, dict):
            refresh_helpfulness = watch_out.get("summary") if isinstance(watch_out.get("summary"), dict) else {}
    except Exception:
        refresh_helpfulness = {}

    review_payload = {
        "generated_at": time.time(),
        "provider_attempts": provider_attempts,
        "llm_ratings": llm_ratings,
    }
    _write_json(review_file, review_payload)

    summary = {
        "ok": True,
        "generated_at": time.time(),
        "window_hours": float(window_hours),
        "candidate_count": len(candidates),
        "applied_count": len(applied),
        "skipped_count": len(skipped),
        "llm_adjudication_missing": bool(llm_adjudication_missing),
        "heuristic_helpful_downgraded": int(heuristic_helpful_downgraded),
        "paths": {
            "queue_file": str(queue_file),
            "prompt_file": str(prompt_file),
            "review_file": str(review_file),
            "summary_file": str(summary_file),
            "history_file": str(history_file),
        },
        "provider_attempts": provider_attempts,
        "applied": applied[:120],
        "skipped": skipped[:120],
        "refresh_quality_summary": refresh_quality,
        "refresh_helpfulness_summary": refresh_helpfulness,
    }
    _write_json(summary_file, summary)
    with history_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return summary
