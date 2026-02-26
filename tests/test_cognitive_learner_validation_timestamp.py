"""Regression tests for cognitive_learner timestamp consistency.

learn_blind_spot() and learn_user_expertise() previously incremented
times_validated directly, bypassing _touch_validation() and therefore
never updating last_validated_at. Downstream freshness scoring and
_merge_insights() both rely on last_validated_at being current.
"""
from __future__ import annotations

import lib.cognitive_learner as cl_mod
from lib.cognitive_learner import CognitiveLearner


def _make_learner(tmp_path, monkeypatch) -> CognitiveLearner:
    insights_file = tmp_path / "cognitive_insights.json"
    monkeypatch.setattr(CognitiveLearner, "INSIGHTS_FILE", insights_file)
    monkeypatch.setattr(CognitiveLearner, "LOCK_FILE", tmp_path / ".cognitive.lock")
    return CognitiveLearner()


def test_learn_blind_spot_updates_last_validated_at(tmp_path, monkeypatch):
    """Re-calling learn_blind_spot on an existing insight must update last_validated_at."""
    learner = _make_learner(tmp_path, monkeypatch)

    learner.learn_blind_spot("type errors", "forgot to cast int")
    key = learner._generate_key(cl_mod.CognitiveCategory.SELF_AWARENESS, "blindspot:type errors")
    first_ts = learner.insights[key].last_validated_at
    first_count = learner.insights[key].times_validated

    # Second call — should merge and refresh the timestamp
    learner.learn_blind_spot("type errors", "same issue in different module")
    second_ts = learner.insights[key].last_validated_at
    second_count = learner.insights[key].times_validated

    assert second_count == first_count + 1, (
        f"times_validated should have incremented; got {first_count} → {second_count}"
    )
    assert second_ts is not None, (
        "last_validated_at must be set after second call; _touch_validation() was not invoked"
    )


def test_learn_user_expertise_updates_last_validated_at(tmp_path, monkeypatch):
    """Re-calling learn_user_expertise on an existing insight must update last_validated_at."""
    learner = _make_learner(tmp_path, monkeypatch)

    learner.learn_user_expertise("Python", "advanced", "wrote metaclass from scratch")
    key = learner._generate_key(
        cl_mod.CognitiveCategory.USER_UNDERSTANDING, "expertise:Python"
    )
    first_ts = learner.insights[key].last_validated_at
    first_count = learner.insights[key].times_validated

    learner.learn_user_expertise("Python", "expert", "debugged CPython internals")
    second_ts = learner.insights[key].last_validated_at
    second_count = learner.insights[key].times_validated

    assert second_count == first_count + 1, (
        f"times_validated should have incremented; got {first_count} → {second_count}"
    )
    assert second_ts is not None, (
        "last_validated_at must be set after second call; _touch_validation() was not invoked"
    )
