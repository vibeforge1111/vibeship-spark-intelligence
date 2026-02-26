"""
Hypothesis Tracker: Makes predictions and validates them over time.

The Problem:
- We learn from outcomes but don't make explicit predictions
- No way to know if our "learnings" actually help
- Can't distinguish lucky guesses from true understanding

The Solution:
- Generate hypotheses from patterns (2+ similar events)
- Make explicit predictions
- Track prediction outcomes
- Promote validated hypotheses to beliefs
- Demote invalidated hypotheses

Hypothesis Lifecycle:
1. EMERGING: First observation, not yet a hypothesis
2. HYPOTHESIS: Pattern noticed, prediction generated
3. TESTING: Actively being validated
4. VALIDATED: Predictions consistently correct (>70%)
5. INVALIDATED: Predictions consistently wrong (<30%)
6. BELIEF: Promoted to cognitive insight (validated)
"""

import json
import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class HypothesisState(Enum):
    EMERGING = "emerging"       # First observation
    HYPOTHESIS = "hypothesis"   # Pattern noticed
    TESTING = "testing"         # Being validated
    VALIDATED = "validated"     # Consistently correct
    INVALIDATED = "invalidated" # Consistently wrong
    BELIEF = "belief"           # Promoted to insight


@dataclass
class Prediction:
    """A specific prediction made from a hypothesis."""
    prediction_text: str
    context: str
    made_at: str = field(default_factory=lambda: datetime.now().isoformat())
    outcome: Optional[bool] = None  # True = correct, False = wrong, None = unknown
    outcome_recorded_at: Optional[str] = None
    outcome_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prediction_text": self.prediction_text,
            "context": self.context,
            "made_at": self.made_at,
            "outcome": self.outcome,
            "outcome_recorded_at": self.outcome_recorded_at,
            "outcome_notes": self.outcome_notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Prediction":
        return cls(
            prediction_text=data["prediction_text"],
            context=data.get("context", ""),
            made_at=data.get("made_at", datetime.now().isoformat()),
            outcome=data.get("outcome"),
            outcome_recorded_at=data.get("outcome_recorded_at"),
            outcome_notes=data.get("outcome_notes", ""),
        )


