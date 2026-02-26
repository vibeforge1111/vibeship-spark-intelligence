from types import SimpleNamespace

import lib.advisory_synthesizer as synth


def _advice(text: str, authority: str = "note", confidence: float = 0.8):
    item = SimpleNamespace(text=text, confidence=confidence, reason="", source="cognitive")
    item._authority = authority
    return item


def test_programmatic_synthesis_applies_concise_strategy(monkeypatch):
    monkeypatch.setattr(
        synth,
        "_emotion_decision_hooks",
        lambda: {
            "current_emotion": "supportive_focus",
            "strategy": {
                "response_pace": "slow",
                "verbosity": "concise",
                "tone_shape": "reassuring_and_clear",
                "ask_clarifying_question": True,
            },
            "guardrails": {
                "user_guided": True,
                "no_autonomous_objectives": True,
                "no_manipulative_affect": True,
            },
        },
    )

    text = synth.synthesize_programmatic(
        [
            _advice("[Caution] verify rollback before deploy", authority="warning"),
            _advice("run quick smoke test on critical path"),
            _advice("capture evidence in release log"),
        ]
    )

    assert "**Cautions:**" not in text
    assert "If this doesn't match your intent" in text
    assert "verify rollback before deploy" in text


def test_build_prompt_includes_emotions_v2_strategy(monkeypatch):
    monkeypatch.setattr(
        synth,
        "_emotion_decision_hooks",
        lambda: {
            "current_emotion": "steady",
            "strategy": {
                "response_pace": "measured",
                "verbosity": "structured",
                "tone_shape": "calm_focus",
                "ask_clarifying_question": False,
            },
            "guardrails": {
                "user_guided": True,
                "no_autonomous_objectives": True,
                "no_manipulative_affect": True,
            },
        },
    )

    prompt = synth._build_synthesis_prompt(
        [_advice("validate schema migration before write")],
        phase="implementation",
        user_intent="ship safely",
        tool_name="Edit",
    )

    assert "Response shaping strategy (Emotions V2):" in prompt
    assert "response_pace: measured" in prompt
    assert "verbosity: structured" in prompt
    assert "tone_shape: calm_focus" in prompt
    assert "Never introduce autonomous goals; stay user-guided" in prompt


def test_programmatic_synthesis_applies_tone_shape_opener(monkeypatch):
    monkeypatch.setattr(
        synth,
        "_emotion_decision_hooks",
        lambda: {
            "current_emotion": "steady",
            "strategy": {
                "response_pace": "measured",
                "verbosity": "medium",
                "tone_shape": "calm_focus",
                "ask_clarifying_question": False,
            },
            "guardrails": {
                "user_guided": True,
                "no_autonomous_objectives": True,
                "no_manipulative_affect": True,
            },
        },
    )

    text = synth.synthesize_programmatic([_advice("run focused tests after edit")])

    assert text.startswith("Calm focus:")


def test_programmatic_synthesis_applies_pace_to_detail_budget(monkeypatch):
    advice = [
        _advice("run focused test suite"),
        _advice("verify migration plan"),
        _advice("check rollback readiness"),
        _advice("capture release notes"),
    ]

    monkeypatch.setattr(
        synth,
        "_emotion_decision_hooks",
        lambda: {
            "current_emotion": "steady",
            "strategy": {
                "response_pace": "lively",
                "verbosity": "medium",
                "tone_shape": "grounded_warm",
                "ask_clarifying_question": False,
            },
            "guardrails": {
                "user_guided": True,
                "no_autonomous_objectives": True,
                "no_manipulative_affect": True,
            },
        },
    )
    lively = synth.synthesize_programmatic(advice)

    monkeypatch.setattr(
        synth,
        "_emotion_decision_hooks",
        lambda: {
            "current_emotion": "steady",
            "strategy": {
                "response_pace": "slow",
                "verbosity": "medium",
                "tone_shape": "grounded_warm",
                "ask_clarifying_question": False,
            },
            "guardrails": {
                "user_guided": True,
                "no_autonomous_objectives": True,
                "no_manipulative_affect": True,
            },
        },
    )
    slow = synth.synthesize_programmatic(advice)

    lively_bullets = sum(1 for line in lively.splitlines() if line.startswith("- "))
    slow_bullets = sum(1 for line in slow.splitlines() if line.startswith("- "))

    assert lively_bullets > slow_bullets


def test_programmatic_synthesis_is_plain_text_no_markdown_noise(monkeypatch):
    monkeypatch.setattr(
        synth,
        "_emotion_decision_hooks",
        lambda: {
            "current_emotion": "steady",
            "strategy": {
                "response_pace": "balanced",
                "verbosity": "medium",
                "tone_shape": "grounded_warm",
                "ask_clarifying_question": False,
            },
            "guardrails": {
                "user_guided": True,
                "no_autonomous_objectives": True,
                "no_manipulative_affect": True,
            },
        },
    )

    text = synth.synthesize_programmatic(
        [
            _advice("[Caution] verify rollback before deploy", authority="warning"),
            _advice("run quick smoke test on critical path"),
        ]
    )

    assert "**" not in text
    assert "<think>" not in text.lower()
    assert "Cautions:" in text
    assert "Relevant context:" in text
