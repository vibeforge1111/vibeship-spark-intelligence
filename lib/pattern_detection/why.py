"""
WhyDetector: Captures reasoning, causality, and principles.

HIGH VALUE - This is the missing piece for cognitive learning:
- Extract WHY something worked/failed, not just THAT it did
- Capture constraints, principles, and cause-effect relationships
- Generate REASONING and WISDOM insights

Signals we detect:
- "because..." - explicit causality
- "the reason is..." - explicit explanation
- "since..." - causal connector
- "that works because..." - success explanation
- "that failed because..." - failure explanation
- "the issue/problem is..." - root cause
- "this is better because..." - preference rationale
- "I prefer X because..." - preference with reason
- "make sure to..." / "always..." / "never..." - principles
- "the constraint is..." - explicit constraints
"""

import re
from typing import Any, Dict, List, Optional

from .base import DetectedPattern, PatternDetector, PatternType
from ..noise_patterns import is_session_boilerplate


# Pattern categories with confidence and insight type
# Format: (regex, confidence, insight_type)
# insight_type: "reasoning" | "wisdom" | "constraint" | "preference"

WHY_PATTERNS = [
    # Explicit causality (high value)
    (r"\bbecause\s+(.{10,120}?)(?:[.!?\n]|$)", 0.85, "reasoning"),
    (r"\bthe\s+reason\s+(?:is|was)\s+(.{10,120}?)(?:[.!?\n]|$)", 0.9, "reasoning"),
    (r"\bsince\s+(.{10,120}?)(?:[.!?\n,]|$)", 0.7, "reasoning"),
    (r"\bdue\s+to\s+(.{10,80}?)(?:[.!?\n,]|$)", 0.75, "reasoning"),
    (r"\bthat'?s\s+why\s+(.{10,100}?)(?:[.!?\n]|$)", 0.85, "reasoning"),

    # Success/failure explanations (very high value)
    (r"\b(?:that|this|it)\s+work(?:s|ed)\s+because\s+(.{10,120}?)(?:[.!?\n]|$)", 0.95, "reasoning"),
    (r"\b(?:that|this|it)\s+fail(?:s|ed)\s+because\s+(.{10,120}?)(?:[.!?\n]|$)", 0.95, "reasoning"),
    (r"\bwork(?:s|ed)\s+(?:well\s+)?because\s+(.{10,120}?)(?:[.!?\n]|$)", 0.9, "reasoning"),
    (r"\bdidn'?t\s+work\s+because\s+(.{10,120}?)(?:[.!?\n]|$)", 0.9, "reasoning"),

    # Root cause identification
    (r"\bthe\s+(?:issue|problem|bug)\s+(?:is|was)\s+(.{10,120}?)(?:[.!?\n]|$)", 0.85, "reasoning"),
    (r"\bthe\s+(?:fix|solution)\s+(?:is|was)\s+(.{10,120}?)(?:[.!?\n]|$)", 0.85, "reasoning"),
    (r"\broot\s+cause\s+(?:is|was)\s+(.{10,100}?)(?:[.!?\n]|$)", 0.95, "reasoning"),

    # Preference with rationale (high value)
    (r"\bi\s+prefer\s+(.{5,50}?)\s+because\s+(.{10,100}?)(?:[.!?\n]|$)", 0.9, "preference"),
    (r"\b(?:this|that)\s+is\s+better\s+because\s+(.{10,100}?)(?:[.!?\n]|$)", 0.85, "preference"),
    (r"\buse\s+(.{5,40}?)\s+(?:instead|rather)\s+because\s+(.{10,80}?)(?:[.!?\n]|$)", 0.9, "preference"),

    # Principles and rules (wisdom)
    (r"\balways\s+(.{10,80}?)(?:[.!?\n]|$)", 0.75, "wisdom"),
    (r"\bnever\s+(.{10,80}?)(?:[.!?\n]|$)", 0.8, "wisdom"),
    (r"\bmake\s+sure\s+(?:to\s+)?(.{10,80}?)(?:[.!?\n]|$)", 0.7, "wisdom"),
    (r"\bremember\s+(?:to\s+)?(.{10,80}?)(?:[.!?\n]|$)", 0.7, "wisdom"),
    (r"\bthe\s+(?:key|trick|secret)\s+is\s+(.{10,100}?)(?:[.!?\n]|$)", 0.85, "wisdom"),
    (r"\brule\s+of\s+thumb[:\s]+(.{10,100}?)(?:[.!?\n]|$)", 0.9, "wisdom"),

    # Constraints
    (r"\bthe\s+constraint\s+is\s+(.{10,100}?)(?:[.!?\n]|$)", 0.9, "constraint"),
    (r"\bwe\s+(?:need|have)\s+to\s+(.{10,80}?)(?:[.!?\n]|$)", 0.65, "constraint"),
    (r"\bmust\s+(?:be|have|ensure)\s+(.{10,80}?)(?:[.!?\n]|$)", 0.7, "constraint"),
    (r"\bcan'?t\s+(?:be|have|do)\s+(.{10,80}?)(?:\s+because|\s+since|[.!?\n]|$)", 0.75, "constraint"),

    # Learning statements (meta)
    (r"\bi\s+learned\s+(?:that\s+)?(.{10,100}?)(?:[.!?\n]|$)", 0.85, "wisdom"),
    (r"\bturns\s+out\s+(?:that\s+)?(.{10,100}?)(?:[.!?\n]|$)", 0.8, "reasoning"),
    (r"\bthe\s+(?:lesson|takeaway)\s+(?:is|was)\s+(.{10,100}?)(?:[.!?\n]|$)", 0.9, "wisdom"),
]

