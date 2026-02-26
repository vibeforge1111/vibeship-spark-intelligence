"""Tests for lib/outcome_predictor.py

Covers:
- Prediction.to_dict(): all keys present, types correct
- _stable_hash(): returns 16-char hex, deterministic, varies with input,
  handles empty/None
- _make_key(): pipe-delimited format, lowercased, None/empty → '*'
- _bump(): creates row when absent, increments succ on success,
  increments fail on failure, updates updated_at
- record_outcome(): returns True, bumps specific key and fallback keys,
  uses STORE_PATH (monkeypatched)
- predict(): returns Prediction, p_fail in [0,1], confidence in [0,1],
  no data → prior-based prediction, p_fail lower after successes,
  p_fail higher after failures
- get_stats(): all expected keys present, key_count reflects stored keys
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.outcome_predictor as op
from lib.outcome_predictor import (
    Prediction,
    _stable_hash,
    _make_key,
    _bump,
    record_outcome,
    predict,
    get_stats,
    PRIOR_FAIL,
    PRIOR_SUCC,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_cache():
    """Reset module-level cache so tests get a fresh read."""
    op._cache = None
    op._cache_ts = 0.0


def _use_tmp_store(tmp_path: Path, monkeypatch):
    store_file = tmp_path / "outcome_predictor.json"
    monkeypatch.setattr(op, "STORE_PATH", store_file)
    _reset_cache()
    return store_file


# ---------------------------------------------------------------------------
# Prediction.to_dict
# ---------------------------------------------------------------------------

def test_prediction_to_dict_is_dict():
    p = Prediction(p_fail=0.2, confidence=0.8, samples=10, key_used="a|b|c", reason="test")
    assert isinstance(p.to_dict(), dict)


def test_prediction_to_dict_has_required_keys():
    p = Prediction(p_fail=0.2, confidence=0.8, samples=10, key_used="a|b|c", reason="test")
    d = p.to_dict()
    for key in ("p_fail", "confidence", "samples", "key_used", "reason"):
        assert key in d


def test_prediction_to_dict_p_fail_is_float():
    p = Prediction(p_fail=0.3, confidence=0.5, samples=5, key_used="k", reason="r")
    assert isinstance(p.to_dict()["p_fail"], float)


def test_prediction_to_dict_samples_is_int():
    p = Prediction(p_fail=0.3, confidence=0.5, samples=7, key_used="k", reason="r")
    assert isinstance(p.to_dict()["samples"], int)


# ---------------------------------------------------------------------------
# _stable_hash
# ---------------------------------------------------------------------------

def test_stable_hash_returns_string():
    assert isinstance(_stable_hash("hello"), str)


def test_stable_hash_is_16_chars():
    assert len(_stable_hash("hello world")) == 16


def test_stable_hash_is_hex():
    h = _stable_hash("test")
    assert all(c in "0123456789abcdef" for c in h)


def test_stable_hash_deterministic():
    assert _stable_hash("abc") == _stable_hash("abc")


def test_stable_hash_varies_with_input():
    assert _stable_hash("foo") != _stable_hash("bar")


def test_stable_hash_empty_string():
    result = _stable_hash("")
    assert len(result) == 16


def test_stable_hash_none():
    result = _stable_hash(None)
    assert len(result) == 16


# ---------------------------------------------------------------------------
# _make_key
# ---------------------------------------------------------------------------

def test_make_key_pipe_format():
    key = _make_key("pre_tool", "file_edit", "bash")
    assert "|" in key
    assert key.count("|") == 2


def test_make_key_lowercased():
    key = _make_key("PRE_TOOL", "FILE_EDIT", "BASH")
    assert key == key.lower()


def test_make_key_none_phase_becomes_star():
    key = _make_key(None, "edit", "bash")
    assert key.startswith("*|")


def test_make_key_empty_intent_becomes_star():
    key = _make_key("pre", "", "bash")
    parts = key.split("|")
    assert parts[1] == "*"


def test_make_key_none_tool_becomes_star():
    key = _make_key("pre", "intent", None)
    parts = key.split("|")
    assert parts[2] == "*"


def test_make_key_specific_values():
    key = _make_key("pre_tool", "file_write", "bash")
    assert key == "pre_tool|file_write|bash"


# ---------------------------------------------------------------------------
# _bump
# ---------------------------------------------------------------------------

def test_bump_creates_row_when_absent():
    store = {}
    _bump(store, "a|b|c", success=True)
    assert "a|b|c" in store["keys"]


def test_bump_increments_succ_on_success():
    store = {}
    _bump(store, "a|b|c", success=True)
    _bump(store, "a|b|c", success=True)
    assert store["keys"]["a|b|c"]["succ"] == 2


def test_bump_increments_fail_on_failure():
    store = {}
    _bump(store, "a|b|c", success=False)
    assert store["keys"]["a|b|c"]["fail"] == 1


def test_bump_tracks_succ_and_fail_separately():
    store = {}
    _bump(store, "k", success=True)
    _bump(store, "k", success=False)
    row = store["keys"]["k"]
    assert row["succ"] == 1
    assert row["fail"] == 1


def test_bump_updates_updated_at():
    store = {}
    before = time.time()
    _bump(store, "k", success=True)
    after = time.time()
    ts = store["keys"]["k"]["updated_at"]
    assert before <= ts <= after


# ---------------------------------------------------------------------------
# record_outcome
# ---------------------------------------------------------------------------

def test_record_outcome_returns_true(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    result = record_outcome(tool_name="bash", intent_family="file_edit", phase="pre_tool", success=True)
    assert result is True


def test_record_outcome_writes_store(tmp_path, monkeypatch):
    store_file = _use_tmp_store(tmp_path, monkeypatch)
    record_outcome(tool_name="bash", intent_family="edit", phase="pre", success=True)
    assert store_file.exists()


def test_record_outcome_bumps_specific_key(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    record_outcome(tool_name="bash", intent_family="edit", phase="pre", success=True)
    _reset_cache()
    store = json.loads(op.STORE_PATH.read_text())
    key = _make_key("pre", "edit", "bash")
    assert key in store["keys"]
    assert store["keys"][key]["succ"] == 1


def test_record_outcome_bumps_fallback_keys(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    record_outcome(tool_name="bash", intent_family="edit", phase="pre", success=False)
    _reset_cache()
    store = json.loads(op.STORE_PATH.read_text())
    # Wildcard tool fallback key
    wildcard_key = _make_key("*", "*", "bash")
    assert wildcard_key in store["keys"]


# ---------------------------------------------------------------------------
# predict
# ---------------------------------------------------------------------------

def test_predict_returns_prediction(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    result = predict(tool_name="bash", intent_family="edit", phase="pre")
    assert isinstance(result, Prediction)


def test_predict_p_fail_in_range(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    result = predict(tool_name="bash", intent_family="edit", phase="pre")
    assert 0.0 <= result.p_fail <= 1.0


def test_predict_confidence_in_range(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    result = predict(tool_name="bash", intent_family="edit", phase="pre")
    assert 0.0 <= result.confidence <= 1.0


def test_predict_no_data_uses_prior(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    result = predict(tool_name="bash", intent_family="edit", phase="pre")
    expected_p_fail = PRIOR_FAIL / (PRIOR_FAIL + PRIOR_SUCC)
    assert result.p_fail == pytest.approx(expected_p_fail)


def test_predict_lower_p_fail_after_successes(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    # Record many successes
    for _ in range(10):
        record_outcome(tool_name="bash", intent_family="edit", phase="pre", success=True)
    _reset_cache()
    result = predict(tool_name="bash", intent_family="edit", phase="pre")
    expected_prior = PRIOR_FAIL / (PRIOR_FAIL + PRIOR_SUCC)
    assert result.p_fail < expected_prior


def test_predict_higher_p_fail_after_failures(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    for _ in range(10):
        record_outcome(tool_name="edit", intent_family="write", phase="post", success=False)
    _reset_cache()
    result = predict(tool_name="edit", intent_family="write", phase="post")
    expected_prior = PRIOR_FAIL / (PRIOR_FAIL + PRIOR_SUCC)
    assert result.p_fail > expected_prior


def test_predict_samples_increases_with_data(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    result_before = predict(tool_name="bash", intent_family="x", phase="y")
    record_outcome(tool_name="bash", intent_family="x", phase="y", success=True)
    _reset_cache()
    result_after = predict(tool_name="bash", intent_family="x", phase="y")
    assert result_after.samples > result_before.samples


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

def test_get_stats_returns_dict(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    assert isinstance(get_stats(), dict)


def test_get_stats_has_expected_keys(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    stats = get_stats()
    for key in ("enabled", "path", "updated_at", "key_count", "cache_ttl_s", "prior"):
        assert key in stats


def test_get_stats_key_count_starts_zero(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    assert get_stats()["key_count"] == 0


def test_get_stats_key_count_grows(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    record_outcome(tool_name="bash", intent_family="edit", phase="pre", success=True)
    _reset_cache()
    stats = get_stats()
    assert stats["key_count"] > 0


def test_get_stats_prior_has_fail_succ(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    prior = get_stats()["prior"]
    assert "fail" in prior and "succ" in prior
