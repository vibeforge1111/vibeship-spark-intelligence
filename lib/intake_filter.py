"""Lightweight pre-queue intake filter.

Rejects obvious noise events BEFORE they reach the queue, saving pipeline
processing time.  All checks are pure CPU (no LLM, no I/O) targeting <5ms.

Design principle: fail-open.  If anything goes wrong, the event passes through.

Event types NEVER filtered:
- POST_TOOL_FAILURE  (all failures are high-value signals)
- USER_PROMPT        (always capture user intent)
- SESSION_START/END  (boundary markers needed for episode tracking)
- STOP / LEARNING / ERROR  (high-value system events)
- POST_TOOL for mutation tools (Edit, Write, Bash, NotebookEdit)
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Import EventType from queue.  Fail-open if unavailable.
# ---------------------------------------------------------------------------
try:
    from lib.queue import EventType
except ImportError:
    EventType = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Tools whose successful POST_TOOL events carry almost zero learning signal.
_READ_ONLY_TOOLS = frozenset({"Read", "Glob", "Grep", "Grep_search", "Search"})

# Mutation tools — queue POST_TOOL results for these (but NOT PRE_TOOL).
_MUTATION_TOOLS = frozenset({"Edit", "Write", "Bash", "NotebookEdit"})

# Bash commands that are operational / zero learning signal.
_BASH_OPERATIONAL_PREFIXES = (
    "taskkill", "kill ", "netstat", "curl ", "wget ",
    "ls ", "ls\n", "dir ", "pwd", "echo ",
    "cat ", "head ", "tail ", "wc ", "type ",
    "findstr ", "find /", "where ",
)

# High-value event types — NEVER filter these.
_ALWAYS_QUEUE_EVENTS: frozenset = frozenset()  # populated after EventType import

# Minimum readiness_hint to keep a low-signal event.
_MIN_READINESS_HINT = 0.15

# Duplicate detection window (seconds).
_DUPE_WINDOW_S = 2.0

# ---------------------------------------------------------------------------
# In-memory state (process lifetime, no persistence needed)
# ---------------------------------------------------------------------------

# Last-seen hash → timestamp, for consecutive-dupe detection.
_last_seen: Dict[str, float] = {}
_LAST_SEEN_MAX = 200  # cap to prevent unbounded growth

# Telemetry counters (exposed via get_intake_filter_stats).
_stats: Dict[str, int] = {
    "total_events": 0,
    "queued": 0,
    "dropped": 0,
    # Per-reason counters added dynamically.
}

# Recent intake decisions (bounded ring buffer for dashboard display).
_DECISION_LOG_MAX = 200
_decision_log: list = []  # list of dicts: {ts, event_type, tool_name, queued, reason}


# ---------------------------------------------------------------------------
# Populate ALWAYS_QUEUE_EVENTS after EventType import.
# ---------------------------------------------------------------------------
def _build_always_queue() -> frozenset:
    if EventType is None:
        return frozenset()
    return frozenset({
        EventType.POST_TOOL_FAILURE,
        EventType.USER_PROMPT,
        EventType.SESSION_START,
        EventType.SESSION_END,
        EventType.STOP,
        EventType.LEARNING,
        EventType.ERROR,
    })


_ALWAYS_QUEUE_EVENTS = _build_always_queue()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def should_queue_event(
    event_type: "EventType",
    tool_name: Optional[str] = None,
    tool_input: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    *,
    hook_event: str = "",
) -> Tuple[bool, str]:
    """Decide whether an event should enter the queue.

    Returns ``(should_queue, reason)``.
    *reason* is ``""`` when queued, or a short code when dropped.

    Target: <5 ms, no LLM, no disk I/O.
    """
    _stats["total_events"] = _stats.get("total_events", 0) + 1

    data = data or {}
    tool_name = (tool_name or "").strip()
    _et = str(event_type)

    # Shorthand for passing context through to the log.
    _ti = tool_input  # tool_input dict (may be None)

    # ------------------------------------------------------------------
    # Rule 0: Always queue high-value event types.
    # ------------------------------------------------------------------
    if _ALWAYS_QUEUE_EVENTS and event_type in _ALWAYS_QUEUE_EVENTS:
        _log_decision(_et, tool_name, True, "high_value_event", _ti, data)
        return _accept()

    # ------------------------------------------------------------------
    # Rule 1: Drop ALL PRE_TOOL events.
    #         POST_TOOL has the actual result — PRE_TOOL is just
    #         "about to run X" which is redundant.
    # ------------------------------------------------------------------
    if EventType is not None and event_type == EventType.PRE_TOOL:
        _log_decision(_et, tool_name, False, "pretool_noop", _ti, data)
        return _drop("pretool_noop")

    # ------------------------------------------------------------------
    # Rule 2: Queue mutation tool results (Edit, Write, Bash, Notebook).
    #         For Bash: skip operational commands (curl, taskkill, ls, etc.)
    #         that carry zero learning signal.
    # ------------------------------------------------------------------
    if tool_name in _MUTATION_TOOLS:
        # Bash operational command filter.
        if tool_name == "Bash" and _ti and isinstance(_ti, dict):
            if _is_bash_operational(_ti.get("command") or ""):
                _log_decision(_et, tool_name, False, "bash_operational", _ti, data)
                return _drop("bash_operational")
        _log_decision(_et, tool_name, True, "mutation_tool", _ti, data)
        return _accept()

    # ------------------------------------------------------------------
    # Rule 3: Skip POST_TOOL successes for read-only tools (no error).
    #         (PRE_TOOL already dropped by Rule 1 above.)
    # ------------------------------------------------------------------
    if EventType is not None and event_type == EventType.POST_TOOL:
        if tool_name in _READ_ONLY_TOOLS:
            # Check whether there's an error or interesting result.
            error = data.get("error") or ""
            if not error:
                _log_decision(_et, tool_name, False, "read_success_noop", _ti, data)
                return _drop("read_success_noop")
            # If there IS an error on a read-only tool, still queue.

    # ------------------------------------------------------------------
    # Rule 4: Skip events with very low advisory readiness and no error.
    # ------------------------------------------------------------------
    advisory = data.get("advisory")
    if isinstance(advisory, dict):
        readiness = advisory.get("readiness_hint", 1.0)
        error = data.get("error") or ""
        if readiness < _MIN_READINESS_HINT and not error:
            _log_decision(_et, tool_name, False, "low_readiness_noop", _ti, data)
            return _drop("low_readiness_noop")

    # ------------------------------------------------------------------
    # Rule 5: Consecutive duplicate detection (same tool+input within 2s).
    # ------------------------------------------------------------------
    if tool_name and tool_input:
        dupe_key = _dupe_hash(tool_name, tool_input)
        now = time.time()
        last_ts = _last_seen.get(dupe_key)
        if last_ts is not None and (now - last_ts) < _DUPE_WINDOW_S:
            _log_decision(_et, tool_name, False, "consecutive_dupe", _ti, data)
            return _drop("consecutive_dupe")
        _record_seen(dupe_key, now)

    # ------------------------------------------------------------------
    # Default: queue the event.
    # ------------------------------------------------------------------
    _log_decision(_et, tool_name, True, "default_pass", _ti, data)
    return _accept()


def get_intake_filter_stats() -> Dict[str, int]:
    """Return a snapshot of intake filter counters (in-memory, no I/O)."""
    return dict(_stats)


def get_intake_decision_log() -> list:
    """Return recent intake decisions for dashboard display (in-memory)."""
    return list(_decision_log)


def persist_intake_snapshot() -> None:
    """Accumulate current stats + decisions into ~/.spark/intake_snapshot.json.

    Called from hooks/observe.py on every event.  Since each hook invocation
    is a separate process, in-memory _stats reset each time.  This function
    reads the existing snapshot, merges the new data, and writes back.
    """
    import json
    from pathlib import Path

    spark_dir = Path.home() / ".spark"
    spark_dir.mkdir(parents=True, exist_ok=True)
    out_path = spark_dir / "intake_snapshot.json"

    # Read existing snapshot to accumulate.
    existing: Dict[str, Any] = {}
    try:
        if out_path.exists():
            existing = json.loads(out_path.read_text(encoding="utf-8"))
    except Exception:
        existing = {}

    existing_stats = existing.get("stats", {})
    existing_decisions = existing.get("recent_decisions", [])

    # Merge stats additively (current process stats on top of persisted).
    merged_stats: Dict[str, Any] = {}
    all_keys = set(existing_stats.keys()) | set(_stats.keys())
    for k in all_keys:
        merged_stats[k] = existing_stats.get(k, 0) + _stats.get(k, 0)

    # Append new decisions, keep bounded at 200.
    merged_decisions = existing_decisions + list(_decision_log)
    if len(merged_decisions) > 200:
        merged_decisions = merged_decisions[-200:]

    snapshot = {
        "stats": merged_stats,
        "recent_decisions": merged_decisions,
        "snapshot_ts": time.time(),
    }
    try:
        out_path.write_text(json.dumps(snapshot, default=str), encoding="utf-8")
    except Exception:
        pass  # fail-open: dashboard visibility is nice-to-have


def reset_intake_filter_stats() -> None:
    """Reset all counters (useful for testing)."""
    _stats.clear()
    _stats.update({"total_events": 0, "queued": 0, "dropped": 0})
    _last_seen.clear()
    _decision_log.clear()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _accept() -> Tuple[bool, str]:
    _stats["queued"] = _stats.get("queued", 0) + 1
    return True, ""


def _drop(reason: str) -> Tuple[bool, str]:
    _stats["dropped"] = _stats.get("dropped", 0) + 1
    _stats[reason] = _stats.get(reason, 0) + 1
    return False, reason


def _is_bash_operational(cmd: str) -> bool:
    """Classify a Bash command as operational (zero learning signal).

    Handles:
    - Simple operational commands: curl, taskkill, ls, netstat, etc.
    - cd-chained commands: ``cd path && curl ...`` → check after &&
    - Diagnostic python one-liners: ``python -c "import json..."``
    """
    cmd = cmd.lstrip()
    if not cmd:
        return False

    # Strip leading ``cd ... &&`` or ``cd ... ;`` to find the real command.
    # e.g. ``cd /some/path && python test.py`` → ``python test.py``
    effective = cmd
    if effective.startswith("cd "):
        for sep in (" && ", " ; "):
            idx = effective.find(sep)
            if idx != -1:
                effective = effective[idx + len(sep):].lstrip()
                break
        else:
            # Pure ``cd path`` with no chained command — definitely operational.
            return True

    # Check against known operational prefixes.
    if any(effective.startswith(p) for p in _BASH_OPERATIONAL_PREFIXES):
        return True

    # Diagnostic python one-liners that just read/print data.
    if effective.startswith("python -c ") or effective.startswith("python3 -c "):
        low = effective.lower()
        # If it only does imports + reads + prints → operational.
        # If it writes files, modifies state → NOT operational.
        write_signals = ("write_text", "open(", ".write(", "mkdir", "remove", "unlink",
                         "shutil", "subprocess", "os.system")
        if not any(s in low for s in write_signals):
            return True

    return False


def _extract_context(
    tool_name: str, tool_input: Optional[Dict[str, Any]], data: Optional[Dict[str, Any]]
) -> str:
    """Extract a human-readable context string from tool_input/data.

    Shows WHAT the event is about — file path, command, pattern, etc.
    Stored in full with no truncation — the dashboard controls display.
    """
    if tool_input and isinstance(tool_input, dict):
        # File-based tools
        fp = tool_input.get("file_path") or ""
        if fp:
            return _clean(fp)
        # Bash command
        cmd = tool_input.get("command") or ""
        if cmd:
            return _clean(cmd)
        # Search/Glob pattern
        pat = tool_input.get("pattern") or ""
        path = tool_input.get("path") or ""
        if pat:
            ctx = pat
            if path:
                ctx = f"{pat} in {path}"
            return _clean(ctx)
        # Query-based tools
        query = tool_input.get("query") or tool_input.get("prompt") or ""
        if query:
            return _clean(query)
        # Fallback: first non-empty string value
        for v in tool_input.values():
            if isinstance(v, str) and v.strip():
                return _clean(v)

    # For non-tool events, pull from data
    if data and isinstance(data, dict):
        # STOP/SessionEnd: session segment summary injected by observe.py
        summary = data.get("session_summary") or ""
        if summary and isinstance(summary, str):
            return _clean(summary)
        # USER_PROMPT: user's message is in data.payload.text
        payload = data.get("payload")
        if isinstance(payload, dict):
            txt = payload.get("text") or ""
            if txt and isinstance(txt, str):
                return _clean(txt)
        # Generic fallback
        msg = data.get("message") or data.get("content") or data.get("text") or ""
        if msg and isinstance(msg, str):
            return _clean(msg)

    return ""


def _clean(s: str) -> str:
    """Clean string for storage — collapse whitespace, no truncation."""
    return s.replace("\r", "").replace("\n", " ").strip()


def _log_decision(
    event_type: str, tool_name: str, queued: bool, reason: str,
    tool_input: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """Append to bounded in-memory decision log for dashboard visibility."""
    _decision_log.append({
        "ts": time.time(),
        "event_type": str(event_type),
        "tool_name": tool_name or "",
        "queued": queued,
        "reason": reason,
        "context": _extract_context(tool_name, tool_input, data),
    })
    # Trim to max size.
    while len(_decision_log) > _DECISION_LOG_MAX:
        _decision_log.pop(0)


def _dupe_hash(tool_name: str, tool_input: Dict[str, Any]) -> str:
    """Fast hash for duplicate detection.  Not cryptographic, just identity."""
    # Use a subset of tool_input to avoid hashing huge payloads.
    key_parts = [tool_name]
    for k in sorted(tool_input.keys())[:5]:
        v = str(tool_input[k])[:200]
        key_parts.append(f"{k}={v}")
    raw = "|".join(key_parts)
    return hashlib.md5(raw.encode("utf-8", errors="replace")).hexdigest()[:12]


def _record_seen(dupe_key: str, ts: float) -> None:
    """Record a hash+timestamp, with bounded eviction."""
    _last_seen[dupe_key] = ts
    # Evict oldest entries when map grows too large.
    if len(_last_seen) > _LAST_SEEN_MAX:
        # Remove entries older than the dupe window.
        cutoff = ts - _DUPE_WINDOW_S * 2
        stale_keys = [k for k, v in _last_seen.items() if v < cutoff]
        for k in stale_keys:
            del _last_seen[k]
        # If still too large, just clear half (LRU-ish).
        if len(_last_seen) > _LAST_SEEN_MAX:
            to_remove = sorted(_last_seen.items(), key=lambda x: x[1])[
                : len(_last_seen) // 2
            ]
            for k, _ in to_remove:
                del _last_seen[k]
