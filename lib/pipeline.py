"""
Spark Processing Pipeline: Adaptive, priority-aware event processing.

Replaces the shallow "read last 40 events" approach with a production-grade
pipeline that:

1. Processes events in priority order (failures/prompts first)
2. Consumes processed events so the queue stays bounded
3. Adapts batch size based on queue depth (backpressure)
4. Extracts deep learnings from event batches (tool effectiveness,
   error patterns, session workflows)
5. Emits processing health metrics for observability
6. Auto-tunes processing frequency based on throughput

Design Principles:
- Never lose events (consume only after successful processing)
- Never slow down the hooks (all processing is async)
- Maximize learning yield per batch (smart aggregation)
- Keep queue depth stable (consume >= produce)
"""

from __future__ import annotations

import json
import os
import time
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib.queue import (
    EventType,
    SparkEvent,
    EventPriority,
    classify_event_priority,
    consume_processed,
    count_events,
    read_events,
)
from lib.diagnostics import log_debug


# ============= Configuration =============

# Batch size bounds for auto-tuning
# DEFAULT_BATCH_SIZE is overridden by tuneables.json → values.queue_batch_size
MIN_BATCH_SIZE = 50
MAX_BATCH_SIZE = 1000
DEFAULT_BATCH_SIZE = 200


def _load_pipeline_config() -> None:
    """Load pipeline tuneables via config_authority resolve_section."""
    global DEFAULT_BATCH_SIZE
    try:
        from .config_authority import resolve_section
        tuneables = Path.home() / ".spark" / "tuneables.json"
        cfg = resolve_section("values", runtime_path=tuneables).data
        if isinstance(cfg, dict) and "queue_batch_size" in cfg:
            batch = int(cfg["queue_batch_size"])
            DEFAULT_BATCH_SIZE = max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, batch))
    except Exception:
        pass


_load_pipeline_config()


def reload_pipeline_from(cfg: Dict[str, Any]) -> None:
    """Hot-reload pipeline batch size from coordinator-supplied 'values' section."""
    global DEFAULT_BATCH_SIZE
    if not isinstance(cfg, dict):
        return
    if "queue_batch_size" in cfg:
        try:
            batch = int(cfg["queue_batch_size"])
            DEFAULT_BATCH_SIZE = max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, batch))
        except (ValueError, TypeError):
            pass


try:
    from .tuneables_reload import register_reload as _pipeline_register
    _pipeline_register("values", reload_pipeline_from, label="pipeline.reload_from")
except ImportError:
    pass

# Backpressure thresholds
QUEUE_HEALTHY = 200       # Below this, normal processing
QUEUE_ELEVATED = 500      # Increase batch size
QUEUE_CRITICAL = 2000     # Maximum batch size + drain mode

# Pipeline section globals — loaded from tuneables.json → "pipeline" section
# with env var overrides via config_authority.
IMPORTANCE_SAMPLING_ENABLED = False
LOW_PRIORITY_KEEP_RATE = 0.25
MACROS_ENABLED = False
MACRO_MIN_COUNT = 3
MIN_INSIGHTS_FLOOR = 1
FLOOR_EVENTS_THRESHOLD = 20
FLOOR_SOFT_MIN_EVENTS = 2

try:
    from .config_authority import env_bool, env_int, env_float

    _PIPELINE_ENV_OVERRIDES = {
        "importance_sampling_enabled": env_bool("SPARK_PIPELINE_IMPORTANCE_SAMPLING"),
        "low_priority_keep_rate": env_float("SPARK_PIPELINE_LOW_KEEP_RATE", lo=0.0, hi=1.0),
        "macros_enabled": env_bool("SPARK_MACROS_ENABLED"),
        "macro_min_count": env_int("SPARK_MACRO_MIN_COUNT", lo=2, hi=20),
        "min_insights_floor": env_int("SPARK_PIPELINE_MIN_INSIGHTS_FLOOR", lo=0, hi=3),
        "floor_events_threshold": env_int("SPARK_PIPELINE_MIN_INSIGHTS_EVENTS", lo=1, hi=200),
        "floor_soft_min_events": env_int("SPARK_PIPELINE_SOFT_MIN_INSIGHTS_EVENTS", lo=1, hi=50),
    }
except ImportError:
    _PIPELINE_ENV_OVERRIDES = {}


def _apply_pipeline_section(cfg: Dict[str, Any]) -> None:
    """Set pipeline-section globals from a resolved dict."""
    global IMPORTANCE_SAMPLING_ENABLED, LOW_PRIORITY_KEEP_RATE
    global MACROS_ENABLED, MACRO_MIN_COUNT
    global MIN_INSIGHTS_FLOOR, FLOOR_EVENTS_THRESHOLD, FLOOR_SOFT_MIN_EVENTS
    if not isinstance(cfg, dict):
        return
    if "importance_sampling_enabled" in cfg:
        IMPORTANCE_SAMPLING_ENABLED = bool(cfg["importance_sampling_enabled"])
    if "low_priority_keep_rate" in cfg:
        LOW_PRIORITY_KEEP_RATE = max(0.0, min(1.0, float(cfg["low_priority_keep_rate"])))
    if "macros_enabled" in cfg:
        MACROS_ENABLED = bool(cfg["macros_enabled"])
    if "macro_min_count" in cfg:
        MACRO_MIN_COUNT = max(2, min(20, int(cfg["macro_min_count"])))
    if "min_insights_floor" in cfg:
        MIN_INSIGHTS_FLOOR = max(0, min(3, int(cfg["min_insights_floor"])))
    if "floor_events_threshold" in cfg:
        FLOOR_EVENTS_THRESHOLD = max(1, min(200, int(cfg["floor_events_threshold"])))
    if "floor_soft_min_events" in cfg:
        FLOOR_SOFT_MIN_EVENTS = max(1, min(50, int(cfg["floor_soft_min_events"])))


