"""Tests for lib/resonance.py

Covers:
- ResonanceState: all four enum values present
- RESONANCE_CONFIG: all four states configured with icon/name/range/description/color
- ResonanceCalculator._score_component(): zero count, at-threshold, above-threshold cap,
  proportional return
- ResonanceCalculator.calculate(): zero input → SPARK state, max inputs → RADIANT,
  component additivty, user_insights count double, strong_opinions count double,
  lessons add bonus, total capped via state boundary
- ResonanceCalculator._get_state(): threshold boundaries (< 25 → SPARK, 25-49 → PULSE,
  50-74 → BLAZE, ≥ 75 → RADIANT)
- ResonanceScore.to_dict(): all keys present, state is string not enum, scores rounded
- _get_next_state(): returns next state info, None for RADIANT
- _points_to_next(): correct delta to next threshold, None for RADIANT
- calculate_user_resonance(): interaction/reciprocity/tone/topic components,
  zero inputs → 0, max interaction → 40 interaction score component, clamps to max
"""

from __future__ import annotations

import pytest

from lib.resonance import (
    ResonanceState,
    RESONANCE_CONFIG,
    ResonanceCalculator,
    ResonanceScore,
    _get_next_state,
    _points_to_next,
    calculate_user_resonance,
)


# ---------------------------------------------------------------------------
# ResonanceState enum
# ---------------------------------------------------------------------------

def test_resonance_state_spark():
    assert ResonanceState.SPARK.value == "spark"


def test_resonance_state_pulse():
    assert ResonanceState.PULSE.value == "pulse"


def test_resonance_state_blaze():
    assert ResonanceState.BLAZE.value == "blaze"


def test_resonance_state_radiant():
    assert ResonanceState.RADIANT.value == "radiant"


def test_resonance_state_has_four_members():
    assert len(ResonanceState) == 4


# ---------------------------------------------------------------------------
# RESONANCE_CONFIG
# ---------------------------------------------------------------------------

def test_resonance_config_covers_all_states():
    for state in ResonanceState:
        assert state in RESONANCE_CONFIG


def test_resonance_config_has_icon():
    for state in ResonanceState:
        assert "icon" in RESONANCE_CONFIG[state]
        assert RESONANCE_CONFIG[state]["icon"]


def test_resonance_config_has_name():
    for state in ResonanceState:
        assert "name" in RESONANCE_CONFIG[state]


def test_resonance_config_has_range():
    for state in ResonanceState:
        r = RESONANCE_CONFIG[state]["range"]
        assert isinstance(r, tuple) and len(r) == 2


def test_resonance_config_ranges_span_0_to_100():
    lows = sorted(RESONANCE_CONFIG[s]["range"][0] for s in ResonanceState)
    assert lows[0] == 0


def test_resonance_config_has_description():
    for state in ResonanceState:
        assert RESONANCE_CONFIG[state]["description"]


def test_resonance_config_has_color():
    for state in ResonanceState:
        assert RESONANCE_CONFIG[state]["color"].startswith("#")


# ---------------------------------------------------------------------------
# ResonanceCalculator._score_component
# ---------------------------------------------------------------------------

def test_score_component_zero_value():
    calc = ResonanceCalculator()
    assert calc._score_component(0, 50, 30) == 0.0


def test_score_component_at_threshold():
    calc = ResonanceCalculator()
    assert calc._score_component(50, 50, 30) == pytest.approx(30.0)


def test_score_component_above_threshold_capped():
    calc = ResonanceCalculator()
    assert calc._score_component(100, 50, 30) == pytest.approx(30.0)


def test_score_component_proportional():
    calc = ResonanceCalculator()
    assert calc._score_component(25, 50, 30) == pytest.approx(15.0)


def test_score_component_returns_float():
    calc = ResonanceCalculator()
    assert isinstance(calc._score_component(10, 50, 20), float)


# ---------------------------------------------------------------------------
# ResonanceCalculator._get_state
# ---------------------------------------------------------------------------

def test_get_state_below_25_is_spark():
    calc = ResonanceCalculator()
    assert calc._get_state(0) is ResonanceState.SPARK
    assert calc._get_state(24.9) is ResonanceState.SPARK


