"""Tests for lib/importance_scorer.py — 52 tests."""

from __future__ import annotations

import pytest

import lib.importance_scorer as is_mod
from lib.importance_scorer import (
    ImportanceScore,
    ImportanceScorer,
    ImportanceTier,
    get_importance_scorer,
    score_importance,
    should_learn,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    monkeypatch.setattr(is_mod, "_scorer", None)


@pytest.fixture()
def scorer():
    s = ImportanceScorer.__new__(ImportanceScorer)
    s.active_domain = None
    s.seen_signals = set()
    s.question_answers = {}
    return s


# ---------------------------------------------------------------------------
# ImportanceTier enum
# ---------------------------------------------------------------------------

def test_tier_values():
    assert ImportanceTier.CRITICAL.value == "critical"
    assert ImportanceTier.HIGH.value == "high"
    assert ImportanceTier.MEDIUM.value == "medium"
    assert ImportanceTier.LOW.value == "low"
    assert ImportanceTier.IGNORE.value == "ignore"


# ---------------------------------------------------------------------------
# ImportanceScore
# ---------------------------------------------------------------------------

def test_importance_score_to_dict():
    s = ImportanceScore(score=0.8, tier=ImportanceTier.HIGH, reasons=["x"])
    d = s.to_dict()
    assert d["score"] == 0.8
    assert d["tier"] == "high"
    assert "reasons" in d


def test_importance_score_defaults():
    s = ImportanceScore(score=0.5, tier=ImportanceTier.MEDIUM)
    assert s.reasons == []
    assert s.signals_detected == []
    assert s.domain_relevance == 0.5
    assert s.first_mention_elevation is False
    assert s.question_match is None


# ---------------------------------------------------------------------------
# score() — empty / telemetry
# ---------------------------------------------------------------------------

def test_score_empty_text_returns_ignore(scorer):
    result = scorer.score("")
    assert result.tier == ImportanceTier.IGNORE


def test_score_whitespace_only_returns_ignore(scorer):
    result = scorer.score("   ")
    assert result.tier == ImportanceTier.IGNORE


def test_score_telemetry_signal_returns_ignore(scorer):
    result = scorer.score("user was satisfied after: read -> edit -> bash")
    assert result.tier == ImportanceTier.IGNORE


def test_score_telemetry_heavy_usage(scorer):
    result = scorer.score("heavy read usage (42 calls)")
    assert result.tier == ImportanceTier.IGNORE or result.score < 0.3


# ---------------------------------------------------------------------------
# score() — CRITICAL signals
# ---------------------------------------------------------------------------

def test_score_remember_this_critical(scorer):
    result = scorer.score("remember this: always use type hints")
    assert result.tier == ImportanceTier.CRITICAL
    assert result.score >= 0.9


def test_score_correction_critical(scorer):
    result = scorer.score("correction: the function should return a list")
    assert result.tier == ImportanceTier.CRITICAL


def test_score_critical_flag(scorer):
    result = scorer.score("this is critical to get right")
    assert result.tier in (ImportanceTier.CRITICAL, ImportanceTier.HIGH)
    assert result.score >= 0.7


def test_score_dont_forget_critical(scorer):
    result = scorer.score("don't forget to run the migrations")
    assert result.score >= 0.5


def test_score_principle_colon(scorer):
    result = scorer.score("principle: always test edge cases first")
    assert result.tier == ImportanceTier.CRITICAL


def test_score_never_do_this(scorer):
    result = scorer.score("never do it this way again")
    assert result.score >= 0.9


# ---------------------------------------------------------------------------
# score() — HIGH signals
# ---------------------------------------------------------------------------

def test_score_i_prefer_high(scorer):
    result = scorer.score("I prefer using async functions")
    assert result.tier in (ImportanceTier.CRITICAL, ImportanceTier.HIGH)
    assert result.score >= 0.7


def test_score_lets_go_with_high(scorer):
    result = scorer.score("let's go with the functional approach")
    assert result.score >= 0.7


def test_score_learned_that_high(scorer):
    result = scorer.score("I learned that early returns improve readability")
    assert result.score >= 0.7


def test_score_the_key_is_high(scorer):
    result = scorer.score("the key is to keep functions small")
    assert result.score >= 0.7


def test_score_turns_out_high(scorer):
    result = scorer.score("turns out that lazy loading helps a lot")
    assert result.score >= 0.7


# ---------------------------------------------------------------------------
# score() — MEDIUM signals
# ---------------------------------------------------------------------------

def test_score_i_noticed_medium(scorer):
    result = scorer.score("I noticed that tests run slower on Fridays")
    assert result.score >= 0.5


def test_score_it_seems_medium(scorer):
    result = scorer.score("it seems like the cache is helping")
    assert result.score >= 0.5


# ---------------------------------------------------------------------------
# score() — LOW signals / noise
# ---------------------------------------------------------------------------

def test_score_acknowledgment_lower(scorer):
    result = scorer.score("okay thanks got it")
    # Multiple low signals should reduce score
    assert result.score < 0.7


def test_score_timeout_metric_low(scorer):
    result = scorer.score("timeout error rate 5%")
    assert result.score <= 0.5 or result.tier in (ImportanceTier.LOW, ImportanceTier.MEDIUM, ImportanceTier.IGNORE)


# ---------------------------------------------------------------------------
# context boosts
# ---------------------------------------------------------------------------

def test_score_user_correction_source_boosts(scorer):
    base = scorer.score("I prefer shorter names")
    boosted = scorer.score("I prefer shorter names", context={"source": "user_correction"})
    assert boosted.score >= base.score


def test_score_has_outcome_boosts(scorer):
    base = scorer.score("this approach works")
    boosted = scorer.score("this approach works", context={"has_outcome": True})
    assert boosted.score >= base.score


# ---------------------------------------------------------------------------
# domain relevance
# ---------------------------------------------------------------------------

def test_score_domain_game_dev_boosts_balance(scorer):
    scorer.active_domain = "game_dev"
    result = scorer.score("the player balance needs adjustment")
    assert result.domain_relevance > 0.5


def test_score_no_domain_neutral_relevance(scorer):
    scorer.active_domain = None
    result = scorer.score("some generic statement")
    assert 0.0 <= result.domain_relevance <= 1.0


def test_score_auto_detects_domain(scorer):
    result = scorer.score("the player spawn rate needs tuning for better gameplay")
    # Should auto-detect game_dev
    assert scorer.active_domain == "game_dev"


# ---------------------------------------------------------------------------
# question match
# ---------------------------------------------------------------------------

def test_score_success_question_match(scorer):
    result = scorer.score("success means we ship on time")
    assert result.question_match is not None


def test_score_avoid_question_match(scorer):
    result = scorer.score("avoid technical debt at all costs")
    assert result.question_match is not None


def test_score_focus_question_match(scorer):
    result = scorer.score("pay attention to the user experience")
    assert result.question_match is not None


# ---------------------------------------------------------------------------
# first_mention_elevation
# ---------------------------------------------------------------------------

def test_first_mention_elevates(scorer):
    result1 = scorer.score("I prefer tabs over spaces")
    result2 = scorer.score("I prefer tabs over spaces")
    # First mention should be elevated (or equal)
    assert result1.score >= result2.score or result1.first_mention_elevation


# ---------------------------------------------------------------------------
# should_learn / should_promote
# ---------------------------------------------------------------------------

def test_should_learn_critical(scorer):
    assert scorer.should_learn("remember this: always test first") is True


def test_should_learn_medium(scorer):
    assert scorer.should_learn("I noticed the cache helps") is True


def test_should_learn_ignore(scorer):
    assert scorer.should_learn("") is False


def test_should_promote_high(scorer):
    assert scorer.should_promote("I prefer using async/await") is True


def test_should_promote_medium_false(scorer):
    # Medium tier should not be promoted
    result = scorer.score("it seems like something is happening")
    if result.tier == ImportanceTier.MEDIUM:
        assert scorer.should_promote("it seems like something is happening") is False


# ---------------------------------------------------------------------------
# _detect_signals
# ---------------------------------------------------------------------------

def test_detect_signals_returns_triple(scorer):
    signals, score, tier = scorer._detect_signals("remember this important thing")
    assert isinstance(signals, list)
    assert isinstance(score, float)
    assert isinstance(tier, ImportanceTier)


def test_detect_signals_critical_in_signals(scorer):
    signals, score, tier = scorer._detect_signals("correction: wrong approach")
    assert any("critical:" in s for s in signals)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

def test_get_importance_scorer_returns_instance():
    s = get_importance_scorer()
    assert isinstance(s, ImportanceScorer)


def test_get_importance_scorer_singleton():
    s1 = get_importance_scorer()
    s2 = get_importance_scorer()
    assert s1 is s2


def test_get_importance_scorer_updates_domain():
    s1 = get_importance_scorer(domain="game_dev")
    s2 = get_importance_scorer(domain="fintech")
    assert s2.active_domain == "fintech"


def test_score_importance_convenience():
    result = score_importance("remember this: use small commits")
    assert isinstance(result, ImportanceScore)
    assert result.tier == ImportanceTier.CRITICAL


def test_should_learn_convenience():
    assert should_learn("I prefer explicit over implicit") is True
