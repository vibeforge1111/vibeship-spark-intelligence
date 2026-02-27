"""Compact primary scorer for Meta-Ralph."""

from __future__ import annotations

import re
from typing import Dict

_ACTION_RE = re.compile(
    r"\b(always|never|must|should|use|avoid|set|prefer|choose|switch|validate|check|run|fix)\b",
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
    r"^\s*(what|why|how|when|where|who)\b|"
    r"^\s*(do|does|did|should|would|could|can|is|are|am)\s+(we|you|i|they|it|this|that)\b",
    re.I,
)


def _question_like(text: str) -> bool:
    sample = str(text or "").strip()
    if not sample:
        return False
    if sample.endswith("?"):
        return True
    if _QUESTION_START_RE.match(sample):
        return True
    if "i'm not sure" in sample.lower() or "im not sure" in sample.lower():
        return True
    return False


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
