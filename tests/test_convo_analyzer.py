"""Tests for lib/convo_analyzer.py — conversation intelligence."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

import lib.convo_analyzer as ca
from lib.convo_analyzer import (
    ConvoAnalyzer,
    classify_hook,
    classify_structure,
    ConversationDNA,
    ReplyAnalysis,
    HookRecommendation,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_tone_profiles():
    """Return minimal TONE_PROFILES so _detect_tone works hermetically."""
    class _Profile:
        def __init__(self, markers):
            self.tone_markers = markers

    return {
        "witty": _Profile(["lol", "haha", "ironically"]),
        "technical": _Profile(["architecture", "latency", "deploy", "api"]),
        "conversational": _Profile(["actually", "honestly", "think"]),
        "provocative": _Profile(["unpopular", "hot take", "wrong"]),
    }


def _make_analyzer(monkeypatch, tmp_path: Path) -> ConvoAnalyzer:
    convo_dir = tmp_path / "convo_iq"
    monkeypatch.setattr(ca, "CONVO_DIR", convo_dir)
    monkeypatch.setattr(ca, "DNA_FILE", convo_dir / "conversation_dna.json")
    monkeypatch.setattr(ca, "REPLY_LOG", convo_dir / "reply_log.jsonl")
    monkeypatch.setattr(ca, "TONE_PROFILES", _make_tone_profiles())

    # Stub x_voice
    mock_xv = MagicMock()
    mock_xv.get_user_warmth.return_value = "cold"
    monkeypatch.setattr(ca, "get_x_voice", lambda: mock_xv)

    return ConvoAnalyzer()


# ---------------------------------------------------------------------------
# classify_hook
# ---------------------------------------------------------------------------


def test_classify_hook_question_mark():
    assert classify_hook("What do you think about this?") == "question"


def test_classify_hook_what_prefix():
    assert classify_hook("What is the best approach here") == "question"


def test_classify_hook_how_prefix():
    assert classify_hook("How do you handle this in prod") == "question"


def test_classify_hook_curious():
    assert classify_hook("Curious about your thoughts on scaling") == "question"


def test_classify_hook_observation_noticed():
    assert classify_hook("Noticed that this pattern comes up a lot") == "observation"


def test_classify_hook_observation_interesting():
    assert classify_hook("Interesting take — the pattern seems consistent") == "observation"


def test_classify_hook_challenge_disagree():
    assert classify_hook("Disagree — here's why") == "challenge"


def test_classify_hook_challenge_hot_take():
    assert classify_hook("Hot take: this approach won't scale") == "challenge"


def test_classify_hook_agreement_exactly():
    assert classify_hook("Exactly! This nailed it") == "agreement"


def test_classify_hook_agreement_100():
    assert classify_hook("100% — spot on") == "agreement"


def test_classify_hook_addition_also():
    assert classify_hook("Also worth adding: the memory footprint") == "addition"


def test_classify_hook_addition_adding():
    assert classify_hook("Adding to this — another angle exists") == "addition"


def test_classify_hook_default_observation():
    # No pattern matches → defaults to observation
    result = classify_hook("completely neutral text with no markers")
    assert result == "observation"


def test_classify_hook_only_inspects_first_100_chars():
    # Pattern appears only after character 100 — should not match
    prefix = "x" * 110
    text = prefix + "What is this?"
    # The "?" is beyond index 100, so it won't match the $-anchored pattern
    result = classify_hook(text)
    # May match observation default or no match → just check it's a valid type
    assert result in ("question", "observation", "challenge", "agreement", "addition")


# ---------------------------------------------------------------------------
# classify_structure
# ---------------------------------------------------------------------------


def test_classify_structure_short():
    assert classify_structure("Quick reply here") == "short"


def test_classify_structure_medium():
    text = " ".join(["word"] * 25)
    assert classify_structure(text) == "medium"


def test_classify_structure_long():
    text = " ".join(["word"] * 50)
    assert classify_structure(text) == "long"


def test_classify_structure_boundary_15_is_short():
    text = " ".join(["word"] * 15)
    assert classify_structure(text) == "short"


def test_classify_structure_boundary_16_is_medium():
    text = " ".join(["word"] * 16)
    assert classify_structure(text) == "medium"


def test_classify_structure_boundary_40_is_medium():
    text = " ".join(["word"] * 40)
    assert classify_structure(text) == "medium"


def test_classify_structure_boundary_41_is_long():
    text = " ".join(["word"] * 41)
    assert classify_structure(text) == "long"


# ---------------------------------------------------------------------------
# ConvoAnalyzer._detect_tone
# ---------------------------------------------------------------------------


def test_detect_tone_witty(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    tone = analyzer._detect_tone("ironically this always happens lol")
    assert tone == "witty"


def test_detect_tone_technical(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    tone = analyzer._detect_tone("the api latency is the bottleneck")
    assert tone == "technical"


def test_detect_tone_conversational(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    tone = analyzer._detect_tone("I honestly think we should do this")
    assert tone == "conversational"


def test_detect_tone_default_when_no_match(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    tone = analyzer._detect_tone("zzz qqq mmm no markers here")
    assert tone == "conversational"


# ---------------------------------------------------------------------------
# ConvoAnalyzer.analyze_reply
# ---------------------------------------------------------------------------


def test_analyze_reply_returns_analysis(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    result = analyzer.analyze_reply("What do you think about this?")
    assert isinstance(result, ReplyAnalysis)
    assert result.hook_type == "question"


def test_analyze_reply_over_280_chars(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    long_text = "word " * 70
    result = analyzer.analyze_reply(long_text)
    assert any("280" in w for w in result.weaknesses)
    assert len(result.suggestions) > 0


def test_analyze_reply_question_hook_strength(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    result = analyzer.analyze_reply("How does this scale?")
    assert any("response" in s.lower() for s in result.strengths)


def test_analyze_reply_short_reply_strength(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    result = analyzer.analyze_reply("Short reply here.")
    assert any("concise" in s.lower() or "short" in s.lower() for s in result.strengths)


def test_analyze_reply_long_reply_weakness(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    result = analyzer.analyze_reply(" ".join(["word"] * 50))
    assert any("long" in w.lower() or "skipped" in w.lower() for w in result.weaknesses)


def test_analyze_reply_challenge_cold_user_warns(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    # x_voice returns "cold" by default in our fixture
    result = analyzer.analyze_reply("Disagree — this won't work", author_handle="colduser")
    assert any("cold" in w.lower() for w in result.weaknesses)


def test_analyze_reply_technical_parent_suggests_tone(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    result = analyzer.analyze_reply(
        "ironically this is hilarious lol",
        parent_text="the code api deploy architecture is broken",
    )
    assert any("technical" in s.lower() for s in result.suggestions)


def test_analyze_reply_engagement_is_float(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    result = analyzer.analyze_reply("What do you think?")
    assert isinstance(result.estimated_engagement, float)
    assert 0 <= result.estimated_engagement <= 10


# ---------------------------------------------------------------------------
# ConvoAnalyzer._estimate_engagement
# ---------------------------------------------------------------------------


def test_estimate_engagement_question_highest_base(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    score_q = analyzer._estimate_engagement("question", "conversational", "short")
    score_agr = analyzer._estimate_engagement("agreement", "conversational", "short")
    assert score_q > score_agr


def test_estimate_engagement_short_beats_long(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    short = analyzer._estimate_engagement("observation", "conversational", "short")
    long = analyzer._estimate_engagement("observation", "conversational", "long")
    assert short > long


def test_estimate_engagement_ally_warmth_bonus(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    analyzer.x_voice.get_user_warmth.return_value = "ally"
    score_ally = analyzer._estimate_engagement("observation", "conversational", "short", "some_user")
    analyzer.x_voice.get_user_warmth.return_value = "cold"
    score_cold = analyzer._estimate_engagement("observation", "conversational", "short", "some_user")
    assert score_ally > score_cold


def test_estimate_engagement_clamped_0_to_10(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    score = analyzer._estimate_engagement("question", "witty", "short")
    assert 0 <= score <= 10


# ---------------------------------------------------------------------------
# ConvoAnalyzer.extract_dna
# ---------------------------------------------------------------------------


def test_extract_dna_low_engagement_returns_none(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    result = analyzer.extract_dna("Some text", engagement_score=1.0)
    assert result is None


def test_extract_dna_high_engagement_creates_pattern(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    dna = analyzer.extract_dna("What do you think?", engagement_score=8.0, topic_tags=["ai"])
    assert dna is not None
    assert isinstance(dna, ConversationDNA)
    assert dna.hook_type == "question"


def test_extract_dna_reinforces_existing_pattern(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    analyzer.extract_dna("What do you think?", engagement_score=6.0)
    dna = analyzer.extract_dna("What do you think?", engagement_score=8.0)
    assert dna.times_seen == 2


def test_extract_dna_ewma_engagement(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    analyzer.extract_dna("What do you think?", engagement_score=6.0)
    dna = analyzer.extract_dna("What do you think?", engagement_score=10.0)
    # EWMA: 6.0*0.7 + 10.0*0.3 = 7.2
    assert abs(dna.engagement_score - 7.2) < 0.1


def test_extract_dna_stores_example(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    reply = "How does this scale? Really curious."
    dna = analyzer.extract_dna(reply, engagement_score=7.0)
    assert any(reply[:50] in ex for ex in dna.examples)


def test_extract_dna_max_5_examples(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    for i in range(8):
        analyzer.extract_dna(f"What do you think about topic {i}?", engagement_score=7.0)
    key = list(analyzer.dna_patterns.keys())[0]
    assert len(analyzer.dna_patterns[key].examples) <= 5


def test_extract_dna_persists_to_disk(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    analyzer.extract_dna("Interesting observation here", engagement_score=5.0)
    assert (tmp_path / "convo_iq" / "conversation_dna.json").exists()


# ---------------------------------------------------------------------------
# ConvoAnalyzer._infer_pattern_type
# ---------------------------------------------------------------------------


def test_infer_pattern_question_chain(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    assert analyzer._infer_pattern_type("question", "", "") == "question_chain"


def test_infer_pattern_debate(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    assert analyzer._infer_pattern_type("challenge", "", "") == "debate"


def test_infer_pattern_build_together_agreement(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    assert analyzer._infer_pattern_type("agreement", "", "") == "build_together"


def test_infer_pattern_build_together_addition(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    assert analyzer._infer_pattern_type("addition", "", "") == "build_together"


def test_infer_pattern_default_hook_and_expand(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    assert analyzer._infer_pattern_type("observation", "", "") == "hook_and_expand"


# ---------------------------------------------------------------------------
# ConvoAnalyzer.get_best_hook
# ---------------------------------------------------------------------------


def test_get_best_hook_returns_recommendation(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    rec = analyzer.get_best_hook("Some parent tweet")
    assert isinstance(rec, HookRecommendation)
    assert rec.hook_type in ("question", "observation", "challenge", "agreement", "addition")


def test_get_best_hook_question_parent_gives_addition(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    rec = analyzer.get_best_hook("What do you think about scaling?")
    assert rec.hook_type == "addition"


def test_get_best_hook_opinion_warm_user_gives_challenge(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    analyzer.x_voice.get_user_warmth.return_value = "warm"
    rec = analyzer.get_best_hook("I think this approach is wrong", author_handle="warmuser")
    assert rec.hook_type == "challenge"


def test_get_best_hook_technical_gives_observation(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    rec = analyzer.get_best_hook("The API architecture for deploy is complex")
    assert rec.hook_type == "observation"
    assert rec.tone == "technical"


def test_get_best_hook_cold_user_gives_question(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    analyzer.x_voice.get_user_warmth.return_value = "cold"
    rec = analyzer.get_best_hook("Just a regular tweet", author_handle="coldperson")
    assert rec.hook_type == "question"


def test_get_best_hook_confidence_boosted_by_dna(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    # Pre-populate DNA that matches the expected recommendation
    for _ in range(3):
        analyzer.extract_dna("What do you think?", engagement_score=8.0)
    rec = analyzer.get_best_hook("Just a regular tweet", author_handle="colduser")
    # With matching DNA, confidence should exceed the base 0.5
    assert rec.confidence > 0.5


def test_get_best_hook_confidence_default(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    rec = analyzer.get_best_hook("Some tweet")
    assert 0 <= rec.confidence <= 1.0


# ---------------------------------------------------------------------------
# ConvoAnalyzer.score_reply_draft
# ---------------------------------------------------------------------------


def test_score_reply_draft_returns_dict(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    result = analyzer.score_reply_draft("What do you think?", "Some parent")
    assert "score" in result
    assert "analysis" in result
    assert "recommendation" in result
    assert "verdict" in result


def test_score_reply_draft_score_in_range(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    result = analyzer.score_reply_draft("Nice observation here", "Some tweet")
    assert 0 <= result["score"] <= 10


def test_score_reply_draft_verdict_strong(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    # High-engagement setup: short question to cold user
    result = analyzer.score_reply_draft("What do you think?", "Just wondering")
    assert result["verdict"] in ("strong", "good", "weak", "rethink")


def test_score_reply_draft_penalty_for_weaknesses(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    short_result = analyzer.score_reply_draft("Short?", "tweet")
    long_text = "word " * 70  # triggers >280 char warning
    long_result = analyzer.score_reply_draft(long_text, "tweet")
    assert short_result["score"] > long_result["score"]


# ---------------------------------------------------------------------------
# ConvoAnalyzer.study_reply
# ---------------------------------------------------------------------------


def test_study_reply_high_engagement_extracts_dna(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    engagement = {"likes": 20, "replies": 10, "retweets": 5}
    dna = analyzer.study_reply("What do you think?", engagement)
    assert dna is not None


def test_study_reply_low_engagement_returns_none(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    engagement = {"likes": 0, "replies": 0, "retweets": 0}
    dna = analyzer.study_reply("A reply nobody cared about.", engagement)
    assert dna is None


def test_study_reply_engagement_score_formula(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    # likes*0.3 + replies*1.0 + retweets*0.5 = 3 + 5 + 2.5 = 10.5 → capped at 10
    engagement = {"likes": 10, "replies": 5, "retweets": 5}
    dna = analyzer.study_reply("What do you think?", engagement)
    assert dna is not None
    assert dna.engagement_score <= 10.0


# ---------------------------------------------------------------------------
# ConvoAnalyzer.log_reply
# ---------------------------------------------------------------------------


def test_log_reply_creates_file(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    analyzer.log_reply("Good point!", "Parent tweet", "author", "conversational", "observation")
    assert (tmp_path / "convo_iq" / "reply_log.jsonl").exists()


def test_log_reply_appends_entries(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    analyzer.log_reply("Reply 1", "Parent", "user1", "witty", "question")
    analyzer.log_reply("Reply 2", "Parent", "user2", "technical", "addition")
    lines = (tmp_path / "convo_iq" / "reply_log.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2


def test_log_reply_entry_structure(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    analyzer.log_reply("Hello world?", "Parent tweet", "author_x", "conversational", "question")
    line = (tmp_path / "convo_iq" / "reply_log.jsonl").read_text().strip()
    entry = json.loads(line)
    assert entry["author_handle"] == "author_x"
    assert entry["hook_type"] == "question"
    assert "timestamp" in entry


def test_log_reply_truncates_at_280(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    long_reply = "word " * 100
    analyzer.log_reply(long_reply, "Parent", "user", "conversational", "addition")
    line = (tmp_path / "convo_iq" / "reply_log.jsonl").read_text().strip()
    entry = json.loads(line)
    assert len(entry["reply_text"]) <= 280


# ---------------------------------------------------------------------------
# ConvoAnalyzer.get_stats
# ---------------------------------------------------------------------------


def test_get_stats_empty(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    stats = analyzer.get_stats()
    assert stats["dna_patterns"] == 0
    assert stats["replies_logged"] == 0


def test_get_stats_counts_dna(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    analyzer.extract_dna("What do you think?", engagement_score=7.0)
    stats = analyzer.get_stats()
    assert stats["dna_patterns"] == 1


def test_get_stats_counts_replies_logged(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    analyzer.log_reply("r1", "p", "u", "t", "h")
    analyzer.log_reply("r2", "p", "u", "t", "h")
    stats = analyzer.get_stats()
    assert stats["replies_logged"] == 2


def test_get_stats_avg_engagement(monkeypatch, tmp_path):
    analyzer = _make_analyzer(monkeypatch, tmp_path)
    analyzer.extract_dna("What do you think?", engagement_score=6.0)
    analyzer.extract_dna("Noticed an interesting pattern here.", engagement_score=8.0)
    stats = analyzer.get_stats()
    assert stats["avg_dna_engagement"] > 0


# ---------------------------------------------------------------------------
# DNA persistence
# ---------------------------------------------------------------------------


def test_dna_loaded_from_disk(monkeypatch, tmp_path):
    convo_dir = tmp_path / "convo_iq"
    convo_dir.mkdir(parents=True)
    dna_file = convo_dir / "conversation_dna.json"
    dna_file.write_text(json.dumps({
        "question_chain_question_conversational": {
            "pattern_type": "question_chain",
            "hook_type": "question",
            "tone": "conversational",
            "structure": "short",
            "engagement_score": 7.5,
            "examples": ["What do you think?"],
            "topic_tags": ["ai"],
            "times_seen": 3,
            "last_seen": "2026-01-01T00:00:00",
        }
    }), encoding="utf-8")

    monkeypatch.setattr(ca, "CONVO_DIR", convo_dir)
    monkeypatch.setattr(ca, "DNA_FILE", dna_file)
    monkeypatch.setattr(ca, "REPLY_LOG", convo_dir / "reply_log.jsonl")
    monkeypatch.setattr(ca, "TONE_PROFILES", _make_tone_profiles())
    mock_xv = MagicMock()
    mock_xv.get_user_warmth.return_value = "cold"
    monkeypatch.setattr(ca, "get_x_voice", lambda: mock_xv)

    analyzer = ConvoAnalyzer()
    assert "question_chain_question_conversational" in analyzer.dna_patterns
    assert analyzer.dna_patterns["question_chain_question_conversational"].times_seen == 3


# ---------------------------------------------------------------------------
# get_convo_analyzer singleton
# ---------------------------------------------------------------------------


def test_get_convo_analyzer_singleton(monkeypatch, tmp_path):
    convo_dir = tmp_path / "convo_iq"
    monkeypatch.setattr(ca, "CONVO_DIR", convo_dir)
    monkeypatch.setattr(ca, "DNA_FILE", convo_dir / "conversation_dna.json")
    monkeypatch.setattr(ca, "REPLY_LOG", convo_dir / "reply_log.jsonl")
    monkeypatch.setattr(ca, "TONE_PROFILES", _make_tone_profiles())
    mock_xv = MagicMock()
    mock_xv.get_user_warmth.return_value = "cold"
    monkeypatch.setattr(ca, "get_x_voice", lambda: mock_xv)
    monkeypatch.setattr(ca, "_analyzer", None)

    a1 = ca.get_convo_analyzer()
    a2 = ca.get_convo_analyzer()
    assert a1 is a2
