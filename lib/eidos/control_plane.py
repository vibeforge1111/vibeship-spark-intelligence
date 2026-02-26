"""
EIDOS Control Plane: The Enforcement Layer

This is NOT an LLM. This is deterministic enforcement.
The LLM proposes, the Control Plane disposes.

Responsibilities:
- Budget enforcement (steps, time, retries)
- Loop detection (watchers)
- Phase control (rule-driven transitions)
- Memory binding enforcement
- Validation enforcement
"""

import time
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .models import Episode, Step, Phase, Outcome, Evaluation


class WatcherType(Enum):
    """Types of watchers that detect problems."""
    REPEAT_ERROR = "repeat_error"           # Same error signature 2+ times
    NO_NEW_INFO = "no_new_info"             # 5 steps without new evidence
    DIFF_THRASH = "diff_thrash"             # Same file modified 3+ times
    CONFIDENCE_STAGNATION = "confidence_stagnation"  # Delta < 0.05 for 3 steps
    MEMORY_BYPASS = "memory_bypass"         # Action without citing memory
    TRACE_GAP = "trace_gap"                 # Missing trace_id bindings


class BlockType(Enum):
    """Types of blocks the control plane can issue."""
    BUDGET_EXCEEDED = "budget_exceeded"
    LOOP_DETECTED = "loop_detected"
    MEMORY_REQUIRED = "memory_required"
    VALIDATION_REQUIRED = "validation_required"
    PHASE_VIOLATION = "phase_violation"


@dataclass
class WatcherAlert:
    """Alert raised by a watcher."""
    watcher_type: WatcherType
    message: str
    severity: str  # "warning" | "blocking"
    suggested_action: str
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ControlDecision:
    """Decision made by the control plane."""
    allowed: bool
    block_type: Optional[BlockType] = None
    message: str = ""
    required_action: str = ""
    phase_change: Optional[Phase] = None
    alerts: List[WatcherAlert] = field(default_factory=list)


