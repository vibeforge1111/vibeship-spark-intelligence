from __future__ import annotations

from lib.noise_classifier import NoiseDecision, classify, summarize_shadow_disagreements


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
