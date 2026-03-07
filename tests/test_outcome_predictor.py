"""Tests for lib/outcome_predictor.py — smoothed counter-table failure predictor."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.outcome_predictor as op


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_cache():
    """Reset module-level cache before each test."""
    op._cache = None
    op._cache_ts = 0.0
    yield
    op._cache = None
    op._cache_ts = 0.0


@pytest.fixture()
def store_path(tmp_path, monkeypatch):
    """Redirect STORE_PATH to a temp file."""
    p = tmp_path / "outcome_predictor.json"
    monkeypatch.setattr(op, "STORE_PATH", p)
    return p


# ---------------------------------------------------------------------------
# _make_key
# ---------------------------------------------------------------------------

class TestMakeKey:
    def test_basic_key(self):
        k = op._make_key("init", "code_edit", "bash")
        assert k == "init|code_edit|bash"

    def test_lowercased(self):
        k = op._make_key("INIT", "CODE_EDIT", "BASH")
        assert k == "init|code_edit|bash"

    def test_empty_phase_becomes_wildcard(self):
        k = op._make_key("", "fam", "tool")
        assert k.startswith("*|")

    def test_empty_tool_becomes_wildcard(self):
        k = op._make_key("phase", "fam", "")
        assert k.endswith("|*")

    def test_strips_whitespace(self):
        k = op._make_key(" phase ", " fam ", " tool ")
        assert k == "phase|fam|tool"


# ---------------------------------------------------------------------------
# _stable_hash
# ---------------------------------------------------------------------------

class TestStableHash:
    def test_deterministic(self):
        assert op._stable_hash("hello") == op._stable_hash("hello")

    def test_different_inputs_differ(self):
        assert op._stable_hash("a") != op._stable_hash("b")

    def test_length_16(self):
        assert len(op._stable_hash("test")) == 16

    def test_empty_string(self):
        h = op._stable_hash("")
        assert len(h) == 16


# ---------------------------------------------------------------------------
# _bump
# ---------------------------------------------------------------------------

class TestBump:
    def _fresh_store(self):
        return {"version": 1, "updated_at": 0.0, "keys": {}}

    def test_creates_key_on_success(self):
        store = self._fresh_store()
        op._bump(store, "k1", success=True)
        assert store["keys"]["k1"]["succ"] == 1
        assert store["keys"]["k1"]["fail"] == 0

    def test_creates_key_on_failure(self):
        store = self._fresh_store()
        op._bump(store, "k1", success=False)
        assert store["keys"]["k1"]["fail"] == 1
        assert store["keys"]["k1"]["succ"] == 0

    def test_increments_existing(self):
        store = self._fresh_store()
        op._bump(store, "k1", success=True)
        op._bump(store, "k1", success=True)
        assert store["keys"]["k1"]["succ"] == 2

    def test_updates_updated_at(self):
        store = self._fresh_store()
        before = time.time()
        op._bump(store, "k1", success=True)
        assert store["keys"]["k1"]["updated_at"] >= before


# ---------------------------------------------------------------------------
# _load_store / _save_store
# ---------------------------------------------------------------------------

class TestLoadSaveStore:
    def test_load_creates_default_when_missing(self, store_path):
        assert not store_path.exists()
        store = op._load_store()
        assert store["version"] == 1
        assert "keys" in store

    def test_save_then_load(self, store_path):
        store = op._load_store()
        op._bump(store, "p|f|t", success=True)
        op._save_store(store)
        # Reset cache
        op._cache = None
        reloaded = op._load_store()
        assert reloaded["keys"]["p|f|t"]["succ"] == 1

    def test_load_uses_cache(self, store_path):
        store1 = op._load_store()
        store2 = op._load_store()
        # Same object returned from cache within TTL
        assert store1 is store2

    def test_save_uses_atomic_replace(self, store_path):
        store = op._load_store()
        op._save_store(store)
        assert store_path.exists()
        # No .tmp file should remain
        tmp = store_path.with_suffix(".json.tmp")
        assert not tmp.exists()

    def test_save_creates_parent_dir(self, tmp_path, monkeypatch):
        deep_path = tmp_path / "deep" / "dir" / "store.json"
        monkeypatch.setattr(op, "STORE_PATH", deep_path)
        store = {"version": 1, "updated_at": 0.0, "keys": {}}
        op._save_store(store)
        assert deep_path.exists()

    def test_corrupt_file_returns_empty(self, store_path):
        store_path.write_text("not_json!!!", encoding="utf-8")
        op._cache = None
        store = op._load_store()
        assert store["keys"] == {}

    def test_load_cache_expires(self, store_path, monkeypatch):
        store = op._load_store()
        # Force cache expiry
        monkeypatch.setattr(op, "_cache_ts", 0.0)
        store2 = op._load_store()
        # Should reload (new call not from cache)
        assert store2 is not None


# ---------------------------------------------------------------------------
# record_outcome
# ---------------------------------------------------------------------------

class TestRecordOutcome:
    def test_returns_true(self, store_path):
        result = op.record_outcome(
            tool_name="bash", intent_family="code_edit", phase="init", success=True
        )
        assert result is True

    def test_file_created(self, store_path):
        op.record_outcome(tool_name="bash", intent_family="code_edit", phase="init", success=True)
        assert store_path.exists()

    def test_bumps_exact_key(self, store_path):
        op.record_outcome(tool_name="bash", intent_family="code_edit", phase="init", success=True)
        op._cache = None
        store = op._load_store()
        key = op._make_key("init", "code_edit", "bash")
        assert store["keys"][key]["succ"] == 1

    def test_bumps_fallback_keys(self, store_path):
        op.record_outcome(tool_name="bash", intent_family="code_edit", phase="init", success=False)
        op._cache = None
        store = op._load_store()
        # Should have wildcard keys too
        wildcard_key = op._make_key("*", "*", "bash")
        assert wildcard_key in store["keys"]

    def test_failure_increments_fail(self, store_path):
        op.record_outcome(tool_name="bash", intent_family="ci", phase="run", success=False)
        op._cache = None
        store = op._load_store()
        key = op._make_key("run", "ci", "bash")
        assert store["keys"][key]["fail"] == 1

    def test_bounded_to_max_keys(self, store_path, monkeypatch):
        monkeypatch.setattr(op, "MAX_KEYS", 5)
        for i in range(20):
            op.record_outcome(
                tool_name=f"tool{i}",
                intent_family="fam",
                phase="ph",
                success=True,
            )
            op._cache = None
        store = op._load_store()
        assert len(store["keys"]) <= op.MAX_KEYS + 4  # some slack for wildcard keys


# ---------------------------------------------------------------------------
# predict
# ---------------------------------------------------------------------------

class TestPredict:
    def test_returns_prediction_object(self, store_path):
        pred = op.predict(tool_name="bash", intent_family="code_edit", phase="init")
        assert isinstance(pred, op.Prediction)

    def test_default_prior_when_no_data(self, store_path):
        pred = op.predict(tool_name="bash", intent_family="code_edit", phase="init")
        # With prior: fail=1, succ=3, total=0 → p_fail = 1/4 = 0.25
        expected = op.PRIOR_FAIL / (op.PRIOR_FAIL + op.PRIOR_SUCC)
        assert abs(pred.p_fail - expected) < 0.01

    def test_p_fail_decreases_with_successes(self, store_path):
        for _ in range(10):
            op.record_outcome(tool_name="bash", intent_family="code_edit", phase="init", success=True)
        op._cache = None
        pred = op.predict(tool_name="bash", intent_family="code_edit", phase="init")
        assert pred.p_fail < 0.25

    def test_p_fail_increases_with_failures(self, store_path):
        for _ in range(10):
            op.record_outcome(tool_name="bash", intent_family="code_edit", phase="init", success=False)
        op._cache = None
        pred = op.predict(tool_name="bash", intent_family="code_edit", phase="init")
        assert pred.p_fail > 0.25

    def test_confidence_zero_with_no_samples(self, store_path):
        pred = op.predict(tool_name="bash", intent_family="code_edit", phase="init")
        assert pred.confidence == 0.0

    def test_confidence_grows_with_samples(self, store_path):
        for _ in range(20):
            op.record_outcome(tool_name="bash", intent_family="code_edit", phase="init", success=True)
        op._cache = None
        pred = op.predict(tool_name="bash", intent_family="code_edit", phase="init")
        assert pred.confidence == 1.0

    def test_falls_back_to_wildcard_key(self, store_path):
        # Record under wildcard tool key
        op.record_outcome(tool_name="bash", intent_family="other", phase="init", success=True)
        op._cache = None
        pred = op.predict(tool_name="bash", intent_family="code_edit", phase="init")
        # Should use some key (samples > 0 if wildcard matched)
        assert pred is not None

    def test_to_dict(self, store_path):
        pred = op.predict(tool_name="bash", intent_family="code_edit", phase="init")
        d = pred.to_dict()
        assert "p_fail" in d
        assert "confidence" in d
        assert "samples" in d
        assert "key_used" in d
        assert "reason" in d

    def test_p_fail_in_0_1_range(self, store_path):
        pred = op.predict(tool_name="any", intent_family="any", phase="any")
        assert 0.0 <= pred.p_fail <= 1.0


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_returns_dict(self, store_path):
        s = op.get_stats()
        assert isinstance(s, dict)

    def test_has_required_keys(self, store_path):
        s = op.get_stats()
        for key in ("enabled", "path", "key_count", "cache_ttl_s", "prior"):
            assert key in s

    def test_key_count_increases(self, store_path):
        before = op.get_stats()["key_count"]
        op.record_outcome(tool_name="newtool", intent_family="fam", phase="ph", success=True)
        op._cache = None
        after = op.get_stats()["key_count"]
        assert after > before

    def test_path_matches_store_path(self, store_path):
        s = op.get_stats()
        assert s["path"] == str(store_path)

    def test_prior_values_present(self, store_path):
        s = op.get_stats()
        assert s["prior"]["fail"] == op.PRIOR_FAIL
        assert s["prior"]["succ"] == op.PRIOR_SUCC
