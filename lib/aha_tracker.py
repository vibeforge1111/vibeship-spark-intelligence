#!/usr/bin/env python3
"""
Aha Moment Tracker - Capture Surprising Events

Philosophy: The most valuable learning moments are surprises.
- Unexpected success: "That worked? I didn't think it would!"
- Unexpected failure: "That failed? I was sure it would work!"

These moments reveal gaps in our understanding and offer the highest
learning potential. We should capture them, analyze them, and learn deeply.

Surprise detection:
1. Track predictions vs outcomes
2. Flag large confidence gaps (predicted 90% success, got failure)
3. Categorize the surprise type
4. Extract the lesson
"""

from __future__ import annotations

import json
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

SPARK_DIR = Path(__file__).parent.parent / ".spark"
AHA_FILE = SPARK_DIR / "aha_moments.json"


class SurpriseType(Enum):
    UNEXPECTED_SUCCESS = "unexpected_success"  # Thought it would fail, but worked
    UNEXPECTED_FAILURE = "unexpected_failure"  # Thought it would work, but failed
    FASTER_THAN_EXPECTED = "faster_than_expected"
    SLOWER_THAN_EXPECTED = "slower_than_expected"
    DIFFERENT_PATH = "different_path"  # Succeeded via unexpected route
    RECOVERY_SUCCESS = "recovery_success"  # Failed, then recovered unexpectedly


@dataclass
class AhaMoment:
    """A captured moment of surprise."""
    id: str
    timestamp: float
    surprise_type: str
    predicted_outcome: str
    actual_outcome: str
    confidence_gap: float  # How wrong we were (0-1)
    context: Dict  # Tool, goal, sequence that led here
    lesson_extracted: Optional[str]  # What we learned
    importance: float  # How important this surprise is (0-1)
    occurrences: int = 1  # How many times this surprise has occurred

    def format_visible(self) -> str:
        """Format for user-visible display."""
        emoji = {
            "unexpected_success": "🎉",
            "unexpected_failure": "😮",
            "faster_than_expected": "⚡",
            "slower_than_expected": "🐢",
            "different_path": "🔀",
            "recovery_success": "💪",
        }.get(self.surprise_type, "💡")

        title = f"{emoji} **Surprise!** {self.surprise_type.replace('_', ' ').title()}"
        if self.occurrences > 1:
            title += f" (x{self.occurrences})"

        lines = [
            title,
            f"   Expected: {self.predicted_outcome}",
            f"   Got: {self.actual_outcome}",
            f"   Confidence gap: {self.confidence_gap:.0%}",
        ]

        if self.lesson_extracted:
            lines.append(f"   💡 Lesson: {self.lesson_extracted}")

        return "\n".join(lines)

    def format_shareable(self) -> str:
        """Format for sharing/tweet."""
        return f"💡 My AI surprised itself:\n\nExpected: {self.predicted_outcome}\nGot: {self.actual_outcome}\n\nLesson learned: {self.lesson_extracted or 'Still processing...'}\n\n#Vibeship #Spark"


