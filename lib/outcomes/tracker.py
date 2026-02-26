"""
Outcome Tracker - Track outcomes and update insight scores.

Maintains running statistics on outcomes and uses them
to validate/invalidate insights over time.
"""

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from collections import defaultdict

from .signals import Outcome, OutcomeType, detect_outcome
from .linker import OutcomeLinker, get_linker

log = logging.getLogger("spark.outcomes")

TRACKER_FILE = Path.home() / ".spark" / "outcome_tracker.json"


@dataclass
class InsightValidation:
    """Validation state for an insight."""
    insight_id: str
    positive_validations: int = 0
    negative_validations: int = 0
    total_confidence: float = 0.0
    last_validated: str = ""

    @property
    def reliability(self) -> float:
        """Calculate reliability score (0-1)."""
        total = self.positive_validations + self.negative_validations
        if total == 0:
            return 0.5  # Unknown

        # Positive ratio with some smoothing
        positive_ratio = (self.positive_validations + 1) / (total + 2)

        # Weight by confidence
        confidence_factor = min(1.0, self.total_confidence / 5.0)

        return positive_ratio * (0.7 + 0.3 * confidence_factor)

    @property
    def validated(self) -> bool:
        """Is this insight sufficiently validated?"""
        return self.reliability >= 0.7 and self.positive_validations >= 2


@dataclass
class TrackerState:
    """Persistent state for the tracker."""
    insights: Dict[str, InsightValidation] = field(default_factory=dict)
    total_outcomes: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_updated: str = ""

    def to_dict(self) -> Dict:
        return {
            "insights": {k: asdict(v) for k, v in self.insights.items()},
            "total_outcomes": self.total_outcomes,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'TrackerState':
        insights = {}
        for k, v in data.get("insights", {}).items():
            try:
                insights[k] = InsightValidation(**v)
            except TypeError:
                log.warning("Skipping malformed insight entry %r", k)
        return cls(
            insights=insights,
            total_outcomes=data.get("total_outcomes", 0),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            last_updated=data.get("last_updated", ""),
        )


class OutcomeTracker:
    """Track outcomes and validate insights."""

    def __init__(self):
        self.state = self._load_state()
        self.linker = get_linker()
        self._recent_insights: List[Dict] = []

    def _load_state(self) -> TrackerState:
        """Load state from disk."""
        if not TRACKER_FILE.exists():
            return TrackerState()
        try:
            with open(TRACKER_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return TrackerState.from_dict(data)
        except Exception as e:
            log.warning(f"Failed to load tracker state: {e}")
            return TrackerState()

    def _save_state(self):
        """Save state to disk (atomic write to avoid partial-JSON on crash)."""
        try:
            TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.state.last_updated = datetime.now().isoformat()
            fd, tmp_path = tempfile.mkstemp(
                dir=TRACKER_FILE.parent, suffix=".tmp"
            )
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self.state.to_dict(), f, indent=2)
            os.replace(tmp_path, TRACKER_FILE)
        except Exception as e:
            log.error(f"Failed to save tracker state: {e}")

    def add_insight(self, insight: Dict):
        """Add an insight to track for validation."""
        self._recent_insights.append(insight)
        # Keep only recent insights (last 50)
        if len(self._recent_insights) > 50:
            self._recent_insights = self._recent_insights[-50:]

    def process_event(self, event: Dict):
        """Process an event for outcome signals."""
        outcome = detect_outcome(event)
        if not outcome:
            return

        # Update global stats
        self.state.total_outcomes += 1
        if outcome.type == OutcomeType.SUCCESS:
            self.state.success_count += 1
        elif outcome.type == OutcomeType.FAILURE:
            self.state.failure_count += 1

        # Link to recent insights
        links = self.linker.link(outcome, self._recent_insights)

        # Update insight validations
        for link in links:
            self._update_insight_validation(link.insight_id, outcome, link.confidence)

        self._save_state()

    def _update_insight_validation(self, insight_id: str, outcome: Outcome, confidence: float):
        """Update validation state for an insight."""
        if insight_id not in self.state.insights:
            self.state.insights[insight_id] = InsightValidation(insight_id=insight_id)

        validation = self.state.insights[insight_id]

        if outcome.type == OutcomeType.SUCCESS:
            validation.positive_validations += 1
            validation.total_confidence += confidence
        elif outcome.type == OutcomeType.FAILURE:
            validation.negative_validations += 1
            validation.total_confidence += confidence

        validation.last_validated = datetime.now().isoformat()

    def get_insight_reliability(self, insight_id: str) -> float:
        """Get reliability score for an insight."""
        if insight_id not in self.state.insights:
            return 0.5  # Unknown
        return self.state.insights[insight_id].reliability

    def is_validated(self, insight_id: str) -> bool:
        """Check if insight is sufficiently validated."""
        if insight_id not in self.state.insights:
            return False
        return self.state.insights[insight_id].validated

    def get_validated_insights(self) -> List[str]:
        """Get list of validated insight IDs."""
        return [
            insight_id
            for insight_id, validation in self.state.insights.items()
            if validation.validated
        ]

    def get_invalidated_insights(self) -> List[str]:
        """Get list of insights that failed validation."""
        return [
            insight_id
            for insight_id, validation in self.state.insights.items()
            if validation.reliability < 0.3 and validation.negative_validations >= 2
        ]

    def get_stats(self) -> Dict:
        """Get outcome tracking statistics."""
        validated_count = len(self.get_validated_insights())
        invalidated_count = len(self.get_invalidated_insights())
        pending_count = len(self.state.insights) - validated_count - invalidated_count

        success_rate = 0.0
        if self.state.total_outcomes > 0:
            success_rate = self.state.success_count / self.state.total_outcomes

        return {
            "total_outcomes": self.state.total_outcomes,
            "success_count": self.state.success_count,
            "failure_count": self.state.failure_count,
            "success_rate": success_rate,
            "insights_tracked": len(self.state.insights),
            "validated": validated_count,
            "invalidated": invalidated_count,
            "pending": pending_count,
        }


# Singleton tracker
_tracker: Optional[OutcomeTracker] = None


def get_tracker() -> OutcomeTracker:
    """Get singleton tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = OutcomeTracker()
    return _tracker
