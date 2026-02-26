"""Implicit outcome tracker: links advisory advice to tool outcomes.

Records what advice was given before a tool call, then records whether the
tool succeeded or failed. This closes the advisory feedback loop so the
system can learn which advice actually helps.

Storage: ~/.spark/advisor/implicit_feedback.jsonl
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.diagnostics import log_debug
from lib.file_lock import file_lock_for

FEEDBACK_FILE = Path.home() / ".spark" / "advisor" / "implicit_feedback.jsonl"
FEEDBACK_FILE_MAX = 2000
# How long to keep advice records for matching (seconds)
ADVICE_TTL_S = 300  # 5 minutes


class ImplicitOutcomeTracker:
    """Tracks advice → outcome for implicit feedback signals."""

    def __init__(self) -> None:
        self._pending: Dict[str, Dict[str, Any]] = {}
        # key = tool_name, value = {advice_texts, advice_sources, timestamp}

    def record_advice(
        self,
        tool_name: str,
        advice_texts: List[str],
        advice_sources: Optional[List[str]] = None,
        tool_input: Optional[Dict] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        """Record that advice was emitted before a tool call."""
        if not advice_texts:
            return
        self._pending[tool_name] = {
            "advice_texts": advice_texts[:5],
            "advice_sources": (advice_sources or [])[:5],
            "file_path": (tool_input or {}).get("file_path", ""),
            "timestamp": time.time(),
            "trace_id": str(trace_id or "").strip(),
        }

    def record_outcome(
        self,
        tool_name: str,
        success: bool,
        tool_input: Optional[Dict] = None,
        error_text: str = "",
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record tool outcome and match against pending advice."""
        self._clean_stale()
        entry = self._pending.pop(tool_name, None)
        if not entry:
            return {"matched": False, "signal": "no_advice"}

        signal = "followed" if success else "unhelpful"

        feedback = {
            "tool": tool_name,
            "signal": signal,
            "success": success,
            "advice_count": len(entry.get("advice_texts", [])),
            "advice_sources": entry.get("advice_sources", []),
            "file_path": entry.get("file_path", ""),
            "trace_id": str(trace_id or entry.get("trace_id") or "").strip(),
            "latency_s": round(time.time() - entry["timestamp"], 2),
            "timestamp": time.time(),
        }
        if error_text:
            feedback["error"] = error_text[:200]

        self._append_feedback(feedback)
        return {"matched": True, "signal": signal}

    def detect_correction(self, tool_name: str) -> bool:
        """Check if a tool was recently advised and then failed (correction signal)."""
        entry = self._pending.get(tool_name)
        if not entry:
            return False
        return (time.time() - entry["timestamp"]) < ADVICE_TTL_S

    def _clean_stale(self) -> None:
        cutoff = time.time() - ADVICE_TTL_S
        self._pending = {
            k: v for k, v in self._pending.items()
            if v.get("timestamp", 0) > cutoff
        }

    def _append_feedback(self, entry: Dict) -> None:
        try:
            FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
            with file_lock_for(FEEDBACK_FILE, fail_open=False):
                with FEEDBACK_FILE.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                self._rotate_if_needed()
        except Exception as e:
            log_debug("implicit_tracker", "write failed", e)

    @staticmethod
    def _rotate_if_needed() -> None:
        """Trim feedback file using atomic temp-write + os.replace.

        Caller should already hold FEEDBACK_FILE lock.
        """
        try:
            if not FEEDBACK_FILE.exists():
                return
            if FEEDBACK_FILE.stat().st_size // 250 <= FEEDBACK_FILE_MAX:
                return
            lines = FEEDBACK_FILE.read_text(encoding="utf-8").splitlines()
            if len(lines) <= FEEDBACK_FILE_MAX:
                return
            keep = "\n".join(lines[-FEEDBACK_FILE_MAX:]) + "\n"
            tmp = FEEDBACK_FILE.with_suffix(FEEDBACK_FILE.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
            tmp.write_text(keep, encoding="utf-8")
            os.replace(str(tmp), str(FEEDBACK_FILE))
        except Exception:
            pass


# Singleton
_tracker: Optional[ImplicitOutcomeTracker] = None


def get_implicit_tracker() -> ImplicitOutcomeTracker:
    global _tracker
    if _tracker is None:
        _tracker = ImplicitOutcomeTracker()
    return _tracker
