"""
RequestTracker: Wrap user requests in EIDOS Step envelopes.

This is the foundation for connecting pattern detection to EIDOS.
Every user request becomes a trackable decision packet with:
- Intent (what user wants)
- Prediction (expected outcome)
- Decision (what action was taken)
- Result (what actually happened)
- Lesson (what we learned)

The key insight: User requests are not just text to parse -
they are decisions to track through the full lifecycle.
"""

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config_authority import resolve_section
from ..eidos.models import Step, Evaluation, ActionType


TUNEABLES_FILE = Path.home() / ".spark" / "tuneables.json"
REQUEST_TRACKER_MAX_PENDING = 50
REQUEST_TRACKER_MAX_COMPLETED = 200
REQUEST_TRACKER_MAX_AGE_SECONDS = 3600.0


def _load_request_tracker_config() -> Dict[str, Any]:
    resolved = resolve_section("request_tracker", runtime_path=TUNEABLES_FILE)
    return resolved.data if isinstance(resolved.data, dict) else {}


def _apply_request_tracker_config(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    global REQUEST_TRACKER_MAX_PENDING
    global REQUEST_TRACKER_MAX_COMPLETED
    global REQUEST_TRACKER_MAX_AGE_SECONDS

    applied: List[str] = []
    warnings: List[str] = []
    if not isinstance(cfg, dict):
        return {"applied": applied, "warnings": warnings}

    if "max_pending" in cfg:
        try:
            REQUEST_TRACKER_MAX_PENDING = max(10, min(500, int(cfg.get("max_pending") or 10)))
            applied.append("max_pending")
        except Exception:
            warnings.append("invalid_max_pending")

    if "max_completed" in cfg:
        try:
            REQUEST_TRACKER_MAX_COMPLETED = max(50, min(5000, int(cfg.get("max_completed") or 50)))
            applied.append("max_completed")
        except Exception:
            warnings.append("invalid_max_completed")

    if "max_age_seconds" in cfg:
        try:
            REQUEST_TRACKER_MAX_AGE_SECONDS = max(
                60.0,
                min(604800.0, float(cfg.get("max_age_seconds") or 60.0)),
            )
            applied.append("max_age_seconds")
        except Exception:
            warnings.append("invalid_max_age_seconds")

    return {"applied": applied, "warnings": warnings}


def apply_request_tracker_config(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    """Apply request tracker tuneables and update singleton if initialized."""
    result = _apply_request_tracker_config(cfg)
    tracker = _tracker
    if tracker is not None:
        tracker.max_pending = int(REQUEST_TRACKER_MAX_PENDING)
        tracker.max_completed = int(REQUEST_TRACKER_MAX_COMPLETED)
        tracker._prune_pending()
        tracker._prune_completed()
    return result


def get_request_tracker_config() -> Dict[str, Any]:
    return {
        "max_pending": int(REQUEST_TRACKER_MAX_PENDING),
        "max_completed": int(REQUEST_TRACKER_MAX_COMPLETED),
        "max_age_seconds": float(REQUEST_TRACKER_MAX_AGE_SECONDS),
    }


def _reload_request_tracker_config(_cfg: Dict[str, Any]) -> None:
    apply_request_tracker_config(_load_request_tracker_config())


_apply_request_tracker_config(_load_request_tracker_config())
try:
    from ..tuneables_reload import register_reload as _register_request_tracker_reload

    _register_request_tracker_reload(
        "request_tracker",
        _reload_request_tracker_config,
        label="request_tracker.reload_from",
    )
except Exception:
    pass


@dataclass
class PendingRequest:
    """A user request awaiting resolution."""
    step: Step
    request_text: str
    context: Dict[str, Any]
    created_at: float = field(default_factory=time.time)

    # Track what's happened so far
    actions_taken: List[str] = field(default_factory=list)
    tools_used: List[str] = field(default_factory=list)


class RequestTracker:
    """
    Track user requests through the EIDOS Step lifecycle.

    This bridges the gap between raw user messages and structured
    decision packets that can be analyzed for patterns and distilled
    into reusable intelligence.

    Flow:
    1. on_user_message() - Creates Step envelope with intent/prediction
    2. on_action_taken() - Records decision and tools used
    3. on_outcome() - Completes Step with result/evaluation/lesson

    The completed Steps feed into PatternDistiller for Distillation creation.
    """

    # Intent patterns for hypothesis extraction
    INTENT_PATTERNS = {
        "push": ("persist changes to repository", "User wants code changes persisted to repository"),
        "commit": ("persist changes to repository", "User wants changes committed"),
        "fix": ("resolve issue", "User wants identified issue resolved"),
        "bug": ("resolve issue", "User wants bug fixed"),
        "add": ("create new functionality", "User wants new functionality added"),
        "create": ("create new functionality", "User wants something created"),
        "clean": ("remove unwanted items", "User wants unwanted items eliminated"),
        "remove": ("eliminate items", "User wants items removed"),
        "delete": ("eliminate items", "User wants items deleted"),
        "update": ("modify existing", "User wants existing functionality modified"),
        "change": ("modify existing", "User wants something changed"),
        "refactor": ("improve code structure", "User wants code structure improved"),
        "optimize": ("improve performance", "User wants performance improved"),
        "test": ("verify functionality", "User wants functionality verified"),
        "deploy": ("release to production", "User wants code deployed"),
        "review": ("examine code", "User wants code reviewed"),
        "explain": ("understand code", "User wants explanation"),
        "help": ("get assistance", "User needs assistance"),
        "search": ("find information", "User wants to find something"),
        "find": ("locate items", "User wants to locate something"),
        "constraint": ("respect constraints", "User defined constraints that should shape execution"),
        "non-negotiable": ("respect constraints", "User specified a hard boundary that must be preserved"),
        "must not": ("respect constraints", "User set a negative constraint that should not be violated"),
        "deadline": ("meet deadline", "User expects delivery within a fixed time window"),
        "scope": ("control scope", "User is constraining project scope"),
        "tradeoff": ("evaluate tradeoff", "User wants an explicit tradeoff decision"),
        "risk": ("manage risk", "User expects risk-aware execution"),
        "decision": ("make decision", "User asked for a decision path"),
        "decide": ("make decision", "User asked to decide between options"),
        "choose": ("select option", "User asked to choose between options"),
    }

    def __init__(self, max_pending: int = 50, max_completed: int = 200):
        """
        Initialize the tracker.

        Args:
            max_pending: Maximum pending requests to track
            max_completed: Maximum completed steps to retain
        """
        self.pending: Dict[str, PendingRequest] = {}
        self.completed: List[Step] = []
        self.max_pending = max_pending
        self.max_completed = max_completed

        # Statistics
        self._stats = {
            "total_requests": 0,
            "completed_requests": 0,
            "timed_out_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
        }

    def on_user_message(
        self,
        message: str,
        episode_id: str = "default",
        context: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None
    ) -> Step:
        """
        Wrap user request in EIDOS Step structure.

        This creates the "BEFORE" part of the decision packet:
        - Intent: What we understand the user wants
        - Hypothesis: Testable claim about what will satisfy them
        - Prediction: Expected outcome

        Args:
            message: The raw user message
            episode_id: EIDOS episode this belongs to
            context: Additional context (project, phase, prior actions)

        Returns:
            Step envelope ready to be completed after action
        """
        context = context or {}
        self._stats["total_requests"] += 1

        # Extract structured understanding from message
        intent = self._extract_intent(message)
        hypothesis = self._extract_hypothesis(message)
        prediction = self._generate_prediction(message, context)

        step = Step(
            step_id="",  # Auto-generated in __post_init__
            episode_id=episode_id,
            trace_id=trace_id,
            intent=intent,
            decision="pending",  # Filled after action
            hypothesis=hypothesis,
            alternatives=[],  # Could be filled with other approaches considered
            assumptions=self._extract_assumptions(message, context),
            prediction=prediction,
            stop_condition=self._generate_stop_condition(message),
            confidence_before=0.7,  # Default confidence
            action_type=ActionType.REASONING,
            action_details={
                "request_text": message,
                "context_snapshot": {
                    "project": context.get("project"),
                    "phase": context.get("phase"),
                    "prior_actions": context.get("prior_actions", [])[-5:],
                }
            },
            # Memory binding
            retrieved_memories=[],
            memory_cited=False,
            memory_absent_declared=True if not context.get("relevant_memories") else False,
        )

        # Store as pending
        self.pending[step.step_id] = PendingRequest(
            step=step,
            request_text=message,
            context=context,
        )

        # Prune old pending requests
        self._prune_pending()

        return step

    def on_action_taken(
        self,
        step_id: str,
        decision: str,
        tool_used: str = "",
        alternatives_considered: Optional[List[str]] = None
    ) -> bool:
        """
        Record what action was taken for this request.

        This fills in the "ACTION" part of the decision packet.

        Args:
            step_id: The step ID to update
            decision: Description of what was decided/done
            tool_used: Primary tool used (Bash, Edit, etc.)
            alternatives_considered: Other approaches that were considered

        Returns:
            True if step was found and updated
        """
        if step_id not in self.pending:
            return False

        pending = self.pending[step_id]
        pending.step.decision = decision
        pending.actions_taken.append(decision)

        if tool_used:
            pending.tools_used.append(tool_used)
            pending.step.action_type = self._infer_action_type(tool_used)
            pending.step.action_details["tool_used"] = tool_used

        if alternatives_considered:
            pending.step.alternatives = alternatives_considered

        return True

    def on_outcome(
        self,
        step_id: str,
        result: str,
        success: bool,
        validation_evidence: str = "",
        user_feedback: Optional[str] = None,
        lesson_override: Optional[str] = None
    ) -> Optional[Step]:
        """
        Complete the Step with outcome.

        This fills in the "AFTER" part of the decision packet:
        - Result: What actually happened
        - Evaluation: Did it work?
        - Lesson: What we learned

        Args:
            step_id: The step ID to complete
            result: Description of what happened
            success: Whether the request was fulfilled
            validation_evidence: Concrete evidence (test output, etc.)
            user_feedback: Explicit user feedback if any
            lesson_override: Explicit lesson to record

        Returns:
            Completed Step, or None if not found
        """
        if step_id not in self.pending:
            return None

        pending = self.pending.pop(step_id)
        step = pending.step

        # Fill outcome fields
        step.result = result
        step.evaluation = Evaluation.PASS if success else Evaluation.FAIL
        step.validated = True
        step.validation_method = "user_feedback" if user_feedback else "outcome_observation"
        step.validation_evidence = validation_evidence or result[:200]

        # Calculate surprise
        step.surprise_level = step.calculate_surprise()

        # Confidence update
        if success:
            step.confidence_after = min(0.95, step.confidence_before + 0.1)
        else:
            step.confidence_after = max(0.2, step.confidence_before - 0.2)
        step.confidence_delta = step.confidence_after - step.confidence_before

        # Extract lesson
        step.lesson = lesson_override or self._extract_lesson(
            step, pending.request_text, user_feedback
        )

        # Progress tracking
        step.progress_made = success
        step.evidence_gathered = bool(validation_evidence)

        # Store completed
        self.completed.append(step)
        self._prune_completed()

        # Update stats
        self._stats["completed_requests"] += 1
        if success:
            self._stats["successful_requests"] += 1
        else:
            self._stats["failed_requests"] += 1

        return step

    def timeout_pending(self, max_age_seconds: Optional[float] = None) -> List[Step]:
        """
        Time out old pending requests.

        Returns list of timed-out steps (marked as UNKNOWN evaluation).
        """
        timeout_s = (
            float(max_age_seconds)
            if max_age_seconds is not None
            else float(REQUEST_TRACKER_MAX_AGE_SECONDS)
        )
        now = time.time()
        timed_out = []

        for step_id, pending in list(self.pending.items()):
            if now - pending.created_at > timeout_s:
                step = pending.step
                step.result = "Request timed out - no outcome recorded"
                step.evaluation = Evaluation.UNKNOWN
                step.lesson = "Request was not completed or outcome was not tracked"

                timed_out.append(step)
                del self.pending[step_id]
                self._stats["timed_out_requests"] += 1

        return timed_out

    def get_completed_steps(self, limit: int = 50) -> List[Step]:
        """Get recently completed steps for pattern detection."""
        return self.completed[-limit:]

    def get_successful_steps(self, limit: int = 50) -> List[Step]:
        """Get recently completed successful steps."""
        successful = [s for s in self.completed if s.evaluation == Evaluation.PASS]
        return successful[-limit:]

    def get_failed_steps(self, limit: int = 50) -> List[Step]:
        """Get recently completed failed steps."""
        failed = [s for s in self.completed if s.evaluation == Evaluation.FAIL]
        return failed[-limit:]

    def get_pending_count(self) -> int:
        """Get count of unresolved requests."""
        return len(self.pending)

    def get_stats(self) -> Dict[str, Any]:
        """Get tracker statistics."""
        return {
            **self._stats,
            "pending_count": len(self.pending),
            "completed_retained": len(self.completed),
        }

    # ==================== Intent Extraction ====================

    def _extract_intent(self, message: str) -> str:
        """Extract structured intent from user message."""
        msg_lower = message.lower().strip()

        # Check for known intent patterns
        for keyword, (category, _) in self.INTENT_PATTERNS.items():
            if keyword in msg_lower:
                # Extract the object of the intent
                words = message.split()
                relevant_words = [w for w in words if w.lower() not in
                                  {"please", "can", "you", "the", "a", "an", "to", "i", "want", "lets", "let's"}]

                if relevant_words:
                    return f"Fulfill user request: {category} - {' '.join(relevant_words[:8])}"
                return f"Fulfill user request: {category}"

        # Fallback: Use first meaningful words
        return f"Fulfill user request: {message[:100]}"

    def _extract_hypothesis(self, message: str) -> str:
        """Extract testable hypothesis from user message."""
        msg_lower = message.lower()

        for keyword, (_, hypothesis) in self.INTENT_PATTERNS.items():
            if keyword in msg_lower:
                return hypothesis

        return f"User wants: {message[:50]}"

    def _generate_prediction(self, message: str, context: Dict) -> str:
        """Generate prediction about expected outcome."""
        msg_lower = message.lower()

        # Specific predictions based on intent
        if "push" in msg_lower or "commit" in msg_lower:
            return "Changes will be persisted to remote repository successfully"
        if "fix" in msg_lower or "bug" in msg_lower:
            return "Issue will be resolved and functionality will work correctly"
        if "test" in msg_lower:
            return "Tests will pass and validate the functionality"
        if "deploy" in msg_lower:
            return "Code will be deployed and accessible in target environment"
        if "clean" in msg_lower or "remove" in msg_lower:
            return "Unwanted items will be eliminated without side effects"
        if any(k in msg_lower for k in ("constraint", "non-negotiable", "must not", "scope")):
            return "Execution will respect stated constraints without violating boundaries"
        if any(k in msg_lower for k in ("decision", "decide", "choose", "tradeoff")):
            return "A clear option will be selected with rationale and tradeoffs"
        if "deadline" in msg_lower:
            return "The plan will prioritize fastest safe path to hit deadline"
        if "risk" in msg_lower:
            return "High-risk paths will be identified and mitigated before execution"

        return "User will be satisfied if request is fulfilled correctly"

    def _extract_assumptions(self, message: str, context: Dict) -> List[str]:
        """Extract assumptions that must be true for success."""
        assumptions = []
        msg_lower = message.lower()

        if "push" in msg_lower or "commit" in msg_lower:
            assumptions.append("Changes are staged and ready to commit")
            assumptions.append("Remote repository is accessible")

        if "fix" in msg_lower:
            assumptions.append("Root cause of issue is understood")

        if "test" in msg_lower:
            assumptions.append("Test environment is configured correctly")
        if any(k in msg_lower for k in ("constraint", "non-negotiable", "must not", "scope")):
            assumptions.append("Constraints are explicit and mutually consistent")
        if any(k in msg_lower for k in ("decision", "decide", "choose", "tradeoff")):
            assumptions.append("Selection criteria are clear enough to rank options")
        if "deadline" in msg_lower:
            assumptions.append("Delivery window is feasible for remaining scope")

        if context.get("project"):
            assumptions.append(f"Working in correct project: {context['project']}")

        if not assumptions:
            assumptions.append("User request is clear and achievable")

        return assumptions

    def _generate_stop_condition(self, message: str) -> str:
        """Generate stop condition - when to abort approach."""
        msg_lower = message.lower()

        if "push" in msg_lower or "commit" in msg_lower:
            return "If authentication fails or remote is unreachable, stop and report"
        if "fix" in msg_lower:
            return "If two different fixes fail, stop and diagnose root cause"
        if "test" in msg_lower:
            return "If tests fail for reasons unrelated to changes, investigate environment"

        return "If approach fails twice, stop and reconsider strategy"

    def _infer_action_type(self, tool: str) -> ActionType:
        """Infer action type from tool used."""
        tool_lower = tool.lower()

        if tool_lower in {"bash", "edit", "write", "notebookedit"}:
            return ActionType.TOOL_CALL
        if tool_lower in {"askuserquestion"}:
            return ActionType.QUESTION
        if tool_lower in {"taskoutput", "read"}:
            return ActionType.WAIT

        return ActionType.REASONING

    def _extract_lesson(
        self,
        step: Step,
        original_request: str,
        user_feedback: Optional[str]
    ) -> str:
        """Extract lesson from completed step."""
        intent_short = step.intent.replace("Fulfill user request: ", "")[:30]
        decision_short = step.decision[:50] if step.decision != "pending" else "unknown approach"

        if step.evaluation == Evaluation.PASS:
            if user_feedback:
                return f"Request '{intent_short}' satisfied. User feedback: {user_feedback[:50]}"
            return f"Request '{intent_short}' resolved by: {decision_short}"

        elif step.evaluation == Evaluation.FAIL:
            return f"Request '{intent_short}' failed with approach: {decision_short}. Need different strategy."

        else:
            return f"Request '{intent_short}' outcome unclear. Consider explicit validation."

    # ==================== Maintenance ====================

    def _prune_pending(self):
        """Remove oldest pending requests if over limit."""
        if len(self.pending) <= self.max_pending:
            return

        # Sort by creation time and remove oldest
        sorted_pending = sorted(
            self.pending.items(),
            key=lambda x: x[1].created_at
        )

        to_remove = len(self.pending) - self.max_pending
        for step_id, _ in sorted_pending[:to_remove]:
            del self.pending[step_id]
            self._stats["timed_out_requests"] += 1

    def _prune_completed(self):
        """Keep only recent completed steps."""
        if len(self.completed) > self.max_completed:
            self.completed = self.completed[-self.max_completed:]


# Singleton instance
_tracker: Optional[RequestTracker] = None


def get_request_tracker() -> RequestTracker:
    """Get the global request tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = RequestTracker(
            max_pending=REQUEST_TRACKER_MAX_PENDING,
            max_completed=REQUEST_TRACKER_MAX_COMPLETED,
        )
    return _tracker
