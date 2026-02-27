from __future__ import annotations

from lib.noise_classifier import NoiseDecision, classify, enforce_enabled, summarize_shadow_disagreements


def test_classify_flags_operational_sequences():
    decision = classify("Sequence 'Read -> Edit -> Bash' worked well", context="meta_ralph")
    assert decision.is_noise is True
    assert decision.rule in {"primitive_pattern", "common_noise", "tool_sequence"}


def test_classify_flags_markdown_headers():
    decision = classify("## Session History")
    assert decision == NoiseDecision(is_noise=True, rule="markdown_header")


def test_classify_allows_actionable_learning_text():
    decision = classify(
        "Use contract tests before broad refactors because they catch schema drift early."
    )
    assert decision.is_noise is False
    assert decision.rule == "none"


def test_classify_flags_short_question_fragment():
    decision = classify("What should we do next?")
    assert decision.is_noise is True
    assert decision.rule in {"question_fragment", "conversational_fragment"}


def test_shadow_summary_counts_by_module():
    rows = [
        {"module": "meta_ralph._is_primitive"},
        {"module": "meta_ralph._is_primitive"},
        {"module": "cognitive_learner._is_noise_insight"},
    ]
    summary = summarize_shadow_disagreements(rows)
    assert summary["meta_ralph._is_primitive"] == 2
    assert summary["cognitive_learner._is_noise_insight"] == 1


def test_enforce_enabled_defaults_true(monkeypatch):
    monkeypatch.delenv("SPARK_NOISE_CLASSIFIER_ENFORCE", raising=False)
    monkeypatch.delenv("SPARK_NOISE_CLASSIFIER_ENFORCE_PROMOTION", raising=False)
    monkeypatch.delenv("SPARK_NOISE_CLASSIFIER_ENFORCE_RETRIEVAL", raising=False)
    monkeypatch.delenv("SPARK_NOISE_CLASSIFIER_FORCE_SHADOW", raising=False)
    assert enforce_enabled() is True


def test_enforce_enabled_context_overrides(monkeypatch):
    monkeypatch.setenv("SPARK_NOISE_CLASSIFIER_ENFORCE", "0")
    monkeypatch.setenv("SPARK_NOISE_CLASSIFIER_ENFORCE_PROMOTION", "1")
    monkeypatch.setenv("SPARK_NOISE_CLASSIFIER_ENFORCE_RETRIEVAL", "0")
    assert enforce_enabled(context="promotion") is True
    assert enforce_enabled(context="retrieval") is False
    assert enforce_enabled(context="default") is False


def test_force_shadow_disables_all_enforcement(monkeypatch):
    monkeypatch.setenv("SPARK_NOISE_CLASSIFIER_ENFORCE", "1")
    monkeypatch.setenv("SPARK_NOISE_CLASSIFIER_ENFORCE_PROMOTION", "1")
    monkeypatch.setenv("SPARK_NOISE_CLASSIFIER_ENFORCE_RETRIEVAL", "1")
    monkeypatch.setenv("SPARK_NOISE_CLASSIFIER_FORCE_SHADOW", "1")
    assert enforce_enabled(context="promotion") is False
    assert enforce_enabled(context="retrieval") is False
    assert enforce_enabled() is False
