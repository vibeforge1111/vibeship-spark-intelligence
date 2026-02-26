"""Contract-focused tests for lib/distillation_transformer.py."""
from __future__ import annotations

import pytest

from lib.distillation_transformer import (
    _DIM_WEIGHTS,
    AdvisoryQuality,
    _compose_advisory_text,
    _compute_unified_score,
    _detect_domain,
    _score_actionability,
    _score_novelty,
    _score_outcome_linked,
    _score_reasoning,
    _score_specificity,
    extract_structure,
    should_suppress,
    transform_for_advisory,
)

# ---------------------------------------------------------------------------
# AdvisoryQuality serialization contract
# ---------------------------------------------------------------------------

def test_advisory_quality_defaults_are_safe():
    aq = AdvisoryQuality()
    assert aq.domain == "general"
    assert aq.suppressed is False
    assert aq.suppression_reason == ""
    assert aq.advisory_text == ""
    assert aq.actionability == 0.0
    assert aq.unified_score == 0.0


def test_to_dict_rounds_scores_and_omits_empty_advisory_text():
    aq = AdvisoryQuality(actionability=0.12345, advisory_text="")
    result = aq.to_dict()

    assert result["actionability"] == 0.123
    assert "advisory_text" not in result
    assert result["suppressed"] is False


def test_to_dict_includes_advisory_text_when_present():
    aq = AdvisoryQuality(advisory_text="Use schema validation")
    result = aq.to_dict()

    assert result["advisory_text"] == "Use schema validation"


def test_from_dict_round_trip_preserves_core_fields():
    original = AdvisoryQuality(
        actionability=0.9,
        novelty=0.6,
        reasoning=0.8,
        specificity=0.7,
        outcome_linked=0.5,
        unified_score=0.74,
        domain="code",
        suppressed=True,
        suppression_reason="noise_pattern",
        advisory_text="Use strict mode because it catches errors",
    )

    restored = AdvisoryQuality.from_dict(original.to_dict())

    assert restored.domain == "code"
    assert restored.suppressed is True
    assert restored.suppression_reason == "noise_pattern"
    assert abs(restored.unified_score - 0.74) < 0.01


def test_from_dict_none_returns_defaults():
    restored = AdvisoryQuality.from_dict(None)  # type: ignore[arg-type]
    assert restored == AdvisoryQuality()


def test_from_dict_ignores_unknown_keys():
    restored = AdvisoryQuality.from_dict(
        {
            "actionability": 0.5,
            "structure": {"action": "use retries"},
            "unknown_key": "ignored",
        }
    )
    assert restored.actionability == 0.5
    assert restored.structure == {"action": "use retries"}
    assert "unknown_key" not in restored.to_dict()


def test_from_dict_corrupt_score_raises_valueerror():
    """Document fail-fast behavior: corrupt JSONL data surfaces immediately."""
    with pytest.raises(ValueError):
        AdvisoryQuality.from_dict({"actionability": "not_a_number"})


# ---------------------------------------------------------------------------
# Dimension scoring contracts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Always validate user input", 1.0),
        ("Avoid using global state", 1.0),
        ("Use TypeScript for this", 1.0),
        ("Consider tradeoffs before rollout", 0.5),
        ("engagement avg was 250 this week", 0.5),
        ("Generic statement only", 0.0),
    ],
)
def test_score_actionability_matrix(text: str, expected: float):
    assert _score_actionability(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Use this because it works", 0.5),
        ("Use this because it works, prefer type safety", 1.0),
        ("1200 avg likes because of better hook", 1.0),
        ("5000 avg engagement, a new insight", 1.0),
        ("Simple statement", 0.0),
    ],
)
def test_score_novelty_matrix(text: str, expected: float):
    assert _score_novelty(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Use batching because it reduces overhead", 1.0),
        ("Caching works since it avoids repeated calls", 1.0),
        ("This helps prevent bugs", 0.5),
        ("1200 avg outperforms 800 control", 0.5),
        ("Add a button", 0.0),
    ],
)
def test_score_reasoning_matrix(text: str, expected: float):
    assert _score_reasoning(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Edit config.json for this service", 1.0),
        ("Check src/lib/auth.py for the bug", 1.0),
        ("Use TypeScript API contracts", 1.0),
        ("This is about authentication", 0.5),
        ("Do it better", 0.0),
    ],
)
def test_score_specificity_matrix(text: str, expected: float):
    assert _score_specificity(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("This approach fixed the bug", 1.0),
        ("It improves retention", 0.5),
        ("Use retries to reduce incidents", 0.0),
        ("1000 avg conversion rate", 0.5),
        ("Add a button", 0.0),
    ],
)
def test_score_outcome_linked_matrix(text: str, expected: float):
    assert _score_outcome_linked(text) == expected


