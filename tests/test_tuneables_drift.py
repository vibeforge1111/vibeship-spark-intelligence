"""Tests for lib/tuneables_drift.py — drift distance calculator."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.tuneables_drift as td
from lib.tuneables_drift import (
    DriftResult,
    _key_distance,
    _read_json,
    compute_drift,
    log_drift,
    check_drift,
    DEFAULT_ALERT_THRESHOLD,
    VOLATILE_KEYS,
    SKIP_SECTIONS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_paths(tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.json"
    runtime = tmp_path / "runtime.json"
    drift_log = tmp_path / "tuneable_drift.jsonl"
    monkeypatch.setattr(td, "BASELINE_FILE", baseline)
    monkeypatch.setattr(td, "RUNTIME_FILE", runtime)
    monkeypatch.setattr(td, "DRIFT_LOG_FILE", drift_log)
    yield baseline, runtime, drift_log


# ---------------------------------------------------------------------------
# _read_json
# ---------------------------------------------------------------------------

class TestReadJson:
    def test_missing_file_returns_empty(self, tmp_path):
        result = _read_json(tmp_path / "nonexistent.json")
        assert result == {}

    def test_valid_json_returned(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"a": 1}', encoding="utf-8")
        assert _read_json(f) == {"a": 1}

    def test_invalid_json_returns_empty(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text("not json", encoding="utf-8")
        assert _read_json(f) == {}

    def test_utf8_bom_handled(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_bytes(b'\xef\xbb\xbf{"k": 2}')  # UTF-8 BOM
        assert _read_json(f) == {"k": 2}


# ---------------------------------------------------------------------------
# _key_distance
# ---------------------------------------------------------------------------

class TestKeyDistance:
    def test_equal_values_zero(self):
        assert _key_distance(5, 5) == 0.0
        assert _key_distance("x", "x") == 0.0
        assert _key_distance([1, 2], [1, 2]) == 0.0

    def test_bool_same_zero(self):
        assert _key_distance(True, True) == 0.0
        assert _key_distance(False, False) == 0.0

    def test_bool_different_one(self):
        assert _key_distance(True, False) == 1.0

    def test_bool_before_numeric(self):
        # True == 1 numerically, but bool check should fire first
        assert _key_distance(True, 1) == 0.0   # True == 1 → equal → 0.0

    def test_numeric_identical(self):
        assert _key_distance(10, 10) == 0.0

    def test_numeric_normalized(self):
        # |10 - 20| / max(10, 20, 1e-9) = 10/20 = 0.5
        result = _key_distance(10, 20)
        assert abs(result - 0.5) < 1e-9

    def test_numeric_clamped_at_one(self):
        result = _key_distance(0, 1000)
        assert result <= 1.0

    def test_string_same_zero(self):
        assert _key_distance("hello", "hello") == 0.0

    def test_string_different_one(self):
        assert _key_distance("hello", "world") == 1.0

    def test_dict_equal_zero(self):
        assert _key_distance({"a": 1}, {"a": 1}) == 0.0

    def test_dict_different_one(self):
        assert _key_distance({"a": 1}, {"a": 2}) == 1.0

    def test_list_equal_zero(self):
        assert _key_distance([1, 2, 3], [1, 2, 3]) == 0.0

    def test_list_different_one(self):
        assert _key_distance([1, 2], [1, 3]) == 1.0

    def test_mixed_types_one(self):
        assert _key_distance(42, "42") == 1.0

    def test_none_vs_value_one(self):
        assert _key_distance(None, "something") == 1.0

    def test_zero_denominator_uses_epsilon(self):
        # Both zero → equal → 0.0
        assert _key_distance(0, 0) == 0.0


# ---------------------------------------------------------------------------
# DriftResult.to_dict
# ---------------------------------------------------------------------------

class TestDriftResultToDict:
    def test_required_keys_present(self):
        r = DriftResult(drift_score=0.1, section_scores={}, key_deltas={})
        d = r.to_dict()
        for key in ("ts", "drift_score", "alert", "threshold", "section_scores"):
            assert key in d

    def test_drift_score_rounded(self):
        r = DriftResult(drift_score=0.123456789, section_scores={}, key_deltas={})
        d = r.to_dict()
        assert d["drift_score"] == round(0.123456789, 4)

    def test_alert_false_by_default(self):
        r = DriftResult(drift_score=0.0, section_scores={}, key_deltas={})
        assert r.to_dict()["alert"] is False

    def test_section_scores_rounded(self):
        r = DriftResult(drift_score=0.0, section_scores={"a": 0.123456}, key_deltas={})
        d = r.to_dict()
        assert d["section_scores"]["a"] == round(0.123456, 4)

    def test_timestamp_is_recent(self):
        before = time.time()
        r = DriftResult(drift_score=0.0, section_scores={}, key_deltas={})
        assert r.to_dict()["ts"] >= before


# ---------------------------------------------------------------------------
# compute_drift
# ---------------------------------------------------------------------------

class TestComputeDrift:
    def test_empty_dicts_score_zero(self):
        result = compute_drift(runtime={}, baseline={})
        assert result.drift_score == 0.0

    def test_identical_returns_zero(self):
        d = {"section": {"key": 10, "other": "val"}}
        result = compute_drift(runtime=d, baseline=d)
        assert result.drift_score == 0.0

    def test_completely_different_scores_one(self):
        runtime = {"sec": {"key": 1}}
        baseline = {"sec": {"key": 0}}
        # |1-0|/max(1,0,1e-9)=1.0
        result = compute_drift(runtime=runtime, baseline=baseline)
        assert result.drift_score > 0.0

    def test_skip_sections_ignored(self):
        # updated_at is in SKIP_SECTIONS — should not affect score
        runtime = {"updated_at": "2024-01-01"}
        baseline = {"updated_at": "2024-06-01"}
        result = compute_drift(runtime=runtime, baseline=baseline)
        assert result.drift_score == 0.0

    def test_volatile_keys_skipped(self):
        # "last_run" is volatile in auto_tuner section
        runtime = {"auto_tuner": {"last_run": "2024-01-01", "stable_key": 5}}
        baseline = {"auto_tuner": {"last_run": "2024-06-01", "stable_key": 5}}
        result = compute_drift(runtime=runtime, baseline=baseline)
        assert result.drift_score == 0.0

    def test_missing_key_in_runtime_scores_one(self):
        runtime = {"sec": {}}
        baseline = {"sec": {"key": 10}}
        result = compute_drift(runtime=runtime, baseline=baseline)
        assert result.section_scores["sec"] == 1.0

    def test_missing_key_in_baseline_scores_one(self):
        runtime = {"sec": {"key": 10}}
        baseline = {"sec": {}}
        result = compute_drift(runtime=runtime, baseline=baseline)
        assert result.section_scores["sec"] == 1.0

    def test_private_keys_ignored(self):
        # Keys starting with _ are skipped
        runtime = {"sec": {"_private": "changed"}}
        baseline = {"sec": {"_private": "original"}}
        result = compute_drift(runtime=runtime, baseline=baseline)
        assert result.section_scores.get("sec", 0.0) == 0.0

    def test_alert_triggered_above_threshold(self):
        runtime = {"sec": {"key": 0}}
        baseline = {"sec": {"key": 100}}
        result = compute_drift(runtime=runtime, baseline=baseline, threshold=0.0)
        assert result.alert is True

    def test_alert_not_triggered_below_threshold(self):
        runtime = {"sec": {"key": 10}}
        baseline = {"sec": {"key": 10}}
        result = compute_drift(runtime=runtime, baseline=baseline, threshold=0.3)
        assert result.alert is False

    def test_section_scores_populated(self):
        runtime = {"a": {"x": 1}, "b": {"y": 2}}
        baseline = {"a": {"x": 2}, "b": {"y": 2}}
        result = compute_drift(runtime=runtime, baseline=baseline)
        assert "a" in result.section_scores
        assert "b" in result.section_scores

    def test_non_dict_section_treated_as_whole(self):
        # If runtime section is a string (not dict), compare whole section
        runtime = {"sec": "val_a"}
        baseline = {"sec": "val_b"}
        result = compute_drift(runtime=runtime, baseline=baseline)
        assert result.section_scores["sec"] == 1.0

    def test_reads_from_files_when_none(self, isolate_paths, tmp_path):
        baseline_f, runtime_f, _ = isolate_paths
        baseline_f.write_text('{"sec": {"k": 1}}', encoding="utf-8")
        runtime_f.write_text('{"sec": {"k": 1}}', encoding="utf-8")
        result = compute_drift()
        assert result.drift_score == 0.0

    def test_returns_drift_result(self):
        result = compute_drift(runtime={}, baseline={})
        assert isinstance(result, DriftResult)

    def test_key_deltas_populated(self):
        runtime = {"sec": {"a": 1, "b": 2}}
        baseline = {"sec": {"a": 2, "b": 2}}
        result = compute_drift(runtime=runtime, baseline=baseline)
        assert "a" in result.key_deltas["sec"]
        assert "b" in result.key_deltas["sec"]


# ---------------------------------------------------------------------------
# log_drift
# ---------------------------------------------------------------------------

class TestLogDrift:
    def test_creates_log_file(self, isolate_paths):
        _, _, drift_log = isolate_paths
        result = DriftResult(drift_score=0.1, section_scores={}, key_deltas={})
        log_drift(result)
        assert drift_log.exists()

    def test_writes_valid_json_line(self, isolate_paths):
        _, _, drift_log = isolate_paths
        result = DriftResult(drift_score=0.25, section_scores={"a": 0.5}, key_deltas={})
        log_drift(result)
        lines = [l for l in drift_log.read_text().splitlines() if l]
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert "drift_score" in data

    def test_appends_multiple_entries(self, isolate_paths):
        _, _, drift_log = isolate_paths
        r = DriftResult(drift_score=0.1, section_scores={}, key_deltas={})
        log_drift(r)
        log_drift(r)
        lines = [l for l in drift_log.read_text().splitlines() if l]
        assert len(lines) == 2

    def test_never_raises(self, monkeypatch):
        # Even if write fails, no exception should propagate
        monkeypatch.setattr(td, "DRIFT_LOG_FILE", Path("/nonexistent/path/drift.jsonl"))
        r = DriftResult(drift_score=0.1, section_scores={}, key_deltas={})
        log_drift(r)  # Should not raise


# ---------------------------------------------------------------------------
# check_drift
# ---------------------------------------------------------------------------

class TestCheckDrift:
    def test_returns_drift_result(self, isolate_paths):
        baseline_f, runtime_f, _ = isolate_paths
        baseline_f.write_text("{}", encoding="utf-8")
        runtime_f.write_text("{}", encoding="utf-8")
        result = check_drift(log=False)
        assert isinstance(result, DriftResult)

    def test_log_false_does_not_create_file(self, isolate_paths):
        _, _, drift_log = isolate_paths
        check_drift(log=False)
        assert not drift_log.exists()

    def test_log_true_creates_file(self, isolate_paths):
        _, _, drift_log = isolate_paths
        check_drift(log=True)
        assert drift_log.exists()

    def test_custom_threshold_respected(self, isolate_paths):
        baseline_f, runtime_f, _ = isolate_paths
        baseline_f.write_text('{"sec": {"k": 0}}', encoding="utf-8")
        runtime_f.write_text('{"sec": {"k": 100}}', encoding="utf-8")
        result = check_drift(threshold=0.0, log=False)
        assert result.alert is True
