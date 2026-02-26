"""
EIDOS Core Models: The Intelligence Primitives

These are the objects that make learning mandatory and measurable:
- Episode: Bounded learning unit with goals, constraints, budgets
- Step: Decision packet with prediction → outcome → evaluation
- Distillation: Extracted rules from experience
- Policy: Operating constraints
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class Phase(Enum):
    """
    Episode phases - transitions are rule-driven, not LLM-decided.

    The LLM cannot "decide" to skip states. The control plane enforces.

    Allowed transitions:
    - EXPLORE → PLAN
    - PLAN → EXECUTE
    - EXECUTE → VALIDATE
    - VALIDATE → (EXECUTE | CONSOLIDATE | DIAGNOSE)
    - DIAGNOSE → (SIMPLIFY | PLAN | ESCALATE)
    - SIMPLIFY → (DIAGNOSE | PLAN | ESCALATE)
    - Any → HALT (budget or safety)
    - Any → ESCALATE (missing info / blocked)
    """
    EXPLORE = "explore"         # Gather context, clarify, retrieve memory
    PLAN = "plan"               # Generate hypotheses/tests (bounded)
    EXECUTE = "execute"         # One action per step + prediction
    VALIDATE = "validate"       # Prove outcome, record evidence
    CONSOLIDATE = "consolidate" # Distill learnings into reusable rules
    DIAGNOSE = "diagnose"       # Debugging mode, evidence-only
    SIMPLIFY = "simplify"       # Reduce scope / minimal reproduction
    ESCALATE = "escalate"       # Ask user / stop and request info
    HALT = "halt"               # Budget exceeded or unsafe; produce report


# Valid phase transitions (control plane enforces these)
VALID_TRANSITIONS = {
    Phase.EXPLORE: [Phase.PLAN, Phase.ESCALATE, Phase.HALT],
    Phase.PLAN: [Phase.EXECUTE, Phase.ESCALATE, Phase.HALT],
    Phase.EXECUTE: [Phase.VALIDATE, Phase.ESCALATE, Phase.HALT],
    Phase.VALIDATE: [Phase.EXECUTE, Phase.CONSOLIDATE, Phase.DIAGNOSE, Phase.ESCALATE, Phase.HALT],
    Phase.CONSOLIDATE: [Phase.EXPLORE, Phase.HALT],  # Start new cycle or end
    Phase.DIAGNOSE: [Phase.SIMPLIFY, Phase.PLAN, Phase.ESCALATE, Phase.HALT],
    Phase.SIMPLIFY: [Phase.DIAGNOSE, Phase.PLAN, Phase.ESCALATE, Phase.HALT],
    Phase.ESCALATE: [Phase.HALT],  # Can only halt after escalation
    Phase.HALT: [],  # Terminal state
}


class Outcome(Enum):
    """Episode outcomes."""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    ESCALATED = "escalated"
    IN_PROGRESS = "in_progress"


class Evaluation(Enum):
    """Step evaluation results."""
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class DistillationType(Enum):
    """Types of distilled knowledge."""
    HEURISTIC = "heuristic"       # "If X, then Y"
    SHARP_EDGE = "sharp_edge"     # Gotcha / pitfall
    ANTI_PATTERN = "anti_pattern" # "Never do X because..."
    PLAYBOOK = "playbook"         # Step-by-step procedure
    POLICY = "policy"             # Operating constraint


class ActionType(Enum):
    """Types of actions a step can take."""
    TOOL_CALL = "tool_call"
    REASONING = "reasoning"
    QUESTION = "question"
    WAIT = "wait"


# Runtime-tuneable threshold for confidence stagnation detection.
CONFIDENCE_STAGNATION_THRESHOLD = 0.05


@dataclass
class Budget:
    """
    Resource constraints for an episode.

    Budget exhaustion triggers:
    - auto transition → HALT
    - produce "Stuck Report" + "Next best experiment"
    - create at least one distillation (anti-pattern/sharp edge)
    """
    max_steps: int = 25
    max_time_seconds: int = 720  # 12 minutes
    max_retries_per_error: int = 2  # After 2 failures, stop modifying
    max_file_touches: int = 3  # Max times to modify same file per episode (raised from 2)
    no_evidence_limit: int = 5  # Force DIAGNOSE after N steps without evidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_steps": self.max_steps,
            "max_time_seconds": self.max_time_seconds,
            "max_retries_per_error": self.max_retries_per_error,
            "max_file_touches": self.max_file_touches,
            "no_evidence_limit": self.no_evidence_limit,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Budget":
        return cls(
            max_steps=data.get("max_steps", 25),
            max_time_seconds=data.get("max_time_seconds", 720),
            max_retries_per_error=data.get("max_retries_per_error", 2),
            max_file_touches=data.get("max_file_touches", 3),
            no_evidence_limit=data.get("no_evidence_limit", 5),
        )


def _merge_eidos_with_values(eidos_cfg: Dict[str, Any], values_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Merge eidos config with shared keys from values section."""
    cfg = dict(eidos_cfg) if isinstance(eidos_cfg, dict) else {}
    if isinstance(values_cfg, dict):
        for key in ("max_steps", "max_retries_per_error", "max_file_touches"):
            if key not in cfg and key in values_cfg:
                cfg[key] = values_cfg[key]
        if "no_evidence_limit" not in cfg and "no_evidence_steps" in values_cfg:
            cfg["no_evidence_limit"] = values_cfg["no_evidence_steps"]
    return cfg


