"""
Importance Scorer: The intelligence foundation for deciding what's worth learning.

This module addresses the core problem: Spark was deciding importance at PROMOTION time,
not at INGESTION time. Critical one-time insights were lost because they didn't repeat.

The Test: Would a human find this useful to know next time?

Key Principles:
1. Importance != Frequency (critical insights may appear once)
2. Domain context affects importance (game balance matters in game_dev, not in fintech)
3. First-mention elevation (some signals are immediately valuable)
4. Question-guided capture (onboarding questions define what matters)
5. Outcome-linked importance (insights tied to outcomes are more valuable)

Intelligence Layers:
1. Rule-based signals (fast, pattern matching)
2. Semantic similarity (embeddings, compare to known-valuable insights)
3. Outcome feedback (learn from importance prediction errors)

Importance Tiers:
- CRITICAL (0.9+): Must learn immediately (user explicit request, correction, domain decision)
- HIGH (0.7-0.9): Should learn (preferences, reasoning, principles)
- MEDIUM (0.5-0.7): Consider learning (patterns, context, observations)
- LOW (0.3-0.5): Store but don't promote (weak signals, noise)
- IGNORE (<0.3): Don't store (primitive, operational, trivial)
"""

from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import json


class ImportanceTier(Enum):
    """Importance tiers for incoming information."""
    CRITICAL = "critical"  # 0.9+ - Must learn immediately
    HIGH = "high"          # 0.7-0.9 - Should learn
    MEDIUM = "medium"      # 0.5-0.7 - Consider learning
    LOW = "low"            # 0.3-0.5 - Store but don't promote
    IGNORE = "ignore"      # <0.3 - Don't store


@dataclass
class ImportanceScore:
    """Result of importance scoring."""
    score: float  # 0.0 to 1.0
    tier: ImportanceTier
    reasons: List[str] = field(default_factory=list)
    signals_detected: List[str] = field(default_factory=list)
    domain_relevance: float = 0.5  # How relevant to active domain
    first_mention_elevation: bool = False
    question_match: Optional[str] = None  # Which onboarding question this answers

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "tier": self.tier.value,
            "reasons": self.reasons,
            "signals_detected": self.signals_detected,
            "domain_relevance": self.domain_relevance,
            "first_mention_elevation": self.first_mention_elevation,
            "question_match": self.question_match,
        }


# =============================================================================
# HIGH-VALUE SIGNAL PATTERNS
# =============================================================================

# Signals that indicate CRITICAL importance (immediate learning)
CRITICAL_SIGNALS = [
    # Explicit learning requests
    (r"\bremember\s+(?:this|that)\b", "explicit_remember"),
    (r"\bremember:\s", "explicit_remember_colon"),  # "REMEMBER: ..."
    (r"\bcorrection:\s", "explicit_correction"),    # "CORRECTION: ..."
    (r"\bprinciple:\s", "explicit_principle"),      # "PRINCIPLE: ..."
    (r"\binsight:\s", "explicit_insight"),          # "INSIGHT: ..."
    (r"\bbalance:\s", "explicit_balance"),          # "BALANCE: ..."
    (r"\balways\s+do\s+(?:it\s+)?this\s+way\b", "explicit_preference"),
    (r"\bnever\s+do\s+(?:it\s+)?this\s+way\b", "explicit_prohibition"),
    (r"\bthis\s+is\s+(?:very\s+)?important\b", "importance_flag"),
    (r"\bdon'?t\s+forget\b", "dont_forget"),
    (r"\bcritical\b", "critical_flag"),

    # User corrections (high signal)
    (r"\bno[,.]?\s+(?:I\s+)?(?:meant|want|need|said)\b", "correction"),
    (r"\bthat'?s\s+(?:not\s+)?(?:wrong|incorrect)\b", "correction"),
    (r"\binstead[,]?\s+(?:do|use|try)\b", "redirect"),

    # Domain decisions with reasoning
    (r"\bbecause\s+(?:this|it|we)\b.*\bwork", "reasoned_decision"),
    (r"\bthe\s+reason\s+(?:is|why)\b", "explicit_reasoning"),
    (r"\bthis\s+(?:works|worked)\s+because\b", "outcome_with_reason"),
]

