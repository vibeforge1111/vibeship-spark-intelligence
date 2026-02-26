"""Generate readability/navigation helper pages for the observatory."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple

_SNAPSHOT_FILE = ".observatory_snapshot.json"


def _fmt_ts(ts: float) -> str:
    if ts <= 0:
        return "-"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except Exception:
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except Exception:
        return int(default)


def _frontmatter(title: str, tags: list[str]) -> str:
    lines = ["---", f"title: {title}", "tags:"]
    for tag in tags:
        lines.append(f"  - {tag}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def collect_metrics_snapshot(data: Dict[int, Dict[str, Any]], *, now_ts: float | None = None) -> Dict[str, Any]:
    """Collect a compact metrics snapshot used for cross-generation diffing."""
    now = float(now_ts if now_ts is not None else time.time())
    pipeline_ts = _as_float((data.get(3) or {}).get("last_cycle_ts"), 0.0)
    pipeline_age_s = max(0.0, now - pipeline_ts) if pipeline_ts > 0 else -1.0
    return {
        "generated_ts": now,
        "queue_pending": _as_int((data.get(2) or {}).get("estimated_pending"), 0),
        "pipeline_last_cycle_ts": pipeline_ts,
        "pipeline_age_s": pipeline_age_s,
        "meta_pass_rate": _as_float((data.get(5) or {}).get("pass_rate"), 0.0),
        "cognitive_insights": _as_int((data.get(6) or {}).get("total_insights"), 0),
        "eidos_distillations": _as_int((data.get(7) or {}).get("distillations"), 0),
        "advisory_given": _as_int((data.get(8) or {}).get("total_advice_given"), 0),
        "decision_emit_rate": _as_float((data.get(8) or {}).get("decision_emit_rate"), 0.0),
        "feedback_follow_rate": _as_float((data.get(8) or {}).get("feedback_follow_rate"), 0.0),
    }


def load_previous_snapshot(obs_dir: Path) -> Dict[str, Any]:
    """Load prior observatory snapshot if available."""
    path = obs_dir / _SNAPSHOT_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return data if isinstance(data, dict) else {}


def save_snapshot(obs_dir: Path, snapshot: Dict[str, Any]) -> None:
    """Persist latest snapshot for next regeneration diff."""
    path = obs_dir / _SNAPSHOT_FILE
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")


def _signed(value: float, *, decimals: int = 1, suffix: str = "") -> str:
    if abs(value) < (0.5 * (10 ** -decimals)):
        value = 0.0
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}{suffix}"


def generate_start_here(data: Dict[int, Dict[str, Any]], current_snapshot: Dict[str, Any]) -> str:
    """Create a guided reading page for humans."""
    queue_pending = _as_int(current_snapshot.get("queue_pending"), 0)
    pipeline_ts = _as_float(current_snapshot.get("pipeline_last_cycle_ts"), 0.0)
    eidos_count = _as_int(current_snapshot.get("eidos_distillations"), 0)
    emit_rate = _as_float(current_snapshot.get("decision_emit_rate"), 0.0)
    follow_rate = _as_float(current_snapshot.get("feedback_follow_rate"), 0.0)

    lines = []
    lines.append(_frontmatter("Start Here", ["observatory", "navigation", "onboarding"]))
    lines.append("# Start Here")
    lines.append("")
    lines.append(f"> Generated: {_fmt_ts(time.time())}")
    lines.append("> This page helps you understand Spark Observatory without prior context.")
    lines.append("")

    lines.append("## 90-Second Orientation")
    lines.append("")
    lines.append("- Spark captures events from your coding workflow and turns them into reusable intelligence.")
    lines.append("- Advice is emitted only after retrieval, quality checks, and suppression controls.")
    lines.append("- You can inspect every stage from capture to advisory outcome in this vault.")
    lines.append("")

    lines.append("## Current Snapshot")
    lines.append("")
    lines.append("| Signal | Current |")
    lines.append("|---|---:|")
    lines.append(f"| Queue pending | {queue_pending} |")
    lines.append(f"| Last pipeline cycle | {_fmt_ts(pipeline_ts)} |")
    lines.append(f"| EIDOS distillations | {eidos_count} |")
    lines.append(f"| Advisory emit rate | {emit_rate:.1f}% |")
    lines.append(f"| Implicit follow rate | {follow_rate:.1f}% |")
    lines.append("")

    lines.append("## Read In This Order")
    lines.append("")
    lines.append("1. [[flow|Intelligence Flow]] - one-page map of the system.")
    lines.append("2. [[system_flow_comprehensive|System Flow Comprehensive]] - full story with real examples.")
    lines.append("3. [[stages/08-advisory|Stage 8 - Advisory]] - advisory-specific health + source outcomes.")
    lines.append("4. [[advisory_reverse_engineering|Advisory Reverse Engineering]] - suppression logic and tuning levers.")
    lines.append("5. [[troubleshooting_by_symptom|Troubleshooting by Symptom]] - fast diagnosis by failure pattern.")
    lines.append("6. [[changes_since_last_regen|Changes Since Last Regen]] - metric deltas from previous generation.")
    lines.append("7. [[topic_finder|Topic Finder]] - jump to exact page for a specific question.")
    lines.append("8. [[glossary|Glossary]] - term definitions for moving parts.")
    lines.append("")

    lines.append("## Suggested Daily Routine (10-15 min)")
    lines.append("")
    lines.append("1. Open [[flow]] for current status.")
    lines.append("2. Check [[troubleshooting_by_symptom]] and [[system_flow_operator_playbook]] triage tables.")
    lines.append("3. If advisory is weak, inspect [[explore/decisions/_index|Decision Ledger]], [[explore/feedback/_index|Implicit Feedback]], and [[explore/helpfulness/_index|Helpfulness Calibration]].")
    lines.append("4. If upstream quality is weak, inspect [[stages/05-meta-ralph|Meta-Ralph]] and [[stages/06-cognitive-learner|Cognitive]].")
    lines.append("5. Review [[changes_since_last_regen]] to validate whether fixes moved metrics.")
    lines.append("")

    lines.append("## Regenerate")
    lines.append("")
    lines.append("- `python scripts/generate_observatory.py --force`")
    lines.append("")
    return "\n".join(lines)


def generate_topic_finder() -> str:
    """Create a question-to-page lookup index."""
    lines = []
    lines.append(_frontmatter("Topic Finder", ["observatory", "navigation", "index"]))
    lines.append("# Topic Finder")
    lines.append("")
    lines.append("> Use this index when you have a specific question and need the fastest path to evidence.")
    lines.append("")
    lines.append("| If you want to know... | Open this page | What to inspect first |")
    lines.append("|---|---|---|")
    lines.append("| Is Spark capture alive right now? | [[stages/01-event-capture|Stage 1 - Event Capture]] | Last cycle + errors |")
    lines.append("| Is queue building up? | [[stages/02-queue|Stage 2 - Queue]] | pending depth + overflow |")
    lines.append("| Is pipeline processing events? | [[stages/03-pipeline|Stage 3 - Pipeline]] | last cycle age + processing rate |")
    lines.append("| Are memories being captured? | [[stages/04-memory-capture|Stage 4 - Memory Capture]] | pending items + category mix |")
    lines.append("| Are low-quality learnings being filtered? | [[stages/05-meta-ralph|Stage 5 - Meta-Ralph]] | pass rate + weak dimensions |")
    lines.append("| What intelligence is available now? | [[stages/06-cognitive-learner|Stage 6 - Cognitive]] | top insights + reliability |")
    lines.append("| What did EIDOS distill recently? | [[stages/07-eidos|Stage 7 - EIDOS]] | latest distillations + confidence |")
    lines.append("| Why advice was blocked/suppressed? | [[explore/decisions/_index|Decision Ledger]] | outcome + suppressed reasons |")
    lines.append("| Are users following advisories? | [[explore/feedback/_index|Implicit Feedback]] | followed vs ignored signals |")
    lines.append("| How accurate is helpfulness labeling? | [[explore/helpfulness/_index|Helpfulness Calibration]] | watcher labels, conflicts, and LLM review queue health |")
    lines.append("| Is Mind helping cross-session? | [[system_flow_comprehensive|System Flow Comprehensive]] | mind sync + mind source examples |")
    lines.append("| Where are advisory bottlenecks? | [[advisory_reverse_engineering|Advisory Reverse Engineering]] | suppression buckets + top reasons |")
    lines.append("| How do I debug by symptom? | [[troubleshooting_by_symptom|Troubleshooting by Symptom]] | symptom table + first commands |")
    lines.append("| What changed after my tuning edits? | [[changes_since_last_regen|Changes Since Last Regen]] | metric deltas + movement status |")
    lines.append("| Are writes going through validate_and_store? | [[stages/05-meta-ralph|Stage 5 - Meta-Ralph]] | validate_and_store telemetry section |")
    lines.append("| Is fallback budget limiting emissions? | [[stages/08-advisory|Stage 8 - Advisory]] | fallback budget subsection |")
    lines.append("| What should we build next? | [[../Advisory Implementation Tasks|Advisory Implementation Tasks]] | task backlog + acceptance criteria |")
    lines.append("")
    lines.append("## Power Navigation")
    lines.append("")
    lines.append("- [[flow|Main Dashboard]]")
    lines.append("- [[start_here|Start Here]]")
    lines.append("- [[glossary|Glossary]]")
    lines.append("")
    return "\n".join(lines)


def generate_glossary() -> str:
    """Create a glossary for observatory/system terms."""
    terms = [
        ("Advisory Engine", "The pre-tool orchestrator (`lib/advisory_engine.py`) that retrieves, gates, dedupes, synthesizes, and emits advice."),
        ("Advisory Gate", "Policy layer (`lib/advisory_gate.py`) that decides emit vs suppress based on phase, score, cooldowns, and relevance."),
        ("Advisory Decision Ledger", "JSONL audit of advisory outcomes (`emitted`, `blocked`, etc.) at `~/.spark/advisory_decision_ledger.jsonl`."),
        ("Advice Source", "Origin of an advisory item (for example: `cognitive`, `eidos`, `mind`, `bank`, `baseline`, `chip`)."),
        ("Baseline Advice", "Deterministic safety/default guidance used when context-specific retrieval is weak."),
        ("Bridge Cycle", "Background worker cycle (`lib/bridge_cycle.py`) that runs memory/pipeline/sync operations."),
        ("Category Cooldown Multiplier", "Scale factor that adjusts suppression windows for specific advisory categories."),
        ("Chip", "Domain-specific intelligence module that contributes retrieval candidates."),
        ("Cognitive Insight", "Persisted learning item with reliability metadata in `~/.spark/cognitive_insights.json`."),
        ("Deduplication", "Suppression of repeated advice via text/id signatures (session and global scope)."),
        ("EIDOS", "Episodic intelligence subsystem storing episodes/steps/distillations in `~/.spark/eidos.db`."),
        ("Emit Rate", "Share of advisory decisions that result in emitted guidance."),
        ("Follow Rate", "Share of implicit feedback marked as followed/helpful after advisory delivery."),
        ("Global Dedupe", "Cross-session anti-repeat mechanism in `lib/advisory_engine.py`."),
        ("Hook", "Claude Code event callback (`hooks/observe.py`) for pre/post tool and prompt events."),
        ("Implicit Feedback", "Post-tool success/failure signals linked to recent advisory exposure."),
        ("Memory Capture", "Extraction of high-signal memory candidates from events (`lib/memory_capture.py`)."),
        ("Mind", "Optional external durable memory service accessed through `lib/mind_bridge.py`."),
        ("Mind Sync", "Bridge-cycle process that pushes selected local insights to Mind."),
        ("Packet", "Cached advisory bundle keyed by context for fast reuse (`lib/advisory_packet_store.py`)."),
        ("Pipeline", "Core event processing stage that generates structured learning outputs."),
        ("Promotion", "Process that promotes validated insights to project docs/rules (`lib/promoter.py`)."),
        ("Queue", "Append-only event buffer at `~/.spark/queue/events.jsonl`."),
        ("Shown TTL", "Time window during which recently shown advice is suppressed from re-emission."),
        ("Task Phase", "Inferred execution phase (exploration/planning/implementation/testing/debugging/deployment)."),
        ("Tool Cooldown", "Per-tool temporary suppression window to reduce advisory spam."),
        ("Validate and Store", "Unified write gate (`lib/validate_and_store.py`) that routes every cognitive insight through Meta-Ralph before storage. Fail-open: quarantines on error, then stores anyway."),
        ("Noise Patterns", "Shared module (`lib/noise_patterns.py`) consolidating noise detection regex from 5 locations into one importable set."),
        ("Fallback Budget", "Rate-limiter on quick/packet fallback emissions (`fallback_budget_cap` / `fallback_budget_window` in tuneables advisory_engine section)."),
        ("Flow Tuneables", "The `flow` tuneable section controlling unified write-path behavior, notably `validate_and_store_enabled`."),
        ("Fail-Open Quarantine", "On Meta-Ralph exception during validate_and_store: the insight is logged to `~/.spark/insight_quarantine.jsonl` AND still stored in cognitive (true fail-open)."),
        ("Rejection Telemetry", "Per-reason counters at every advisory exit path, flushed to `~/.spark/advisory_rejection_telemetry.json`."),
        ("Source Boosts", "Auto-tuner multipliers per advice source, clamped to [0.8, 1.1] and stored in tuneables `auto_tuner.source_boosts`."),
        ("Pre-Alpha Era", "Fresh data start after Intelligence Flow Evolution. Legacy data archived to `~/.spark/archive/legacy_*/`. Era marker at `~/.spark/era.json`."),
        ("Era Marker", "The file `~/.spark/era.json` records when the current era started and where legacy data was archived. Created by `scripts/start_alpha.py`. Current era: pre-alpha."),
    ]
    lines = []
    lines.append(_frontmatter("Glossary", ["observatory", "glossary", "reference"]))
    lines.append("# Glossary")
    lines.append("")
    lines.append("> Shared language for Spark Observatory and advisory diagnostics.")
    lines.append("")
    lines.append("| Term | Meaning |")
    lines.append("|---|---|")
    for term, meaning in terms:
        lines.append(f"| {term} | {meaning} |")
    lines.append("")
    lines.append("## Related")
    lines.append("")
    lines.append("- [[start_here|Start Here]]")
    lines.append("- [[topic_finder|Topic Finder]]")
    lines.append("- [[flow|Intelligence Flow]]")
    lines.append("")
    return "\n".join(lines)


def generate_troubleshooting_by_symptom(current_snapshot: Dict[str, Any]) -> str:
    """Create a symptom-driven operator troubleshooting page."""
    queue_pending = _as_int(current_snapshot.get("queue_pending"), 0)
    pipeline_age_s = _as_float(current_snapshot.get("pipeline_age_s"), -1.0)
    emit_rate = _as_float(current_snapshot.get("decision_emit_rate"), 0.0)
    follow_rate = _as_float(current_snapshot.get("feedback_follow_rate"), 0.0)
    meta_pass = _as_float(current_snapshot.get("meta_pass_rate"), 0.0)

    lines = []
    lines.append(_frontmatter("Troubleshooting by Symptom", ["observatory", "operations", "troubleshooting"]))
    lines.append("# Troubleshooting by Symptom")
    lines.append("")
    lines.append(f"> Generated: {_fmt_ts(time.time())}")
    lines.append("> Use this when behavior feels wrong and you need the fastest path to root cause.")
    lines.append("")

    lines.append("## Current Risk Flags")
    lines.append("")
    flags: list[str] = []
    if queue_pending >= 20000:
        flags.append(f"- Queue backlog is critical ({queue_pending}).")
    elif queue_pending >= 5000:
        flags.append(f"- Queue backlog is elevated ({queue_pending}).")
    if pipeline_age_s < 0:
        flags.append("- Pipeline cycle timestamp is missing.")
    elif pipeline_age_s > 600:
        flags.append(f"- Pipeline appears stale ({int(pipeline_age_s)}s since last cycle).")
    if meta_pass < 15.0:
        flags.append(f"- Meta-Ralph pass rate is low ({meta_pass:.1f}%).")
    if emit_rate < 25.0 and follow_rate >= 40.0:
        flags.append(f"- Emissions may be over-constrained (emit {emit_rate:.1f}% vs follow {follow_rate:.1f}%).")
    if not flags:
        flags.append("- No high-severity risk flags from current snapshot.")
    lines.extend(flags)
    lines.append("")

    lines.append("## Symptom Lookup")
    lines.append("")
    lines.append("| Symptom | First page | Likely cause | First check command |")
    lines.append("|---|---|---|---|")
    lines.append("| Advice feels too quiet | [[stages/08-advisory|Stage 8 - Advisory]] | Over-suppression from TTL/dedupe/cooldowns | `python scripts/generate_observatory.py --force` |")
    lines.append("| Advice repeats too much | [[advisory_reverse_engineering|Advisory Reverse Engineering]] | Weak dedupe or short repeat cooldown | `python -c \"import json, pathlib; p=pathlib.Path.home()/'.spark'/'advisory_decision_ledger.jsonl'; print(len(p.read_text().splitlines()))\"` |")
    lines.append("| High rejection rate or quarantine spikes | [[stages/05-meta-ralph|Stage 5 - Meta-Ralph]] | Meta-Ralph threshold drift or flow.validate_and_store_enabled toggle | `python -c \"import json, pathlib; t=pathlib.Path.home()/'.spark'/'validate_and_store_telemetry.json'; print(json.loads(t.read_text()) if t.exists() else 'no telemetry')\"` |")
    lines.append("| Pipeline appears frozen | [[stages/03-pipeline|Stage 3 - Pipeline]] | Bridge cycle not running or crash loop | `python -c \"import json, pathlib; p=pathlib.Path.home()/'.spark'/'pipeline_state.json'; print(json.loads(p.read_text()))\"` |")
    lines.append("| Queue keeps growing | [[stages/02-queue|Stage 2 - Queue]] | Intake exceeds consumption, or worker stale | `python -c \"import lib.queue as q; print(q.get_queue_stats())\"` |")
    lines.append("| Advice quality feels weak | [[stages/05-meta-ralph|Stage 5 - Meta-Ralph]] | Low-quality insights passing/overfitting | `python -m pytest -q tests/test_safety_guardrails.py tests/test_sparkd_hardening.py` |")
    lines.append("| Cross-session recall seems weak | [[system_flow_comprehensive|System Flow Comprehensive]] | Mind sync stale or low salience coverage | `python -c \"import json, pathlib; p=pathlib.Path.home()/'.spark'/'mind_sync_state.json'; print(json.loads(p.read_text()))\"` |")
    lines.append("")

    lines.append("## Escalation Path")
    lines.append("")
    lines.append("1. Start at [[flow|Intelligence Flow]] for global health context.")
    lines.append("2. Jump to the relevant stage page from the table above.")
    lines.append("3. Validate with [[explore/decisions/_index|Decision Ledger]], [[explore/feedback/_index|Implicit Feedback]], and [[explore/helpfulness/_index|Helpfulness Calibration]].")
    lines.append("4. Apply tuneable/task changes and verify movement in [[changes_since_last_regen|Changes Since Last Regen]].")
    lines.append("")
    return "\n".join(lines)


def generate_changes_since_last_regen(
    current_snapshot: Dict[str, Any],
    previous_snapshot: Dict[str, Any],
) -> str:
    """Create a metric diff page between current and previous generation."""
    lines = []
    lines.append(_frontmatter("Changes Since Last Regen", ["observatory", "history", "diff"]))
    lines.append("# Changes Since Last Regen")
    lines.append("")
    lines.append(f"> Current generated: {_fmt_ts(_as_float(current_snapshot.get('generated_ts'), 0.0))}")
    prev_ts = _as_float(previous_snapshot.get("generated_ts"), 0.0) if previous_snapshot else 0.0
    lines.append(f"> Previous generated: {_fmt_ts(prev_ts)}")
    lines.append("")

    if not previous_snapshot:
        lines.append("No prior snapshot found. This page will show deltas after the next regeneration.")
        lines.append("")
        lines.append("## Tracked Metrics")
        lines.append("")
        lines.append(f"- Queue pending: {_as_int(current_snapshot.get('queue_pending'), 0)}")
        lines.append(f"- Pipeline age: {_as_int(current_snapshot.get('pipeline_age_s'), 0)}s")
        lines.append(f"- Meta-Ralph pass rate: {_as_float(current_snapshot.get('meta_pass_rate'), 0.0):.1f}%")
        lines.append(f"- Cognitive insights: {_as_int(current_snapshot.get('cognitive_insights'), 0)}")
        lines.append(f"- EIDOS distillations: {_as_int(current_snapshot.get('eidos_distillations'), 0)}")
        lines.append(f"- Advisory emit rate: {_as_float(current_snapshot.get('decision_emit_rate'), 0.0):.1f}%")
        lines.append(f"- Implicit follow rate: {_as_float(current_snapshot.get('feedback_follow_rate'), 0.0):.1f}%")
        lines.append("")
        return "\n".join(lines)

    rows = [
        ("Queue pending", "queue_pending", 0, "count"),
        ("Pipeline age", "pipeline_age_s", 0, "seconds"),
        ("Meta-Ralph pass rate", "meta_pass_rate", 1, "percent"),
        ("Cognitive insights", "cognitive_insights", 0, "count"),
        ("EIDOS distillations", "eidos_distillations", 0, "count"),
        ("Advisory given", "advisory_given", 0, "count"),
        ("Advisory emit rate", "decision_emit_rate", 1, "percent"),
        ("Implicit follow rate", "feedback_follow_rate", 1, "percent"),
    ]

    lines.append("## Metric Deltas")
    lines.append("")
    lines.append("| Metric | Previous | Current | Delta | Direction |")
    lines.append("|---|---:|---:|---:|---|")
    for label, key, decimals, unit in rows:
        prev = _as_float(previous_snapshot.get(key), 0.0)
        cur = _as_float(current_snapshot.get(key), 0.0)
        delta = cur - prev
        if unit == "percent":
            prev_text = f"{prev:.1f}%"
            cur_text = f"{cur:.1f}%"
            delta_text = _signed(delta, decimals=1, suffix=" pp")
        elif unit == "seconds":
            prev_text = f"{int(prev)}s"
            cur_text = f"{int(cur)}s"
            delta_text = _signed(delta, decimals=0, suffix="s")
        else:
            prev_text = f"{int(prev)}"
            cur_text = f"{int(cur)}"
            delta_text = _signed(delta, decimals=0)
        if delta < 0:
            direction = "down"
        elif delta > 0:
            direction = "up"
        else:
            direction = "flat"
        lines.append(f"| {label} | {prev_text} | {cur_text} | {delta_text} | {direction} |")
    lines.append("")

    lines.append("## Interpretation")
    lines.append("")
    lines.append("- Use this page after tuneable/code changes to confirm movement.")
    lines.append("- For quality regressions, open [[system_flow_operator_playbook|Operator Playbook]] and [[advisory_reverse_engineering|Advisory Reverse Engineering]].")
    lines.append("- For throughput regressions, inspect [[stages/02-queue|Queue]] and [[stages/03-pipeline|Pipeline]].")
    lines.append("")
    return "\n".join(lines)


def generate_readability_pack(
    data: Dict[int, Dict[str, Any]],
    *,
    current_snapshot: Dict[str, Any],
    previous_snapshot: Dict[str, Any],
) -> Iterator[Tuple[str, str]]:
    """Yield readability page files."""
    yield ("start_here.md", generate_start_here(data, current_snapshot))
    yield ("topic_finder.md", generate_topic_finder())
    yield ("glossary.md", generate_glossary())
    yield ("troubleshooting_by_symptom.md", generate_troubleshooting_by_symptom(current_snapshot))
    yield ("changes_since_last_regen.md", generate_changes_since_last_regen(current_snapshot, previous_snapshot))
