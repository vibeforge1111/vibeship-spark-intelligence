#!/usr/bin/env python3
"""
ConvoIQ - Conversation Intelligence for X/Twitter.

Analyzes replies, extracts conversation DNA, scores drafts,
and recommends hooks. Learns what makes conversations land.

"Every great reply starts with understanding the conversation."
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

try:
    from lib.x_voice import get_x_voice, XVoice, TONE_PROFILES
except ImportError:
    get_x_voice = None
    XVoice = None
    TONE_PROFILES = {}


# State directory
CONVO_DIR = Path.home() / ".spark" / "convo_iq"
DNA_FILE = CONVO_DIR / "conversation_dna.json"
REPLY_LOG = CONVO_DIR / "reply_log.jsonl"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ConversationDNA:
    """Extracted pattern from successful conversations."""

    pattern_type: str  # hook_and_expand | question_chain | build_together | debate
    hook_type: str  # question | observation | challenge | agreement | addition
    tone: str  # witty | technical | conversational | provocative
    structure: str  # short | medium | long
    engagement_score: float  # 0-10
    examples: List[str] = field(default_factory=list)
    topic_tags: List[str] = field(default_factory=list)
    times_seen: int = 1
    last_seen: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ReplyAnalysis:
    """Analysis of a reply's potential effectiveness."""

    hook_type: str
    tone: str
    estimated_engagement: float  # 0-10
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


@dataclass
class HookRecommendation:
    """A recommended conversation hook."""

    hook_type: str
    tone: str
    template: str  # Pattern template (not literal text)
    reasoning: str
    confidence: float  # 0-1
    based_on_dna: Optional[str] = None  # DNA pattern this is based on


# ---------------------------------------------------------------------------
# Hook type classification
# ---------------------------------------------------------------------------

HOOK_PATTERNS = {
    "question": [
        r"\?$",
        r"^(?:what|how|why|when|where|who|which|do you|have you|is it|can you)",
        r"(?:curious|wondering|thoughts on|what do you think)",
    ],
    "observation": [
        r"(?:noticed|interesting|pattern|seems like|looks like)",
        r"(?:the thing about|what stands out|one thing I see)",
    ],
    "challenge": [
        r"(?:disagree|actually|but what about|counterpoint|hot take)",
        r"(?:unpopular opinion|contrary to|the problem with)",
    ],
    "agreement": [
        r"(?:exactly|this|100%|spot on|nailed it|so true)",
        r"(?:couldn't agree more|yes and|building on this)",
    ],
    "addition": [
        r"(?:also|adding|plus|and another|related to this|on top of)",
        r"(?:to extend this|another angle|worth adding)",
    ],
}

_COMPILED_HOOKS = {
    hook_type: [re.compile(p, re.IGNORECASE) for p in patterns]
    for hook_type, patterns in HOOK_PATTERNS.items()
}


def classify_hook(text: str) -> str:
    """Classify the hook type of a reply."""
    text_trimmed = text[:100]

    scores: Dict[str, int] = {}
    for hook_type, patterns in _COMPILED_HOOKS.items():
        scores[hook_type] = sum(1 for p in patterns if p.search(text_trimmed))

    if not any(scores.values()):
        return "observation"  # Default

    return max(scores, key=scores.get)


def classify_structure(text: str) -> str:
    """Classify reply structure by length."""
    word_count = len(text.split())
    if word_count <= 15:
        return "short"
    elif word_count <= 40:
        return "medium"
    return "long"


# ---------------------------------------------------------------------------
# Core ConvoAnalyzer
# ---------------------------------------------------------------------------


