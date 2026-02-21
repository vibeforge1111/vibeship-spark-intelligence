"""Tests for lib/hypothesis_tracker.py

Covers:
- HypothesisState enum: all 6 values present
- Prediction.to_dict(): all fields present, from_dict() round-trips
- Hypothesis.hypothesis_id: deterministic 12-char hex string
- Hypothesis.accuracy: 0.5 when no outcomes, correct ratio when outcomes set
- Hypothesis.sample_size: counts only predictions with recorded outcomes
- HypothesisTracker.observe(): first observation returns None (not enough
  for hypothesis), second same-pattern returns Hypothesis, repeated calls
  update existing hypothesis, different patterns independent
- HypothesisTracker.make_prediction(): bad hypothesis_id returns None,
  good id appends Prediction and sets state to TESTING
- HypothesisTracker.record_outcome(): bad id/index no-op, updates prediction
  outcome, triggers state update when enough outcomes
- HypothesisTracker.add_counter_evidence(): adds to counter_evidence list,
  reduces confidence, caps list at 10
- HypothesisTracker.get_testable_hypotheses(): only HYPOTHESIS/TESTING states,
  limit respected
- HypothesisTracker.get_stats(): all keys present, correct counts
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.hypothesis_tracker import (
    HypothesisState,
    Prediction,
    Hypothesis,
    HypothesisTracker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(tmp_path: Path) -> HypothesisTracker:
    HypothesisTracker.HYPOTHESES_FILE = tmp_path / "hypotheses.json"
    return HypothesisTracker()


def _make_hypothesis(statement="Test statement", domain="") -> Hypothesis:
    return Hypothesis(
        statement=statement,
        evidence=["obs1"],
        counter_evidence=[],
        domain=domain,
    )


# ---------------------------------------------------------------------------
# HypothesisState enum
# ---------------------------------------------------------------------------

def test_hypothesis_state_emerging():
    assert HypothesisState.EMERGING.value == "emerging"


def test_hypothesis_state_hypothesis():
    assert HypothesisState.HYPOTHESIS.value == "hypothesis"


def test_hypothesis_state_testing():
    assert HypothesisState.TESTING.value == "testing"


def test_hypothesis_state_validated():
    assert HypothesisState.VALIDATED.value == "validated"


def test_hypothesis_state_invalidated():
    assert HypothesisState.INVALIDATED.value == "invalidated"


def test_hypothesis_state_belief():
    assert HypothesisState.BELIEF.value == "belief"


def test_hypothesis_state_has_six_members():
    assert len(HypothesisState) == 6


# ---------------------------------------------------------------------------
# Prediction.to_dict / from_dict
# ---------------------------------------------------------------------------

def test_prediction_to_dict_is_dict():
    p = Prediction(prediction_text="X will happen", context="ctx")
    assert isinstance(p.to_dict(), dict)


def test_prediction_to_dict_has_required_keys():
    p = Prediction(prediction_text="X", context="ctx")
    d = p.to_dict()
    for key in ("prediction_text", "context", "made_at", "outcome",
                "outcome_recorded_at", "outcome_notes"):
        assert key in d


def test_prediction_from_dict_round_trips():
    p = Prediction(prediction_text="It will work", context="test context")
    p2 = Prediction.from_dict(p.to_dict())
    assert p2.prediction_text == "It will work"
    assert p2.context == "test context"


def test_prediction_from_dict_default_outcome_is_none():
    p = Prediction(prediction_text="Maybe", context="")
    p2 = Prediction.from_dict(p.to_dict())
    assert p2.outcome is None


# ---------------------------------------------------------------------------
# Hypothesis.hypothesis_id
# ---------------------------------------------------------------------------

def test_hypothesis_id_is_string():
    h = _make_hypothesis()
    assert isinstance(h.hypothesis_id, str)


def test_hypothesis_id_is_12_chars():
    h = _make_hypothesis()
    assert len(h.hypothesis_id) == 12


def test_hypothesis_id_is_hex():
    h = _make_hypothesis()
    assert all(c in "0123456789abcdef" for c in h.hypothesis_id)


def test_hypothesis_id_deterministic():
    h1 = _make_hypothesis("same statement", domain="d1")
    h2 = _make_hypothesis("same statement", domain="d1")
    assert h1.hypothesis_id == h2.hypothesis_id


def test_hypothesis_id_varies_with_statement():
    h1 = _make_hypothesis("statement A")
    h2 = _make_hypothesis("statement B")
    assert h1.hypothesis_id != h2.hypothesis_id


# ---------------------------------------------------------------------------
# Hypothesis.accuracy
# ---------------------------------------------------------------------------

def test_accuracy_no_outcomes_is_half():
    h = _make_hypothesis()
    assert h.accuracy == pytest.approx(0.5)


def test_accuracy_all_correct():
    h = _make_hypothesis()
    h.predictions = [
        Prediction("p1", "", outcome=True),
        Prediction("p2", "", outcome=True),
    ]
    assert h.accuracy == pytest.approx(1.0)


def test_accuracy_all_wrong():
    h = _make_hypothesis()
    h.predictions = [
        Prediction("p1", "", outcome=False),
        Prediction("p2", "", outcome=False),
    ]
    assert h.accuracy == pytest.approx(0.0)


def test_accuracy_mixed():
    h = _make_hypothesis()
    h.predictions = [
        Prediction("p1", "", outcome=True),
        Prediction("p2", "", outcome=False),
        Prediction("p3", "", outcome=True),
    ]
    assert h.accuracy == pytest.approx(2 / 3)


def test_accuracy_ignores_none_outcomes():
    h = _make_hypothesis()
    h.predictions = [
        Prediction("p1", "", outcome=True),
        Prediction("p2", "", outcome=None),
    ]
    # Only 1 outcome recorded, 1 correct
    assert h.accuracy == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Hypothesis.sample_size
# ---------------------------------------------------------------------------

def test_sample_size_zero_when_no_predictions():
    h = _make_hypothesis()
    assert h.sample_size == 0


def test_sample_size_counts_only_recorded_outcomes():
    h = _make_hypothesis()
    h.predictions = [
        Prediction("p1", "", outcome=True),
        Prediction("p2", "", outcome=None),
        Prediction("p3", "", outcome=False),
    ]
    assert h.sample_size == 2


# ---------------------------------------------------------------------------
# HypothesisTracker.observe
# ---------------------------------------------------------------------------

def test_observe_first_returns_none(tmp_path):
    t = _make_tracker(tmp_path)
    result = t.observe("user prefers tabs over spaces")
    assert result is None


def test_observe_second_same_pattern_returns_hypothesis(tmp_path):
    # observe() groups by first-50-char pattern key, so use same string
    t = _make_tracker(tmp_path)
    t.observe("user prefers tabs over spaces")
    result = t.observe("user prefers tabs over spaces")
    assert result is not None


def test_observe_returns_hypothesis_instance(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe("retry logic prevents cascading failures consistently")
    result = t.observe("retry logic prevents cascading failures consistently")
    assert isinstance(result, Hypothesis)


def test_observe_hypothesis_state_is_hypothesis(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe("error occurs when cache is full")
    result = t.observe("error occurs when cache is full")
    assert result.state == HypothesisState.HYPOTHESIS


def test_observe_different_patterns_are_independent(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe("alpha fires first time in loop")
    result = t.observe("zzz gamma completely unrelated")
    # Different 50-char prefix → not 2 of the same pattern yet
    assert result is None


def test_observe_third_call_updates_confidence(tmp_path):
    t = _make_tracker(tmp_path)
    obs = "batch writes are faster than individual writes"
    t.observe(obs)
    h = t.observe(obs)
    conf_before = h.confidence
    h2 = t.observe(obs)
    assert h2.confidence >= conf_before


def test_observe_saves_hypothesis_to_disk(tmp_path):
    t = _make_tracker(tmp_path)
    obs = "test pattern fires consistently in prod"
    t.observe(obs)
    t.observe(obs)
    assert (tmp_path / "hypotheses.json").exists()


# ---------------------------------------------------------------------------
# HypothesisTracker.make_prediction
# ---------------------------------------------------------------------------

_OBS_A = "connection timeouts spike after deploy"
_OBS_B = "memory usage grows linearly with queue depth"
_OBS_C = "cache hit rate drops when cold start occurs"
_OBS_D = "disk writes slow under high cpu contention"
_OBS_E = "auth failures cluster around token expiry"
_OBS_F = "batch job duration scales with input size"
_OBS_G = "health checks fail during rolling restarts"
_OBS_H = "throughput degrades when buffer is exhausted"
_OBS_I = "latency spikes correlate with gc pressure"
_OBS_J = "queue depth grows when workers are blocked"


def test_make_prediction_bad_id_returns_none(tmp_path):
    t = _make_tracker(tmp_path)
    result = t.make_prediction("nonexistent", "it will fail")
    assert result is None


def test_make_prediction_returns_prediction(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_A)
    h = t.observe(_OBS_A)
    result = t.make_prediction(h.hypothesis_id, "it will happen")
    assert isinstance(result, Prediction)


def test_make_prediction_sets_state_to_testing(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_B)
    h = t.observe(_OBS_B)
    t.make_prediction(h.hypothesis_id, "it will happen")
    assert t.hypotheses[h.hypothesis_id].state == HypothesisState.TESTING


def test_make_prediction_appends_to_predictions(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_C)
    h = t.observe(_OBS_C)
    t.make_prediction(h.hypothesis_id, "pred 1")
    t.make_prediction(h.hypothesis_id, "pred 2")
    assert len(t.hypotheses[h.hypothesis_id].predictions) == 2


# ---------------------------------------------------------------------------
# HypothesisTracker.record_outcome
# ---------------------------------------------------------------------------

def test_record_outcome_bad_id_is_noop(tmp_path):
    t = _make_tracker(tmp_path)
    t.record_outcome("bad-id", 0, correct=True)  # should not raise


def test_record_outcome_bad_index_is_noop(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_D)
    h = t.observe(_OBS_D)
    t.make_prediction(h.hypothesis_id, "some pred")
    t.record_outcome(h.hypothesis_id, 99, correct=True)  # bad index, no raise


def test_record_outcome_sets_prediction_outcome(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_A)
    h = t.observe(_OBS_A)
    t.make_prediction(h.hypothesis_id, "it happens")
    t.record_outcome(h.hypothesis_id, 0, correct=True)
    assert t.hypotheses[h.hypothesis_id].predictions[0].outcome is True


def test_record_outcome_stores_notes(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_B)
    h = t.observe(_OBS_B)
    t.make_prediction(h.hypothesis_id, "pred")
    t.record_outcome(h.hypothesis_id, 0, correct=False, notes="because X")
    assert t.hypotheses[h.hypothesis_id].predictions[0].outcome_notes == "because X"


def test_record_outcome_validates_to_validated_state(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_C)
    h = t.observe(_OBS_C)
    hid = h.hypothesis_id
    # Record 3 correct outcomes → should flip to VALIDATED
    for _ in range(3):
        t.make_prediction(hid, "pred")
    for i in range(3):
        t.record_outcome(hid, i, correct=True)
    assert t.hypotheses[hid].state == HypothesisState.VALIDATED


def test_record_outcome_invalid_flips_to_invalidated(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_D)
    h = t.observe(_OBS_D)
    hid = h.hypothesis_id
    for _ in range(3):
        t.make_prediction(hid, "pred")
    for i in range(3):
        t.record_outcome(hid, i, correct=False)
    assert t.hypotheses[hid].state == HypothesisState.INVALIDATED


# ---------------------------------------------------------------------------
# HypothesisTracker.add_counter_evidence
# ---------------------------------------------------------------------------

def test_add_counter_evidence_bad_id_is_noop(tmp_path):
    t = _make_tracker(tmp_path)
    t.add_counter_evidence("bad-id", "something contradicts")  # no raise


def test_add_counter_evidence_appends(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_E)
    h = t.observe(_OBS_E)
    t.add_counter_evidence(h.hypothesis_id, "contradicting evidence")
    assert "contradicting evidence" in t.hypotheses[h.hypothesis_id].counter_evidence


def test_add_counter_evidence_reduces_confidence(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_F)
    h = t.observe(_OBS_F)
    conf_before = t.hypotheses[h.hypothesis_id].confidence
    t.add_counter_evidence(h.hypothesis_id, "contradicting evidence")
    assert t.hypotheses[h.hypothesis_id].confidence < conf_before


def test_add_counter_evidence_caps_at_10(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_G)
    h = t.observe(_OBS_G)
    hid = h.hypothesis_id
    for i in range(15):
        t.add_counter_evidence(hid, f"counter {i}")
    assert len(t.hypotheses[hid].counter_evidence) <= 10


def test_add_counter_evidence_no_duplicate(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_H)
    h = t.observe(_OBS_H)
    hid = h.hypothesis_id
    t.add_counter_evidence(hid, "same evidence")
    t.add_counter_evidence(hid, "same evidence")
    assert t.hypotheses[hid].counter_evidence.count("same evidence") == 1


# ---------------------------------------------------------------------------
# HypothesisTracker.get_testable_hypotheses
# ---------------------------------------------------------------------------

def test_get_testable_hypotheses_returns_list(tmp_path):
    t = _make_tracker(tmp_path)
    assert isinstance(t.get_testable_hypotheses(), list)


def test_get_testable_hypotheses_empty_when_no_hypotheses(tmp_path):
    t = _make_tracker(tmp_path)
    assert t.get_testable_hypotheses() == []


def test_get_testable_hypotheses_returns_hypothesis_state(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_I)
    t.observe(_OBS_I)
    result = t.get_testable_hypotheses()
    assert len(result) >= 1
    for h in result:
        assert h.state in (HypothesisState.HYPOTHESIS, HypothesisState.TESTING)


def test_get_testable_hypotheses_respects_limit(tmp_path):
    t = _make_tracker(tmp_path)
    # Create multiple hypotheses using the pre-defined distinct observations
    for obs in [_OBS_A, _OBS_B, _OBS_C, _OBS_D, _OBS_E, _OBS_F]:
        t.observe(obs)
        t.observe(obs)
    result = t.get_testable_hypotheses(limit=3)
    assert len(result) <= 3


# ---------------------------------------------------------------------------
# HypothesisTracker.get_stats
# ---------------------------------------------------------------------------

def test_get_stats_returns_dict(tmp_path):
    t = _make_tracker(tmp_path)
    assert isinstance(t.get_stats(), dict)


def test_get_stats_has_expected_keys(tmp_path):
    t = _make_tracker(tmp_path)
    stats = t.get_stats()
    for key in ("total_hypotheses", "by_state", "total_predictions",
                "outcomes_recorded", "pending_outcomes", "validated_count",
                "avg_validated_accuracy", "observation_patterns"):
        assert key in stats


def test_get_stats_zero_when_empty(tmp_path):
    t = _make_tracker(tmp_path)
    stats = t.get_stats()
    assert stats["total_hypotheses"] == 0
    assert stats["total_predictions"] == 0


def test_get_stats_total_hypotheses_correct(tmp_path):
    t = _make_tracker(tmp_path)
    t.observe(_OBS_J)
    t.observe(_OBS_J)
    stats = t.get_stats()
    assert stats["total_hypotheses"] == 1
