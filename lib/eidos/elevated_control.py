"""
EIDOS Elevated Control Layer: Keep Intelligence High, React When It Falls

This module implements:
1. Operating States (Finite State Machine)
2. Non-Negotiable Step Contract (Step Envelope)
3. Memory Binding Enforcement
4. Budget Management
5. Watchers (Automatic Rabbit-Hole Detection)
6. Escape Protocol (Universal Recovery Routine)

The Core Principle:
> "If progress is unclear, stop acting and change the question."

A rabbit hole is NOT lack of intelligence - it's LOSS OF PROGRESS SIGNAL.
This layer detects loss early and forces correction.
"""

import json
import time
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    Episode, Step, Distillation, Phase, Outcome, Evaluation,
    DistillationType, ActionType, Budget, VALID_TRANSITIONS
)
from .store import get_store

import re


def _generalize_failed_decision(raw: str) -> str:
    """Extract a generalizable tool/action pattern from a literal decision string.

    Instead of encoding 'Execute: cd <USER_HOME> && find ...' verbatim,
    produce something like 'Bash find commands' that matches future similar actions
    without matching every unrelated Bash command.
    """
    low = raw.lower().strip()

    # Extract tool type from "Execute: ..." or "Modify ..." or "Inspect ..." patterns
    tool_map = {
        "execute:": "Bash",
        "run command:": "Bash",
        "modify": "Edit",
        "inspect": "Read",
        "locate files": "Glob",
        "search for": "Grep",
    }
    tool_type = "tool"
    for prefix, tname in tool_map.items():
        if low.startswith(prefix):
            tool_type = tname
            break

    # Extract the actual command verb from Bash decisions
    if tool_type == "Bash":
        # Find common command names in the decision
        cmd_patterns = re.findall(
            r'\b(find|grep|cd|ls|dir|cat|type|timeout|curl|pip|npm|git|python|pytest|mkdir|rm|cp|mv|chmod|findstr)\b',
            low
        )
        if cmd_patterns:
            return f"'{cmd_patterns[0]}' commands"

    # For non-Bash, use the tool type
    return f"{tool_type} operations"


# ===== WATCHER TYPES =====

class WatcherType(Enum):
    """Types of watchers that detect rabbit holes."""
    REPEAT_FAILURE = "repeat_failure"        # Same error 2x
    NO_NEW_EVIDENCE = "no_new_evidence"      # N steps without evidence
    DIFF_THRASH = "diff_thrash"              # Same file modified 3x
    CONFIDENCE_STAGNATION = "confidence_stagnation"  # Delta < 0.05 for 3 steps
    MEMORY_BYPASS = "memory_bypass"          # Action without memory citation
    BUDGET_HALF_NO_PROGRESS = "budget_half_no_progress"  # >50% budget, no progress
    SCOPE_CREEP = "scope_creep"              # Plan grows while progress doesn't
    VALIDATION_GAP = "validation_gap"        # >2 steps without validation evidence
    TRACE_GAP = "trace_gap"                  # Missing trace_id bindings


class WatcherSeverity(Enum):
    """Severity of watcher alerts."""
    WARNING = "warning"    # Log and continue
    BLOCK = "block"        # Block action, require fix
    FORCE = "force"        # Force state transition


@dataclass
class WatcherAlert:
    """An alert from a watcher."""
    watcher: WatcherType
    severity: WatcherSeverity
    message: str
    forced_phase: Optional[Phase] = None
    required_output: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "watcher": self.watcher.value,
            "severity": self.severity.value,
            "message": self.message,
            "forced_phase": self.forced_phase.value if self.forced_phase else None,
            "required_output": self.required_output,
            "timestamp": self.timestamp,
        }


# ===== ESCAPE PROTOCOL =====

@dataclass
class EscapeProtocolResult:
    """Result of running the escape protocol."""
    triggered: bool = False
    reason: str = ""
    summary: str = ""
    smallest_failing_unit: str = ""
    flipped_question: str = ""
    hypotheses: List[str] = field(default_factory=list)
    discriminating_test: str = ""
    learning_artifact: Optional[Distillation] = None
    new_phase: Optional[Phase] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "triggered": self.triggered,
            "reason": self.reason,
            "summary": self.summary,
            "smallest_failing_unit": self.smallest_failing_unit,
            "flipped_question": self.flipped_question,
            "hypotheses": self.hypotheses,
            "discriminating_test": self.discriminating_test,
            "learning_artifact": self.learning_artifact.to_dict() if self.learning_artifact else None,
            "new_phase": self.new_phase.value if self.new_phase else None,
        }


