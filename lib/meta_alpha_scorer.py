"""Compact challenger scorer for Meta-Ralph dual-scoring experiments.

Default mode is shadow-only. Legacy Meta-Ralph scoring remains authoritative
unless SPARK_META_DUAL_SCORE_ENFORCE is enabled.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Dict

SHADOW_LOG = Path.home() / ".spark" / "meta_dual_score_shadow.jsonl"

_ACTION_RE = re.compile(
    r"\b(always|never|must|should|use|avoid|set|prefer|choose|switch|validate|check)\b",
    re.I,
)
_REASONING_RE = re.compile(r"\b(because|so that|therefore|hence|due to|prevents|ensures)\b", re.I)
_OUTCOME_RE = re.compile(
    r"\b(reduced|improved|increased|decreased|outperformed|worked|failed|outcome|result)\b",
    re.I,
)
_SPECIFIC_RE = re.compile(
    r"\b(api|schema|trace|latency|token|retry|deploy|auth|memory|advisory|sqlite|jsonl)\b",
    re.I,
)
_RISKY_RE = re.compile(r"\b(exploit|bypass|disable safety|unsafe|harm)\b", re.I)


def shadow_enabled() -> bool:
    raw = str(os.getenv("SPARK_META_DUAL_SCORE_SHADOW", "1")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def enforce_enabled() -> bool:
    raw = str(os.getenv("SPARK_META_DUAL_SCORE_ENFORCE", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def score(text: str | None, context: Dict[str, object] | None = None) -> Dict[str, int]:
    sample = str(text or "").strip()
    lower = sample.lower()
    ctx = context or {}

    actionability = 2 if _ACTION_RE.search(lower) else (1 if any(w in lower for w in ("try", "consider", "could")) else 0)
    reasoning = 2 if _REASONING_RE.search(lower) else (1 if "why" in lower else 0)

    novelty = 2 if (re.search(r"\d{2,}", lower) and len(lower) > 40) else 1
    if "remember this" in lower:
        novelty = max(novelty, 1)
    if ctx.get("is_priority"):
        novelty = min(2, novelty + 1)

    specificity = 2 if _SPECIFIC_RE.search(lower) else (1 if len(lower) >= 60 else 0)
    outcome_linked = 2 if _OUTCOME_RE.search(lower) else (1 if "if " in lower and " then " in lower else 0)
    ethics = 0 if _RISKY_RE.search(lower) else 1

    return {
        "actionability": max(0, min(2, int(actionability))),
        "novelty": max(0, min(2, int(novelty))),
        "reasoning": max(0, min(2, int(reasoning))),
        "specificity": max(0, min(2, int(specificity))),
        "outcome_linked": max(0, min(2, int(outcome_linked))),
        "ethics": max(0, min(2, int(ethics))),
    }


def record_shadow(
    *,
    learning: str,
    legacy_total: int,
    legacy_verdict: str,
    challenger_total: int,
    challenger_verdict: str,
    selected: str,
) -> None:
    if legacy_verdict == challenger_verdict and abs(int(legacy_total) - int(challenger_total)) < 2:
        return
    try:
        SHADOW_LOG.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": time.time(),
            "legacy_total": int(legacy_total),
            "legacy_verdict": str(legacy_verdict),
            "challenger_total": int(challenger_total),
            "challenger_verdict": str(challenger_verdict),
            "selected": str(selected),
            "snippet": str(learning or "").strip()[:220],
        }
        with SHADOW_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass
