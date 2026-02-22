"""Cognitive signal extraction from text content.

Detects user preferences, decisions, corrections, reasoning patterns,
and domain context from user messages and code content.  Routes high-value
signals through Meta-Ralph for quality filtering before storage.

Moved from hooks/observe.py so that lib modules (bridge_cycle, etc.) can
import it without a backwards cross-layer dependency on the hooks package.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from lib.diagnostics import log_debug
from lib.cognitive_learner import get_cognitive_learner


# ===== Domain Detection =====

DOMAIN_TRIGGERS = {
    "game_dev": [
        "player", "spawn", "physics", "collision", "balance", "gameplay",
        "difficulty", "level", "enemy", "health", "damage", "score",
        "inventory", "quest", "boss", "npc", "animation", "sprite",
        "tilemap", "hitbox", "frame rate", "fps", "game loop", "state machine",
    ],
    "fintech": [
        "payment", "transaction", "compliance", "risk", "audit", "kyc", "aml",
        "pci", "ledger", "settlement", "clearing", "fraud", "reconciliation",
        "banking", "wallet", "transfer", "fee", "interest", "loan", "credit",
    ],
    "marketing": [
        "audience", "campaign", "conversion", "roi", "funnel", "messaging",
        "channel", "brand", "engagement", "ctr", "impression", "retention",
        "acquisition", "segmentation", "persona", "content", "seo", "ad",
    ],
    "product": [
        "user", "feature", "feedback", "priority", "roadmap", "mvp",
        "backlog", "sprint", "story", "epic", "milestone", "release",
        "launch", "metric", "kpi", "adoption", "onboarding",
    ],
    "orchestration": [
        "workflow", "pipeline", "sequence", "parallel", "coordination",
        "handoff", "trigger", "event", "queue", "scheduler", "cron",
        "dag", "task", "step", "stage", "job", "batch",
    ],
    "architecture": [
        "pattern", "tradeoff", "scalability", "coupling", "interface",
        "abstraction", "modularity", "layer", "microservice", "monolith",
        "api", "contract", "schema", "migration", "refactor", "decouple",
    ],
    "agent_coordination": [
        "agent", "capability", "routing", "specialization", "collaboration",
        "escalation", "delegation", "context", "prompt", "chain", "tool",
        "memory", "reasoning", "planning", "retrieval", "rag",
    ],
    "team_management": [
        "delegation", "blocker", "review", "sprint", "standup", "retro",
        "pr", "merge", "conflict", "branch", "deploy", "release",
        "oncall", "incident", "postmortem",
    ],
    "ui_ux": [
        "layout", "component", "responsive", "accessibility", "a11y",
        "interaction", "animation", "modal", "form", "validation",
        "navigation", "menu", "button", "input", "dropdown", "theme",
        "dark mode", "mobile", "tablet", "desktop", "breakpoint",
    ],
    "debugging": [
        "error", "trace", "root cause", "hypothesis", "reproduce",
        "bisect", "isolate", "stacktrace", "breakpoint", "log",
        "assert", "crash", "exception", "bug", "regression", "flaky",
    ],
}


def detect_domain(text: str) -> Optional[str]:
    """Detect the domain from text content.

    Returns the domain with most trigger matches, or None if no clear match.
    """
    if not text:
        return None

    text_lower = text.lower()
    domain_scores = {}

    for domain, triggers in DOMAIN_TRIGGERS.items():
        score = sum(1 for t in triggers if t in text_lower)
        if score > 0:
            domain_scores[domain] = score

    if not domain_scores:
        return None

    return max(domain_scores, key=domain_scores.get)


def _build_advisory_quality(text: str, source: str, confidence: float) -> Dict[str, Any]:
    """Derive advisory metadata for user-sourced learnings."""
    try:
        from .distillation_transformer import transform_for_advisory

        return transform_for_advisory(
            text,
            source=source or "user_prompt",
            reliability=confidence,
        ).to_dict()
    except Exception:
        return {}


# ===== Cognitive Signal Patterns =====

COGNITIVE_PATTERNS = {
    "remember": [
        r"remember (this|that)",
        r"don't forget",
        r"important:",
        r"note:",
        r"always remember",
        r"keep in mind",
    ],
    "preference": [
        r"i (prefer|like|want|love|hate)",
        r"(prefer|like|want) (to |the )?",
        r"my preference",
        r"i'd rather",
    ],
    "decision": [
        r"(i |we |let's )(decided?|chose?|choosing|went with)",
        r"instead of",
        r"rather than",
        r"switched to",
        r"going with",
    ],
    "correction": [
        r"(no|not|wrong|incorrect|actually)",
        r"i meant",
        r"that's not",
        r"should be",
        r"fix that",
    ],
    "reasoning": [
        r"because",
        r"the reason",
        r"since",
        r"so that",
        r"in order to",
    ],
}


def extract_cognitive_signals(text: str, session_id: str, trace_id: Optional[str] = None, source: str = "") -> None:
    """Extract cognitive signals from user messages and route to Meta-Ralph.

    Uses three scoring systems:
    1. Domain detection (context-aware learning)
    2. Pattern-based signal detection (fast)
    3. Importance scorer (semantic, more accurate)

    This is where we capture the GOOD stuff:
    - User preferences
    - Explicit decisions
    - Corrections/feedback
    - Reasoned statements
    """
    if not text or len(text) < 10:
        return

    # Ignore synthetic pipeline test prompts. They are useful for validating
    # ingestion, but they are not user learnings and they pollute Meta-Ralph
    # quality-band metrics.
    if "[PIPELINE_TEST" in text:
        return

    text_lower = text.lower()
    signals_found = []

    # Detect domain for context-aware learning
    detected_domain = detect_domain(text)

    # Also use importance scorer for semantic analysis (with domain context)
    importance_score = None
    try:
        from lib.importance_scorer import get_importance_scorer
        scorer = get_importance_scorer(domain=detected_domain)
        importance_result = scorer.score(text)
        importance_score = importance_result.score

        if importance_score >= 0.5:
            signals_found.extend(importance_result.signals_detected)
    except Exception as e:
        log_debug("cognitive_signals", "importance scorer failed", e)

    # Check each pattern category
    for category, patterns in COGNITIVE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                signals_found.append(category)
                break

    def _derive_candidate(raw: str, signals: list[str]) -> Optional[str]:
        """Derive a learning candidate from a raw user prompt.

        Meta-Ralph is a quality gate for learnings, not a classifier for arbitrary chat text.
        We try to extract the sentence/claim most likely to be a durable learning.
        """
        raw = (raw or "").strip()
        if not raw:
            return None

        sigset = set(signals or [])

        # Only "remember" without any structure tends to be non-actionable.
        if sigset == {"remember"}:
            m = re.search(r"remember\\s*:\\s*(.+)$", raw, flags=re.IGNORECASE)
            if not m:
                return None
            candidate = m.group(1).strip()
            if not re.search(r"\\b(when|because|avoid|instead|must|should|always|never)\\b", candidate, flags=re.IGNORECASE):
                return None
            return candidate[:500]

        # Prefer the first sentence with stronger learning signals.
        parts = re.split(r"[\\n\\.\\!\\?]+", raw)
        parts = [p.strip() for p in parts if p.strip()]
        for p in parts:
            if re.search(r"\\b(because|avoid|instead of|prefer|never|always|should|must)\\b", p, flags=re.IGNORECASE):
                return p[:500]
            if re.search(r"\\bwhen\\b.+\\bthen\\b", p, flags=re.IGNORECASE):
                return p[:500]

        return raw[:500]

    # If any cognitive signals found, extract and roast
    if signals_found:
        try:
            from lib.meta_ralph import get_meta_ralph

            ralph = get_meta_ralph()
            learning = _derive_candidate(text, signals_found)
            if not learning:
                return

            result = ralph.roast(
                learning,
                source="user_prompt",
                context={
                    "signals": signals_found,
                    "session_id": session_id,
                    "trace_id": trace_id,
                    "importance_score": importance_score,
                    "is_priority": importance_score and importance_score >= 0.7,
                    "domain": detected_domain,
                }
            )

            if result.verdict.value == "quality":
                log_debug("cognitive_signals", f"CAPTURED: [{signals_found}] {text[:50]}...", None)

            from lib.cognitive_learner import CognitiveCategory
            category = CognitiveCategory.USER_UNDERSTANDING  # default

            if "preference" in signals_found:
                category = CognitiveCategory.USER_UNDERSTANDING
            elif "decision" in signals_found:
                category = CognitiveCategory.REASONING
            elif "reasoning" in signals_found:
                category = CognitiveCategory.REASONING
            elif "correction" in signals_found:
                category = CognitiveCategory.CONTEXT
            elif "remember" in signals_found:
                category = CognitiveCategory.WISDOM

            cognitive = get_cognitive_learner()
            domain_ctx = f", domain: {detected_domain}" if detected_domain else ""
            confidence = 0.7 + (importance_score * 0.2 if importance_score else 0)
            advisory_quality = _build_advisory_quality(
                learning,
                source=(source or "user_prompt"),
                confidence=confidence,
            )
            stored = cognitive.add_insight(
                category=category,
                insight=learning,
                context=f"signals: {signals_found}, session: {session_id}{domain_ctx}",
                confidence=confidence,
                source=source,
                advisory_quality=advisory_quality,
            )

            if stored:
                log_debug("cognitive_signals", f"STORED: {category.value} - {learning[:40]}...", None)

        except Exception as e:
            log_debug("cognitive_signals", "cognitive extraction failed", e)