class ConvoAnalyzer:
    """Analyzes conversations and learns reply patterns.

    Key capabilities:
    - Classify reply hooks and tones
    - Extract conversation DNA from successful exchanges
    - Score reply drafts before posting
    - Recommend hooks for specific contexts
    - Study high-engagement replies for patterns
    """

    def __init__(self) -> None:
        self.dna_patterns: Dict[str, ConversationDNA] = {}
        self.x_voice: XVoice = get_x_voice()
        self._load_dna()

    def _load_dna(self) -> None:
        """Load conversation DNA patterns from disk."""
        if DNA_FILE.exists():
            try:
                raw = json.loads(DNA_FILE.read_text(encoding="utf-8"))
                for key, data in raw.items():
                    self.dna_patterns[key] = ConversationDNA(**data)
            except Exception:
                pass

    def _save_dna(self) -> None:
        """Persist conversation DNA patterns."""
        CONVO_DIR.mkdir(parents=True, exist_ok=True)
        payload = {k: asdict(v) for k, v in self.dna_patterns.items()}
        DNA_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ------ Reply Analysis ------

    def analyze_reply(
        self,
        reply_text: str,
        parent_text: str = "",
        author_handle: Optional[str] = None,
    ) -> ReplyAnalysis:
        """Analyze a reply draft for effectiveness.

        Args:
            reply_text: The proposed reply text
            parent_text: The tweet being replied to
            author_handle: Who we're replying to

        Returns:
            ReplyAnalysis with hook type, strengths, weaknesses, suggestions
        """
        hook = classify_hook(reply_text)
        structure = classify_structure(reply_text)
        tone = self._detect_tone(reply_text)

        strengths = []
        weaknesses = []
        suggestions = []

        # Length check
        if len(reply_text) > 280:
            weaknesses.append("Exceeds 280 character limit")
            suggestions.append("Trim to fit tweet length")

        # Hook analysis
        if hook == "question":
            strengths.append("Questions invite responses")
        elif hook == "challenge":
            if author_handle:
                warmth = self.x_voice.get_user_warmth(author_handle)
                if warmth in ("cold", "cool"):
                    weaknesses.append("Challenge hook with cold user - risky")
                    suggestions.append("Consider observation or question hook for cold users")
                else:
                    strengths.append("Challenge hook with warm user can deepen connection")

        # Structure analysis
        if structure == "short":
            strengths.append("Concise replies get more reads")
        elif structure == "long":
            weaknesses.append("Long replies may get skipped")
            suggestions.append("Consider splitting into shorter, punchier reply")

        # Tone-content match
        if parent_text:
            parent_is_technical = any(
                w in parent_text.lower()
                for w in ["code", "api", "debug", "deploy", "architecture"]
            )
            if parent_is_technical and tone == "witty":
                suggestions.append("Technical parent tweet may respond better to technical tone")

        # Estimate engagement
        estimated = self._estimate_engagement(hook, tone, structure, author_handle)

        return ReplyAnalysis(
            hook_type=hook,
            tone=tone,
            estimated_engagement=estimated,
            strengths=strengths,
            weaknesses=weaknesses,
            suggestions=suggestions,
        )

    def _detect_tone(self, text: str) -> str:
        """Detect the tone of a reply."""
        text_lower = text.lower()

        # Score each tone by marker presence
        scores: Dict[str, int] = {}
        for tone_name, profile in TONE_PROFILES.items():
            score = 0
            for marker in profile.tone_markers:
                marker_words = marker.lower().split()
                if any(w in text_lower for w in marker_words):
                    score += 1
            scores[tone_name] = score

        if not any(scores.values()):
            return "conversational"

        return max(scores, key=scores.get)

    def _estimate_engagement(
        self,
        hook: str,
        tone: str,
        structure: str,
        author_handle: Optional[str] = None,
    ) -> float:
        """Estimate engagement score (0-10) based on learned patterns."""
        base = 4.0

        # Hook bonuses (from general social patterns)
        hook_bonus = {
            "question": 1.5,
            "observation": 1.0,
            "challenge": 0.8,
            "agreement": 0.5,
            "addition": 0.7,
        }
        base += hook_bonus.get(hook, 0)

        # Structure bonus
        if structure == "short":
            base += 0.5
        elif structure == "long":
            base -= 0.5

        # DNA pattern bonus: if we have a matching DNA, boost confidence
        for dna in self.dna_patterns.values():
            if dna.hook_type == hook and dna.tone == tone:
                pattern_boost = min(1.5, dna.engagement_score / 10.0 * dna.times_seen * 0.3)
                base += pattern_boost
                break

        # Warmth bonus
        if author_handle:
            warmth = self.x_voice.get_user_warmth(author_handle)
            warmth_bonus = {
                "cold": -0.5,
                "cool": 0.0,
                "warm": 0.5,
                "hot": 1.0,
                "ally": 1.5,
            }
            base += warmth_bonus.get(warmth, 0)

        return round(max(0, min(10, base)), 1)

    # ------ DNA Extraction ------

    def extract_dna(
        self,
        reply_text: str,
        engagement_score: float,
        parent_text: str = "",
        topic_tags: Optional[List[str]] = None,
    ) -> Optional[ConversationDNA]:
        """Extract conversation DNA from a reply.

        Only extracts from replies with meaningful engagement.

        Args:
            reply_text: The reply content
            engagement_score: How well it performed (0-10)
            parent_text: The parent tweet text
            topic_tags: Tags for the conversation topic

        Returns:
            ConversationDNA if engagement was high enough, else None
        """
        if engagement_score < 3.0:
            return None  # Not interesting enough to learn from

        hook = classify_hook(reply_text)
        tone = self._detect_tone(reply_text)
        structure = classify_structure(reply_text)

        # Determine pattern type from conversation dynamics
        pattern_type = self._infer_pattern_type(hook, reply_text, parent_text)

        dna_key = f"{pattern_type}_{hook}_{tone}"

        if dna_key in self.dna_patterns:
            # Strengthen existing pattern
            existing = self.dna_patterns[dna_key]
            existing.times_seen += 1
            existing.engagement_score = (
                existing.engagement_score * 0.7 + engagement_score * 0.3
            )
            existing.last_seen = datetime.now().isoformat()
            if reply_text not in existing.examples and len(existing.examples) < 5:
                existing.examples.append(reply_text[:200])
        else:
            # New DNA pattern
            self.dna_patterns[dna_key] = ConversationDNA(
                pattern_type=pattern_type,
                hook_type=hook,
                tone=tone,
                structure=structure,
                engagement_score=engagement_score,
                examples=[reply_text[:200]],
                topic_tags=topic_tags or [],
            )

        self._save_dna()
        return self.dna_patterns[dna_key]

    def _infer_pattern_type(
        self, hook: str, reply_text: str, parent_text: str
    ) -> str:
        """Infer the conversation pattern type."""
        if hook == "question":
            return "question_chain"
        elif hook == "challenge":
            return "debate"
        elif hook in ("agreement", "addition"):
            return "build_together"
        return "hook_and_expand"

    # ------ Hook Recommendations ------

    def get_best_hook(
        self,
        parent_text: str,
        author_handle: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> HookRecommendation:
        """Recommend the best hook for a conversation context.

        Args:
            parent_text: The tweet to reply to
            author_handle: Who wrote it
            topic: Topic of the conversation

        Returns:
            HookRecommendation with type, tone, and reasoning
        """
        # Determine context
        is_technical = any(
            w in parent_text.lower()
            for w in ["code", "api", "build", "architecture", "deploy", "debug"]
        )
        is_question = "?" in parent_text
        is_opinion = any(
            w in parent_text.lower()
            for w in ["think", "believe", "opinion", "take", "hot take"]
        )

        # Get warmth level
        warmth = "cold"
        if author_handle:
            warmth = self.x_voice.get_user_warmth(author_handle)

        # Select best hook based on context
        if is_question:
            hook_type = "addition"
            tone = "technical" if is_technical else "conversational"
            template = "Direct answer + personal experience"
            reasoning = "Questions want answers, not more questions"
        elif is_opinion and warmth in ("warm", "hot", "ally"):
            hook_type = "challenge"
            tone = "provocative"
            template = "Respectful pushback with reasoning"
            reasoning = "Warm relationships can handle friendly challenges"
        elif is_technical:
            hook_type = "observation"
            tone = "technical"
            template = "Specific observation + concrete example"
            reasoning = "Technical content rewards precise engagement"
        elif warmth == "cold":
            hook_type = "question"
            tone = "conversational"
            template = "Genuine curiosity about their experience"
            reasoning = "Questions are the safest opener for new relationships"
        else:
            hook_type = "observation"
            tone = "witty"
            template = "Interesting connection or unexpected angle"
            reasoning = "Default: be interesting without being pushy"

        # Check DNA patterns for learned improvements
        confidence = 0.5
        based_on = None
        for dna_key, dna in self.dna_patterns.items():
            if dna.hook_type == hook_type and dna.tone == tone:
                if dna.engagement_score > 5.0 and dna.times_seen >= 2:
                    confidence = min(0.95, 0.5 + dna.times_seen * 0.1)
                    based_on = dna_key
                    break

        return HookRecommendation(
            hook_type=hook_type,
            tone=tone,
            template=template,
            reasoning=reasoning,
            confidence=confidence,
            based_on_dna=based_on,
        )

    # ------ Reply Scoring ------

    def score_reply_draft(
        self,
        draft: str,
        parent_text: str,
        author_handle: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Score a reply draft and return detailed feedback.

        Args:
            draft: The proposed reply
            parent_text: What we're replying to
            author_handle: Who wrote the parent

        Returns:
            Dict with score, analysis, and recommendation
        """
        analysis = self.analyze_reply(draft, parent_text, author_handle)
        recommendation = self.get_best_hook(parent_text, author_handle)

        # Calculate overall score
        score = analysis.estimated_engagement

        # Bonus for matching recommended hook
        if analysis.hook_type == recommendation.hook_type:
            score += 0.5

        # Penalty for weaknesses
        score -= len(analysis.weaknesses) * 0.5

        return {
            "score": round(max(0, min(10, score)), 1),
            "analysis": asdict(analysis),
            "recommendation": asdict(recommendation),
            "verdict": (
                "strong"
                if score >= 7
                else "good" if score >= 5 else "weak" if score >= 3 else "rethink"
            ),
        }

    # ------ High-Engagement Study ------

    def study_reply(
        self,
        reply_text: str,
        engagement: Dict[str, int],
        parent_text: str = "",
        topic_tags: Optional[List[str]] = None,
    ) -> Optional[ConversationDNA]:
        """Study a high-engagement reply (from anyone) for patterns.

        Args:
            reply_text: The reply content
            engagement: Dict with likes, replies, retweets
            parent_text: The parent tweet
            topic_tags: Topic tags

        Returns:
            Extracted DNA if the reply was worth learning from
        """
        # Calculate engagement score (0-10)
        likes = engagement.get("likes", 0)
        replies = engagement.get("replies", 0)
        retweets = engagement.get("retweets", 0)

        engagement_score = min(
            10.0,
            (likes * 0.3 + replies * 1.0 + retweets * 0.5),
        )

        return self.extract_dna(
            reply_text, engagement_score, parent_text, topic_tags
        )

    # ------ Logging ------

    def log_reply(
        self,
        reply_text: str,
        parent_text: str,
        author_handle: str,
        tone_used: str,
        hook_type: str,
    ) -> None:
        """Log a sent reply for later outcome tracking."""
        CONVO_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "reply_text": reply_text[:280],
            "parent_text": parent_text[:280],
            "author_handle": author_handle,
            "tone_used": tone_used,
            "hook_type": hook_type,
        }
        with REPLY_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ------ Stats ------

    def get_stats(self) -> Dict[str, Any]:
        """Get ConvoIQ statistics."""
        dna_by_type = {}
        for dna in self.dna_patterns.values():
            dna_by_type[dna.pattern_type] = dna_by_type.get(dna.pattern_type, 0) + 1

        avg_engagement = 0.0
        if self.dna_patterns:
            avg_engagement = sum(
                d.engagement_score for d in self.dna_patterns.values()
            ) / len(self.dna_patterns)

        reply_count = 0
        if REPLY_LOG.exists():
            try:
                reply_count = sum(
                    1 for line in REPLY_LOG.read_text(encoding="utf-8").splitlines() if line.strip()
                )
            except Exception:
                pass

        return {
            "dna_patterns": len(self.dna_patterns),
            "dna_by_type": dna_by_type,
            "avg_dna_engagement": round(avg_engagement, 1),
            "replies_logged": reply_count,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_analyzer: Optional[ConvoAnalyzer] = None


def get_convo_analyzer() -> ConvoAnalyzer:
    """Get the singleton ConvoAnalyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = ConvoAnalyzer()
    return _analyzer