def _load_pipeline_section_config() -> None:
    """Load pipeline-section tuneables via config_authority resolve_section."""
    try:
        from .config_authority import resolve_section
        tuneables = Path.home() / ".spark" / "tuneables.json"
        cfg = resolve_section(
            "pipeline", runtime_path=tuneables, env_overrides=_PIPELINE_ENV_OVERRIDES,
        ).data
        _apply_pipeline_section(cfg)
    except Exception as exc:
        import logging as _pl_logging
        _pl_logging.getLogger("spark.pipeline").debug(
            "Failed to load pipeline section config: %s", exc,
        )


_load_pipeline_section_config()

try:
    from lib.tuneables_reload import register_reload as _pipeline_section_register
    _pipeline_section_register("pipeline", _apply_pipeline_section, label="pipeline.reload_section")
except ImportError:
    pass

# Processing health metrics file
PIPELINE_STATE_FILE = Path.home() / ".spark" / "pipeline_state.json"
PIPELINE_METRICS_FILE = Path.home() / ".spark" / "pipeline_metrics.json"


@dataclass
class ProcessingMetrics:
    """Metrics from a single processing cycle."""
    cycle_start: float = 0.0
    cycle_duration_ms: float = 0.0
    events_read: int = 0
    events_processed: int = 0
    events_consumed: int = 0
    events_remaining: int = 0
    batch_size_used: int = 0

    # Learning yield
    patterns_detected: int = 0
    insights_created: int = 0
    tool_effectiveness_updates: int = 0
    error_patterns_found: int = 0
    session_workflows_analyzed: int = 0

    # Priority breakdown
    high_priority_processed: int = 0
    medium_priority_processed: int = 0
    low_priority_processed: int = 0

    # Health indicators
    queue_depth_before: int = 0
    queue_depth_after: int = 0
    processing_rate_eps: float = 0.0  # events per second
    backpressure_level: str = "healthy"

    errors: List[str] = field(default_factory=list)
    distillation_debug: Dict[str, Any] = field(default_factory=dict)

    # The actual events processed this cycle.  Used by bridge_cycle to feed
    # downstream subsystems without re-reading the (now consumed) queue.
    # Intentionally excluded from to_dict() to keep serialized metrics small.
    processed_events: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_start": self.cycle_start,
            "cycle_duration_ms": self.cycle_duration_ms,
            "events_read": self.events_read,
            "events_processed": self.events_processed,
            "events_consumed": self.events_consumed,
            "events_remaining": self.events_remaining,
            "batch_size_used": self.batch_size_used,
            "learning_yield": {
                "patterns_detected": self.patterns_detected,
                "insights_created": self.insights_created,
                "tool_effectiveness_updates": self.tool_effectiveness_updates,
                "error_patterns_found": self.error_patterns_found,
                "session_workflows_analyzed": self.session_workflows_analyzed,
            },
            "priority_breakdown": {
                "high": self.high_priority_processed,
                "medium": self.medium_priority_processed,
                "low": self.low_priority_processed,
            },
            "health": {
                "queue_depth_before": self.queue_depth_before,
                "queue_depth_after": self.queue_depth_after,
                "processing_rate_eps": round(self.processing_rate_eps, 1),
                "backpressure_level": self.backpressure_level,
            },
            "errors": self.errors,
            "distillation_debug": self.distillation_debug,
        }


def _load_pipeline_state() -> Dict:
    if PIPELINE_STATE_FILE.exists():
        try:
            return json.loads(PIPELINE_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "last_batch_size": DEFAULT_BATCH_SIZE,
        "last_processing_rate": 0.0,
        "consecutive_empty_cycles": 0,
        "total_events_processed": 0,
        "total_insights_created": 0,
        "last_cycle_ts": 0.0,
    }


def _save_pipeline_state(state: Dict) -> None:
    PIPELINE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PIPELINE_STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(PIPELINE_STATE_FILE)


def _save_pipeline_metrics(metrics: ProcessingMetrics) -> None:
    """Append metrics to a rolling log (keeps last 100 entries)."""
    PIPELINE_METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    entries: List[Dict] = []
    if PIPELINE_METRICS_FILE.exists():
        try:
            entries = json.loads(
                PIPELINE_METRICS_FILE.read_text(encoding="utf-8")
            )
        except Exception:
            entries = []
    entries.append(metrics.to_dict())
    # Keep last 100 entries for trend analysis
    entries = entries[-100:]
    tmp = PIPELINE_METRICS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    tmp.replace(PIPELINE_METRICS_FILE)


# ============= Adaptive Batch Sizing =============

def compute_batch_size(queue_depth: int, state: Dict) -> int:
    """Compute the optimal batch size based on queue depth and history.

    Strategy:
    - Healthy queue (< 200): Use default batch size
    - Elevated queue (200-500): Double batch size
    - Critical queue (500-2000): Quadruple batch size
    - Emergency (> 2000): Maximum batch size (drain mode)

    Also factors in previous processing rate to avoid overwhelming the system.
    """
    if queue_depth <= QUEUE_HEALTHY:
        base = DEFAULT_BATCH_SIZE
    elif queue_depth <= QUEUE_ELEVATED:
        base = DEFAULT_BATCH_SIZE * 2
    elif queue_depth <= QUEUE_CRITICAL:
        base = DEFAULT_BATCH_SIZE * 4
    else:
        base = MAX_BATCH_SIZE

    # If previous cycle was fast, allow bigger batches
    last_rate = state.get("last_processing_rate", 0.0)
    if last_rate > 500:  # More than 500 events/sec
        base = min(MAX_BATCH_SIZE, int(base * 1.5))

    return max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, base))


