from __future__ import annotations

import json
from unittest.mock import patch

import sparkd


def test_rate_limiter_enforces_window(monkeypatch):
    monkeypatch.setattr(sparkd, "RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(sparkd, "RATE_LIMIT_WINDOW_S", 60)
    sparkd._RATE_LIMIT_BUCKETS.clear()

    ok, retry = sparkd._allow_rate_limited_request("127.0.0.1", now=100.0)
    assert ok is True
    assert retry == 0

    ok, retry = sparkd._allow_rate_limited_request("127.0.0.1", now=101.0)
    assert ok is True
    assert retry == 0

    ok, retry = sparkd._allow_rate_limited_request("127.0.0.1", now=102.0)
    assert ok is False
    assert retry >= 1

    ok, retry = sparkd._allow_rate_limited_request("127.0.0.1", now=161.0)
    assert ok is True
    assert retry == 0


def test_invalid_quarantine_is_bounded(monkeypatch, tmp_path):
    quarantine = tmp_path / "invalid_events.jsonl"
    monkeypatch.setattr(sparkd, "INVALID_EVENTS_FILE", quarantine)
    monkeypatch.setattr(sparkd, "INVALID_EVENTS_MAX_LINES", 3)
    monkeypatch.setattr(sparkd, "INVALID_EVENTS_MAX_PAYLOAD_CHARS", 12)

    for i in range(5):
        sparkd._quarantine_invalid({"payload": "x" * 200, "i": i}, f"reason-{i}")

    lines = quarantine.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3

    rows = [json.loads(line) for line in lines]
    assert [row["reason"] for row in rows] == ["reason-2", "reason-3", "reason-4"]
    assert isinstance(rows[-1]["payload"], str)
    assert rows[-1]["payload"].endswith("...<truncated>")


def test_safe_float_returns_default_for_string(monkeypatch):
    """_safe_float must not swallow AttributeError or other unexpected exceptions."""
    assert sparkd._safe_float("not-a-float", default=3.5) == 3.5
    assert sparkd._safe_float(None, default=1.0) == 1.0
    assert sparkd._safe_float([], default=2.0) == 2.0


def test_safe_float_parses_valid_values():
    assert sparkd._safe_float("0.7") == 0.7
    assert sparkd._safe_float(1) == 1.0


def test_load_openclaw_runtime_config_corrupt_json_logs_and_returns_defaults(
    tmp_path, monkeypatch
):
    """When tuneables.json is corrupt, config must fall back to defaults and log."""
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(sparkd, "TUNEABLES_FILE", tuneables)
    monkeypatch.setattr(sparkd, "_OPENCLAW_RUNTIME_CFG_MTIME", None)
    monkeypatch.setattr(sparkd, "_OPENCLAW_RUNTIME_CFG_CACHE", dict(sparkd.OPENCLAW_RUNTIME_DEFAULTS))

    logged = []
    with patch("sparkd.log_debug", side_effect=lambda *a, **kw: logged.append(a)):
        cfg = sparkd._load_openclaw_runtime_config(force=True)

    # Defaults must be returned
    assert cfg == sparkd.OPENCLAW_RUNTIME_DEFAULTS
    # The failure must be logged (not silently swallowed)
    assert any("openclaw runtime config" in str(args).lower() for args in logged), (
        f"Expected log_debug call about config failure, got: {logged}"
    )


def test_load_openclaw_runtime_config_applies_valid_section(tmp_path, monkeypatch):
    """Valid openclaw_runtime section must override defaults."""
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "openclaw_runtime": {
                    "advisory_bridge_enabled": False,
                    "emotion_trigger_intensity": 0.3,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sparkd, "TUNEABLES_FILE", tuneables)
    monkeypatch.setattr(sparkd, "_OPENCLAW_RUNTIME_CFG_MTIME", None)
    monkeypatch.setattr(sparkd, "_OPENCLAW_RUNTIME_CFG_CACHE", dict(sparkd.OPENCLAW_RUNTIME_DEFAULTS))

    cfg = sparkd._load_openclaw_runtime_config(force=True)

    assert cfg["advisory_bridge_enabled"] is False
    assert cfg["emotion_trigger_intensity"] == 0.3
