"""Tests for lib/hypothesis_tracker.py — hypothesis lifecycle tracker."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.hypothesis_tracker as ht
from lib.hypothesis_tracker import (
    HypothesisTracker,
    HypothesisState,
    Hypothesis,
    Prediction,
    get_hypothesis_tracker,
    observe_for_hypothesis,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tracker(monkeypatch, tmp_path: Path) -> HypothesisTracker:
    fake_file = tmp_path / "hypotheses.json"
    monkeypatch.setattr(HypothesisTracker, "HYPOTHESES_FILE", fake_file)
    return HypothesisTracker()


def _make_hypothesis(
    tracker: HypothesisTracker,
    statement: str = "Test hypothesis",
    domain: str = "",
    state: HypothesisState = HypothesisState.HYPOTHESIS,
) -> Hypothesis:
    """Directly insert a hypothesis into the tracker, bypassing observe()."""
    h = Hypothesis(
        statement=statement,
        evidence=["obs 1", "obs 2"],
        counter_evidence=[],
        state=state,
        confidence=0.6,
        domain=domain,
    )
    tracker.hypotheses[h.hypothesis_id] = h
    return h


def _fill_predictions(tracker: HypothesisTracker, h_id: str, count: int, correct: bool):
    """Add `count` predictions with the given outcome to a hypothesis."""
    for i in range(count):
        tracker.make_prediction(h_id, f"prediction {i}", context=f"ctx {i}")
    for i in range(count):
        tracker.record_outcome(h_id, i, correct)


# ---------------------------------------------------------------------------
# HypothesisState enum
# ---------------------------------------------------------------------------


def test_all_states_have_values():
    assert HypothesisState.EMERGING.value == "emerging"
    assert HypothesisState.BELIEF.value == "belief"


# ---------------------------------------------------------------------------
# Prediction dataclass
# ---------------------------------------------------------------------------


def test_prediction_defaults():
    p = Prediction(prediction_text="X will happen", context="ctx")
    assert p.outcome is None
    assert p.outcome_recorded_at is None
    assert p.outcome_notes == ""


def test_prediction_to_dict_roundtrip():
    p = Prediction(prediction_text="X", context="ctx", outcome=True, outcome_notes="notes")
    d = p.to_dict()
    p2 = Prediction.from_dict(d)
    assert p2.prediction_text == "X"
    assert p2.outcome is True
    assert p2.outcome_notes == "notes"


# ---------------------------------------------------------------------------
# Hypothesis dataclass
# ---------------------------------------------------------------------------


def test_hypothesis_id_stable():
    h = Hypothesis(statement="Test statement", evidence=["e1"], counter_evidence=[])
    id1 = h.hypothesis_id
    id2 = h.hypothesis_id
    assert id1 == id2
    assert len(id1) == 12


def test_hypothesis_accuracy_no_outcomes():
    h = Hypothesis(statement="X", evidence=[], counter_evidence=[])
    # No outcomes → 0.5 (unknown)
    assert h.accuracy == 0.5


def test_hypothesis_accuracy_all_correct():
    h = Hypothesis(statement="X", evidence=[], counter_evidence=[])
    h.predictions = [
        Prediction("p1", "c", outcome=True),
        Prediction("p2", "c", outcome=True),
    ]
    assert h.accuracy == 1.0


def test_hypothesis_accuracy_mixed():
    h = Hypothesis(statement="X", evidence=[], counter_evidence=[])
    h.predictions = [
        Prediction("p1", "c", outcome=True),
        Prediction("p2", "c", outcome=False),
        Prediction("p3", "c", outcome=None),  # not counted
    ]
    assert abs(h.accuracy - 0.5) < 0.01


def test_hypothesis_sample_size():
    h = Hypothesis(statement="X", evidence=[], counter_evidence=[])
    h.predictions = [
        Prediction("p1", "c", outcome=True),
        Prediction("p2", "c", outcome=None),
    ]
    assert h.sample_size == 1


def test_hypothesis_to_dict_roundtrip():
    h = Hypothesis(
        statement="Test",
        evidence=["e1"],
        counter_evidence=["c1"],
        state=HypothesisState.HYPOTHESIS,
        confidence=0.7,
        domain="ai",
    )
    d = h.to_dict()
    h2 = Hypothesis.from_dict(d)
    assert h2.statement == "Test"
    assert h2.state == HypothesisState.HYPOTHESIS
    assert h2.confidence == 0.7
    assert h2.domain == "ai"


# ---------------------------------------------------------------------------
# _extract_pattern
# ---------------------------------------------------------------------------


def test_extract_pattern_normalizes_numbers(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    p1 = tracker._extract_pattern("Tool failed 42 times")
    p2 = tracker._extract_pattern("Tool failed 7 times")
    assert p1 == p2


def test_extract_pattern_strips_quoted_strings(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    p1 = tracker._extract_pattern('User prefers "dark mode"')
    p2 = tracker._extract_pattern('User prefers "light theme"')
    assert p1 == p2


def test_extract_pattern_max_50_chars(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    p = tracker._extract_pattern("x" * 200)
    assert len(p) <= 50


# ---------------------------------------------------------------------------
# observe
# ---------------------------------------------------------------------------


def test_observe_first_time_returns_none(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    result = tracker.observe("This approach works well")
    assert result is None


def test_observe_second_time_generates_hypothesis(monkeypatch, tmp_path):
    # Numbers normalize so both produce the same pattern key
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.observe("The approach works 3 times")
    result = tracker.observe("The approach works 5 times")
    assert result is not None
    assert isinstance(result, Hypothesis)


def test_observe_hypothesis_state(monkeypatch, tmp_path):
    # Quoted strings normalize to the same pattern
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.observe('User prefers "dark mode"')
    h = tracker.observe('User prefers "light mode"')
    assert h is not None
    assert h.state == HypothesisState.HYPOTHESIS


def test_observe_confidence_increases_with_more_observations(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.observe("prefer dark mode 3 times")
    h = tracker.observe("prefer dark mode 5 times")
    initial_confidence = h.confidence

    h2 = tracker.observe("prefer dark mode 7 times")
    assert h2 is not None
    assert h2.confidence >= initial_confidence


def test_observe_updates_existing_hypothesis(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.observe("the approach works 3 times")
    tracker.observe("the approach works 5 times")
    first_id = list(tracker.hypotheses.keys())[0]

    tracker.observe("the approach works 7 times")
    # Should update the existing hypothesis, not add a new one with the same pattern
    assert len(tracker.hypotheses) == 1
    assert tracker.hypotheses[first_id].confidence >= 0.5


def test_observe_persists_to_disk(monkeypatch, tmp_path):
    fake_file = tmp_path / "hypotheses.json"
    monkeypatch.setattr(HypothesisTracker, "HYPOTHESES_FILE", fake_file)
    tracker = HypothesisTracker()
    tracker.observe("Some repeated thing happens")
    assert fake_file.exists()


def test_observe_with_domain(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.observe("api fails 3 times", domain="fintech")
    h = tracker.observe("api fails 5 times", domain="fintech")
    if h is not None:
        assert h.domain == "fintech"


# ---------------------------------------------------------------------------
# _generate_hypothesis_statement
# ---------------------------------------------------------------------------


def test_generate_prefer_pattern(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    stmt = tracker._generate_hypothesis_statement(["User prefers dark mode"])
    assert "prefer" in stmt.lower()


def test_generate_error_pattern(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    stmt = tracker._generate_hypothesis_statement(["Tool error occurred here"])
    assert "issue" in stmt.lower() or "cause" in stmt.lower() or "tend" in stmt.lower()


def test_generate_success_pattern(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    stmt = tracker._generate_hypothesis_statement(["This approach works great"])
    assert "work" in stmt.lower() or "approach" in stmt.lower()


def test_generate_generic_pattern(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    stmt = tracker._generate_hypothesis_statement(["Completely neutral statement"])
    assert len(stmt) > 0


def test_generate_empty_observations(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    stmt = tracker._generate_hypothesis_statement([])
    assert stmt == "Unknown pattern"


# ---------------------------------------------------------------------------
# make_prediction
# ---------------------------------------------------------------------------


def test_make_prediction_returns_prediction(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    p = tracker.make_prediction(h.hypothesis_id, "Next time user will prefer x", context="ctx")
    assert isinstance(p, Prediction)
    assert p.prediction_text == "Next time user will prefer x"
    assert p.outcome is None


def test_make_prediction_sets_testing_state(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    tracker.make_prediction(h.hypothesis_id, "Will prefer x")
    assert tracker.hypotheses[h.hypothesis_id].state == HypothesisState.TESTING


def test_make_prediction_unknown_id_returns_none(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    result = tracker.make_prediction("nonexistent_id", "something")
    assert result is None


def test_make_prediction_appended_to_hypothesis(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    tracker.make_prediction(h.hypothesis_id, "pred 1")
    tracker.make_prediction(h.hypothesis_id, "pred 2")
    assert len(tracker.hypotheses[h.hypothesis_id].predictions) == 2


# ---------------------------------------------------------------------------
# record_outcome
# ---------------------------------------------------------------------------


def test_record_outcome_marks_correct(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    tracker.make_prediction(h.hypothesis_id, "x will repeat")
    tracker.record_outcome(h.hypothesis_id, 0, correct=True, notes="as expected")
    p = tracker.hypotheses[h.hypothesis_id].predictions[0]
    assert p.outcome is True
    assert p.outcome_notes == "as expected"
    assert p.outcome_recorded_at is not None


def test_record_outcome_invalid_index_is_safe(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    tracker.record_outcome(h.hypothesis_id, 99, correct=True)  # Should not raise


def test_record_outcome_unknown_hypothesis_is_safe(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_outcome("nonexistent", 0, correct=True)  # Should not raise


# ---------------------------------------------------------------------------
# _update_hypothesis_state
# ---------------------------------------------------------------------------


def test_update_state_needs_3_outcomes(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    h_id = h.hypothesis_id

    # Only 2 outcomes — state should stay in TESTING
    _fill_predictions(tracker, h_id, 2, correct=True)
    assert tracker.hypotheses[h_id].state == HypothesisState.TESTING


def test_update_state_validated_at_70_pct(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    h_id = h.hypothesis_id

    # 3 correct predictions → accuracy 1.0 → VALIDATED
    _fill_predictions(tracker, h_id, 3, correct=True)
    assert tracker.hypotheses[h_id].state == HypothesisState.VALIDATED


def test_update_state_invalidated_at_30_pct(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    h_id = h.hypothesis_id

    # 3 incorrect predictions → accuracy 0.0 → INVALIDATED
    _fill_predictions(tracker, h_id, 3, correct=False)
    assert tracker.hypotheses[h_id].state == HypothesisState.INVALIDATED


def test_update_state_testing_at_mid_accuracy(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    h_id = h.hypothesis_id

    # 3 predictions, ~50% accurate → TESTING
    tracker.make_prediction(h_id, "p1")
    tracker.make_prediction(h_id, "p2")
    tracker.make_prediction(h_id, "p3")
    tracker.record_outcome(h_id, 0, True)
    tracker.record_outcome(h_id, 1, False)
    tracker.record_outcome(h_id, 2, False)
    assert tracker.hypotheses[h_id].state == HypothesisState.TESTING


# ---------------------------------------------------------------------------
# add_counter_evidence
# ---------------------------------------------------------------------------


def test_add_counter_evidence(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    h_id = h.hypothesis_id
    tracker.add_counter_evidence(h_id, "actually this failed")
    assert "actually this failed" in tracker.hypotheses[h_id].counter_evidence


def test_add_counter_evidence_reduces_confidence(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    h_id = h.hypothesis_id
    before = tracker.hypotheses[h_id].confidence
    tracker.add_counter_evidence(h_id, "contradicting evidence")
    after = tracker.hypotheses[h_id].confidence
    assert after < before


def test_add_counter_evidence_unknown_id_is_safe(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.add_counter_evidence("nonexistent", "evidence")  # Should not raise


def test_add_counter_evidence_no_duplicates(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    h_id = h.hypothesis_id
    tracker.add_counter_evidence(h_id, "same counter")
    tracker.add_counter_evidence(h_id, "same counter")
    counter = tracker.hypotheses[h_id].counter_evidence
    assert counter.count("same counter") == 1


# ---------------------------------------------------------------------------
# get_testable_hypotheses
# ---------------------------------------------------------------------------


def test_get_testable_returns_hypothesis_state(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    _make_hypothesis(tracker, statement="Testable pattern hypothesis")
    testable = tracker.get_testable_hypotheses()
    assert len(testable) >= 1
    for h in testable:
        assert h.state in (HypothesisState.HYPOTHESIS, HypothesisState.TESTING)


def test_get_testable_respects_limit(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    # Create 3 distinct hypotheses directly
    for i in range(3):
        _make_hypothesis(tracker, statement=f"Distinct hypothesis number {i}")
    testable = tracker.get_testable_hypotheses(limit=2)
    assert len(testable) <= 2


# ---------------------------------------------------------------------------
# get_pending_predictions
# ---------------------------------------------------------------------------


def test_get_pending_predictions_empty(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    assert tracker.get_pending_predictions() == []


def test_get_pending_predictions_returns_unresolved(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    tracker.make_prediction(h.hypothesis_id, "pred")
    pending = tracker.get_pending_predictions()
    assert len(pending) == 1
    assert pending[0][1] == 0  # index 0


def test_get_pending_excludes_resolved(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    h_id = h.hypothesis_id
    tracker.make_prediction(h_id, "pred")
    tracker.record_outcome(h_id, 0, correct=True)
    pending = tracker.get_pending_predictions()
    assert len(pending) == 0


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


def test_get_stats_empty(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    stats = tracker.get_stats()
    assert stats["total_hypotheses"] == 0
    assert stats["total_predictions"] == 0
    assert stats["outcomes_recorded"] == 0
    assert stats["observation_patterns"] == 0


def test_get_stats_counts_hypotheses(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    _make_hypothesis(tracker)
    stats = tracker.get_stats()
    assert stats["total_hypotheses"] == 1


def test_get_stats_counts_predictions(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    tracker.make_prediction(h.hypothesis_id, "p1")
    tracker.make_prediction(h.hypothesis_id, "p2")
    stats = tracker.get_stats()
    assert stats["total_predictions"] == 2


def test_get_stats_pending_outcomes(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    h = _make_hypothesis(tracker)
    tracker.make_prediction(h.hypothesis_id, "pred")
    stats = tracker.get_stats()
    assert stats["pending_outcomes"] == 1


def test_get_stats_by_state(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    _make_hypothesis(tracker, state=HypothesisState.HYPOTHESIS)
    stats = tracker.get_stats()
    assert "hypothesis" in stats["by_state"] or "testing" in stats["by_state"]


def test_get_stats_observation_patterns(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.observe("first distinct observation here")
    tracker.observe("second completely different thing!")
    stats = tracker.get_stats()
    assert stats["observation_patterns"] >= 1


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


def test_persistence_roundtrip(monkeypatch, tmp_path):
    fake_file = tmp_path / "hypotheses.json"
    monkeypatch.setattr(HypothesisTracker, "HYPOTHESES_FILE", fake_file)

    t1 = HypothesisTracker()
    h = _make_hypothesis(t1, statement="Persisted hypothesis")
    t1._save_hypotheses()

    t2 = HypothesisTracker()
    assert len(t2.hypotheses) == 1


def test_load_handles_corrupt_file(monkeypatch, tmp_path):
    fake_file = tmp_path / "hypotheses.json"
    monkeypatch.setattr(HypothesisTracker, "HYPOTHESES_FILE", fake_file)
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("not json", encoding="utf-8")
    tracker = HypothesisTracker()  # Should not raise
    assert tracker.hypotheses == {}


# ---------------------------------------------------------------------------
# get_hypothesis_tracker / observe_for_hypothesis singletons
# ---------------------------------------------------------------------------


def test_get_hypothesis_tracker_singleton(monkeypatch, tmp_path):
    monkeypatch.setattr(HypothesisTracker, "HYPOTHESES_FILE", tmp_path / "h.json")
    monkeypatch.setattr(ht, "_tracker", None)
    t1 = get_hypothesis_tracker()
    t2 = get_hypothesis_tracker()
    assert t1 is t2


def test_observe_for_hypothesis_convenience(monkeypatch, tmp_path):
    monkeypatch.setattr(HypothesisTracker, "HYPOTHESES_FILE", tmp_path / "h.json")
    monkeypatch.setattr(ht, "_tracker", None)
    # First observe returns None (need 2)
    result = observe_for_hypothesis("first thing", domain="ai")
    assert result is None
