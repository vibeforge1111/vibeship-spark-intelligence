"""Regression tests for queue config loader exception specificity.

Before the fix:
- _load_queue_config() caught bare Exception with no logging.
- _apply_queue_config() caught bare Exception for int() conversions.

After the fix:
- _load_queue_config() logs via log_debug() and narrows to JSON/OS errors.
- _apply_queue_config() narrows to (ValueError, TypeError) for int() calls.
"""
from __future__ import annotations

import json

import lib.queue as queue_mod


def test_load_queue_config_returns_queue_section(tmp_path, monkeypatch):
    cfg_file = tmp_path / "tuneables.json"
    cfg_file.write_text(
        json.dumps({"queue": {"max_events": 5000, "tail_chunk_bytes": 8192}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(queue_mod, "TUNEABLES_FILE", cfg_file)
    result = queue_mod._load_queue_config()
    assert result["max_events"] == 5000
    assert result["tail_chunk_bytes"] == 8192


def test_load_queue_config_corrupt_json_returns_empty_and_logs(tmp_path, monkeypatch):
    """Corrupt tuneables.json must return {} and emit a log_debug entry."""
    cfg_file = tmp_path / "tuneables.json"
    cfg_file.write_text("{bad json!!!", encoding="utf-8")
    monkeypatch.setattr(queue_mod, "TUNEABLES_FILE", cfg_file)

    logged = []

    def _capture(component, message, exc=None):
        logged.append((component, message))

    monkeypatch.setattr(queue_mod, "log_debug", _capture)
    result = queue_mod._load_queue_config()

    assert result == {}, f"Expected empty dict for corrupt JSON; got {result!r}"
    assert logged, "Expected log_debug to be called for corrupt tuneables.json"


def test_apply_queue_config_invalid_max_events_adds_warning(monkeypatch):
    """Non-numeric max_events must add 'invalid_max_events' to warnings."""
    original_max = queue_mod.MAX_EVENTS
    result = queue_mod._apply_queue_config({"max_events": "not-a-number"})
    assert "invalid_max_events" in result["warnings"]
    assert queue_mod.MAX_EVENTS == original_max  # unchanged


def test_apply_queue_config_valid_max_events_applied(monkeypatch):
    """Valid numeric max_events must be applied and appear in 'applied'."""
    queue_mod._apply_queue_config({"max_events": 2500})
    result = queue_mod._apply_queue_config({"max_events": 2500})
    assert "max_events" in result["applied"]
    assert queue_mod.MAX_EVENTS == 2500
