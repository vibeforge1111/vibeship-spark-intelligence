"""Contextual memory envelope helpers.

Builds self-contained memory context strings with stable metadata so retrieval
can match across sparse or abbreviated original contexts.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

DEFAULT_MIN_CONTEXT_CHARS = 120
DEFAULT_MAX_CONTEXT_CHARS = 320


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _clip(text: str, *, max_chars: int) -> str:
    t = _clean(text)
    if len(t) > max_chars:
        t = t[:max_chars].rstrip()
    return t


def _split_sentences(text: str, *, limit: int = 3) -> str:
    cleaned = _clean(text)
    if not cleaned:
        return ""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\s*[;|]\s+", cleaned) if p.strip()]
    if not parts:
        return cleaned
    return " ".join(parts[: max(1, int(limit))])


def _keywords(text: str, *, limit: int = 6) -> List[str]:
    cleaned = _clean(text).lower()
    if not cleaned:
        return []
    tokens = re.findall(r"[a-z][a-z0-9_]{3,}", cleaned)
    stop = {
        "that",
        "this",
        "with",
        "from",
        "when",
        "where",
        "which",
        "while",
        "should",
        "would",
        "could",
        "about",
        "after",
        "before",
        "during",
        "using",
        "into",
        "through",
        "always",
        "never",
    }
    out: List[str] = []
    seen = set()
    for tok in tokens:
        if tok in stop or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= max(1, int(limit)):
            break
    return out


def build_context_envelope(
    *,
    context: str,
    insight: str,
    category: str = "",
    source: str = "",
    advisory_quality: Dict[str, Any] | None = None,
    min_chars: int = DEFAULT_MIN_CONTEXT_CHARS,
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> str:
    """Build a retrieval-friendly context envelope for an insight."""
    parts: List[str] = []
    base = _clip(context, max_chars=max_chars)
    if base:
        parts.append(base)

    quality = advisory_quality if isinstance(advisory_quality, dict) else {}
    structure = quality.get("structure") if isinstance(quality.get("structure"), dict) else {}
    condition = _clean(structure.get("condition") or "")
    action = _clean(structure.get("action") or "")
    reasoning = _clean(structure.get("reasoning") or "")
    outcome = _clean(structure.get("outcome") or "")

    if condition:
        parts.append(f"When {condition}")
    if action:
        parts.append(f"Action: {action}")
    if reasoning:
        parts.append(f"Reason: {reasoning}")
    elif outcome:
        parts.append(f"Outcome: {outcome}")

    cat = _clean(category).lower()
    if cat:
        parts.append(f"Category: {cat}")
    src = _clean(source).lower()
    if src and src not in {"unknown", "none", "general"}:
        parts.append(f"Source: {src}")

    summary = _split_sentences(insight, limit=3)
    if summary:
        parts.append(f"Signal: {summary}")

    merged = " | ".join([p for p in parts if p]).strip(" |")
    if len(merged) < max(0, int(min_chars)):
        keys = _keywords(insight, limit=6)
        if keys:
            merged = " | ".join([merged, f"Keywords: {', '.join(keys)}"]).strip(" |")

    return _clip(merged, max_chars=max_chars)