@dataclass
class Hypothesis:
    """A hypothesis about how things work."""
    statement: str              # The hypothesis statement
    evidence: List[str]         # Supporting observations
    counter_evidence: List[str] # Contradicting observations
    predictions: List[Prediction] = field(default_factory=list)
    state: HypothesisState = HypothesisState.EMERGING
    confidence: float = 0.5     # 0-1, how confident we are
    domain: str = ""            # Domain this applies to
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    promoted_to_insight: Optional[str] = None  # Insight key if promoted

    @property
    def hypothesis_id(self) -> str:
        """Generate unique ID for this hypothesis."""
        key = f"{self.statement[:50]}:{self.domain}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    @property
    def accuracy(self) -> float:
        """Calculate prediction accuracy."""
        outcomes = [p.outcome for p in self.predictions if p.outcome is not None]
        if not outcomes:
            return 0.5  # Unknown
        return sum(outcomes) / len(outcomes)

    @property
    def sample_size(self) -> int:
        """Number of predictions with outcomes."""
        return sum(1 for p in self.predictions if p.outcome is not None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "evidence": self.evidence,
            "counter_evidence": self.counter_evidence,
            "predictions": [p.to_dict() for p in self.predictions],
            "state": self.state.value,
            "confidence": self.confidence,
            "domain": self.domain,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "promoted_to_insight": self.promoted_to_insight,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Hypothesis":
        return cls(
            statement=data["statement"],
            evidence=data.get("evidence", []),
            counter_evidence=data.get("counter_evidence", []),
            predictions=[Prediction.from_dict(p) for p in data.get("predictions", [])],
            state=HypothesisState(data.get("state", "emerging")),
            confidence=data.get("confidence", 0.5),
            domain=data.get("domain", ""),
            created_at=data.get("created_at", datetime.now().isoformat()),
            last_updated=data.get("last_updated", datetime.now().isoformat()),
            promoted_to_insight=data.get("promoted_to_insight"),
        )


class HypothesisTracker:
    """
    Tracks hypotheses and their validation over time.

    The goal is to turn observations into testable predictions,
    then validate or invalidate them based on outcomes.
    """

    HYPOTHESES_FILE = Path.home() / ".spark" / "hypotheses.json"

    def __init__(self):
        self.hypotheses: Dict[str, Hypothesis] = {}  # id -> hypothesis
        self._observation_buffer: Dict[str, List[str]] = {}  # pattern -> observations
        self._load_hypotheses()

    def _load_hypotheses(self):
        """Load existing hypotheses."""
        if self.HYPOTHESES_FILE.exists():
            try:
                data = json.loads(self.HYPOTHESES_FILE.read_text(encoding="utf-8"))
                for h_data in data.get("hypotheses", []):
                    h = Hypothesis.from_dict(h_data)
                    self.hypotheses[h.hypothesis_id] = h
                self._observation_buffer = data.get("observation_buffer", {})
            except Exception:
                pass

    def _save_hypotheses(self):
        """Save hypotheses to disk (atomic write to avoid partial-JSON on crash)."""
        self.HYPOTHESES_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "hypotheses": [h.to_dict() for h in self.hypotheses.values()],
            "observation_buffer": self._observation_buffer,
        }
        fd, tmp_path = tempfile.mkstemp(dir=self.HYPOTHESES_FILE.parent, suffix=".tmp")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, self.HYPOTHESES_FILE)

    def _extract_pattern(self, observation: str) -> str:
        """Extract a normalizable pattern from an observation."""
        import re
        # Remove specifics, keep structure
        pattern = observation.lower()
        pattern = re.sub(r"\d+", "N", pattern)  # Numbers → N
        pattern = re.sub(r"\"[^\"]+\"", "X", pattern)  # Quoted strings → X
        pattern = re.sub(r"'[^']+'", "X", pattern)
        pattern = re.sub(r"\s+", " ", pattern).strip()
        # Take first 50 chars as pattern key
        return pattern[:50]

    def observe(self, observation: str, domain: str = "") -> Optional[Hypothesis]:
        """
        Record an observation and potentially generate a hypothesis.

        If we've seen similar observations 2+ times, generate a hypothesis.
        """
        pattern = self._extract_pattern(observation)

        # Add to observation buffer
        if pattern not in self._observation_buffer:
            self._observation_buffer[pattern] = []
        self._observation_buffer[pattern].append(observation)

        # Trim buffer
        if len(self._observation_buffer[pattern]) > 10:
            self._observation_buffer[pattern] = self._observation_buffer[pattern][-10:]

        # Check if we have enough observations to form a hypothesis
        observations = self._observation_buffer[pattern]
        if len(observations) >= 2:
            # Generate hypothesis
            statement = self._generate_hypothesis_statement(observations)
            hypothesis = Hypothesis(
                statement=statement,
                evidence=observations[:5],
                counter_evidence=[],
                state=HypothesisState.HYPOTHESIS,
                confidence=0.5 + (0.1 * min(len(observations), 5)),  # More observations = higher confidence
                domain=domain,
            )

            # Check if we already have this hypothesis
            if hypothesis.hypothesis_id not in self.hypotheses:
                self.hypotheses[hypothesis.hypothesis_id] = hypothesis
                self._save_hypotheses()
                return hypothesis
            else:
                # Update existing
                existing = self.hypotheses[hypothesis.hypothesis_id]
                if observation not in existing.evidence:
                    existing.evidence.append(observation)
                    existing.evidence = existing.evidence[-10:]
                    existing.confidence = min(0.9, existing.confidence + 0.05)
                    existing.last_updated = datetime.now().isoformat()
                    self._save_hypotheses()
                return existing

        self._save_hypotheses()
        return None

    def _generate_hypothesis_statement(self, observations: List[str]) -> str:
        """Generate a hypothesis statement from observations."""
        # Find common words/patterns
        if not observations:
            return "Unknown pattern"

        # Use first observation as base
        first = observations[0]

        # Check for common patterns
        if "prefer" in first.lower():
            return f"User consistently prefers patterns similar to: {first[:60]}"
        elif "fail" in first.lower() or "error" in first.lower():
            return f"This type of situation tends to cause issues: {first[:60]}"
        elif "work" in first.lower() or "success" in first.lower():
            return f"This approach tends to work: {first[:60]}"
        else:
            return f"Repeated pattern observed: {first[:60]}"

    def make_prediction(self, hypothesis_id: str, prediction_text: str, context: str = "") -> Optional[Prediction]:
        """
        Make a prediction based on a hypothesis.

        This is how we test if our hypotheses are actually useful.
        """
        if hypothesis_id not in self.hypotheses:
            return None

        hypothesis = self.hypotheses[hypothesis_id]
        prediction = Prediction(
            prediction_text=prediction_text,
            context=context,
        )

        hypothesis.predictions.append(prediction)
        hypothesis.state = HypothesisState.TESTING
        hypothesis.last_updated = datetime.now().isoformat()
        self._save_hypotheses()

        return prediction

    def record_outcome(self, hypothesis_id: str, prediction_index: int, correct: bool, notes: str = ""):
        """
        Record the outcome of a prediction.

        This is the validation step that makes the system learn.
        """
        if hypothesis_id not in self.hypotheses:
            return

        hypothesis = self.hypotheses[hypothesis_id]
        if prediction_index < 0 or prediction_index >= len(hypothesis.predictions):
            return

        prediction = hypothesis.predictions[prediction_index]
        prediction.outcome = correct
        prediction.outcome_recorded_at = datetime.now().isoformat()
        prediction.outcome_notes = notes

        # Update hypothesis state based on accuracy
        self._update_hypothesis_state(hypothesis)
        self._save_hypotheses()

    def _update_hypothesis_state(self, hypothesis: Hypothesis):
        """Update hypothesis state based on prediction outcomes."""
        if hypothesis.sample_size < 3:
            return  # Need at least 3 outcomes

        accuracy = hypothesis.accuracy

        if accuracy >= 0.7:
            hypothesis.state = HypothesisState.VALIDATED
            hypothesis.confidence = accuracy

            # Promote to belief if highly validated
            if accuracy >= 0.8 and hypothesis.sample_size >= 5:
                self._promote_to_belief(hypothesis)

        elif accuracy <= 0.3:
            hypothesis.state = HypothesisState.INVALIDATED
            hypothesis.confidence = accuracy

        else:
            hypothesis.state = HypothesisState.TESTING
            hypothesis.confidence = accuracy

        hypothesis.last_updated = datetime.now().isoformat()

    def _promote_to_belief(self, hypothesis: Hypothesis):
        """Promote a validated hypothesis to a cognitive insight."""
        if hypothesis.promoted_to_insight:
            return  # Already promoted

        try:
            from .cognitive_learner import CognitiveCategory
            from .validate_and_store import validate_and_store_insight

            stored = validate_and_store_insight(
                text=hypothesis.statement,
                category=CognitiveCategory.REASONING,
                context=f"Validated hypothesis ({hypothesis.accuracy:.0%} accuracy over {hypothesis.sample_size} predictions)",
                confidence=hypothesis.accuracy,
                source="hypothesis_tracker",
            )

            hypothesis.state = HypothesisState.BELIEF
            hypothesis.promoted_to_insight = f"reasoning:{hypothesis.statement[:40]}"
        except Exception:
            pass

    def add_counter_evidence(self, hypothesis_id: str, counter_observation: str):
        """Add counter-evidence to a hypothesis."""
        if hypothesis_id not in self.hypotheses:
            return

        hypothesis = self.hypotheses[hypothesis_id]
        if counter_observation not in hypothesis.counter_evidence:
            hypothesis.counter_evidence.append(counter_observation)
            hypothesis.counter_evidence = hypothesis.counter_evidence[-10:]

            # Reduce confidence
            hypothesis.confidence = max(0.1, hypothesis.confidence - 0.1)
            hypothesis.last_updated = datetime.now().isoformat()
            self._save_hypotheses()

    def get_testable_hypotheses(self, limit: int = 5) -> List[Hypothesis]:
        """Get hypotheses that need testing (predictions to make)."""
        testable = [
            h for h in self.hypotheses.values()
            if h.state in (HypothesisState.HYPOTHESIS, HypothesisState.TESTING)
            and h.sample_size < 5  # Not enough data yet
        ]
        testable.sort(key=lambda h: h.confidence, reverse=True)
        return testable[:limit]

    def get_pending_predictions(self) -> List[tuple]:
        """Get predictions awaiting outcomes."""
        pending = []
        for h in self.hypotheses.values():
            for i, p in enumerate(h.predictions):
                if p.outcome is None:
                    pending.append((h.hypothesis_id, i, h, p))
        return pending

    def get_stats(self) -> Dict[str, Any]:
        """Get hypothesis tracking statistics."""
        total = len(self.hypotheses)
        by_state = {}
        for h in self.hypotheses.values():
            s = h.state.value
            by_state[s] = by_state.get(s, 0) + 1

        total_predictions = sum(len(h.predictions) for h in self.hypotheses.values())
        outcomes_recorded = sum(
            sum(1 for p in h.predictions if p.outcome is not None)
            for h in self.hypotheses.values()
        )

        validated = [h for h in self.hypotheses.values() if h.state == HypothesisState.VALIDATED]
        avg_accuracy = sum(h.accuracy for h in validated) / len(validated) if validated else 0

        return {
            "total_hypotheses": total,
            "by_state": by_state,
            "total_predictions": total_predictions,
            "outcomes_recorded": outcomes_recorded,
            "pending_outcomes": total_predictions - outcomes_recorded,
            "validated_count": len(validated),
            "avg_validated_accuracy": avg_accuracy,
            "observation_patterns": len(self._observation_buffer),
        }


# Singleton
_tracker: Optional[HypothesisTracker] = None


def get_hypothesis_tracker() -> HypothesisTracker:
    """Get the global hypothesis tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = HypothesisTracker()
    return _tracker


def observe_for_hypothesis(observation: str, domain: str = "") -> Optional[Hypothesis]:
    """Convenience function to record an observation."""
    return get_hypothesis_tracker().observe(observation, domain)