# Signals that indicate HIGH importance
HIGH_SIGNALS = [
    # Preferences
    (r"\bi\s+(?:prefer|like|want)\b", "preference"),
    (r"\blet'?s\s+(?:go\s+with|use|try)\b", "preference"),
    (r"\bswitch\s+to\b", "preference"),
    (r"\brather\s+than\b", "comparative_preference"),

    # Principles and wisdom
    (r"\bthe\s+(?:key|trick|secret)\s+is\b", "principle"),
    (r"\bthe\s+pattern\s+(?:here\s+)?is\b", "pattern_recognition"),
    (r"\bin\s+general[,]?\b", "generalization"),
    (r"\busually[,]?\b", "generalization"),

    # Domain-specific decisions
    (r"\bbalance\b.*\b(?:at|to|is)\b", "balance_decision"),
    (r"\bset\s+(?:it|this)\s+to\b", "config_decision"),
    (r"\bchoose\b.*\bover\b", "tradeoff_decision"),

    # Learning cues
    (r"\blearned\s+that\b", "explicit_learning"),
    (r"\brealized\s+that\b", "realization"),
    (r"\bturns\s+out\b", "discovery"),
]

# Signals that indicate MEDIUM importance
MEDIUM_SIGNALS = [
    # Observations
    (r"\bi\s+(?:noticed|notice)\b", "observation"),
    (r"\bit\s+(?:seems|looks)\s+like\b", "observation"),
    (r"\binteresting(?:ly)?\b", "observation"),

    # Context
    (r"\bwhen\s+(?:you|we|I)\b", "contextual"),
    (r"\bif\s+(?:you|we|I)\b", "conditional"),
    (r"\bin\s+this\s+(?:case|scenario)\b", "contextual"),

    # Weak preferences
    (r"\bmaybe\s+(?:we\s+)?(?:should|could)\b", "weak_preference"),
    (r"\bmight\s+be\s+better\b", "weak_preference"),
]

# Signals that indicate LOW importance (noise indicators)
LOW_SIGNALS = [
    # Primitive/operational
    (r"\b(?:Read|Edit|Bash|Glob|Grep)\s*(?:->|→)", "tool_sequence"),
    (r"\b\d+%?\s*(?:success|fail)", "metric"),
    (r"\btimeout\b", "operational"),
    (r"\berror\s+rate\b", "metric"),

    # Trivial
    (r"\bokay\b", "acknowledgment"),
    (r"\balright\b", "acknowledgment"),
    (r"\bgot\s+it\b", "acknowledgment"),
    (r"\bthanks?\b", "acknowledgment"),
]

# Signals that indicate telemetry/operational noise to ignore entirely
TELEMETRY_SIGNALS = [
    r"\b(?:read|edit|bash|write|glob|grep)\b\s*(?:->)\b",  # tool sequence arrows
    r"\bsequence\b.*\bworked\b",
    r"\bpattern\b.*->",
    r"\bheavy\s+\w+\s+usage\b",
    r"\busage\s*\(\d+\s*calls?\)",
    r"^user was satisfied after:",
    r"^user frustrated after:",
]


# =============================================================================
# DOMAIN-SPECIFIC IMPORTANCE WEIGHTS
# =============================================================================

DOMAIN_WEIGHTS = {
    "game_dev": {
        "balance": 1.5,
        "feel": 1.5,
        "gameplay": 1.4,
        "physics": 1.3,
        "collision": 1.2,
        "spawn": 1.2,
        "difficulty": 1.3,
        "player": 1.3,
    },
    "fintech": {
        "compliance": 1.5,
        "security": 1.5,
        "transaction": 1.4,
        "risk": 1.4,
        "audit": 1.3,
        "validation": 1.3,
    },
    "marketing": {
        "audience": 1.5,
        "conversion": 1.5,
        "messaging": 1.4,
        "channel": 1.3,
        "campaign": 1.3,
        "roi": 1.4,
    },
    "product": {
        "user": 1.5,
        "feature": 1.4,
        "feedback": 1.4,
        "priority": 1.3,
        "roadmap": 1.3,
    },
    # New domains for comprehensive skill learning
    "orchestration": {
        "workflow": 1.5,
        "pipeline": 1.5,
        "sequence": 1.4,
        "parallel": 1.4,
        "coordination": 1.4,
        "handoff": 1.3,
        "trigger": 1.3,
        "batch": 1.3,  # Added for Improvement #9
        "job": 1.3,
        "queue": 1.3,
        "scheduler": 1.4,
    },
    "ui_ux": {
        "layout": 1.5,
        "component": 1.4,
        "responsive": 1.4,
        "accessibility": 1.5,
        "user flow": 1.4,
        "interaction": 1.3,
        "animation": 1.2,
    },
    "team_management": {
        "delegation": 1.5,
        "blocker": 1.5,
        "handoff": 1.4,
        "review": 1.4,
        "sprint": 1.3,
        "standup": 1.2,
        "retrospective": 1.3,
    },
    "agent_coordination": {
        "agent": 1.5,
        "capability": 1.4,
        "routing": 1.4,
        "context": 1.4,
        "specialization": 1.3,
        "collaboration": 1.4,
        "escalation": 1.3,
    },
    "debugging": {
        "error": 1.4,
        "trace": 1.4,
        "root cause": 1.5,
        "hypothesis": 1.5,
        "reproduce": 1.4,
        "bisect": 1.3,
        "isolate": 1.4,
    },
    "architecture": {
        "pattern": 1.4,
        "tradeoff": 1.5,
        "scalability": 1.4,
        "coupling": 1.4,
        "decouple": 1.4,  # Added for Improvement #9
        "interface": 1.3,
        "abstraction": 1.3,
        "modularity": 1.4,
        "layer": 1.3,
        "microservice": 1.4,
    },
}

