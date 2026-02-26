from __future__ import annotations

import lib.meta_ralph as mr


def _score(total: int) -> mr.QualityScore:
    # 5 dimensions + ethics default 1
    # Keep values simple for deterministic tests.
    if total <= 3:
        return mr.QualityScore(actionability=0, novelty=0, reasoning=0, specificity=1, outcome_linked=1, ethics=1)
    return mr.QualityScore(actionability=2, novelty=1, reasoning=1, specificity=1, outcome_linked=1, ethics=1)


def test_runtime_llm_refinement_applies_when_enabled_and_better(monkeypatch):
    monkeypatch.setattr(mr, "RUNTIME_REFINER_LLM_ENABLED", True)
    monkeypatch.setattr(mr, "RUNTIME_REFINER_LLM_PROVIDER", "auto")
    monkeypatch.setattr(mr, "RUNTIME_REFINER_LLM_TIMEOUT_S", 2.0)
    monkeypatch.setattr(mr, "RUNTIME_REFINER_LLM_MAX_CHARS", 260)

    ralph = mr.MetaRalph()
    monkeypatch.setattr(ralph, "_attempt_llm_refinement", lambda learning, issues, context: "When auth token expires: refresh token because stale credentials trigger retries")
    monkeypatch.setattr(ralph, "_score_learning", lambda text, context: _score(6) if "refresh token" in text else _score(3))
    monkeypatch.setattr("lib.elevation.elevate", lambda text, context: text)

    out = ralph._attempt_refinement("Token issue observed", ["No actionable guidance"], {})
    assert out is not None
    assert "refresh token" in out


def test_runtime_llm_refinement_kept_off_when_candidate_worse(monkeypatch):
    monkeypatch.setattr(mr, "RUNTIME_REFINER_LLM_ENABLED", True)
    ralph = mr.MetaRalph()
    monkeypatch.setattr(ralph, "_attempt_llm_refinement", lambda learning, issues, context: "Generic note")
    monkeypatch.setattr(ralph, "_score_learning", lambda text, context: _score(3))
    monkeypatch.setattr("lib.elevation.elevate", lambda text, context: text)

    out = ralph._attempt_refinement("Token issue observed", ["No actionable guidance"], {})
    # No structural/elevation change and LLM candidate not better -> no refinement.
    assert out is None

