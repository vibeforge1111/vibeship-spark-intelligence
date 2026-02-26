"""Regression tests for advisory_synthesizer._load_synth_config error handling.

Before the fix, _load_synth_config() caught bare Exception with no logging,
making corrupt tuneables.json completely invisible in production.
"""
from __future__ import annotations

import json
import logging

import lib.advisory_synthesizer as synth_mod


def test_load_synth_config_returns_synthesizer_section(tmp_path, monkeypatch):
    cfg_file = tmp_path / "tuneables.json"
    cfg_file.write_text(
        json.dumps({"synthesizer": {"mode": "full", "cache_ttl_s": 60}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(synth_mod, "SYNTH_CONFIG_FILE", cfg_file)
    result = synth_mod._load_synth_config()
    assert result["mode"] == "full"
    assert result["cache_ttl_s"] == 60


def test_load_synth_config_corrupt_json_returns_empty_and_logs(tmp_path, monkeypatch):
    """Corrupt tuneables.json must return {} and emit a log via log_debug."""
    cfg_file = tmp_path / "tuneables.json"
    cfg_file.write_text("{bad json!!!", encoding="utf-8")
    monkeypatch.setattr(synth_mod, "SYNTH_CONFIG_FILE", cfg_file)

    logged = []

    def _capture_log(component, message, exc=None):
        logged.append((component, message))

    monkeypatch.setattr(synth_mod, "log_debug", _capture_log)

    result = synth_mod._load_synth_config()

    assert result == {}, f"Expected empty dict for corrupt JSON; got {result!r}"
    assert any(
        "synth" in comp or "synth" in msg.lower() or "config" in msg.lower()
        for comp, msg in logged
    ), f"Expected a log entry about config failure; got: {logged}"