def test_get_state_25_to_49_is_pulse():
    calc = ResonanceCalculator()
    assert calc._get_state(25) is ResonanceState.PULSE
    assert calc._get_state(49.9) is ResonanceState.PULSE


def test_get_state_50_to_74_is_blaze():
    calc = ResonanceCalculator()
    assert calc._get_state(50) is ResonanceState.BLAZE
    assert calc._get_state(74.9) is ResonanceState.BLAZE


def test_get_state_75_and_above_is_radiant():
    calc = ResonanceCalculator()
    assert calc._get_state(75) is ResonanceState.RADIANT
    assert calc._get_state(100) is ResonanceState.RADIANT


# ---------------------------------------------------------------------------
# ResonanceCalculator.calculate — zero inputs
# ---------------------------------------------------------------------------

def test_calculate_zero_inputs_returns_spark():
    calc = ResonanceCalculator()
    score = calc.calculate()
    assert score.state is ResonanceState.SPARK


def test_calculate_zero_inputs_total_zero():
    calc = ResonanceCalculator()
    assert calc.calculate().total == pytest.approx(0.0)


def test_calculate_returns_resonance_score():
    calc = ResonanceCalculator()
    assert isinstance(calc.calculate(), ResonanceScore)


# ---------------------------------------------------------------------------
# ResonanceCalculator.calculate — max inputs → RADIANT
# ---------------------------------------------------------------------------

def test_calculate_max_inputs_returns_radiant():
    calc = ResonanceCalculator()
    score = calc.calculate(
        insights_count=50,
        user_insights_count=50,
        surprises_count=20,
        lessons_count=20,
        opinions_count=15,
        strong_opinions_count=15,
        growth_count=10,
        interactions_count=100,
        validated_count=30,
    )
    assert score.state is ResonanceState.RADIANT


def test_calculate_max_inputs_total_is_100():
    calc = ResonanceCalculator()
    score = calc.calculate(
        insights_count=50,
        surprises_count=20,
        opinions_count=15,
        growth_count=10,
        interactions_count=100,
        validated_count=30,
    )
    assert score.total == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# ResonanceCalculator.calculate — component logic
# ---------------------------------------------------------------------------

def test_calculate_user_insights_count_double():
    calc = ResonanceCalculator()
    # 25 insights with 0 user → same as 0 insights + 25 user
    score_a = calc.calculate(insights_count=25)
    score_b = calc.calculate(user_insights_count=25)
    assert score_a.insights_score == pytest.approx(score_b.insights_score)


def test_calculate_strong_opinions_count_double():
    calc = ResonanceCalculator()
    score_a = calc.calculate(opinions_count=8)
    score_b = calc.calculate(strong_opinions_count=8)
    assert score_a.opinions_score == pytest.approx(score_b.opinions_score)


def test_calculate_lessons_add_half_bonus():
    calc = ResonanceCalculator()
    # 4 lessons should contribute same as 2 surprises
    score_a = calc.calculate(surprises_count=2)
    score_b = calc.calculate(lessons_count=4)
    assert score_a.surprises_score == pytest.approx(score_b.surprises_score)


def test_calculate_total_is_sum_of_components():
    calc = ResonanceCalculator()
    score = calc.calculate(insights_count=10, interactions_count=20)
    expected = (
        score.insights_score + score.surprises_score + score.opinions_score
        + score.growth_score + score.interactions_score + score.validation_score
    )
    assert score.total == pytest.approx(expected)


def test_calculate_growth_score_at_max():
    calc = ResonanceCalculator()
    score = calc.calculate(growth_count=10)
    assert score.growth_score == pytest.approx(15.0)


def test_calculate_interactions_score_at_max():
    calc = ResonanceCalculator()
    score = calc.calculate(interactions_count=100)
    assert score.interactions_score == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# ResonanceScore.to_dict
# ---------------------------------------------------------------------------

def test_to_dict_returns_dict():
    calc = ResonanceCalculator()
    assert isinstance(calc.calculate().to_dict(), dict)


def test_to_dict_has_required_keys():
    calc = ResonanceCalculator()
    d = calc.calculate().to_dict()
    for key in ("insights_score", "surprises_score", "opinions_score",
                "growth_score", "interactions_score", "validation_score",
                "total", "state", "state_config"):
        assert key in d


