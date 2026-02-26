"""Feedback Loop — closes the circle between advice and outcomes.

This module:
1. Ingests self-reports from the agent (decisions, outcomes, preferences)
2. Matches outcomes to the advisories that prompted them
3. Updates cognitive confidence based on what actually worked
4. Feeds results back into the prediction/validation system

The key insight: without feedback, Spark's distillation rate stays at ~0.4%.
This module is what makes advice actionable and measurable.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from lib.diagnostics import log_debug

REPORTS_DIR = Path.home() / ".openclaw" / "workspace" / "spark_reports"
FEEDBACK_STATE_FILE = Path.home() / ".spark" / "feedback_state.json"
FEEDBACK_LOG_FILE = Path.home() / ".spark" / "feedback_log.jsonl"
ADVISORY_FILE = Path.home() / ".spark" / "llm_advisory.md"


def _load_state() -> Dict[str, Any]:
    if FEEDBACK_STATE_FILE.exists():
        try:
            return json.loads(FEEDBACK_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "processed_reports": [],
        "advisory_outcomes": {},
        "total_processed": 0,
        "total_positive": 0,
        "total_negative": 0,
        "total_neutral": 0,
        "advice_action_rate": 0.0,
    }


def _save_state(state: Dict[str, Any]) -> None:
    FEEDBACK_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=FEEDBACK_STATE_FILE.parent, suffix=".tmp")
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, FEEDBACK_STATE_FILE)


def _log_feedback(entry: Dict[str, Any]) -> None:
    """Append to the feedback log for trend analysis."""
    FEEDBACK_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(FEEDBACK_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def ingest_reports() -> Dict[str, Any]:
    """Read and process pending self-reports from the agent.

    Returns stats about what was processed.
    """
    stats = {
        "found": 0,
        "processed": 0,
        "decisions": 0,
        "outcomes": 0,
        "preferences": 0,
        "errors": 0,
    }

    if not REPORTS_DIR.exists():
        return stats

    state = _load_state()
    processed_set = set(state.get("processed_reports", [])[-500:])

    report_files = sorted(REPORTS_DIR.glob("*.json"))
    stats["found"] = len(report_files)

    for report_file in report_files:
        fname = report_file.name
        if fname in processed_set:
            continue

        # File might have been moved by another process — skip gracefully
        if not report_file.exists():
            continue

        try:
            data = json.loads(report_file.read_text(encoding="utf-8"))
            kind = data.get("kind", "unknown")

            if kind == "decision":
                _process_decision(data, state)
                stats["decisions"] += 1
            elif kind == "outcome":
                _process_outcome(data, state)
                stats["outcomes"] += 1
            elif kind == "preference":
                _process_preference(data, state)
                stats["preferences"] += 1
            else:
                log_debug("feedback", f"Unknown report kind: {kind}", None)

            stats["processed"] += 1
            processed_set.add(fname)

            _log_feedback({
                "ts": time.time(),
                "kind": kind,
                "file": fname,
                "data": data,
            })

        except Exception as e:
            stats["errors"] += 1
            stats.setdefault("error_details", []).append(f"{fname}: {type(e).__name__}: {e}")
            log_debug("feedback", f"Failed to process {fname}", e)

    # Update state
    state["processed_reports"] = list(processed_set)[-500:]
    state["total_processed"] = state.get("total_processed", 0) + stats["processed"]

    # Calculate advice action rate
    total = state.get("total_processed", 0)
    positive = state.get("total_positive", 0)
    if total > 0:
        state["advice_action_rate"] = round(positive / total, 3)

    _save_state(state)
    return stats


def _process_decision(data: Dict, state: Dict) -> None:
    """Process a decision report — agent decided to act on something."""
    intent = data.get("intent", "")
    reasoning = data.get("reasoning", "")
    confidence = float(data.get("confidence", 0.5))
    source = data.get("source", "")  # e.g., "spark_advisory"

    # If this decision was prompted by a Spark advisory, track it
    if source in ("spark_advisory", "spark_context", "spark"):
        advisory_outcomes = state.get("advisory_outcomes", {})
        key = f"decision_{int(data.get('ts', time.time()))}"
        advisory_outcomes[key] = {
            "intent": intent,
            "confidence": confidence,
            "status": "pending",
            "ts": data.get("ts", time.time()),
        }
        state["advisory_outcomes"] = advisory_outcomes

    # Feed into cognitive system via unified validation
    try:
        from lib.cognitive_learner import CognitiveCategory
        from lib.validate_and_store import validate_and_store_insight
        validate_and_store_insight(
            text=f"Agent decided: {intent} (confidence={confidence:.1f})",
            category=CognitiveCategory.WISDOM,
            context=reasoning,
            confidence=confidence,
            source="feedback_loop",
        )
    except Exception as e:
        log_debug("feedback", "Failed to add decision insight", e)


def _process_outcome(data: Dict, state: Dict) -> None:
    """Process an outcome report — what actually happened."""
    result = data.get("result", "")
    lesson = data.get("lesson", "")
    success = data.get("success", None)  # True/False/None
    advisory_ref = data.get("advisory_ref", "")  # which advisory prompted this

    # Update counters
    if success is True:
        state["total_positive"] = state.get("total_positive", 0) + 1
    elif success is False:
        state["total_negative"] = state.get("total_negative", 0) + 1
    else:
        state["total_neutral"] = state.get("total_neutral", 0) + 1

    # Feed lesson into cognitive system via unified validation
    if lesson:
        try:
            from lib.cognitive_learner import CognitiveCategory
            from lib.validate_and_store import validate_and_store_insight
            cat = CognitiveCategory.WISDOM if success else CognitiveCategory.REASONING
            validate_and_store_insight(
                text=lesson,
                category=cat,
                context=f"Outcome: {result}",
                confidence=0.9 if success else 0.7,
                source="feedback_loop",
            )
        except Exception as e:
            log_debug("feedback", "Failed to add outcome insight", e)

    # Feed into prediction/outcome system
    try:
        from lib.outcome_log import append_outcomes
        append_outcomes([{
            "type": "agent_feedback",
            "result": result,
            "success": success,
            "lesson": lesson,
            "advisory_ref": advisory_ref,
            "created_at": data.get("ts", time.time()),
        }])
    except Exception as e:
        log_debug("feedback", "Failed to log outcome", e)


def _process_preference(data: Dict, state: Dict) -> None:
    """Process a preference report — what the agent likes/dislikes."""
    liked = data.get("liked", "")
    disliked = data.get("disliked", "")

    try:
        from lib.cognitive_learner import CognitiveCategory
        from lib.validate_and_store import validate_and_store_insight
        if liked:
            validate_and_store_insight(
                text=f"Agent prefers: {liked}",
                category=CognitiveCategory.WISDOM,
                context="self-reported preference",
                confidence=0.95,
                source="feedback_loop",
            )
        if disliked:
            validate_and_store_insight(
                text=f"Agent avoids: {disliked}",
                category=CognitiveCategory.WISDOM,
                context="self-reported preference",
                confidence=0.95,
                source="feedback_loop",
            )
    except Exception as e:
        log_debug("feedback", "Failed to add preference insight", e)


def get_feedback_stats() -> Dict[str, Any]:
    """Get current feedback loop statistics."""
    state = _load_state()
    return {
        "total_processed": state.get("total_processed", 0),
        "total_positive": state.get("total_positive", 0),
        "total_negative": state.get("total_negative", 0),
        "total_neutral": state.get("total_neutral", 0),
        "advice_action_rate": state.get("advice_action_rate", 0.0),
    }


def report_advisory_feedback(
    advisory_text: str,
    acted_on: bool,
    outcome: Optional[str] = None,
    success: Optional[bool] = None,
) -> None:
    """Quick helper for reporting feedback on a specific advisory.

    Call this after reading and acting (or not) on SPARK_ADVISORY.md.
    """
    from lib.self_report import report

    if acted_on:
        report(
            "outcome",
            result=outcome or "Applied advisory recommendation",
            lesson=f"Advisory said: {advisory_text[:200]}",
            success=success,
            advisory_ref=advisory_text[:100],
            source="spark_advisory",
        )
    else:
        report(
            "decision",
            intent="Skipped advisory",
            reasoning=f"Did not act on: {advisory_text[:200]}",
            confidence=0.5,
            source="spark_advisory",
        )
