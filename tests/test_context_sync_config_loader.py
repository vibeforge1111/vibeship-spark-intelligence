"""Tests for context_sync._load_sync_adapter_policy() exception specificity fixes."""
import json
from pathlib import Path

import pytest


def test_corrupt_json_logs_and_uses_default_mode(tmp_path, monkeypatch):
    """Corrupt tuneables.json should log via log_debug and fall back to 'core' mode."""
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text("not valid json {{ }", encoding="utf-8")

    import lib.context_sync as cs_mod

    monkeypatch.setattr(cs_mod, "TUNEABLES_FILE", tuneables)
    monkeypatch.delenv("SPARK_SYNC_MODE", raising=False)

    captured = []
    monkeypatch.setattr(
        cs_mod, "log_debug", lambda tag, msg, exc: captured.append((tag, msg, exc))
    )

    result = cs_mod._load_sync_adapter_policy()

    assert result["mode"] == "core"
    assert len(captured) == 1
    assert captured[0][0] == "context_sync"
    assert "tuneables" in captured[0][1]


def test_valid_sync_mode_applied(tmp_path, monkeypatch):
    """Valid tuneables.json with sync.mode='all' should activate all adapters."""
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(json.dumps({"sync": {"mode": "all"}}), encoding="utf-8")

    import lib.context_sync as cs_mod

    monkeypatch.setattr(cs_mod, "TUNEABLES_FILE", tuneables)
    monkeypatch.delenv("SPARK_SYNC_MODE", raising=False)
    monkeypatch.delenv("SPARK_SYNC_TARGETS", raising=False)

    result = cs_mod._load_sync_adapter_policy()

    assert result["mode"] == "all"
    assert set(cs_mod.ALL_SYNC_ADAPTERS).issubset(set(result["enabled"]))
