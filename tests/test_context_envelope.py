from __future__ import annotations

from lib.context_envelope import build_context_envelope


def test_build_context_envelope_adds_structured_metadata():
    text = "Validate JWT expiration before trusting user session claims."
    out = build_context_envelope(
        context="",
        insight=text,
        category="reasoning",
        source="distillation",
        advisory_quality={
            "structure": {
                "condition": "processing authenticated API requests",
                "action": "validate token exp and nbf",
                "reasoning": "prevents stale-token authorization bugs",
            }
        },
    )

    assert "Category: reasoning" in out
    assert "Source: distillation" in out
    assert "Action:" in out
    assert len(out) >= 120


def test_build_context_envelope_clips_at_max_chars():
    long_insight = " ".join(["memory" for _ in range(200)])
    out = build_context_envelope(
        context="short",
        insight=long_insight,
        category="context",
        source="capture",
        max_chars=140,
    )
    assert len(out) <= 140
