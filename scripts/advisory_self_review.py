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
        results.append(
            {
                "provider": provider,
                "ok": bool(cleaned),
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
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    out_path = write_report(summary, out_dir)
    if args.emit_context_bundle or args.run_llm_review:
        bundle_paths = write_context_bundle(summary, out_dir)
        print(f"Advisory context bundle written: {bundle_paths.get('bundle')}")
        print(f"Advisory context prompt written: {bundle_paths.get('prompt')}")
        if bundle_paths.get("external_review"):
            print(f"Advisory external review written: {bundle_paths.get('external_review')}")
    print(f"Advisory self-review written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