# ===== STEP ENVELOPE VALIDATOR =====

@dataclass
class StepEnvelopeValidation:
    """Validation result for step envelope."""
    valid_before: bool = False
    valid_after: bool = False
    missing_before: List[str] = field(default_factory=list)
    missing_after: List[str] = field(default_factory=list)
    memory_binding_ok: bool = False
    memory_binding_issue: str = ""

    @property
    def can_act(self) -> bool:
        """Can we proceed with the action?"""
        return self.valid_before and self.memory_binding_ok

    @property
    def can_distill(self) -> bool:
        """Can this step produce distillations?"""
        return self.valid_before and self.valid_after


def validate_step_envelope(step: Step, memories_exist: bool = False) -> StepEnvelopeValidation:
    """
    Validate that a step meets the Step Envelope contract.

    BEFORE ACTION (required):
    - intent, hypothesis, prediction, stop_condition
    - budget_snapshot, memory_citations

    AFTER ACTION (required):
    - result, validation_evidence, evaluation
    - lesson, confidence_delta
    """
    result = StepEnvelopeValidation()

    # Before action validation
    missing_before = []
    if not step.intent:
        missing_before.append("intent")
    if not step.hypothesis and not step.prediction:
        missing_before.append("hypothesis or prediction")
    if not step.stop_condition:
        missing_before.append("stop_condition")

    result.missing_before = missing_before
    result.valid_before = len(missing_before) == 0

    # Memory binding validation
    if memories_exist:
        if not step.memory_cited and not step.memory_absent_declared:
            result.memory_binding_ok = False
            result.memory_binding_issue = "Memory exists but not cited or declared absent"
        else:
            result.memory_binding_ok = True
    else:
        # No memories exist, so binding is automatically OK if declared absent
        result.memory_binding_ok = step.memory_absent_declared or not memories_exist

    # After action validation
    missing_after = []
    if not step.result:
        missing_after.append("result")
    if step.evaluation == Evaluation.UNKNOWN:
        missing_after.append("evaluation")
    if not step.validated and not step.validation_method:
        missing_after.append("validation")

    result.missing_after = missing_after
    result.valid_after = len(missing_after) == 0

    return result


def _trace_gap_severity() -> WatcherSeverity:
    try:
        from lib.config_authority import resolve_section, env_bool
        _e = resolve_section("eidos", env_overrides={"trace_strict": env_bool("SPARK_TRACE_STRICT")}).data
        strict = bool(_e.get("trace_strict", False))
    except Exception:
        strict = os.environ.get("SPARK_TRACE_STRICT", "").strip().lower() in {"1", "true", "yes", "on"}
    return WatcherSeverity.BLOCK if strict else WatcherSeverity.WARNING


# ===== WATCHERS =====

