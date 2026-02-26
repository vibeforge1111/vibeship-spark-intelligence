"""Tests for lib/effect_evaluator.py — deterministic advisory effect evaluator."""
from __future__ import annotations

import json
import re
from typing import Any, Dict

import pytest

from lib.effect_evaluator import (
    _strip_think,
    _extract_json_obj,
    evaluate_effect,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _advisory(recommendation: str = "Do something useful") -> Dict[str, Any]:
    return {"recommendation": recommendation}


def _match(
    status: str = "acted",
    effect_hint: str = "neutral",
    confidence_hint: float = 0.35,
    match_type: str = "keyword",
    evidence_excerpt: str = "",
) -> Dict[str, Any]:
    return {
        "status": status,
        "effect_hint": effect_hint,
        "confidence_hint": confidence_hint,
        "match_type": match_type,
        "evidence_excerpt": evidence_excerpt,
    }


# ---------------------------------------------------------------------------
# _strip_think
# ---------------------------------------------------------------------------


def test_strip_think_removes_tags():
    text = "<think>internal reasoning</think>Final answer"
    result = _strip_think(text)
    assert "think" not in result.lower()
    assert "Final answer" in result


def test_strip_think_multiline():
    text = "<think>\nline 1\nline 2\n</think>output"
    assert "output" in _strip_think(text)
    assert "line 1" not in _strip_think(text)


def test_strip_think_case_insensitive():
    assert "hidden" not in _strip_think("<THINK>hidden</THINK>visible")
    assert "visible" in _strip_think("<THINK>hidden</THINK>visible")


def test_strip_think_no_tags_unchanged():
    assert _strip_think("plain text") == "plain text"


def test_strip_think_empty_string():
    assert _strip_think("") == ""


def test_strip_think_none_safe():
    assert _strip_think(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _extract_json_obj
# ---------------------------------------------------------------------------


def test_extract_json_obj_direct_parse():
    obj = _extract_json_obj('{"effect": "positive", "confidence": 0.9}')
    assert obj["effect"] == "positive"


def test_extract_json_obj_embedded_json():
    text = 'Some text before {"effect": "negative"} some text after'
    obj = _extract_json_obj(text)
    assert obj is not None
    assert obj["effect"] == "negative"


def test_extract_json_obj_returns_none_for_invalid():
    assert _extract_json_obj("no json here at all") is None


def test_extract_json_obj_returns_none_for_empty():
    assert _extract_json_obj("") is None


def test_extract_json_obj_nested():
    text = '{"a": {"b": 1}}'
    obj = _extract_json_obj(text)
    assert obj["a"]["b"] == 1


def test_extract_json_obj_with_surrounding_prose():
    text = "My analysis:\n\n{\"effect\": \"neutral\", \"confidence\": 0.5, \"reason\": \"ok\"}"
    obj = _extract_json_obj(text)
    assert obj is not None
    assert obj["confidence"] == 0.5


# ---------------------------------------------------------------------------
# evaluate_effect — skipped status
# ---------------------------------------------------------------------------


def test_evaluate_skipped_returns_neutral():
    result = evaluate_effect(_advisory(), _match(status="skipped"))
    assert result["effect"] == "neutral"
    assert result["reason"] == "advisory_skipped"


def test_evaluate_skipped_confidence_at_least_075():
    result = evaluate_effect(_advisory(), _match(status="skipped", confidence_hint=0.1))
    assert result["confidence"] >= 0.75


def test_evaluate_skipped_high_confidence_kept():
    result = evaluate_effect(_advisory(), _match(status="skipped", confidence_hint=0.9))
    assert result["confidence"] >= 0.75


# ---------------------------------------------------------------------------
# evaluate_effect — unresolved status
# ---------------------------------------------------------------------------


def test_evaluate_unresolved_returns_neutral():
    result = evaluate_effect(_advisory(), _match(status="unresolved"))
    assert result["effect"] == "neutral"
    assert result["reason"] == "no_action_evidence"


def test_evaluate_unresolved_confidence_capped_at_045():
    result = evaluate_effect(_advisory(), _match(status="unresolved", confidence_hint=0.9))
    assert result["confidence"] <= 0.45


# ---------------------------------------------------------------------------
# evaluate_effect — acted with hint
# ---------------------------------------------------------------------------


def test_evaluate_acted_positive_hint():
    result = evaluate_effect(
        _advisory(), _match(status="acted", effect_hint="positive", confidence_hint=0.5)
    )
    assert result["effect"] == "positive"
    assert result["confidence"] >= 0.8


def test_evaluate_acted_negative_hint():
    result = evaluate_effect(
        _advisory(), _match(status="acted", effect_hint="negative", confidence_hint=0.5)
    )
    assert result["effect"] == "negative"
    assert result["confidence"] >= 0.8


def test_evaluate_acted_neutral_hint_no_confidence_boost():
    result = evaluate_effect(
        _advisory(), _match(status="acted", effect_hint="neutral", confidence_hint=0.5)
    )
    assert result["effect"] == "neutral"
    # Neutral doesn't get boosted above 0.8
    assert result["confidence"] == 0.5


def test_evaluate_acted_hint_reason_contains_match_type():
    result = evaluate_effect(
        _advisory(), _match(status="acted", effect_hint="positive", match_type="tool_name")
    )
    assert "tool_name" in result["reason"]


def test_evaluate_confidence_clamped_0_to_1():
    result = evaluate_effect(
        _advisory(), _match(status="acted", effect_hint="positive", confidence_hint=2.0)
    )
    assert 0.0 <= result["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# evaluate_effect — default neutral fallback
# ---------------------------------------------------------------------------


def test_evaluate_fallback_neutral_when_hint_unrecognized():
    # An unrecognized hint (not positive/neutral/negative) → default_neutral branch
    result = evaluate_effect(
        _advisory(),
        {"status": "acted", "effect_hint": "ambiguous", "confidence_hint": 0.3, "match_type": "x"},
    )
    assert result["effect"] == "neutral"
    assert result["reason"] == "default_neutral"


def test_evaluate_fallback_confidence_capped_at_06():
    # Unrecognized hint → fallback caps confidence at min(0.6, hint)
    result = evaluate_effect(
        _advisory(),
        {"status": "acted", "effect_hint": "ambiguous", "confidence_hint": 0.8, "match_type": "x"},
    )
    assert result["confidence"] <= 0.6


def test_evaluate_empty_effect_hint_treated_as_neutral():
    # Empty string normalizes to "neutral" via `or "neutral"`, returns match_* reason
    result = evaluate_effect(
        _advisory(),
        {"status": "acted", "effect_hint": "", "confidence_hint": 0.5, "match_type": "kw"},
    )
    assert result["effect"] == "neutral"
    assert result["reason"].startswith("match_")


# ---------------------------------------------------------------------------
# evaluate_effect — minimax disabled (no env var)
# ---------------------------------------------------------------------------


def test_evaluate_minimax_skipped_without_api_key(monkeypatch):
    # No MINIMAX_API_KEY → _minimax_effect returns None → default neutral
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("SPARK_MINIMAX_API_KEY", raising=False)
    result = evaluate_effect(
        _advisory(),
        {"status": "acted", "effect_hint": "", "confidence_hint": 0.3, "match_type": "x"},
        use_minimax=True,
    )
    assert result["effect"] == "neutral"


# ---------------------------------------------------------------------------
# evaluate_effect — return structure
# ---------------------------------------------------------------------------


def test_evaluate_always_has_effect_key():
    for status in ("skipped", "unresolved", "acted"):
        result = evaluate_effect(_advisory(), _match(status=status))
        assert "effect" in result


def test_evaluate_always_has_confidence_key():
    for status in ("skipped", "unresolved", "acted"):
        result = evaluate_effect(_advisory(), _match(status=status))
        assert "confidence" in result
        assert 0.0 <= result["confidence"] <= 1.0


def test_evaluate_always_has_reason_key():
    for status in ("skipped", "unresolved", "acted"):
        result = evaluate_effect(_advisory(), _match(status=status))
        assert "reason" in result
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0


def test_evaluate_effect_values_restricted():
    allowed = {"positive", "neutral", "negative"}
    for hint in ("positive", "neutral", "negative", ""):
        result = evaluate_effect(_advisory(), _match(effect_hint=hint))
        assert result["effect"] in allowed
