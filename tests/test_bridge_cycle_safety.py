"""
Safety-net tests for bridge_cycle.py — run_bridge_cycle() behavior.

These tests verify the bridge cycle's orchestration, fail-open behavior,
and batch mode management. They use mocking to avoid hitting disk or
requiring real queue data.

Usage:
    pytest tests/test_bridge_cycle_safety.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── run_bridge_cycle with empty events ────────────────────────────────

def test_bridge_cycle_empty_events():
    """run_bridge_cycle should handle empty event list without crashing."""
    with patch("lib.bridge_cycle.read_recent_events", return_value=[]):
        with patch("lib.bridge_cycle.update_spark_context", return_value=(True, {}, None)):
            with patch("lib.bridge_cycle.process_recent_memory_events", return_value={"auto_saved": 0, "suggested": 0}):
                from lib.bridge_cycle import run_bridge_cycle
                stats = run_bridge_cycle(memory_limit=5, pattern_limit=5)

    assert isinstance(stats, dict)
    assert "errors" in stats
    assert "timestamp" in stats


# ── Stats structure ───────────────────────────────────────────────────

def test_bridge_cycle_returns_expected_keys():
    """Stats dict should contain all expected keys."""
    with patch("lib.bridge_cycle.read_recent_events", return_value=[]):
        with patch("lib.bridge_cycle.update_spark_context", return_value=(True, {}, None)):
            with patch("lib.bridge_cycle.process_recent_memory_events", return_value={"auto_saved": 0, "suggested": 0}):
                from lib.bridge_cycle import run_bridge_cycle
                stats = run_bridge_cycle(memory_limit=5, pattern_limit=5)

    expected_keys = ["timestamp", "context_updated", "memory", "errors"]
    for key in expected_keys:
        assert key in stats, f"Expected key '{key}' in stats"


# ── Fail-open behavior ───────────────────────────────────────────────

def test_bridge_cycle_survives_context_failure():
    """If context update fails, cycle should continue (fail-open)."""
    with patch("lib.bridge_cycle.read_recent_events", return_value=[]):
        with patch("lib.bridge_cycle.update_spark_context", side_effect=Exception("context boom")):
            with patch("lib.bridge_cycle.process_recent_memory_events", return_value={"auto_saved": 0, "suggested": 0}):
                from lib.bridge_cycle import run_bridge_cycle
                stats = run_bridge_cycle(memory_limit=5, pattern_limit=5)

    # Should not crash — fail-open behavior
    assert isinstance(stats, dict)
    assert "context" in stats.get("errors", [])


def test_bridge_cycle_survives_memory_failure():
    """If memory capture fails, cycle should continue (fail-open)."""
    with patch("lib.bridge_cycle.read_recent_events", return_value=[]):
        with patch("lib.bridge_cycle.update_spark_context", return_value=(True, {}, None)):
            with patch("lib.bridge_cycle.process_recent_memory_events", side_effect=Exception("memory boom")):
                from lib.bridge_cycle import run_bridge_cycle
                stats = run_bridge_cycle(memory_limit=5, pattern_limit=5)

    assert isinstance(stats, dict)


# ── Batch mode management ────────────────────────────────────────────

def test_bridge_cycle_calls_batch_mode():
    """Verify cognitive learner and meta_ralph get begin_batch/end_batch calls."""
    mock_cognitive = MagicMock()
    mock_ralph = MagicMock()

    with patch("lib.bridge_cycle.read_recent_events", return_value=[]):
        with patch("lib.bridge_cycle.update_spark_context", return_value=(True, {}, None)):
            with patch("lib.bridge_cycle.process_recent_memory_events", return_value={"auto_saved": 0, "suggested": 0}):
                # These are imported inside run_bridge_cycle via `from lib.cognitive_learner import ...`
                with patch("lib.cognitive_learner.get_cognitive_learner", return_value=mock_cognitive):
                    with patch("lib.meta_ralph.get_meta_ralph", return_value=mock_ralph):
                        from lib.bridge_cycle import run_bridge_cycle
                        run_bridge_cycle(memory_limit=5, pattern_limit=5)

    # begin_batch should have been called
    mock_cognitive.begin_batch.assert_called()
    mock_ralph.begin_batch.assert_called()


# ── _run_step helper ──────────────────────────────────────────────────

def test_run_step_exists_and_callable():
    """Verify _run_step helper function exists."""
    from lib.bridge_cycle import _run_step
    assert callable(_run_step)


def test_run_step_returns_triple():
    """_run_step should return (ok, result, error) triple."""
    from lib.bridge_cycle import _run_step

    ok, result, error = _run_step("test_step", lambda: {"key": "value"})
    assert isinstance(ok, bool)
    if ok:
        assert result == {"key": "value"}
        assert error == ""  # empty string, not None


def test_run_step_handles_exception():
    """_run_step should catch exceptions and return (False, None, error_str)."""
    from lib.bridge_cycle import _run_step

    def boom():
        raise ValueError("test explosion")

    ok, result, error = _run_step("test_boom", boom)
    assert not ok
    assert error is not None


def test_chip_events_filtered_to_project_path_when_cwd_present():
    from lib.bridge_cycle import _filter_chip_events_for_project

    chip_events = [
        {"cwd": "C:/repo/a", "event_type": "post_tool"},
        {"cwd": "C:/repo/a/src", "event_type": "post_tool"},
        {"cwd": "C:/repo/b", "event_type": "post_tool"},
        {"cwd": "", "event_type": "post_tool"},
    ]

    filtered, meta = _filter_chip_events_for_project(chip_events, "C:/repo/a")
    assert len(filtered) == 2
    assert meta["enabled"] is True
    assert meta["fallback_used"] is False
    assert meta["filtered_events"] == 2


def test_chip_events_filter_fails_open_when_no_matching_cwd():
    from lib.bridge_cycle import _filter_chip_events_for_project

    chip_events = [
        {"cwd": "C:/repo/x", "event_type": "post_tool"},
        {"cwd": "C:/repo/y", "event_type": "post_tool"},
    ]

    filtered, meta = _filter_chip_events_for_project(chip_events, "C:/repo/a")
    assert len(filtered) == len(chip_events)
    assert meta["enabled"] is True
    assert meta["fallback_used"] is True
    assert meta["reason"] == "no_matching_cwd_fallback"


def test_chip_events_no_project_path_keeps_all():
    from lib.bridge_cycle import _filter_chip_events_for_project

    chip_events = [
        {"cwd": "C:/repo/a", "event_type": "post_tool"},
        {"cwd": "C:/repo/b", "event_type": "post_tool"},
    ]

    filtered, meta = _filter_chip_events_for_project(chip_events, None)
    assert len(filtered) == len(chip_events)
    assert meta["enabled"] is False
    assert meta["fallback_used"] is False
    assert meta["reason"] == "no_project_path"
