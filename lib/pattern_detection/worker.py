"""Pattern detection worker: process queued events outside hooks."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from lib.queue import read_events, count_events, EventType
from .aggregator import get_aggregator


STATE_FILE = Path.home() / ".spark" / "pattern_detection_state.json"


def _load_state() -> Dict:
    if not STATE_FILE.exists():
        return {"offset": 0}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"offset": 0}


def _save_state(state: Dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=STATE_FILE.parent, suffix=".tmp")
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, STATE_FILE)


def _hook_event_from_type(event_type: EventType) -> str:
    mapping = {
        EventType.USER_PROMPT: "UserPromptSubmit",
        EventType.PRE_TOOL: "PreToolUse",
        EventType.POST_TOOL: "PostToolUse",
        EventType.POST_TOOL_FAILURE: "PostToolUseFailure",
        EventType.SESSION_START: "SessionStart",
        EventType.SESSION_END: "SessionEnd",
    }
    return mapping.get(event_type, "Unknown")


def process_pattern_events(limit: int = 200) -> int:
    """Process new queued events and run pattern detection.

    NOTE: When the pipeline's ``consume_processed()`` removes events from
    the head of the queue, the total line count shrinks.  We detect this
    and reset the offset so we don't skip events or stall.
    """
    state = _load_state()
    offset = int(state.get("offset", 0))

    # Handle queue rotation, truncation, or consumption
    total = count_events()
    if total < offset:
        # Queue was consumed or rotated -- reset offset relative to new size
        offset = max(0, total - limit)

    events = read_events(limit=limit, offset=offset)
    if not events:
        # If the offset is stale and there are events, reset to 0
        if total > 0 and offset > 0:
            state["offset"] = 0
            _save_state(state)
        return 0

    aggregator = get_aggregator()
    processed = 0

    for ev in events:
        hook_event = (ev.data or {}).get("hook_event") or _hook_event_from_type(ev.event_type)
        payload = (ev.data or {}).get("payload")

        pattern_event = {
            "session_id": ev.session_id,
            "hook_event": hook_event,
            "tool_name": ev.tool_name,
            "tool_input": ev.tool_input,
            "payload": payload,
        }
        trace_id = (ev.data or {}).get("trace_id")
        if trace_id:
            pattern_event["trace_id"] = trace_id

        if ev.error:
            pattern_event["error"] = ev.error

        patterns = aggregator.process_event(pattern_event)
        if patterns:
            aggregator.trigger_learning(patterns)

        processed += 1

    state["offset"] = offset + processed
    _save_state(state)
    return processed


def reset_offset() -> None:
    """Reset the pattern detection offset to 0.

    Called after queue consumption to keep the offset in sync.
    """
    state = _load_state()
    state["offset"] = 0
    _save_state(state)


def get_pattern_backlog() -> int:
    """Return the count of queued events not yet processed by pattern detection."""
    state = _load_state()
    try:
        offset = int(state.get("offset", 0))
    except Exception:
        offset = 0
    total = count_events()
    if total < offset:
        offset = total
    return max(0, total - offset)

