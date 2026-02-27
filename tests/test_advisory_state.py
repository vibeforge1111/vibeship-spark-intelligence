from __future__ import annotations

import time

from lib.runtime_session_state import (
    SessionState,
    apply_state_gate_config,
    get_shown_advice_ttl_s,
    is_tool_suppressed,
    resolve_recent_trace_id,
    suppress_tool_advice,
)


def test_resolve_recent_trace_id_prefers_unresolved_pre_tool_call():
    now = time.time()
    state = SessionState(
        session_id="s1",
        recent_tools=[
            {
                "tool_name": "Edit",
                "timestamp": now - 4,
                "success": True,
                "trace_id": "trace-post",
            },
            {
                "tool_name": "Edit",
                "timestamp": now - 2,
                "success": None,
                "trace_id": "trace-pre",
            },
        ],
    )

    assert resolve_recent_trace_id(state, "Edit") == "trace-pre"


def test_resolve_recent_trace_id_ignores_stale_entries():
    now = time.time()
    state = SessionState(
        session_id="s2",
        recent_tools=[
            {
                "tool_name": "Bash",
                "timestamp": now - 900,
                "success": None,
                "trace_id": "trace-old",
            }
        ],
    )

    assert resolve_recent_trace_id(state, "Bash", max_age_s=120) is None


def test_apply_state_gate_config_updates_shown_ttl_and_alias():
    original = get_shown_advice_ttl_s()
    try:
        result = apply_state_gate_config({"shown_advice_ttl_s": 42})
        assert "shown_advice_ttl_s" in result["applied"]
        assert get_shown_advice_ttl_s() == 42

        result_alias = apply_state_gate_config({"advice_repeat_cooldown_s": 77})
        assert "shown_advice_ttl_s" in result_alias["applied"]
        assert get_shown_advice_ttl_s() == 77
    finally:
        apply_state_gate_config({"shown_advice_ttl_s": original})


def test_tool_suppression_supports_structured_entries_and_scale():
    now = time.time()
    state = SessionState(
        session_id="s3",
        suppressed_tools={
            "Edit": {"started_at": now - 8, "duration_s": 10, "until": now + 2}
        },
    )

    assert is_tool_suppressed(state, "Edit", cooldown_scale=1.0) is True
    assert is_tool_suppressed(state, "Edit", cooldown_scale=0.5) is False


def test_tool_suppression_legacy_timestamp_still_supported():
    state = SessionState(session_id="s4")
    suppress_tool_advice(state, "Read", duration_s=0.2)
    assert is_tool_suppressed(state, "Read") is True
