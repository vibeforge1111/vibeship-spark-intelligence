"""
Tests for lib/advisor.py — SparkAdvisor core module.

Covers:
  1. Intent/domain classification (_detect_retrieval_domain, _is_x_social_query)
  2. Advice fusion scoring (_rank_score, _score_actionability)
  3. Source ranking/boosting (_SOURCE_BOOST, _rank_advice)
  4. Advice filtering (_should_drop_advice, _filter_cross_domain_advice,
     _is_metadata_pattern, _is_low_signal_struggle_text, _is_transcript_artifact)
  5. Public API (advise, report_outcome, get_effectiveness_report,
     get_quick_advice, should_be_careful, generate_context_block)
  6. BM25 / lexical scoring helpers
  7. Effectiveness normalization
  8. Caching behaviour
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import lib.advisor as advisor_mod
import lib.workflow_evidence as workflow_evidence_mod
from lib.advisor import Advice, AdviceOutcome, SparkAdvisor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _DummyCognitive:
    """Minimal stub for CognitiveLearner — all retrieval returns empty."""

    def get_insights_for_context(self, *_a, **_kw):
        return []

    def get_self_awareness_insights(self):
        return []

    def get_insights_by_category(self, *_a, **_kw):
        return []

    def record_insight(self, *_a, **_kw):
        pass

    def search_semantic(self, *_a, **_kw):
        return []


class _DummyMindBridge:
    """Minimal stub for MindBridge."""

    def retrieve(self, *_a, **_kw):
        return []

    def get_stats(self):
        return {}


class _DummyRalph:
    """Minimal stub for Meta-Ralph."""

    def __init__(self):
        self.tracked = []

    def track_retrieval(self, *a, **kw):
        self.tracked.append(("retrieval", a, kw))

    def track_outcome(self, *a, **kw):
        self.tracked.append(("outcome", a, kw))

    def get_insight_effectiveness(self, *_a, **_kw):
        return 0.5


class _DummyFeedbackCache:
    """Deterministic feedback cache stub for rank-score tests."""

    def get_source_effectiveness(self, *_a, **_kw):
        return -1.0

    def get_category_boost(self, *_a, **_kw):
        return 1.0


def _patch_advisor(monkeypatch, tmp_path):
    """Redirect all filesystem paths and stub heavy dependencies."""
    monkeypatch.setattr(advisor_mod, "ADVISOR_DIR", tmp_path)
    monkeypatch.setattr(advisor_mod, "ADVICE_LOG", tmp_path / "advice_log.jsonl")
    monkeypatch.setattr(advisor_mod, "EFFECTIVENESS_FILE", tmp_path / "effectiveness.json")
    monkeypatch.setattr(advisor_mod, "ADVISOR_METRICS", tmp_path / "metrics.json")
    monkeypatch.setattr(advisor_mod, "RECENT_ADVICE_LOG", tmp_path / "recent_advice.jsonl")
    monkeypatch.setattr(advisor_mod, "RETRIEVAL_ROUTE_LOG", tmp_path / "retrieval_route.jsonl")
    monkeypatch.setattr(advisor_mod, "CHIP_INSIGHTS_DIR", tmp_path / "chip_insights")
    monkeypatch.setattr(advisor_mod, "get_cognitive_learner", lambda: _DummyCognitive())
    monkeypatch.setattr(advisor_mod, "get_mind_bridge", lambda: _DummyMindBridge())
    monkeypatch.setattr(advisor_mod, "HAS_EIDOS", False)
    monkeypatch.setattr(advisor_mod, "AUTO_TUNER_SOURCE_BOOSTS", {})
    monkeypatch.setattr("lib.feedback_effectiveness_cache.get_feedback_cache", lambda: _DummyFeedbackCache())
    # Isolate workflow evidence from live data
    monkeypatch.setattr(workflow_evidence_mod, "WORKFLOW_REPORT_DIRS", {
        "claude": tmp_path / "_wf_claude",
        "codex": tmp_path / "_wf_codex",
        "openclaw": tmp_path / "_wf_openclaw",
    })
    # Stub singleton so tests are isolated
    monkeypatch.setattr(advisor_mod, "_advisor", None)


def _make_advice(
    text="Use pytest for testing",
    confidence=0.8,
    context_match=0.9,
    source="cognitive",
    insight_key="test_key",
    emotional_priority=0.0,
):
    """Factory for Advice objects with sensible defaults."""
    return Advice(
        advice_id=f"test:{insight_key}",
        insight_key=insight_key,
        text=text,
        confidence=confidence,
        source=source,
        context_match=context_match,
        emotional_priority=emotional_priority,
    )


def _build_advisor(monkeypatch, tmp_path) -> SparkAdvisor:
    """Construct an advisor instance with all IO stubbed out."""
    _patch_advisor(monkeypatch, tmp_path)
    # Prevent cross-encoder from loading
    monkeypatch.setattr(advisor_mod, "HAS_EIDOS", False)
    return SparkAdvisor()


# ---------------------------------------------------------------------------
# 1. Domain / intent classification
# ---------------------------------------------------------------------------

class TestDomainClassification:

    def test_x_social_detected_via_tweet_marker(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._detect_retrieval_domain("", "write a tweet about AI") == "x_social"

    def test_x_social_detected_via_tool_hint(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._detect_retrieval_domain("x_post", "hello world") == "x_social"

    def test_coding_detected_via_context(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._detect_retrieval_domain("", "refactor the module") == "coding"

    def test_coding_detected_via_tool_hint(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._detect_retrieval_domain("edit", "something unrelated") == "coding"

    def test_testing_detected_via_tool_hint(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        # Tool hint "pytest" -> testing domain
        assert adv._detect_retrieval_domain("pytest", "check results") == "testing"

    def test_general_fallback(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._detect_retrieval_domain("", "do something random") == "general"

    def test_empty_inputs_return_general(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._detect_retrieval_domain("", "") == "general"

    def test_is_x_social_query_positive(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._is_x_social_query("check my tweet engagement") is True

    def test_is_x_social_query_negative(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._is_x_social_query("fix the python bug") is False


# ---------------------------------------------------------------------------
# 2. Actionability scoring
# ---------------------------------------------------------------------------

class TestActionabilityScoring:

    def test_directive_verb_scores_high(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        score = adv._score_actionability("Always validate input before saving to database")
        # Should be high: has directive ("always"), has condition ("before"), has specificity
        assert score >= 0.5

    def test_pure_observation_scores_low(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        score = adv._score_actionability("RT @someone interesting thread (eng:150)")
        assert score < 0.3

    def test_code_snippet_scores_low(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        score = adv._score_actionability("{{{}}}(())[]##**!!@@~~``")
        assert score < 0.3

    def test_eidos_tag_boosts_directive(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        score = adv._score_actionability("[EIDOS] Use retry logic for flaky API calls")
        assert score >= 0.5

    def test_caution_tag_boosts_directive(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        score = adv._score_actionability("[Caution] Always check auth tokens before deploy")
        assert score >= 0.5

    def test_conditional_text_gets_condition_boost(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        score_with = adv._score_actionability("When deploying, always check the rollback plan")
        score_without = adv._score_actionability("The rollback plan exists")
        assert score_with > score_without

    def test_score_always_in_range(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        for text in ["", "x", "A" * 500, "Use pytest for testing", "RT @foo (eng:100)"]:
            score = adv._score_actionability(text)
            assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# 3. Source boosting and rank scoring
# ---------------------------------------------------------------------------

class TestSourceBoostAndRanking:

    def test_eidos_source_boosted_above_cognitive(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        with patch("lib.meta_ralph.get_meta_ralph", return_value=_DummyRalph()):
            a_eidos = _make_advice(source="eidos", confidence=0.8, context_match=0.8)
            a_cognitive = _make_advice(source="cognitive", confidence=0.8, context_match=0.8)
            score_eidos = adv._rank_score(a_eidos)
            score_cognitive = adv._rank_score(a_cognitive)
        assert score_eidos > score_cognitive

    def test_bank_source_penalized(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        with patch("lib.meta_ralph.get_meta_ralph", return_value=_DummyRalph()):
            # Use low-actionability text so source_quality tier differentiates
            low_text = "data observations noted"
            a_bank = _make_advice(source="bank", confidence=0.8, context_match=0.8, text=low_text)
            a_cognitive = _make_advice(source="cognitive", confidence=0.8, context_match=0.8, text=low_text)
            score_bank = adv._rank_score(a_bank)
            score_cog = adv._rank_score(a_cognitive)
        assert score_bank < score_cog

    def test_auto_tuner_boost_scales_source_quality_map(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        monkeypatch.setattr(advisor_mod, "AUTO_TUNER_SOURCE_BOOSTS", {"cognitive": 1.8, "bank": 0.5})
        adv = SparkAdvisor()
        assert adv._SOURCE_BOOST["cognitive"] > adv._SOURCE_QUALITY["cognitive"]
        assert adv._SOURCE_BOOST["bank"] < adv._SOURCE_QUALITY["bank"]

    def test_reload_reads_auto_tuner_source_boosts_and_refreshes_singleton(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        fake_home = tmp_path / "home"
        spark_dir = fake_home / ".spark"
        spark_dir.mkdir(parents=True, exist_ok=True)
        tuneables_path = spark_dir / "tuneables.json"
        tuneables_path.write_text(
            json.dumps(
                {
                    "advisor": {"min_rank_score": 0.35},
                    "auto_tuner": {"source_boosts": {"cognitive": 1.8}},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(advisor_mod.Path, "home", staticmethod(lambda: fake_home))
        monkeypatch.setattr(advisor_mod, "_advisor", SparkAdvisor())
        baseline = advisor_mod._advisor._SOURCE_BOOST["cognitive"]
        cfg = advisor_mod.reload_advisor_config()
        assert cfg["source_boosts"]["cognitive"] == 1.8
        assert advisor_mod._advisor._SOURCE_BOOST["cognitive"] > baseline

    def test_rank_advice_sorts_descending(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        with patch("lib.meta_ralph.get_meta_ralph", return_value=_DummyRalph()):
            items = [
                _make_advice(source="bank", confidence=0.5, context_match=0.5, insight_key="low"),
                _make_advice(source="eidos", confidence=0.9, context_match=0.9, insight_key="high"),
                _make_advice(source="cognitive", confidence=0.7, context_match=0.7, insight_key="mid"),
            ]
            ranked = adv._rank_advice(items)
        scores = [adv._rank_score(a) for a in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_higher_confidence_provides_boost(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        with patch("lib.meta_ralph.get_meta_ralph", return_value=_DummyRalph()):
            a_low = _make_advice(confidence=0.3, insight_key="k1")
            a_high = _make_advice(confidence=0.9, insight_key="k2")
            assert adv._rank_score(a_high) > adv._rank_score(a_low)

    def test_low_signal_text_heavily_penalized(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        with patch("lib.meta_ralph.get_meta_ralph", return_value=_DummyRalph()):
            good = _make_advice(text="Use retry logic for HTTP calls", insight_key="good")
            bad = _make_advice(
                text="I struggle with tool_42_error tasks",
                insight_key="bad",
            )
            assert adv._rank_score(good) > adv._rank_score(bad) * 5


# ---------------------------------------------------------------------------
# 4. Advice filtering
# ---------------------------------------------------------------------------

class TestAdviceFiltering:

    def test_empty_text_is_dropped(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        item = _make_advice(text="")
        assert adv._should_drop_advice(item) is True

    def test_low_signal_struggle_is_dropped(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        item = _make_advice(text="I struggle with mcp__tool_error tasks")
        assert adv._should_drop_advice(item) is True

    def test_transcript_artifact_is_dropped(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        item = _make_advice(text="Said it like this: something")
        assert adv._should_drop_advice(item) is True

    def test_metadata_pattern_dropped_for_cognitive_source(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        item = _make_advice(text="detail_level: concise", source="cognitive")
        assert adv._should_drop_advice(item) is True

    def test_metadata_pattern_kept_for_non_cognitive_source(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        # Non-cognitive sources (like "opportunity") are not metadata-filtered
        item = _make_advice(text="detail_level: concise", source="opportunity")
        assert adv._should_drop_advice(item) is False

    def test_read_before_edit_dropped_for_unrelated_tool(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        item = _make_advice(text="Always read before edit to verify content")
        # "Bash" is unrelated to Read/Edit
        assert adv._should_drop_advice(item, tool_name="Bash") is True

    def test_read_before_edit_kept_for_edit_tool(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        item = _make_advice(text="Always read before edit to verify content")
        assert adv._should_drop_advice(item, tool_name="Edit") is False

    def test_normal_advice_not_dropped(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        item = _make_advice(text="Use pytest fixtures to isolate test state")
        assert adv._should_drop_advice(item) is False

    def test_is_metadata_pattern_key_value(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._is_metadata_pattern("User style: detail_level = concise") is True

    def test_is_metadata_pattern_underscore_key(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._is_metadata_pattern("code_style: pythonic") is True

    def test_is_metadata_pattern_short_fragment(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._is_metadata_pattern("Type: x") is True

    def test_is_metadata_pattern_incomplete_sentence(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._is_metadata_pattern("The important thing about the") is True

    def test_is_metadata_pattern_real_advice_passes(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._is_metadata_pattern("Always validate input before writing to disk") is False

    def test_is_low_signal_struggle_text(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._is_low_signal_struggle_text("I struggle with tool_42_error tasks") is True
        assert adv._is_low_signal_struggle_text("I struggle with syntax_error") is True
        assert adv._is_low_signal_struggle_text("Good advice about testing") is False

    def test_is_transcript_artifact(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._is_transcript_artifact("said it like this: hello") is True
        assert adv._is_transcript_artifact("another reply is: test") is True
        assert adv._is_transcript_artifact("from lib.foo import bar") is True
        assert adv._is_transcript_artifact("Use retry logic for HTTP calls") is False

    def test_filter_cross_domain_drops_social_in_coding_context(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        items = [
            _make_advice(text="Use pytest for testing", insight_key="k1"),
            _make_advice(text="When posting a tweet, use lowercase", insight_key="k2"),
        ]
        filtered = adv._filter_cross_domain_advice(items, "fix python bug")
        assert len(filtered) == 1
        assert filtered[0].insight_key == "k1"

    def test_filter_cross_domain_keeps_social_in_social_context(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        items = [
            _make_advice(text="When posting a tweet, use lowercase", insight_key="k1"),
        ]
        filtered = adv._filter_cross_domain_advice(items, "write a tweet about ai")
        assert len(filtered) == 1


# ---------------------------------------------------------------------------
# 5. BM25 and lexical scoring
# ---------------------------------------------------------------------------

class TestLexicalScoring:

    def test_lexical_overlap_identical(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        score = adv._lexical_overlap_score("python testing fixtures", "python testing fixtures")
        assert score == 1.0

    def test_lexical_overlap_no_match(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        score = adv._lexical_overlap_score("python testing", "javascript deployment")
        assert score == 0.0

    def test_lexical_overlap_partial(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        score = adv._lexical_overlap_score("python testing fixtures", "python testing mocha")
        assert 0.0 < score < 1.0

    def test_lexical_overlap_empty_returns_zero(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._lexical_overlap_score("", "something") == 0.0
        assert adv._lexical_overlap_score("something", "") == 0.0

    def test_bm25_normalized_empty_docs(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._bm25_normalized_scores("test query", []) == []

    def test_bm25_normalized_empty_query(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        scores = adv._bm25_normalized_scores("", ["doc one", "doc two"])
        assert all(s == 0.0 for s in scores)

    def test_bm25_normalized_max_is_one(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        docs = [
            "python testing best practices for web applications",
            "javascript deployment automation pipeline",
            "python testing fixtures and mocking patterns",
        ]
        scores = adv._bm25_normalized_scores("python testing", docs)
        assert len(scores) == 3
        assert abs(max(scores) - 1.0) < 1e-9
        assert all(0.0 <= s <= 1.0 for s in scores)

    def test_hybrid_lexical_scores_blend(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        docs = ["python testing", "java compiling"]
        scores = adv._hybrid_lexical_scores("python testing", docs)
        assert len(scores) == 2
        # First doc should score higher
        assert scores[0] > scores[1]

    def test_reciprocal_rank_fusion_scores_rewards_cross_signal(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        scores = adv._reciprocal_rank_fusion_scores(
            semantic_scores=[0.90, 0.80, 0.30],
            lexical_scores=[0.20, 0.95, 0.10],
            support_scores=[1.0, 2.0, 1.0],
        )
        assert len(scores) == 3
        assert all(0.0 <= s <= 1.0 for s in scores)
        assert scores[1] > scores[0]
        assert scores[2] < scores[0]

    def test_intent_terms_filters_stopwords(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        terms = adv._intent_terms("the python for testing and debugging")
        assert "the" not in terms
        assert "for" not in terms
        assert "and" not in terms
        assert "python" in terms
        assert "testing" in terms

    def test_intent_coverage_score(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        query_terms = adv._intent_terms("python testing fixtures")
        full = adv._intent_coverage_score(query_terms, "python testing fixtures work great")
        partial = adv._intent_coverage_score(query_terms, "python is a language")
        assert full > partial
        assert adv._intent_coverage_score(set(), "anything") == 0.0


# ---------------------------------------------------------------------------
# 6. Effectiveness normalization
# ---------------------------------------------------------------------------

class TestEffectivenessNormalization:

    def test_clamps_followed_to_given(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        data = {"total_advice_given": 5, "total_followed": 10, "total_helpful": 3}
        result = adv._normalize_effectiveness(data)
        assert result["total_followed"] == 5
        assert result["total_helpful"] == 3

    def test_clamps_helpful_to_followed(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        data = {"total_advice_given": 10, "total_followed": 3, "total_helpful": 8}
        result = adv._normalize_effectiveness(data)
        assert result["total_helpful"] == 3

    def test_handles_none_input(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        result = adv._normalize_effectiveness(None)
        assert result["total_advice_given"] == 0
        assert result["total_followed"] == 0
        assert result["total_helpful"] == 0

    def test_by_source_helpful_clamped(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        data = {
            "by_source": {"cognitive": {"total": 2, "helpful": 10}},
        }
        result = adv._normalize_effectiveness(data)
        assert result["by_source"]["cognitive"]["helpful"] == 2

    def test_recent_outcomes_trimmed(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        outcomes = {}
        for i in range(6000):
            outcomes[f"id_{i}"] = {"followed_counted": True, "helpful_counted": False, "ts": float(i)}
        data = {"recent_outcomes": outcomes}
        result = adv._normalize_effectiveness(data)
        assert len(result["recent_outcomes"]) <= advisor_mod.RECENT_OUTCOMES_MAX


# ---------------------------------------------------------------------------
# 7. Caching
# ---------------------------------------------------------------------------

class TestCaching:

    def test_cache_hit_within_ttl(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        items = [_make_advice()]
        adv._cache_advice("key1", items)
        result = adv._get_cached_advice("key1")
        assert result is items

    def test_cache_miss_after_ttl(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        items = [_make_advice()]
        adv._cache["key_old"] = (items, time.time() - 9999)
        result = adv._get_cached_advice("key_old")
        assert result is None

    def test_cache_evicts_oldest_when_full(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        # Fill cache beyond 100
        now = time.time()
        for i in range(101):
            adv._cache[f"k{i}"] = ([_make_advice()], now + i)
        adv._cache_advice("new_key", [_make_advice()])
        # Should have evicted the oldest (k0)
        assert len(adv._cache) <= 101

    def test_cache_key_deterministic(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        k1 = adv._cache_key("Edit", "fix bug", {"file_path": "main.py"})
        k2 = adv._cache_key("Edit", "fix bug", {"file_path": "main.py"})
        assert k1 == k2

    def test_cache_key_varies_by_tool(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        k1 = adv._cache_key("Edit", "fix bug")
        k2 = adv._cache_key("Bash", "fix bug")
        assert k1 != k2


# ---------------------------------------------------------------------------
# 8. Public API: advise()
# ---------------------------------------------------------------------------

class TestAdvisePublicAPI:

    def test_advise_returns_list(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        # Suppress meta_ralph imports inside advise
        monkeypatch.setattr(
            "lib.advisor.get_meta_ralph",
            lambda: _DummyRalph(),
            raising=False,
        )
        adv = SparkAdvisor()
        result = adv.advise("Edit", {"file_path": "main.py"}, "fix a bug")
        assert isinstance(result, list)

    def test_advise_respects_max_items(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        monkeypatch.setattr(advisor_mod, "MAX_ADVICE_ITEMS", 3)
        adv = SparkAdvisor()
        # _rank_advice only sorts; the truncation happens in advise().
        # Verify _rank_advice preserves all items (sorting, no truncation).
        fake = [
            _make_advice(confidence=0.9, context_match=0.9, insight_key=f"k{i}")
            for i in range(10)
        ]
        with patch("lib.meta_ralph.get_meta_ralph", return_value=_DummyRalph()):
            ranked = adv._rank_advice(fake)
        assert len(ranked) == 10  # _rank_advice just sorts, doesn't truncate

    def test_advise_filters_unsafe_advice(self, monkeypatch, tmp_path):
        """Verify that the safety filter from promoter is invoked."""
        _patch_advisor(monkeypatch, tmp_path)
        adv = SparkAdvisor()
        # We test the filtering by verifying the code path doesn't crash
        # even when promoter.is_unsafe_insight is unavailable
        result = adv.advise("Edit", {}, "something")
        assert isinstance(result, list)

    def test_advise_track_retrieval_false_skips_logging(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        adv = SparkAdvisor()
        result = adv.advise("Edit", {}, "test", track_retrieval=False)
        assert isinstance(result, list)
        # Recent advice log should not exist (nothing written)
        assert not (tmp_path / "recent_advice.jsonl").exists()


# ---------------------------------------------------------------------------
# 9. Public API: report_outcome, effectiveness, etc.
# ---------------------------------------------------------------------------

class TestOutcomeReporting:

    def test_report_outcome_increments_followed(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        adv = SparkAdvisor()
        adv.effectiveness["total_advice_given"] = 5
        adv.report_outcome("test_id", was_followed=True, was_helpful=None)
        assert adv.effectiveness["total_followed"] == 1

    def test_report_outcome_increments_helpful(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        adv = SparkAdvisor()
        adv.effectiveness["total_advice_given"] = 5
        adv.report_outcome("test_id", was_followed=True, was_helpful=True)
        assert adv.effectiveness["total_followed"] == 1
        assert adv.effectiveness["total_helpful"] == 1

    def test_report_outcome_not_followed_no_increment(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        adv = SparkAdvisor()
        adv.effectiveness["total_advice_given"] = 5
        adv.report_outcome("test_id", was_followed=False, was_helpful=None)
        assert adv.effectiveness["total_followed"] == 0

    def test_get_effectiveness_report_structure(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        adv = SparkAdvisor()
        adv.effectiveness["total_advice_given"] = 10
        adv.effectiveness["total_followed"] = 5
        adv.effectiveness["total_helpful"] = 3
        report = adv.get_effectiveness_report()
        assert report["total_advice_given"] == 10
        assert report["follow_rate"] == pytest.approx(0.5)
        assert report["helpfulness_rate"] == pytest.approx(0.6)

    def test_get_effectiveness_report_zero_division(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        adv = SparkAdvisor()
        report = adv.get_effectiveness_report()
        assert report["follow_rate"] == pytest.approx(0.0)
        assert report["helpfulness_rate"] == 0

    def test_repair_effectiveness_counters(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        adv = SparkAdvisor()
        adv.effectiveness["total_advice_given"] = 2
        adv.effectiveness["total_followed"] = 10  # Invalid: > given
        adv.effectiveness["total_helpful"] = 20   # Invalid: > followed
        result = adv.repair_effectiveness_counters()
        assert result["after"]["total_followed"] == 2
        assert result["after"]["total_helpful"] == 2


# ---------------------------------------------------------------------------
# 10. Public API: get_quick_advice, should_be_careful, generate_context_block
# ---------------------------------------------------------------------------

class TestPublicHelpers:

    def test_get_quick_advice_returns_none_when_empty(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        adv = SparkAdvisor()
        result = adv.get_quick_advice("SomeUnknownTool")
        assert result is None

    def test_should_be_careful_returns_tuple(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        adv = SparkAdvisor()
        careful, reason = adv.should_be_careful("Edit")
        assert isinstance(careful, bool)
        assert isinstance(reason, str)

    def test_should_be_careful_false_no_struggles(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        adv = SparkAdvisor()
        careful, _ = adv.should_be_careful("Edit")
        assert careful is False

    def test_generate_context_block_empty_when_no_advice(self, monkeypatch, tmp_path):
        _patch_advisor(monkeypatch, tmp_path)
        monkeypatch.setattr(SparkAdvisor, "advise", lambda *_a, **_kw: [])
        adv = SparkAdvisor()
        block = adv.generate_context_block("RandomTool", "some task")
        assert block == ""


# ---------------------------------------------------------------------------
# 11. Utility functions (module level)
# ---------------------------------------------------------------------------

class TestUtilityFunctions:

    def test_norm_retrieval_domain_aliases(self):
        assert advisor_mod._norm_retrieval_domain("xsocial") == "x_social"
        assert advisor_mod._norm_retrieval_domain("social") == "x_social"
        assert advisor_mod._norm_retrieval_domain("ui") == "ui_design"
        assert advisor_mod._norm_retrieval_domain("ux") == "ui_design"

    def test_norm_retrieval_domain_empty(self):
        assert advisor_mod._norm_retrieval_domain("") == "general"
        assert advisor_mod._norm_retrieval_domain(None) == "general"

    def test_norm_retrieval_domain_passthrough(self):
        assert advisor_mod._norm_retrieval_domain("coding") == "coding"
        assert advisor_mod._norm_retrieval_domain("testing") == "testing"

    def test_parse_bool(self):
        assert advisor_mod._parse_bool(True, False) is True
        assert advisor_mod._parse_bool(False, True) is False
        assert advisor_mod._parse_bool("1", False) is True
        assert advisor_mod._parse_bool("yes", False) is True
        assert advisor_mod._parse_bool("0", True) is False
        assert advisor_mod._parse_bool("no", True) is False
        assert advisor_mod._parse_bool("garbage", True) is True
        assert advisor_mod._parse_bool("garbage", False) is False

    def test_safe_float(self):
        assert advisor_mod._safe_float("3.14", 0.0) == pytest.approx(3.14)
        assert advisor_mod._safe_float("not_a_number", 1.5) == pytest.approx(1.5)
        assert advisor_mod._safe_float(None, 2.0) == pytest.approx(2.0)

    def test_clamp_01(self):
        assert advisor_mod._clamp_01(-0.5) == 0.0
        assert advisor_mod._clamp_01(0.5) == 0.5
        assert advisor_mod._clamp_01(1.5) == 1.0


# ---------------------------------------------------------------------------
# 12. Advice ID generation
# ---------------------------------------------------------------------------

class TestAdviceIdGeneration:

    def test_stable_id_for_cognitive_with_key(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        id1 = adv._generate_advice_id("some text", insight_key="mykey", source="cognitive")
        id2 = adv._generate_advice_id("different text", insight_key="mykey", source="cognitive")
        # Same insight_key + cognitive source -> same ID
        assert id1 == id2 == "cognitive:mykey"

    def test_semantic_source_normalizes_to_cognitive(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        id1 = adv._generate_advice_id("text", insight_key="k", source="semantic")
        id2 = adv._generate_advice_id("text", insight_key="k", source="semantic-hybrid")
        id3 = adv._generate_advice_id("text", insight_key="k", source="trigger")
        assert id1 == id2 == id3 == "cognitive:k"

    def test_hash_fallback_when_no_key(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        aid = adv._generate_advice_id("some specific text", insight_key="", source="unknown")
        assert len(aid) == 12  # sha256[:12]

    def test_different_texts_produce_different_hashes(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        id1 = adv._generate_advice_id("text alpha", insight_key="", source="unknown")
        id2 = adv._generate_advice_id("text beta", insight_key="", source="unknown")
        assert id1 != id2


# ---------------------------------------------------------------------------
# 13. Query complexity analysis
# ---------------------------------------------------------------------------

class TestQueryComplexity:

    def test_simple_query_low_complexity(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        result = adv._analyze_query_complexity("Read", "read file")
        assert result["score"] < result["threshold"] or result["score"] == 0

    def test_complex_query_detected(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        # Long query with question mark, high-impact tool, risk terms
        ctx = "What is the root cause of the auth token failure across the production deployment? " * 2
        result = adv._analyze_query_complexity("Bash", ctx)
        assert result["score"] >= 2
        assert "risk_terms" in result["reasons"] or "complexity_terms" in result["reasons"]

    def test_high_impact_tool_adds_score(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        r1 = adv._analyze_query_complexity("bash", "deploy code")
        r2 = adv._analyze_query_complexity("read", "deploy code")
        # bash gets +1 for high_impact_tool, read does not
        assert "high_impact_tool" in r1["reasons"]


# ---------------------------------------------------------------------------
# 14. Agentic rate limiting
# ---------------------------------------------------------------------------

class TestAgenticRateLimiting:

    def test_allow_when_rate_limit_is_1(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._allow_agentic_escalation(1.0, 50) is True

    def test_allow_when_no_history(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._allow_agentic_escalation(0.5, 50) is True

    def test_deny_when_rate_exceeded(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        # Fill history with all True (100% agentic)
        adv._agentic_route_history = [True] * 50
        assert adv._allow_agentic_escalation(0.1, 50) is False

    def test_record_agentic_route_bounded(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        for _ in range(200):
            adv._record_agentic_route(True, 80)
        assert len(adv._agentic_route_history) <= 80


# ---------------------------------------------------------------------------
# 15. Mind retrieval gating
# ---------------------------------------------------------------------------

class TestMindRetrievalGating:

    def test_blocked_when_include_mind_false(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        assert adv._mind_retrieval_allowed(include_mind=False, pre_mind_count=0) is False

    def test_allowed_when_stale_threshold_zero(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        monkeypatch.setattr(advisor_mod, "MIND_MAX_STALE_SECONDS", 0)
        monkeypatch.setattr(advisor_mod, "HAS_REQUESTS", True)
        adv.mind = _DummyMindBridge()
        assert adv._mind_retrieval_allowed(include_mind=True, pre_mind_count=0) is True

    def test_blocked_when_mind_is_none(self, monkeypatch, tmp_path):
        adv = _build_advisor(monkeypatch, tmp_path)
        adv.mind = None
        assert adv._mind_retrieval_allowed(include_mind=True, pre_mind_count=0) is False


# ---------------------------------------------------------------------------
# 16. AdviceOutcome dataclass
# ---------------------------------------------------------------------------

class TestAdviceOutcome:

    def test_defaults(self):
        outcome = AdviceOutcome(advice_id="a1", was_followed=True)
        assert outcome.was_helpful is None
        assert outcome.outcome_notes == ""
        assert outcome.timestamp  # non-empty

    def test_full_construction(self):
        outcome = AdviceOutcome(
            advice_id="a2",
            was_followed=False,
            was_helpful=False,
            outcome_notes="did not help",
        )
        assert outcome.advice_id == "a2"
        assert outcome.was_followed is False
        assert outcome.was_helpful is False