def compute_backpressure_level(queue_depth: int) -> str:
    """Classify queue pressure level for observability."""
    if queue_depth <= QUEUE_HEALTHY:
        return "healthy"
    elif queue_depth <= QUEUE_ELEVATED:
        return "elevated"
    elif queue_depth <= QUEUE_CRITICAL:
        return "critical"
    else:
        return "emergency"


# ============= Deep Learning Extraction =============

def extract_tool_effectiveness(events: List[SparkEvent]) -> Dict[str, Any]:
    """Extract tool effectiveness metrics from a batch of events.

    This is the missing piece -- the current system has tool_effectiveness = 0
    despite thousands of events because nothing aggregates success/failure
    rates into actual learnings.

    Enhanced to:
    - Collect common error messages per tool for root-cause insights
    - Detect success-after-failure patterns (recovery signals)
    - Track tool combinations that predict success/failure

    Returns a dict with tool-level statistics and generated insights.
    """
    tool_stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"success": 0, "failure": 0, "total": 0, "errors": []}
    )

    # Track tool sequences per session for recovery detection
    session_sequences: Dict[str, List[Tuple[str, bool]]] = defaultdict(list)

    for event in events:
        tool = (event.tool_name or "").strip()
        if not tool:
            continue

        if event.event_type == EventType.POST_TOOL:
            tool_stats[tool]["success"] += 1
            tool_stats[tool]["total"] += 1
            session_sequences[event.session_id].append((tool, True))
        elif event.event_type == EventType.POST_TOOL_FAILURE:
            tool_stats[tool]["failure"] += 1
            tool_stats[tool]["total"] += 1
            err = (event.error or "")[:150].strip()
            if err:
                tool_stats[tool]["errors"].append(err)
            session_sequences[event.session_id].append((tool, False))

    # Generate learnings from the stats
    insights: List[Dict[str, Any]] = []
    for tool, stats in tool_stats.items():
        if stats["total"] < 3:
            continue  # Need enough data

        success_rate = stats["success"] / stats["total"] if stats["total"] > 0 else 0

        # Low success rate with error details
        if success_rate < 0.5 and stats["total"] >= 5:
            # Summarize top errors
            error_counter = Counter(e[:80] for e in stats["errors"])
            top_errors = error_counter.most_common(3)
            error_summary = "; ".join(
                f"{err} ({cnt}x)" for err, cnt in top_errors
            ) if top_errors else "no error details"
            insights.append({
                "type": "low_success_rate",
                "tool": tool,
                "success_rate": round(success_rate, 2),
                "total": stats["total"],
                "insight": (
                    f"{tool} has {success_rate:.0%} success rate "
                    f"({stats['failure']}/{stats['total']} failures). "
                    f"Common errors: {error_summary}"
                ),
            })
        elif stats["failure"] >= 3:
            error_counter = Counter(e[:80] for e in stats["errors"])
            top_error = error_counter.most_common(1)
            error_hint = f" Most common: {top_error[0][0]}" if top_error else ""
            insights.append({
                "type": "recurring_failures",
                "tool": tool,
                "failures": stats["failure"],
                "success_rate": round(success_rate, 2),
                "insight": (
                    f"{tool} failed {stats['failure']}/{stats['total']} times "
                    f"({success_rate:.0%} success rate).{error_hint}"
                ),
            })

    # Detect recovery patterns (fail then succeed with same tool)
    recovery_count = 0
    for session_id, seq in session_sequences.items():
        for i in range(1, len(seq)):
            tool, success = seq[i]
            prev_tool, prev_success = seq[i - 1]
            if tool == prev_tool and success and not prev_success:
                recovery_count += 1

    if recovery_count >= 3:
        insights.append({
            "type": "recovery_pattern",
            "recovery_count": recovery_count,
            "insight": (
                f"Detected {recovery_count} recovery patterns "
                f"(tool fail then retry succeed) -- retrying often works"
            ),
        })

    return {
        "tool_stats": {
            k: {"success": v["success"], "failure": v["failure"],
                 "total": v["total"], "success_rate": round(
                     v["success"] / v["total"], 2) if v["total"] > 0 else 0}
            for k, v in tool_stats.items()
        },
        "insights": insights,
        "tools_tracked": len(tool_stats),
    }


