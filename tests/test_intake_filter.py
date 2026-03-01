"""Tests for lib/intake_filter.py — pre-queue event noise filter."""

import pytest
from lib.queue import EventType
from lib.intake_filter import (
    should_queue_event,
    get_intake_filter_stats,
    reset_intake_filter_stats,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_intake_filter_stats()
    yield
    reset_intake_filter_stats()


# ── Events that MUST always pass ────────────────────────────────

class TestAlwaysQueue:
    def test_user_prompt_always_queued(self):
        ok, reason = should_queue_event(EventType.USER_PROMPT, data={})
        assert ok is True and reason == ""

    def test_post_tool_failure_always_queued(self):
        ok, reason = should_queue_event(
            EventType.POST_TOOL_FAILURE, tool_name="Read", data={"error": "file not found"}
        )
        assert ok is True

    def test_session_start_always_queued(self):
        ok, _ = should_queue_event(EventType.SESSION_START, data={})
        assert ok is True

    def test_session_end_always_queued(self):
        ok, _ = should_queue_event(EventType.SESSION_END, data={})
        assert ok is True

    def test_stop_always_queued(self):
        ok, _ = should_queue_event(EventType.STOP, data={})
        assert ok is True

    def test_error_always_queued(self):
        ok, _ = should_queue_event(EventType.ERROR, data={})
        assert ok is True

    def test_learning_always_queued(self):
        ok, _ = should_queue_event(EventType.LEARNING, data={})
        assert ok is True


# ── Mutation tools always pass ──────────────────────────────────

class TestMutationTools:
    def test_edit_post_tool_queued(self):
        ok, _ = should_queue_event(EventType.POST_TOOL, tool_name="Edit", data={})
        assert ok is True

    def test_write_post_tool_queued(self):
        ok, _ = should_queue_event(EventType.POST_TOOL, tool_name="Write", data={})
        assert ok is True

    def test_bash_post_tool_queued(self):
        ok, _ = should_queue_event(EventType.POST_TOOL, tool_name="Bash", data={})
        assert ok is True

    def test_notebook_edit_queued(self):
        ok, _ = should_queue_event(EventType.POST_TOOL, tool_name="NotebookEdit", data={})
        assert ok is True


# ── Read-only tool successes dropped ────────────────────────────

class TestReadOnlyDropped:
    def test_read_success_dropped(self):
        ok, reason = should_queue_event(EventType.POST_TOOL, tool_name="Read", data={})
        assert ok is False
        assert reason == "read_success_noop"

    def test_glob_success_dropped(self):
        ok, reason = should_queue_event(EventType.POST_TOOL, tool_name="Glob", data={})
        assert ok is False
        assert reason == "read_success_noop"  # all read-only tools share same code

    def test_grep_success_dropped(self):
        ok, reason = should_queue_event(EventType.POST_TOOL, tool_name="Grep", data={})
        assert ok is False
        assert reason == "read_success_noop"

    def test_read_with_error_queued(self):
        """Read that had an error should still be queued."""
        ok, _ = should_queue_event(
            EventType.POST_TOOL, tool_name="Read", data={"error": "permission denied"}
        )
        assert ok is True


# ── PRE_TOOL filtering ──────────────────────────────────────────

class TestPreTool:
    def test_pretool_read_dropped(self):
        ok, reason = should_queue_event(EventType.PRE_TOOL, tool_name="Read", data={})
        assert ok is False
        assert reason == "pretool_read_noop"

    def test_pretool_glob_dropped(self):
        ok, reason = should_queue_event(EventType.PRE_TOOL, tool_name="Glob", data={})
        assert ok is False

    def test_pretool_edit_queued(self):
        ok, _ = should_queue_event(EventType.PRE_TOOL, tool_name="Edit", data={})
        assert ok is True

    def test_pretool_bash_queued(self):
        ok, _ = should_queue_event(EventType.PRE_TOOL, tool_name="Bash", data={})
        assert ok is True


# ── Low readiness dropped ──────────────────────────────────────

class TestLowReadiness:
    def test_low_readiness_dropped(self):
        ok, reason = should_queue_event(
            EventType.POST_TOOL,
            tool_name="SomeUnknownTool",
            data={"advisory": {"readiness_hint": 0.05}},
        )
        assert ok is False
        assert reason == "low_readiness_noop"

    def test_low_readiness_with_error_queued(self):
        ok, _ = should_queue_event(
            EventType.POST_TOOL,
            tool_name="SomeUnknownTool",
            data={"advisory": {"readiness_hint": 0.05}, "error": "something failed"},
        )
        assert ok is True

    def test_normal_readiness_queued(self):
        ok, _ = should_queue_event(
            EventType.POST_TOOL,
            tool_name="SomeUnknownTool",
            data={"advisory": {"readiness_hint": 0.50}},
        )
        assert ok is True


# ── Consecutive duplicate detection ─────────────────────────────

class TestDuplicateDetection:
    def test_consecutive_dupe_dropped(self):
        tool_input = {"file_path": "/some/file.py"}
        # First call should pass (unknown tool, normal readiness).
        ok1, _ = should_queue_event(
            EventType.POST_TOOL,
            tool_name="CustomTool",
            tool_input=tool_input,
            data={"advisory": {"readiness_hint": 0.5}},
        )
        # Second call within 2s should be dropped as dupe.
        ok2, reason = should_queue_event(
            EventType.POST_TOOL,
            tool_name="CustomTool",
            tool_input=tool_input,
            data={"advisory": {"readiness_hint": 0.5}},
        )
        assert ok1 is True
        assert ok2 is False
        assert reason == "consecutive_dupe"


# ── Stats tracking ──────────────────────────────────────────────

class TestStats:
    def test_stats_increment(self):
        should_queue_event(EventType.USER_PROMPT, data={})
        should_queue_event(EventType.POST_TOOL, tool_name="Read", data={})
        stats = get_intake_filter_stats()
        assert stats["total_events"] == 2
        assert stats["queued"] == 1
        assert stats["dropped"] == 1
        assert stats.get("read_success_noop", 0) == 1
