"""Regression tests for chip_merger._load_merge_tuneables exception specificity.

Before the fix:
- _load_merge_tuneables() caught bare Exception on json.loads(), silently
  discarding all config with no log entry.
- Seven float()/int() conversions caught bare Exception, masking attribute
  errors and other real bugs in surrounding code.
"""
from __future__ import annotations

import json

import lib.chip_merger as cm


def test_load_merge_tuneables_returns_defaults_on_missing_file(monkeypatch, tmp_path):
    missing = tmp_path / "tuneables.json"
    monkeypatch.setattr(cm, "TUNEABLES_FILE", missing)
    result = cm._load_merge_tuneables()
    # Should return defaults without crashing
    assert "min_cognitive_value" in result
    assert "duplicate_churn_ratio" in result


def test_load_merge_tuneables_applies_chip_merge_section(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps({"chip_merge": {"min_cognitive_value": 0.55, "min_statement_len": 40}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cm, "TUNEABLES_FILE", tuneables)
    result = cm._load_merge_tuneables()
    assert result["min_cognitive_value"] == 0.55
    assert result["min_statement_len"] == 40


def test_load_merge_tuneables_corrupt_json_logs_and_uses_defaults(monkeypatch, tmp_path):
    """Corrupt tuneables.json must call log_debug and return defaults."""
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text("{bad json!!!", encoding="utf-8")
    monkeypatch.setattr(cm, "TUNEABLES_FILE", tuneables)

    logged = []

    def _capture(component, message, exc=None):
        logged.append((component, message))

    monkeypatch.setattr(cm, "log_debug", _capture)

    result = cm._load_merge_tuneables()

    assert logged, "Expected log_debug to be called for corrupt tuneables.json"
    assert "chip_merge" in result or "min_cognitive_value" in result


def test_load_merge_tuneables_invalid_float_uses_default(monkeypatch, tmp_path):
    """Non-numeric float value must fall back to default without crashing."""
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps({"chip_merge": {"min_cognitive_value": "not-a-number"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cm, "TUNEABLES_FILE", tuneables)
    result = cm._load_merge_tuneables()
    # Should use the hard-coded default (0.35), not crash
    assert result["min_cognitive_value"] == 0.35