def _load_eidos_config() -> Dict[str, Any]:
    """Load EIDOS budget tuneables via config_authority resolve_section.

    Checks the "eidos" section first, then falls back to "values" section
    for shared keys (max_steps, max_retries_per_error, max_file_touches,
    no_evidence_steps → no_evidence_limit).
    """
    try:
        from ..config_authority import resolve_section
        tuneables = Path.home() / ".spark" / "tuneables.json"
        eidos_cfg = resolve_section("eidos", runtime_path=tuneables).data
        values_cfg = resolve_section("values", runtime_path=tuneables).data
        return _merge_eidos_with_values(eidos_cfg, values_cfg)
    except Exception:
        return {}


_EIDOS_CFG = _load_eidos_config()


def reload_eidos_from(cfg: Dict[str, Any]) -> None:
    """Hot-reload EIDOS budget tuneables from coordinator-supplied dict.

    Merges with values section via resolve_section so that shared keys
    like max_steps inherited from values are not lost after reload.
    """
    global _EIDOS_CFG
    if not isinstance(cfg, dict):
        return
    try:
        from ..config_authority import resolve_section
        tuneables = Path.home() / ".spark" / "tuneables.json"
        values_cfg = resolve_section("values", runtime_path=tuneables).data
    except Exception:
        values_cfg = {}
    _EIDOS_CFG = _merge_eidos_with_values(cfg, values_cfg)


try:
    from ..tuneables_reload import register_reload as _eidos_register
    _eidos_register("eidos", reload_eidos_from, label="eidos.models.reload_from")
except ImportError:
    pass


def default_budget() -> "Budget":
    """Create a Budget with tuneable-aware defaults.

    Reads overrides from ~/.spark/tuneables.json → "eidos" section.
    Falls back to hard-coded defaults for any missing key.
    """
    return Budget(
        max_steps=int(_EIDOS_CFG.get("max_steps", 25)),
        max_time_seconds=int(_EIDOS_CFG.get("max_time_seconds", 720)),
        max_retries_per_error=int(_EIDOS_CFG.get("max_retries_per_error", 2)),
        max_file_touches=int(_EIDOS_CFG.get("max_file_touches", 3)),
        no_evidence_limit=int(_EIDOS_CFG.get("no_evidence_limit", 5)),
    )