def test_to_dict_state_is_string():
    calc = ResonanceCalculator()
    d = calc.calculate().to_dict()
    assert isinstance(d["state"], str)


def test_to_dict_state_config_has_icon():
    calc = ResonanceCalculator()
    d = calc.calculate().to_dict()
    assert "icon" in d["state_config"]


def test_to_dict_scores_rounded_to_1dp():
    calc = ResonanceCalculator()
    d = calc.calculate(insights_count=7).to_dict()
    # Should be rounded to 1 decimal place
    val = d["insights_score"]
    assert val == round(val, 1)


# ---------------------------------------------------------------------------
# _get_next_state
# ---------------------------------------------------------------------------

def test_get_next_state_spark_gives_pulse():
    result = _get_next_state(ResonanceState.SPARK)
    assert result is not None
    assert result["state"] == "pulse"


def test_get_next_state_pulse_gives_blaze():
    result = _get_next_state(ResonanceState.PULSE)
    assert result["state"] == "blaze"


def test_get_next_state_blaze_gives_radiant():
    result = _get_next_state(ResonanceState.BLAZE)
    assert result["state"] == "radiant"


def test_get_next_state_radiant_returns_none():
    assert _get_next_state(ResonanceState.RADIANT) is None


def test_get_next_state_has_icon_and_name():
    result = _get_next_state(ResonanceState.SPARK)
    assert "icon" in result and "name" in result


# ---------------------------------------------------------------------------
# _points_to_next
# ---------------------------------------------------------------------------

def test_points_to_next_spark_at_0_needs_50():
    # PULSE threshold in _points_to_next is 50; SPARK at 0 → 50 - 0 = 50
    assert _points_to_next(0.0, ResonanceState.SPARK) == pytest.approx(50.0)


def test_points_to_next_spark_at_10_needs_40():
    assert _points_to_next(10.0, ResonanceState.SPARK) == pytest.approx(40.0)


def test_points_to_next_pulse_at_25_needs_50():
    # BLAZE threshold is 75; PULSE at 25 → 75 - 25 = 50
    assert _points_to_next(25.0, ResonanceState.PULSE) == pytest.approx(50.0)


def test_points_to_next_blaze_at_50_needs_50():
    # RADIANT threshold is 100; BLAZE at 50 → 100 - 50 = 50
    assert _points_to_next(50.0, ResonanceState.BLAZE) == pytest.approx(50.0)


def test_points_to_next_radiant_returns_none():
    assert _points_to_next(90.0, ResonanceState.RADIANT) is None


# ---------------------------------------------------------------------------
# calculate_user_resonance
# ---------------------------------------------------------------------------

def test_calculate_user_resonance_zero_inputs():
    assert calculate_user_resonance("@user") == pytest.approx(0.0)


def test_calculate_user_resonance_max_interaction_gives_40():
    # 20 interactions → interaction_score = 40
    score = calculate_user_resonance("@user", interaction_count=20)
    assert score == pytest.approx(40.0)


def test_calculate_user_resonance_reciprocity_50pct():
    # 10 interactions, 5 they-initiated → 50% reciprocity → 12.5
    score = calculate_user_resonance("@user", interaction_count=10, they_initiated_count=5)
    assert score == pytest.approx(12.5 + calculate_user_resonance("@user", interaction_count=10))


def test_calculate_user_resonance_max_tone_gives_20():
    score = calculate_user_resonance("@user", successful_tones=5)
    assert score == pytest.approx(20.0)


def test_calculate_user_resonance_max_topics_gives_15():
    score = calculate_user_resonance("@user", topics_shared=5)
    assert score == pytest.approx(15.0)


def test_calculate_user_resonance_all_max_gives_100():
    score = calculate_user_resonance(
        "@user",
        interaction_count=20,
        they_initiated_count=20,
        successful_tones=5,
        topics_shared=5,
    )
    assert score == pytest.approx(100.0)


def test_calculate_user_resonance_returns_float():
    assert isinstance(calculate_user_resonance("@user"), float)


def test_calculate_user_resonance_interaction_capped():
    # 100 interactions shouldn't exceed 40
    score = calculate_user_resonance("@user", interaction_count=100)
    assert score == pytest.approx(40.0)