def extract_micro_insights(events: List[SparkEvent]) -> List[Dict[str, Any]]:
    """Extract targeted insights from individual events in low-volume cycles.

    When event counts are too low for aggregation thresholds (tool needs 3+
    uses, error patterns need 2+ occurrences), this function extracts useful
    signal from individual high-value events like failures, user prompts,
    and noteworthy tool patterns.

    Returns a list of insight dicts suitable for _gate_and_store().
    """
    insights: List[Dict[str, Any]] = []

    for event in events:
        tool = (event.tool_name or "").strip()
        error = (event.error or "").strip()

        # Individual failure with error detail → targeted learning
        if event.event_type == EventType.POST_TOOL_FAILURE and tool and error:
            # Extract the actionable part of the error (first line, trimmed)
            error_core = error.split("\n")[0][:120].strip()
            if len(error_core) > 15:  # Skip trivially short errors
                insights.append({
                    "type": "single_failure",
                    "tool": tool,
                    "insight": f"{tool} failed: {error_core}",
                    "confidence": 0.55,
                    "category": "SELF_AWARENESS",
                })

        # Tool input patterns — detect large file operations that often signal complexity
        tool_input = event.tool_input or {}
        if tool == "Edit" and tool_input:
            old_text = str(tool_input.get("old_string") or tool_input.get("oldText") or "")
            new_text = str(tool_input.get("new_string") or tool_input.get("newText") or "")
            # Large edit replacements (>500 chars changed) are noteworthy
            if len(old_text) > 500 or len(new_text) > 500:
                file_path = str(tool_input.get("file_path") or tool_input.get("path") or "?")
                fname = Path(file_path).name if file_path != "?" else "?"
                insights.append({
                    "type": "large_edit",
                    "tool": tool,
                    "insight": (
                        f"Large edit on {fname} ({len(old_text)}→{len(new_text)} chars). "
                        f"Consider smaller incremental changes for safer refactoring."
                    ),
                    "confidence": 0.50,
                    "category": "REASONING",
                })

    # Cap to avoid noise from busy micro-cycles
    return insights[:3]


def extract_error_patterns(events: List[SparkEvent]) -> Dict[str, Any]:
    """Extract recurring error patterns from failure events.

    Groups errors by tool + error signature to find systematic issues.
    """
    error_groups: Dict[str, List[str]] = defaultdict(list)

    for event in events:
        if event.event_type != EventType.POST_TOOL_FAILURE:
            continue
        tool = (event.tool_name or "unknown").strip()
        error = (event.error or "").strip()
        if not error:
            continue
        # Normalize error to first 100 chars for grouping
        error_key = f"{tool}:{error[:100]}"
        error_groups[error_key].append(error[:300])

    patterns: List[Dict[str, Any]] = []
    for key, errors in error_groups.items():
        if len(errors) >= 2:  # Recurring pattern
            tool, error_prefix = key.split(":", 1)
            patterns.append({
                "tool": tool,
                "error_pattern": error_prefix,
                "occurrences": len(errors),
                "insight": f"{tool} fails repeatedly with: {error_prefix[:80]}",
            })

    return {
        "error_patterns": patterns,
        "total_errors": sum(1 for e in events if e.event_type == EventType.POST_TOOL_FAILURE),
    }


def _extract_macros_from_sessions(
    sessions: Dict[str, List[Tuple[str, str]]],
    *,
    n: int = 3,
    min_count: int = 3,
) -> List[Dict[str, Any]]:
    """Extract frequent successful tool n-grams as macro candidates."""
    if n < 2:
        n = 2
    counts: Counter[str] = Counter()
    for _sid, tools in (sessions or {}).items():
        ok_tools = [tool for tool, status in tools if status == "ok" and tool]
        if len(ok_tools) < n:
            continue
        for i in range(0, len(ok_tools) - n + 1):
            gram = ok_tools[i : i + n]
            # Require at least one "action" tool so we don't learn read-only macros.
            if not any(t in {"Edit", "Write", "Bash", "NotebookEdit"} for t in gram):
                continue
            counts["→".join(gram)] += 1

    macros: List[Dict[str, Any]] = []
    for seq, cnt in counts.most_common(10):
        if cnt < max(2, int(min_count or 2)):
            continue
        macros.append({"sequence": seq, "count": int(cnt)})
    return macros


def extract_session_workflows(events: List[SparkEvent]) -> Dict[str, Any]:
    """Analyze tool usage patterns within sessions.

    Identifies common sequences and anti-patterns like:
    - Edit without preceding Read (risky)
    - Multiple consecutive failures (struggling)
    - Effective tool chains (Read -> Edit -> Read verify)

    Deduplicates insights to avoid noise -- counts occurrences rather
    than emitting one insight per occurrence.
    """
    sessions: Dict[str, List[Tuple[str, str]]] = defaultdict(list)

    for event in events:
        tool = (event.tool_name or "").strip()
        if not tool:
            continue
        status = "ok" if event.event_type == EventType.POST_TOOL else "fail"
        sessions[event.session_id].append((tool, status))

    # Aggregate pattern counts instead of listing every occurrence
    struggling_sessions: List[Dict[str, Any]] = []
    risky_edit_by_predecessor: Counter = Counter()
    total_edits = 0
    safe_edits = 0

    for session_id, tools in sessions.items():
        if len(tools) < 3:
            continue

        # Detect consecutive failures (struggling)
        max_consecutive_fails = 0
        current_fails = 0
        for _, status in tools:
            if status == "fail":
                current_fails += 1
                max_consecutive_fails = max(max_consecutive_fails, current_fails)
            else:
                current_fails = 0

        if max_consecutive_fails >= 3:
            struggling_sessions.append({
                "session_id": session_id,
                "consecutive_failures": max_consecutive_fails,
            })

        # Count Edit-without-Read patterns (aggregated)
        for i, (tool, _) in enumerate(tools):
            if tool == "Edit":
                total_edits += 1
                if i > 0:
                    prev_tool = tools[i - 1][0]
                    if prev_tool != "Read":
                        risky_edit_by_predecessor[prev_tool] += 1
                    else:
                        safe_edits += 1
                else:
                    risky_edit_by_predecessor["(first_action)"] += 1

    workflow_insights: List[Dict[str, Any]] = []

    # Emit aggregated struggling insight
    if struggling_sessions:
        worst = max(s["consecutive_failures"] for s in struggling_sessions)
        workflow_insights.append({
            "type": "struggling",
            "sessions_affected": len(struggling_sessions),
            "worst_streak": worst,
            "insight": (
                f"{len(struggling_sessions)} session(s) had 3+ consecutive "
                f"failures (worst streak: {worst}). Consider different "
                f"approach when stuck."
            ),
        })

    # Emit aggregated risky-edit insight
    risky_total = sum(risky_edit_by_predecessor.values())
    if risky_total >= 2 and total_edits > 0:
        risky_pct = risky_total / total_edits
        top_predecessors = risky_edit_by_predecessor.most_common(3)
        pred_str = ", ".join(
            f"{pred} ({cnt}x)" for pred, cnt in top_predecessors
        )
        workflow_insights.append({
            "type": "risky_edit",
            "risky_count": risky_total,
            "total_edits": total_edits,
            "safe_count": safe_edits,
            "insight": (
                f"{risky_total}/{total_edits} Edits ({risky_pct:.0%}) "
                f"not preceded by Read. Preceded by: {pred_str}. "
                f"Always Read before Edit to avoid mismatch errors."
            ),
        })

    macros: List[Dict[str, Any]] = []
    if MACROS_ENABLED:
        try:
            macros = _extract_macros_from_sessions(
                sessions,
                n=3,
                min_count=MACRO_MIN_COUNT,
            )
        except Exception:
            macros = []

    return {
        "sessions_analyzed": len(sessions),
        "workflow_insights": workflow_insights,
        "macros": macros,
    }


