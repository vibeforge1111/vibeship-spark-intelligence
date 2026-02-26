from __future__ import annotations

import copy

import pytest

import lib.distillation_refiner as ref


class _AQ:
    def __init__(self, score: float, *, suppressed: bool = False) -> None:
        self._payload = {
            "unified_score": float(score),
            "suppressed": bool(suppressed),
            "actionability": float(score),
            "reasoning": float(score),
            "specificity": float(score),
            "structure": {},
            "advisory_text": "",
        }

    def to_dict(self):
        return dict(self._payload)


@pytest.fixture(autouse=True)
def _restore_runtime_refiner_cfg():
    original = copy.deepcopy(ref._RUNTIME_REFINER_CFG)
    try:
        yield
    finally:
        ref._RUNTIME_REFINER_CFG = original


def test_runtime_llm_refiner_disabled_by_default(monkeypatch):
    ref.reload_runtime_refiner_from(
        {
            "runtime_refiner_llm_enabled": False,
            "runtime_refiner_llm_min_unified_score": 0.9,
        }
    )

    monkeypatch.setattr(ref, "transform_for_advisory", lambda _text, source="eidos": _AQ(0.10))
    monkeypatch.setattr(
        ref,
        "_llm_refine_candidate",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("runtime llm refiner must not run when disabled")
        ),
    )

    text, quality = ref.refine_distillation(
        "maybe validate payload structure before processing",
        source="eidos",
        min_unified_score=0.80,
    )
    assert "validate payload structure" in text
    assert quality["unified_score"] == 0.10


def test_runtime_llm_refiner_applies_when_enabled_and_better(monkeypatch):
    ref.reload_runtime_refiner_from(
        {
            "runtime_refiner_llm_enabled": True,
            "runtime_refiner_llm_min_unified_score": 0.75,
            "runtime_refiner_llm_provider": "claude",
        }
    )

    def _transform(text: str, source: str = "eidos"):
        if text.startswith("When validating webhook payloads"):
            return _AQ(0.91)
        return _AQ(0.22)

    monkeypatch.setattr(ref, "transform_for_advisory", _transform)
    monkeypatch.setattr(ref, "elevate", lambda _text, _ctx: "")
    monkeypatch.setattr(ref, "_rewrite_from_structure", lambda _s, fallback: fallback)
    monkeypatch.setattr(ref, "_compose_from_structure", lambda _s: "")
    monkeypatch.setattr(
        ref,
        "_llm_refine_candidate",
        lambda *_a, **_kw: "When validating webhook payloads: enforce schema because malformed payloads break handlers",
    )

    text, quality = ref.refine_distillation(
        "validate payload",
        source="eidos",
        min_unified_score=0.80,
    )
    assert text.startswith("When validating webhook payloads")
    assert quality["unified_score"] == 0.91


def test_runtime_llm_refiner_keeps_deterministic_if_llm_worse(monkeypatch):
    ref.reload_runtime_refiner_from(
        {
            "runtime_refiner_llm_enabled": True,
            "runtime_refiner_llm_min_unified_score": 0.90,
            "runtime_refiner_llm_provider": "auto",
        }
    )

    deterministic_text = (
        "When editing API handlers: validate request schema because malformed payloads fail downstream"
    )
    llm_text = "When working on API handlers: validate input"

    def _transform(text: str, source: str = "eidos"):
        if text == deterministic_text:
            return _AQ(0.68)
        if text == llm_text:
            return _AQ(0.35)
        return _AQ(0.18)

    monkeypatch.setattr(ref, "transform_for_advisory", _transform)
    monkeypatch.setattr(ref, "elevate", lambda _text, _ctx: deterministic_text)
    monkeypatch.setattr(ref, "_llm_refine_candidate", lambda *_a, **_kw: llm_text)

    text, quality = ref.refine_distillation(
        "validate input",
        source="eidos",
        min_unified_score=0.70,
    )
    assert text == deterministic_text
    assert quality["unified_score"] == 0.68