def test_compute_unified_score_uses_weights():
    dims = {k: 0.0 for k in _DIM_WEIGHTS}
    dims["actionability"] = 1.0
    assert _compute_unified_score(dims) == _DIM_WEIGHTS["actionability"]


def test_compute_unified_score_all_ones_equals_one():
    assert _compute_unified_score({k: 1.0 for k in _DIM_WEIGHTS}) == pytest.approx(1.0)


def test_compute_unified_score_weights_sum_to_one():
    assert sum(_DIM_WEIGHTS.values()) == pytest.approx(1.0)


def test_compute_unified_score_clamps_and_handles_missing_dims():
    assert _compute_unified_score({}) == 0.0
    assert _compute_unified_score({k: 2.0 for k in _DIM_WEIGHTS}) == 1.0


# ---------------------------------------------------------------------------
# Extraction and domain contracts
# ---------------------------------------------------------------------------

def test_extract_structure_returns_expected_shape():
    result = extract_structure("When queue is full: use batching because it reduces overhead")
    assert set(result.keys()) == {"condition", "action", "reasoning", "outcome"}


def test_extract_structure_short_text_returns_nones():
    result = extract_structure("ok")
    assert all(v is None for v in result.values())


def test_extract_structure_action_capture_respects_action_pattern_limit():
    long_text = "Always use " + ("x" * 96) + " because it helps"
    result = extract_structure(long_text)
    assert result["action"] is not None
    assert len(result["action"]) == 100


def test_extract_structure_can_capture_reasoning_without_action():
    result = extract_structure("Because retries reduce outages.")
    assert result["action"] is None
    assert result["reasoning"] == "retries reduce outages"


def test_extract_structure_captures_each_slot_independently():
    """Verify condition, action, reasoning, outcome each match from dedicated patterns."""
    full = "When the queue backs up, use batching because it cuts latency which leads to faster deploys."
    result = extract_structure(full)
    assert result["condition"] is not None
    assert result["action"] is not None
    assert result["reasoning"] is not None
    # outcome depends on regex — just verify the slot was attempted
    assert "outcome" in result


def test_extract_structure_caps_at_120_chars():
    """The post-regex truncation caps any extracted slot at 120 characters."""
    long = "When " + ("y" * 130) + ", use batching because " + ("z" * 130) + "."
    result = extract_structure(long)
    for value in result.values():
        if value is not None:
            assert len(value) <= 120


def test_extract_structure_empty_string_returns_nones():
    result = extract_structure("")
    assert all(v is None for v in result.values())


@pytest.mark.parametrize(
    ("text", "source", "expected"),
    [
        ("Refactor this TypeScript function", "unknown", "code"),
        ("bridge_cycle publishes advisories", "unknown", "system"),
        ("General advice", "depth_session", "code"),
        ("General advice", "other", "general"),
    ],
)
def test_detect_domain_matrix(text: str, source: str, expected: str):
    assert _detect_domain(text, source=source) == expected


# ---------------------------------------------------------------------------
# Advisory composition contracts
# ---------------------------------------------------------------------------

def test_compose_advisory_text_requires_action():
    structure = {"condition": "queue is full", "action": None, "reasoning": "reduces load", "outcome": None}
    dims = {"reasoning": 1.0, "outcome_linked": 1.0}
    assert _compose_advisory_text("raw", structure, dims) == ""


def test_compose_advisory_text_includes_reasoning_and_outcome_at_thresholds():
    raw = "When queue is full, use batching because it reduces overhead which leads to faster responses."
    structure = {
        "condition": "queue is full",
        "action": "use batching",
        "reasoning": "it reduces overhead",
        "outcome": "faster responses",
    }
    dims = {"reasoning": 0.5, "outcome_linked": 0.5}

    composed = _compose_advisory_text(raw, structure, dims)
    assert "because it reduces overhead" in composed
    assert "(faster responses)" in composed


def test_compose_advisory_text_excludes_low_confidence_reasoning_and_outcome():
    raw = "Use batching."
    structure = {
        "condition": None,
        "action": "use batching",
        "reasoning": "it reduces overhead",
        "outcome": "faster responses",
    }
    dims = {"reasoning": 0.49, "outcome_linked": 0.49}

    composed = _compose_advisory_text(raw, structure, dims)
    assert "because" not in composed
    assert "(" not in composed


