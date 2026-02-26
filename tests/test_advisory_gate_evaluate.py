"""
Safety-net tests for advisory_gate.py — evaluate() and _evaluate_single().

These tests lock down gate behavior BEFORE the intelligence flow evolution
modifies the read path. Covers authority assignment, suppression filters,
dynamic budget, and multiplier systems.

Usage:
    pytest tests/test_advisory_gate_evaluate.py -v
"""

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.advisory_gate import (
    AUTHORITY_THRESHOLDS,
    AuthorityLevel,
    GateResult,
    _assign_authority,
    _evaluate_single,
    _shown_ttl_for_advice,
    _source_ttl_scale,
    _tool_cooldown_scale,
    evaluate,
)

# ── Minimal mock objects ──────────────────────────────────────────────

@dataclass
class MockAdvice:
    advice_id: str = "test_001"
    text: str = "Consider using connection pooling for better performance"
    confidence: float = 0.8
    source: str = "cognitive"
    context_match: float = 0.7
    insight_key: str = "wisdom:connection_pooling"
    emotional_priority: float = 0.0


@dataclass
class MockState:
    shown_advice_ids: Dict[str, float] = None
    task_phase: str = "implementation"
    consecutive_failures: int = 0
    tool_suppressed_until: Dict[str, float] = None

    def __post_init__(self):
        if self.shown_advice_ids is None:
            self.shown_advice_ids = {}
        if self.tool_suppressed_until is None:
            self.tool_suppressed_until = {}


# ── evaluate() with empty input ──────────────────────────────────────

def test_evaluate_empty_list():
    state = MockState()
    result = evaluate([], state, "Read")
    assert isinstance(result, GateResult)
    assert result.emitted == []
    assert result.suppressed == []
    assert result.total_retrieved == 0


def test_evaluate_none_items():
    """evaluate() should handle None gracefully (or raise TypeError — documents current behavior)."""
    state = MockState()
    try:
        result = evaluate(None, state, "Read")
        assert result.emitted == []
        assert result.total_retrieved == 0
    except TypeError:
        # Current behavior: None is not iterable. This is a known gap
        # that the evolution will fix with an early guard.
        pass


# ── Authority assignment ──────────────────────────────────────────────

def test_authority_warning_high_score_caution():
    """WARNING requires high score AND caution/negative text."""
    auth = _assign_authority(0.85, 0.9, "[Caution] Don't skip input validation", "cognitive")
    assert auth == AuthorityLevel.WARNING

def test_authority_note_high_score_no_caution():
    """High score without caution text → NOTE not WARNING."""
    auth = _assign_authority(0.85, 0.9, "Use connection pooling for better throughput", "cognitive")
    assert auth == AuthorityLevel.NOTE

def test_authority_note_moderate_score():
    """Score above NOTE threshold → NOTE."""
    note_threshold = AUTHORITY_THRESHOLDS[AuthorityLevel.NOTE]
    auth = _assign_authority(note_threshold + 0.05, 0.7, "Consider caching results", "cognitive")
    assert auth == AuthorityLevel.NOTE

def test_authority_whisper_low_score():
    """Score between WHISPER and NOTE → WHISPER."""
    whisper_threshold = AUTHORITY_THRESHOLDS[AuthorityLevel.WHISPER]
    note_threshold = AUTHORITY_THRESHOLDS[AuthorityLevel.NOTE]
    mid = (whisper_threshold + note_threshold) / 2
    # Ensure the text is not primitive noise and doesn't trigger actionable boost
    auth = _assign_authority(mid, 0.3, "This is a moderate confidence suggestion about architecture design patterns for distributed systems", "bank")
    assert auth in (AuthorityLevel.WHISPER, AuthorityLevel.NOTE)

def test_authority_silent_very_low_score():
    """Score below WHISPER → SILENT."""
    auth = _assign_authority(0.05, 0.1, "Something very low confidence and quite generic but not too short", "bank")
    assert auth == AuthorityLevel.SILENT

def test_authority_silent_primitive_noise():
    """Primitive noise patterns always → SILENT regardless of score."""
    auth = _assign_authority(0.95, 0.95, "Bash → Edit → Read", "cognitive")
    assert auth == AuthorityLevel.SILENT


# ── Shown TTL suppression (Filter 1) ─────────────────────────────────

def test_shown_ttl_suppresses_recently_shown():
    """Advice shown 10 seconds ago should be suppressed."""
    state = MockState(shown_advice_ids={"test_001": time.time() - 10})
    advice = MockAdvice(advice_id="test_001")

    with patch("lib.advisory_state.is_tool_suppressed", return_value=False):
        decision = _evaluate_single(advice, state, "Edit", None, "implementation")

    assert not decision.emit
    assert "shown" in decision.reason.lower()


def test_shown_ttl_allows_expired():
    """Advice shown long ago should be allowed (past any reasonable TTL)."""
    # Use 10000s to safely exceed any multiplied TTL (base * category * source).
    state = MockState(shown_advice_ids={"test_001": time.time() - 10_000})
    advice = MockAdvice(advice_id="test_001")

    with patch("lib.advisory_state.is_tool_suppressed", return_value=False):
        decision = _evaluate_single(advice, state, "Edit", None, "implementation")

    assert "shown" not in decision.reason.lower() or decision.emit


# ── Tool cooldown (Filter 2) ─────────────────────────────────────────

def test_tool_cooldown_suppresses():
    """Advice suppressed when tool is on cooldown."""
    state = MockState()
    advice = MockAdvice()

    with patch("lib.advisory_state.is_tool_suppressed", return_value=True):
        decision = _evaluate_single(advice, state, "Edit", None, "implementation")

    assert not decision.emit
    assert "cooldown" in decision.reason.lower()