@dataclass
class Episode:
    """
    A bounded learning unit.

    Every episode has:
    - A clear goal
    - Success criteria
    - Budget constraints
    - Explicit phase tracking
    """
    episode_id: str
    goal: str
    success_criteria: str
    constraints: List[str] = field(default_factory=list)
    budget: Budget = field(default_factory=default_budget)
    phase: Phase = Phase.EXPLORE
    outcome: Outcome = Outcome.IN_PROGRESS
    final_evaluation: str = ""
    start_ts: float = field(default_factory=time.time)
    end_ts: Optional[float] = None

    # Tracking
    step_count: int = 0
    error_counts: Dict[str, int] = field(default_factory=dict)  # error_signature -> count
    file_touch_counts: Dict[str, int] = field(default_factory=dict)  # file_path -> touch count
    no_evidence_streak: int = 0  # Steps without new evidence
    confidence_history: List[float] = field(default_factory=list)  # Track confidence over time
    stuck_count: int = 0  # Times we've entered DIAGNOSE/SIMPLIFY
    escape_protocol_triggered: bool = False

    def __post_init__(self):
        if not self.episode_id:
            self.episode_id = self._generate_id()

    def _generate_id(self) -> str:
        key = f"{self.goal[:50]}:{self.start_ts}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def is_budget_exceeded(self) -> bool:
        """Check if any budget limit is exceeded."""
        if self.step_count >= self.budget.max_steps:
            return True
        elapsed = time.time() - self.start_ts
        if elapsed >= self.budget.max_time_seconds:
            return True
        return False

    def is_error_limit_exceeded(self, error_signature: str) -> bool:
        """Check if we've hit the retry limit for an error."""
        count = self.error_counts.get(error_signature, 0)
        return count >= self.budget.max_retries_per_error

    def record_error(self, error_signature: str):
        """Record an error occurrence."""
        self.error_counts[error_signature] = self.error_counts.get(error_signature, 0) + 1

    def record_file_touch(self, file_path: str):
        """Record that a file was modified."""
        self.file_touch_counts[file_path] = self.file_touch_counts.get(file_path, 0) + 1

    def is_file_frozen(self, file_path: str) -> bool:
        """Check if file has been touched too many times."""
        return self.file_touch_counts.get(file_path, 0) >= self.budget.max_file_touches

    def get_frozen_files(self) -> List[str]:
        """Get list of files that can no longer be modified."""
        return [f for f, c in self.file_touch_counts.items() if c >= self.budget.max_file_touches]

    def record_evidence(self, has_evidence: bool):
        """Track evidence streak."""
        if has_evidence:
            self.no_evidence_streak = 0
        else:
            self.no_evidence_streak += 1

    def is_no_evidence_limit_exceeded(self) -> bool:
        """Check if we've gone too long without new evidence."""
        return self.no_evidence_streak >= self.budget.no_evidence_limit

    def record_confidence(self, confidence: float):
        """Track confidence over time for stagnation detection."""
        self.confidence_history.append(confidence)
        # Keep only last 10
        if len(self.confidence_history) > 10:
            self.confidence_history = self.confidence_history[-10:]

    def is_confidence_stagnant(self, threshold: Optional[float] = None, steps: int = 3) -> bool:
        """Check if confidence hasn't improved significantly."""
        if len(self.confidence_history) < steps:
            return False
        recent = self.confidence_history[-steps:]
        effective_threshold = (
            float(threshold)
            if threshold is not None
            else float(CONFIDENCE_STAGNATION_THRESHOLD)
        )
        return max(recent) - min(recent) < effective_threshold

    def budget_percentage_used(self) -> float:
        """Get percentage of budget used."""
        return self.step_count / self.budget.max_steps

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "goal": self.goal,
            "success_criteria": self.success_criteria,
            "constraints": self.constraints,
            "budget": self.budget.to_dict(),
            "phase": self.phase.value,
            "outcome": self.outcome.value,
            "final_evaluation": self.final_evaluation,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "step_count": self.step_count,
            "error_counts": self.error_counts,
            "file_touch_counts": self.file_touch_counts,
            "no_evidence_streak": self.no_evidence_streak,
            "confidence_history": self.confidence_history,
            "stuck_count": self.stuck_count,
            "escape_protocol_triggered": self.escape_protocol_triggered,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Episode":
        return cls(
            episode_id=data["episode_id"],
            goal=data["goal"],
            success_criteria=data.get("success_criteria", ""),
            constraints=data.get("constraints", []),
            budget=Budget.from_dict(data.get("budget", {})),
            phase=Phase(data.get("phase", "explore")),
            outcome=Outcome(data.get("outcome", "in_progress")),
            final_evaluation=data.get("final_evaluation", ""),
            start_ts=data.get("start_ts", time.time()),
            end_ts=data.get("end_ts"),
            step_count=data.get("step_count", 0),
            error_counts=data.get("error_counts", {}),
            file_touch_counts=data.get("file_touch_counts", {}),
            no_evidence_streak=data.get("no_evidence_streak", 0),
            confidence_history=data.get("confidence_history", []),
            stuck_count=data.get("stuck_count", 0),
            escape_protocol_triggered=data.get("escape_protocol_triggered", False),
        )


