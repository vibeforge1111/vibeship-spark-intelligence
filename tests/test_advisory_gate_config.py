from __future__ import annotations

import json
from unittest.mock import patch

import lib.advisory_gate as gate


def test_load_gate_config_reads_advisory_gate_section(tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "advisor": {"max_items": 4},
                "advisory_gate": {
                    "max_emit_per_call": 2,
                    "tool_cooldown_s": 120,
                    "advice_repeat_cooldown_s": 2400,
                },
            }
        ),
        encoding="utf-8",
    )

    cfg = gate._load_gate_config(path=tuneables)

    assert cfg["max_emit_per_call"] == 2
    assert cfg["tool_cooldown_s"] == 120
    assert cfg["advice_repeat_cooldown_s"] == 2400


def test_apply_gate_config_updates_runtime_values():
    original = gate.get_gate_config()
    try:
        result = gate.apply_gate_config(
            {
                "max_emit_per_call": 2,
                "tool_cooldown_s": 180,
                "advice_repeat_cooldown_s": 7200,
                "warning_threshold": 0.82,
                "note_threshold": 0.52,
                "whisper_threshold": 0.36,
            }
        )
        cfg = gate.get_gate_config()

        assert "max_emit_per_call" in result["applied"]
        assert "tool_cooldown_s" in result["applied"]
        assert "advice_repeat_cooldown_s" in result["applied"]
        assert cfg["max_emit_per_call"] == 2
        assert cfg["tool_cooldown_s"] == 180
        assert cfg["advice_repeat_cooldown_s"] == 7200
        assert cfg["warning_threshold"] == 0.82
        assert cfg["note_threshold"] == 0.52
        assert cfg["whisper_threshold"] == 0.36
    finally:
        gate.apply_gate_config(original)


def test_load_gate_config_invalid_json_logs_and_returns_empty(tmp_path):
    """A corrupt tuneables.json must log and return {}, not silently swallow.

    Regression test: the original code caught all exceptions in the outer
    try block including json.JSONDecodeError, then retried with 'utf-8'
    encoding (which reads the same bytes and fails identically), then
    returned {} with no log — making config corruption invisible.
    """
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text("{this is not valid json", encoding="utf-8")

    logged = []

    def fake_log(module, msg, exc=None):
        logged.append((module, msg))

    with patch("lib.advisory_gate.log_debug", side_effect=fake_log):
        result = gate._load_gate_config(path=tuneables)

    assert result == {}, "Should return empty dict on parse failure"
    assert any("advisory_gate" in m[0] and "gate config" in m[1] for m in logged), (
        "Expected a log_debug call when gate config cannot be parsed. "
        "Silent failure makes tuneables.json corruption invisible to operators."
    )


def test_load_gate_config_no_double_read_on_json_error(tmp_path):
    """Invalid JSON must NOT trigger a second file read with utf-8 encoding.

    Regression test: the original code caught json.JSONDecodeError in the
    outer except and then retried read_text(encoding='utf-8'), wasting an
    I/O round-trip that cannot fix a JSON syntax error.
    """
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text("{bad json", encoding="utf-8")

    read_calls = []
    original_read_text = tuneables.__class__.read_text

    def counting_read_text(self, **kwargs):
        read_calls.append(kwargs.get("encoding"))
        return original_read_text(self, **kwargs)

    with patch.object(tuneables.__class__, "read_text", counting_read_text):
        gate._load_gate_config(path=tuneables)

    assert len(read_calls) == 1, (
        f"Expected exactly 1 file read for a JSON parse error, got {len(read_calls)}. "
        "The utf-8 fallback must only fire on UnicodeDecodeError, not JSONDecodeError."
    )


def test_apply_gate_config_invalid_int_adds_warning_not_raises(tmp_path):
    """Non-numeric config values must append a warning, not raise Exception.

    Verifies that the except clause is narrow enough to only catch
    (ValueError, TypeError) from int() — the only exceptions it can raise.

    Note: empty/falsy values like [] or None are handled by the `or` fallback
    in expressions like `int(cfg.get(...) or 1)`, so non-falsy invalid strings
    are used here to trigger ValueError from int().
    """
    original = gate.get_gate_config()
    try:
        result = gate.apply_gate_config({
            "max_emit_per_call": "not-a-number",
            "tool_cooldown_s": "bad-value",
            "advice_repeat_cooldown_s": "also-bad",
        })
        assert "invalid_max_emit_per_call" in result["warnings"]
        assert "invalid_tool_cooldown_s" in result["warnings"]
        assert "invalid_advice_repeat_cooldown_s" in result["warnings"]
        # Runtime values must remain unchanged when config is invalid
        cfg = gate.get_gate_config()
        assert cfg["max_emit_per_call"] == original["max_emit_per_call"]
    finally:
        gate.apply_gate_config(original)