class AhaTracker:
    """
    Track and analyze surprising moments.

    Usage:
        tracker = AhaTracker()
        tracker.capture_surprise(
            surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
            predicted="failure",
            actual="success",
            confidence_gap=0.8,
            context={"tool": "Bash", "command": "complex_command"}
        )
        insights = tracker.get_insights()
    """

    def __init__(self) -> None:
        self.data = self._load()
        self.pending_surface: List[str] = []  # IDs to show user

    def _load(self) -> Dict[str, Any]:
        if AHA_FILE.exists():
            try:
                data = json.loads(AHA_FILE.read_text(encoding='utf-8'))
                self.pending_surface = data.get("pending_surface", [])
                return data
            except (json.JSONDecodeError, OSError) as e:
                logging.getLogger(__name__).warning("Failed to load AHA file: %s", e)
        return {
            "moments": [],
            "lessons": [],
            "patterns": {},
            "pending_surface": [],
            "stats": {
                "total_captured": 0,
                "unexpected_successes": 0,
                "unexpected_failures": 0,
                "lessons_extracted": 0
            }
        }

    def _save(self) -> None:
        SPARK_DIR.mkdir(parents=True, exist_ok=True)
        self.data["pending_surface"] = self.pending_surface
        AHA_FILE.write_text(json.dumps(self.data, indent=2, default=str), encoding='utf-8')

    def _find_duplicate(self, tool: str, actual_outcome: str, hours: float = 24.0) -> Optional[int]:
        """Find a duplicate moment by tool + similar outcome within time window.

        Returns the index of the duplicate moment, or None if not found.
        """
        cutoff = datetime.now().timestamp() - (hours * 3600)
        actual_prefix = (actual_outcome or "")[:80].lower()

        for i, m in enumerate(self.data["moments"]):
            if m.get("timestamp", 0) < cutoff:
                continue
            m_tool = (m.get("context") or {}).get("tool", "")
            m_actual = (m.get("actual_outcome") or "")[:80].lower()
            if m_tool == tool and m_actual == actual_prefix:
                return i
        return None

    def capture_surprise(
        self,
        surprise_type: SurpriseType,
        predicted: str,
        actual: str,
        confidence_gap: float,
        context: Dict,
        lesson: Optional[str] = None,
        auto_surface: bool = True
    ) -> AhaMoment:
        """
        Capture a surprising moment.

        Args:
            surprise_type: Type of surprise
            predicted: What we expected
            actual: What actually happened
            confidence_gap: How wrong we were (0-1, higher = more surprising)
            context: Relevant context (tool, goal, etc.)
            lesson: Optional lesson extracted from this moment
            auto_surface: Add to pending queue to show user
        """
        tool = context.get("tool", "unknown")

        # Check for duplicate within last 24 hours
        dup_idx = self._find_duplicate(tool, actual)
        if dup_idx is not None:
            # Increment occurrences on existing moment instead of creating new
            self.data["moments"][dup_idx]["occurrences"] = self.data["moments"][dup_idx].get("occurrences", 1) + 1
            self.data["moments"][dup_idx]["timestamp"] = datetime.now().timestamp()  # Update timestamp
            self._save()
            return AhaMoment(**self.data["moments"][dup_idx])

        moment_id = hashlib.sha256(
            f"{datetime.now().timestamp()}{predicted}{actual}".encode()
        ).hexdigest()[:12]

        # Calculate importance based on confidence gap and type
        importance = confidence_gap
        if surprise_type in [SurpriseType.UNEXPECTED_FAILURE, SurpriseType.RECOVERY_SUCCESS]:
            importance *= 1.2
        importance = min(1.0, importance)

        moment = AhaMoment(
            id=moment_id,
            timestamp=datetime.now().timestamp(),
            surprise_type=surprise_type.value,
            predicted_outcome=predicted,
            actual_outcome=actual,
            confidence_gap=confidence_gap,
            context=context,
            lesson_extracted=lesson,
            importance=importance,
            occurrences=1
        )

        # Store moment
        self.data["moments"].append(asdict(moment))

        # Update stats
        self.data["stats"]["total_captured"] += 1
        if surprise_type == SurpriseType.UNEXPECTED_SUCCESS:
            self.data["stats"]["unexpected_successes"] += 1
        elif surprise_type == SurpriseType.UNEXPECTED_FAILURE:
            self.data["stats"]["unexpected_failures"] += 1

        if lesson:
            self.data["lessons"].append({
                "moment_id": moment_id,
                "lesson": lesson,
                "timestamp": datetime.now().timestamp()
            })
            self.data["stats"]["lessons_extracted"] += 1

        # Track patterns
        pattern_key = f"{surprise_type.value}:{context.get('tool', 'unknown')}"
        self.data["patterns"][pattern_key] = self.data["patterns"].get(pattern_key, 0) + 1

        # Add to surface queue
        if auto_surface and importance >= 0.5:
            self.pending_surface.append(moment_id)

        # Keep only last 200 moments
        if len(self.data["moments"]) > 200:
            self.data["moments"] = self.data["moments"][-200:]

        self._save()
        return moment

    def get_pending_surface(self) -> List[AhaMoment]:
        """Get moments waiting to be shown to user."""
        moments = []
        for moment_data in self.data["moments"]:
            if moment_data["id"] in self.pending_surface:
                moments.append(AhaMoment(**moment_data))
        return moments

    def surface(self, moment_id: str) -> Optional[str]:
        """Mark a moment as surfaced and return formatted string."""
        for moment_data in self.data["moments"]:
            if moment_data["id"] == moment_id:
                if moment_id in self.pending_surface:
                    self.pending_surface.remove(moment_id)
                    self._save()
                return AhaMoment(**moment_data).format_visible()
        return None

    def surface_all_pending(self) -> List[str]:
        """Surface all pending moments."""
        results = []
        for moment_id in list(self.pending_surface):
            formatted = self.surface(moment_id)
            if formatted:
                results.append(formatted)
        return results

    def extract_lesson(self, moment_id: str, lesson: str) -> bool:
        """Add a lesson to an existing moment."""
        for moment in self.data["moments"]:
            if moment["id"] == moment_id:
                moment["lesson_extracted"] = lesson
                self.data["lessons"].append({
                    "moment_id": moment_id,
                    "lesson": lesson,
                    "timestamp": datetime.now().timestamp()
                })
                self.data["stats"]["lessons_extracted"] += 1
                self._save()
                return True
        return False

    def get_recent_surprises(self, limit: int = 10) -> List[Dict]:
        """Get recent surprising moments with occurrence counts."""
        moments = []
        for m in self.data["moments"][-limit * 2:]:  # Get more to account for sorting
            moment_data = dict(m)
            moment_data.setdefault("occurrences", 1)
            moments.append(moment_data)
        moments.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return moments[:limit]

    def dedupe_existing(self) -> int:
        """Deduplicate existing moments, merging duplicates and summing occurrences.

        Returns the number of duplicates merged.
        """
        if not self.data["moments"]:
            return 0

        seen: Dict[str, int] = {}  # key -> index in deduped list
        deduped: List[Dict] = []
        merged_count = 0

        for m in self.data["moments"]:
            tool = (m.get("context") or {}).get("tool", "unknown")
            actual_prefix = (m.get("actual_outcome") or "")[:80].lower()
            key = f"{tool}:{actual_prefix}"

            if key in seen:
                # Merge into existing
                idx = seen[key]
                deduped[idx]["occurrences"] = deduped[idx].get("occurrences", 1) + m.get("occurrences", 1)
                # Keep the more recent timestamp
                if m.get("timestamp", 0) > deduped[idx].get("timestamp", 0):
                    deduped[idx]["timestamp"] = m["timestamp"]
                # Keep lesson if the existing one doesn't have one
                if not deduped[idx].get("lesson_extracted") and m.get("lesson_extracted"):
                    deduped[idx]["lesson_extracted"] = m["lesson_extracted"]
                merged_count += 1
            else:
                m.setdefault("occurrences", 1)
                seen[key] = len(deduped)
                deduped.append(dict(m))

        if merged_count > 0:
            self.data["moments"] = deduped
            self._save()

        return merged_count

    def get_high_importance_surprises(self, min_importance: float = 0.7) -> List[AhaMoment]:
        """Get surprises with high learning potential."""
        return [
            AhaMoment(**m) for m in self.data["moments"]
            if m["importance"] >= min_importance
        ]

    def get_unlearned_surprises(self) -> List[AhaMoment]:
        """Get surprises without extracted lessons."""
        return [
            AhaMoment(**m) for m in self.data["moments"]
            if not m.get("lesson_extracted")
        ]

    def get_surprise_patterns(self) -> Dict[str, int]:
        """Get patterns of what surprises us most."""
        return dict(sorted(
            self.data["patterns"].items(),
            key=lambda x: x[1],
            reverse=True
        ))

    def get_lessons(self) -> List[Dict]:
        """Get all extracted lessons."""
        return self.data["lessons"]

    def get_insights(self) -> Dict[str, Any]:
        """Analyze surprises and generate insights."""
        moments = [AhaMoment(**m) for m in self.data["moments"]]
        if not moments:
            return {"message": "No surprises captured yet"}

        # Analyze patterns
        by_type = {}
        by_tool = {}
        total_gap = 0

        for m in moments:
            by_type[m.surprise_type] = by_type.get(m.surprise_type, 0) + 1
            tool = m.context.get("tool", "unknown")
            by_tool[tool] = by_tool.get(tool, 0) + 1
            total_gap += m.confidence_gap

        avg_gap = total_gap / len(moments)

        insights = {
            "total_surprises": len(moments),
            "avg_confidence_gap": avg_gap,
            "most_surprising_type": max(by_type.items(), key=lambda x: x[1])[0] if by_type else None,
            "most_surprising_tool": max(by_tool.items(), key=lambda x: x[1])[0] if by_tool else None,
            "lessons_learned": len(self.data["lessons"]),
            "learning_rate": len(self.data["lessons"]) / len(moments) if moments else 0,
            "breakdown_by_type": by_type,
            "breakdown_by_tool": by_tool
        }

        # Add recommendations
        recommendations = []
        if insights["avg_confidence_gap"] > 0.6:
            recommendations.append("High average surprise gap - predictions may be overconfident")
        if by_type.get("unexpected_failure", 0) > by_type.get("unexpected_success", 0):
            recommendations.append("More unexpected failures than successes - may be too optimistic")
        if insights["learning_rate"] < 0.5:
            recommendations.append("Low lesson extraction rate - review unlearned surprises")

        insights["recommendations"] = recommendations
        return insights

    def get_stats(self) -> Dict[str, Any]:
        """Get tracker statistics."""
        total_occurrences = sum(m.get("occurrences", 1) for m in self.data["moments"])
        return {
            **self.data["stats"],
            "pattern_count": len(self.data["patterns"]),
            "unlearned_count": len(self.get_unlearned_surprises()),
            "pending_surface": len(self.pending_surface),
            "unique_moments": len(self.data["moments"]),
            "total_occurrences": total_occurrences
        }