def store_deep_learnings(
    tool_effectiveness: Dict[str, Any],
    error_patterns: Dict[str, Any],
    session_workflows: Dict[str, Any],
    *,
    events_processed: int = 0,
    micro_insights: Optional[List[Dict[str, Any]]] = None,
) -> tuple[int, Dict[str, Any]]:
    """Store extracted learnings in the cognitive system.

    All insights pass through MetaRalph quality gate before storage.
    Returns: (stored_count, debug_info)
    """
    stored = 0
    debug: Dict[str, Any] = {
        "attempted": 0,
        "stored": 0,
        "skipped": {},
        "floor_applied": False,
    }

    try:
        from lib.cognitive_learner import get_cognitive_learner, CognitiveCategory
        from lib.meta_ralph import get_meta_ralph, RoastVerdict
        learner = get_cognitive_learner()
        ralph = get_meta_ralph()

        def _gate_and_store(insight_text: str, category, context: str, confidence: float,
                            source: str = "pipeline", roast_context: dict = None) -> bool:
            """Run insight through MetaRalph quality gate, then store if it passes."""
            debug["attempted"] = int(debug.get("attempted", 0)) + 1
            roast_result = ralph.roast(insight_text, source=source, context=roast_context)
            verdict_value = str(getattr(roast_result.verdict, "value", roast_result.verdict) or "gate_rejected").lower()

            # Keep strict default, but allow low-volume pipeline cycles to pass non-primitive verdicts.
            allow_low_volume_pass = (
                events_processed <= FLOOR_SOFT_MIN_EVENTS
                and verdict_value not in {"primitive", "noise", "garbage"}
            )

            if roast_result.verdict == RoastVerdict.QUALITY or allow_low_volume_pass:
                # Use refined version if MetaRalph improved it
                # NOTE: Intentional direct add_insight() — pipeline already ran Meta-Ralph
                # above, so routing through validate_and_store would double-roast.
                final_text = roast_result.refined_version or insight_text
                ok = bool(learner.add_insight(
                    category=category,
                    insight=final_text,
                    context=context,
                    confidence=confidence,
                    source="pipeline_macro",
                ))
                if ok:
                    debug["stored"] = int(debug.get("stored", 0)) + 1
                else:
                    skipped = debug.setdefault("skipped", {})
                    skipped["storage_rejected"] = int(skipped.get("storage_rejected", 0)) + 1
                return ok

            skipped = debug.setdefault("skipped", {})
            skipped[verdict_value] = int(skipped.get(verdict_value, 0)) + 1
            return False

        # Tool effectiveness insights
        for insight_data in tool_effectiveness.get("insights", []):
            if _gate_and_store(
                insight_data["insight"],
                CognitiveCategory.SELF_AWARENESS,
                f"tool_effectiveness:{insight_data['tool']}",
                0.7,
                source="pipeline_tool_effectiveness",
                roast_context={"tool_name": insight_data.get("tool", "")},
            ):
                stored += 1

        # Error pattern insights
        for pattern in error_patterns.get("error_patterns", []):
            if _gate_and_store(
                pattern["insight"],
                CognitiveCategory.SELF_AWARENESS,
                f"error_pattern:{pattern['tool']}",
                0.75,
                source="pipeline_error_pattern",
                roast_context={
                    "tool_name": pattern.get("tool", ""),
                    "error": pattern.get("error", ""),
                },
            ):
                stored += 1

        # Workflow anti-pattern insights
        for insight_data in session_workflows.get("workflow_insights", []):
            if insight_data["type"] == "risky_edit":
                if _gate_and_store(
                    "Always Read a file before Edit to verify current content",
                    CognitiveCategory.REASONING,
                    f"workflow_antipattern:{insight_data.get('session_id', '')}",
                    0.8,
                    source="pipeline_workflow",
                ):
                    stored += 1
            elif insight_data["type"] == "struggling":
                if _gate_and_store(
                    insight_data["insight"],
                    CognitiveCategory.META_LEARNING,
                    f"workflow_struggle:{insight_data.get('session_id', '')}",
                    0.65,
                    source="pipeline_workflow",
                ):
                    stored += 1

        # Workflow macros (temporal abstractions over successful tool sequences)
        macros = session_workflows.get("macros") or []
        if MACROS_ENABLED and isinstance(macros, list) and macros:
            # Store at most one per cycle to avoid memory spam.
            top = macros[0] if isinstance(macros[0], dict) else None
            if top and top.get("sequence"):
                seq = str(top.get("sequence") or "").strip()
                cnt = int(top.get("count") or 0)
                if seq and cnt >= max(2, MACRO_MIN_COUNT):
                    text = (
                        f"Macro (often works): {seq}. "
                        f"Use this sequence when appropriate to reduce thrash."
                    )
                    if _gate_and_store(
                        text,
                        CognitiveCategory.META_LEARNING,
                        f"workflow_macro:{seq} count={cnt}",
                        0.6,
                        source="pipeline_macro",
                    ):
                        stored += 1

        # Micro-insights: individual event signal for low-volume cycles
        _CATEGORY_MAP = {
            "SELF_AWARENESS": CognitiveCategory.SELF_AWARENESS,
            "REASONING": CognitiveCategory.REASONING,
            "META_LEARNING": CognitiveCategory.META_LEARNING,
        }
        for mi in (micro_insights or []):
            mi_text = mi.get("insight", "")
            mi_cat = _CATEGORY_MAP.get(mi.get("category", ""), CognitiveCategory.SELF_AWARENESS)
            mi_conf = float(mi.get("confidence", 0.5))
            mi_tool = mi.get("tool", "unknown")
            if mi_text and _gate_and_store(
                mi_text,
                mi_cat,
                f"micro:{mi.get('type', 'unknown')}:{mi_tool}",
                mi_conf,
                source="pipeline_micro",
            ):
                stored += 1

        # Distillation floor: ensure at least one durable insight when meaningful signal exists.
        tool_updates = int(tool_effectiveness.get("tools_tracked", 0) or 0)
        error_count = len(error_patterns.get("error_patterns", []))
        workflow_count = len(session_workflows.get("workflow_insights", []))
        has_signal = (tool_updates > 0) or (error_count > 0) or (workflow_count > 0)

        floor_gate = (
            events_processed >= FLOOR_EVENTS_THRESHOLD
            or (events_processed >= FLOOR_SOFT_MIN_EVENTS and has_signal)
        )

        if (
            MIN_INSIGHTS_FLOOR > 0
            and floor_gate
            and stored < MIN_INSIGHTS_FLOOR
        ):
            # Build a data-specific fallback insight from actual cycle signals
            # instead of a generic meta-statement.
            fallback_parts: List[str] = []
            # Summarize top tool stat if available
            tool_stats_raw = tool_effectiveness.get("tool_stats", {})
            if tool_stats_raw:
                sorted_tools = sorted(
                    tool_stats_raw.items(),
                    key=lambda kv: kv[1].get("total", 0),
                    reverse=True,
                )
                top_tool_name, top_tool_data = sorted_tools[0]
                sr = top_tool_data.get("success_rate", 1.0)
                total = top_tool_data.get("total", 0)
                if sr < 0.9 and total >= 2:
                    fallback_parts.append(
                        f"{top_tool_name} had {sr:.0%} success across {total} uses"
                    )
                else:
                    fallback_parts.append(
                        f"{top_tool_name} used {total} times ({sr:.0%} success)"
                    )
            # Summarize error pattern if available
            err_patterns_list = error_patterns.get("error_patterns", [])
            if err_patterns_list:
                ep = err_patterns_list[0]
                fallback_parts.append(
                    f"recurring error in {ep.get('tool', '?')}: {ep.get('error_pattern', '')[:60]}"
                )
            # Summarize workflow signal if available
            wf_insights = session_workflows.get("workflow_insights", [])
            if wf_insights:
                fallback_parts.append(wf_insights[0].get("insight", "")[:80])

            if fallback_parts:
                fallback_insight = "Cycle summary: " + "; ".join(fallback_parts) + "."
            else:
                fallback_insight = (
                    f"Processed {events_processed} events with "
                    f"{tool_updates} tools tracked and "
                    f"{error_count} error patterns — no strong signal this cycle."
                )
            context = (
                f"distillation_floor events={events_processed} "
                f"tool_updates={tool_effectiveness.get('tools_tracked', 0)} "
                f"errors={len(error_patterns.get('error_patterns', []))}"
            )
            # Floor enforcement now goes through unified validation (Meta-Ralph + noise filter).
            from lib.validate_and_store import validate_and_store_insight
            if validate_and_store_insight(
                text=fallback_insight,
                category=CognitiveCategory.META_LEARNING,
                context=context,
                confidence=0.55,
                source="pipeline_macro",
            ):
                stored += 1
                debug["stored"] = int(debug.get("stored", 0)) + 1
                debug["floor_applied"] = True
            else:
                skipped = debug.setdefault("skipped", {})
                skipped["floor_storage_rejected"] = int(skipped.get("floor_storage_rejected", 0)) + 1

    except Exception as e:
        skipped = debug.setdefault("skipped", {})
        skipped["exception"] = int(skipped.get("exception", 0)) + 1
        debug["error"] = str(e)[:160]
        log_debug("pipeline", "store_deep_learnings failed", e)

    return stored, debug


