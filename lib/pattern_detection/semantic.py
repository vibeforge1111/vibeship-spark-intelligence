"""
SemanticIntentDetector: lightweight intent detection beyond exact keywords.

Focuses on polite redirects and implicit preferences, but stays conservative:
- Emits low-confidence patterns by default
- Requires repetition to cross learning threshold
"""

import re
from typing import Dict, List, Optional, Tuple

from .base import DetectedPattern, PatternDetector, PatternType


INTENT_PATTERNS: List[Tuple[str, float, str]] = [
    (r"\bwhat\s+about\b", 0.6, "redirect"),
    (r"\bhow\s+about\b", 0.6, "redirect"),
    (r"\blet'?s\s+go\s+with\b", 0.65, "redirect"),
    (r"\blet'?s\s+use\b", 0.65, "preference"),
    (r"\bgo\s+with\b", 0.6, "preference"),
    (r"\bi'?d\s+rather\b", 0.65, "preference"),
    (r"\bi\s+would\s+rather\b", 0.65, "preference"),
    (r"\bprefer\b", 0.65, "preference"),
    (r"\bswitch\s+to\b", 0.65, "redirect"),
    (r"\boption\s+[a-z0-9]\b", 0.6, "choice"),
    (r"\bnon[-\s]?negotiable\b", 0.8, "constraint"),
    (r"\bmust\s+not\b", 0.8, "constraint"),
    (r"\bconstraint\b", 0.75, "constraint"),
    (r"\bdeadline\b", 0.72, "constraint"),
    (r"\bscope\b", 0.68, "constraint"),
    (r"\btrade[\s-]?off\b", 0.72, "tradeoff"),
    (r"\brisk\b", 0.68, "tradeoff"),
    (r"\bdecision\b", 0.68, "decision"),
    (r"\bwe\s+decided\b", 0.75, "decision"),
]


def _extract_preference(text: str) -> Dict[str, str]:
    # "instead of X, Y"
    m = re.search(r"(?:instead\s+of|rather\s+than)\s+(.+?)[,;:.]\s*(.+?)(?:[.!?]|$)", text, re.I)
    if m:
        return {"rejected": m.group(1).strip(), "wanted": m.group(2).strip()}

    # "what about X", "how about X"
    m = re.search(r"\b(?:what|how)\s+about\s+(.+?)(?:[.!?]|$)", text, re.I)
    if m:
        return {"wanted": m.group(1).strip()}

    # "go with X", "choose X", "use X", "try X"
    m = re.search(r"\b(?:go\s+with|choose|use|try|pick)\s+(.+?)(?:[.!?]|$)", text, re.I)
    if m:
        return {"wanted": m.group(1).strip()}

    # "option B"
    m = re.search(r"\boption\s+([a-z0-9]+)\b", text, re.I)
    if m:
        return {"wanted": f"option {m.group(1).lower()}"}

    # "non-negotiable: X", "constraint: X", "decision: X"
    m = re.search(r"\b(?:non[-\s]?negotiable|constraint|decision)\s*[:\-]\s*(.+?)(?:[.!?]|$)", text, re.I)
    if m:
        return {"wanted": m.group(1).strip()}

    return {}


def _normalize_key(*parts: Optional[str]) -> str:
    joined = " ".join(p or "" for p in parts).strip().lower()
    joined = re.sub(r"\s+", " ", joined)
    return joined


class SemanticIntentDetector(PatternDetector):
    """Detect polite redirects and implicit preferences with low confidence."""

    def __init__(self):
        super().__init__("SemanticIntentDetector")
        self._signal_counts: Dict[str, Dict[str, int]] = {}

    def _bump_signal(self, session_id: str, key: str) -> int:
        if session_id not in self._signal_counts:
            self._signal_counts[session_id] = {}
        counts = self._signal_counts[session_id]
        counts[key] = counts.get(key, 0) + 1
        # Trim excessive keys
        if len(counts) > 50:
            self._signal_counts[session_id] = {}
        return counts[key]

    def process_event(self, event: Dict) -> List[DetectedPattern]:
        patterns: List[DetectedPattern] = []
        session_id = event.get("session_id", "unknown")
        hook_event = event.get("hook_event", "")

        if hook_event != "UserPromptSubmit":
            return patterns

        payload = event.get("payload", {})
        text = payload.get("text", "") if isinstance(payload, dict) else ""
        if not text:
            text = event.get("prompt", "") or event.get("user_prompt", "")
        if not text:
            return patterns

        text_lower = text.lower()

        best_match = None
        best_conf = 0.0
        best_label = ""

        for pattern, conf, label in INTENT_PATTERNS:
            match = re.search(pattern, text_lower)
            if match and conf > best_conf:
                best_match = match
                best_conf = conf
                best_label = label

        if not best_match:
            return patterns

        pref = _extract_preference(text)
        wanted = pref.get("wanted")
        rejected = pref.get("rejected")
        key = _normalize_key(wanted, rejected, best_label)
        repeat_count = self._bump_signal(session_id, key) if key else 1

        confidence = best_conf
        if repeat_count >= 2:
            confidence = min(0.95, confidence + 0.15)
        if repeat_count >= 3:
            confidence = min(0.95, confidence + 0.1)

        evidence = [
            f"User said: {text[:150]}...",
            f"Matched semantic intent: {best_match.group(0)}",
        ]
        if repeat_count >= 2:
            evidence.append(f"Repeated semantic signal x{repeat_count}")

        context = {
            "user_text": text,
            "intent_label": best_label,
            "semantic_signal": best_match.group(0),
            "repeat_count": repeat_count,
        }
        if wanted:
            context["wanted"] = wanted
        if rejected:
            context["rejected"] = rejected

        suggested_insight = None
        if confidence >= 0.7 and wanted:
            if best_label == "constraint":
                suggested_insight = f"Constraint: {wanted}"
            elif best_label in {"decision", "tradeoff"}:
                suggested_insight = f"Decision signal: {wanted}"
            elif rejected:
                suggested_insight = f"User prefers '{wanted}' over '{rejected}'"
            else:
                suggested_insight = f"User prefers: {wanted}"

        suggested_category = "user_understanding"
        if best_label == "constraint":
            suggested_category = "context"
        elif best_label in {"decision", "tradeoff"}:
            suggested_category = "reasoning"

        patterns.append(DetectedPattern(
            pattern_type=PatternType.CORRECTION,
            confidence=confidence,
            evidence=evidence,
            context=context,
            session_id=session_id,
            suggested_insight=suggested_insight,
            suggested_category=suggested_category,
        ))

        return patterns