# Singleton
_tracker: Optional[AhaTracker] = None


def get_aha_tracker() -> AhaTracker:
    global _tracker
    if _tracker is None:
        _tracker = AhaTracker()
    return _tracker


def dedupe_aha_moments() -> int:
    """Deduplicate existing aha moments file. Returns count of duplicates merged."""
    tracker = get_aha_tracker()
    return tracker.dedupe_existing()


def maybe_capture_surprise(
    prediction: Dict,
    outcome: Dict,
    threshold: float = 0.5
) -> Optional[AhaMoment]:
    """
    Check if an outcome was surprising and capture it.

    Args:
        prediction: {"outcome": "success/failure", "confidence": 0.0-1.0}
        outcome: {"success": bool, "tool": str, ...}
        threshold: Minimum confidence gap to consider surprising
    """
    tracker = get_aha_tracker()

    predicted_success = prediction.get("outcome", "").lower() == "success"
    actual_success = outcome.get("success", False)
    confidence = prediction.get("confidence", 0.5)

    if predicted_success and not actual_success:
        confidence_gap = confidence
        if confidence_gap >= threshold:
            return tracker.capture_surprise(
                surprise_type=SurpriseType.UNEXPECTED_FAILURE,
                predicted=f"success ({confidence:.0%} confident)",
                actual="failure",
                confidence_gap=confidence_gap,
                context=outcome
            )
    elif not predicted_success and actual_success:
        confidence_gap = 1 - confidence
        if confidence_gap >= threshold:
            return tracker.capture_surprise(
                surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
                predicted=f"failure ({1-confidence:.0%} confident)",
                actual="success",
                confidence_gap=confidence_gap,
                context=outcome
            )

    return None