class WatcherEngine:
    """
    Automatic rabbit-hole detection engine.

    Implements watchers that continuously monitor for signs of trouble:
    - Repeat Failure: Same error 2x → force DIAGNOSE
    - No New Evidence: 5 steps without evidence → force DIAGNOSE
    - Diff Thrash: Same file 3x → freeze file, force SIMPLIFY
    - Confidence Stagnation: Delta < 0.05 for 3 steps → force PLAN
    - Memory Bypass: Action without citation → BLOCK
    - Budget Half No Progress: >50% budget, no progress → force SIMPLIFY
    """

    def __init__(self):
        self.alert_history: List[WatcherAlert] = []
        self._max_alert_history = 2000

    def check_all(
        self,
        episode: Episode,
        step: Step,
        recent_steps: List[Step],
        memories_exist: bool = False
    ) -> List[WatcherAlert]:
        """Run all watchers and return any alerts."""
        alerts = []

        # Watcher A: Repeat Failure
        alert = self._check_repeat_failure(episode, step)
        if alert:
            alerts.append(alert)

        # Watcher B: No New Evidence
        alert = self._check_no_new_evidence(episode, recent_steps)
        if alert:
            alerts.append(alert)

        # Watcher C: Diff Thrash
        alert = self._check_diff_thrash(episode, step)
        if alert:
            alerts.append(alert)

        # Watcher D: Confidence Stagnation
        alert = self._check_confidence_stagnation(episode)
        if alert:
            alerts.append(alert)

        # Watcher E: Memory Bypass
        alert = self._check_memory_bypass(step, memories_exist)
        if alert:
            alerts.append(alert)

        # Watcher F: Budget Half No Progress
        alert = self._check_budget_half_no_progress(episode, recent_steps)
        if alert:
            alerts.append(alert)

        # Watcher G: Scope Creep
        alert = self._check_scope_creep(episode, recent_steps)
        if alert:
            alerts.append(alert)

        # Watcher H: Validation Gap
        alert = self._check_validation_gap(recent_steps)
        if alert:
            alerts.append(alert)

        # Watcher I: Trace Gap
        alert = self._check_trace_gap(step, recent_steps)
        if alert:
            alerts.append(alert)

        self.alert_history.extend(alerts)
        if len(self.alert_history) > self._max_alert_history:
            self.alert_history = self.alert_history[-self._max_alert_history:]
        return alerts

    def _check_repeat_failure(self, episode: Episode, step: Step) -> Optional[WatcherAlert]:
        """Watcher A: Same error signature >=2 times."""
        # Check error counts
        for error_sig, count in episode.error_counts.items():
            if count >= 2:
                return WatcherAlert(
                    watcher=WatcherType.REPEAT_FAILURE,
                    severity=WatcherSeverity.FORCE,
                    message=f"Error '{error_sig[:50]}' occurred {count} times",
                    forced_phase=Phase.DIAGNOSE,
                    required_output="new hypothesis + discriminating test"
                )
        return None

    def _check_no_new_evidence(self, episode: Episode, recent_steps: List[Step]) -> Optional[WatcherAlert]:
        """Watcher B: 5 steps with no new evidence."""
        if episode.no_evidence_streak >= episode.budget.no_evidence_limit:
            return WatcherAlert(
                watcher=WatcherType.NO_NEW_EVIDENCE,
                severity=WatcherSeverity.FORCE,
                message=f"No new evidence for {episode.no_evidence_streak} steps",
                forced_phase=Phase.DIAGNOSE,
                required_output="evidence-gather plan only"
            )
        return None

    def _check_diff_thrash(self, episode: Episode, step: Step) -> Optional[WatcherAlert]:
        """Watcher C: Same file modified >=3 times."""
        frozen_files = episode.get_frozen_files()
        if frozen_files:
            # Check if current step is trying to modify a frozen file
            file_path = step.action_details.get("file_path", "")
            if file_path in frozen_files:
                return WatcherAlert(
                    watcher=WatcherType.DIFF_THRASH,
                    severity=WatcherSeverity.BLOCK,
                    message=f"File '{file_path}' has been modified too many times",
                    forced_phase=Phase.SIMPLIFY,
                    required_output="minimal reproduction or isolation plan"
                )
        return None

    def _check_confidence_stagnation(self, episode: Episode) -> Optional[WatcherAlert]:
        """Watcher D: Confidence delta < 0.05 across 3 steps."""
        if episode.is_confidence_stagnant():
            return WatcherAlert(
                watcher=WatcherType.CONFIDENCE_STAGNATION,
                severity=WatcherSeverity.FORCE,
                message="Confidence has not improved in last 3 steps",
                forced_phase=Phase.PLAN,
                required_output="2 alternate hypotheses + tests"
            )
        return None

    def _check_memory_bypass(self, step: Step, memories_exist: bool) -> Optional[WatcherAlert]:
        """Watcher E: Plan/action without memory citations when memory exists."""
        if memories_exist and not step.memory_cited and not step.memory_absent_declared:
            return WatcherAlert(
                watcher=WatcherType.MEMORY_BYPASS,
                severity=WatcherSeverity.BLOCK,
                message="Action proposed without memory citation",
                required_output="retrieval + citation"
            )
        return None

    def _check_budget_half_no_progress(self, episode: Episode, recent_steps: List[Step]) -> Optional[WatcherAlert]:
        """Watcher F: >50% budget used with no progress."""
        if episode.budget_percentage_used() > 0.5:
            # Check if recent steps made progress
            recent_progress = [s.progress_made for s in recent_steps[-5:] if hasattr(s, 'progress_made')]
            if recent_progress and not any(recent_progress):
                return WatcherAlert(
                    watcher=WatcherType.BUDGET_HALF_NO_PROGRESS,
                    severity=WatcherSeverity.FORCE,
                    message=f"Budget {episode.budget_percentage_used():.0%} used with no recent progress",
                    forced_phase=Phase.SIMPLIFY,
                    required_output="scope reduction + minimal failing unit"
                )
        return None

    def _check_scope_creep(self, episode: Episode, recent_steps: List[Step]) -> Optional[WatcherAlert]:
        """Watcher G: Plan size grows while progress doesn't."""
        if len(recent_steps) < 5:
            return None

        # Check if we're accumulating alternatives/assumptions without progress
        early_steps = recent_steps[:len(recent_steps)//2]
        late_steps = recent_steps[len(recent_steps)//2:]

        early_complexity = sum(
            len(s.alternatives) + len(s.assumptions)
            for s in early_steps
        )
        late_complexity = sum(
            len(s.alternatives) + len(s.assumptions)
            for s in late_steps
        )

        early_progress = sum(1 for s in early_steps if s.progress_made)
        late_progress = sum(1 for s in late_steps if s.progress_made)

        # Complexity growing but progress not
        if late_complexity > early_complexity * 1.5 and late_progress <= early_progress:
            return WatcherAlert(
                watcher=WatcherType.SCOPE_CREEP,
                severity=WatcherSeverity.FORCE,
                message="Scope/complexity growing while progress stagnates",
                forced_phase=Phase.SIMPLIFY,
                required_output="reduce scope by 50% - focus on one thing"
            )
        return None

    def _check_validation_gap(self, recent_steps: List[Step]) -> Optional[WatcherAlert]:
        """Watcher H: >2 steps executed without validation evidence."""
        if len(recent_steps) < 3:
            return None

        # Check last 3 steps for validation evidence
        recent_without_validation = 0
        for step in recent_steps[-3:]:
            if not step.validated and not step.validation_evidence:
                recent_without_validation += 1

        if recent_without_validation >= 2:
            return WatcherAlert(
                watcher=WatcherType.VALIDATION_GAP,
                severity=WatcherSeverity.FORCE,
                message=f"{recent_without_validation} recent steps lack validation evidence",
                forced_phase=Phase.VALIDATE,
                required_output="validation-only step - verify current state"
            )

    def _check_trace_gap(self, step: Step, recent_steps: List[Step]) -> Optional[WatcherAlert]:
        """Watcher I: Missing trace_id bindings on steps."""
        missing = [s for s in recent_steps[-5:] if not getattr(s, "trace_id", None)]
        if not getattr(step, "trace_id", None) and step not in missing:
            missing.append(step)
        if not missing:
            return None
        severity = _trace_gap_severity()
        return WatcherAlert(
            watcher=WatcherType.TRACE_GAP,
            severity=severity,
            message=f"{len(missing)} step(s) missing trace_id",
            required_output="bind trace_id to steps/evidence/outcomes",
        )

    def get_blocking_alerts(self, alerts: List[WatcherAlert]) -> List[WatcherAlert]:
        """Get alerts that should block the action."""
        return [a for a in alerts if a.severity in (WatcherSeverity.BLOCK, WatcherSeverity.FORCE)]

    def count_watcher_triggers(self, watcher_type: WatcherType) -> int:
        """Count how many times a watcher has triggered."""
        return len([a for a in self.alert_history if a.watcher == watcher_type])


# ===== ESCAPE PROTOCOL =====

class EscapeProtocol:
    """
    Universal recovery routine when stuck.

    Trigger conditions (any one fires):
    - same failure twice
    - confidence not improving
    - no new evidence in N steps
    - same object modified repeatedly
    - budget halfway used with no progress

    Steps:
    1. FREEZE (no edits)
    2. SUMMARIZE (what we know/tried/observed)
    3. ISOLATE (smallest failing unit)
    4. FLIP QUESTION ("What would prove this approach is wrong?")
    5. GENERATE 3 hypotheses max
    6. PICK 1 discriminating test
    7. Execute test only
    8. If still stuck: ESCALATE with crisp request

    Required learning artifact: Even if stuck, produce one:
    - sharp edge
    - anti-pattern
    - "avoid under X"
    """

    def should_trigger(
        self,
        episode: Episode,
        alerts: List[WatcherAlert],
        watcher_engine: WatcherEngine
    ) -> Tuple[bool, str]:
        """Check if escape protocol should trigger."""
        # Condition 1: Any watcher triggered twice
        for watcher_type in WatcherType:
            if watcher_engine.count_watcher_triggers(watcher_type) >= 2:
                return True, f"Watcher {watcher_type.value} triggered twice"

        # Condition 2: Budget near exhaustion (>80%)
        if episode.budget_percentage_used() > 0.8:
            return True, f"Budget {episode.budget_percentage_used():.0%} exhausted"

        # Condition 3: Already has a FORCE alert
        force_alerts = [a for a in alerts if a.severity == WatcherSeverity.FORCE]
        if len(force_alerts) >= 2:
            return True, "Multiple force alerts"

        return False, ""

    def execute(
        self,
        episode: Episode,
        recent_steps: List[Step],
        trigger_reason: str
    ) -> EscapeProtocolResult:
        """
        Execute the escape protocol.

        This is where we stop, breathe, and change the question.
        """
        result = EscapeProtocolResult(
            triggered=True,
            reason=trigger_reason
        )

        # Step 1: FREEZE - no more edits (handled by caller)

        # Step 2: SUMMARIZE
        result.summary = self._generate_summary(episode, recent_steps)

        # Step 3: ISOLATE - find smallest failing unit
        result.smallest_failing_unit = self._find_smallest_failing_unit(recent_steps)

        # Step 4: FLIP QUESTION
        result.flipped_question = self._flip_question(episode, recent_steps)

        # Step 5: GENERATE 3 hypotheses max
        result.hypotheses = self._generate_hypotheses(episode, recent_steps)

        # Step 6: PICK 1 discriminating test
        result.discriminating_test = self._pick_discriminating_test(result.hypotheses)

        # Step 7: Determine next phase
        if episode.stuck_count >= 2:
            result.new_phase = Phase.ESCALATE
        else:
            result.new_phase = Phase.DIAGNOSE

        # Required learning artifact
        result.learning_artifact = self._create_learning_artifact(
            episode, recent_steps, trigger_reason
        )

        return result

    def _generate_summary(self, episode: Episode, recent_steps: List[Step]) -> str:
        """Generate a factual summary of what we know/tried/observed."""
        lines = [
            f"Goal: {episode.goal}",
            f"Steps taken: {episode.step_count}",
            f"Phase: {episode.phase.value}",
            f"Errors: {len(episode.error_counts)} unique signatures",
        ]

        # Recent attempts
        failed_steps = [s for s in recent_steps if s.evaluation == Evaluation.FAIL]
        if failed_steps:
            lines.append(f"Recent failures: {len(failed_steps)}")
            for step in failed_steps[-3:]:
                lines.append(f"  - {step.decision[:50]}: {step.result[:50]}")

        return "\n".join(lines)

    def _find_smallest_failing_unit(self, recent_steps: List[Step]) -> str:
        """Find the smallest failing unit from recent steps."""
        failed_steps = [s for s in recent_steps if s.evaluation == Evaluation.FAIL]
        if not failed_steps:
            return "No clear failing unit identified"

        # Look for common patterns in failures
        files_involved = []
        for step in failed_steps:
            file_path = step.action_details.get("file_path", "")
            if file_path:
                files_involved.append(file_path)

        if files_involved:
            from collections import Counter
            most_common = Counter(files_involved).most_common(1)
            if most_common:
                return f"File: {most_common[0][0]}"

        # Fallback to most recent failure
        return f"Operation: {failed_steps[-1].decision[:100]}"

    def _flip_question(self, episode: Episode, recent_steps: List[Step]) -> str:
        """
        Replace "How do I fix this?" with "What must be true for this to be impossible?"
        """
        # Analyze what we've been trying
        recent_decisions = [s.decision for s in recent_steps[-5:]]
        recent_assumptions = []
        for step in recent_steps[-5:]:
            recent_assumptions.extend(step.assumptions)

        # Find the hidden assumption
        if recent_assumptions:
            return f"What if assumption '{recent_assumptions[0]}' is wrong?"
        elif recent_decisions:
            return f"What would make '{recent_decisions[0][:50]}' impossible to succeed?"
        else:
            return "What hidden constraint are we not seeing?"

    def _generate_hypotheses(self, episode: Episode, recent_steps: List[Step]) -> List[str]:
        """Generate up to 3 hypotheses."""
        hypotheses = []

        # Hypothesis 1: The obvious one isn't true
        failed_steps = [s for s in recent_steps if s.evaluation == Evaluation.FAIL]
        if failed_steps:
            last_failure = failed_steps[-1]
            if last_failure.assumptions:
                hypotheses.append(
                    f"Assumption '{last_failure.assumptions[0]}' is false"
                )

        # Hypothesis 2: Wrong level of abstraction
        hypotheses.append("The problem is at a different layer than we're operating")

        # Hypothesis 3: Missing prerequisite
        hypotheses.append("There's a prerequisite step we haven't identified")

        return hypotheses[:3]

    def _pick_discriminating_test(self, hypotheses: List[str]) -> str:
        """Pick a test that discriminates between hypotheses."""
        if not hypotheses:
            return "Read the actual state/content before any modification"

        # A discriminating test should tell us which hypothesis is correct
        return f"Test: Verify the truth of '{hypotheses[0][:50]}' directly"

    def _create_learning_artifact(
        self,
        episode: Episode,
        recent_steps: List[Step],
        trigger_reason: str
    ) -> Distillation:
        """
        Create a learning artifact from the rabbit hole.

        Even if still stuck, produce one:
        - sharp edge
        - anti-pattern
        - "avoid under X"
        """
        # Analyze what went wrong
        error_types = list(episode.error_counts.keys())
        failed_decisions = [s.decision for s in recent_steps if s.evaluation == Evaluation.FAIL]

        if error_types:
            statement = f"When error '{error_types[0][:30]}' occurs twice, stop and diagnose instead of retrying"
            dist_type = DistillationType.SHARP_EDGE
        elif failed_decisions:
            # Extract the generalizable pattern, not the literal command
            # e.g. "Execute: cd <USER_HOME> && find ..." -> "Bash find commands"
            raw = failed_decisions[0]
            tool_hint = _generalize_failed_decision(raw)
            statement = f"When repeated {tool_hint} attempts fail without progress, step back and try a different approach"
            dist_type = DistillationType.ANTI_PATTERN
        else:
            statement = "When budget is high without progress, simplify scope"
            dist_type = DistillationType.HEURISTIC

        return Distillation(
            distillation_id="",
            type=dist_type,
            statement=statement,
            domains=["escape_protocol", "rabbit_hole_recovery"],
            triggers=[trigger_reason],
            source_steps=[s.step_id for s in recent_steps[-5:]],
            confidence=0.7,  # Initial confidence
        )


# ===== STATE MACHINE =====

class StateMachine:
    """
    Enforces the phase state machine.

    The LLM cannot "decide" to skip states. The control plane enforces.
    """

    def can_transition(self, from_phase: Phase, to_phase: Phase) -> bool:
        """Check if a transition is valid."""
        valid = VALID_TRANSITIONS.get(from_phase, [])
        return to_phase in valid

    def get_valid_transitions(self, from_phase: Phase) -> List[Phase]:
        """Get all valid transitions from a phase."""
        return VALID_TRANSITIONS.get(from_phase, [])

    def force_transition(
        self,
        episode: Episode,
        to_phase: Phase,
        reason: str
    ) -> Tuple[bool, str]:
        """Force a transition (used by watchers and escape protocol)."""
        # Some transitions are always allowed (HALT, ESCALATE)
        if to_phase in (Phase.HALT, Phase.ESCALATE):
            return True, f"Forced to {to_phase.value}: {reason}"

        # Check if valid transition
        if self.can_transition(episode.phase, to_phase):
            return True, f"Valid transition to {to_phase.value}: {reason}"

        # Invalid but forced (log warning)
        return True, f"FORCED (invalid) transition to {to_phase.value}: {reason}"


# ===== ELEVATED CONTROL PLANE =====

class ElevatedControlPlane:
    """
    The main control plane that keeps intelligence elevated.

    Combines:
    - State machine enforcement
    - Step envelope validation
    - Watcher monitoring
    - Escape protocol execution
    - Memory binding enforcement

    The mantra:
    > "If progress is unclear, stop acting and change the question."
    """

    def __init__(self):
        self.state_machine = StateMachine()
        self.watcher_engine = WatcherEngine()
        self.escape_protocol = EscapeProtocol()
        self.store = get_store()

    def check_before_action(
        self,
        episode: Episode,
        step: Step,
        recent_steps: List[Step],
        memories_exist: bool = False
    ) -> Tuple[bool, List[WatcherAlert], Optional[EscapeProtocolResult]]:
        """
        Check all conditions before allowing an action.

        Returns:
            (allowed, alerts, escape_result)
        """
        # 1. Validate step envelope
        envelope_validation = validate_step_envelope(step, memories_exist)
        if not envelope_validation.can_act:
            return False, [WatcherAlert(
                watcher=WatcherType.MEMORY_BYPASS,
                severity=WatcherSeverity.BLOCK,
                message=f"Step envelope invalid: {envelope_validation.missing_before}"
            )], None

        # 2. Run watchers
        alerts = self.watcher_engine.check_all(
            episode, step, recent_steps, memories_exist
        )

        # 3. Check if escape protocol should trigger
        should_escape, escape_reason = self.escape_protocol.should_trigger(
            episode, alerts, self.watcher_engine
        )

        if should_escape:
            escape_result = self.escape_protocol.execute(
                episode, recent_steps, escape_reason
            )
            # Save the learning artifact
            if escape_result.learning_artifact:
                self.store.save_distillation(escape_result.learning_artifact)

            return False, alerts, escape_result

        # 4. Check for blocking alerts
        blocking = self.watcher_engine.get_blocking_alerts(alerts)
        if blocking:
            return False, alerts, None

        return True, alerts, None

    def process_after_action(
        self,
        episode: Episode,
        step: Step
    ) -> Tuple[Phase, List[str]]:
        """
        Process after an action completes.

        Updates episode tracking and suggests next phase.

        Returns:
            (suggested_phase, messages)
        """
        messages = []

        # Update episode tracking
        if step.result:
            episode.record_evidence(step.evidence_gathered)

        if step.evaluation == Evaluation.FAIL:
            # Extract error signature
            error_sig = step.action_details.get("tool", "unknown")
            if step.result:
                error_sig += f":{step.result[:30]}"
            episode.record_error(error_sig)

        # Track file touches
        file_path = step.action_details.get("file_path", "")
        if file_path and step.action_type == ActionType.TOOL_CALL:
            tool = step.action_details.get("tool", "")
            if tool in ("Edit", "Write"):
                episode.record_file_touch(file_path)

        # Track confidence
        episode.record_confidence(step.confidence_after)

        # Determine next phase based on current state
        current_phase = episode.phase
        suggested_phase = current_phase

        if step.evaluation == Evaluation.PASS:
            if current_phase == Phase.EXECUTE:
                suggested_phase = Phase.VALIDATE
                messages.append("Success - moving to VALIDATE")
            elif current_phase == Phase.VALIDATE:
                suggested_phase = Phase.CONSOLIDATE
                messages.append("Validation passed - moving to CONSOLIDATE")

        elif step.evaluation == Evaluation.FAIL:
            if current_phase == Phase.EXECUTE:
                # Check if we need to diagnose
                if episode.is_error_limit_exceeded(step.action_details.get("tool", "")):
                    suggested_phase = Phase.DIAGNOSE
                    messages.append("Repeated failures - moving to DIAGNOSE")

        # Check budget
        if episode.is_budget_exceeded():
            suggested_phase = Phase.HALT
            messages.append("Budget exceeded - HALT")

        return suggested_phase, messages

    def initiate_escape(
        self,
        episode: Episode,
        recent_steps: List[Step],
        reason: str = "Manual trigger"
    ) -> EscapeProtocolResult:
        """Manually initiate escape protocol."""
        result = self.escape_protocol.execute(episode, recent_steps, reason)

        # Mark episode
        episode.escape_protocol_triggered = True
        episode.stuck_count += 1

        # Save learning artifact
        if result.learning_artifact:
            self.store.save_distillation(result.learning_artifact)

        return result


# ===== SINGLETON =====

_elevated_control_plane = None


def get_elevated_control_plane() -> ElevatedControlPlane:
    """Get singleton elevated control plane instance."""
    global _elevated_control_plane
    if _elevated_control_plane is None:
        _elevated_control_plane = ElevatedControlPlane()
    return _elevated_control_plane


# ===== METRICS TRACKING =====

@dataclass
class ControlMetrics:
    """Metrics for the control layer."""
    total_steps: int = 0
    steps_blocked: int = 0
    escape_protocols_triggered: int = 0
    watchers_fired: Dict[str, int] = field(default_factory=dict)
    avg_time_to_escape: float = 0.0  # How long to recognize rabbit hole
    rabbit_holes_recovered: int = 0
    learning_artifacts_created: int = 0


def calculate_control_metrics() -> ControlMetrics:
    """Calculate control layer metrics."""
    store = get_store()
    metrics = ControlMetrics()

    # Get all episodes with escape_protocol_triggered
    # This would require a database query
    # For now, return empty metrics
    return metrics
