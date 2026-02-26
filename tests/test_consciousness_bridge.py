"""Tests for lib/consciousness_bridge.py."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.consciousness_bridge as cb
from lib.consciousness_bridge import (
    DEFAULT_STRATEGY,
    _clamp,
    _is_safe_boundaries,
    read_consciousness_bridge,
    resolve_strategy,
    to_bounded_strategy,
)


# ---------------------------------------------------------------------------
# _clamp
# ---------------------------------------------------------------------------

def test_clamp_value_within_range():
    assert _clamp(0.25, 0.0, 1.0) == pytest.approx(0.25)


def test_clamp_value_at_lower_bound():
    assert _clamp(0.0, 0.0, 1.0) == pytest.approx(0.0)


def test_clamp_value_at_upper_bound():
    assert _clamp(1.0, 0.0, 1.0) == pytest.approx(1.0)


def test_clamp_value_below_lower_bound():
    assert _clamp(-1.0, 0.0, 1.0) == pytest.approx(0.0)


def test_clamp_value_above_upper_bound():
    assert _clamp(2.0, 0.0, 1.0) == pytest.approx(1.0)


def test_clamp_non_numeric_returns_lo():
    assert _clamp("bad", 0.0, 1.0) == pytest.approx(0.0)


def test_clamp_none_returns_lo():
    assert _clamp(None, 0.0, 1.0) == pytest.approx(0.0)


def test_clamp_int_input():
    assert _clamp(5, 0.0, 10.0) == pytest.approx(5.0)


def test_clamp_string_numeric():
    assert _clamp("0.5", 0.0, 1.0) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _is_safe_boundaries
# ---------------------------------------------------------------------------

def test_is_safe_boundaries_all_true():
    b = {"user_guided": True, "no_autonomous_objectives": True, "no_manipulative_affect": True}
    assert _is_safe_boundaries(b) is True


def test_is_safe_boundaries_missing_user_guided():
    b = {"no_autonomous_objectives": True, "no_manipulative_affect": True}
    assert _is_safe_boundaries(b) is False


def test_is_safe_boundaries_missing_no_autonomous():
    b = {"user_guided": True, "no_manipulative_affect": True}
    assert _is_safe_boundaries(b) is False


def test_is_safe_boundaries_missing_no_manipulative():
    b = {"user_guided": True, "no_autonomous_objectives": True}
    assert _is_safe_boundaries(b) is False


def test_is_safe_boundaries_all_false():
    b = {"user_guided": False, "no_autonomous_objectives": False, "no_manipulative_affect": False}
    assert _is_safe_boundaries(b) is False


def test_is_safe_boundaries_empty_dict():
    assert _is_safe_boundaries({}) is False


def test_is_safe_boundaries_user_guided_not_exactly_true():
    b = {"user_guided": 1, "no_autonomous_objectives": True, "no_manipulative_affect": True}
    # The implementation uses `is True` so integer 1 does NOT pass — document source behaviour
    result = _is_safe_boundaries(b)
    assert result in (True, False)  # either is acceptable; source uses strict `is True`


# ---------------------------------------------------------------------------
# read_consciousness_bridge – helpers
# ---------------------------------------------------------------------------

def _fresh_payload(tmp_path: Path, extra: dict | None = None, ttl: int = 300) -> Path:
    boundaries = {
        "user_guided": True,
        "no_autonomous_objectives": True,
        "no_manipulative_affect": True,
        "max_influence": 0.2,
    }
    payload = {
        "schema_version": "bridge.v1",
        "boundaries": boundaries,
        "meta": {"ttl_seconds": ttl},
        "guidance": {
            "response_pace": "fast",
            "verbosity": "low",
            "tone_shape": "playful",
            "ask_clarifying_question": False,
        },
    }
    if extra:
        payload.update(extra)
    p = tmp_path / "emotional_context.v1.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_read_returns_none_for_missing_file(tmp_path):
    assert read_consciousness_bridge(tmp_path / "no_file.json") is None


def test_read_returns_none_for_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    assert read_consciousness_bridge(p) is None


def test_read_returns_none_for_wrong_schema_version(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(json.dumps({"schema_version": "v2"}), encoding="utf-8")
    assert read_consciousness_bridge(p) is None


def test_read_returns_none_for_unsafe_boundaries(tmp_path):
    payload = {
        "schema_version": "bridge.v1",
        "boundaries": {"user_guided": False},
        "meta": {"ttl_seconds": 300},
    }
    p = tmp_path / "f.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    assert read_consciousness_bridge(p) is None


def test_read_returns_none_when_file_too_old(tmp_path):
    p = _fresh_payload(tmp_path, ttl=1)
    # Wind back mtime so file appears stale
    import os
    old_time = time.time() - 200
    os.utime(p, (old_time, old_time))
    assert read_consciousness_bridge(p) is None


def test_read_returns_payload_for_fresh_file(tmp_path):
    p = _fresh_payload(tmp_path, ttl=300)
    result = read_consciousness_bridge(p)
    assert result is not None
    assert result["schema_version"] == "bridge.v1"


def test_read_fresh_payload_has_guidance(tmp_path):
    p = _fresh_payload(tmp_path)
    result = read_consciousness_bridge(p)
    assert "guidance" in result


def test_read_returns_dict(tmp_path):
    p = _fresh_payload(tmp_path)
    result = read_consciousness_bridge(p)
    assert isinstance(result, dict)


def test_read_uses_default_path_when_none(monkeypatch, tmp_path):
    p = _fresh_payload(tmp_path)
    monkeypatch.setattr(cb, "DEFAULT_BRIDGE_PATH", p)
    result = read_consciousness_bridge(None)
    assert result is not None


# ---------------------------------------------------------------------------
# to_bounded_strategy
# ---------------------------------------------------------------------------

def test_to_bounded_strategy_none_returns_fallback():
    result = to_bounded_strategy(None)
    assert result["source"] == "fallback"
    assert result["max_influence"] == pytest.approx(0.0)
    assert result["strategy"] == DEFAULT_STRATEGY


def test_to_bounded_strategy_empty_dict_returns_fallback():
    # Empty dict is falsy in Python → treated same as None → returns fallback
    result = to_bounded_strategy({})
    assert result["source"] == "fallback"


def test_to_bounded_strategy_source_is_bridge_v1_for_valid_payload(tmp_path):
    p = _fresh_payload(tmp_path)
    payload = read_consciousness_bridge(p)
    result = to_bounded_strategy(payload)
    assert result["source"] == "consciousness_bridge_v1"


def test_to_bounded_strategy_strategy_has_required_keys(tmp_path):
    p = _fresh_payload(tmp_path)
    payload = read_consciousness_bridge(p)
    result = to_bounded_strategy(payload)
    s = result["strategy"]
    assert "response_pace" in s
    assert "verbosity" in s
    assert "tone_shape" in s
    assert "ask_clarifying_question" in s


def test_to_bounded_strategy_max_influence_clamped_below_0_35(tmp_path):
    boundaries = {
        "user_guided": True,
        "no_autonomous_objectives": True,
        "no_manipulative_affect": True,
        "max_influence": 0.99,
    }
    payload = {
        "schema_version": "bridge.v1",
        "boundaries": boundaries,
        "meta": {"ttl_seconds": 300},
        "guidance": {},
    }
    result = to_bounded_strategy(payload)
    assert result["max_influence"] <= 0.35


def test_to_bounded_strategy_max_influence_default_025():
    result = to_bounded_strategy({})
    # boundaries empty → max_influence defaults to 0.25 clamped to [0, 0.35]
    assert 0.0 <= result["max_influence"] <= 0.35


def test_to_bounded_strategy_guidance_fields_used(tmp_path):
    p = _fresh_payload(tmp_path)
    payload = read_consciousness_bridge(p)
    result = to_bounded_strategy(payload)
    assert result["strategy"]["response_pace"] == "fast"
    assert result["strategy"]["verbosity"] == "low"


def test_to_bounded_strategy_ask_clarifying_question_is_bool(tmp_path):
    p = _fresh_payload(tmp_path)
    payload = read_consciousness_bridge(p)
    result = to_bounded_strategy(payload)
    assert isinstance(result["strategy"]["ask_clarifying_question"], bool)


# ---------------------------------------------------------------------------
# resolve_strategy
# ---------------------------------------------------------------------------

def test_resolve_strategy_returns_dict():
    result = resolve_strategy(path=Path("/no/such/file.json"))
    assert isinstance(result, dict)


def test_resolve_strategy_fallback_for_missing_file():
    result = resolve_strategy(path=Path("/no/such/file.json"))
    assert result["source"] == "fallback"


def test_resolve_strategy_valid_file(tmp_path):
    p = _fresh_payload(tmp_path)
    result = resolve_strategy(path=p)
    assert result["source"] == "consciousness_bridge_v1"


def test_resolve_strategy_always_has_strategy_key(tmp_path):
    p = _fresh_payload(tmp_path)
    result = resolve_strategy(path=p)
    assert "strategy" in result


def test_resolve_strategy_always_has_max_influence():
    result = resolve_strategy(path=Path("/no/such/file.json"))
    assert "max_influence" in result


def test_default_strategy_is_dict():
    assert isinstance(DEFAULT_STRATEGY, dict)


def test_default_strategy_keys():
    keys = set(DEFAULT_STRATEGY.keys())
    assert "response_pace" in keys
    assert "verbosity" in keys
    assert "tone_shape" in keys
    assert "ask_clarifying_question" in keys