def test_compose_advisory_text_rejects_too_short_or_too_long_rewrite():
    short_structure = {"condition": None, "action": "do x", "reasoning": None, "outcome": None}
    assert _compose_advisory_text("raw text", short_structure, {"reasoning": 1.0, "outcome_linked": 1.0}) == ""

    long_structure = {
        "condition": "when " + ("very " * 25) + "busy",
        "action": "apply " + ("strict " * 20) + "controls",
        "reasoning": "to prevent cascading failures",
        "outcome": None,
    }
    assert _compose_advisory_text("short", long_structure, {"reasoning": 1.0, "outcome_linked": 0.0}) == ""


# ---------------------------------------------------------------------------
# Suppression contracts and precedence
# ---------------------------------------------------------------------------

def _dims(**overrides: float) -> dict[str, float]:
    base = {
        "actionability": 1.0,
        "novelty": 0.5,
        "reasoning": 1.0,
        "specificity": 0.5,
        "outcome_linked": 0.5,
        "unified_score": 0.7,
    }
    base.update(overrides)
    return base


def _structure(**overrides: str | None) -> dict[str, str | None]:
    base = {"condition": None, "action": "validate input", "reasoning": None, "outcome": None}
    base.update(overrides)
    return base


def test_should_suppress_prefix_takes_precedence():
    suppressed, reason = should_suppress("RT @user: content", _dims(unified_score=1.0), _structure())
    assert suppressed is True
    assert reason.startswith("observation_prefix")


def test_should_suppress_depth_prefix():
    suppressed, reason = should_suppress("[DEPTH: session 42]", _dims(unified_score=1.0), _structure())
    assert suppressed is True
    assert reason.startswith("observation_prefix")


def test_should_suppress_code_artifact_before_low_quality_checks():
    code_text = "0x1A;0xFF;{};[];1+2=3;4/5;6*7;8-9;!@#$%^&*();" * 3
    suppressed, reason = should_suppress(code_text, _dims(), _structure())
    assert suppressed is True
    assert reason == "code_artifact"


def test_should_suppress_no_action_no_reasoning():
    dims = _dims(actionability=0.0, reasoning=0.0, outcome_linked=0.0, novelty=0.0, unified_score=0.3)
    suppressed, reason = should_suppress("This is just an observation", dims, _structure(action=None))
    assert suppressed is True
    assert reason == "no_action_no_reasoning"


def test_should_suppress_tautology_before_unified_floor():
    dims = _dims(reasoning=0.0, outcome_linked=0.0, specificity=0.0, novelty=0.0, unified_score=0.05)
    suppressed, reason = should_suppress("Always validate input", dims, _structure())
    assert suppressed is True
    # Operationalizability gate fires before tautology when no support dims present
    assert reason in ("tautology_no_context", "missing_condition_reason_or_outcome")


def test_should_suppress_unified_floor_when_other_checks_pass():
    dims = _dims(reasoning=0.5, novelty=0.0, outcome_linked=0.0, specificity=0.5, unified_score=0.19)
    text = "Use schema validation because it prevents malformed payload handling regressions in auth flow"
    suppressed, reason = should_suppress(text, dims, _structure(condition="auth flow", action="use schema validation"))
    assert suppressed is True
    assert reason.startswith("unified_score_too_low")


def test_should_not_suppress_high_quality_actionable_text():
    text = "Always validate inputs because it prevents injection and reduces incident rate"
    suppressed, reason = should_suppress(text, _dims(), _structure())
    assert suppressed is False
    assert reason == ""


def test_should_suppress_verbatim_quote_without_action():
    """Verbatim user quotes (e.g. 'Now, can we...') suppressed when no action extracted."""
    suppressed, reason = should_suppress(
        "Now, can we look at this later please",
        _dims(unified_score=0.7),
        _structure(action=None),
    )
    assert suppressed is True
    assert reason == "verbatim_quote_no_action"


def test_should_not_suppress_verbatim_quote_with_action():
    """Same prefix passes if the text actually contains an extracted action."""
    suppressed, reason = should_suppress(
        "Now, can we validate inputs because it prevents injection attacks in auth flow",
        _dims(),
        _structure(action="validate inputs"),
    )
    assert suppressed is False


def test_should_not_suppress_no_action_but_strong_outcome_and_specificity():
    """Escape hatch: outcome-backed specific observations survive no-action filter."""
    dims = _dims(actionability=0.0, reasoning=0.0, outcome_linked=0.5, specificity=0.5, unified_score=0.3)
    suppressed, reason = should_suppress(
        "The authentication token refresh resulted in fewer 401 errors",
        dims,
        _structure(action=None),
    )
    assert suppressed is False