# Compile patterns for efficiency
_WHY_REGEXES = [(re.compile(p, re.IGNORECASE), conf, itype) for p, conf, itype in WHY_PATTERNS]


def _clean_extracted(text: str) -> str:
    """Clean extracted reasoning text."""
    text = text.strip()
    # Remove trailing punctuation artifacts
    text = re.sub(r"[,;:\s]+$", "", text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_too_generic(text: str) -> bool:
    """Filter out generic/low-value extractions."""
    text = text.lower().strip()

    # Too short
    if len(text) < 15:
        return True

    # Generic phrases
    generic = [
        "it works",
        "it's better",
        "it's easier",
        "that's how",
        "we need to",
        "i think",
        "i guess",
    ]
    for g in generic:
        if text == g or text.startswith(g + " "):
            return True

    return False


class WhyDetector(PatternDetector):
    """
    Detects explanations of WHY things work, fail, or matter.

    This is CRITICAL for cognitive learning because:
    - Captures cause-effect relationships
    - Extracts principles and wisdom
    - Learns constraints and rationales
    - Moves beyond "what happened" to "why it happened"

    Unlike CorrectionDetector (what user wants),
    WhyDetector captures the REASONING that makes insights transferable.
    """

    def __init__(self):
        super().__init__("WhyDetector")
        self._recent_context: Dict[str, Dict] = {}  # session -> last tool/event context

    def _update_context(self, session_id: str, event: Dict):
        """Track recent context for enriching why extractions."""
        tool_name = event.get("tool_name")
        if tool_name:
            self._recent_context[session_id] = {
                "tool": tool_name,
                "success": event.get("hook_event") == "PostToolUse",
                "error": event.get("error"),
            }

    def _get_context(self, session_id: str) -> Optional[Dict]:
        """Get recent context for a session."""
        return self._recent_context.get(session_id)

    def process_event(self, event: Dict) -> List[DetectedPattern]:
        """
        Process event and detect "why" patterns.

        Looks for causal explanations in user messages and AI responses.
        """
        patterns: List[DetectedPattern] = []
        session_id = event.get("session_id", "unknown")
        hook_event = event.get("hook_event", "")

        # Track context from tool events
        if hook_event in ("PostToolUse", "PostToolUseFailure"):
            self._update_context(session_id, event)
            return patterns

        # Look for "why" patterns in user messages
        if hook_event == "UserPromptSubmit":
            payload = event.get("payload", {})
            text = payload.get("text", "") if isinstance(payload, dict) else ""

            if not text:
                text = event.get("prompt", "") or event.get("user_prompt", "")

            if not text or len(text) < 20:
                return patterns
            if is_session_boilerplate(text):
                return patterns

            # Check each why pattern
            for regex, confidence, insight_type in _WHY_REGEXES:
                match = regex.search(text)
                if not match:
                    continue

                # Extract the reasoning content
                groups = match.groups()
                if not groups:
                    continue

                # Handle patterns with multiple capture groups (preference patterns)
                if len(groups) >= 2:
                    extracted = f"{_clean_extracted(groups[0])} because {_clean_extracted(groups[1])}"
                else:
                    extracted = _clean_extracted(groups[0])

                # Skip generic/low-value extractions
                if _is_too_generic(extracted):
                    continue
                if is_session_boilerplate(extracted):
                    continue

                # Get recent context
                recent_ctx = self._get_context(session_id)

                # Build evidence
                evidence = [
                    f"User said: {text[:120]}...",
                    f"Extracted: {extracted}",
                    f"Pattern type: {insight_type}",
                ]

                context = {
                    "user_text": text,
                    "extracted_reasoning": extracted,
                    "insight_type": insight_type,
                    "match": match.group(0),
                }

                if recent_ctx:
                    evidence.append(f"Context: {recent_ctx.get('tool', 'unknown')} ({'success' if recent_ctx.get('success') else 'failed'})")
                    context["preceding_context"] = recent_ctx

                # Generate suggested insight based on type
                suggested_insight = self._generate_insight(extracted, insight_type, recent_ctx)
                suggested_category = self._map_category(insight_type)

                patterns.append(DetectedPattern(
                    pattern_type=PatternType.CORRECTION,  # Reuse existing type for now
                    confidence=confidence,
                    evidence=evidence,
                    context=context,
                    session_id=session_id,
                    suggested_insight=suggested_insight,
                    suggested_category=suggested_category,
                ))

        return patterns

    def _generate_insight(self, extracted: str, insight_type: str, context: Optional[Dict]) -> str:
        """Generate a human-readable insight from extracted reasoning."""
        if insight_type == "reasoning":
            if context and not context.get("success"):
                return f"Failure reason: {extracted}"
            elif context and context.get("success"):
                return f"Success factor: {extracted}"
            else:
                return f"Reasoning: {extracted}"

        elif insight_type == "wisdom":
            return f"Principle: {extracted}"

        elif insight_type == "constraint":
            return f"Constraint: {extracted}"

        elif insight_type == "preference":
            return f"Preference rationale: {extracted}"

        return extracted

    def _map_category(self, insight_type: str) -> str:
        """Map insight type to CognitiveCategory."""
        mapping = {
            "reasoning": "reasoning",
            "wisdom": "wisdom",
            "constraint": "context",
            "preference": "user_understanding",
        }
        return mapping.get(insight_type, "reasoning")
