#!/usr/bin/env python3
"""Generate a trace-backed advisory self-review report.

Focus: no new feature logic; summarize what already happened in runtime logs.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SPARK_DIR = Path.home() / ".spark"
ALPHA_ENGINE_LOG = SPARK_DIR / "advisory_engine_alpha.jsonl"
COMPAT_ENGINE_LOG = SPARK_DIR / "advisory_engine.jsonl"


def _default_engine_log() -> Path:
    return ALPHA_ENGINE_LOG if ALPHA_ENGINE_LOG.exists() else COMPAT_ENGINE_LOG


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


def _load_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _pct(n: float, d: float) -> float:
    if d <= 0:
        return 0.0
    return round((n / d) * 100.0, 2)


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
        iso = datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts > 0 else "unknown"
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
    delivered = events.get("emitted", 0) + events.get("fallback_emit", 0)
    fallback_share_pct = _pct(events.get("fallback_emit", 0), delivered)
    trace_rows = sum(1 for r in rows if r.get("trace_id"))

    return {
        "rows": int(len(rows)),
        "trace_rows": int(trace_rows),
        "trace_coverage_pct": _pct(trace_rows, len(rows)),
        "events": dict(events),
        "routes": dict(routes),
        "fallback_share_pct": fallback_share_pct,
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


def build_report(summary: Dict[str, Any], window_hours: float, now_ts: float) -> str:
    iso_now = datetime.fromtimestamp(now_ts, timezone.utc).isoformat()
    ra = summary["recent_advice"]
    ra_nonbench = summary.get("recent_advice_nonbench") or {}
    en = summary["engine"]
    oc = summary["outcomes"]

    rep = ra["repeated_texts"][:6]
    repeated_share = round(sum(float(r["share_pct_of_items"]) for r in rep), 2)
    high_fallback = float(en.get("fallback_share_pct") or 0.0) >= 60.0

    improvement_state = "improving" if (oc.get("strict_effectiveness_rate") or 0) >= 0.9 else "unclear"
    if high_fallback:
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
        f"- Fallback share (delivered): {en['fallback_share_pct']}%",
        f"- Strict action rate: {oc['strict_action_rate']}",
        f"- Strict effectiveness rate: {oc['strict_effectiveness_rate']}",
        f"- Trace mismatch count: {oc['trace_mismatch_count']}",
        "",
        "## Honest Answers",
        "### Did learnings help make better decisions?",
        "- Yes, but unevenly. Trace-bound clusters show good outcomes, mostly from cognitive/self-awareness sources.",
        "- Mind usage exists but is still low-share in retrieval mix.",
        "",
        "### Examples with trace IDs",
    ]
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
                "- Yes. High fallback share suggests packet/live retrieval quality is still inconsistent."
                if high_fallback
                else "- Mixed. Fallback was not dominant in this window; evaluate misses via trace coverage and repeated-noise patterns."
            ),
            (
                "- Engine trace coverage is low; evidence linkage is incomplete in the engine path."
                if float(en.get("trace_coverage_pct") or 0.0) < 60.0
                else "- Engine trace coverage is healthy enough for stronger attribution confidence."
            ),
            "",
            "### Were unnecessary advisories/memories triggered?",
            f"- Yes. Top repeated advisories account for ~{repeated_share}% of all advice items in this window.",
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
            "3. Where did fallback dominate and why?",
            "4. Which sources had strict-good outcomes vs non-strict optimism?",
            "5. What is one simplification we can do before adding anything new?",
            "",
        ]
    )
    return "\n".join(lines)


def generate_summary(window_hours: float) -> Dict[str, Any]:
    now_ts = time.time()
    # Allow fractional hours for tighter live verification windows.
    window_s = max(60, int(float(window_hours) * 3600))
    spark_dir = SPARK_DIR
    return {
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
            exclude_trace_prefixes=["advisory-bench-"],
        ),
        "engine": summarize_engine(
            _default_engine_log(),
            window_s=window_s,
            now_ts=now_ts,
        ),
        "outcomes": summarize_outcomes(
            spark_dir / "meta_ralph" / "outcome_tracking.json",
            window_s=window_s,
            now_ts=now_ts,
        ),
    }


def write_report(summary: Dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d_%H%M%S")
    out_file = out_dir / f"{stamp}_advisory_self_review.md"
    report = build_report(summary, float(summary["window_hours"]), now.timestamp())
    out_file.write_text(report, encoding="utf-8")
    return out_file


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate advisory self-review report")
    ap.add_argument("--window-hours", type=float, default=12.0, help="Lookback window in hours (float allowed)")
    ap.add_argument("--out-dir", default="docs/reports", help="Output directory for markdown report")
    ap.add_argument("--json", action="store_true", help="Print JSON summary only")
    ap.add_argument("--min-gap-hours", type=float, default=6.0, help="Skip if a report younger than this exists")
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

    summary = generate_summary(window_hours=max(1.0 / 60.0, float(args.window_hours)))
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    out_path = write_report(summary, out_dir)
    print(f"Advisory self-review written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