# ============= Main Processing Pipeline =============

def _stable_sample_keep(*, key: str, keep_rate: float) -> bool:
    """Deterministic sampling gate based on a stable hash.

    Avoids randomness across processes while still downsampling under backlog.
    """
    rate = max(0.0, min(1.0, float(keep_rate)))
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    digest = hashlib.sha1(str(key or "").encode("utf-8", errors="ignore")).hexdigest()[:8]
    # Map first 8 hex chars to [0,1)
    value = int(digest, 16) / float(16 ** 8)
    return value < rate


def run_processing_cycle(
    *,
    force_batch_size: Optional[int] = None,
) -> ProcessingMetrics:
    """Run one processing cycle with adaptive batch sizing.

    This is the production replacement for the shallow ``read_recent_events(40)``
    approach in ``bridge_cycle.py``.

    Flow:
    1. Check queue depth, compute batch size
    2. Read events (priority-ordered)
    3. Run pattern detection on the batch
    4. Extract deep learnings (tool effectiveness, errors, workflows)
    5. Store insights in cognitive system
    6. Consume processed events from queue
    7. Emit metrics

    Returns ProcessingMetrics with full observability data.
    """
    metrics = ProcessingMetrics(cycle_start=time.time())
    state = _load_pipeline_state()

    # 1. Check queue depth
    metrics.queue_depth_before = count_events()
    metrics.backpressure_level = compute_backpressure_level(
        metrics.queue_depth_before
    )

    # 2. Compute batch size
    if force_batch_size:
        batch_size = max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, force_batch_size))
    else:
        batch_size = compute_batch_size(metrics.queue_depth_before, state)
    metrics.batch_size_used = batch_size

    # 3. Read events from the head of the queue (oldest first = FIFO)
    events = read_events(limit=batch_size, offset=0)
    metrics.events_read = len(events)

    if not events:
        state["consecutive_empty_cycles"] = state.get("consecutive_empty_cycles", 0) + 1
        _save_pipeline_state(state)
        metrics.cycle_duration_ms = (time.time() - metrics.cycle_start) * 1000
        _save_pipeline_metrics(metrics)
        return metrics

    state["consecutive_empty_cycles"] = 0

    # 4. Classify by priority and sort HIGH first for pattern detection
    for event in events:
        priority = classify_event_priority(event)
        if priority == EventPriority.HIGH:
            metrics.high_priority_processed += 1
        elif priority == EventPriority.MEDIUM:
            metrics.medium_priority_processed += 1
        else:
            metrics.low_priority_processed += 1

    # Sort so HIGH-priority events are processed first by pattern detection.
    # This ensures that user prompts and failures (the most valuable events)
    # get full attention even if we can only partially process a huge batch.
    processing_order = sorted(
        events,
        key=lambda e: classify_event_priority(e),
        reverse=True,
    )

    # 5. Run pattern detection (existing system) with priority ordering
    # Map hook_event names to aggregator "type" values for EIDOS step-wrapping.
    _HOOK_TO_AGG_TYPE = {
        "UserPromptSubmit": "user_message",
        "PostToolUse": "action_complete",
        "PostToolUseFailure": "failure",
    }

    pattern_cycle_ok = False
    try:
        from lib.pattern_detection.aggregator import get_aggregator
        aggregator = get_aggregator()

        for event in processing_order:
            # Under heavy backlog, skip low-priority events in the expensive
            # pattern detection pass to drain faster while preserving signal.
            if IMPORTANCE_SAMPLING_ENABLED and metrics.backpressure_level in {"critical", "emergency"}:
                pr = classify_event_priority(event)
                if pr == EventPriority.LOW:
                    trace_id = (event.data or {}).get("trace_id") or ""
                    sample_key = f"{event.session_id}|{event.event_type.value if hasattr(event.event_type,'value') else event.event_type}|{event.tool_name or ''}|{trace_id}"  # noqa
                    if not _stable_sample_keep(key=sample_key, keep_rate=LOW_PRIORITY_KEEP_RATE):
                        continue

            hook_event = (event.data or {}).get("hook_event") or ""
            payload = (event.data or {}).get("payload")
            pattern_event = {
                "session_id": event.session_id,
                "hook_event": hook_event,
                "tool_name": event.tool_name,
                "tool_input": event.tool_input,
                "payload": payload,
            }

            # Provide the "type" key the aggregator expects for EIDOS
            agg_type = _HOOK_TO_AGG_TYPE.get(hook_event, "")
            if agg_type:
                pattern_event["type"] = agg_type

            # For user messages, map content so aggregator can create Steps
            if hook_event == "UserPromptSubmit" and isinstance(payload, dict):
                user_text = payload.get("text", "")
                if user_text:
                    pattern_event["content"] = user_text

            trace_id = (event.data or {}).get("trace_id")
            if trace_id:
                pattern_event["trace_id"] = trace_id
            if event.error:
                pattern_event["error"] = event.error

            patterns = aggregator.process_event(pattern_event)
            if patterns:
                aggregator.trigger_learning(patterns)
                metrics.patterns_detected += len(patterns)

        pattern_cycle_ok = True
        metrics.events_processed = len(events)
        # Only keep lightweight references, not full event objects (memory leak fix)
        metrics.processed_events = events  # share reference, don't copy
    except Exception as e:
        metrics.errors.append(f"pattern_detection: {str(e)[:100]}")
        log_debug("pipeline", "pattern detection failed", e)

    if pattern_cycle_ok:
        # 6. Extract deep learnings (THE NEW PART)
        try:
            tool_eff = extract_tool_effectiveness(events)
            metrics.tool_effectiveness_updates = tool_eff.get("tools_tracked", 0)
        except Exception as e:
            tool_eff = {"insights": [], "tool_stats": {}, "tools_tracked": 0}
            metrics.errors.append(f"tool_effectiveness: {str(e)[:100]}")

        try:
            error_pats = extract_error_patterns(events)
            metrics.error_patterns_found = len(error_pats.get("error_patterns", []))
        except Exception as e:
            error_pats = {"error_patterns": [], "total_errors": 0}
            metrics.errors.append(f"error_patterns: {str(e)[:100]}")

        try:
            workflows = extract_session_workflows(events)
            metrics.session_workflows_analyzed = workflows.get("sessions_analyzed", 0)
        except Exception as e:
            workflows = {"sessions_analyzed": 0, "workflow_insights": []}
            metrics.errors.append(f"session_workflows: {str(e)[:100]}")

        # 6b. Extract micro-insights for low-volume cycles
        micro = []
        try:
            micro = extract_micro_insights(events)
        except Exception as e:
            metrics.errors.append(f"micro_insights: {str(e)[:100]}")

        # 7. Store deep learnings
        try:
            stored, distill_debug = store_deep_learnings(
                tool_eff,
                error_pats,
                workflows,
                events_processed=len(events),
                micro_insights=micro,
            )
            metrics.insights_created = stored
            metrics.distillation_debug = distill_debug
        except Exception as e:
            metrics.errors.append(f"store_learnings: {str(e)[:100]}")
            log_debug("pipeline", "store deep learnings failed", e)

        # 8. Consume processed events from queue
        try:
            consumed = consume_processed(len(events))
            metrics.events_consumed = consumed
            # Reset the pattern detection offset since we've removed lines
            # from the head of the file.  Without this, the worker's saved
            # offset would point past the end of the (now shorter) file.
            if consumed > 0:
                try:
                    from lib.pattern_detection.worker import reset_offset
                    reset_offset()
                except Exception:
                    pass
        except Exception as e:
            metrics.errors.append(f"consume: {str(e)[:100]}")
            log_debug("pipeline", "consume_processed failed", e)
    else:
        metrics.errors.append("consume_skipped:pattern_detection_failed")

    # 9. Final stats
    metrics.events_remaining = count_events()
    metrics.queue_depth_after = metrics.events_remaining

    cycle_time = time.time() - metrics.cycle_start
    metrics.cycle_duration_ms = cycle_time * 1000
    if cycle_time > 0:
        metrics.processing_rate_eps = metrics.events_processed / cycle_time

    # 10. Update pipeline state for auto-tuning
    state["last_batch_size"] = batch_size
    state["last_processing_rate"] = metrics.processing_rate_eps
    state["total_events_processed"] = (
        state.get("total_events_processed", 0) + metrics.events_processed
    )
    state["total_insights_created"] = (
        state.get("total_insights_created", 0) + metrics.insights_created
    )
    state["last_cycle_ts"] = time.time()
    _save_pipeline_state(state)

    # 11. Save metrics for observability
    _save_pipeline_metrics(metrics)

    return metrics


