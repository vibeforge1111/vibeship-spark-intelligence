"""Deterministic Layer-0 keepability gate.

Purpose:
- Reject obvious non-intelligence early (cheap string checks).
- Emit explicit reason codes for observability and rule tuning.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


_HEX_LONG_RE = re.compile(r"\b[a-f0-9]{8,}\b", re.IGNORECASE)
_CHUNK_RE = re.compile(r"\bchunk id[:\s]*[a-f0-9]{4,}\b", re.IGNORECASE)
_EXEC_FAIL_RE = re.compile(r"\bexec_command failed\b", re.IGNORECASE)
_CSS_RE = re.compile(
    r"(#[\w-]+\s*\{[^}]*\})|(\{[^}]*\b(position|display|padding|margin|z-index)\b[^}]*\})",
    re.IGNORECASE,
)
_QUESTION_ONLY_RE = re.compile(
    r"^\s*(can we|should we|could we|what if|why not|is it|are we)\b.*\?\s*$",
    re.IGNORECASE,
)
_CONVERSATIONAL_RE = re.compile(
    r"\b(it worked|sounds good|thanks|thank you|let'?s do it|user expressed satisfaction)\b",
    re.IGNORECASE,
)
_QUOTE_ECHO_RE = re.compile(r"^\s*['\"`].+['\"`]\s*$")
_BLOB_RE = re.compile(r"[{};:]{3,}")
_WORD_RE = re.compile(r"[A-Za-z0-9_'-]+")
# Short real words that legitimately end a sentence (don't flag as truncation)
_SHORT_END_WORDS = {
    "be", "do", "is", "or", "if", "at", "in", "on", "to", "it", "of",
    "so", "no", "go", "up", "us", "we", "me", "my", "by", "am", "an",
    "as", "ok", "vs",
}
_PREFER_OVER_RE = re.compile(
    r"prefer\s+['\"](.+?)['\"]\s+over\s+['\"](.+?)['\"]", re.IGNORECASE
)

_ACTION_VERBS = {
    # Original
    "use", "run", "check", "verify", "validate", "avoid", "prefer",
    "split", "refactor", "retry", "inspect", "log", "gate", "store",
    "remove", "add", "align", "trace", "promote", "demote", "rewrite",
    "because", "should", "must", "always", "never",
    # Implementation / creation
    "implement", "create", "build", "configure", "set", "enable", "disable",
    "establish", "setup", "initialize", "install", "deploy", "migrate",
    # Testing / validation
    "test", "try", "attempt", "confirm", "demonstrate", "assert",
    # Investigation / analysis
    "search", "find", "look", "explore", "analyze", "investigate",
    "examine", "review", "debug", "diagnose", "profile",
    # Modification / fixing
    "modify", "fix", "update", "change", "adjust", "correct", "revise",
    "improve", "enhance", "patch", "optimize", "tune", "tweak",
    # Organization / structure
    "ensure", "organize", "structure", "group", "categorize", "separate",
    # Awareness / monitoring
    "watch", "monitor", "observe", "track", "consider", "measure",
    "detect", "prevent", "alert",
    # Decision / planning
    "decide", "plan", "choose", "select", "design", "architect",
    # Communication / documentation
    "document", "explain", "clarify",
    # Security / data
    "sanitize", "escape", "encrypt", "authenticate", "authorize", "audit",
    # Flow control
    "cache", "batch", "throttle", "queue", "schedule", "fallback",
}


def evaluate_structural_keepability(text: str) -> Dict[str, Any]:
    """Return structural gate decision with explicit reason codes."""
    raw = str(text or "").strip()
    reasons: List[str] = []

    if not raw:
        reasons.append("empty_text")
        return {"passed": False, "reasons": reasons}

    words = _WORD_RE.findall(raw)
    word_count = len(words)

    if word_count < 4:
        reasons.append("too_short")
    if word_count > 100:
        reasons.append("too_long")

    lowered = raw.lower()
    if _EXEC_FAIL_RE.search(lowered) or _CHUNK_RE.search(lowered):
        reasons.append("operational_chunk_telemetry")

    if _HEX_LONG_RE.search(lowered) and ("error" in lowered or "failed" in lowered or "chunk" in lowered):
        reasons.append("opaque_error_hash")

    if _CSS_RE.search(raw):
        reasons.append("css_or_style_artifact")

    if _QUESTION_ONLY_RE.match(raw):
        reasons.append("question_without_resolution")

    if _CONVERSATIONAL_RE.search(raw):
        reasons.append("conversational_residue")

    if _QUOTE_ECHO_RE.match(raw):
        reasons.append("raw_quote_echo")

    # Blobs are often logs/snippets, not reusable intelligence.
    if _BLOB_RE.search(raw) and not any(v in lowered for v in ("because", "should", "must", "avoid", "prefer")):
        reasons.append("blob_like_fragment")

    has_action_signal = any(token.lower() in _ACTION_VERBS for token in words)
    if not has_action_signal:
        reasons.append("no_action_signal")

    # Truncation detection: text cut mid-word or mid-sentence.
    if word_count >= 4:
        last_word = words[-1] if words else ""
        last_char = raw.rstrip()[-1] if raw.rstrip() else ""
        # Ends with 1-2 char fragment that isn't a real short word
        if (
            last_char.isalnum()
            and len(last_word) <= 2
            and last_word.lower() not in _SHORT_END_WORDS
        ):
            reasons.append("mid_sentence_truncation")

    # Malformed "prefer X over Y" — both sides must be meaningful.
    m = _PREFER_OVER_RE.search(raw)
    if m:
        x_part, y_part = m.group(1).strip(), m.group(2).strip()
        if len(x_part) < 3 or len(y_part) < 3:
            reasons.append("malformed_preference")

    # De-duplicate while preserving order.
    uniq: List[str] = []
    for reason in reasons:
        if reason not in uniq:
            uniq.append(reason)

    return {"passed": len(uniq) == 0, "reasons": uniq}

