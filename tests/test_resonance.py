"""Tests for lib/resonance.py — connection depth evolution / resonance scoring."""
from __future__ import annotations

from typing import Optional

import pytest

from lib.resonance import (
    ResonanceState,
    RESONANCE_CONFIG,
    ResonanceScore,
    ResonanceCalculator,
    _get_next_state,
    _points_to_next,
    calculate_user_resonance,
)


# ---------------------------------------------------------------------------
# ResonanceState enum
# ---------------------------------------------------------------------------

class TestResonanceState:
    def test_all_four_states_exist(self):
        assert ResonanceState.SPARK.value == "spark"
        assert ResonanceState.PULSE.value == "pulse"
        assert ResonanceState.BLAZE.value == "blaze"
        assert ResonanceState.RADIANT.value == "radiant"

    def test_state_iteration(self):
        states = list(ResonanceState)
        assert len(states) == 4

    def test_states_unique(self):
        values = [s.value for s in ResonanceState]
        assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# RESONANCE_CONFIG
# ---------------------------------------------------------------------------

class TestResonanceConfig:
    def test_all_states_in_config(self):
        for state in ResonanceState:
            assert state in RESONANCE_CONFIG

    def test_each_entry_has_required_keys(self):
        for state, cfg in RESONANCE_CONFIG.items():
            assert "icon" in cfg, f"{state} missing icon"
            assert "name" in cfg, f"{state} missing name"
            assert "range" in cfg, f"{state} missing range"
            assert "description" in cfg, f"{state} missing description"
            assert "color" in cfg, f"{state} missing color"

    def test_range_tuples_are_pairs(self):
        for state, cfg in RESONANCE_CONFIG.items():
            rng = cfg["range"]
            assert len(rng) == 2, f"{state} range should be a 2-tuple"
            assert rng[0] < rng[1], f"{state} range start must be < end"

    def test_range_covers_0_to_100(self):
        starts = [cfg["range"][0] for cfg in RESONANCE_CONFIG.values()]
        ends = [cfg["range"][1] for cfg in RESONANCE_CONFIG.values()]
        assert min(starts) == 0
        assert max(ends) == 100

    def test_icons_are_nonempty_strings(self):
        for state, cfg in RESONANCE_CONFIG.items():
            assert isinstance(cfg["icon"], str) and cfg["icon"].strip()

    def test_colors_are_hex_strings(self):
        for state, cfg in RESONANCE_CONFIG.items():
            assert cfg["color"].startswith("#"), f"{state} color not hex"


# ---------------------------------------------------------------------------
# ResonanceCalculator._score_component
# ---------------------------------------------------------------------------

class TestScoreComponent:
    def setup_method(self):
        self.calc = ResonanceCalculator()

    def test_zero_value_gives_zero_score(self):
        assert self.calc._score_component(0, 50, 30) == 0.0

    def test_full_value_gives_full_weight(self):
        assert self.calc._score_component(50, 50, 30) == 30.0

    def test_half_value_gives_half_weight(self):
        assert self.calc._score_component(25, 50, 30) == 15.0

    def test_over_threshold_caps_at_weight(self):
        # 200 > threshold 50 → capped at weight 30
        assert self.calc._score_component(200, 50, 30) == 30.0

    def test_fractional_result(self):
        score = self.calc._score_component(10, 20, 10)
        assert score == 5.0

    def test_weight_one(self):
        score = self.calc._score_component(1, 10, 1)
        assert abs(score - 0.1) < 1e-9


# ---------------------------------------------------------------------------
# ResonanceCalculator.calculate — state boundaries
# ---------------------------------------------------------------------------

