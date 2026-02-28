"""Emission-native advisory quality spine.

Builds per-emission advisory quality events from runtime artifacts:
- ~/.spark/advisor/recent_advice.jsonl (what was emitted)
- ~/.spark/advisory_engine_alpha.jsonl (alpha trace/session timing)
- ~/.spark/logs/observe_hook_telemetry.jsonl (provider attribution)
- ~/.spark/advisor/implicit_feedback.jsonl (implicit outcomes)
- ~/.spark/advice_feedback.jsonl (explicit outcomes)

Outputs:
- ~/.spark/advisor/advisory_quality_events.jsonl
- ~/.spark/advisor/advisory_quality_summary.json
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AdvisoryQualityConfig:
    spark_dir: Path
    max_recent_rows: int = 10000
    max_alpha_rows: int = 24000
    max_observe_rows: int = 24000
    max_implicit_rows: int = 24000
    max_explicit_rows: int = 24000
    explicit_window_s: int = 6 * 3600
    implicit_window_s: int = 90 * 60
    provider_window_s: int = 180
    write_files: bool = True


@dataclass(frozen=True)
class AdvisoryQualityPaths:
    recent_file: Path
    alpha_file: Path
    observe_file: Path
    implicit_file: Path
    explicit_file: Path
    events_file: Path
    summary_file: Path


def _default_paths(spark_dir: Path) -> AdvisoryQualityPaths:
    return AdvisoryQualityPaths(
        recent_file=spark_dir / "advisor" / "recent_advice.jsonl",
        alpha_file=spark_dir / "advisory_engine_alpha.jsonl",
        observe_file=spark_dir / "logs" / "observe_hook_telemetry.jsonl",
        implicit_file=spark_dir / "advisor" / "implicit_feedback.jsonl",
        explicit_file=spark_dir / "advice_feedback.jsonl",
        events_file=spark_dir / "advisor" / "advisory_quality_events.jsonl",
        summary_file=spark_dir / "advisor" / "advisory_quality_summary.json",
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _norm_tool(value: Any) -> str:
    return _norm_text(value).lower()


def _hash_id(blob: str) -> str:
    return hashlib.sha256(blob.encode("utf-8", errors="ignore")).hexdigest()[:24]


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


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _write_jsonl_atomic(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(str(tmp), str(path))


def _normalize_provider(source: str) -> str:
    s = _norm_text(source).lower()
    if s in {"codex", "openai-codex"}:
        return "codex"
    if s in {"claude", "claude_code"}:
        return "claude"
    if s in {"openclaw", "openclaw_plugin"}:
        return "openclaw"
    return s or "unknown"


def _infer_provider_from_hints(*values: Any) -> str:
    joined = " ".join(_norm_text(v).lower() for v in values if _norm_text(v))
    if not joined:
        return "unknown"
    if "codex" in joined or "openai-codex" in joined:
        return "codex"
    if "claude" in joined:
        return "claude"
    if "openclaw" in joined:
        return "openclaw"
    return "unknown"


def _derive_from_explicit(row: Dict[str, Any]) -> Dict[str, Any]:
    helpful = row.get("helpful")
    followed_raw = row.get("followed")
    followed: Optional[bool]
    if followed_raw is True:
        followed = True
    elif followed_raw is False:
        followed = False
    else:
        followed = None
    status = _norm_text(row.get("status")).lower()

    if status == "harmful":
        return {"label": "harmful", "followed": True, "confidence": 0.99, "judge_source": "explicit_feedback"}
    if helpful is True:
        return {
            "label": "helpful",
            "followed": True if followed is not False else False,
            "confidence": 0.99,
            "judge_source": "explicit_feedback",
        }
    if helpful is False:
        return {
            "label": "unhelpful",
            "followed": True if followed is not False else False,
            "confidence": 0.99,
            "judge_source": "explicit_feedback",
        }
    if status in {"blocked"}:
        return {
            "label": "unhelpful",
            "followed": True if followed is not False else False,
            "confidence": 0.96,
            "judge_source": "explicit_feedback_status",
        }
    if status in {"ignored", "skipped"}:
        return {"label": "not_followed", "followed": False, "confidence": 0.96, "judge_source": "explicit_feedback_status"}
    if status == "acted":
        return {"label": "helpful", "followed": True, "confidence": 0.86, "judge_source": "explicit_feedback_status"}
    if followed is False:
        return {"label": "not_followed", "followed": False, "confidence": 0.92, "judge_source": "explicit_feedback"}
    if followed is True:
        return {"label": "unknown", "followed": True, "confidence": 0.70, "judge_source": "explicit_feedback_partial"}
    return {"label": "unknown", "followed": None, "confidence": 0.60, "judge_source": "explicit_feedback_partial"}


def _derive_from_implicit(signal: str) -> Dict[str, Any]:
    sig = _norm_text(signal).lower()
    if sig == "unhelpful":
        return {"label": "unhelpful", "followed": None, "confidence": 0.74, "judge_source": "implicit_feedback"}
    if sig in {"ignored", "not_followed"}:
        return {"label": "not_followed", "followed": False, "confidence": 0.68, "judge_source": "implicit_feedback"}
    if sig in {"followed", "helpful"}:
        return {"label": "unknown", "followed": True, "confidence": 0.58, "judge_source": "implicit_feedback"}
    return {"label": "unknown", "followed": None, "confidence": 0.40, "judge_source": "implicit_feedback"}


def _usefulness_score(label: str) -> float:
    key = _norm_text(label).lower()
    if key == "helpful":
        return 1.0
    if key == "harmful":
        return 0.0
    if key == "unhelpful":
        return 0.2
    if key == "not_followed":
        return 0.35
    return 0.5


def _timing_bucket(latency_s: Optional[float]) -> str:
    if latency_s is None:
        return "unknown"
    val = float(latency_s)
    if val < 0:
        return "unknown"
    if val <= 60:
        return "right_on_time"
    if val <= 300:
        return "near_time"
    if val <= 1200:
        return "delayed"
    return "stale"


def _timing_score(bucket: str) -> float:
    b = _norm_text(bucket).lower()
    if b == "right_on_time":
        return 1.0
    if b == "near_time":
        return 0.8
    if b == "delayed":
        return 0.55
    if b == "stale":
        return 0.25
    return 0.45


def _build_alpha_trace_index(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        trace_id = _norm_text(row.get("trace_id"))
        if not trace_id:
            continue
        out.setdefault(trace_id, []).append(row)
    for key in list(out.keys()):
        out[key] = sorted(out[key], key=lambda r: _safe_float(r.get("ts"), 0.0))
    return out


def _resolve_alpha_context(
    trace_rows: List[Dict[str, Any]],
    *,
    tool: str,
    approximate_ts: float,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "session_id": "",
        "emitted_ts": 0.0,
        "post_tool_ts": 0.0,
    }
    if not trace_rows:
        return out
    tool_norm = _norm_tool(tool)
    for row in trace_rows:
        sid = _norm_text(row.get("session_id"))
        if sid:
            out["session_id"] = sid
            break

    emitted_candidates = []
    for row in trace_rows:
        if _norm_text(row.get("event")).lower() != "emitted":
            continue
        row_tool = _norm_tool(row.get("tool_name"))
        if row_tool and tool_norm and row_tool != tool_norm:
            continue
        emitted_candidates.append(row)

    if emitted_candidates:
        chosen_emitted = min(
            emitted_candidates,
            key=lambda r: abs(_safe_float(r.get("ts"), 0.0) - float(approximate_ts)),
        )
        out["emitted_ts"] = _safe_float(chosen_emitted.get("ts"), 0.0)

    post_candidates = []
    for row in trace_rows:
        if _norm_text(row.get("event")).lower() != "post_tool_recorded":
            continue
        row_tool = _norm_tool(row.get("tool_name"))
        if row_tool and tool_norm and row_tool != tool_norm:
            continue
        ts = _safe_float(row.get("ts"), 0.0)
        if out["emitted_ts"] > 0 and ts + 1e-6 < out["emitted_ts"]:
            continue
        post_candidates.append(row)

    if post_candidates:
        anchor = out["emitted_ts"] if out["emitted_ts"] > 0 else float(approximate_ts)
        post = min(post_candidates, key=lambda r: abs(_safe_float(r.get("ts"), 0.0) - anchor))
        out["post_tool_ts"] = _safe_float(post.get("ts"), 0.0)
    return out


def _build_observe_session_index(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    out: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for row in rows:
        session_id = _norm_text(row.get("session_id"))
        source = _normalize_provider(_norm_text(row.get("source")))
        ts = _safe_float(row.get("ts"), 0.0)
        if not session_id or not source or ts <= 0:
            continue
        tool = _norm_tool(row.get("tool_name")) or "*"
        out.setdefault(session_id, {}).setdefault(tool, []).append(
            {
                "ts": ts,
                "source": source,
                "event_type": _norm_text(row.get("event_type")).lower(),
            }
        )
    for by_tool in out.values():
        for tool, entries in by_tool.items():
            _ = tool
            by_tool[tool] = sorted(entries, key=lambda e: _safe_float(e.get("ts"), 0.0))
    return out


def _infer_provider(
    observe_index: Dict[str, Dict[str, List[Dict[str, Any]]]],
    *,
    session_id: str,
    tool: str,
    emitted_ts: float,
    provider_window_s: int,
) -> str:
    if not session_id:
        return "unknown"
    by_tool = observe_index.get(session_id) or {}
    tool_norm = _norm_tool(tool) or "*"
    candidates = list(by_tool.get(tool_norm) or [])
    if not candidates:
        candidates.extend(by_tool.get("*") or [])
    if not candidates:
        return "unknown"
    if emitted_ts <= 0:
        return _normalize_provider(_norm_text(candidates[-1].get("source")))
    near = min(candidates, key=lambda r: abs(_safe_float(r.get("ts"), 0.0) - emitted_ts))
    delta_s = abs(_safe_float(near.get("ts"), 0.0) - emitted_ts)
    if delta_s > max(1, int(provider_window_s)):
        return "unknown"
    return _normalize_provider(_norm_text(near.get("source")))


def _build_explicit_indexes(
    rows: Iterable[Dict[str, Any]],
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]]:
    by_advice: Dict[str, List[Dict[str, Any]]] = {}
    by_trace: Dict[str, List[Dict[str, Any]]] = {}
    by_group: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        for aid in row.get("advice_ids") or []:
            key = _norm_text(aid)
            if key:
                by_advice.setdefault(key, []).append(row)
        trace = _norm_text(row.get("trace_id"))
        if trace:
            by_trace.setdefault(trace, []).append(row)
        group = _norm_text(row.get("advisory_group_key"))
        if group:
            by_group.setdefault(group, []).append(row)
    for bucket in (by_advice, by_trace, by_group):
        for key in list(bucket.keys()):
            bucket[key] = sorted(bucket[key], key=lambda r: _safe_float(r.get("created_at"), 0.0))
    return by_advice, by_trace, by_group


def _pick_best_explicit(
    *,
    advice_id: str,
    trace_id: str,
    advisory_group_key: str,
    tool: str,
    emitted_ts: float,
    window_s: int,
    by_advice: Dict[str, List[Dict[str, Any]]],
    by_trace: Dict[str, List[Dict[str, Any]]],
    by_group: Dict[str, List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    candidates.extend(by_advice.get(advice_id, []))
    if trace_id:
        candidates.extend(by_trace.get(trace_id, []))
    if advisory_group_key:
        candidates.extend(by_group.get(advisory_group_key, []))
    if not candidates:
        return None
    best: Optional[Tuple[float, Dict[str, Any]]] = None
    tool_norm = _norm_tool(tool)
    for row in candidates:
        ts = _safe_float(row.get("created_at"), 0.0)
        if ts <= 0:
            continue
        if emitted_ts > 0:
            if ts + 5 < emitted_ts:
                continue
            if ts - emitted_ts > float(window_s):
                continue
        score = 0.0
        if trace_id and _norm_text(row.get("trace_id")) == trace_id:
            score += 7.0
        if advisory_group_key and _norm_text(row.get("advisory_group_key")) == advisory_group_key:
            score += 5.0
        if advice_id and advice_id in [str(x) for x in (row.get("advice_ids") or [])]:
            score += 4.0
        if tool_norm and _norm_tool(row.get("tool")) == tool_norm:
            score += 1.0
        if emitted_ts > 0:
            score += max(0.0, 1.0 - abs(ts - emitted_ts) / max(float(window_s), 1.0))
        if best is None or score > best[0]:
            best = (score, row)
    return best[1] if best else None


def _build_implicit_indexes(
    rows: Iterable[Dict[str, Any]],
) -> Tuple[Dict[Tuple[str, str], List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]]:
    by_trace_tool: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    by_trace: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        trace = _norm_text(row.get("trace_id"))
        if not trace:
            continue
        tool = _norm_tool(row.get("tool"))
        if tool:
            by_trace_tool.setdefault((trace, tool), []).append(row)
        by_trace.setdefault(trace, []).append(row)
    for bucket in (by_trace_tool, by_trace):
        for key in list(bucket.keys()):
            bucket[key] = sorted(bucket[key], key=lambda r: _safe_float(r.get("timestamp"), 0.0))
    return by_trace_tool, by_trace


def _pick_best_implicit(
    *,
    trace_id: str,
    tool: str,
    emitted_ts: float,
    window_s: int,
    by_trace_tool: Dict[Tuple[str, str], List[Dict[str, Any]]],
    by_trace: Dict[str, List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    if not trace_id:
        return None
    tool_norm = _norm_tool(tool)
    rows = list(by_trace_tool.get((trace_id, tool_norm), []))
    if not rows:
        rows = list(by_trace.get(trace_id, []))
    if not rows:
        return None
    candidates = []
    for row in rows:
        ts = _safe_float(row.get("timestamp"), 0.0)
        if ts <= 0:
            continue
        if emitted_ts > 0:
            if ts + 5 < emitted_ts:
                continue
            if ts - emitted_ts > float(window_s):
                continue
        candidates.append(row)
    if not candidates:
        return None
    if emitted_ts <= 0:
        return candidates[0]
    return min(candidates, key=lambda r: abs(_safe_float(r.get("timestamp"), 0.0) - emitted_ts))


def _event_id_for_item(
    *,
    run_id: str,
    trace_id: str,
    tool: str,
    advice_id: str,
    emitted_ts: float,
    item_idx: int,
) -> str:
    blob = "|".join(
        [
            run_id or f"no-run:{emitted_ts:.3f}:{item_idx}",
            trace_id,
            _norm_tool(tool),
            advice_id,
        ]
    )
    return _hash_id(blob)


def _build_events(
    *,
    recent_rows: List[Dict[str, Any]],
    alpha_index: Dict[str, List[Dict[str, Any]]],
    observe_index: Dict[str, Dict[str, List[Dict[str, Any]]]],
    explicit_by_advice: Dict[str, List[Dict[str, Any]]],
    explicit_by_trace: Dict[str, List[Dict[str, Any]]],
    explicit_by_group: Dict[str, List[Dict[str, Any]]],
    implicit_by_trace_tool: Dict[Tuple[str, str], List[Dict[str, Any]]],
    implicit_by_trace: Dict[str, List[Dict[str, Any]]],
    cfg: AdvisoryQualityConfig,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for req in recent_rows:
        advice_ids = req.get("advice_ids")
        if not isinstance(advice_ids, list) or not advice_ids:
            continue
        advice_texts = req.get("advice_texts") if isinstance(req.get("advice_texts"), list) else []
        insight_keys = req.get("insight_keys") if isinstance(req.get("insight_keys"), list) else []
        sources = req.get("sources") if isinstance(req.get("sources"), list) else []
        readiness = req.get("advisory_readiness") if isinstance(req.get("advisory_readiness"), list) else []
        quality = req.get("advisory_quality") if isinstance(req.get("advisory_quality"), list) else []

        tool = _norm_text(req.get("tool"))
        trace_id = _norm_text(req.get("trace_id"))
        run_id = _norm_text(req.get("run_id"))
        route = _norm_text(req.get("route")) or "unknown"
        advisory_group_key = _hash_id("|".join([run_id, trace_id, _norm_tool(tool), ",".join(str(x) for x in advice_ids[:20])]))
        approx_ts = _safe_float(req.get("recorded_at"), 0.0) or _safe_float(req.get("ts"), 0.0)

        trace_rows = alpha_index.get(trace_id, []) if trace_id else []
        alpha_ctx = _resolve_alpha_context(trace_rows, tool=tool, approximate_ts=approx_ts)
        emitted_ts = _safe_float(alpha_ctx.get("emitted_ts"), 0.0) or approx_ts
        post_tool_ts = _safe_float(alpha_ctx.get("post_tool_ts"), 0.0)
        session_id = _norm_text(alpha_ctx.get("session_id"))
        provider_base = _infer_provider(
            observe_index,
            session_id=session_id,
            tool=tool,
            emitted_ts=emitted_ts,
            provider_window_s=cfg.provider_window_s,
        )

        for idx, aid_raw in enumerate(advice_ids[:80]):
            advice_id = _norm_text(aid_raw)
            if not advice_id:
                continue
            explicit_row = _pick_best_explicit(
                advice_id=advice_id,
                trace_id=trace_id,
                advisory_group_key=advisory_group_key,
                tool=tool,
                emitted_ts=emitted_ts,
                window_s=cfg.explicit_window_s,
                by_advice=explicit_by_advice,
                by_trace=explicit_by_trace,
                by_group=explicit_by_group,
            )
            implicit_row = _pick_best_implicit(
                trace_id=trace_id,
                tool=tool,
                emitted_ts=emitted_ts,
                window_s=cfg.implicit_window_s,
                by_trace_tool=implicit_by_trace_tool,
                by_trace=implicit_by_trace,
            )

            explicit_decision = _derive_from_explicit(explicit_row) if explicit_row else None
            implicit_decision = _derive_from_implicit(_norm_text((implicit_row or {}).get("signal"))) if implicit_row else None

            if explicit_decision and _norm_text(explicit_decision.get("label")).lower() != "unknown":
                final = dict(explicit_decision)
            elif explicit_decision and implicit_decision and _norm_text(implicit_decision.get("label")).lower() != "unknown":
                final = dict(implicit_decision)
                final["judge_source"] = "implicit_after_explicit_unknown"
                final["confidence"] = max(0.0, _safe_float(final.get("confidence"), 0.0) - 0.05)
            elif explicit_decision:
                final = dict(explicit_decision)
            elif implicit_decision:
                final = dict(implicit_decision)
            else:
                final = {"label": "unknown", "followed": None, "confidence": 0.2, "judge_source": "no_signal"}

            explicit_ts = _safe_float((explicit_row or {}).get("created_at"), 0.0)
            implicit_ts = _safe_float((implicit_row or {}).get("timestamp"), 0.0)
            signal_ts = min(x for x in [explicit_ts, implicit_ts, post_tool_ts] if x > 0) if (explicit_ts > 0 or implicit_ts > 0 or post_tool_ts > 0) else 0.0
            latency_s = (signal_ts - emitted_ts) if (emitted_ts > 0 and signal_ts > 0) else None
            timing_bucket = _timing_bucket(latency_s)
            timing_score = _timing_score(timing_bucket)
            usefulness_label = _norm_text(final.get("label")).lower() or "unknown"
            usefulness_score = _usefulness_score(usefulness_label)
            impact_score = round((0.65 * usefulness_score) + (0.35 * timing_score), 4)
            source_hint = _norm_text(sources[idx] if idx < len(sources) else "") or "unknown"
            insight_hint = _norm_text(insight_keys[idx] if idx < len(insight_keys) else "")
            text_hint = _norm_text(advice_texts[idx] if idx < len(advice_texts) else "")
            provider_hint = _infer_provider_from_hints(source_hint, insight_hint, text_hint)
            provider = provider_base
            provider_resolution = "observe"
            if provider == "unknown" and provider_hint != "unknown":
                provider = provider_hint
                provider_resolution = "hint"
            elif provider == "unknown":
                provider_resolution = "unknown"

            event = {
                "schema_version": SCHEMA_VERSION,
                "event_id": _event_id_for_item(
                    run_id=run_id,
                    trace_id=trace_id,
                    tool=tool,
                    advice_id=advice_id,
                    emitted_ts=emitted_ts,
                    item_idx=idx,
                ),
                "emitted_ts": emitted_ts,
                "recorded_at": _safe_float(req.get("recorded_at"), 0.0),
                "route": route,
                "tool": tool,
                "trace_id": trace_id or None,
                "run_id": run_id or None,
                "session_id": session_id or None,
                "provider": provider or "unknown",
                "provider_resolution": provider_resolution,
                "advice_id": advice_id,
                "advice_text": _norm_text(advice_texts[idx] if idx < len(advice_texts) else "")[:260],
                "source_hint": source_hint,
                "advisory_readiness": round(max(0.0, min(1.0, _safe_float(readiness[idx] if idx < len(readiness) else 0.0, 0.0))), 4),
                "advisory_unified_score": round(max(0.0, min(1.0, _safe_float((quality[idx] or {}).get("unified_score"), 0.0) if idx < len(quality) and isinstance(quality[idx], dict) else 0.0)), 4),
                "helpfulness_label": usefulness_label,
                "followed": final.get("followed"),
                "judge_source": _norm_text(final.get("judge_source")) or "unknown",
                "judge_confidence": round(max(0.0, min(1.0, _safe_float(final.get("confidence"), 0.0))), 3),
                "explicit_present": bool(explicit_row),
                "implicit_present": bool(implicit_row),
                "explicit_status": _norm_text((explicit_row or {}).get("status")).lower() or None,
                "implicit_signal": _norm_text((implicit_row or {}).get("signal")).lower() or None,
                "timing_bucket": timing_bucket,
                "timing_latency_s": round(float(latency_s), 3) if isinstance(latency_s, float) else None,
                "timing_score": round(timing_score, 4),
                "usefulness_score": round(usefulness_score, 4),
                "impact_score": impact_score,
                "post_tool_ts": post_tool_ts if post_tool_ts > 0 else None,
                "signal_ts": signal_ts if signal_ts > 0 else None,
            }
            events.append(event)
    events.sort(key=lambda r: (_safe_float(r.get("emitted_ts"), 0.0), _norm_text(r.get("event_id"))))
    return events


def _rate_pct(numer: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return round((100.0 * float(numer) / float(denom)), 2)


def _summarize_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    labels: Dict[str, int] = {}
    timing: Dict[str, int] = {}
    providers: Dict[str, Dict[str, Any]] = {}
    by_tool: Dict[str, Dict[str, Any]] = {}
    by_route: Dict[str, Dict[str, Any]] = {}
    impact_sum = 0.0

    for row in events:
        label = _norm_text(row.get("helpfulness_label")).lower() or "unknown"
        labels[label] = labels.get(label, 0) + 1

        tb = _norm_text(row.get("timing_bucket")).lower() or "unknown"
        timing[tb] = timing.get(tb, 0) + 1

        provider = _normalize_provider(_norm_text(row.get("provider")))
        p = providers.setdefault(
            provider,
            {"events": 0, "impact_sum": 0.0, "known_helpfulness": 0, "helpful": 0, "right_on_time": 0},
        )
        p["events"] += 1
        p["impact_sum"] += _safe_float(row.get("impact_score"), 0.0)
        if label in {"helpful", "unhelpful", "harmful"}:
            p["known_helpfulness"] += 1
        if label == "helpful":
            p["helpful"] += 1
        if tb == "right_on_time":
            p["right_on_time"] += 1

        tool = _norm_text(row.get("tool")) or "unknown"
        t = by_tool.setdefault(tool, {"events": 0, "impact_sum": 0.0, "helpful": 0})
        t["events"] += 1
        t["impact_sum"] += _safe_float(row.get("impact_score"), 0.0)
        if label == "helpful":
            t["helpful"] += 1

        route = _norm_text(row.get("route")) or "unknown"
        r = by_route.setdefault(route, {"events": 0, "impact_sum": 0.0, "helpful": 0})
        r["events"] += 1
        r["impact_sum"] += _safe_float(row.get("impact_score"), 0.0)
        if label == "helpful":
            r["helpful"] += 1

        impact_sum += _safe_float(row.get("impact_score"), 0.0)

    total = len(events)
    acted_total = labels.get("helpful", 0) + labels.get("unhelpful", 0) + labels.get("harmful", 0)
    known_total = acted_total + labels.get("not_followed", 0)
    unknown_total = labels.get("unknown", 0)
    avg_impact = round(impact_sum / max(total, 1), 4) if total else 0.0

    provider_summary: Dict[str, Any] = {}
    for provider, stats in providers.items():
        ev = int(stats.get("events", 0))
        known = int(stats.get("known_helpfulness", 0))
        helpful = int(stats.get("helpful", 0))
        right = int(stats.get("right_on_time", 0))
        provider_summary[provider] = {
            "events": ev,
            "avg_impact_score": round(_safe_float(stats.get("impact_sum"), 0.0) / max(ev, 1), 4),
            "known_helpfulness": known,
            "helpful_rate_pct": _rate_pct(helpful, max(known, 1) if known > 0 else 0),
            "right_on_time_rate_pct": _rate_pct(right, max(ev, 1) if ev > 0 else 0),
        }

    tool_top = sorted(by_tool.items(), key=lambda kv: (-_safe_int(kv[1].get("events"), 0), kv[0]))[:12]
    route_summary: Dict[str, Any] = {}
    for route, stats in by_route.items():
        ev = int(stats.get("events", 0))
        route_summary[route] = {
            "events": ev,
            "avg_impact_score": round(_safe_float(stats.get("impact_sum"), 0.0) / max(ev, 1), 4),
            "helpful_rate_pct": _rate_pct(int(stats.get("helpful", 0)), max(ev, 1) if ev > 0 else 0),
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.time(),
        "total_events": total,
        "labels": labels,
        "timing": timing,
        "known_helpfulness_total": known_total,
        "acted_total": acted_total,
        "unknown_total": unknown_total,
        "helpful_rate_pct": _rate_pct(labels.get("helpful", 0), acted_total if acted_total > 0 else 0),
        "unknown_rate_pct": _rate_pct(unknown_total, total if total > 0 else 0),
        "right_on_time_rate_pct": _rate_pct(timing.get("right_on_time", 0), total if total > 0 else 0),
        "avg_impact_score": avg_impact,
        "provider_summary": provider_summary,
        "route_summary": route_summary,
        "top_tools": [
            {
                "tool": tool,
                "events": int(stats.get("events", 0)),
                "avg_impact_score": round(_safe_float(stats.get("impact_sum"), 0.0) / max(int(stats.get("events", 0)), 1), 4),
                "helpful_rate_pct": _rate_pct(int(stats.get("helpful", 0)), int(stats.get("events", 0))),
            }
            for tool, stats in tool_top
        ],
    }


def run_advisory_quality_spine(cfg: AdvisoryQualityConfig) -> Dict[str, Any]:
    paths = _default_paths(cfg.spark_dir)

    recent_rows = _tail_jsonl(paths.recent_file, cfg.max_recent_rows)
    alpha_rows = _tail_jsonl(paths.alpha_file, cfg.max_alpha_rows)
    observe_rows = _tail_jsonl(paths.observe_file, cfg.max_observe_rows)
    implicit_rows = _tail_jsonl(paths.implicit_file, cfg.max_implicit_rows)
    explicit_rows = _tail_jsonl(paths.explicit_file, cfg.max_explicit_rows)

    recent_rows = [
        r for r in recent_rows
        if bool(r.get("delivered", True))
        and isinstance(r.get("advice_ids"), list)
        and len(r.get("advice_ids") or []) > 0
    ]

    alpha_index = _build_alpha_trace_index(alpha_rows)
    observe_index = _build_observe_session_index(observe_rows)
    explicit_by_advice, explicit_by_trace, explicit_by_group = _build_explicit_indexes(explicit_rows)
    implicit_by_trace_tool, implicit_by_trace = _build_implicit_indexes(implicit_rows)

    events = _build_events(
        recent_rows=recent_rows,
        alpha_index=alpha_index,
        observe_index=observe_index,
        explicit_by_advice=explicit_by_advice,
        explicit_by_trace=explicit_by_trace,
        explicit_by_group=explicit_by_group,
        implicit_by_trace_tool=implicit_by_trace_tool,
        implicit_by_trace=implicit_by_trace,
        cfg=cfg,
    )
    summary = _summarize_events(events)

    if cfg.write_files:
        _write_jsonl_atomic(paths.events_file, events)
        _write_json_atomic(paths.summary_file, summary)

    return {
        "ok": True,
        "paths": {
            "events_file": str(paths.events_file),
            "summary_file": str(paths.summary_file),
        },
        "inputs": {
            "recent_rows": len(recent_rows),
            "alpha_rows": len(alpha_rows),
            "observe_rows": len(observe_rows),
            "implicit_rows": len(implicit_rows),
            "explicit_rows": len(explicit_rows),
        },
        "summary": summary,
        "events": events,
    }


def run_advisory_quality_spine_default(
    *,
    spark_dir: Optional[Path] = None,
    max_recent_rows: int = 10000,
    max_alpha_rows: int = 24000,
    max_observe_rows: int = 24000,
    max_implicit_rows: int = 24000,
    max_explicit_rows: int = 24000,
    explicit_window_s: int = 6 * 3600,
    implicit_window_s: int = 90 * 60,
    provider_window_s: int = 180,
    write_files: bool = True,
) -> Dict[str, Any]:
    cfg = AdvisoryQualityConfig(
        spark_dir=(spark_dir or (Path.home() / ".spark")),
        max_recent_rows=max_recent_rows,
        max_alpha_rows=max_alpha_rows,
        max_observe_rows=max_observe_rows,
        max_implicit_rows=max_implicit_rows,
        max_explicit_rows=max_explicit_rows,
        explicit_window_s=explicit_window_s,
        implicit_window_s=implicit_window_s,
        provider_window_s=provider_window_s,
        write_files=write_files,
    )
    return run_advisory_quality_spine(cfg)
