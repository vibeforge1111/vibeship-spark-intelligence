from __future__ import annotations

from lib.pattern_detection.request_tracker import RequestTracker


def test_request_tracker_avoids_substring_false_positive_for_scope():
    tracker = RequestTracker()
    message = "Please describe microscope calibration steps"

    intent = tracker._extract_intent(message)
    hypothesis = tracker._extract_hypothesis(message)
    prediction = tracker._generate_prediction(message, {})
    assumptions = tracker._extract_assumptions(message, {})

    assert "control scope" not in intent.lower()
    assert "constraining project scope" not in hypothesis.lower()
    assert "respect stated constraints" not in prediction.lower()
    assert "constraints are explicit and mutually consistent" not in assumptions


def test_request_tracker_matches_explicit_scope_keyword():
    tracker = RequestTracker()
    message = "Scope is fixed for this release, keep the migration small."

    intent = tracker._extract_intent(message)
    hypothesis = tracker._extract_hypothesis(message)
    prediction = tracker._generate_prediction(message, {})
    assumptions = tracker._extract_assumptions(message, {})

    assert "control scope" in intent.lower()
    assert hypothesis == "User is constraining project scope"
    assert "respect stated constraints" in prediction.lower()
    assert "Constraints are explicit and mutually consistent" in assumptions