@dataclass
class Step:
    """
    The atomic intelligence unit - a decision packet (Step Envelope).

    This is the core substrate for learning because it captures:
    - What was decided (and what wasn't)
    - Why it was decided
    - What was predicted
    - What actually happened
    - What we learned

    THE STEP ENVELOPE (non-negotiable contract):

    BEFORE ACTION (required):
    - intent, hypothesis, prediction, stop_condition
    - budget_snapshot, memory_citations

    AFTER ACTION (required):
    - result, validation_evidence, evaluation
    - lesson, confidence_delta

    HARD GATE: If validation is missing, step marked INVALID
    and cannot produce distillations.
    """
    step_id: str
    episode_id: str

    # ===== BEFORE ACTION (mandatory) =====
    intent: str = ""                      # What I'm trying to accomplish
    decision: str = ""                    # What I chose to do
    trace_id: Optional[str] = None        # Optional trace ID for debugging
    hypothesis: str = ""                  # Falsifiable claim being tested
    alternatives: List[str] = field(default_factory=list)  # What I considered but didn't do
    assumptions: List[str] = field(default_factory=list)   # What must be true for this to work
    prediction: str = ""                  # What I expect to happen
    stop_condition: str = ""              # "If X, change approach" - when to abort
    confidence_before: float = 0.5        # 0-1, how sure I am
    budget_snapshot: Dict[str, Any] = field(default_factory=dict)  # Budget state at step start

    # ===== THE ACTION =====
    action_type: ActionType = ActionType.REASONING
    action_details: Dict[str, Any] = field(default_factory=dict)  # Minimal provenance

    # ===== AFTER ACTION (mandatory) =====
    result: str = ""                      # What actually happened
    validation_evidence: str = ""         # Concrete evidence (test output, metric, file hash)
    evaluation: Evaluation = Evaluation.UNKNOWN
    surprise_level: float = 0.0           # 0-1, how different from prediction
    lesson: str = ""                      # 1-3 bullets, what we learned
    confidence_after: float = 0.5         # Updated confidence
    confidence_delta: float = 0.0         # Change in confidence

    # ===== MEMORY BINDING (mandatory) =====
    retrieved_memories: List[str] = field(default_factory=list)  # Memory IDs retrieved
    memory_cited: bool = False            # Did we actually use retrieved memory?
    memory_useful: Optional[bool] = None  # Was the memory helpful?
    memory_absent_declared: bool = False  # Explicitly declared "none found"

    # ===== VALIDATION (mandatory) =====
    validated: bool = False               # Did we check the result?
    validation_method: str = ""           # How we validated
    is_valid: bool = True                 # False if missing required fields

    # ===== PROGRESS TRACKING =====
    evidence_gathered: bool = False       # Did this step produce new evidence?
    progress_made: bool = False           # Did this step advance toward goal?

    # Metadata
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.step_id:
            self.step_id = self._generate_id()

    def _generate_id(self) -> str:
        key = f"{self.episode_id}:{self.intent[:30]}:{self.created_at}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def is_valid_before_action(self) -> tuple:
        """Check if step has required fields before action."""
        missing = []
        if not self.intent:
            missing.append("intent")
        if not self.decision:
            missing.append("decision")
        if not self.prediction:
            missing.append("prediction")
        return (len(missing) == 0, missing)

    def is_valid_after_action(self) -> tuple:
        """Check if step has required fields after action."""
        missing = []
        if not self.result:
            missing.append("result")
        if self.evaluation == Evaluation.UNKNOWN:
            missing.append("evaluation")
        if not self.validated and not self.validation_method:
            missing.append("validation")
        return (len(missing) == 0, missing)

    def calculate_surprise(self) -> float:
        """Calculate how surprising the result was vs prediction."""
        if not self.prediction or not self.result:
            return 0.0

        # Simple heuristic: if evaluation doesn't match expected, high surprise
        if self.evaluation == Evaluation.FAIL:
            return 0.8  # Failure is usually surprising
        if self.evaluation == Evaluation.PARTIAL:
            return 0.5

        # Check for keyword mismatches
        pred_words = set(self.prediction.lower().split())
        result_words = set(self.result.lower().split())
        if pred_words and result_words:
            overlap = len(pred_words & result_words) / len(pred_words | result_words)
            return 1.0 - overlap

        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "episode_id": self.episode_id,
            "trace_id": self.trace_id,
            "intent": self.intent,
            "decision": self.decision,
            "hypothesis": self.hypothesis,
            "alternatives": self.alternatives,
            "assumptions": self.assumptions,
            "prediction": self.prediction,
            "stop_condition": self.stop_condition,
            "confidence_before": self.confidence_before,
            "budget_snapshot": self.budget_snapshot,
            "action_type": self.action_type.value,
            "action_details": self.action_details,
            "result": self.result,
            "validation_evidence": self.validation_evidence,
            "evaluation": self.evaluation.value,
            "surprise_level": self.surprise_level,
            "lesson": self.lesson,
            "confidence_after": self.confidence_after,
            "confidence_delta": self.confidence_delta,
            "retrieved_memories": self.retrieved_memories,
            "memory_cited": self.memory_cited,
            "memory_useful": self.memory_useful,
            "memory_absent_declared": self.memory_absent_declared,
            "validated": self.validated,
            "validation_method": self.validation_method,
            "is_valid": self.is_valid,
            "evidence_gathered": self.evidence_gathered,
            "progress_made": self.progress_made,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Step":
        return cls(
            step_id=data["step_id"],
            episode_id=data["episode_id"],
            trace_id=data.get("trace_id"),
            intent=data.get("intent", ""),
            decision=data.get("decision", ""),
            hypothesis=data.get("hypothesis", ""),
            alternatives=data.get("alternatives", []),
            assumptions=data.get("assumptions", []),
            prediction=data.get("prediction", ""),
            stop_condition=data.get("stop_condition", ""),
            confidence_before=data.get("confidence_before", 0.5),
            budget_snapshot=data.get("budget_snapshot", {}),
            action_type=ActionType(data.get("action_type", "reasoning")),
            action_details=data.get("action_details", {}),
            result=data.get("result", ""),
            validation_evidence=data.get("validation_evidence", ""),
            evaluation=Evaluation(data.get("evaluation", "unknown")),
            surprise_level=data.get("surprise_level", 0.0),
            lesson=data.get("lesson", ""),
            confidence_after=data.get("confidence_after", 0.5),
            confidence_delta=data.get("confidence_delta", 0.0),
            retrieved_memories=data.get("retrieved_memories", []),
            memory_cited=data.get("memory_cited", False),
            memory_useful=data.get("memory_useful"),
            memory_absent_declared=data.get("memory_absent_declared", False),
            validated=data.get("validated", False),
            validation_method=data.get("validation_method", ""),
            is_valid=data.get("is_valid", True),
            evidence_gathered=data.get("evidence_gathered", False),
            progress_made=data.get("progress_made", False),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class Distillation:
    """
    Where intelligence lives - extracted rules from experience.

    Types:
    - HEURISTIC: "If X, then Y"
    - SHARP_EDGE: Gotcha / pitfall
    - ANTI_PATTERN: "Never do X because..."
    - PLAYBOOK: Step-by-step procedure
    - POLICY: Operating constraint
    """
    distillation_id: str
    type: DistillationType
    statement: str

    # Applicability
    domains: List[str] = field(default_factory=list)    # Where this applies
    triggers: List[str] = field(default_factory=list)   # When to retrieve this
    anti_triggers: List[str] = field(default_factory=list)  # When NOT to apply

    # Evidence
    source_steps: List[str] = field(default_factory=list)  # Step IDs that generated this
    validation_count: int = 0
    contradiction_count: int = 0
    confidence: float = 0.5

    # Usage tracking
    times_retrieved: int = 0
    times_used: int = 0      # Actually influenced decision
    times_helped: int = 0    # Led to success

    # Metadata
    created_at: float = field(default_factory=time.time)
    revalidate_by: Optional[float] = None
    refined_statement: str = ""
    advisory_quality: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.distillation_id:
            self.distillation_id = self._generate_id()

    def _generate_id(self) -> str:
        key = f"{self.type.value}:{self.statement[:50]}:{self.created_at}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    @property
    def effectiveness(self) -> float:
        """How effective is this distillation when used?"""
        if self.times_used == 0:
            return 0.5  # Unknown
        return self.times_helped / self.times_used

    @property
    def reliability(self) -> float:
        """How reliable is this distillation?"""
        total = self.validation_count + self.contradiction_count
        if total == 0:
            return self.confidence
        return self.validation_count / total

    def record_retrieval(self):
        """Record that this was retrieved."""
        self.times_retrieved += 1

    def record_usage(self, helped: bool):
        """Record that this was used and whether it helped."""
        self.times_used += 1
        if helped:
            self.times_helped += 1
            self.validation_count += 1
        else:
            self.contradiction_count += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "distillation_id": self.distillation_id,
            "type": self.type.value,
            "statement": self.statement,
            "domains": self.domains,
            "triggers": self.triggers,
            "anti_triggers": self.anti_triggers,
            "source_steps": self.source_steps,
            "validation_count": self.validation_count,
            "contradiction_count": self.contradiction_count,
            "confidence": self.confidence,
            "times_retrieved": self.times_retrieved,
            "times_used": self.times_used,
            "times_helped": self.times_helped,
            "created_at": self.created_at,
            "revalidate_by": self.revalidate_by,
            "refined_statement": self.refined_statement,
            "advisory_quality": self.advisory_quality,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Distillation":
        return cls(
            distillation_id=data["distillation_id"],
            type=DistillationType(data["type"]),
            statement=data["statement"],
            domains=data.get("domains", []),
            triggers=data.get("triggers", []),
            anti_triggers=data.get("anti_triggers", []),
            source_steps=data.get("source_steps", []),
            validation_count=data.get("validation_count", 0),
            contradiction_count=data.get("contradiction_count", 0),
            confidence=data.get("confidence", 0.5),
            times_retrieved=data.get("times_retrieved", 0),
            times_used=data.get("times_used", 0),
            times_helped=data.get("times_helped", 0),
            created_at=data.get("created_at", time.time()),
            revalidate_by=data.get("revalidate_by"),
            refined_statement=data.get("refined_statement", ""),
            advisory_quality=data.get("advisory_quality", {}),
        )


@dataclass
class Policy:
    """
    Operating constraints - what we must respect.

    Sources:
    - USER: Explicitly stated by user
    - DISTILLED: Extracted from experience
    - INFERRED: Detected from patterns
    """
    policy_id: str
    statement: str
    scope: str = "GLOBAL"  # GLOBAL, PROJECT, SESSION
    priority: int = 50     # Higher = more important
    source: str = "INFERRED"
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.policy_id:
            self.policy_id = self._generate_id()

    def _generate_id(self) -> str:
        key = f"{self.scope}:{self.statement[:50]}:{self.created_at}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "statement": self.statement,
            "scope": self.scope,
            "priority": self.priority,
            "source": self.source,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Policy":
        return cls(
            policy_id=data["policy_id"],
            statement=data["statement"],
            scope=data.get("scope", "GLOBAL"),
            priority=data.get("priority", 50),
            source=data.get("source", "INFERRED"),
            created_at=data.get("created_at", time.time()),
        )