class TestCalculate:
    def setup_method(self):
        self.calc = ResonanceCalculator()

    def test_all_zeros_gives_spark_state(self):
        score = self.calc.calculate()
        assert score.state == ResonanceState.SPARK
        assert score.total == 0.0

    def test_all_zeros_all_component_scores_zero(self):
        score = self.calc.calculate()
        assert score.insights_score == 0.0
        assert score.surprises_score == 0.0
        assert score.opinions_score == 0.0
        assert score.growth_score == 0.0
        assert score.interactions_score == 0.0
        assert score.validation_score == 0.0

    def test_full_inputs_gives_radiant_state(self):
        score = self.calc.calculate(
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
        assert score.state == ResonanceState.RADIANT
        assert score.total >= 75.0

    def test_moderate_inputs_pulse_or_blaze(self):
        score = self.calc.calculate(
            insights_count=25,
            surprises_count=10,
            opinions_count=8,
            interactions_count=60,
            validated_count=15,
        )
        assert score.state in (ResonanceState.PULSE, ResonanceState.BLAZE)

    def test_user_insights_count_double(self):
        score_base = self.calc.calculate(insights_count=10)
        score_user = self.calc.calculate(insights_count=10, user_insights_count=10)
        # user_insights adds to effective_insights so score is higher
        assert score_user.insights_score >= score_base.insights_score

    def test_lessons_add_bonus_to_surprises(self):
        score_no_lesson = self.calc.calculate(surprises_count=5)
        score_lesson = self.calc.calculate(surprises_count=5, lessons_count=4)
        assert score_lesson.surprises_score >= score_no_lesson.surprises_score

    def test_strong_opinions_count_double(self):
        score_base = self.calc.calculate(opinions_count=5)
        score_strong = self.calc.calculate(opinions_count=5, strong_opinions_count=5)
        assert score_strong.opinions_score >= score_base.opinions_score

    def test_total_is_sum_of_components(self):
        score = self.calc.calculate(
            insights_count=10,
            surprises_count=5,
            opinions_count=3,
            growth_count=2,
            interactions_count=20,
            validated_count=5,
        )
        component_sum = (
            score.insights_score + score.surprises_score + score.opinions_score
            + score.growth_score + score.interactions_score + score.validation_score
        )
        assert abs(score.total - component_sum) < 1e-9

    def test_total_capped_at_100(self):
        score = self.calc.calculate(
            insights_count=9999,
            user_insights_count=9999,
            surprises_count=9999,
            lessons_count=9999,
            opinions_count=9999,
            strong_opinions_count=9999,
            growth_count=9999,
            interactions_count=9999,
            validated_count=9999,
        )
        assert score.total <= 100.0

    def test_returns_resonance_score_instance(self):
        score = self.calc.calculate()
        assert isinstance(score, ResonanceScore)


# ---------------------------------------------------------------------------
# ResonanceCalculator._get_state — threshold boundaries
# ---------------------------------------------------------------------------

class TestGetState:
    def setup_method(self):
        self.calc = ResonanceCalculator()

    def test_below_25_is_spark(self):
        assert self.calc._get_state(0.0) == ResonanceState.SPARK
        assert self.calc._get_state(24.9) == ResonanceState.SPARK

    def test_exactly_25_is_pulse(self):
        assert self.calc._get_state(25.0) == ResonanceState.PULSE

    def test_between_25_and_50_is_pulse(self):
        assert self.calc._get_state(37.5) == ResonanceState.PULSE
        assert self.calc._get_state(49.9) == ResonanceState.PULSE

    def test_exactly_50_is_blaze(self):
        assert self.calc._get_state(50.0) == ResonanceState.BLAZE

    def test_between_50_and_75_is_blaze(self):
        assert self.calc._get_state(62.5) == ResonanceState.BLAZE
        assert self.calc._get_state(74.9) == ResonanceState.BLAZE

    def test_exactly_75_is_radiant(self):
        assert self.calc._get_state(75.0) == ResonanceState.RADIANT

    def test_100_is_radiant(self):
        assert self.calc._get_state(100.0) == ResonanceState.RADIANT


# ---------------------------------------------------------------------------
# ResonanceScore.to_dict
# ---------------------------------------------------------------------------

class TestResonanceScoreToDict:
    def _make_score(self) -> ResonanceScore:
        return ResonanceCalculator().calculate(
            insights_count=10,
            surprises_count=5,
            interactions_count=20,
        )

    def test_has_all_required_keys(self):
        d = self._make_score().to_dict()
        for key in ("insights_score", "surprises_score", "opinions_score",
                    "growth_score", "interactions_score", "validation_score",
                    "total", "state", "state_config"):
            assert key in d, f"Missing key: {key}"

    def test_state_is_string(self):
        d = self._make_score().to_dict()
        assert isinstance(d["state"], str)

    def test_state_config_is_dict(self):
        d = self._make_score().to_dict()
        assert isinstance(d["state_config"], dict)

    def test_total_rounded_to_one_decimal(self):
        d = self._make_score().to_dict()
        # Check it's a valid float with at most 1 decimal place representation
        total = d["total"]
        assert isinstance(total, float)
        assert total == round(total, 1)

    def test_all_scores_rounded_to_one_decimal(self):
        d = self._make_score().to_dict()
        for key in ("insights_score", "surprises_score", "opinions_score",
                    "growth_score", "interactions_score", "validation_score"):
            v = d[key]
            assert v == round(v, 1), f"{key} not rounded"


# ---------------------------------------------------------------------------
# _get_next_state
# ---------------------------------------------------------------------------

class TestGetNextState:
    def test_spark_next_is_pulse(self):
        nxt = _get_next_state(ResonanceState.SPARK)
        assert nxt is not None
        assert nxt["state"] == "pulse"

    def test_pulse_next_is_blaze(self):
        nxt = _get_next_state(ResonanceState.PULSE)
        assert nxt is not None
        assert nxt["state"] == "blaze"

    def test_blaze_next_is_radiant(self):
        nxt = _get_next_state(ResonanceState.BLAZE)
        assert nxt is not None
        assert nxt["state"] == "radiant"

    def test_radiant_next_is_none(self):
        nxt = _get_next_state(ResonanceState.RADIANT)
        assert nxt is None

    def test_next_state_has_icon_and_name(self):
        nxt = _get_next_state(ResonanceState.SPARK)
        assert "icon" in nxt
        assert "name" in nxt
        assert nxt["name"] == "Pulse"


# ---------------------------------------------------------------------------
# _points_to_next
# ---------------------------------------------------------------------------

class TestPointsToNext:
    # _points_to_next uses the *next* state's threshold, not the current one.
    # SPARK→PULSE threshold = 50, PULSE→BLAZE = 75, BLAZE→RADIANT = 100.

    def test_spark_needs_points_to_pulse_threshold(self):
        pts = _points_to_next(10.0, ResonanceState.SPARK)
        assert pts is not None
        assert abs(pts - 40.0) < 0.01  # 50 - 10 = 40

    def test_pulse_needs_points_to_blaze_threshold(self):
        pts = _points_to_next(30.0, ResonanceState.PULSE)
        assert pts is not None
        assert abs(pts - 45.0) < 0.01  # 75 - 30 = 45

    def test_blaze_needs_points_to_radiant_threshold(self):
        pts = _points_to_next(60.0, ResonanceState.BLAZE)
        assert pts is not None
        assert abs(pts - 40.0) < 0.01  # 100 - 60 = 40

    def test_radiant_returns_none(self):
        pts = _points_to_next(90.0, ResonanceState.RADIANT)
        assert pts is None

    def test_at_pulse_threshold_gives_gap_to_blaze(self):
        # PULSE at 25 → distance to BLAZE threshold (75): 75 - 25 = 50
        pts = _points_to_next(25.0, ResonanceState.PULSE)
        assert pts is not None
        assert abs(pts - 50.0) < 0.01

    def test_result_is_rounded(self):
        pts = _points_to_next(12.3, ResonanceState.SPARK)
        assert pts == round(pts, 1)


# ---------------------------------------------------------------------------
# calculate_user_resonance
# ---------------------------------------------------------------------------

class TestCalculateUserResonance:
    def test_zero_interactions_gives_low_score(self):
        score = calculate_user_resonance("@user", 0, 0, 0, 0)
        assert score == 0.0

    def test_full_inputs_give_100(self):
        score = calculate_user_resonance(
            "@user",
            interaction_count=20,
            they_initiated_count=20,
            successful_tones=5,
            topics_shared=5,
        )
        assert score == 100.0

    def test_interaction_component(self):
        # 10 interactions = 50% of 40-weight = 20 points (others zero)
        score = calculate_user_resonance("@u", interaction_count=10)
        assert abs(score - 20.0) < 0.01

    def test_reciprocity_component(self):
        # 20 interactions, 10 initiated → reciprocity = 0.5 * 25 = 12.5
        score_no_recip = calculate_user_resonance("@u", interaction_count=20)
        score_recip = calculate_user_resonance("@u", interaction_count=20, they_initiated_count=10)
        assert score_recip > score_no_recip

    def test_tone_component(self):
        score_no_tone = calculate_user_resonance("@u", interaction_count=5)
        score_tone = calculate_user_resonance("@u", interaction_count=5, successful_tones=5)
        assert score_tone > score_no_tone

    def test_topic_component(self):
        score_no_topic = calculate_user_resonance("@u", interaction_count=5)
        score_topic = calculate_user_resonance("@u", interaction_count=5, topics_shared=5)
        assert score_topic > score_no_topic

    def test_score_in_0_100_range(self):
        for interactions in (0, 5, 10, 20, 50):
            score = calculate_user_resonance("@u", interaction_count=interactions,
                                             they_initiated_count=interactions,
                                             successful_tones=5, topics_shared=5)
            assert 0.0 <= score <= 100.0

    def test_reciprocity_zero_when_no_interactions(self):
        # interaction_count=0 → guard prevents division by zero
        score = calculate_user_resonance("@u", interaction_count=0, they_initiated_count=5)
        assert score == 0.0

    def test_returns_float(self):
        score = calculate_user_resonance("@handle", interaction_count=3)
        assert isinstance(score, float)

    def test_result_is_rounded_to_one_decimal(self):
        score = calculate_user_resonance("@u", interaction_count=7, they_initiated_count=3)
        assert score == round(score, 1)

    def test_handles_more_initiations_than_interactions(self):
        # they_initiated > interaction_count → reciprocity > 1, should still work
        score = calculate_user_resonance("@u", interaction_count=5, they_initiated_count=10)
        assert score >= 0.0
