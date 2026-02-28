#!/usr/bin/env python3
"""Generate a context-rich advisory self-review report.

This script preserves the original trace-backed metrics and adds:
- Stage-by-stage context summaries (event capture -> promotion)
- Trace storybook (wins/misses with evidence paths)
- Hard-question external review prompt bundle
- Optional external LLM adjudication pass for context-heavy critiques
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

SPARK_DIR = Path.home() / ".spark"
ADVISORY_ENGINE_LOG = SPARK_DIR / "advisory_engine_alpha.jsonl"
OBSERVE_TELEMETRY_LOG = SPARK_DIR / "logs" / "observe_hook_telemetry.jsonl"
QUALITY_EVENTS_LOG = SPARK_DIR / "advisor" / "advisory_quality_events.jsonl"
RETRIEVAL_ROUTER_LOG = SPARK_DIR / "advisor" / "retrieval_router.jsonl"
IMPLICIT_FEEDBACK_LOG = SPARK_DIR / "advisor" / "implicit_feedback.jsonl"
EXPLICIT_FEEDBACK_LOG = SPARK_DIR / "advice_feedback.jsonl"
PROMOTION_LOG = SPARK_DIR / "promotion_log.jsonl"
QUEUE_EVENTS_LOG = SPARK_DIR / "queue" / "events.jsonl"
EIDOS_DB = SPARK_DIR / "eidos.db"
EVIDENCE_DB = SPARK_DIR / "evidence.db"
GATE_STATE_FILE = SPARK_DIR / "advisory_review_gates_state.json"
GATE_ALERTS_FILE = SPARK_DIR / "alerts" / "advisory_context_alerts.jsonl"

ALPHA_SUPPRESSION_EVENTS = {
    "gate_no_emit",
    "emit_suppressed",
    "global_dedupe_suppressed",
    "context_repeat_blocked",
    "dedupe_empty",
    "dedupe_gate_empty",
}
NONBENCH_TRACE_EXCLUDE_PREFIXES = [
    "advisory-bench-",
    "arena:",
    "delta-",
]
KNOWN_NEGATIVE_LABELS = {"unhelpful", "harmful", "not_followed"}
KNOWN_POSITIVE_LABELS = {"helpful"}
DECISION_BLOCK_EVENTS = {
    "gate_no_emit",
    "dedupe_empty",
    "dedupe_gate_empty",
    "question_like_blocked",
    "context_repeat_blocked",
    "text_repeat_blocked",
    "global_dedupe_suppressed",
    "emit_suppressed",
    "no_advice",
    "engine_error",
}


def _to_ts(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return float(text)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def _to_iso(ts: float) -> str:
    if ts <= 0:
        return "unknown"
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


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


def _load_json(path: Path) -> Any:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _load_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _tail_jsonl(path: Path, max_rows: int) -> List[Dict[str, Any]]:
    if not path.exists() or max_rows <= 0:
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-max_rows:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _pct(n: float, d: float) -> float:
    if d <= 0:
        return 0.0
    return round((n / d) * 100.0, 2)


def _row_ts(row: Dict[str, Any], keys: Sequence[str]) -> float:
    for key in keys:
        ts = _to_ts(row.get(key))
        if ts > 0:
            return ts
    return 0.0


def _rows_in_window(
    rows: Iterable[Dict[str, Any]],
    *,
    now_ts: float,
    window_s: float,
    ts_keys: Sequence[str],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        ts = _row_ts(row, ts_keys)
        if ts <= 0:
            continue
        if (now_ts - ts) <= window_s:
            enriched = dict(row)
            enriched["_ts"] = ts
            out.append(enriched)
    return out


def summarize_recent_advice(
    path: Path,
    window_s: float,
    now_ts: float,
    *,
    exclude_trace_prefixes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    rows = []
    excluded = 0
    prefixes = [str(p or "") for p in (exclude_trace_prefixes or []) if str(p or "")]
    for row in _load_jsonl(path):
        ts = _to_ts(row.get("ts"))
        if ts > 0 and (now_ts - ts) <= window_s:
            trace_id = str(row.get("trace_id") or "")
            if prefixes and trace_id and any(trace_id.startswith(p) for p in prefixes):
                excluded += 1
                continue
            rows.append(row)

    item_total = 0
    source_counts: Counter[str] = Counter()
    text_counts: Counter[str] = Counter()
    trace_rows = 0

    for row in rows:
        if row.get("trace_id"):
            trace_rows += 1
        for src in (row.get("sources") or []):
            source_counts[str(src or "unknown")] += 1
            item_total += 1
        for text in (row.get("advice_texts") or []):
            txt = str(text or "").strip()
            if txt:
                text_counts[txt] += 1

    repeated = []
    for text, count in text_counts.most_common(12):
        repeated.append(
            {
                "count": int(count),
                "share_pct_of_items": _pct(count, item_total),
                "text": text,
            }
        )

    trace_examples = []
    seen = set()
    rows_sorted = sorted(rows, key=lambda r: _to_ts(r.get("ts")), reverse=True)
    for row in rows_sorted:
        trace_id = str(row.get("trace_id") or "").strip()
        if not trace_id or trace_id in seen:
            continue
        seen.add(trace_id)
        ts = _to_ts(row.get("ts"))
        iso = _to_iso(ts)
        advice_texts = row.get("advice_texts") or []
        sources = row.get("sources") or []
        trace_examples.append(
            {
                "trace_id": trace_id,
                "tool": row.get("tool"),
                "source": sources[0] if sources else None,
                "advice_preview": (str(advice_texts[0]) if advice_texts else "")[:160],
                "ts": iso,
            }
        )
        if len(trace_examples) >= 10:
            break

    return {
        "rows": int(len(rows)),
        "excluded": int(excluded),
        "trace_rows": int(trace_rows),
        "trace_coverage_pct": _pct(trace_rows, len(rows)),
        "item_total": int(item_total),
        "sources": dict(source_counts.most_common()),
        "repeated_texts": repeated,
        "trace_examples": trace_examples,
    }


def summarize_engine(path: Path, window_s: float, now_ts: float) -> Dict[str, Any]:
    rows = []
    for row in _load_jsonl(path):
        ts = _to_ts(row.get("ts"))
        if ts > 0 and (now_ts - ts) <= window_s:
            rows.append(row)

    events = Counter(str(r.get("event") or "unknown") for r in rows)
    routes = Counter(str(r.get("route") or "unknown") for r in rows)
    suppression_events = sum(int(events.get(ev, 0) or 0) for ev in ALPHA_SUPPRESSION_EVENTS)
    suppression_share_pct = _pct(suppression_events, len(rows))
    trace_rows = sum(1 for r in rows if r.get("trace_id"))
    suppression_breakdown = {
        ev: int(events.get(ev, 0) or 0)
        for ev in sorted(ALPHA_SUPPRESSION_EVENTS)
        if int(events.get(ev, 0) or 0) > 0
    }

    return {
        "rows": int(len(rows)),
        "trace_rows": int(trace_rows),
        "trace_coverage_pct": _pct(trace_rows, len(rows)),
        "events": dict(events),
        "routes": dict(routes),
        "suppression_events": int(suppression_events),
        "suppression_share_pct": suppression_share_pct,
        "suppression_breakdown": suppression_breakdown,
    }


def summarize_outcomes(path: Path, window_s: float, now_ts: float) -> Dict[str, Any]:
    if not path.exists():
        return {
            "records": 0,
            "strict_action_rate": None,
            "strict_effectiveness_rate": None,
            "bad_records": [],
            "trace_mismatch_count": 0,
            "top_trace_clusters": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {
            "records": 0,
            "strict_action_rate": None,
            "strict_effectiveness_rate": None,
            "bad_records": [],
            "trace_mismatch_count": 0,
            "top_trace_clusters": [],
        }

    recs = data.get("records") or []
    recent = []
    for rec in recs:
        ts = _to_ts(rec.get("retrieved_at"))
        if ts > 0 and (now_ts - ts) <= window_s:
            recent.append(rec)

    acted = len(recent)
    strict = 0
    strict_good = 0
    strict_outcome_known = 0
    mismatch_count = 0
    bad_records = []
    clusters: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for rec in recent:
        source = str(rec.get("source") or "unknown")
        outcome = str(rec.get("outcome") or "unknown")
        trace_id = str(rec.get("trace_id") or "").strip()
        out_trace = str(rec.get("outcome_trace_id") or "").strip()
        if trace_id:
            clusters[trace_id].append(rec)
        if trace_id and out_trace and trace_id != out_trace:
            mismatch_count += 1

        is_strict = bool(trace_id and out_trace and trace_id == out_trace)
        if is_strict:
            strict += 1
            if outcome in {"good", "bad"}:
                strict_outcome_known += 1
            if outcome == "good":
                strict_good += 1

        if outcome == "bad":
            bad_records.append(
                {
                    "trace_id": trace_id or None,
                    "source": source,
                    "insight_key": rec.get("insight_key"),
                    "learning_content": str(rec.get("learning_content") or "")[:180],
                }
            )

    cluster_rows = []
    for trace_id, items in sorted(clusters.items(), key=lambda kv: len(kv[1]), reverse=True)[:10]:
        src_counts = Counter(str(i.get("source") or "unknown") for i in items)
        outcome_counts = Counter(str(i.get("outcome") or "unknown") for i in items)
        cluster_rows.append(
            {
                "trace_id": trace_id,
                "count": len(items),
                "sources": dict(src_counts),
                "outcomes": dict(outcome_counts),
            }
        )

    strict_action_rate = round(strict / acted, 4) if acted > 0 else None
    strict_effectiveness_rate = (
        round(strict_good / strict_outcome_known, 4) if strict_outcome_known > 0 else None
    )

    return {
        "records": acted,
        "strict_action_rate": strict_action_rate,
        "strict_effectiveness_rate": strict_effectiveness_rate,
        "bad_records": bad_records[:10],
        "trace_mismatch_count": int(mismatch_count),
        "top_trace_clusters": cluster_rows,
    }


def _sample_rows(rows: List[Dict[str, Any]], limit: int, keys: Sequence[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: _safe_float(r.get("_ts"), 0.0), reverse=True)[: max(0, int(limit))]:
        item: Dict[str, Any] = {"ts": _to_iso(_safe_float(row.get("_ts"), 0.0))}
        for key in keys:
            value = row.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                item[key] = value[:220]
            elif isinstance(value, (int, float, bool)):
                item[key] = value
            else:
                item[key] = str(value)[:220]
        out.append(item)
    return out


def _sqlite_count_tables(db_path: Path, tables: Sequence[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if not db_path.exists():
        for table in tables:
            out[table] = 0
        return out
    try:
        conn = sqlite3.connect(str(db_path))
    except Exception:
        for table in tables:
            out[table] = 0
        return out
    try:
        cur = conn.cursor()
        for table in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                row = cur.fetchone() or (0,)
                out[table] = _safe_int(row[0], 0)
            except Exception:
                out[table] = 0
    finally:
        conn.close()
    return out


def summarize_stage_context(
    *,
    spark_dir: Path,
    now_ts: float,
    window_s: float,
    stage_sample_limit: int,
) -> Dict[str, Any]:
    observe_log = spark_dir / "logs" / "observe_hook_telemetry.jsonl"
    queue_events_log = spark_dir / "queue" / "events.jsonl"
    retrieval_router_log = spark_dir / "advisor" / "retrieval_router.jsonl"
    quality_events_log = spark_dir / "advisor" / "advisory_quality_events.jsonl"
    promotion_log = spark_dir / "promotion_log.jsonl"
    eidos_db = spark_dir / "eidos.db"
    evidence_db = spark_dir / "evidence.db"

    observe_rows = _rows_in_window(
        _tail_jsonl(observe_log, 80000),
        now_ts=now_ts,
        window_s=window_s,
        ts_keys=("ts", "timestamp"),
    )
    observe_sources = Counter(_norm_text(r.get("source")) or "unknown" for r in observe_rows)
    observe_tools = Counter(_norm_text(r.get("tool_name")) or "unknown" for r in observe_rows)
    observe_events = Counter(_norm_text(r.get("event_type")) or "unknown" for r in observe_rows)
    stage_1 = {
        "name": "Event Capture",
        "observed_rows": len(observe_rows),
        "source_mix": dict(observe_sources.most_common(8)),
        "tool_mix": dict(observe_tools.most_common(8)),
        "event_mix": dict(observe_events.most_common(8)),
        "samples": _sample_rows(
            observe_rows,
            stage_sample_limit,
            ("source", "event_type", "tool_name", "trace_id", "session_id"),
        ),
    }

    queue_state = _load_json(spark_dir / "queue" / "state.json") or {}
    queue_events_rows = _tail_jsonl(queue_events_log, 3000)
    queue_tools = Counter(_norm_text(r.get("tool_name")) or _norm_text(r.get("tool")) or "unknown" for r in queue_events_rows)
    stage_2 = {
        "name": "Queue",
        "head_bytes": _safe_int((queue_state or {}).get("head_bytes"), 0),
        "queue_events_sampled": len(queue_events_rows),
        "tool_mix": dict(queue_tools.most_common(8)),
        "samples": _sample_rows(queue_events_rows, stage_sample_limit, ("tool_name", "tool", "kind", "trace_id")),
    }

    pipeline_state = _load_json(spark_dir / "pipeline_state.json") or {}
    pipeline_metrics = _load_json(spark_dir / "pipeline_metrics.json")
    recent_cycles = pipeline_metrics[-5:] if isinstance(pipeline_metrics, list) else []
    stage_3 = {
        "name": "Pipeline",
        "total_events_processed": _safe_int((pipeline_state or {}).get("total_events_processed"), 0),
        "total_insights_created": _safe_int((pipeline_state or {}).get("total_insights_created"), 0),
        "last_processing_rate": _safe_float((pipeline_state or {}).get("last_processing_rate"), 0.0),
        "recent_cycles": recent_cycles,
    }

    pending_memory = _load_json(spark_dir / "pending_memory.json") or {}
    pending_items = pending_memory.get("items") if isinstance(pending_memory, dict) else []
    if not isinstance(pending_items, list):
        pending_items = []
    pending_categories = Counter(_norm_text(x.get("category")) or "unknown" for x in pending_items if isinstance(x, dict))
    stage_4 = {
        "name": "Memory Capture",
        "pending_count": len(pending_items),
        "pending_category_mix": dict(pending_categories.most_common(8)),
        "samples": [
            {
                "category": _norm_text(x.get("category")) or "unknown",
                "score": _safe_float(x.get("score"), 0.0),
                "text_preview": _norm_text(x.get("text"))[:180],
            }
            for x in pending_items[: max(0, int(stage_sample_limit))]
            if isinstance(x, dict)
        ],
    }

    stage_5 = {
        "name": "Quality Gate (Meta-Ralph)",
        "outcomes": summarize_outcomes(
            spark_dir / "meta_ralph" / "outcome_tracking.json",
            window_s=window_s,
            now_ts=now_ts,
        ),
    }

    eidos_counts = _sqlite_count_tables(
        eidos_db,
        ("episodes", "steps", "distillations", "distillations_archive", "policies"),
    )
    evidence_counts = _sqlite_count_tables(evidence_db, ("evidence",))
    stage_6 = {
        "name": "Distillation / EIDOS",
        "eidos_counts": eidos_counts,
        "evidence_counts": evidence_counts,
        "curriculum_state": _load_json(spark_dir / "eidos_curriculum_state.json") or {},
    }

    retrieval_rows = _rows_in_window(
        _tail_jsonl(retrieval_router_log, 12000),
        now_ts=now_ts,
        window_s=window_s,
        ts_keys=("ts", "created_at", "recorded_at"),
    )
    retrieval_route = Counter(_norm_text(r.get("route")) or "unknown" for r in retrieval_rows)
    retrieval_reason = Counter(_norm_text(r.get("reason")) or "unknown" for r in retrieval_rows)
    stage_7 = {
        "name": "Retrieval",
        "rows": len(retrieval_rows),
        "route_mix": dict(retrieval_route.most_common(10)),
        "reason_mix": dict(retrieval_reason.most_common(10)),
        "samples": _sample_rows(
            retrieval_rows,
            stage_sample_limit,
            ("trace_id", "route", "reason", "tool", "provider"),
        ),
    }

    quality_rows = _rows_in_window(
        _tail_jsonl(quality_events_log, 20000),
        now_ts=now_ts,
        window_s=window_s,
        ts_keys=("emitted_ts", "recorded_at", "signal_ts"),
    )
    quality_labels = Counter(_norm_text(r.get("helpfulness_label")).lower() or "unknown" for r in quality_rows)
    quality_provider = Counter(_norm_text(r.get("provider")) or "unknown" for r in quality_rows)
    quality_timing = Counter(_norm_text(r.get("timing_bucket")).lower() or "unknown" for r in quality_rows)
    quality_known = quality_labels.get("helpful", 0) + quality_labels.get("unhelpful", 0) + quality_labels.get("harmful", 0)
    stage_8 = {
        "name": "Advisory",
        "quality_events": len(quality_rows),
        "label_mix": dict(quality_labels),
        "provider_mix": dict(quality_provider.most_common(8)),
        "timing_mix": dict(quality_timing),
        "known_helpfulness": int(quality_known),
        "helpful_rate_pct": _pct(float(quality_labels.get("helpful", 0)), float(quality_known)),
        "samples": _sample_rows(
            quality_rows,
            stage_sample_limit,
            ("trace_id", "provider", "tool", "helpfulness_label", "impact_score", "timing_bucket"),
        ),
    }

    promotion_rows = _rows_in_window(
        _tail_jsonl(promotion_log, 5000),
        now_ts=now_ts,
        window_s=window_s,
        ts_keys=("ts", "created_at", "timestamp"),
    )
    promotion_targets = Counter(_norm_text(r.get("target")) or "unknown" for r in promotion_rows)
    promotion_results = Counter(_norm_text(r.get("result")) or "unknown" for r in promotion_rows)
    stage_9 = {
        "name": "Promotion",
        "rows": len(promotion_rows),
        "target_mix": dict(promotion_targets),
        "result_mix": dict(promotion_results),
        "samples": _sample_rows(promotion_rows, stage_sample_limit, ("key", "target", "result", "reason")),
    }

    return {
        "stage_1_event_capture": stage_1,
        "stage_2_queue": stage_2,
        "stage_3_pipeline": stage_3,
        "stage_4_memory_capture": stage_4,
        "stage_5_quality_gate": stage_5,
        "stage_6_distillation": stage_6,
        "stage_7_retrieval": stage_7,
        "stage_8_advisory": stage_8,
        "stage_9_promotion": stage_9,
    }


def _index_by_trace(rows: Iterable[Dict[str, Any]], key_names: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        trace_id = ""
        for key in key_names:
            v = _norm_text(row.get(key))
            if v:
                trace_id = v
                break
        if not trace_id:
            continue
        out[trace_id].append(dict(row))
    return out


def _build_trace_story(
    event: Dict[str, Any],
    *,
    engine_by_trace: Dict[str, List[Dict[str, Any]]],
    explicit_by_trace: Dict[str, List[Dict[str, Any]]],
    implicit_by_trace: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    trace_id = _norm_text(event.get("trace_id"))
    advice_id = _norm_text(event.get("advice_id"))
    tool = _norm_text(event.get("tool")) or "unknown"
    label = _norm_text(event.get("helpfulness_label")).lower() or "unknown"
    impact = _safe_float(event.get("impact_score"), 0.0)

    engine_rows = sorted(
        engine_by_trace.get(trace_id, []),
        key=lambda r: _to_ts(r.get("ts")),
    )
    engine_path = [_norm_text(r.get("event")) or "unknown" for r in engine_rows[:16]]
    explicit_rows = explicit_by_trace.get(trace_id, [])
    implicit_rows = implicit_by_trace.get(trace_id, [])

    explicit_statuses = [
        {
            "status": _norm_text(r.get("status")) or ("acted" if r.get("followed") is True else "unknown"),
            "helpful": r.get("helpful"),
            "notes": _norm_text(r.get("notes"))[:140],
        }
        for r in explicit_rows[:6]
    ]
    implicit_signals = [_norm_text(r.get("signal")) or "unknown" for r in implicit_rows[:8]]

    context_notes: List[str] = []
    if any(ev in ALPHA_SUPPRESSION_EVENTS for ev in engine_path):
        context_notes.append("suppression_present_in_trace")
    if not explicit_statuses:
        context_notes.append("missing_explicit_feedback")
    if not implicit_signals:
        context_notes.append("missing_implicit_feedback")
    if label in KNOWN_NEGATIVE_LABELS and impact >= 0.7:
        context_notes.append("high_impact_negative_event")
    if label in KNOWN_POSITIVE_LABELS and "post_tool_recorded" in engine_path:
        context_notes.append("timely_positive_followthrough")

    return {
        "trace_id": trace_id or "unknown",
        "advice_id": advice_id or "unknown",
        "tool": tool,
        "provider": _norm_text(event.get("provider")) or "unknown",
        "label": label,
        "impact_score": round(impact, 4),
        "timing_bucket": _norm_text(event.get("timing_bucket")).lower() or "unknown",
        "advice_preview": _norm_text(event.get("advice_text"))[:180],
        "emitted_at": _to_iso(_safe_float(event.get("emitted_ts"), 0.0)),
        "engine_path": engine_path,
        "explicit_feedback": explicit_statuses,
        "implicit_signals": implicit_signals,
        "context_notes": context_notes,
    }


def build_trace_storybook(
    *,
    spark_dir: Path,
    now_ts: float,
    window_s: float,
    trace_story_limit: int,
) -> Dict[str, Any]:
    quality_events_log = spark_dir / "advisor" / "advisory_quality_events.jsonl"
    advisory_engine_log = spark_dir / "advisory_engine_alpha.jsonl"
    explicit_feedback_log = spark_dir / "advice_feedback.jsonl"
    implicit_feedback_log = spark_dir / "advisor" / "implicit_feedback.jsonl"

    quality_rows = _rows_in_window(
        _tail_jsonl(quality_events_log, 24000),
        now_ts=now_ts,
        window_s=window_s,
        ts_keys=("emitted_ts", "recorded_at", "signal_ts"),
    )
    quality_rows = [r for r in quality_rows if _norm_text(r.get("trace_id"))]
    quality_rows_sorted = sorted(quality_rows, key=lambda r: _safe_float(r.get("_ts"), 0.0), reverse=True)

    engine_rows = _rows_in_window(
        _tail_jsonl(advisory_engine_log, 50000),
        now_ts=now_ts,
        window_s=max(window_s, 24 * 3600),
        ts_keys=("ts",),
    )
    explicit_rows = _rows_in_window(
        _tail_jsonl(explicit_feedback_log, 20000),
        now_ts=now_ts,
        window_s=max(window_s, 24 * 3600),
        ts_keys=("created_at",),
    )
    implicit_rows = _rows_in_window(
        _tail_jsonl(implicit_feedback_log, 20000),
        now_ts=now_ts,
        window_s=max(window_s, 24 * 3600),
        ts_keys=("timestamp", "created_at"),
    )

    engine_by_trace = _index_by_trace(engine_rows, ("trace_id",))
    explicit_by_trace = _index_by_trace(explicit_rows, ("trace_id",))
    implicit_by_trace = _index_by_trace(implicit_rows, ("trace_id",))

    wins: List[Dict[str, Any]] = []
    misses: List[Dict[str, Any]] = []
    seen_trace: set[str] = set()

    max_each = max(2, int(trace_story_limit // 2))
    for event in quality_rows_sorted:
        trace_id = _norm_text(event.get("trace_id"))
        if not trace_id or trace_id in seen_trace:
            continue
        label = _norm_text(event.get("helpfulness_label")).lower()
        if label in KNOWN_POSITIVE_LABELS and len(wins) < max_each:
            wins.append(
                _build_trace_story(
                    event,
                    engine_by_trace=engine_by_trace,
                    explicit_by_trace=explicit_by_trace,
                    implicit_by_trace=implicit_by_trace,
                )
            )
            seen_trace.add(trace_id)
            continue
        if label in KNOWN_NEGATIVE_LABELS and len(misses) < max_each:
            misses.append(
                _build_trace_story(
                    event,
                    engine_by_trace=engine_by_trace,
                    explicit_by_trace=explicit_by_trace,
                    implicit_by_trace=implicit_by_trace,
                )
            )
            seen_trace.add(trace_id)
        if len(wins) >= max_each and len(misses) >= max_each:
            break

    return {
        "total_quality_rows": len(quality_rows_sorted),
        "stories_selected": len(wins) + len(misses),
        "wins": wins,
        "misses": misses,
    }


def derive_passed_and_surpassed(
    *,
    summary: Dict[str, Any],
    stage_context: Dict[str, Any],
) -> Dict[str, Any]:
    passed: List[str] = []
    surpassed: List[str] = []

    ra = summary.get("recent_advice_nonbench") or {}
    engine = summary.get("engine") or {}
    outcomes = summary.get("outcomes") or {}
    advisory = (stage_context.get("stage_8_advisory") or {}) if isinstance(stage_context, dict) else {}

    trace_cov = _safe_float(ra.get("trace_coverage_pct"), 0.0)
    if trace_cov >= 60.0:
        passed.append(f"Non-benchmark advisory trace coverage passed baseline ({trace_cov:.1f}%).")
    if trace_cov >= 85.0:
        surpassed.append(f"Non-benchmark advisory trace coverage surpassed stretch target ({trace_cov:.1f}%).")

    suppression_share = _safe_float(engine.get("suppression_share_pct"), 100.0)
    if suppression_share <= 55.0:
        passed.append(f"Suppression share passed stability baseline ({suppression_share:.1f}%).")
    if suppression_share <= 35.0:
        surpassed.append(f"Suppression share surpassed quality target ({suppression_share:.1f}%).")

    strict_effectiveness = outcomes.get("strict_effectiveness_rate")
    if isinstance(strict_effectiveness, (int, float)) and strict_effectiveness >= 0.55:
        passed.append(f"Strict effectiveness passed baseline ({float(strict_effectiveness):.2f}).")
    if isinstance(strict_effectiveness, (int, float)) and strict_effectiveness >= 0.75:
        surpassed.append(f"Strict effectiveness surpassed target ({float(strict_effectiveness):.2f}).")

    helpful_rate = _safe_float(advisory.get("helpful_rate_pct"), 0.0)
    if helpful_rate >= 45.0:
        passed.append(f"Known helpful-rate passed baseline ({helpful_rate:.1f}%).")
    if helpful_rate >= 65.0:
        surpassed.append(f"Known helpful-rate surpassed stretch target ({helpful_rate:.1f}%).")

    if not passed:
        passed.append("No major stage passed baseline in this window; treat as degraded context.")

    return {
        "passed": passed,
        "surpassed": surpassed,
    }


def _compact_for_prompt(payload: Dict[str, Any], max_chars: int = 28000) -> str:
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...<truncated for prompt budget>..."


def build_hard_question_prompt(
    *,
    summary: Dict[str, Any],
    stage_context: Dict[str, Any],
    storybook: Dict[str, Any],
    passed_surpassed: Dict[str, Any],
) -> str:
    context_payload = {
        "window_hours": summary.get("window_hours"),
        "core": {
            "recent_advice_nonbench": summary.get("recent_advice_nonbench"),
            "engine": summary.get("engine"),
            "outcomes": summary.get("outcomes"),
        },
        "passed_and_surpassed": passed_surpassed,
        "stage_context": stage_context,
        "trace_storybook": storybook,
    }
    compact_context = _compact_for_prompt(context_payload)
    return (
        "You are acting as a world-class Systems Architect + QA Lead + AGI Engineer.\n\n"
        "Goal:\n"
        "Interrogate advisory usefulness with hard questions and context-first rigor. "
        "Do not optimize for superficial metric gains. Explain reality from event capture to promotion.\n\n"
        "Required quality bar:\n"
        "- Falsifiable, skeptical, explicit assumptions.\n"
        "- Separate passed, surpassed, and blind spots with evidence.\n"
        "- Treat each stage as a causal chain, not independent widgets.\n"
        "- If a metric improved while context degraded, call it out explicitly.\n"
        "- Propose concrete remediation experiments with owner, gate, and success metric.\n\n"
        "Hard questions you must answer:\n"
        "1. Where did the system appear healthy numerically but fail contextually?\n"
        "2. Which advisory emissions were directionally right but mistimed for user context?\n"
        "3. Which suppression paths protected quality vs accidentally blocked high-value help?\n"
        "4. Which upstream stage injected the most downstream noise this window?\n"
        "5. Which passed and surpassed signals are robust vs fragile artifacts?\n"
        "6. If you had to remove one component tomorrow, which removal would improve net utility?\n"
        "7. What exact 30-day validation loop should run every 4h to prove learning quality compounding?\n\n"
        "Output format (strict):\n"
        "A) Executive verdict (<=10 bullets)\n"
        "B) Stage-by-stage findings (Stages 1..9: issue, evidence, user-context impact)\n"
        "C) Root-cause chains (top 5)\n"
        "D) Passed vs Surpassed vs Misleading signals\n"
        "E) Experiment plan (P0/P1/P2 with owner, metric, gate, fallback)\n"
        "F) Risks and unknowns\n"
        "G) Definition of better advisory intelligence for next 4h window\n\n"
        "Context bundle:\n"
        f"{compact_context}\n"
    )


def _resolve_external_review_providers(raw: str) -> List[str]:
    txt = _norm_text(raw).lower()
    if not txt or txt == "auto":
        out: List[str] = []
        if _norm_text(os.getenv("MINIMAX_API_KEY") or os.getenv("SPARK_MINIMAX_API_KEY")):
            out.append("minimax")
        out.append("claude")
        return out
    out = []
    for token in [x.strip().lower() for x in txt.split(",")]:
        if token and token not in out:
            out.append(token)
    return out


def run_external_context_review(
    *,
    prompt: str,
    providers: str,
    timeout_s: float,
    max_chars: int = 12000,
) -> Dict[str, Any]:
    chosen = _resolve_external_review_providers(providers)
    results: List[Dict[str, Any]] = []
    for provider in chosen:
        started = time.time()
        text: Optional[str] = None
        err = ""
        try:
            if provider == "claude":
                from lib.llm import ask_claude

                text = ask_claude(
                    prompt,
                    system_prompt=(
                        "You are an uncompromising architecture reviewer. "
                        "Use strict evidence and return deep analysis."
                    ),
                    max_tokens=3200,
                    timeout_s=max(30, int(timeout_s)),
                )
            elif provider == "minimax":
                from lib.advisory_synthesizer import _query_minimax

                text = _query_minimax(prompt, timeout_s=max(30.0, float(timeout_s)))
            else:
                from lib.advisory_synthesizer import _query_provider

                text = _query_provider(provider, prompt)
        except Exception as exc:
            err = f"{type(exc).__name__}:{exc}"
            text = None

        latency_ms = round((time.time() - started) * 1000.0, 1)
        cleaned = _norm_text(text)
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars] + "\n...<truncated>..."
        lowered = cleaned.lower()
        response_error = "execution error" in lowered or "provider_error" in lowered
        ok = bool(cleaned) and not response_error
        if response_error and not err:
            err = "response_error:provider_execution_error"
        results.append(
            {
                "provider": provider,
                "ok": ok,
                "latency_ms": latency_ms,
                "error": err,
                "response": cleaned,
            }
        )
    return {
        "attempted_providers": chosen,
        "results": results,
    }


def build_report(summary: Dict[str, Any], window_hours: float, now_ts: float) -> str:
    iso_now = datetime.fromtimestamp(now_ts, timezone.utc).isoformat()
    ra = summary["recent_advice"]
    ra_nonbench = summary.get("recent_advice_nonbench") or {}
    en = summary["engine"]
    oc = summary["outcomes"]
    stage_context = summary.get("stage_context") or {}
    storybook = summary.get("trace_storybook") or {}
    passed_surpassed = summary.get("passed_surpassed") or {}
    integrity = summary.get("integrity_gates") or {}
    remediation = summary.get("integrity_remediation") or {}

    rep = ra["repeated_texts"][:6]
    repeated_share = round(sum(float(r["share_pct_of_items"]) for r in rep), 2)
    high_suppression = float(en.get("suppression_share_pct") or 0.0) >= 60.0

    improvement_state = "improving" if (oc.get("strict_effectiveness_rate") or 0) >= 0.9 else "unclear"
    if high_suppression:
        improvement_state = "noisy"

    lines = [
        f"# Advisory Self-Review ({iso_now})",
        "",
        "## Window",
        f"- Hours analyzed: {window_hours}",
        f"- State: {improvement_state}",
        "",
        "## Core Metrics",
        f"- Advisory rows: {ra['rows']}",
        f"- Advisory trace coverage: {ra['trace_rows']}/{ra['rows']} ({ra['trace_coverage_pct']}%)",
        f"- Advice items emitted: {ra['item_total']}",
        (
            f"- Non-benchmark advisory rows: {ra_nonbench.get('rows', 0)} "
            f"(excluded {ra_nonbench.get('excluded', 0)})"
            if ra_nonbench
            else "- Non-benchmark advisory rows: unavailable"
        ),
        f"- Engine events: {en['rows']}",
        f"- Engine trace coverage: {en['trace_rows']}/{en['rows']} ({en['trace_coverage_pct']}%)",
        f"- Suppression share (all events): {en.get('suppression_share_pct', 0.0)}%",
        f"- Strict action rate: {oc['strict_action_rate']}",
        f"- Strict effectiveness rate: {oc['strict_effectiveness_rate']}",
        f"- Trace mismatch count: {oc['trace_mismatch_count']}",
        "",
        "## Passed And Surpassed Signals",
    ]
    for item in (passed_surpassed.get("passed") or []):
        lines.append(f"- Passed: {item}")
    for item in (passed_surpassed.get("surpassed") or []):
        lines.append(f"- Surpassed: {item}")

    if isinstance(remediation, dict) and remediation:
        lines.extend(["", "## Integrity Auto-Remediation"])
        before = remediation.get("before") if isinstance(remediation.get("before"), dict) else {}
        after = remediation.get("after") if isinstance(remediation.get("after"), dict) else {}
        if before:
            lines.append(
                "- Before:"
                f" ledger={before.get('decision_ledger_rows', 0)},"
                f" helpfulness={before.get('helpfulness_event_rows', 0)},"
                f" explicit_feedback={before.get('explicit_feedback_rows', 0)},"
                f" quality={before.get('quality_event_rows', 0)}"
            )
        if after:
            lines.append(
                "- After:"
                f" ledger={after.get('decision_ledger_rows', 0)},"
                f" helpfulness={after.get('helpfulness_event_rows', 0)},"
                f" explicit_feedback={after.get('explicit_feedback_rows', 0)},"
                f" quality={after.get('quality_event_rows', 0)}"
            )
        actions = remediation.get("actions") if isinstance(remediation.get("actions"), list) else []
        if actions:
            for action in actions:
                if not isinstance(action, dict):
                    continue
                step = _norm_text(action.get("step")) or "unknown_step"
                ok = bool(action.get("ok"))
                lines.append(f"- {'OK' if ok else 'WARN'} `{step}` {json.dumps(action, ensure_ascii=False)}")
        errors = remediation.get("errors") if isinstance(remediation.get("errors"), list) else []
        for err in errors[:8]:
            lines.append(f"- ERROR `{err}`")

    if isinstance(integrity, dict) and integrity:
        lines.extend(["", "## Integrity Gates"])
        gates = integrity.get("gates") if isinstance(integrity.get("gates"), list) else []
        if gates:
            for gate in gates:
                if not isinstance(gate, dict):
                    continue
                status = "PASS" if bool(gate.get("ok")) else "FAIL"
                lines.append(
                    f"- {status} `{gate.get('id')}` value=`{gate.get('value')}` target=`{gate.get('target')}`"
                )
        if integrity.get("failed_gate_ids"):
            lines.append(f"- Failed gates: {integrity.get('failed_gate_ids')}")
        persistence = integrity.get("persistence") if isinstance(integrity.get("persistence"), dict) else {}
        if persistence.get("persistent_failed_gate_ids"):
            lines.append(
                f"- Persistent failed gates ({persistence.get('persist_windows')} windows): "
                f"{persistence.get('persistent_failed_gate_ids')}"
            )
        if persistence.get("alert_written"):
            lines.append(f"- Alert written: `{persistence.get('alert_path')}`")

    lines.extend(
        [
            "",
            "## Honest Answers",
            "### Did learnings help make better decisions?",
            "- Yes, but unevenly. Trace-bound clusters show good outcomes only where evidence linkage stayed strict.",
            "- Context mismatch still appears where suppression or timing dominates despite healthy top-line metrics.",
            "",
            "### Examples with trace IDs",
        ]
    )
    if ra["trace_examples"]:
        for ex in ra["trace_examples"][:8]:
            lines.append(
                f"- `{ex['trace_id']}` | tool `{ex['tool']}` | source `{ex['source']}` | {ex['advice_preview']}"
            )
    else:
        lines.append("- No trace-bound advisory rows found in this window.")

    lines.extend(
        [
            "",
            "### Were there misses despite memory existing?",
            (
                "- Yes. High suppression share suggests retrieval/gating quality is still inconsistent."
                if high_suppression
                else "- Mixed. Suppression was not dominant in this window; evaluate misses via trace coverage and repeated-noise patterns."
            ),
            (
                "- Engine trace coverage is low; evidence linkage is incomplete in the engine path."
                if float(en.get("trace_coverage_pct") or 0.0) < 60.0
                else "- Engine trace coverage is healthy enough for stronger attribution confidence."
            ),
            "",
            "### Were unnecessary advisories/memories triggered?",
            f"- Top repeated advisories account for ~{repeated_share}% of all advice items in this window.",
            "",
            "## Top Repeated Advice (Noise Candidates)",
        ]
    )
    for row in rep:
        lines.append(f"- {row['count']}x ({row['share_pct_of_items']}%) {row['text'][:180]}")

    if ra_nonbench and ra_nonbench.get("repeated_texts"):
        lines.append("")
        lines.append("## Top Repeated Advice (Non-Benchmark Window)")
        for row in (ra_nonbench.get("repeated_texts") or [])[:6]:
            lines.append(f"- {row['count']}x ({row['share_pct_of_items']}%) {row['text'][:180]}")

    lines.extend(["", "## Bad Outcome Records"])
    if oc["bad_records"]:
        for row in oc["bad_records"]:
            lines.append(
                f"- trace `{row['trace_id']}` | source `{row['source']}` | insight `{row['insight_key']}` | {row['learning_content']}"
            )
    else:
        lines.append("- None in this window.")

    lines.extend(["", "## Stage Context Digest"])
    for stage_key in sorted(stage_context.keys()):
        stage = stage_context.get(stage_key) or {}
        if not isinstance(stage, dict):
            continue
        lines.append(f"### {stage.get('name', stage_key)}")
        for metric_key in ("observed_rows", "rows", "quality_events", "pending_count", "total_events_processed", "total_insights_created"):
            if metric_key in stage:
                lines.append(f"- {metric_key}: `{stage.get(metric_key)}`")
        if stage_key == "stage_8_advisory":
            lines.append(f"- helpful_rate_pct: `{stage.get('helpful_rate_pct', 0.0)}`")
            lines.append(f"- known_helpfulness: `{stage.get('known_helpfulness', 0)}`")
        if stage_key == "stage_5_quality_gate":
            oq = (stage.get("outcomes") or {}) if isinstance(stage.get("outcomes"), dict) else {}
            lines.append(f"- strict_effectiveness_rate: `{oq.get('strict_effectiveness_rate')}`")
            lines.append(f"- trace_mismatch_count: `{oq.get('trace_mismatch_count')}`")

    lines.extend(["", "## Trace Storybook", f"- stories_selected: `{storybook.get('stories_selected', 0)}`"])
    wins = storybook.get("wins") or []
    misses = storybook.get("misses") or []
    if wins:
        lines.append("### Wins")
        for row in wins[:6]:
            lines.append(
                f"- `{row.get('trace_id')}` {row.get('provider')}/{row.get('tool')} "
                f"label=`{row.get('label')}` impact=`{row.get('impact_score')}` notes={row.get('context_notes')}"
            )
    if misses:
        lines.append("### Misses")
        for row in misses[:6]:
            lines.append(
                f"- `{row.get('trace_id')}` {row.get('provider')}/{row.get('tool')} "
                f"label=`{row.get('label')}` impact=`{row.get('impact_score')}` notes={row.get('context_notes')}"
            )

    ext = summary.get("external_review") or {}
    if isinstance(ext, dict) and ext.get("results"):
        lines.extend(["", "## External Context Review (LLM)"])
        for row in ext.get("results", []):
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- provider=`{row.get('provider')}` ok=`{row.get('ok')}` latency_ms=`{row.get('latency_ms')}` error=`{row.get('error')}`"
            )
            response = _norm_text(row.get("response"))
            if response:
                lines.append(f"  - excerpt: {response[:280]}")

    lines.extend(
        [
            "",
            "## Optimization (No New Features)",
            "- Increase advisory repeat cooldowns and tool cooldowns to reduce duplicate cautions.",
            "- Keep `include_mind=true` with stale gating and minimum salience to improve cross-session quality without flooding.",
            "- Prefer fewer higher-rank items (`advisor.max_items` and `advisor.min_rank_score`) to improve signal density.",
            "- Improve strict trace discipline in advisory engine events before trusting aggregate success counters.",
            "",
            "## Questions To Ask Every Review",
            "1. Which advisories changed a concrete decision, with trace IDs?",
            "2. Which advisories repeated without adding new actionability?",
            "3. Where did suppression dominate and why?",
            "4. Which sources had strict-good outcomes vs non-strict optimism?",
            "5. What is one simplification we can do before adding anything new?",
            "",
        ]
    )
    return "\n".join(lines)


def generate_summary(
    window_hours: float,
    *,
    include_context: bool = True,
    stage_sample_limit: int = 10,
    trace_story_limit: int = 12,
    run_llm_review: bool = False,
    llm_providers: str = "auto",
    llm_timeout_s: float = 180.0,
) -> Dict[str, Any]:
    now_ts = time.time()
    # Allow fractional hours for tighter live verification windows.
    window_s = max(60, int(float(window_hours) * 3600))
    spark_dir = SPARK_DIR
    summary: Dict[str, Any] = {
        "window_hours": float(window_hours),
        "generated_at": datetime.fromtimestamp(now_ts, timezone.utc).isoformat(),
        "recent_advice": summarize_recent_advice(
            spark_dir / "advisor" / "recent_advice.jsonl",
            window_s=window_s,
            now_ts=now_ts,
        ),
        "recent_advice_nonbench": summarize_recent_advice(
            spark_dir / "advisor" / "recent_advice.jsonl",
            window_s=window_s,
            now_ts=now_ts,
            exclude_trace_prefixes=NONBENCH_TRACE_EXCLUDE_PREFIXES,
        ),
        "engine": summarize_engine(
            ADVISORY_ENGINE_LOG,
            window_s=window_s,
            now_ts=now_ts,
        ),
        "outcomes": summarize_outcomes(
            spark_dir / "meta_ralph" / "outcome_tracking.json",
            window_s=window_s,
            now_ts=now_ts,
        ),
    }

    if include_context:
        stage_context = summarize_stage_context(
            spark_dir=spark_dir,
            now_ts=now_ts,
            window_s=window_s,
            stage_sample_limit=max(3, int(stage_sample_limit)),
        )
        storybook = build_trace_storybook(
            spark_dir=spark_dir,
            now_ts=now_ts,
            window_s=window_s,
            trace_story_limit=max(4, int(trace_story_limit)),
        )
        passed_surpassed = derive_passed_and_surpassed(
            summary=summary,
            stage_context=stage_context,
        )
        prompt = build_hard_question_prompt(
            summary=summary,
            stage_context=stage_context,
            storybook=storybook,
            passed_surpassed=passed_surpassed,
        )
        summary["stage_context"] = stage_context
        summary["trace_storybook"] = storybook
        summary["passed_surpassed"] = passed_surpassed
        summary["hard_question_prompt"] = prompt
        if run_llm_review:
            summary["external_review"] = run_external_context_review(
                prompt=prompt,
                providers=llm_providers,
                timeout_s=float(llm_timeout_s),
            )

    return summary


def write_report(summary: Dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d_%H%M%S")
    out_file = out_dir / f"{stamp}_advisory_self_review.md"
    report = build_report(summary, float(summary["window_hours"]), now.timestamp())
    out_file.write_text(report, encoding="utf-8")
    return out_file


def write_context_bundle(summary: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d_%H%M%S")

    bundle_path = out_dir / f"{stamp}_advisory_context_bundle.json"
    prompt_path = out_dir / f"{stamp}_advisory_context_prompt.md"
    review_path = out_dir / f"{stamp}_advisory_context_external_review.json"

    bundle_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    prompt_path.write_text(_norm_text(summary.get("hard_question_prompt")), encoding="utf-8")
    if summary.get("external_review") is not None:
        review_path.write_text(
            json.dumps(summary.get("external_review"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return {
        "bundle": str(bundle_path),
        "prompt": str(prompt_path),
        "external_review": str(review_path) if review_path.exists() else "",
    }


def _write_jsonl_atomic(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            if isinstance(row, dict):
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(str(tmp), str(path))


def _decision_outcome_from_engine_row(row: Dict[str, Any]) -> str:
    outcome = _norm_text(row.get("outcome")).lower()
    if outcome in {"emitted", "blocked"}:
        return outcome
    event = _norm_text(row.get("event")).lower()
    if bool(row.get("emitted")) or event == "emitted":
        return "emitted"
    if event in DECISION_BLOCK_EVENTS:
        return "blocked"
    return ""


def _rebuild_decision_ledger_from_engine(
    *,
    spark_dir: Path,
    max_engine_rows: int,
) -> Dict[str, Any]:
    engine_rows = _tail_jsonl(spark_dir / "advisory_engine_alpha.jsonl", max(500, int(max_engine_rows)))
    if not engine_rows:
        return {"ok": False, "reason": "missing_engine_rows", "written": 0}

    out_rows: List[Dict[str, Any]] = []
    for row in engine_rows:
        outcome = _decision_outcome_from_engine_row(row)
        if not outcome:
            continue
        event = _norm_text(row.get("event")).lower() or "unknown"
        ts = _to_ts(row.get("ts")) or time.time()
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        gate_reason = _norm_text(row.get("gate_reason") or row.get("reason"))
        if not gate_reason and isinstance(extra, dict):
            gate_reason = _norm_text(extra.get("gate_reason") or extra.get("reason"))
        if not gate_reason and outcome == "blocked":
            gate_reason = event

        entry: Dict[str, Any] = {
            "ts": float(ts),
            "event": event,
            "outcome": outcome,
            "session_id": _norm_text(row.get("session_id")),
            "tool_name": _norm_text(row.get("tool_name")),
            "tool": _norm_text(row.get("tool_name") or row.get("tool")),
            "trace_id": _norm_text(row.get("trace_id")),
            "route": _norm_text(row.get("route")) or "alpha",
            "emitted": bool(outcome == "emitted"),
            "elapsed_ms": round(max(0.0, _safe_float(row.get("elapsed_ms"), 0.0)), 2),
        }
        if gate_reason:
            entry["gate_reason"] = gate_reason
        if isinstance(extra, dict) and extra:
            entry["extra"] = extra
        out_rows.append(entry)

    if not out_rows:
        return {"ok": False, "reason": "no_decision_events_in_engine_log", "written": 0}

    _write_jsonl_atomic(spark_dir / "advisory_decision_ledger.jsonl", out_rows)
    return {"ok": True, "written": len(out_rows), "reason": "rebuilt_from_engine_log"}


def _run_quality_spine(spark_dir: Path) -> Dict[str, Any]:
    from lib.advisory_quality_spine import run_advisory_quality_spine_default

    result = run_advisory_quality_spine_default(spark_dir=spark_dir, write_files=True)
    return result if isinstance(result, dict) else {}


def _run_helpfulness_watcher(spark_dir: Path, *, min_created_at: float) -> Dict[str, Any]:
    from lib.helpfulness_watcher import run_helpfulness_watcher_default

    result = run_helpfulness_watcher_default(
        spark_dir=spark_dir,
        min_created_at=max(0.0, float(min_created_at)),
        write_files=True,
    )
    return result if isinstance(result, dict) else {}


def _rating_label_to_feedback(label: str) -> Dict[str, Any]:
    key = _norm_text(label).lower()
    if key == "helpful":
        return {"helpful": True, "followed": True, "status": "acted", "outcome": "good"}
    if key == "unhelpful":
        return {"helpful": False, "followed": True, "status": "blocked", "outcome": "bad"}
    if key == "harmful":
        return {"helpful": False, "followed": True, "status": "harmful", "outcome": "bad"}
    if key == "not_followed":
        return {"helpful": None, "followed": False, "status": "ignored", "outcome": "neutral"}
    return {"helpful": None, "followed": False, "status": "ignored", "outcome": "neutral"}


def _backfill_feedback_from_quality_ratings(
    *,
    spark_dir: Path,
    max_rows: int = 4000,
) -> Dict[str, Any]:
    feedback_file = spark_dir / "advice_feedback.jsonl"
    existing_feedback = list(_load_jsonl(feedback_file))
    if existing_feedback:
        return {"ok": True, "skipped": True, "reason": "explicit_feedback_already_present", "written": 0}

    rating_rows = _tail_jsonl(spark_dir / "advisor" / "advisory_quality_ratings.jsonl", max(1, int(max_rows)))
    if not rating_rows:
        return {"ok": False, "skipped": True, "reason": "no_quality_ratings_rows", "written": 0}

    feedback_rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rating_rows:
        trace_id = _norm_text(row.get("trace_id"))
        advice_id = _norm_text(row.get("advice_id"))
        if not trace_id or not advice_id:
            continue
        mapped = _rating_label_to_feedback(_norm_text(row.get("label")))
        created_at = _to_ts(row.get("ts")) or time.time()
        key = f"{trace_id}|{advice_id}|{mapped.get('status')}|{int(created_at)}"
        if key in seen:
            continue
        seen.add(key)
        feedback_rows.append(
            {
                "advice_ids": [advice_id],
                "tool": _norm_text(row.get("tool")),
                "helpful": mapped.get("helpful"),
                "followed": bool(mapped.get("followed")) if mapped.get("followed") is not None else None,
                "status": _norm_text(mapped.get("status")),
                "outcome": _norm_text(mapped.get("outcome")),
                "trace_id": trace_id,
                "run_id": _norm_text(row.get("run_id")),
                "session_id": _norm_text(row.get("session_id")),
                "route": _norm_text(row.get("route")) or "alpha",
                "notes": _norm_text(row.get("notes"))[:200],
                "source": "quality_rating_backfill",
                "created_at": float(created_at),
            }
        )

    if not feedback_rows:
        return {"ok": False, "skipped": True, "reason": "no_backfillable_quality_rating_rows", "written": 0}

    _write_jsonl_atomic(feedback_file, feedback_rows[-max(1, int(max_rows)):])
    return {"ok": True, "skipped": False, "reason": "backfilled_from_quality_ratings", "written": len(feedback_rows)}


def auto_remediate_integrity_streams(
    *,
    summary: Dict[str, Any],
    spark_dir: Path,
    max_engine_rows: int = 60000,
) -> Dict[str, Any]:
    before = {
        "decision_ledger_rows": len(list(_load_jsonl(spark_dir / "advisory_decision_ledger.jsonl"))),
        "helpfulness_event_rows": len(list(_load_jsonl(spark_dir / "advisor" / "helpfulness_events.jsonl"))),
        "explicit_feedback_rows": len(list(_load_jsonl(spark_dir / "advice_feedback.jsonl"))),
        "feedback_request_rows": len(list(_load_jsonl(spark_dir / "advice_feedback_requests.jsonl"))),
        "quality_event_rows": len(list(_load_jsonl(spark_dir / "advisor" / "advisory_quality_events.jsonl"))),
    }
    actions: List[Dict[str, Any]] = []
    errors: List[str] = []

    if before["decision_ledger_rows"] <= 0:
        try:
            actions.append(
                {
                    "step": "rebuild_decision_ledger",
                    **_rebuild_decision_ledger_from_engine(
                        spark_dir=spark_dir,
                        max_engine_rows=max(500, int(max_engine_rows)),
                    ),
                }
            )
        except Exception as exc:
            errors.append(f"rebuild_decision_ledger_failed:{type(exc).__name__}:{exc}")

    needs_quality_refresh = before["quality_event_rows"] <= 0 or before["helpfulness_event_rows"] <= 0
    if needs_quality_refresh:
        try:
            quality = _run_quality_spine(spark_dir)
            actions.append(
                {
                    "step": "refresh_quality_spine",
                    "ok": True,
                    "summary_total_events": _safe_int((quality.get("summary") or {}).get("total_events"), 0),
                }
            )
        except Exception as exc:
            errors.append(f"refresh_quality_spine_failed:{type(exc).__name__}:{exc}")

    if before["helpfulness_event_rows"] <= 0:
        try:
            window_hours = max(4.0, _safe_float(summary.get("window_hours"), 4.0))
            min_created_at = time.time() - (window_hours * 6.0 * 3600.0)
            watch = _run_helpfulness_watcher(
                spark_dir=spark_dir,
                min_created_at=min_created_at,
            )
            actions.append(
                {
                    "step": "refresh_helpfulness_events",
                    "ok": bool(watch.get("ok", False)),
                    "input_requests_rows": _safe_int((watch.get("inputs") or {}).get("requests_rows"), 0),
                    "output_total_events": _safe_int((watch.get("summary") or {}).get("total_events"), 0),
                }
            )
        except Exception as exc:
            errors.append(f"refresh_helpfulness_events_failed:{type(exc).__name__}:{exc}")

    if before["explicit_feedback_rows"] <= 0:
        try:
            actions.append(
                {
                    "step": "backfill_explicit_feedback_from_quality_ratings",
                    **_backfill_feedback_from_quality_ratings(spark_dir=spark_dir),
                }
            )
        except Exception as exc:
            errors.append(f"backfill_explicit_feedback_failed:{type(exc).__name__}:{exc}")

    after = {
        "decision_ledger_rows": len(list(_load_jsonl(spark_dir / "advisory_decision_ledger.jsonl"))),
        "helpfulness_event_rows": len(list(_load_jsonl(spark_dir / "advisor" / "helpfulness_events.jsonl"))),
        "explicit_feedback_rows": len(list(_load_jsonl(spark_dir / "advice_feedback.jsonl"))),
        "feedback_request_rows": len(list(_load_jsonl(spark_dir / "advice_feedback_requests.jsonl"))),
        "quality_event_rows": len(list(_load_jsonl(spark_dir / "advisor" / "advisory_quality_events.jsonl"))),
    }
    return {
        "attempted": bool(actions),
        "before": before,
        "after": after,
        "actions": actions,
        "errors": errors,
    }


def evaluate_integrity_gates(
    *,
    summary: Dict[str, Any],
    spark_dir: Path,
) -> Dict[str, Any]:
    """Evaluate advisory context integrity gates for hard-fail enforcement."""
    generated_ts = _to_ts(summary.get("generated_at"))
    now_ts = generated_ts if generated_ts > 0 else time.time()
    window_s = max(60, int(_safe_float(summary.get("window_hours"), 4.0) * 3600.0))

    ledger_rows = _load_jsonl(spark_dir / "advisory_decision_ledger.jsonl")
    helpful_rows = _load_jsonl(spark_dir / "advisor" / "helpfulness_events.jsonl")
    feedback_rows = _load_jsonl(spark_dir / "advice_feedback.jsonl")

    quality_rows = _rows_in_window(
        _tail_jsonl(spark_dir / "advisor" / "advisory_quality_events.jsonl", 24000),
        now_ts=now_ts,
        window_s=window_s,
        ts_keys=("emitted_ts", "recorded_at", "signal_ts"),
    )
    trace_field_rows = sum(1 for r in quality_rows if any(k in r for k in ("trace_id", "outcome_trace_id", "trace")))
    trace_bound_rows = sum(1 for r in quality_rows if _norm_text(r.get("trace_id")))
    quality_trace_coverage_pct = _pct(trace_bound_rows, trace_field_rows) if trace_field_rows > 0 else 0.0

    stage_context = summary.get("stage_context") or {}
    stage8 = stage_context.get("stage_8_advisory") if isinstance(stage_context, dict) else {}
    if not isinstance(stage8, dict):
        stage8 = {}
    known_helpfulness = _safe_int(stage8.get("known_helpfulness"), 0)
    quality_events = _safe_int(stage8.get("quality_events"), 0) or len(quality_rows)
    known_helpfulness_rate_pct = _pct(known_helpfulness, quality_events)

    gates = [
        {
            "id": "decision_ledger_present",
            "description": "Decision ledger exists and has rows",
            "ok": bool(len(ledger_rows) > 0),
            "value": int(len(ledger_rows)),
            "target": ">0 rows",
            "severity": "critical",
            "failure_note": "decision ledger missing or empty",
        },
        {
            "id": "helpfulness_events_present",
            "description": "Helpfulness events stream present",
            "ok": bool(len(helpful_rows) > 0),
            "value": int(len(helpful_rows)),
            "target": ">0 rows",
            "severity": "critical",
            "failure_note": "helpfulness events missing",
        },
        {
            "id": "explicit_feedback_present",
            "description": "Explicit advisory feedback rows present",
            "ok": bool(len(feedback_rows) > 0),
            "value": int(len(feedback_rows)),
            "target": ">0 rows",
            "severity": "critical",
            "failure_note": "explicit feedback missing",
        },
        {
            "id": "quality_trace_coverage_floor",
            "description": "Quality events trace coverage",
            "ok": bool(quality_trace_coverage_pct >= 50.0),
            "value": float(quality_trace_coverage_pct),
            "target": ">=50.0%",
            "severity": "critical",
            "failure_note": "quality events trace coverage below 50%",
        },
        {
            "id": "known_helpfulness_coverage_floor",
            "description": "Known helpfulness coverage of quality events",
            "ok": bool(known_helpfulness_rate_pct >= 40.0),
            "value": float(known_helpfulness_rate_pct),
            "target": ">=40.0%",
            "severity": "critical",
            "failure_note": "known helpfulness coverage below 40%",
        },
    ]

    failed = [g for g in gates if not bool(g.get("ok"))]
    return {
        "evaluated_at": _to_iso(now_ts),
        "window_hours": _safe_float(summary.get("window_hours"), 4.0),
        "gates": gates,
        "failed_gate_ids": [str(g.get("id")) for g in failed],
        "blind_spots": [str(g.get("failure_note")) for g in failed],
        "quality_trace_coverage_pct": quality_trace_coverage_pct,
        "known_helpfulness_rate_pct": known_helpfulness_rate_pct,
        "quality_events": int(quality_events),
    }


def _load_gate_state(path: Path) -> Dict[str, Any]:
    data = _load_json(path)
    return data if isinstance(data, dict) else {"history": []}


def _save_gate_state(path: Path, state: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _append_alert(path: Path, payload: Dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def apply_gate_persistence(
    *,
    gate_report: Dict[str, Any],
    state_file: Path,
    persist_windows: int,
    alert_file: Path,
    alerts_enabled: bool,
    now_ts: float,
) -> Dict[str, Any]:
    state = _load_gate_state(state_file)
    history = state.get("history")
    if not isinstance(history, list):
        history = []

    current_failed = [str(x) for x in (gate_report.get("failed_gate_ids") or [])]
    snapshot = {
        "ts": float(now_ts),
        "window_hours": float(gate_report.get("window_hours") or 0.0),
        "failed_gate_ids": current_failed,
        "blind_spots": list(gate_report.get("blind_spots") or []),
    }
    history.append(snapshot)
    history = history[-80:]

    required = max(1, int(persist_windows))
    persistent_failed: List[str] = []
    if current_failed:
        for gate_id in current_failed:
            streak = 0
            for item in reversed(history):
                ids = item.get("failed_gate_ids")
                if not isinstance(ids, list):
                    break
                if gate_id in ids:
                    streak += 1
                else:
                    break
            if streak >= required:
                persistent_failed.append(gate_id)

    alert_written = False
    alert_payload: Dict[str, Any] = {}
    if alerts_enabled and persistent_failed:
        fingerprint = ",".join(sorted(set(persistent_failed)))
        last_alert = state.get("last_alert") if isinstance(state.get("last_alert"), dict) else {}
        last_fingerprint = _norm_text(last_alert.get("fingerprint"))
        last_ts = _safe_float(last_alert.get("ts"), 0.0)
        # Avoid duplicate alerts in tight manual loops while still alerting each ~4h cycle.
        if fingerprint != last_fingerprint or (now_ts - last_ts) >= 3.0 * 3600.0:
            alert_payload = {
                "ts": now_ts,
                "at": _to_iso(now_ts),
                "kind": "advisory_context_blind_spot_persistent",
                "persist_windows": required,
                "persistent_failed_gate_ids": sorted(set(persistent_failed)),
                "current_failed_gate_ids": current_failed,
                "blind_spots": list(gate_report.get("blind_spots") or []),
                "window_hours": gate_report.get("window_hours"),
            }
            alert_written = _append_alert(alert_file, alert_payload)
            if alert_written:
                state["last_alert"] = {
                    "ts": now_ts,
                    "fingerprint": fingerprint,
                    "path": str(alert_file),
                }

    state["history"] = history
    state["last_run"] = snapshot
    state["persistent_failed_gate_ids"] = sorted(set(persistent_failed))
    _save_gate_state(state_file, state)
    return {
        "persist_windows": required,
        "persistent_failed_gate_ids": sorted(set(persistent_failed)),
        "alert_written": bool(alert_written),
        "alert_path": str(alert_file),
        "alert_payload": alert_payload,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate advisory self-review report")
    ap.add_argument("--window-hours", type=float, default=4.0, help="Lookback window in hours (float allowed)")
    ap.add_argument("--out-dir", default="docs/reports", help="Output directory for markdown report")
    ap.add_argument("--json", action="store_true", help="Print JSON summary only")
    ap.add_argument("--min-gap-hours", type=float, default=4.0, help="Skip if a report younger than this exists")
    ap.add_argument(
        "--context-mode",
        choices=("full", "off"),
        default="full",
        help="full=include stage context and prompt bundle data; off=metrics-only",
    )
    ap.add_argument("--stage-sample-limit", type=int, default=10, help="Max per-stage context samples in report bundle")
    ap.add_argument("--trace-story-limit", type=int, default=12, help="Max trace stories across wins/misses")
    ap.add_argument("--emit-context-bundle", action="store_true", help="Write context bundle JSON + prompt markdown")
    ap.add_argument("--run-llm-review", action="store_true", help="Run external LLM review on the hard-question prompt")
    ap.add_argument("--llm-providers", default="auto", help="Comma-separated providers (auto|minimax,claude,...)")
    ap.add_argument("--llm-timeout-s", type=float, default=180.0, help="Per-provider LLM timeout seconds")
    ap.add_argument("--no-enforce-integrity-gates", action="store_true", help="Disable advisory integrity gate evaluation")
    ap.add_argument("--gate-persist-windows", type=int, default=2, help="Consecutive windows required before persistent gate fail")
    ap.add_argument("--gate-state-file", default=str(GATE_STATE_FILE), help="State file for gate persistence tracking")
    ap.add_argument("--gate-alert-file", default=str(GATE_ALERTS_FILE), help="JSONL alert sink for persistent gate failures")
    ap.add_argument("--no-gate-alerts", action="store_true", help="Disable writing persistent gate alerts")
    ap.add_argument(
        "--no-auto-remediate-integrity",
        action="store_true",
        help="Disable best-effort remediation of missing advisory integrity streams before gate checks",
    )
    ap.add_argument(
        "--integrity-remediate-max-engine-rows",
        type=int,
        default=60000,
        help="Max advisory engine rows scanned when rebuilding decision ledger from engine log",
    )
    ap.add_argument(
        "--no-fail-on-persistent-blind-spots",
        action="store_true",
        help="Do not return non-zero when blind spots persist across required windows",
    )
    args = ap.parse_args()

    # Gap guard: skip if a recent report already exists
    out_dir = Path(args.out_dir)
    if args.min_gap_hours > 0 and out_dir.exists():
        import glob as _glob

        existing = sorted(_glob.glob(str(out_dir / "*_advisory_self_review.md")))
        if existing:
            newest_age_h = (time.time() - Path(existing[-1]).stat().st_mtime) / 3600
            if newest_age_h < args.min_gap_hours:
                print(f"Skipped: recent report exists ({newest_age_h:.1f}h old, min gap {args.min_gap_hours}h)")
                return 0

    summary = generate_summary(
        window_hours=max(1.0 / 60.0, float(args.window_hours)),
        include_context=(args.context_mode != "off"),
        stage_sample_limit=max(2, int(args.stage_sample_limit)),
        trace_story_limit=max(2, int(args.trace_story_limit)),
        run_llm_review=bool(args.run_llm_review),
        llm_providers=str(args.llm_providers),
        llm_timeout_s=float(args.llm_timeout_s),
    )
    gate_exit_code = 0
    enforce_gates = not bool(args.no_enforce_integrity_gates)
    if enforce_gates and args.context_mode != "off":
        if not bool(args.no_auto_remediate_integrity):
            summary["integrity_remediation"] = auto_remediate_integrity_streams(
                summary=summary,
                spark_dir=SPARK_DIR,
                max_engine_rows=max(500, int(args.integrity_remediate_max_engine_rows)),
            )
        gate_report = evaluate_integrity_gates(summary=summary, spark_dir=SPARK_DIR)
        persistence = apply_gate_persistence(
            gate_report=gate_report,
            state_file=Path(str(args.gate_state_file)),
            persist_windows=max(1, int(args.gate_persist_windows)),
            alert_file=Path(str(args.gate_alert_file)),
            alerts_enabled=(not bool(args.no_gate_alerts)),
            now_ts=time.time(),
        )
        gate_report["persistence"] = persistence
        summary["integrity_gates"] = gate_report

        failed_now = gate_report.get("failed_gate_ids") or []
        if failed_now:
            print(f"Advisory integrity gates failing now: {failed_now}")
        if persistence.get("alert_written"):
            print(f"Advisory integrity alert written: {persistence.get('alert_path')}")
        if (
            not bool(args.no_fail_on_persistent_blind_spots)
            and (persistence.get("persistent_failed_gate_ids") or [])
        ):
            persistent = persistence.get("persistent_failed_gate_ids")
            print(
                "Advisory integrity gate FAILED: persistent blind spots across "
                f"{persistence.get('persist_windows')} windows: {persistent}"
            )
            gate_exit_code = 2

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return gate_exit_code

    out_path = write_report(summary, out_dir)
    if args.emit_context_bundle or args.run_llm_review:
        bundle_paths = write_context_bundle(summary, out_dir)
        print(f"Advisory context bundle written: {bundle_paths.get('bundle')}")
        print(f"Advisory context prompt written: {bundle_paths.get('prompt')}")
        if bundle_paths.get("external_review"):
            print(f"Advisory external review written: {bundle_paths.get('external_review')}")
    print(f"Advisory self-review written: {out_path}")
    return gate_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
