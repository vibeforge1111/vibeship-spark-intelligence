from pathlib import Path
import types

import lib.feedback as fb
import lib.skills_registry as sr


def _write_skill(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_update_skill_effectiveness(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_SKILLS_DIR", str(tmp_path))
    monkeypatch.setattr(sr, "INDEX_FILE", tmp_path / "skills_index.json")
    monkeypatch.setattr(fb, "SKILLS_EFFECTIVENESS_FILE", tmp_path / "skills_effectiveness.json")

    content = """name: auth-specialist
description: Authentication and OAuth flows
owns:
  - oauth
"""
    _write_skill(tmp_path / "security" / "auth-specialist.yaml", content)

    # Build index
    sr.load_skills_index(force_refresh=True)

    # Update effectiveness
    fb.update_skill_effectiveness("oauth login", success=True, limit=1)
    data = fb._load_json(fb.SKILLS_EFFECTIVENESS_FILE)
    assert data["auth-specialist"]["success"] == 1


def _make_learner(key: str, insight):
    """Build a minimal learner stub with one insight."""
    learner = types.SimpleNamespace(insights={key: insight})
    learner._save_insights = lambda: None
    return learner


def _make_insight(times_validated=0, times_contradicted=0):
    """Build a minimal self_awareness insight stub."""
    return types.SimpleNamespace(
        category=types.SimpleNamespace(value="self_awareness"),
        times_validated=times_validated,
        times_contradicted=times_contradicted,
        last_validated_at=None,
    )


def test_update_self_awareness_reliability_success_validates(monkeypatch):
    """A successful tool call must increment times_validated, not times_contradicted."""
    insight = _make_insight()
    monkeypatch.setattr(fb, "get_cognitive_learner", lambda: _make_learner("edit_assumption_edit", insight))

    fb.update_self_awareness_reliability("Edit", success=True)

    assert insight.times_validated == 1, (
        f"Expected times_validated=1, got {insight.times_validated}. "
        "Success must VALIDATE an insight, not contradict it."
    )
    assert insight.times_contradicted == 0


def test_update_self_awareness_reliability_failure_contradicts(monkeypatch):
    """A failed tool call must increment times_contradicted, not times_validated."""
    insight = _make_insight()
    monkeypatch.setattr(fb, "get_cognitive_learner", lambda: _make_learner("edit_assumption_edit", insight))

    fb.update_self_awareness_reliability("Edit", success=False)

    assert insight.times_contradicted == 1, (
        f"Expected times_contradicted=1, got {insight.times_contradicted}. "
        "Failure must CONTRADICT an insight, not validate it."
    )
    assert insight.times_validated == 0


def test_update_self_awareness_reliability_no_match_is_noop(monkeypatch):
    """When no insight key matches the tool name, function must not raise."""
    # Only has a "bash_assumption" insight — "Edit" won't match
    insight = _make_insight()
    monkeypatch.setattr(fb, "get_cognitive_learner", lambda: _make_learner("bash_assumption_bash", insight))

    # Should not raise, and should not touch this insight
    fb.update_self_awareness_reliability("Edit", success=True)
    fb.update_self_awareness_reliability("Edit", success=False)

    assert insight.times_validated == 0
    assert insight.times_contradicted == 0
