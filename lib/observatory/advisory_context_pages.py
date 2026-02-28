"""Generate context-first advisory observability pages.

These pages focus on advisory usefulness as a traced, end-to-end system:
event capture -> queue -> engine decisions -> emitted advisory -> feedback.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import spark_dir
from .linker import flow_link, fmt_num
from .readers import _coerce_decision_outcome

_SD = spark_dir()
_REPO_ROOT = Path(__file__).resolve().parents[2]

_KNOWN_LABELS = {"helpful", "unhelpful", "harmful"}
_BLOCKING_EVENTS = {
    "gate_no_emit",
    "context_repeat_blocked",
    "text_repeat_blocked",
    "question_like_blocked",
    "global_dedupe_suppressed",
    "emit_failed",
    "synth_empty",
    "no_gate_emissions",
    "no_ranked_advice",
    "exception",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path, *, max_rows: int = 12000) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    total = 0
    invalid = 0
    if not path.exists():
        return rows, {"lines": 0, "invalid_lines": 0}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                total += 1
                try:
                    row = json.loads(line)
                except Exception:
                    invalid += 1
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except Exception:
        return [], {"lines": 0, "invalid_lines": 0}
    if max_rows > 0 and len(rows) > max_rows:
        rows = rows[-max_rows:]
    return rows, {"lines": total, "invalid_lines": invalid}


def _parse_ts(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return float(text)
    except Exception:
        pass
    try:
        return float(datetime.fromisoformat(text).timestamp())
    except Exception:
        return 0.0


def _extract_ts(row: dict[str, Any], keys: Iterable[str] | None = None) -> float:
    if keys is None:
        keys = (
            "ts",
            "timestamp",
            "created_at",
            "created_ts",
            "emitted_ts",
            "request_ts",
            "resolved_at",
            "reviewed_at",
        )
    for key in keys:
        ts = _parse_ts(row.get(key))
        if ts > 0:
            return ts
    return 0.0


def _fmt_ts(ts: float) -> str:
    if ts <= 0:
        return "?"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _fmt_pct(numer: float, denom: float, digits: int = 1) -> str:
    if float(denom) <= 0.0:
        return f"{0.0:.{digits}f}%"
    pct = (100.0 * float(numer)) / float(denom)
    return f"{pct:.{digits}f}%"


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _trace_from_row(row: dict[str, Any]) -> str:
    for key in ("trace_id", "outcome_trace_id", "trace"):
        value = _norm_text(row.get(key))
        if value:
            return value
    return ""


def _load_decision_rows(limit: int = 10000) -> tuple[list[dict[str, Any]], str, Path]:
    ledger_path = _SD / "advisory_decision_ledger.jsonl"
    engine_path = _SD / "advisory_engine_alpha.jsonl"
    emit_path = _SD / "advisory_emit.jsonl"

    ledger_rows, _ = _read_jsonl(ledger_path, max_rows=limit)
    if ledger_rows:
        return ledger_rows, "advisory_decision_ledger", ledger_path

    engine_rows_raw, _ = _read_jsonl(engine_path, max_rows=max(limit * 2, 4000))
    if engine_rows_raw:
        normalized: list[dict[str, Any]] = []
        for row in engine_rows_raw:
            outcome = _coerce_decision_outcome(row)
            if outcome == "unknown":
                continue
            rec = dict(row)
            rec["outcome"] = outcome
            rec["tool"] = _norm_text(rec.get("tool") or rec.get("tool_name") or "?")
            rec["route"] = _norm_text(rec.get("route") or rec.get("delivery_route") or "alpha")
            reason = _norm_text(rec.get("gate_reason") or rec.get("reason"))
            if reason and outcome == "blocked" and not rec.get("suppressed_reasons"):
                rec["suppressed_reasons"] = [{"reason": reason, "count": 1}]
            normalized.append(rec)
        return normalized[-limit:], "advisory_engine_alpha_fallback", engine_path

    emit_rows_raw, _ = _read_jsonl(emit_path, max_rows=limit)
    if emit_rows_raw:
        normalized = []
        for row in emit_rows_raw:
            rec = dict(row)
            rec["outcome"] = "emitted"
            rec["tool"] = _norm_text(rec.get("tool") or rec.get("tool_name") or "?")
            rec["route"] = _norm_text(rec.get("route") or "emit_fallback")
            normalized.append(rec)
        return normalized, "advisory_emit_fallback", emit_path

    return [], "none", ledger_path


def _extract_suppression_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    raw = row.get("suppressed_reasons")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                reason = _norm_text(item.get("reason"))
            else:
                reason = _norm_text(item)
            if reason:
                reasons.append(reason)
    for key in ("gate_reason", "reason", "event"):
        reason = _norm_text(row.get(key))
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def _classify_reason(reason: str) -> str:
    txt = reason.lower()
    if "global_dedupe" in txt:
        return "global_dedupe"
    if "question_like" in txt:
        return "question_like"
    if "context_repeat" in txt or "repeat" in txt:
        return "repeat_guard"
    if "cooldown" in txt:
        return "cooldown"
    if "budget" in txt:
        return "budget"
    if "synth" in txt:
        return "synth"
    if "no_ranked_advice" in txt:
        return "retrieval_empty"
    return "other"


def _distribution(counter: Counter[str]) -> dict[str, float]:
    total = float(sum(counter.values()))
    if total <= 0:
        return {}
    return {k: float(v) / total for k, v in counter.items()}


def _drift_score(prev: Counter[str], curr: Counter[str]) -> tuple[float, list[tuple[str, float, float, float]]]:
    prev_dist = _distribution(prev)
    curr_dist = _distribution(curr)
    keys = sorted(set(prev_dist.keys()) | set(curr_dist.keys()))
    deltas: list[tuple[str, float, float, float]] = []
    l1 = 0.0
    for key in keys:
        p = prev_dist.get(key, 0.0)
        c = curr_dist.get(key, 0.0)
        diff = abs(c - p)
        l1 += diff
        deltas.append((key, p, c, diff))
    deltas.sort(key=lambda row: row[3], reverse=True)
    return round((l1 / 2.0) * 100.0, 1), deltas


def _split_windows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not rows:
        return [], []
    with_ts = [row for row in rows if _extract_ts(row) > 0]
    if with_ts:
        ordered = sorted(with_ts, key=_extract_ts)
    else:
        ordered = rows[:]
    mid = max(1, len(ordered) // 2)
    return ordered[:mid], ordered[mid:]


def _trace_lineage_page(data: dict[int, dict[str, Any]]) -> str:
    observe_rows, _ = _read_jsonl(_SD / "logs" / "observe_hook_telemetry.jsonl", max_rows=25000)
    queue_rows, _ = _read_jsonl(_SD / "queue" / "events.jsonl", max_rows=25000)
    quality_rows, _ = _read_jsonl(_SD / "advisor" / "advisory_quality_events.jsonl", max_rows=25000)
    helpful_rows, _ = _read_jsonl(_SD / "advisor" / "helpfulness_events.jsonl", max_rows=25000)
    feedback_rows, _ = _read_jsonl(_SD / "advice_feedback.jsonl", max_rows=25000)
    decision_rows, decision_source, _ = _load_decision_rows(limit=25000)

    stage_sets: dict[str, set[str]] = {
        "event_capture": {_trace_from_row(r) for r in observe_rows if _trace_from_row(r)},
        "queue": {_trace_from_row(r) for r in queue_rows if _trace_from_row(r)},
        "advisory_engine": {_trace_from_row(r) for r in decision_rows if _trace_from_row(r)},
        "quality_spine": {_trace_from_row(r) for r in quality_rows if _trace_from_row(r)},
        "helpfulness": {_trace_from_row(r) for r in helpful_rows if _trace_from_row(r)},
        "explicit_feedback": {_trace_from_row(r) for r in feedback_rows if _trace_from_row(r)},
    }
    engine_set = stage_sets.get("advisory_engine", set())
    denom = float(max(len(engine_set), 1))

    trace_events: dict[str, list[tuple[float, str, str]]] = defaultdict(list)

    def _add_trace_events(rows: list[dict[str, Any]], stage: str, desc_fn) -> None:
        for row in rows:
            trace = _trace_from_row(row)
            if not trace:
                continue
            ts = _extract_ts(row)
            trace_events[trace].append((ts, stage, desc_fn(row)))

    _add_trace_events(
        observe_rows,
        "event_capture",
        lambda row: _norm_text(row.get("event") or row.get("hook_event") or row.get("kind") or "captured"),
    )
    _add_trace_events(
        queue_rows,
        "queue",
        lambda row: _norm_text(row.get("event_type") or row.get("kind") or row.get("tool_name") or "queued"),
    )
    _add_trace_events(
        decision_rows,
        "advisory_engine",
        lambda row: _norm_text(row.get("outcome") or row.get("event") or "decision"),
    )
    _add_trace_events(
        quality_rows,
        "quality_spine",
        lambda row: _norm_text(row.get("helpfulness_label") or row.get("timing_bucket") or "quality"),
    )
    _add_trace_events(
        helpful_rows,
        "helpfulness",
        lambda row: _norm_text(row.get("helpful_label") or "helpfulness"),
    )
    _add_trace_events(
        feedback_rows,
        "explicit_feedback",
        lambda row: _norm_text(row.get("status") or row.get("helpful") or "feedback"),
    )

    trace_rows = []
    for trace, events in trace_events.items():
        stage_names = {stage for _, stage, _ in events}
        latest_ts = max((ts for ts, _, _ in events), default=0.0)
        trace_rows.append((trace, len(stage_names), latest_ts))
    trace_rows.sort(key=lambda row: (row[1], row[2]), reverse=True)

    lines = [
        "---",
        "title: Advisory Trace Lineage",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - trace",
        "  - lineage",
        "---",
        "",
        "# Advisory Trace Lineage",
        "",
        f"> {flow_link()} | [[stages/08-advisory|Stage 8: Advisory]]",
        f"> Decision source used for lineage: `{decision_source}`",
        "",
        "## Stage Coverage Against Advisory Engine Traces",
        "",
        "| Stage | Traces Seen | Coverage vs Advisory Engine |",
        "|-------|-------------|-----------------------------|",
    ]
    for stage in (
        "event_capture",
        "queue",
        "advisory_engine",
        "quality_spine",
        "helpfulness",
        "explicit_feedback",
    ):
        traces = stage_sets.get(stage, set())
        overlap = len(traces & engine_set) if engine_set else 0
        lines.append(
            f"| {stage} | {fmt_num(len(traces))} | {_fmt_pct(overlap, denom)} ({overlap}/{max(len(engine_set), 1)}) |"
        )
    lines.append("")

    if trace_rows:
        lines.extend(
            [
                "## Cross-Stage Trace Samples",
                "",
                "| Trace ID | Stages Touched | Latest Event |",
                "|----------|----------------|--------------|",
            ]
        )
        for trace, stage_count, latest_ts in trace_rows[:15]:
            lines.append(f"| `{trace}` | {stage_count} | {_fmt_ts(latest_ts)} |")
        lines.append("")

        lines.append("## Sample Timelines")
        lines.append("")
        for trace, _, _ in trace_rows[:8]:
            lines.append(f"### `{trace}`")
            timeline = sorted(trace_events.get(trace, []), key=lambda row: row[0])
            if not timeline:
                lines.append("- no events")
                lines.append("")
                continue
            for ts, stage, desc in timeline[:12]:
                lines.append(f"- {_fmt_ts(ts)} | `{stage}` | {desc[:140]}")
            lines.append("")
    else:
        lines.extend(["## Cross-Stage Trace Samples", "", "- No trace-linked events found in current files.", ""])

    stage8 = (data.get(8) or {}) if isinstance(data.get(8), dict) else {}
    coverage = stage8.get("advisory_rating_coverage_summary") or {}
    if isinstance(coverage, dict) and coverage:
        lines.extend(
            [
                "## Prompted-to-Rated Linkage Snapshot",
                "",
                f"- Prompted advisory items: `{coverage.get('prompted_total', 0)}`",
                f"- Explicitly rated: `{coverage.get('explicit_rated_total', 0)}` ({coverage.get('explicit_rate_pct', 0.0)}%)",
                f"- Known helpfulness: `{coverage.get('known_helpful_total', 0)}` ({coverage.get('known_helpful_rate_pct', 0.0)}%)",
                "",
            ]
        )
    return "\n".join(lines)


def _unknown_helpfulness_page(data: dict[int, dict[str, Any]]) -> str:
    summary = _read_json(_SD / "advisor" / "helpfulness_summary.json")
    events, _ = _read_jsonl(_SD / "advisor" / "helpfulness_events.jsonl", max_rows=40000)
    queue_rows, _ = _read_jsonl(_SD / "advisor" / "helpfulness_llm_queue.jsonl", max_rows=5000)
    review_rows, _ = _read_jsonl(_SD / "advisor" / "helpfulness_llm_reviews.jsonl", max_rows=15000)

    by_day: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "total": 0,
            "unknown": 0,
            "known": 0,
            "helpful": 0,
            "queued": 0,
            "llm_applied": 0,
        }
    )
    unknown_tools: Counter[str] = Counter()
    for row in events:
        ts = _extract_ts(row, ("request_ts", "resolved_at", "ts", "created_at"))
        if ts <= 0:
            continue
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        bucket = by_day[day]
        bucket["total"] += 1
        label = _norm_text(row.get("helpful_label")).lower()
        if label in _KNOWN_LABELS:
            bucket["known"] += 1
            if label == "helpful":
                bucket["helpful"] += 1
        else:
            bucket["unknown"] += 1
            unknown_tools[_norm_text(row.get("tool")) or "unknown"] += 1
        if bool(row.get("llm_review_required")):
            bucket["queued"] += 1
        if bool(row.get("llm_review_applied")):
            bucket["llm_applied"] += 1

    review_latest: dict[str, dict[str, Any]] = {}
    for row in review_rows:
        event_id = _norm_text(row.get("event_id"))
        if not event_id:
            continue
        prev = review_latest.get(event_id)
        if prev is None or _extract_ts(row, ("reviewed_at", "ts")) >= _extract_ts(prev, ("reviewed_at", "ts")):
            review_latest[event_id] = row
    queue_ids = {_norm_text(r.get("event_id")) for r in queue_rows if _norm_text(r.get("event_id"))}
    unresolved = 0
    for event_id in queue_ids:
        status = _norm_text((review_latest.get(event_id) or {}).get("status")).lower()
        if status not in {"ok", "abstain"}:
            unresolved += 1

    days = sorted(by_day.keys())[-14:]
    first_unknown = None
    last_unknown = None
    for day in days:
        row = by_day[day]
        if row["total"] <= 0:
            continue
        rate = round((100.0 * row["unknown"]) / max(row["total"], 1), 1)
        if first_unknown is None:
            first_unknown = rate
        last_unknown = rate
    delta = 0.0
    if first_unknown is not None and last_unknown is not None:
        delta = round(last_unknown - first_unknown, 1)

    lines = [
        "---",
        "title: Advisory Unknown Helpfulness Burn-Down",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - helpfulness",
        "  - burndown",
        "---",
        "",
        "# Advisory Unknown Helpfulness Burn-Down",
        "",
        f"> {flow_link()} | [[stages/08-advisory|Stage 8: Advisory]] | [[explore/helpfulness/_index|Helpfulness Explorer]]",
        "",
        "## Current Window Scoreboard",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Events in stream file | {fmt_num(len(events))} |",
        f"| Summary total events | {fmt_num(summary.get('total_events', len(events)))} |",
        f"| Known helpfulness events | {fmt_num(summary.get('known_helpfulness_total', 0))} |",
        f"| Unknown rate | {summary.get('unknown_rate_pct', 0.0)}% |",
        f"| Helpful rate (known) | {summary.get('helpful_rate_pct', 0.0)}% |",
        f"| LLM review queue count | {fmt_num(summary.get('llm_review_queue_count', len(queue_rows)))} |",
        f"| LLM unresolved queue items | {fmt_num(unresolved)} |",
        "",
        "## 14-Day Burn-Down Trend",
        "",
        "| Day | Events | Known | Unknown | Unknown Rate | Helpful (known) | Helpful Rate | Queued | LLM Applied |",
        "|-----|--------|-------|---------|--------------|-----------------|--------------|--------|-------------|",
    ]
    for day in days:
        row = by_day[day]
        unknown_rate = round((100.0 * row["unknown"]) / max(row["total"], 1), 1) if row["total"] > 0 else 0.0
        helpful_rate = round((100.0 * row["helpful"]) / max(row["known"], 1), 1) if row["known"] > 0 else 0.0
        lines.append(
            f"| {day} | {row['total']} | {row['known']} | {row['unknown']} | {unknown_rate}% | "
            f"{row['helpful']} | {helpful_rate}% | {row['queued']} | {row['llm_applied']} |"
        )
    lines.extend(
        [
            "",
            "## Burn-Down Status",
            "",
            f"- Unknown-rate delta across visible window: `{delta:+.1f}%` (negative is improving).",
            "- Goal: unknown rate should trend down while known-helpful rate remains stable or improves.",
            "",
        ]
    )
    if unknown_tools:
        lines.extend(
            [
                "## Top Tools Feeding Unknown Labels",
                "",
                "| Tool | Unknown Labels |",
                "|------|----------------|",
            ]
        )
        for tool, count in unknown_tools.most_common(8):
            lines.append(f"| {tool} | {count} |")
        lines.append("")

    stage8 = (data.get(8) or {}) if isinstance(data.get(8), dict) else {}
    quality_summary = stage8.get("advisory_quality_summary") or {}
    if isinstance(quality_summary, dict) and quality_summary:
        lines.extend(
            [
                "## Emission Quality Cross-Check",
                "",
                f"- Quality spine events: `{quality_summary.get('total_events', 0)}`",
                f"- Avg impact score: `{quality_summary.get('avg_impact_score', 0.0)}`",
                f"- Right-on-time rate: `{quality_summary.get('right_on_time_rate_pct', 0.0)}%`",
                "",
            ]
        )
    return "\n".join(lines)


def _suppression_replay_page() -> str:
    rows, source, source_path = _load_decision_rows(limit=16000)
    blocked_rows = []
    reason_counter: Counter[str] = Counter()
    bucket_counter: Counter[str] = Counter()
    for row in rows:
        outcome = _norm_text(row.get("outcome")).lower()
        if outcome == "emitted":
            continue
        if not outcome:
            event = _norm_text(row.get("event")).lower()
            if event in _BLOCKING_EVENTS:
                outcome = "blocked"
        if outcome not in {"blocked", "suppressed"}:
            continue
        reasons = _extract_suppression_reasons(row)
        if not reasons:
            reasons = [_norm_text(row.get("event")) or "unknown"]
        for reason in reasons:
            reason_counter[reason] += 1
            bucket_counter[_classify_reason(reason)] += 1
        rec = dict(row)
        rec["_reasons"] = reasons
        blocked_rows.append(rec)

    blocked_rows.sort(key=_extract_ts, reverse=True)
    high_potential = []
    for row in blocked_rows:
        selected_count = int(row.get("selected_count") or 0)
        source_counts = row.get("source_counts")
        source_total = 0
        if isinstance(source_counts, dict):
            for value in source_counts.values():
                try:
                    source_total += int(value or 0)
                except Exception:
                    continue
        if selected_count > 0 or source_total > 0:
            high_potential.append((row, selected_count, source_total))

    lines = [
        "---",
        "title: Advisory Suppression Decision Replay",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - suppression",
        "  - replay",
        "---",
        "",
        "# Advisory Suppression Decision Replay",
        "",
        f"> {flow_link()} | [[stages/08-advisory|Stage 8: Advisory]] | [[explore/decisions/_index|Decision Explorer]]",
        f"> Decision source: `{source}` (`{source_path}`)",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total decision rows analyzed | {fmt_num(len(rows))} |",
        f"| Blocked/suppressed rows | {fmt_num(len(blocked_rows))} |",
        f"| High-potential blocked rows | {fmt_num(len(high_potential))} |",
        "",
    ]
    if bucket_counter:
        lines.extend(
            [
                "## Suppression Buckets",
                "",
                "| Bucket | Count | Share of blocked |",
                "|--------|-------|------------------|",
            ]
        )
        denom = float(max(len(blocked_rows), 1))
        for bucket, count in bucket_counter.most_common(10):
            lines.append(f"| {bucket} | {count} | {_fmt_pct(count, denom)} |")
        lines.append("")

    if reason_counter:
        lines.extend(
            [
                "## Top Raw Suppression Reasons",
                "",
                "| Reason | Count |",
                "|--------|-------|",
            ]
        )
        for reason, count in reason_counter.most_common(15):
            lines.append(f"| {reason[:120]} | {count} |")
        lines.append("")

    if high_potential:
        lines.extend(
            [
                "## High-Potential Blocked Samples",
                "",
                "| Time | Tool | Route | Selected | Retrieved Sources | Trace | Reasons |",
                "|------|------|-------|----------|------------------|-------|---------|",
            ]
        )
        for row, selected_count, source_total in high_potential[:20]:
            ts = _fmt_ts(_extract_ts(row))
            tool = _norm_text(row.get("tool") or row.get("tool_name") or "?")
            route = _norm_text(row.get("route") or row.get("delivery_route") or "?")
            trace = _trace_from_row(row) or "?"
            reasons = "; ".join(row.get("_reasons", [])[:2])
            lines.append(
                f"| {ts} | {tool} | `{route}` | {selected_count} | {source_total} | `{trace}` | {reasons[:120]} |"
            )
        lines.append("")
    else:
        lines.extend(["## High-Potential Blocked Samples", "", "- none in current window", ""])

    lines.extend(
        [
            "## Replay Drill",
            "",
            "Use this command on traces above to inspect end-to-end timeline:",
            "",
            "```bash",
            "python scripts/trace_query.py --trace-id <trace_id>",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _context_drift_page() -> str:
    decision_rows, source, _ = _load_decision_rows(limit=22000)
    quality_rows, _ = _read_jsonl(_SD / "advisor" / "advisory_quality_events.jsonl", max_rows=22000)

    prev_dec, curr_dec = _split_windows(decision_rows)
    prev_q, curr_q = _split_windows(quality_rows)

    dimensions: list[tuple[str, Counter[str], Counter[str], int, int]] = []

    def _counter(rows: list[dict[str, Any]], key_fn) -> Counter[str]:
        out: Counter[str] = Counter()
        for row in rows:
            key = key_fn(row)
            if key:
                out[key] += 1
        return out

    dimensions.append(
        (
            "decision_tool",
            _counter(prev_dec, lambda r: _norm_text(r.get("tool") or r.get("tool_name") or "unknown")),
            _counter(curr_dec, lambda r: _norm_text(r.get("tool") or r.get("tool_name") or "unknown")),
            len(prev_dec),
            len(curr_dec),
        )
    )
    dimensions.append(
        (
            "decision_route",
            _counter(prev_dec, lambda r: _norm_text(r.get("route") or r.get("delivery_route") or "unknown")),
            _counter(curr_dec, lambda r: _norm_text(r.get("route") or r.get("delivery_route") or "unknown")),
            len(prev_dec),
            len(curr_dec),
        )
    )
    dimensions.append(
        (
            "quality_provider",
            _counter(prev_q, lambda r: _norm_text(r.get("provider") or "unknown")),
            _counter(curr_q, lambda r: _norm_text(r.get("provider") or "unknown")),
            len(prev_q),
            len(curr_q),
        )
    )
    dimensions.append(
        (
            "quality_phase",
            _counter(prev_q, lambda r: _norm_text(r.get("task_phase") or "unknown").lower()),
            _counter(curr_q, lambda r: _norm_text(r.get("task_phase") or "unknown").lower()),
            len(prev_q),
            len(curr_q),
        )
    )
    dimensions.append(
        (
            "suppression_bucket",
            _counter(
                [r for r in prev_dec if _norm_text(r.get("outcome")).lower() != "emitted"],
                lambda r: _classify_reason((_extract_suppression_reasons(r) or ["other"])[0]),
            ),
            _counter(
                [r for r in curr_dec if _norm_text(r.get("outcome")).lower() != "emitted"],
                lambda r: _classify_reason((_extract_suppression_reasons(r) or ["other"])[0]),
            ),
            len([r for r in prev_dec if _norm_text(r.get("outcome")).lower() != "emitted"]),
            len([r for r in curr_dec if _norm_text(r.get("outcome")).lower() != "emitted"]),
        )
    )

    lines = [
        "---",
        "title: Advisory Context Drift Panel",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - drift",
        "  - context",
        "---",
        "",
        "# Advisory Context Drift Panel",
        "",
        f"> {flow_link()} | [[stages/08-advisory|Stage 8: Advisory]]",
        f"> Decision source for drift inputs: `{source}`",
        "",
        "## Drift Scores (Previous vs Current Window)",
        "",
        "| Dimension | Previous Rows | Current Rows | Drift Score | Top Movers |",
        "|-----------|---------------|--------------|-------------|------------|",
    ]
    for name, prev_ctr, curr_ctr, prev_n, curr_n in dimensions:
        score, movers = _drift_score(prev_ctr, curr_ctr)
        mover_parts = []
        for label, prev_p, curr_p, _ in movers[:3]:
            mover_parts.append(f"{label}:{prev_p*100:.1f}%->{curr_p*100:.1f}%")
        lines.append(
            f"| {name} | {prev_n} | {curr_n} | {score}% | {'; '.join(mover_parts) if mover_parts else '-'} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Interpretation",
            "",
            "- Drift > 25% usually indicates changed user/tool mix, provider routing, or suppression policy behavior.",
            "- Pair this panel with suppression replay to verify whether drift is beneficial or regressive.",
            "",
        ]
    )
    return "\n".join(lines)


def _latest_external_review_status() -> dict[str, Any]:
    reports_dir = _REPO_ROOT / "reports"
    if not reports_dir.exists():
        return {}
    candidates = sorted(
        reports_dir.glob("*_advisory_context_external_review.json"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    if not candidates:
        return {}
    path = candidates[0]
    payload = _read_json(path)
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    inconsistent = 0
    provider_errors = 0
    for row in results:
        if not isinstance(row, dict):
            continue
        response = _norm_text(row.get("response")).lower()
        ok = bool(row.get("ok"))
        if "execution error" in response:
            provider_errors += 1
            if ok:
                inconsistent += 1
    return {
        "path": str(path),
        "results": len(results),
        "provider_errors": provider_errors,
        "inconsistent_ok_flags": inconsistent,
    }


def _data_integrity_page(data: dict[int, dict[str, Any]]) -> str:
    decision_rows, decision_source, decision_path = _load_decision_rows(limit=20000)
    external_review = _latest_external_review_status()

    specs = [
        ("observe_hook_telemetry", _SD / "logs" / "observe_hook_telemetry.jsonl", True),
        ("queue_events", _SD / "queue" / "events.jsonl", True),
        ("advisory_engine_alpha", _SD / "advisory_engine_alpha.jsonl", True),
        ("advisory_decision_ledger", _SD / "advisory_decision_ledger.jsonl", False),
        ("advisory_emit", _SD / "advisory_emit.jsonl", False),
        ("advisory_quality_events", _SD / "advisor" / "advisory_quality_events.jsonl", True),
        ("helpfulness_events", _SD / "advisor" / "helpfulness_events.jsonl", True),
        ("advice_feedback_requests", _SD / "advice_feedback_requests.jsonl", True),
        ("advice_feedback", _SD / "advice_feedback.jsonl", True),
    ]

    lines = [
        "---",
        "title: Advisory Data Quality Integrity",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - integrity",
        "  - data-quality",
        "---",
        "",
        "# Advisory Data Quality Integrity",
        "",
        f"> {flow_link()} | [[stages/08-advisory|Stage 8: Advisory]]",
        "",
        "## File Integrity Matrix",
        "",
        "| Source | Exists | Parsed Rows (windowed) | Invalid Lines | Trace Coverage | Newest Timestamp | Freshness |",
        "|--------|--------|-----------------------|---------------|----------------|------------------|-----------|",
    ]
    now = time.time()
    blind_spots: list[str] = []
    for name, path, required in specs:
        rows, stats = _read_jsonl(path, max_rows=22000)
        exists = path.exists()
        newest_ts = max((_extract_ts(r) for r in rows), default=0.0)
        freshness_s = int(max(0.0, now - newest_ts)) if newest_ts > 0 else -1
        trace_rows = 0
        trace_field_rows = 0
        for row in rows:
            if any(k in row for k in ("trace_id", "outcome_trace_id", "trace")):
                trace_field_rows += 1
            if _trace_from_row(row):
                trace_rows += 1
        trace_pct = _fmt_pct(trace_rows, max(trace_field_rows, 1)) if trace_field_rows > 0 else "n/a"
        freshness_label = f"{freshness_s}s" if freshness_s >= 0 else "unknown"
        trace_cov_label = (
            f"{trace_pct} ({trace_rows}/{max(trace_field_rows, 1)})"
            if trace_field_rows > 0
            else "n/a"
        )
        lines.append(
            f"| {name} | {'yes' if exists else 'no'} | {fmt_num(len(rows))} | "
            f"{fmt_num(stats.get('invalid_lines', 0))} | {trace_cov_label} | "
            f"{_fmt_ts(newest_ts)} | {freshness_label} |"
        )
        if required and not exists:
            blind_spots.append(f"{name} missing")
        if stats.get("invalid_lines", 0) > 0:
            blind_spots.append(f"{name} has invalid jsonl lines")
        if trace_field_rows > 0 and (trace_rows / max(trace_field_rows, 1)) < 0.5:
            blind_spots.append(f"{name} trace coverage below 50%")
    lines.append("")

    lines.extend(
        [
            "## Decision Source Integrity",
            "",
            f"- Active decision source: `{decision_source}`",
            f"- Active decision path: `{decision_path}`",
            f"- Decision rows available: `{len(decision_rows)}`",
            "",
        ]
    )
    if decision_source != "advisory_decision_ledger":
        blind_spots.append("decision ledger missing; using fallback source")
        lines.append(
            "- Warning: decision ledger missing; observatory is using fallback source and should show lower confidence."
        )
        lines.append("")

    stage8 = (data.get(8) or {}) if isinstance(data.get(8), dict) else {}
    coverage_summary = stage8.get("advisory_rating_coverage_summary") or {}
    if isinstance(coverage_summary, dict) and coverage_summary:
        lines.extend(
            [
                "## Prompted-to-Rating Coverage Integrity",
                "",
                f"- Prompted total: `{coverage_summary.get('prompted_total', 0)}`",
                f"- Explicitly rated: `{coverage_summary.get('explicit_rated_total', 0)}`",
                f"- Known helpfulness: `{coverage_summary.get('known_helpful_total', 0)}`",
                f"- Explicit coverage gap: `{coverage_summary.get('explicit_gap', 0)}`",
                f"- Known-helpful gap: `{coverage_summary.get('known_helpful_gap', 0)}`",
                "",
            ]
        )
        if float(coverage_summary.get("known_helpful_rate_pct", 0.0) or 0.0) < 40.0:
            blind_spots.append("known helpfulness coverage below 40%")

    if external_review:
        lines.extend(
            [
                "## External Review Runtime Integrity",
                "",
                f"- Latest external review file: `{external_review.get('path')}`",
                f"- Provider result rows: `{external_review.get('results', 0)}`",
                f"- Provider execution-error rows: `{external_review.get('provider_errors', 0)}`",
                f"- Inconsistent ok=true with execution-error text: `{external_review.get('inconsistent_ok_flags', 0)}`",
                "",
            ]
        )
        if int(external_review.get("inconsistent_ok_flags", 0) or 0) > 0:
            blind_spots.append("external review result status inconsistent with error response")

    lines.append("## Context Blind Spots")
    lines.append("")
    if blind_spots:
        for item in sorted(set(blind_spots)):
            lines.append(f"- {item}")
    else:
        lines.append("- none detected from current integrity checks")
    lines.append("")
    return "\n".join(lines)


def _retrieval_route_forensics_page(detail_rows: int = 450) -> str:
    route_path = _SD / "advisor" / "retrieval_router.jsonl"
    semantic_path = _SD / "logs" / "semantic_retrieval.jsonl"
    route_rows, route_stats = _read_jsonl(route_path, max_rows=50000)
    semantic_rows, semantic_stats = _read_jsonl(semantic_path, max_rows=50000)

    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return int(default)

    def _semantic_empty_bucket(row: dict[str, Any]) -> str:
        candidates = _safe_int(row.get("semantic_candidates_count"), 0)
        final_results = row.get("final_results")
        final_count = len(final_results) if isinstance(final_results, list) else 0
        if final_count > 0:
            return "non_empty"
        if bool(row.get("embedding_available")) and candidates <= 0:
            return "embed_enabled_no_candidates"
        if (not bool(row.get("embedding_available"))) and candidates <= 0:
            return "no_embeddings_no_keyword_overlap"
        if candidates > 0 and final_count <= 0:
            return "gated_or_filtered_after_candidates"
        return "other_empty"

    route_reason_counter: Counter[tuple[str, str]] = Counter()
    tool_route_counter: Counter[tuple[str, str]] = Counter()
    empty_tool_counter: Counter[str] = Counter()
    total_tool_counter: Counter[str] = Counter()

    for row in route_rows:
        route = _norm_text(row.get("route") or "unknown").lower() or "unknown"
        reason = _norm_text(row.get("reason"))
        if not reason:
            reasons = row.get("reasons")
            if isinstance(reasons, list) and reasons:
                reason = _norm_text(reasons[0])
        if not reason:
            reason = "unknown"
        tool = _norm_text(row.get("tool") or row.get("tool_name") or "?")
        route_reason_counter[(route, reason)] += 1
        tool_route_counter[(tool, route)] += 1
        total_tool_counter[tool] += 1
        if route == "empty":
            empty_tool_counter[tool] += 1

    lines = [
        "---",
        "title: Retrieval Route Forensics",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - retrieval",
        "  - forensics",
        "  - context-first",
        "---",
        "",
        "# Retrieval Route Forensics (Context First)",
        "",
        f"> {flow_link()} | [[stages/08-advisory|Stage 8: Advisory]]",
        "",
        "## Data Scope",
        "",
        f"- Retrieval route source: `{route_path}`",
        f"- Retrieval route rows parsed: `{len(route_rows)}`",
        f"- Retrieval route invalid lines: `{route_stats.get('invalid_lines', 0)}`",
        f"- Semantic retrieval source: `{semantic_path}`",
        f"- Semantic retrieval rows parsed: `{len(semantic_rows)}`",
        f"- Semantic retrieval invalid lines: `{semantic_stats.get('invalid_lines', 0)}`",
        "",
        "## Route x Reason Distribution (Top 40)",
        "",
        "| Route | Reason | Count | Share |",
        "|-------|--------|-------|-------|",
    ]
    route_total = max(1, len(route_rows))
    for (route, reason), count in route_reason_counter.most_common(40):
        lines.append(f"| {route} | {reason} | {fmt_num(count)} | {_fmt_pct(count, route_total)} |")
    lines.append("")

    lines.extend(
        [
            "## Tool x Route Matrix (Top 30 Tools)",
            "",
            "| Tool | Total | Empty | Empty Rate | Top Routes |",
            "|------|-------|-------|------------|------------|",
        ]
    )
    for tool, total in total_tool_counter.most_common(30):
        empty_count = empty_tool_counter.get(tool, 0)
        top_routes = sorted(
            [(route, cnt) for (tool_name, route), cnt in tool_route_counter.items() if tool_name == tool],
            key=lambda item: item[1],
            reverse=True,
        )[:3]
        top_routes_text = "; ".join(f"{route}:{cnt}" for route, cnt in top_routes) if top_routes else "-"
        lines.append(
            f"| {tool} | {fmt_num(total)} | {fmt_num(empty_count)} | {_fmt_pct(empty_count, max(1, total))} | {top_routes_text} |"
        )
    lines.append("")

    ordered_route_rows = sorted(route_rows, key=_extract_ts, reverse=True)
    detailed = ordered_route_rows[: max(100, int(detail_rows))]
    lines.extend(
        [
            f"## Detailed Retrieval Rows (Latest {len(detailed)})",
            "",
            "| ts | tool | route | reason | complexity | active_insights | primary | returned | over_budget | route_ms | reasons | trace |",
            "|----|------|-------|--------|------------|-----------------|---------|----------|-------------|----------|---------|-------|",
        ]
    )
    for row in detailed:
        ts = _fmt_ts(_extract_ts(row))
        tool = _norm_text(row.get("tool") or row.get("tool_name") or "?")
        route = _norm_text(row.get("route") or "unknown").lower() or "unknown"
        reason = _norm_text(row.get("reason"))
        reasons = row.get("reasons")
        reasons_txt = ""
        if isinstance(reasons, list):
            reasons_txt = ", ".join(_norm_text(x) for x in reasons if _norm_text(x))[:140]
        if not reason:
            reason = _norm_text(reasons_txt.split(",")[0]) if reasons_txt else "unknown"
        complexity = _safe_int(row.get("complexity_score"), 0)
        active_insights = _safe_int(row.get("active_insights"), 0)
        primary = _safe_int(row.get("primary_count"), 0)
        returned = _safe_int(row.get("returned_count"), 0)
        over_budget = "yes" if bool(row.get("fast_path_over_budget")) else "no"
        route_ms = _safe_int(row.get("route_elapsed_ms"), 0)
        trace = _norm_text(row.get("trace_id"))[:24] or "-"
        lines.append(
            f"| {ts} | {tool} | {route} | {reason} | {complexity} | {active_insights} | "
            f"{primary} | {returned} | {over_budget} | {route_ms} | {reasons_txt or '-'} | {trace} |"
        )
    lines.append("")

    ordered_semantic = sorted(semantic_rows, key=_extract_ts, reverse=True)
    sem_detail = ordered_semantic[:350]
    lines.extend(
        [
            f"## Semantic Retrieval Diagnostics (Latest {len(sem_detail)})",
            "",
            "| ts | empty_bucket | embedding | candidates | raw | post_noise | post_similarity | post_fusion | rescue_used | elapsed_ms | intent_preview |",
            "|----|--------------|-----------|------------|-----|------------|-----------------|-------------|-------------|------------|----------------|",
        ]
    )
    for row in sem_detail:
        ts = _fmt_ts(_extract_ts(row))
        bucket = _semantic_empty_bucket(row)
        embedding = "yes" if bool(row.get("embedding_available")) else "no"
        candidates = _safe_int(row.get("semantic_candidates_count"), 0)
        raw_count = _safe_int(row.get("raw_result_count"), 0)
        post_noise = _safe_int(row.get("post_noise_count"), 0)
        post_similarity = _safe_int(row.get("post_similarity_count"), 0)
        post_fusion = _safe_int(row.get("post_fusion_count"), 0)
        rescue_used = "yes" if bool(row.get("rescue_used")) else "no"
        elapsed_ms = _safe_int(row.get("elapsed_ms"), 0)
        intent = _norm_text(row.get("intent"))[:120].replace("|", "\\|")
        lines.append(
            f"| {ts} | {bucket} | {embedding} | {candidates} | {raw_count} | {post_noise} | "
            f"{post_similarity} | {post_fusion} | {rescue_used} | {elapsed_ms} | {intent or '-'} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Hard Questions For Next Cycle",
            "",
            "- Which `empty_primary` rows had `active_insights > 10` but still returned zero candidates, and why?",
            "- Are generic rewrite intents (for example: `failure pattern and fix`) replacing high-signal context in retrieval queries?",
            "- For each high-empty tool, what % of rows are `embedding_available=false` vs `embed_enabled_no_candidates`?",
            "- Which suppression/threshold settings are discarding candidates after semantic retrieval (`gated_or_filtered_after_candidates` bucket)?",
            "- Which repeated traces are stuck in empty retrieval loops across multiple tools?",
            "",
        ]
    )
    return "\n".join(lines)


def generate_advisory_context_pages(data: dict[int, dict[str, Any]]) -> dict[str, str]:
    """Generate additional observatory pages for context-rich advisory diagnostics."""
    return {
        "advisory_trace_lineage.md": _trace_lineage_page(data),
        "advisory_unknown_helpfulness_burndown.md": _unknown_helpfulness_page(data),
        "advisory_suppression_replay.md": _suppression_replay_page(),
        "advisory_context_drift.md": _context_drift_page(),
        "advisory_data_integrity.md": _data_integrity_page(data),
        "retrieval_route_forensics.md": _retrieval_route_forensics_page(),
    }
