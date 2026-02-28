"""Compact primary scorer for Meta-Ralph."""

from __future__ import annotations

import re
from typing import Dict

_ACTION_RE = re.compile(
    r"\b(always|never|must|should|use|avoid|set|prefer|choose|switch|validate|check|run|fix|"
    r"enforce|add|include|remove|update|enable|disable)\b",
    re.I,
)
_REASONING_RE = re.compile(r"\b(because|so that|therefore|hence|due to|prevents|ensures)\b", re.I)
_OUTCOME_RE = re.compile(
    r"\b(reduced|improved|increased|decreased|outperformed|worked|failed|outcome|result|reduces|improves|fair)\b",
    re.I,
)
_SPECIFIC_RE = re.compile(
    r"\b(api|schema|trace|latency|token|retry|deploy|auth|memory|advisory|sqlite|jsonl|oauth|pkce|postgresql|mysql|typescript|javascript|health|queue|bridge)\b",
    re.I,
)
_RISKY_RE = re.compile(r"\b(exploit|bypass|disable safety|unsafe|harm)\b", re.I)
_PRIMITIVE_RE = re.compile(
    r"\b(read task succeeded with read tool|pattern using write|bash\s*[->\u2192]\s*edit|success rate:\s*\d|for shell tasks, use standard approach)\b",
    re.I,
)
_DECISION_RE = re.compile(
    r"\b(decided to|chose to|switched to|opted for|corrected me|they want)\b",
    re.I,
)
_QUESTION_START_RE = re.compile(
    r"^\s*(what|why|how|where|who)\b|"
    r"^\s*when\s+(do|does|did|should|would|could|can|is|are|will)\b|"
    r"^\s*(do|does|did|should|would|could|can|is|are|am)\s+(we|you|i|they|it|this|that)\b",
    re.I,
)
_TECHNICAL_SIGNAL_RE = re.compile(
    r"\b(api|schema|trace|latency|token|retry|deploy|auth|memory|advisory|sqlite|jsonl|"
    r"queue|bridge|contract|payload|regression|benchmark|coverage|rollback|migration|"
    r"validator|threshold|gate|pytest|test|typescript|python)\b",
    re.I,
)
_LOW_SIGNAL_DIRECTIVE_RE = re.compile(
    r"\b(do that|this too|that too|as well|whatever works|if you want|if needed)\b|"
    r"^\s*(ok|okay|sure|sounds good|lets do it|let's do it|go ahead)\b|"
    r"\b(let me know|can you|could you|would you|please)\b",
    re.I,
)
_ACTIONABLE_REQUEST_RE = re.compile(
    r"^\s*(can|could|would)\s+(you\s+)?"
    r"(enforce|add|set|run|validate|check|update|fix|remove|use|switch|enable|disable|include)\b|"
    r"^\s*please\s+"
    r"(enforce|add|set|run|validate|check|update|fix|remove|use|switch|enable|disable|include)\b",
    re.I,
)


def _question_like(text: str) -> bool:
    sample = str(text or "").strip()
    if not sample:
        return False
    if _ACTIONABLE_REQUEST_RE.match(sample) and _has_reusable_signal(sample):
        return False
    if sample.endswith("?"):
        return True
    if _QUESTION_START_RE.match(sample):
        return True
    if "i'm not sure" in sample.lower() or "im not sure" in sample.lower():
        return True
    return False


def _has_reusable_signal(text: str) -> bool:
    sample = str(text or "").strip()
    if not sample:
        return False
    lower = sample.lower()
    if _TECHNICAL_SIGNAL_RE.search(lower):
        return True
    if re.search(r"\b(because|so that|therefore|hence|prevents|ensures|reduces|improves)\b", lower):
        return True
    if re.search(r"\b\d+(\.\d+)?%?\b", lower):
        return True
    return False


def _low_signal_conversational(text: str) -> bool:
    sample = str(text or "").strip()
    if not sample:
        return False
    return bool(_LOW_SIGNAL_DIRECTIVE_RE.search(sample))


def score(text: str | None, context: Dict[str, object] | None = None) -> Dict[str, int]:
    sample = str(text or "").strip()
    if _question_like(sample):
        return {
            "actionability": 0,
            "novelty": 0,
            "reasoning": 0,
            "specificity": 0,
            "outcome_linked": 0,
            "ethics": 1,
        }
    if _low_signal_conversational(sample) and not _has_reusable_signal(sample):
        return {
            "actionability": 0,
            "novelty": 0,
            "reasoning": 0,
            "specificity": 0,
            "outcome_linked": 0,
            "ethics": 1,
        }
    lower = sample.lower()
    ctx = context or {}

    actionability = 2 if _ACTION_RE.search(lower) else 0
    if actionability == 0 and any(w in lower for w in ("try", "consider", "could", "prefer", "prefers", "want")):
        actionability = 1
    reasoning = 2 if _REASONING_RE.search(lower) else 0
    if reasoning == 0 and (" if " in f" {lower} " and " then " in f" {lower} "):
        reasoning = 1

    novelty = 0
    if re.search(r"\d{2,}", lower) and len(lower) > 30:
        novelty = 2
    elif len(lower) >= 35:
        novelty = 1
    if "remember this" in lower:
        novelty = max(novelty, 1)
    if _DECISION_RE.search(lower):
        novelty = max(novelty, 2)
    if ctx.get("is_priority"):
        novelty = min(2, novelty + 1)

    specificity = 2 if _SPECIFIC_RE.search(lower) else (1 if len(lower) >= 35 else 0)
    outcome_linked = 2 if _OUTCOME_RE.search(lower) else 0
    if outcome_linked == 0 and (" if " in f" {lower} " and " then " in f" {lower} "):
        outcome_linked = 1
    if outcome_linked == 0 and " for better " in f" {lower} ":
        outcome_linked = 1
    ethics = 0 if _RISKY_RE.search(lower) else 1

    if _PRIMITIVE_RE.search(lower):
        actionability = 0
        novelty = 0
        reasoning = 0
        specificity = 0
        outcome_linked = 0

    return {
        "actionability": max(0, min(2, int(actionability))),
        "novelty": max(0, min(2, int(novelty))),
        "reasoning": max(0, min(2, int(reasoning))),
        "specificity": max(0, min(2, int(specificity))),
        "outcome_linked": max(0, min(2, int(outcome_linked))),
        "ethics": max(0, min(2, int(ethics))),
    }