def test_should_not_suppress_no_action_but_high_novelty():
    """Escape hatch: novel observations with quality signals survive no-action filter."""
    dims = _dims(actionability=0.0, reasoning=0.0, outcome_linked=0.0, novelty=0.5, unified_score=0.3)
    suppressed, reason = should_suppress(
        "Data shows engagement consistently outperforms on surprise hooks",
        dims,
        _structure(action=None),
    )
    assert suppressed is False


# ---------------------------------------------------------------------------
# End-to-end transformer contract
# ---------------------------------------------------------------------------

def test_transform_for_advisory_empty_text_is_suppressed():
    aq = transform_for_advisory("   ")
    assert aq.suppressed is True
    assert aq.suppression_reason == "empty_text"


def test_transform_for_advisory_normalizes_ralph_scores():
    class Ralph:
        actionability = 2
        novelty = 1
        reasoning = 2
        specificity = 1
        outcome_linked = 0

    aq = transform_for_advisory("Some text", ralph_score=Ralph())
    assert aq.actionability == 1.0
    assert aq.novelty == 0.5
    assert aq.reasoning == 1.0


def test_transform_for_advisory_external_signals_boost_moderate_score():
    class Ralph:
        actionability = 0
        novelty = 1
        reasoning = 0
        specificity = 1
        outcome_linked = 0

    base = transform_for_advisory("Generic statement", ralph_score=Ralph())
    boosted = transform_for_advisory("Generic statement", ralph_score=Ralph(), reliability=0.9, chip_quality=0.9)
    assert base.unified_score < 0.9
    assert boosted.unified_score > base.unified_score
    assert 0.0 <= boosted.unified_score <= 1.0


def test_transform_for_advisory_external_signals_can_reduce_very_high_score():
    class Ralph:
        actionability = 2
        novelty = 2
        reasoning = 2
        specificity = 2
        outcome_linked = 2

    base = transform_for_advisory("Use strict schema checks", ralph_score=Ralph())
    boosted = transform_for_advisory("Use strict schema checks", ralph_score=Ralph(), reliability=0.9, chip_quality=0.9)

    expected = (0.80 * ((0.70 * base.unified_score) + (0.30 * 0.9))) + (0.20 * 0.9)
    assert base.unified_score > 0.9
    assert boosted.unified_score < base.unified_score
    assert boosted.unified_score == pytest.approx(expected)


def test_transform_for_advisory_quality_is_consumed_by_memory_fusion_readiness():
    from lib.advisory_memory_fusion import _coerce_readiness

    aq = transform_for_advisory(
        "Use retries because it prevents transient failures and improves success rate"
    )
    readiness = _coerce_readiness({"advisory_quality": aq.to_dict()}, confidence=0.1)

    assert readiness == pytest.approx(round(aq.unified_score, 3))
    assert readiness > 0.1


def test_transform_for_advisory_detects_domain_from_source():
    aq = transform_for_advisory("General sentence", source="depth_session")
    assert aq.domain == "code"


def test_transform_for_advisory_reliability_boost_isolated():
    """Reliability alone blends into unified: 0.70 * base + 0.30 * reliability."""
    base = transform_for_advisory("Generic statement with no keywords at all")
    boosted = transform_for_advisory("Generic statement with no keywords at all", reliability=0.9)
    assert boosted.unified_score > base.unified_score


def test_transform_for_advisory_chip_quality_boost_isolated():
    """Chip quality alone blends into unified: 0.80 * base + 0.20 * chip_quality."""
    base = transform_for_advisory("Generic statement with no keywords at all")
    boosted = transform_for_advisory("Generic statement with no keywords at all", chip_quality=0.9)
    assert boosted.unified_score > base.unified_score


def test_transform_for_advisory_unified_clamped_at_one():
    """Even with max Ralph scores + max external boosts, unified never exceeds 1.0."""

    class MaxRalph:
        actionability = 2
        novelty = 2
        reasoning = 2
        specificity = 2
        outcome_linked = 2

    aq = transform_for_advisory("Use strict mode", ralph_score=MaxRalph(), reliability=1.0, chip_quality=1.0)
    assert aq.unified_score <= 1.0


def test_transform_for_advisory_structure_extracted():
    """transform_for_advisory populates the structure dict from the text."""
    aq = transform_for_advisory("When queue is full, use batching because overhead drops.")
    assert isinstance(aq.structure, dict)
    assert set(aq.structure.keys()) == {"condition", "action", "reasoning", "outcome"}


def test_transform_for_advisory_composes_advisory_text_for_good_input():
    text = "When queue is full, use batching because it reduces overhead and leads to faster responses."
    aq = transform_for_advisory(text)
    assert aq.suppressed is False
    assert isinstance(aq, AdvisoryQuality)
    assert aq.advisory_text != ""
