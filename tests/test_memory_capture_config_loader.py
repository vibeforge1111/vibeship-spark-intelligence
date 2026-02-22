"""Regression tests for memory_capture config loader exception specificity.

Before the fix:
- _load_memory_capture_config() caught bare Exception with no log entry.
- Three float()/int() conversions in _apply_memory_capture_config() caught
  bare Exception, masking attribute errors in surrounding code.
"""
from __future__ import annotations

import json

import lib.memory_capture as mc


def test_load_memory_capture_config_returns_section(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps({"memory_capture": {"auto_save_threshold": 0.75}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(mc, "TUNEABLES_FILE", tuneables)
    result = mc._load_memory_capture_config()
    assert result["auto_save_threshold"] == 0.75


def test_load_memory_capture_config_corrupt_json_returns_empty_and_logs(monkeypatch, tmp_path):
    """Corrupt tuneables.json must return {} and call log_debug."""
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text("{bad json!!!", encoding="utf-8")
    monkeypatch.setattr(mc, "TUNEABLES_FILE", tuneables)

    logged = []

    def _capture(component, message, exc=None):
        logged.append((component, message))

    monkeypatch.setattr(mc, "log_debug", _capture)

    result = mc._load_memory_capture_config()

    assert result == {}, f"Expected empty dict for corrupt JSON; got {result!r}"
    assert logged, "Expected log_debug to be called for corrupt tuneables.json"


def test_apply_memory_capture_config_invalid_float_adds_warning():
    """Non-numeric auto_save_threshold must add a warning and leave global unchanged."""
    original = mc.AUTO_SAVE_THRESHOLD
    result = mc._apply_memory_capture_config({"auto_save_threshold": "not-a-number"})
    assert "invalid_auto_save_threshold" in result["warnings"]
    assert mc.AUTO_SAVE_THRESHOLD == original


def test_apply_memory_capture_config_invalid_int_adds_warning():
    """Non-numeric max_capture_chars must add a warning and leave global unchanged."""
    original = mc.MAX_CAPTURE_CHARS
    result = mc._apply_memory_capture_config({"max_capture_chars": "bad"})
    assert "invalid_max_capture_chars" in result["warnings"]
    assert mc.MAX_CAPTURE_CHARS == original


def test_apply_memory_capture_config_valid_values_applied():
    """Valid config values must be applied and listed in 'applied'."""
    result = mc._apply_memory_capture_config(
        {"auto_save_threshold": 0.8, "max_capture_chars": 5000}
    )
    assert "auto_save_threshold" in result["applied"]
    assert "max_capture_chars" in result["applied"]
    assert mc.AUTO_SAVE_THRESHOLD == 0.8
    assert mc.MAX_CAPTURE_CHARS == 5000
