"""Shared noise pattern definitions used by multiple quality gates.

Consolidates commonly duplicated patterns across meta_ralph, cognitive_learner,
primitive_filter, and bridge_cycle.  Each consumer module imports what it needs
and keeps its own domain-specific patterns in place.

Created in Batch 6 of Intelligence Flow Evolution.
"""

import re
from typing import FrozenSet, Tuple

# ---------------------------------------------------------------------------
# Tool token lists (shared by primitive_filter + cognitive_learner)
# ---------------------------------------------------------------------------

TOOL_TOKENS: Tuple[str, ...] = (
    "read", "edit", "write", "bash", "glob", "grep",
    "todowrite", "taskoutput", "webfetch", "powershell",
    "python", "killshell", "cli",
)

# Pre-compiled regex matching any tool token (case-insensitive).
TOOL_TOKEN_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in TOOL_TOKENS) + r")\b", re.I
)

# ---------------------------------------------------------------------------
# Tool sequence / arrow patterns (shared by meta_ralph + cognitive + primitive)
# ---------------------------------------------------------------------------

ARROW_RE = re.compile(r"(?:->|-->|\u2192)")

TOOL_SEQUENCE_PATTERNS: Tuple[str, ...] = (
    r"\b(?:read|edit|write|bash|glob|grep)\b\s*->\s*\b(?:read|edit|write|bash|glob|grep)\b",
    r"\b(?:read|edit|write|bash|glob|grep)\b\s*(?:->|-->|\u2192)\s*\b\w+\b",
    r"tool sequence",
    r"pattern using \w+\.",
    r"sequence.*(?:work|pattern)",
)

TOOL_SEQUENCE_RE = re.compile(
    "|".join(TOOL_SEQUENCE_PATTERNS), re.I
)

# ---------------------------------------------------------------------------
# Statistics / telemetry patterns (shared by meta_ralph + cognitive)
# ---------------------------------------------------------------------------

STATS_TELEMETRY_PATTERNS: Tuple[str, ...] = (
    r"success rate: \d+%",
    r"over \d+ uses",
    r"usage \(\d+ calls?\)",
    r"pattern distribution",
    r"events processed",
    r"generation: \d+",
    r"accumulated \d+ learnings",
    r"validation count",
    r"file modified:",
    r"tool timeout",
)

STATS_TELEMETRY_RE = re.compile(
    "|".join(STATS_TELEMETRY_PATTERNS), re.I
)

# ---------------------------------------------------------------------------
# API / infrastructure error patterns (bridge_cycle)
# ---------------------------------------------------------------------------

API_ERROR_STRINGS: FrozenSet[str] = frozenset({
    "invalid api key",
    "usage limit reached",
    "rate limit",
    "quota exceeded",
    "authentication failed",
    "insufficient credits",
    "service unavailable",
})


def is_api_error_noise(text: str) -> bool:
    """Check if text matches common API/infra error noise."""
    text_lower = text.lower()
    return any(p in text_lower for p in API_ERROR_STRINGS)


# ---------------------------------------------------------------------------
# Generic advice / tautology patterns (bridge_cycle + meta_ralph)
# ---------------------------------------------------------------------------

GENERIC_ADVICE_STRINGS: FrozenSet[str] = frozenset({
    "try a different approach",
    "step back and",
    "try something else",
    "try another approach",
    "always validate",
    "always verify",
    "be careful",
    "consider alternatives",
    "consider other options",
})


def is_generic_advice(text: str) -> bool:
    """Check if text is generic, non-actionable advice."""
    text_lower = text.lower()
    return any(p in text_lower for p in GENERIC_ADVICE_STRINGS)


# ---------------------------------------------------------------------------
# Primitive keyword lists (primitive_filter)
# ---------------------------------------------------------------------------

PRIMITIVE_KEYWORDS: Tuple[str, ...] = (
    "struggle", "overconfident", "fails", "failed", "error",
    "timeout", "usage", "sequence", "pattern",
)

# ---------------------------------------------------------------------------
# Session boilerplate / inventory scaffolding (shared across capture + distill)
# ---------------------------------------------------------------------------

SESSION_BOILERPLATE_PATTERNS: Tuple[str, ...] = (
    r"you are spark intelligence, observing a live coding session",
    r"system inventory \(what actually exists",
    r"<task-notification>|<task-id>|<output-file>|<status>|<summary>",
    r"\bmission id:\b|\bassigned tasks:\b|\bexecution expectations:\b",
    r"\bh70 skill loading\b|\bmission completion gate\b",
    r"^\s*#\s*provider prompt",
    r"\bcurl\s+-x\s+post\s+http://127\.0\.0\.1:\d+/api/events\b",
)

SESSION_BOILERPLATE_RE = re.compile(
    "|".join(SESSION_BOILERPLATE_PATTERNS), re.I
)


def is_session_boilerplate(text: str) -> bool:
    """Detect session scaffolding that should not become durable memory."""
    sample = str(text or "").strip()
    if not sample:
        return False
    return bool(SESSION_BOILERPLATE_RE.search(sample))

# ---------------------------------------------------------------------------
# Quick noise check combining the most common shared patterns.
# ---------------------------------------------------------------------------


def is_common_noise(text: str) -> bool:
    """Fast check against the most commonly shared noise patterns.

    Returns True if the text matches tool sequences, stats telemetry,
    API errors, or generic advice patterns.  Consumers should still apply
    their own domain-specific filters on top.
    """
    if not text or len(text) < 10:
        return False
    if TOOL_SEQUENCE_RE.search(text):
        return True
    if STATS_TELEMETRY_RE.search(text):
        return True
    text_lower = text.lower()
    if any(p in text_lower for p in API_ERROR_STRINGS):
        return True
    if any(p in text_lower for p in GENERIC_ADVICE_STRINGS):
        return True
    return False
