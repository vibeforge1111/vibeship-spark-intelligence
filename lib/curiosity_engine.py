"""
Curiosity Engine: Tracks what we don't know and actively seeks to fill knowledge gaps.

The Problem:
- We only learn from what happens to pass by
- We don't know what we don't know
- No active seeking of valuable information

The Solution:
- Track "unknown edges" - things referenced but not understood
- Generate questions from partial knowledge
- Surface curiosity prompts during relevant contexts
- Reward question-asking that leads to valuable answers

Knowledge Gap Types:
1. WHY gaps: "User prefers X" → "Why does user prefer X?"
2. WHEN gaps: "Pattern X works" → "When does X work vs not work?"
3. HOW gaps: "Achieved Y" → "How exactly was Y achieved?"
4. WHAT gaps: "Mentioned Z" → "What is Z?"
5. WHO gaps: "Works for them" → "Who is 'them'?"
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import hashlib


class GapType(Enum):
    WHY = "why"       # Missing reasoning/motivation
    WHEN = "when"     # Missing context/conditions
    HOW = "how"       # Missing process/method
    WHAT = "what"     # Missing definition/clarification
    WHO = "who"       # Missing actor/subject


@dataclass
class KnowledgeGap:
    """A gap in our knowledge that we want to fill."""
    gap_type: GapType
    topic: str
    question: str
    source_insight: Optional[str] = None  # What insight generated this gap
    context: str = ""
    priority: float = 0.5  # 0-1, how important to fill
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    filled: bool = False
    filled_at: Optional[str] = None
    answer: Optional[str] = None
    answer_valuable: Optional[bool] = None  # Was the answer valuable?

    @property
    def gap_id(self) -> str:
        """Generate unique ID for this gap."""
        key = f"{self.gap_type.value}:{self.topic}:{self.question[:50]}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "gap_type": self.gap_type.value,
            "topic": self.topic,
            "question": self.question,
            "source_insight": self.source_insight,
            "context": self.context,
            "priority": self.priority,
            "created_at": self.created_at,
            "filled": self.filled,
            "filled_at": self.filled_at,
            "answer": self.answer,
            "answer_valuable": self.answer_valuable,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeGap":
        return cls(
            gap_type=GapType(data["gap_type"]),
            topic=data["topic"],
            question=data["question"],
            source_insight=data.get("source_insight"),
            context=data.get("context", ""),
            priority=data.get("priority", 0.5),
            created_at=data.get("created_at", datetime.now().isoformat()),
            filled=data.get("filled", False),
            filled_at=data.get("filled_at"),
            answer=data.get("answer"),
            answer_valuable=data.get("answer_valuable"),
        )


# Question generation templates
QUESTION_TEMPLATES = {
    GapType.WHY: [
        "Why does {subject} {action}?",
        "What's the reason behind {topic}?",
        "What motivates {topic}?",
    ],
    GapType.WHEN: [
        "When does {topic} apply?",
        "Under what conditions is {topic} true?",
        "When should {topic} be used vs not?",
    ],
    GapType.HOW: [
        "How exactly does {topic} work?",
        "What's the process for {topic}?",
        "How is {topic} achieved?",
    ],
    GapType.WHAT: [
        "What exactly is {topic}?",
        "Can you clarify what {topic} means?",
        "What does {topic} refer to?",
    ],
    GapType.WHO: [
        "Who is involved in {topic}?",
        "Who does {topic} affect?",
        "Who is responsible for {topic}?",
    ],
}

# Patterns that indicate missing knowledge
GAP_INDICATORS = {
    GapType.WHY: [
        r"\bprefers?\b",
        r"\blikes?\b",
        r"\bhates?\b",
        r"\bwants?\b",
        r"\bchooses?\b",
        r"\bdecided?\b",
    ],
    GapType.WHEN: [
        r"\bworks\b",
        r"\bfails?\b",
        r"\bsometimes\b",
        r"\busually\b",
        r"\bdepends\b",
    ],
    GapType.HOW: [
        r"\bachieved?\b",
        r"\bfixed\b",
        r"\bsolved\b",
        r"\bimplemented\b",
        r"\bbuilt\b",
    ],
    GapType.WHAT: [
        r"\bthe (\w+)\b",  # "the X" - might need clarification
        r"\bthis (\w+)\b",
        r"\bthat (\w+)\b",
    ],
}


def _extract_topic(text: str) -> str:
    """Extract main topic from text."""
    # Remove common prefixes
    text = re.sub(r"^(User\s+)?(prefers?|likes?|wants?|hates?)\s+", "", text, flags=re.I)
    # Take first phrase
    words = text.split()[:5]
    return " ".join(words).strip()


def _generate_question(gap_type: GapType, topic: str, original_text: str) -> str:
    """Generate a question for a knowledge gap."""
    templates = QUESTION_TEMPLATES.get(gap_type, [])
    if not templates:
        return f"What more can we learn about {topic}?"

    template = templates[0]  # Use first template
    subject = "the user" if "user" in original_text.lower() else "this"
    action = _extract_topic(original_text)

    return template.format(topic=topic, subject=subject, action=action)


class CuriosityEngine:
    """
    Tracks knowledge gaps and generates questions to fill them.

    The goal is to actively seek valuable information, not just
    passively process what comes in.
    """

    GAPS_FILE = Path.home() / ".spark" / "knowledge_gaps.json"

    def __init__(self) -> None:
        self.gaps: Dict[str, KnowledgeGap] = {}  # gap_id -> gap
        self.question_success_rate: Dict[str, float] = {}  # gap_type -> success rate
        self._load_gaps()

    def _load_gaps(self) -> None:
        """Load existing knowledge gaps."""
        if self.GAPS_FILE.exists():
            try:
                data = json.loads(self.GAPS_FILE.read_text(encoding="utf-8"))
                for gap_data in data.get("gaps", []):
                    gap = KnowledgeGap.from_dict(gap_data)
                    self.gaps[gap.gap_id] = gap
                self.question_success_rate = data.get("success_rates", {})
            except Exception:
                pass

    def _save_gaps(self) -> None:
        """Save knowledge gaps to disk."""
        self.GAPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "gaps": [g.to_dict() for g in self.gaps.values()],
            "success_rates": self.question_success_rate,
        }
        self.GAPS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def identify_gaps(self, insight_text: str, context: str = "") -> List[KnowledgeGap]:
        """
        Identify knowledge gaps from an insight.

        Returns list of gaps that could be filled.
        """
        text_lower = insight_text.lower()
        topic = _extract_topic(insight_text)
        gaps = []

        for gap_type, patterns in GAP_INDICATORS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower, re.I):
                    question = _generate_question(gap_type, topic, insight_text)

                    # Calculate priority based on gap type success rate
                    base_priority = 0.5
                    if gap_type.value in self.question_success_rate:
                        base_priority = self.question_success_rate[gap_type.value]

                    gap = KnowledgeGap(
                        gap_type=gap_type,
                        topic=topic,
                        question=question,
                        source_insight=insight_text[:200],
                        context=context,
                        priority=base_priority,
                    )

                    # Don't add duplicate gaps
                    if gap.gap_id not in self.gaps:
                        gaps.append(gap)
                        self.gaps[gap.gap_id] = gap
                    break  # One gap per type per insight

        if gaps:
            self._save_gaps()

        return gaps

    def get_relevant_questions(self, context: str, limit: int = 3) -> List[KnowledgeGap]:
        """
        Get questions relevant to current context.

        These are questions we'd like answered based on what we're working on.
        """
        context_lower = context.lower()
        relevant = []

        for gap in self.gaps.values():
            if gap.filled:
                continue

            # Check relevance by topic/question overlap with context
            relevance = 0.0
            gap_words = set(gap.topic.lower().split() + gap.question.lower().split())
            context_words = set(context_lower.split())

            if gap_words and context_words:
                overlap = len(gap_words & context_words)
                relevance = overlap / len(gap_words) if gap_words else 0

            if relevance > 0.2:  # At least 20% word overlap
                relevant.append((relevance * gap.priority, gap))

        # Sort by relevance * priority
        relevant.sort(key=lambda x: x[0], reverse=True)

        return [g for _, g in relevant[:limit]]

    def fill_gap(self, gap_id: str, answer: str, valuable: bool = True) -> None:
        """
        Fill a knowledge gap with an answer.

        Args:
            gap_id: The gap ID to fill
            answer: The answer/information that fills the gap
            valuable: Whether this answer was actually valuable
        """
        if gap_id not in self.gaps:
            return

        gap = self.gaps[gap_id]
        gap.filled = True
        gap.filled_at = datetime.now().isoformat()
        gap.answer = answer
        gap.answer_valuable = valuable

        # Update success rate for this gap type
        gap_type = gap.gap_type.value
        filled_gaps = [g for g in self.gaps.values() if g.filled and g.gap_type.value == gap_type]
        if filled_gaps:
            valuable_count = sum(1 for g in filled_gaps if g.answer_valuable)
            self.question_success_rate[gap_type] = valuable_count / len(filled_gaps)

        self._save_gaps()

        # If valuable, store the answer as an insight
        if valuable and answer:
            try:
                from .cognitive_learner import get_cognitive_learner, CognitiveCategory
                learner = get_cognitive_learner()

                # Map gap type to category
                category_map = {
                    GapType.WHY: CognitiveCategory.REASONING,
                    GapType.WHEN: CognitiveCategory.CONTEXT,
                    GapType.HOW: CognitiveCategory.REASONING,
                    GapType.WHAT: CognitiveCategory.CONTEXT,
                    GapType.WHO: CognitiveCategory.USER_UNDERSTANDING,
                }

                category = category_map.get(gap.gap_type, CognitiveCategory.CONTEXT)
                learner.add_insight(
                    category=category,
                    insight=answer,
                    context=f"Answer to: {gap.question}",
                    confidence=0.8,
                    source="curiosity_engine",
                )
            except Exception:
                pass

    def suggest_question(self, context: str = "") -> Optional[KnowledgeGap]:
        """
        Suggest a question to ask based on current context.

        This is the "curiosity prompt" that can be surfaced to the user.
        """
        relevant = self.get_relevant_questions(context, limit=1)
        if relevant:
            return relevant[0]

        # If no context-relevant questions, return highest priority unfilled gap
        unfilled = [g for g in self.gaps.values() if not g.filled]
        if unfilled:
            return max(unfilled, key=lambda g: g.priority)

        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get curiosity engine statistics."""
        total = len(self.gaps)
        filled = sum(1 for g in self.gaps.values() if g.filled)
        valuable = sum(1 for g in self.gaps.values() if g.answer_valuable)

        by_type = {}
        for g in self.gaps.values():
            t = g.gap_type.value
            if t not in by_type:
                by_type[t] = {"total": 0, "filled": 0, "valuable": 0}
            by_type[t]["total"] += 1
            if g.filled:
                by_type[t]["filled"] += 1
            if g.answer_valuable:
                by_type[t]["valuable"] += 1

        return {
            "total_gaps": total,
            "filled": filled,
            "unfilled": total - filled,
            "valuable_answers": valuable,
            "value_rate": valuable / filled if filled > 0 else 0.0,
            "by_type": by_type,
            "success_rates": self.question_success_rate,
        }

    def get_open_questions(self, limit: int = 10) -> List[KnowledgeGap]:
        """Get unfilled knowledge gaps ordered by priority."""
        unfilled = [g for g in self.gaps.values() if not g.filled]
        unfilled.sort(key=lambda g: g.priority, reverse=True)
        return unfilled[:limit]


# Singleton
_engine: Optional[CuriosityEngine] = None


def get_curiosity_engine() -> CuriosityEngine:
    """Get the global curiosity engine instance."""
    global _engine
    if _engine is None:
        _engine = CuriosityEngine()
    return _engine


def identify_knowledge_gaps(insight_text: str, context: str = "") -> List[KnowledgeGap]:
    """Convenience function to identify knowledge gaps."""
    return get_curiosity_engine().identify_gaps(insight_text, context)


def suggest_question(context: str = "") -> Optional[KnowledgeGap]:
    """Convenience function to get a suggested question."""
    return get_curiosity_engine().suggest_question(context)
