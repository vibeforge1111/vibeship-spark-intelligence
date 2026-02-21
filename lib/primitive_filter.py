"""Heuristics for filtering primitive/operational text from learnings."""

from __future__ import annotations

import re


_TOOL_TOKENS = (
    "read",
    "edit",
    "write",
    "bash",
    "glob",
    "grep",
    "todowrite",
    "taskoutput",
    "webfetch",
    "powershell",
    "python",
    "killshell",
    "cli",
)

_PRIM_KW = (
    "struggle",
    "overconfident",
    "fails",
    "failed",
    "error",
    "timeout",
    "usage",
    "sequence",
    "pattern",
)

_TOOL_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in _TOOL_TOKENS) + r")\b", re.I)
_TOOL_ERROR_KEY_RE = re.compile(r"\btool[_\s-]*\d+[_\s-]*error\b", re.I)


def is_primitive_text(text: str) -> bool:
    """Return True when text looks like low-level operational telemetry."""
    if not text:
        return False
    tl = text.lower()
    if _TOOL_ERROR_KEY_RE.search(tl):
        return True
    if "i struggle with tool_" in tl and "_error" in tl:
        return True
    if "error_pattern:" in tl:
        return True
    if "status code 404" in tl and ("webfetch" in tl or "request failed" in tl):
        return True
    if "->" in text or "→" in text:
        return True
    if "sequence" in tl and ("work" in tl or "pattern" in tl):
        return True
    if _TOOL_RE.search(tl) and any(k in tl for k in _PRIM_KW):
        return True
    return False