# Default domain weights (applies to all domains)
DEFAULT_WEIGHTS = {
    "user": 1.3,
    "preference": 1.4,
    "decision": 1.3,
    "principle": 1.3,
    "style": 1.2,
}


# =============================================================================
# QUESTION-GUIDED IMPORTANCE
# =============================================================================

# These map onboarding questions to content patterns
# Updated for Improvement #6: Comprehensive domain detection
QUESTION_PATTERNS = {
    "domain": [
        # Game development
        (r"\b(?:game|gaming|player|spawn|collision|physics|gameplay|enemy|health|damage|score)\b", "game_dev"),
        # Fintech
        (r"\b(?:finance|fintech|banking|payment|transaction|compliance|risk|kyc|aml|ledger)\b", "fintech"),
        # Marketing
        (r"\b(?:market|campaign|audience|conversion|roi|funnel|messaging|channel|brand|engagement)\b", "marketing"),
        # Product
        (r"\b(?:product|feature|feedback|roadmap|mvp|backlog|sprint|story|epic|release)\b", "product"),
        # Orchestration
        (r"\b(?:workflow|pipeline|sequence|parallel|coordination|handoff|trigger|queue|scheduler|dag)\b", "orchestration"),
        # Architecture
        (r"\b(?:architecture|pattern|tradeoff|scalability|coupling|interface|abstraction|modularity|microservice)\b", "architecture"),
        # Agent coordination
        (r"\b(?:agent|capability|routing|specialization|collaboration|escalation|prompt|chain|rag|memory)\b", "agent_coordination"),
        # Team management
        (r"\b(?:delegation|blocker|review|standup|retro|oncall|incident|postmortem)\b", "team_management"),
        # UI/UX
        (r"\b(?:layout|component|responsive|accessibility|a11y|interaction|animation|modal|form|navigation)\b", "ui_ux"),
        # Debugging
        (r"\b(?:debug|error|trace|root cause|hypothesis|reproduce|bisect|isolate|stacktrace|breakpoint|crash|exception|bug|regression)\b", "debugging"),
    ],
    "success": [
        (r"\bsuccess\s+(?:means|is|looks)\b", 1.5),
        (r"\bgoal\s+is\b", 1.4),
        (r"\bwant\s+to\s+achieve\b", 1.4),
    ],
    "focus": [
        (r"\bpay\s+attention\s+to\b", 1.5),
        (r"\bfocus\s+on\b", 1.4),
        (r"\bprioritize\b", 1.4),
    ],
    "avoid": [
        (r"\bavoid\b", 1.5),
        (r"\bdon'?t\s+want\b", 1.4),
        (r"\bmistake\b", 1.4),
    ],
}