class ControlPlane:
    """
    The enforcement layer - deterministic rules, not LLM decisions.

    Key principle: The Control Plane can BLOCK but never DECIDE.
    It enforces constraints; the agent chooses within them.
    """

    def __init__(self):
        # Watcher state
        self.error_signatures: Dict[str, List[str]] = {}  # episode_id -> [signatures]
        self.file_modifications: Dict[str, Dict[str, int]] = {}  # episode_id -> {file: count}
        self.confidence_history: Dict[str, List[float]] = {}  # episode_id -> [confidences]
        self.steps_without_new_info: Dict[str, int] = {}  # episode_id -> count

        # Thresholds (configurable)
        self.repeat_error_threshold = 2
        self.no_new_info_threshold = 5
        self.diff_thrash_threshold = 3
        self.confidence_delta_threshold = 0.05
        self.confidence_stagnation_steps = 3

    def check_before_action(
        self,
        episode: Episode,
        step: Step,
        recent_steps: List[Step]
    ) -> ControlDecision:
        """
        Check if an action should be allowed.
        Called BEFORE the agent takes any action.
        """
        alerts = []

        # 1. Budget enforcement
        if episode.is_budget_exceeded():
            return ControlDecision(
                allowed=False,
                block_type=BlockType.BUDGET_EXCEEDED,
                message=f"Budget exceeded: {episode.step_count}/{episode.budget.max_steps} steps",
                required_action="Escalate or conclude episode",
                phase_change=Phase.ESCALATE
            )

        # 2. Memory binding enforcement
        if not step.retrieved_memories and step.action_type.value != "reasoning":
            return ControlDecision(
                allowed=False,
                block_type=BlockType.MEMORY_REQUIRED,
                message="No memories retrieved before action",
                required_action="Retrieve relevant memories or explicitly state none exist"
            )

        # 3. Step validity check
        valid, missing = step.is_valid_before_action()
        if not valid:
            return ControlDecision(
                allowed=False,
                block_type=BlockType.PHASE_VIOLATION,
                message=f"Step missing required fields: {missing}",
                required_action=f"Fill in: {', '.join(missing)}"
            )

        # 4. Run watchers
        alerts.extend(self._run_watchers(episode, step, recent_steps))

        # Check for blocking alerts
        blocking_alerts = [a for a in alerts if a.severity == "blocking"]
        if blocking_alerts:
            alert = blocking_alerts[0]
            return ControlDecision(
                allowed=False,
                block_type=BlockType.LOOP_DETECTED,
                message=alert.message,
                required_action=alert.suggested_action,
                phase_change=Phase.DIAGNOSE if alert.watcher_type != WatcherType.MEMORY_BYPASS else None,
                alerts=alerts
            )

        return ControlDecision(allowed=True, alerts=alerts)

    def check_after_action(self, episode: Episode, step: Step) -> ControlDecision:
        """
        Check if the step result is valid.
        Called AFTER the action completes.
        """
        # Validation enforcement
        valid, missing = step.is_valid_after_action()
        if not valid:
            return ControlDecision(
                allowed=False,
                block_type=BlockType.VALIDATION_REQUIRED,
                message=f"Step missing post-action fields: {missing}",
                required_action=f"Fill in: {', '.join(missing)}"
            )

        return ControlDecision(allowed=True)

    def _run_watchers(
        self,
        episode: Episode,
        step: Step,
        recent_steps: List[Step]
    ) -> List[WatcherAlert]:
        """Run all watchers and collect alerts."""
        alerts = []

        # Initialize episode tracking if needed
        eid = episode.episode_id
        if eid not in self.error_signatures:
            self.error_signatures[eid] = []
        if eid not in self.file_modifications:
            self.file_modifications[eid] = {}
        if eid not in self.confidence_history:
            self.confidence_history[eid] = []
        if eid not in self.steps_without_new_info:
            self.steps_without_new_info[eid] = 0

        # 1. Repeat Error Watcher
        alert = self._watch_repeat_error(episode, step, recent_steps)
        if alert:
            alerts.append(alert)

        # 2. No New Info Watcher
        alert = self._watch_no_new_info(episode, step, recent_steps)
        if alert:
            alerts.append(alert)

        # 3. Diff Thrash Watcher
        alert = self._watch_diff_thrash(episode, step)
        if alert:
            alerts.append(alert)

        # 4. Confidence Stagnation Watcher
        alert = self._watch_confidence_stagnation(episode, step)
        if alert:
            alerts.append(alert)

        # 5. Memory Bypass Watcher (already handled in check_before_action)
        # 6. Trace Gap Watcher
        alert = self._watch_trace_gap(step)
        if alert:
            alerts.append(alert)

        return alerts

    def _watch_repeat_error(
        self,
        episode: Episode,
        step: Step,
        recent_steps: List[Step]
    ) -> Optional[WatcherAlert]:
        """Detect same error signature occurring multiple times."""
        # Check recent failed steps for similar errors
        failed_steps = [s for s in recent_steps if s.evaluation == Evaluation.FAIL]

        if len(failed_steps) < 2:
            return None

        # Extract error signatures from results
        signatures = []
        for s in failed_steps[-5:]:  # Last 5 failures
            # Simple signature: first 50 chars of result
            sig = s.result[:50].lower() if s.result else ""
            signatures.append(sig)

        # Check for repeats
        from collections import Counter
        counts = Counter(signatures)
        repeated = [(sig, count) for sig, count in counts.items() if count >= self.repeat_error_threshold and sig]

        if repeated:
            sig, count = repeated[0]
            return WatcherAlert(
                watcher_type=WatcherType.REPEAT_ERROR,
                message=f"Same error repeated {count}x: '{sig[:30]}...'",
                severity="blocking",
                suggested_action="Enter diagnostic phase with new hypothesis",
                evidence={"signature": sig, "count": count}
            )

        return None

    def _watch_no_new_info(
        self,
        episode: Episode,
        step: Step,
        recent_steps: List[Step]
    ) -> Optional[WatcherAlert]:
        """Detect steps without new evidence."""
        eid = episode.episode_id

        # Check if step provides new information
        has_new_info = (
            step.surprise_level > 0.3 or
            step.evaluation != Evaluation.UNKNOWN or
            len(step.lesson) > 20
        )

        if has_new_info:
            self.steps_without_new_info[eid] = 0
        else:
            self.steps_without_new_info[eid] += 1

        if self.steps_without_new_info[eid] >= self.no_new_info_threshold:
            return WatcherAlert(
                watcher_type=WatcherType.NO_NEW_INFO,
                message=f"{self.steps_without_new_info[eid]} steps without new evidence",
                severity="blocking",
                suggested_action="Stop; create explicit data-gathering plan",
                evidence={"steps_count": self.steps_without_new_info[eid]}
            )

        return None

    def _watch_diff_thrash(
        self,
        episode: Episode,
        step: Step
    ) -> Optional[WatcherAlert]:
        """Detect same file being modified repeatedly."""
        eid = episode.episode_id

        # Extract file path from action details
        file_path = step.action_details.get("file_path", "")
        if not file_path:
            return None

        # Track modifications
        if file_path not in self.file_modifications[eid]:
            self.file_modifications[eid][file_path] = 0
        self.file_modifications[eid][file_path] += 1

        count = self.file_modifications[eid][file_path]
        if count >= self.diff_thrash_threshold:
            return WatcherAlert(
                watcher_type=WatcherType.DIFF_THRASH,
                message=f"File modified {count}x: {file_path}",
                severity="warning" if count == self.diff_thrash_threshold else "blocking",
                suggested_action="Freeze file, focus elsewhere, then return with clear plan",
                evidence={"file_path": file_path, "count": count}
            )

        return None

    def _watch_confidence_stagnation(
        self,
        episode: Episode,
        step: Step
    ) -> Optional[WatcherAlert]:
        """Detect confidence not improving over multiple steps."""
        eid = episode.episode_id

        # Track confidence
        self.confidence_history[eid].append(step.confidence_after)

        # Need enough history
        if len(self.confidence_history[eid]) < self.confidence_stagnation_steps:
            return None

        # Check recent confidence deltas
        recent = self.confidence_history[eid][-self.confidence_stagnation_steps:]
        deltas = [abs(recent[i+1] - recent[i]) for i in range(len(recent)-1)]

        if all(d < self.confidence_delta_threshold for d in deltas):
            return WatcherAlert(
                watcher_type=WatcherType.CONFIDENCE_STAGNATION,
                message=f"Confidence stagnant for {len(deltas)+1} steps",
                severity="warning",
                suggested_action="Try alternative approach or escalate",
                evidence={"confidences": recent, "deltas": deltas}
            )

        return None

    def _watch_trace_gap(self, step: Step) -> Optional[WatcherAlert]:
        """Detect missing trace_id on a step."""
        if getattr(step, "trace_id", None):
            return None
        try:
            from lib.config_authority import resolve_section, env_bool
            _e = resolve_section("eidos", env_overrides={"trace_strict": env_bool("SPARK_TRACE_STRICT")}).data
            strict = bool(_e.get("trace_strict", False))
        except Exception:
            strict = os.environ.get("SPARK_TRACE_STRICT", "").strip().lower() in {"1", "true", "yes", "on"}
        return WatcherAlert(
            watcher_type=WatcherType.TRACE_GAP,
            message="Step missing trace_id binding",
            severity="blocking" if strict else "warning",
            suggested_action="Bind trace_id to step/evidence/outcomes",
        )

    def suggest_phase_transition(
        self,
        episode: Episode,
        step: Step,
        recent_steps: List[Step]
    ) -> Optional[Phase]:
        """
        Suggest a phase transition based on current state.
        Phase transitions are rule-driven, not LLM-decided.
        """
        current = episode.phase

        # EXPLORE → DIAGNOSE: When we have enough information
        if current == Phase.EXPLORE:
            # After 3+ explore steps with evidence
            explore_steps = [s for s in recent_steps if s.evaluation != Evaluation.UNKNOWN]
            if len(explore_steps) >= 3:
                return Phase.DIAGNOSE

        # DIAGNOSE → EXECUTE: When we have a clear hypothesis
        if current == Phase.DIAGNOSE:
            # After hypothesis validated or high confidence
            if step.confidence_after >= 0.7:
                return Phase.EXECUTE

        # EXECUTE → CONSOLIDATE: On success
        if current == Phase.EXECUTE:
            if step.evaluation == Evaluation.PASS:
                return Phase.CONSOLIDATE

        # Any → ESCALATE: On budget exceeded or repeated failures
        if episode.is_budget_exceeded():
            return Phase.ESCALATE

        # Check for repeated failures
        recent_failures = [s for s in recent_steps[-5:] if s.evaluation == Evaluation.FAIL]
        if len(recent_failures) >= 3:
            return Phase.ESCALATE

        return None

    def record_error(self, episode: Episode, error_signature: str):
        """Record an error for tracking."""
        episode.record_error(error_signature)
        eid = episode.episode_id
        if eid not in self.error_signatures:
            self.error_signatures[eid] = []
        self.error_signatures[eid].append(error_signature)

    def reset_episode_tracking(self, episode_id: str):
        """Clear tracking state for an episode."""
        self.error_signatures.pop(episode_id, None)
        self.file_modifications.pop(episode_id, None)
        self.confidence_history.pop(episode_id, None)
        self.steps_without_new_info.pop(episode_id, None)


# Singleton instance
_control_plane: Optional[ControlPlane] = None


def get_control_plane() -> ControlPlane:
    """Get the singleton control plane instance."""
    global _control_plane
    if _control_plane is None:
        _control_plane = ControlPlane()
    return _control_plane
