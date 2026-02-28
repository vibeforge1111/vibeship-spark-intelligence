from __future__ import annotations

from lib.meta_alpha_scorer import score


def test_question_prompt_scores_zero_dimensions():
    dims = score("What should we do so that this system runs right?")
    assert dims["actionability"] == 0
    assert dims["novelty"] == 0
    assert dims["reasoning"] == 0
    assert dims["specificity"] == 0
    assert dims["outcome_linked"] == 0
    assert dims["ethics"] == 1


def test_actionable_statement_still_scores():
    dims = score("Validate contracts before changing payload shapes because this prevents regressions.")
    assert dims["actionability"] >= 1
    assert dims["reasoning"] >= 1


def test_low_signal_conversational_directive_scores_zero():
    dims = score("And if there are other things that you think will be helpful, do that too.")
    assert dims["actionability"] == 0
    assert dims["novelty"] == 0
    assert dims["reasoning"] == 0
    assert dims["specificity"] == 0
    assert dims["outcome_linked"] == 0


def test_conversational_but_technical_instruction_still_scores():
    dims = score("Can you enforce schema validation at the API boundary to prevent payload drift?")
    assert dims["actionability"] >= 1
    assert dims["specificity"] >= 1