def get_pipeline_health() -> Dict[str, Any]:
    """Get current pipeline health for monitoring.

    Returns a dict with queue depth, processing rate, backlog trend, etc.
    Suitable for the /status endpoint and watchdog checks.
    """
    queue_depth = count_events()
    state = _load_pipeline_state()

    # Load recent metrics for trend analysis
    trend = {"improving": False, "stable": True, "degrading": False}
    recent_rates: List[float] = []
    recent_yields: List[int] = []
    if PIPELINE_METRICS_FILE.exists():
        try:
            entries = json.loads(
                PIPELINE_METRICS_FILE.read_text(encoding="utf-8")
            )
            for entry in entries[-10:]:
                health = entry.get("health", {})
                rate = health.get("processing_rate_eps", 0)
                if rate > 0:
                    recent_rates.append(rate)
                ly = entry.get("learning_yield", {})
                recent_yields.append(ly.get("insights_created", 0))
        except Exception:
            pass

    if len(recent_rates) >= 3:
        first_half = sum(recent_rates[: len(recent_rates) // 2]) / max(
            1, len(recent_rates) // 2
        )
        second_half = sum(recent_rates[len(recent_rates) // 2 :]) / max(
            1, len(recent_rates) - len(recent_rates) // 2
        )
        if second_half > first_half * 1.1:
            trend = {"improving": True, "stable": False, "degrading": False}
        elif second_half < first_half * 0.8:
            trend = {"improving": False, "stable": False, "degrading": True}

    return {
        "queue_depth": queue_depth,
        "backpressure_level": compute_backpressure_level(queue_depth),
        "last_cycle_ts": state.get("last_cycle_ts", 0),
        "last_processing_rate": state.get("last_processing_rate", 0),
        "total_events_processed": state.get("total_events_processed", 0),
        "total_insights_created": state.get("total_insights_created", 0),
        "consecutive_empty_cycles": state.get("consecutive_empty_cycles", 0),
        "trend": trend,
        "avg_processing_rate": (
            round(sum(recent_rates) / len(recent_rates), 1) if recent_rates else 0
        ),
        "avg_learning_yield": (
            round(sum(recent_yields) / len(recent_yields), 1) if recent_yields else 0
        ),
    }


def compute_next_interval(metrics: ProcessingMetrics, base_interval: int = 30) -> int:
    """Compute the optimal interval before the next processing cycle.

    Auto-tunes based on:
    - Queue depth (shorter interval when backlogged)
    - Processing rate (can we handle faster cycles?)
    - Learning yield (slow down if nothing interesting)

    Returns interval in seconds.
    """
    if metrics.backpressure_level == "emergency":
        return 5   # Drain as fast as possible
    elif metrics.backpressure_level == "critical":
        return 10
    elif metrics.backpressure_level == "elevated":
        return 15
    elif metrics.events_read == 0:
        # Nothing to process, back off
        return min(120, base_interval * 2)
    else:
        return base_interval