class ImportanceScorer:
    """
    Scores incoming information for learning importance.

    This is the intelligence foundation that decides what's worth learning
    at INGESTION time, not at PROMOTION time.
    """

    def __init__(self, active_domain: Optional[str] = None) -> None:
        self.active_domain = active_domain
        self.seen_signals: Set[str] = set()  # Track first-mention
        self._load_question_context()

    def _load_question_context(self) -> None:
        """Load answered onboarding questions for guidance."""
        self.question_answers: Dict[str, str] = {}
        answers_file = Path.home() / ".spark" / "project_answers.json"
        if answers_file.exists():
            try:
                self.question_answers = json.loads(answers_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    def _detect_domain(self, text: str) -> Optional[str]:
        """Auto-detect domain from text if not set."""
        text_lower = text.lower()
        for pattern, domain in QUESTION_PATTERNS.get("domain", []):
            if re.search(pattern, text_lower, re.I):
                return domain
        return None

    def _calculate_domain_relevance(self, text: str) -> float:
        """Calculate how relevant text is to active domain."""
        if not self.active_domain:
            # Try to detect domain
            detected = self._detect_domain(text)
            if detected:
                self.active_domain = detected

        if not self.active_domain:
            return 0.5  # Neutral

        text_lower = text.lower()
        weights = DOMAIN_WEIGHTS.get(self.active_domain, {})
        weights.update(DEFAULT_WEIGHTS)

        max_relevance = 0.5
        for keyword, weight in weights.items():
            if keyword in text_lower:
                max_relevance = max(max_relevance, weight / 1.5)  # Normalize to 0-1

        return min(1.0, max_relevance)

    def _check_question_match(self, text: str) -> Tuple[Optional[str], float]:
        """Check if text answers an onboarding question."""
        text_lower = text.lower()

        for question_id, patterns in QUESTION_PATTERNS.items():
            if question_id == "domain":
                continue  # Handled separately
            for pattern, boost in patterns:
                if re.search(pattern, text_lower, re.I):
                    return question_id, boost

        return None, 1.0

    def _detect_signals(self, text: str) -> Tuple[List[str], float, ImportanceTier]:
        """Detect importance signals in text."""
        text_lower = text.lower() if text else ""
        signals = []
        base_score = 0.5
        tier = ImportanceTier.MEDIUM

        for pattern in TELEMETRY_SIGNALS:
            if re.search(pattern, text_lower, re.I):
                signals.append("ignore:telemetry")
                return signals, 0.0, ImportanceTier.IGNORE

        # Check CRITICAL signals
        for pattern, signal_name in CRITICAL_SIGNALS:
            if re.search(pattern, text_lower, re.I):
                signals.append(f"critical:{signal_name}")
                base_score = max(base_score, 0.9)
                tier = ImportanceTier.CRITICAL

        # Check HIGH signals (only if not already critical)
        if tier != ImportanceTier.CRITICAL:
            for pattern, signal_name in HIGH_SIGNALS:
                if re.search(pattern, text_lower, re.I):
                    signals.append(f"high:{signal_name}")
                    base_score = max(base_score, 0.75)
                    if tier != ImportanceTier.CRITICAL:
                        tier = ImportanceTier.HIGH

        # Check MEDIUM signals
        for pattern, signal_name in MEDIUM_SIGNALS:
            if re.search(pattern, text_lower, re.I):
                signals.append(f"medium:{signal_name}")
                if tier == ImportanceTier.IGNORE or tier == ImportanceTier.LOW:
                    base_score = max(base_score, 0.55)
                    tier = ImportanceTier.MEDIUM

        # Check LOW signals (noise indicators)
        low_count = 0
        for pattern, signal_name in LOW_SIGNALS:
            if re.search(pattern, text_lower, re.I):
                signals.append(f"low:{signal_name}")
                low_count += 1

        # Heavy noise presence drops importance
        if low_count >= 2 and tier not in (ImportanceTier.CRITICAL, ImportanceTier.HIGH):
            base_score = min(base_score, 0.4)
            tier = ImportanceTier.LOW

        return signals, base_score, tier

    def _check_first_mention(self, text: str, signals: List[str]) -> bool:
        """Check if this is a first-mention high-value signal."""
        # Create a normalized key from the text
        text_key = re.sub(r"\W+", " ", text.lower().strip())[:100]

        # Check if any high-value signals are first-time
        high_signals = [s for s in signals if s.startswith(("critical:", "high:"))]

        if high_signals:
            signal_key = f"{text_key}:{','.join(sorted(high_signals))}"
            if signal_key not in self.seen_signals:
                self.seen_signals.add(signal_key)
                # Trim seen signals if too large
                if len(self.seen_signals) > 1000:
                    self.seen_signals = set(list(self.seen_signals)[-500:])
                return True

        return False

    def score(self, text: str, context: Optional[Dict[str, Any]] = None) -> ImportanceScore:
        """
        Score the importance of incoming information.

        Args:
            text: The text to score
            context: Optional context (source, domain, session, etc.)

        Returns:
            ImportanceScore with score, tier, and reasons
        """
        if not text or not text.strip():
            return ImportanceScore(
                score=0.0,
                tier=ImportanceTier.IGNORE,
                reasons=["empty_text"],
            )

        context = context or {}
        reasons = []

        # 1. Detect signals
        signals, base_score, tier = self._detect_signals(text)

        # 2. Calculate domain relevance
        domain_relevance = self._calculate_domain_relevance(text)
        if domain_relevance > 0.6:
            base_score = min(1.0, base_score * 1.1)
            reasons.append(f"domain_relevant:{self.active_domain}")

        # 3. Check question match
        question_match, question_boost = self._check_question_match(text)
        if question_match:
            base_score = min(1.0, base_score * question_boost)
            reasons.append(f"answers_question:{question_match}")

        # 4. First-mention elevation
        first_mention = self._check_first_mention(text, signals)
        if first_mention and tier in (ImportanceTier.HIGH, ImportanceTier.CRITICAL):
            base_score = min(1.0, base_score + 0.1)
            reasons.append("first_mention_elevation")

        # 5. Context boosts
        if context.get("source") == "user_correction":
            base_score = min(1.0, base_score + 0.15)
            tier = ImportanceTier.CRITICAL if base_score >= 0.9 else ImportanceTier.HIGH
            reasons.append("user_correction_source")

        if context.get("has_outcome"):
            base_score = min(1.0, base_score + 0.1)
            reasons.append("outcome_linked")

        # 6. Recalculate tier based on final score
        if base_score >= 0.9:
            tier = ImportanceTier.CRITICAL
        elif base_score >= 0.7:
            tier = ImportanceTier.HIGH
        elif base_score >= 0.5:
            tier = ImportanceTier.MEDIUM
        elif base_score >= 0.3:
            tier = ImportanceTier.LOW
        else:
            tier = ImportanceTier.IGNORE

        return ImportanceScore(
            score=base_score,
            tier=tier,
            reasons=reasons,
            signals_detected=signals,
            domain_relevance=domain_relevance,
            first_mention_elevation=first_mention,
            question_match=question_match,
        )

    def should_learn(self, text: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """Quick check: should we learn from this text?"""
        score = self.score(text, context)
        return score.tier in (ImportanceTier.CRITICAL, ImportanceTier.HIGH, ImportanceTier.MEDIUM)

    def should_promote(self, text: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """Quick check: should this be promoted to CLAUDE.md?"""
        score = self.score(text, context)
        return score.tier in (ImportanceTier.CRITICAL, ImportanceTier.HIGH)

    # =========================================================================
    # SEMANTIC INTELLIGENCE LAYER
    # =========================================================================

    def _init_semantic_intelligence(self) -> None:
        """Initialize semantic intelligence (embeddings + known-valuable insights)."""
        if hasattr(self, "_semantic_initialized"):
            return

        self._semantic_initialized = True
        self._valuable_insights: List[Dict[str, Any]] = []
        self._valuable_embeddings: List[List[float]] = []
        self._feedback_log: List[Dict[str, Any]] = []

        # Load known-valuable insights (high reliability, validated by outcomes)
        try:
            from .cognitive_learner import get_cognitive_learner
            learner = get_cognitive_learner()
            for key, insight in learner.insights.items():
                # Only use insights that have been validated by outcomes
                if insight.times_validated >= 3 and insight.reliability >= 0.7:
                    self._valuable_insights.append({
                        "key": key,
                        "text": insight.insight,
                        "category": insight.category.value,
                        "reliability": insight.reliability,
                    })
        except Exception:
            pass

        # Load feedback log for importance predictions
        feedback_file = Path.home() / ".spark" / "importance_feedback.json"
        if feedback_file.exists():
            try:
                self._feedback_log = json.loads(feedback_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding for text using fastembed."""
        try:
            from .embeddings import embed_text
            return embed_text(text)
        except Exception:
            return None

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def semantic_score(self, text: str) -> Tuple[float, Optional[str]]:
        """
        Score text importance using semantic similarity to known-valuable insights.

        Returns (similarity_score, most_similar_insight_key).
        """
        self._init_semantic_intelligence()

        if not self._valuable_insights:
            return 0.0, None

        text_embedding = self._get_embedding(text)
        if text_embedding is None:
            return 0.0, None

        best_sim = 0.0
        best_key = None

        for insight in self._valuable_insights:
            insight_embedding = self._get_embedding(insight["text"])
            if insight_embedding is None:
                continue

            sim = self._cosine_similarity(text_embedding, insight_embedding)
            # Weight by reliability
            weighted_sim = sim * insight["reliability"]

            if weighted_sim > best_sim:
                best_sim = weighted_sim
                best_key = insight["key"]

        return best_sim, best_key

    def score_with_semantics(self, text: str, context: Optional[Dict[str, Any]] = None) -> ImportanceScore:
        """
        Score importance using both rule-based AND semantic intelligence.

        This is the full intelligent scoring that:
        1. Applies rule-based signal detection
        2. Compares against known-valuable insights (embeddings)
        3. Considers feedback from past predictions
        """
        # Get base rule-based score
        base_result = self.score(text, context)

        # Add semantic layer
        semantic_sim, similar_to = self.semantic_score(text)

        # If semantically similar to a known-valuable insight, boost score
        if semantic_sim > 0.7:
            boost = 0.15 * semantic_sim  # Up to 0.15 boost for high similarity
            new_score = min(1.0, base_result.score + boost)
            base_result.reasons.append(f"semantic_similarity:{semantic_sim:.2f}")
            if similar_to:
                base_result.reasons.append(f"similar_to:{similar_to[:30]}")

            # Recalculate tier
            if new_score >= 0.9:
                base_result.tier = ImportanceTier.CRITICAL
            elif new_score >= 0.7:
                base_result.tier = ImportanceTier.HIGH

            base_result.score = new_score

        return base_result

    def record_feedback(self, text: str, predicted_tier: str, actual_valuable: bool, reason: str = "") -> None:
        """
        Record feedback on an importance prediction.

        This allows the system to learn from its mistakes.
        """
        self._init_semantic_intelligence()

        feedback = {
            "text": text[:200],
            "predicted_tier": predicted_tier,
            "actual_valuable": actual_valuable,
            "correct": (predicted_tier in ("critical", "high") and actual_valuable) or
                       (predicted_tier in ("low", "ignore") and not actual_valuable),
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }

        self._feedback_log.append(feedback)

        # Keep last 1000 feedback entries
        if len(self._feedback_log) > 1000:
            self._feedback_log = self._feedback_log[-1000:]

        # Save feedback
        feedback_file = Path.home() / ".spark" / "importance_feedback.json"
        try:
            feedback_file.parent.mkdir(parents=True, exist_ok=True)
            feedback_file.write_text(json.dumps(self._feedback_log, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get_feedback_stats(self) -> Dict[str, Any]:
        """Get statistics on importance prediction accuracy."""
        self._init_semantic_intelligence()

        if not self._feedback_log:
            return {"total": 0, "accuracy": 0.0}

        correct = sum(1 for f in self._feedback_log if f.get("correct", False))
        total = len(self._feedback_log)

        by_tier = {}
        for f in self._feedback_log:
            tier = f.get("predicted_tier", "unknown")
            if tier not in by_tier:
                by_tier[tier] = {"total": 0, "correct": 0}
            by_tier[tier]["total"] += 1
            if f.get("correct", False):
                by_tier[tier]["correct"] += 1

        return {
            "total": total,
            "correct": correct,
            "accuracy": correct / total if total > 0 else 0.0,
            "by_tier": by_tier,
        }


# =============================================================================
# SINGLETON
# =============================================================================

_scorer: Optional[ImportanceScorer] = None


def get_importance_scorer(domain: Optional[str] = None) -> ImportanceScorer:
    """Get the global importance scorer instance."""
    global _scorer
    if _scorer is None:
        _scorer = ImportanceScorer(active_domain=domain)
    elif domain and _scorer.active_domain != domain:
        _scorer.active_domain = domain
    return _scorer


def score_importance(text: str, context: Optional[Dict[str, Any]] = None) -> ImportanceScore:
    """Convenience function to score text importance."""
    return get_importance_scorer().score(text, context)


def should_learn(text: str, context: Optional[Dict[str, Any]] = None) -> bool:
    """Convenience function to check if text should be learned."""
    return get_importance_scorer().should_learn(text, context)
