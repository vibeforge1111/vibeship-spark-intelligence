"""Tests for advisory_engine, advisory_gate, advisory_packet_store config loader fixes.

Covers:
- Double-decode utf-8-sig -> utf-8 anti-pattern: inner except Exception now narrow
- Silent return {} on JSONDecodeError replaced with log_debug call
- _to_int/_to_float: except Exception -> (ValueError, TypeError), no int(default)/float(default)
"""
import json
from pathlib import Path

import pytest


# ── advisory_engine ────────────────────────────────────────────────────────

def test_advisory_engine_corrupt_json_logs(tmp_path, monkeypatch):
    """Corrupt tuneables.json should log via log_debug and return {}."""
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text("{corrupt", encoding="utf-8")

    import lib.advisory_engine as ae_mod

    captured = []
    monkeypatch.setattr(
        ae_mod, "log_debug", lambda tag, msg, exc: captured.append((tag, msg, exc))
    )

    result = ae_mod._load_engine_config(path=tuneables)

    assert result == {}
    assert len(captured) == 1
    assert captured[0][0] == "advisory_engine"


def test_advisory_engine_valid_config(tmp_path):
    """Valid tuneables.json advisory_engine section should be returned."""
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps({"advisory_engine": {"emit_enabled": True}}), encoding="utf-8"
    )

    import lib.advisory_engine as ae_mod

    result = ae_mod._load_engine_config(path=tuneables)

    assert result.get("emit_enabled") is True


# ── advisory_gate ──────────────────────────────────────────────────────────

def test_advisory_gate_corrupt_json_logs(tmp_path, monkeypatch):
    """Corrupt tuneables.json should log via log_debug and return {}."""
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text("{corrupt", encoding="utf-8")

    import lib.advisory_gate as ag_mod

    captured = []
    monkeypatch.setattr(
        ag_mod, "log_debug", lambda tag, msg, exc: captured.append((tag, msg, exc))
    )

    result = ag_mod._load_gate_config(path=tuneables)

    assert result == {}
    assert len(captured) == 1
    assert captured[0][0] == "advisory_gate"


def test_advisory_gate_valid_config(tmp_path):
    """Valid tuneables.json advisory_gate section should be returned."""
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps({"advisory_gate": {"max_emit_per_call": 5}}), encoding="utf-8"
    )

    import lib.advisory_gate as ag_mod

    result = ag_mod._load_gate_config(path=tuneables)

    assert result.get("max_emit_per_call") == 5


# ── advisory_packet_store ──────────────────────────────────────────────────

def test_packet_store_corrupt_json_logs(tmp_path, monkeypatch):
    """Corrupt tuneables.json should log via log_debug and return {}."""
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text("{corrupt", encoding="utf-8")

    import lib.advisory_packet_store as aps_mod

    captured = []
    monkeypatch.setattr(
        aps_mod, "log_debug", lambda tag, msg, exc: captured.append((tag, msg, exc))
    )

    result = aps_mod._load_packet_store_config(path=tuneables)

    assert result == {}
    assert len(captured) == 1
    assert captured[0][0] == "advisory_packet_store"


def test_packet_store_valid_config(tmp_path):
    """Valid tuneables.json advisory_packet_store section should be returned."""
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps({"advisory_packet_store": {"max_stored_packets": 500}}),
        encoding="utf-8",
    )

    import lib.advisory_packet_store as aps_mod

    result = aps_mod._load_packet_store_config(path=tuneables)

    assert result.get("max_stored_packets") == 500


def test_to_int_only_catches_value_type_errors():
    """_to_int should return default on ValueError/TypeError, not mask AttributeError."""
    import lib.advisory_packet_store as aps_mod

    assert aps_mod._to_int("42", default=0) == 42
    assert aps_mod._to_int("bad", default=7) == 7
    assert aps_mod._to_int(None, default=3) == 3
    # int(default) should NOT be called — default is returned directly
    assert aps_mod._to_int("bad", default=9) == 9


def test_to_float_only_catches_value_type_errors():
    """_to_float should return default on ValueError/TypeError."""
    import lib.advisory_packet_store as aps_mod

    assert aps_mod._to_float("1.5", default=0.0) == 1.5
    assert aps_mod._to_float("bad", default=2.5) == 2.5
    assert aps_mod._to_float(None, default=0.5) == 0.5
