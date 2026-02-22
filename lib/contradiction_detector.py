"""
Contradiction Detector: Catches when new information conflicts with existing beliefs.

The Problem:
- We store new insights without checking if they contradict existing ones
- User preferences can change, but we don't notice
- Context-dependent truths get stored as absolute truths

The Solution:
- Before storing, semantic search for similar existing insights
- Detect sentiment/meaning opposition
- Track contradictions for resolution
- Learn when beliefs are context-dependent vs need updating

Contradiction Types:
1. DIRECT: "User prefers X" vs "User prefers Y" (same topic, different answer)
2. TEMPORAL: Old belief superseded by new information
3. CONTEXTUAL: Both true, but in different contexts
4. UNCERTAIN: Not enough evidence to determine
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class ContradictionType(Enum):
    DIRECT = "direct"           # Mutually exclusive beliefs
    TEMPORAL = "temporal"       # New info supersedes old
    CONTEXTUAL = "contextual"   # Both true in different contexts
    UNCERTAIN = "uncertain"     # Need more evidence


@dataclass
class Contradiction:
    """A detected contradiction between insights."""
    existing_key: str
    existing_text: str
    new_text: str
    similarity: float
    contradiction_type: ContradictionType
    confidence: float
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved: bool = False
    resolution: Optional[str] = None
    resolution_type: Optional[str] = None  # "update", "context", "keep_both", "discard_new"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "existing_key": self.existing_key,
            "existing_text": self.existing_text,
            "new_text": self.new_text,
            "similarity": self.similarity,
            "contradiction_type": self.contradiction_type.value,
            "confidence": self.confidence,
            "detected_at": self.detected_at,
            "resolved": self.resolved,
            "resolution": self.resolution,
            "resolution_type": self.resolution_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Contradiction":
        return cls(
            existing_key=data["existing_key"],
            existing_text=data["existing_text"],
            new_text=data["new_text"],
            similarity=data["similarity"],
            contradiction_type=ContradictionType(data["contradiction_type"]),
            confidence=data["confidence"],
            detected_at=data.get("detected_at", datetime.now().isoformat()),
            resolved=data.get("resolved", False),
            resolution=data.get("resolution"),
            resolution_type=data.get("resolution_type"),
        )


# Opposition indicators
OPPOSITION_PAIRS = [
    (r"\bprefer\b", r"\bavoid\b"),
    (r"\blike\b", r"\bhate\b"),
    (r"\blike\b", r"\bdislike\b"),
    (r"\balways\b", r"\bnever\b"),
    (r"\byes\b", r"\bno\b"),
    (r"\bdo\b", r"\bdon'?t\b"),
    (r"\bshould\b", r"\bshouldn'?t\b"),
    (r"\bwant\b", r"\bdon'?t want\b"),
    (r"\bgood\b", r"\bbad\b"),
    (r"\bbetter\b", r"\bworse\b"),
    (r"\bmore\b", r"\bless\b"),
    (r"\bincrease\b", r"\bdecrease\b"),
]

# Negation patterns
NEGATION_PATTERNS = [
    r"\bnot\b",
    r"\bno\b",
    r"\bnever\b",
    r"\bdon'?t\b",
    r"\bdoesn'?t\b",
    r"\bwon'?t\b",
    r"\bcan'?t\b",
    r"\bshouldn'?t\b",
    r"\bwouldn'?t\b",
    r"\bnone\b",
    r"\bnothing\b",
]


def _has_negation(text: str) -> bool:
    """Check if text contains negation."""
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in NEGATION_PATTERNS)


def _has_opposition(text1: str, text2: str) -> Tuple[bool, float]:
    """Check if two texts have opposing sentiment."""
    t1 = text1.lower()
    t2 = text2.lower()

    # Check for direct opposition pairs
    for pos, neg in OPPOSITION_PAIRS:
        if re.search(pos, t1) and re.search(neg, t2):
            return True, 0.8
        if re.search(neg, t1) and re.search(pos, t2):
            return True, 0.8

    # Check for negation asymmetry
    neg1 = _has_negation(t1)
    neg2 = _has_negation(t2)
    if neg1 != neg2:
        return True, 0.6

    return False, 0.0


def _extract_topic(text: str) -> str:
    """Extract the main topic from an insight."""
    # Remove common prefixes
    text = re.sub(r"^(User\s+)?(prefers?|likes?|wants?|hates?|dislikes?|avoids?)\s+", "", text, flags=re.I)
    text = re.sub(r"^(I\s+)?(struggle|learned|realized|noticed)\s+(with|that)?\s*", "", text, flags=re.I)
    # Take first meaningful phrase
    words = text.split()[:6]
    return " ".join(words).lower().strip()


class ContradictionDetector:
    """
    Detects contradictions between new and existing insights.

    Flow:
    1. New insight comes in
    2. Semantic search for similar existing insights
    3. Check for opposition/contradiction signals
    4. If contradiction found, track for resolution
    5. Learn resolution patterns over time
    """

    CONTRADICTIONS_FILE = Path.home() / ".spark" / "contradictions.json"

    def __init__(self) -> None:
        self.contradictions: List[Contradiction] = []
        self._load_contradictions()

    def _load_contradictions(self) -> None:
        """Load existing contradictions."""
        if self.CONTRADICTIONS_FILE.exists():
            try:
                data = json.loads(self.CONTRADICTIONS_FILE.read_text(encoding="utf-8"))
                self.contradictions = [Contradiction.from_dict(c) for c in data]
            except Exception:
                pass

    def _save_contradictions(self) -> None:
        """Save contradictions to disk."""
        self.CONTRADICTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = [c.to_dict() for c in self.contradictions]
        self.CONTRADICTIONS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding for text."""
        try:
            from .embeddings import embed_text
            return embed_text(text)
        except Exception:
            return None

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity."""
        import math
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def check_contradiction(self, new_text: str, min_similarity: float = 0.6) -> Optional[Contradiction]:
        """
        Check if new text contradicts any existing insight.

        Returns Contradiction if found, None otherwise.
        """
        try:
            from .cognitive_learner import get_cognitive_learner
            learner = get_cognitive_learner()
        except Exception:
            return None

        new_embedding = self._get_embedding(new_text)
        new_topic = _extract_topic(new_text)

        candidates = []

        for key, insight in learner.insights.items():
            existing_text = insight.insight

            # Check topic similarity
            existing_topic = _extract_topic(existing_text)

            # Semantic similarity
            similarity = 0.0
            if new_embedding:
                existing_embedding = self._get_embedding(existing_text)
                if existing_embedding:
                    similarity = self._cosine_similarity(new_embedding, existing_embedding)

            # Topic word overlap
            new_words = set(new_topic.split())
            existing_words = set(existing_topic.split())
            if new_words and existing_words:
                overlap = len(new_words & existing_words) / len(new_words | existing_words)
                similarity = max(similarity, overlap)

            if similarity < min_similarity:
                continue

            # Check for opposition
            has_opp, opp_confidence = _has_opposition(new_text, existing_text)

            if has_opp:
                candidates.append({
                    "key": key,
                    "text": existing_text,
                    "similarity": similarity,
                    "opposition_confidence": opp_confidence,
                })

        if not candidates:
            return None

        # Return highest confidence contradiction
        best = max(candidates, key=lambda c: c["similarity"] * c["opposition_confidence"])

        contradiction = Contradiction(
            existing_key=best["key"],
            existing_text=best["text"],
            new_text=new_text,
            similarity=best["similarity"],
            contradiction_type=self._infer_type(best["text"], new_text),
            confidence=best["similarity"] * best["opposition_confidence"],
        )

        self.contradictions.append(contradiction)
        self._save_contradictions()

        return contradiction

    def _infer_type(self, existing: str, new: str) -> ContradictionType:
        """Infer the type of contradiction."""
        # Check for temporal indicators
        temporal_words = ["now", "currently", "lately", "recently", "changed", "updated"]
        if any(w in new.lower() for w in temporal_words):
            return ContradictionType.TEMPORAL

        # Check for context indicators
        context_words = ["when", "if", "during", "for", "in case of", "sometimes"]
        if any(w in new.lower() for w in context_words) or any(w in existing.lower() for w in context_words):
            return ContradictionType.CONTEXTUAL

        # Default to uncertain
        return ContradictionType.UNCERTAIN

    def resolve(self, contradiction_idx: int, resolution_type: str, resolution: str = "") -> None:
        """
        Resolve a contradiction.

        resolution_type:
        - "update": New info supersedes old
        - "context": Both true in different contexts
        - "keep_both": Both are valid
        - "discard_new": Keep old, ignore new
        """
        if 0 <= contradiction_idx < len(self.contradictions):
            c = self.contradictions[contradiction_idx]
            c.resolved = True
            c.resolution_type = resolution_type
            c.resolution = resolution
            self._save_contradictions()

            # If updating, modify the existing insight
            if resolution_type == "update":
                try:
                    from .cognitive_learner import get_cognitive_learner
                    learner = get_cognitive_learner()
                    if c.existing_key in learner.insights:
                        # Mark old as contradicted
                        learner.insights[c.existing_key].times_contradicted += 1
                        learner._save_insights()
                except Exception:
                    pass

    def get_unresolved(self) -> List[Tuple[int, Contradiction]]:
        """Get all unresolved contradictions."""
        return [(i, c) for i, c in enumerate(self.contradictions) if not c.resolved]

    def get_stats(self) -> Dict[str, Any]:
        """Get contradiction statistics."""
        total = len(self.contradictions)
        resolved = sum(1 for c in self.contradictions if c.resolved)
        by_type = {}
        for c in self.contradictions:
            t = c.contradiction_type.value
            by_type[t] = by_type.get(t, 0) + 1

        resolution_types = {}
        for c in self.contradictions:
            if c.resolution_type:
                resolution_types[c.resolution_type] = resolution_types.get(c.resolution_type, 0) + 1

        return {
            "total": total,
            "resolved": resolved,
            "unresolved": total - resolved,
            "by_type": by_type,
            "resolution_types": resolution_types,
        }


# Singleton
_detector: Optional[ContradictionDetector] = None


def get_contradiction_detector() -> ContradictionDetector:
    """Get the global contradiction detector instance."""
    global _detector
    if _detector is None:
        _detector = ContradictionDetector()
    return _detector


def check_for_contradiction(new_text: str) -> Optional[Contradiction]:
    """Convenience function to check for contradictions."""
    return get_contradiction_detector().check_contradiction(new_text)