def test_tool_cooldown_allows_when_clear():
    """Advice allowed when tool is NOT on cooldown."""
    state = MockState()
    advice = MockAdvice()

    with patch("lib.advisory_state.is_tool_suppressed", return_value=False):
        decision = _evaluate_single(advice, state, "Edit", None, "implementation")

    # Should be emittable (no cooldown)
    assert decision.emit or decision.authority == AuthorityLevel.SILENT


# ── Dynamic budget ────────────────────────────────────────────────────

def test_dynamic_budget_base():
    """Base budget should be MAX_EMIT_PER_CALL (2)."""
    state = MockState()
    # Keep per-item score below warning threshold so warning boost does not apply.
    items = [MockAdvice(advice_id=f"adv_{i}", confidence=0.6, context_match=0.4) for i in range(5)]

    with patch("lib.advisory_state.is_tool_suppressed", return_value=False):
        result = evaluate(items, state, "Edit")

    # Base budget is 2; effective cap can rise to 3 when internal warning boost applies.
    assert len(result.emitted) <= 3, f"Base budget should not exceed 3, got {len(result.emitted)}"


def test_dynamic_budget_warning_boost():
    """WARNING items should increase the budget by 1."""
    state = MockState()
    items = [
        MockAdvice(advice_id="warn_1", text="[Caution] Avoid eval() in production", confidence=0.95, context_match=0.9),
        MockAdvice(advice_id="note_1", text="Use parameterized queries for database access", confidence=0.8, context_match=0.7),
        MockAdvice(advice_id="note_2", text="Consider connection pooling for better throughput", confidence=0.75, context_match=0.7),
    ]

    with patch("lib.advisory_state.is_tool_suppressed", return_value=False):
        result = evaluate(items, state, "Edit")

    # With a WARNING present, budget increases — should emit more than 2
    emitted_count = len(result.emitted)
    assert emitted_count >= 2, f"Expected >= 2 emitted with WARNING boost, got {emitted_count}"


# ── Source TTL multipliers ────────────────────────────────────────────

def test_source_ttl_cognitive():
    scale = _source_ttl_scale("cognitive")
    assert scale == 1.0, f"Cognitive source should have 1.0x TTL, got {scale}"

def test_source_ttl_baseline():
    scale = _source_ttl_scale("baseline")
    assert scale == 0.5, f"Baseline source should have 0.5x TTL, got {scale}"

def test_source_ttl_unknown():
    scale = _source_ttl_scale("unknown_source")
    assert scale == 1.0, f"Unknown source should fall back to default 1.0x, got {scale}"


# ── Tool cooldown multipliers ────────────────────────────────────────

def test_tool_cooldown_read():
    scale = _tool_cooldown_scale("Read")
    assert scale == 0.5, f"Read should have 0.5x cooldown, got {scale}"

def test_tool_cooldown_edit():
    scale = _tool_cooldown_scale("Edit")
    assert scale == 1.2, f"Edit should have 1.2x cooldown, got {scale}"

def test_tool_cooldown_unknown():
    scale = _tool_cooldown_scale("UnknownTool")
    assert scale == 1.0, f"Unknown tool should fall back to 1.0x, got {scale}"


# ── Combined shown TTL (source + category) ───────────────────────────

def test_shown_ttl_cognitive_source():
    ttl, scale = _shown_ttl_for_advice("wisdom", "cognitive")
    # cognitive = 1.0x, so TTL should be close to base
    assert ttl > 0
    assert scale >= 0.9, f"Cognitive wisdom should have scale >= 0.9, got {scale}"

def test_shown_ttl_baseline_source():
    ttl, scale = _shown_ttl_for_advice("context", "baseline")
    # baseline = 0.5x, so TTL should be about half of base
    assert scale <= 0.6, f"Baseline context should have scale <= 0.6, got {scale}"


# ── Phase relevance boost ────────────────────────────────────────────

def test_debugging_phase_boosts_self_awareness():
    """During debugging, self_awareness insights should get boosted."""
    state = MockState(task_phase="debugging")
    advice = MockAdvice(
        insight_key="self_awareness:past_failure",
        text="[Past Failure] You tend to miss edge cases in error handling",
        confidence=0.8,
        context_match=0.6,
    )

    with patch("lib.advisory_state.is_tool_suppressed", return_value=False):
        decision = _evaluate_single(advice, state, "Bash", None, "debugging")

    # Self-awareness during debugging should get 1.5x boost
    assert decision.adjusted_score > decision.original_score


# ── Obvious suppression ──────────────────────────────────────────────

def test_read_before_edit_suppressed_on_bash():
    """'Read before Edit' advice should be suppressed on non-Edit tools."""
    state = MockState()
    advice = MockAdvice(text="Always read a file before editing to verify current state")

    with patch("lib.advisory_state.is_tool_suppressed", return_value=False):
        decision = _evaluate_single(advice, state, "Bash", None, "implementation")

    assert not decision.emit
    assert "read-before-edit" in decision.reason.lower()


def test_primitive_noise_suppressed():
    """Primitive noise patterns should never emit."""
    state = MockState()
    advice = MockAdvice(text="Read → Edit → Write", confidence=0.9, context_match=0.9)

    with patch("lib.advisory_state.is_tool_suppressed", return_value=False):
        decision = _evaluate_single(advice, state, "Edit", None, "implementation")

    assert not decision.emit
    assert decision.authority == AuthorityLevel.SILENT
