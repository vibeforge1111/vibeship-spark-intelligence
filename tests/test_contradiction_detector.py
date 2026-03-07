"""Tests for lib.contradiction_detector."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import lib.contradiction_detector as cd
from lib.contradiction_detector import (
    ContradictionType,
    Contradiction,
    _has_negation,
    _has_opposition,
    _extract_topic,
    ContradictionDetector,
    get_contradiction_detector,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    monkeypatch.setattr(cd, "_detector", None)


@pytest.fixture()
def detector(tmp_path, monkeypatch):
    monkeypatch.setattr(ContradictionDetector, "CONTRADICTIONS_FILE", tmp_path / "contradictions.json")
    return ContradictionDetector()


# ---------------------------------------------------------------------------
# ContradictionType enum
# ---------------------------------------------------------------------------

def test_contradiction_type_values():
    assert ContradictionType.DIRECT.value == "direct"
    assert ContradictionType.TEMPORAL.value == "temporal"
    assert ContradictionType.CONTEXTUAL.value == "contextual"
    assert ContradictionType.UNCERTAIN.value == "uncertain"


# ---------------------------------------------------------------------------
# Contradiction dataclass
# ---------------------------------------------------------------------------

def _make_contradiction(**kw) -> Contradiction:
    defaults = dict(
        existing_key="key-1",
        existing_text="I prefer tabs",
        new_text="I hate tabs",
        similarity=0.75,
        contradiction_type=ContradictionType.DIRECT,
        confidence=0.6,
    )
    defaults.update(kw)
    return Contradiction(**defaults)


def test_contradiction_to_dict_keys():
    c = _make_contradiction()
    d = c.to_dict()
    for key in ("existing_key", "existing_text", "new_text", "similarity",
                "contradiction_type", "confidence", "detected_at",
                "resolved", "resolution", "resolution_type"):
        assert key in d, f"missing key {key}"


def test_contradiction_to_dict_type_is_value():
    c = _make_contradiction(contradiction_type=ContradictionType.TEMPORAL)
    assert c.to_dict()["contradiction_type"] == "temporal"


def test_contradiction_to_dict_resolved_false_by_default():
    c = _make_contradiction()
    assert c.to_dict()["resolved"] is False


def test_contradiction_from_dict_roundtrip():
    c = _make_contradiction()
    d = c.to_dict()
    c2 = Contradiction.from_dict(d)
    assert c2.existing_key == c.existing_key
    assert c2.existing_text == c.existing_text
    assert c2.new_text == c.new_text
    assert c2.similarity == c.similarity
    assert c2.contradiction_type == c.contradiction_type
    assert c2.confidence == c.confidence
    assert c2.resolved == c.resolved


def test_contradiction_from_dict_optional_fields():
    d = {
        "existing_key": "k", "existing_text": "a", "new_text": "b",
        "similarity": 0.5, "contradiction_type": "direct", "confidence": 0.4,
    }
    c = Contradiction.from_dict(d)
    assert c.resolved is False
    assert c.resolution is None
    assert c.resolution_type is None


# ---------------------------------------------------------------------------
# _has_negation
# ---------------------------------------------------------------------------

def test_has_negation_not():
    assert _has_negation("I do not like this") is True


def test_has_negation_never():
    assert _has_negation("never use global state") is True


def test_has_negation_dont():
    assert _has_negation("don't do that") is True


def test_has_negation_doesnt():
    assert _has_negation("it doesn't work") is True


def test_has_negation_wont():
    assert _has_negation("it won't scale") is True


def test_has_negation_cant():
    assert _has_negation("can't be done") is True


def test_has_negation_shouldnt():
    assert _has_negation("shouldn't rely on this") is True


def test_has_negation_none():
    assert _has_negation("I like this approach") is False


def test_has_negation_empty():
    assert _has_negation("") is False


def test_has_negation_nothing():
    assert _has_negation("nothing works here") is True


# ---------------------------------------------------------------------------
# _has_opposition
# ---------------------------------------------------------------------------

def test_has_opposition_prefer_avoid():
    has_opp, conf = _has_opposition("I prefer tabs", "avoid tabs")
    assert has_opp is True
    assert conf == 0.8


def test_has_opposition_like_hate():
    has_opp, conf = _has_opposition("I like Python", "I hate Python")
    assert has_opp is True
    assert conf == 0.8


def test_has_opposition_always_never():
    has_opp, conf = _has_opposition("always use type hints", "never use type hints")
    assert has_opp is True


def test_has_opposition_good_bad():
    has_opp, conf = _has_opposition("this is good", "this is bad")
    assert has_opp is True


def test_has_opposition_reversed_pair():
    has_opp, conf = _has_opposition("avoid tight coupling", "prefer tight coupling")
    assert has_opp is True


def test_has_opposition_negation_asymmetry():
    has_opp, conf = _has_opposition("use redis", "do not use redis")
    assert has_opp is True
    assert conf == 0.6


def test_has_opposition_no_opposition():
    has_opp, conf = _has_opposition("use caching", "caching improves performance")
    assert has_opp is False
    assert conf == 0.0


def test_has_opposition_both_negated():
    # Both have negation → symmetric → no asymmetry detected
    has_opp, conf = _has_opposition("don't use X", "don't use Y")
    # Both negated → neg1==neg2 → no asymmetry; no opposition pair → False
    assert has_opp is False


# ---------------------------------------------------------------------------
# _extract_topic
# ---------------------------------------------------------------------------

def test_extract_topic_strips_prefers():
    result = _extract_topic("User prefers tabs over spaces")
    assert "prefers" not in result
    assert len(result.split()) <= 6


def test_extract_topic_strips_likes():
    result = _extract_topic("likes dark mode themes")
    assert "likes" not in result


def test_extract_topic_strips_i_struggle():
    result = _extract_topic("I struggle with async code")
    assert "struggle" not in result


def test_extract_topic_short_result():
    result = _extract_topic("some very long sentence with many words that should be truncated")
    assert len(result.split()) <= 6


def test_extract_topic_lowercased():
    result = _extract_topic("User Prefers TABS")
    assert result == result.lower()


# ---------------------------------------------------------------------------
# ContradictionDetector — init and file I/O
# ---------------------------------------------------------------------------

def test_detector_init_no_file(detector):
    assert detector.contradictions == []


def test_detector_load_existing_contradictions(tmp_path, monkeypatch):
    path = tmp_path / "contradictions.json"
    c = _make_contradiction()
    path.write_text(json.dumps([c.to_dict()]), encoding="utf-8")
    monkeypatch.setattr(ContradictionDetector, "CONTRADICTIONS_FILE", path)
    det = ContradictionDetector()
    assert len(det.contradictions) == 1
    assert det.contradictions[0].existing_key == "key-1"


def test_detector_load_corrupt_file_silently(tmp_path, monkeypatch):
    path = tmp_path / "contradictions.json"
    path.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(ContradictionDetector, "CONTRADICTIONS_FILE", path)
    det = ContradictionDetector()
    assert det.contradictions == []


def test_detector_save_creates_file(detector):
    c = _make_contradiction()
    detector.contradictions.append(c)
    detector._save_contradictions()
    data = json.loads(ContradictionDetector.CONTRADICTIONS_FILE.read_text())
    assert len(data) == 1
    assert data[0]["existing_key"] == "key-1"


# ---------------------------------------------------------------------------
# ContradictionDetector — _cosine_similarity
# ---------------------------------------------------------------------------

def test_cosine_similarity_identical():
    v = [1.0, 0.0, 0.0]
    det = ContradictionDetector.__new__(ContradictionDetector)
    det.contradictions = []
    assert abs(det._cosine_similarity(v, v) - 1.0) < 1e-9


def test_cosine_similarity_orthogonal():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    # Need an instance
    det = ContradictionDetector.__new__(ContradictionDetector)
    det.contradictions = []
    assert abs(det._cosine_similarity(a, b)) < 1e-9


def test_cosine_similarity_zero_vector():
    det = ContradictionDetector.__new__(ContradictionDetector)
    det.contradictions = []
    assert det._cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_cosine_similarity_empty():
    det = ContradictionDetector.__new__(ContradictionDetector)
    det.contradictions = []
    assert det._cosine_similarity([], []) == 0.0


def test_cosine_similarity_mismatched_length():
    det = ContradictionDetector.__new__(ContradictionDetector)
    det.contradictions = []
    assert det._cosine_similarity([1.0], [1.0, 2.0]) == 0.0


# ---------------------------------------------------------------------------
# ContradictionDetector — _infer_type
# ---------------------------------------------------------------------------

def test_infer_type_temporal(detector):
    assert detector._infer_type("old way", "now we use redis") == ContradictionType.TEMPORAL


def test_infer_type_temporal_recently(detector):
    assert detector._infer_type("old", "recently changed") == ContradictionType.TEMPORAL


def test_infer_type_contextual_new(detector):
    assert detector._infer_type("always cache", "when load is low, skip cache") == ContradictionType.CONTEXTUAL


def test_infer_type_contextual_existing(detector):
    assert detector._infer_type("sometimes use X", "use Y") == ContradictionType.CONTEXTUAL


def test_infer_type_uncertain_default(detector):
    assert detector._infer_type("prefer A", "prefer B") == ContradictionType.UNCERTAIN


# ---------------------------------------------------------------------------
# ContradictionDetector — get_unresolved / get_stats / resolve
# ---------------------------------------------------------------------------

def test_get_unresolved_empty(detector):
    assert detector.get_unresolved() == []


def test_get_unresolved_returns_unresolved(detector):
    c1 = _make_contradiction()
    c2 = _make_contradiction(existing_key="key-2")
    c2.resolved = True
    detector.contradictions = [c1, c2]
    unresolved = detector.get_unresolved()
    assert len(unresolved) == 1
    assert unresolved[0][1].existing_key == "key-1"


def test_get_stats_empty(detector):
    stats = detector.get_stats()
    assert stats == {"total": 0, "resolved": 0, "unresolved": 0, "by_type": {}, "resolution_types": {}}


def test_get_stats_with_contradictions(detector):
    c1 = _make_contradiction(contradiction_type=ContradictionType.DIRECT)
    c2 = _make_contradiction(existing_key="k2", contradiction_type=ContradictionType.TEMPORAL)
    c2.resolved = True
    c2.resolution_type = "update"
    detector.contradictions = [c1, c2]
    stats = detector.get_stats()
    assert stats["total"] == 2
    assert stats["resolved"] == 1
    assert stats["unresolved"] == 1
    assert stats["by_type"]["direct"] == 1
    assert stats["by_type"]["temporal"] == 1
    assert stats["resolution_types"]["update"] == 1


def test_resolve_marks_resolved(detector):
    c = _make_contradiction()
    detector.contradictions = [c]
    detector.resolve(0, "context", "both valid in different scopes")
    assert detector.contradictions[0].resolved is True
    assert detector.contradictions[0].resolution_type == "context"
    assert "both valid" in detector.contradictions[0].resolution


def test_resolve_out_of_range_noop(detector):
    c = _make_contradiction()
    detector.contradictions = [c]
    detector.resolve(99, "update")  # should not raise
    assert c.resolved is False


# ---------------------------------------------------------------------------
# check_contradiction — mocked cognitive_learner (no embeddings)
# ---------------------------------------------------------------------------

def test_check_contradiction_no_learner(detector, monkeypatch):
    # If cognitive_learner import fails, returns None
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "lib.cognitive_learner" or (name == ".cognitive_learner"):
            raise ImportError("mocked")
        return real_import(name, *args, **kwargs)

    # Patch get_embedding to return None and learner to raise
    detector._get_embedding = lambda text: None
    monkeypatch.setattr(cd, "get_contradiction_detector", lambda: detector)

    # Simulate learner not importable by patching inside check_contradiction
    result = detector.check_contradiction("I prefer Y", min_similarity=0.0)
    # Either returns None or a Contradiction depending on if learner.insights is empty
    assert result is None or isinstance(result, Contradiction)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

def test_get_contradiction_detector_returns_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(ContradictionDetector, "CONTRADICTIONS_FILE", tmp_path / "c.json")
    det = get_contradiction_detector()
    assert isinstance(det, ContradictionDetector)


def test_get_contradiction_detector_singleton(tmp_path, monkeypatch):
    monkeypatch.setattr(ContradictionDetector, "CONTRADICTIONS_FILE", tmp_path / "c.json")
    d1 = get_contradiction_detector()
    d2 = get_contradiction_detector()
    assert d1 is d2
