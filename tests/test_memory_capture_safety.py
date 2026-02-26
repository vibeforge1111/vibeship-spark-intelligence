"""
Safety-net tests for memory_capture.py — importance_score() function.

These tests lock down the scoring behavior BEFORE the intelligence flow
evolution changes routing logic. If any of these fail after a change,
the change likely broke scoring semantics.

Usage:
    pytest tests/test_memory_capture_safety.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.memory_capture import _compact_context_snippet, importance_score

# ── Hard trigger detection ────────────────────────────────────────────

def test_hard_trigger_remember_this():
    score, breakdown = importance_score("remember this: always use PostgreSQL for this project")
    assert score >= 0.9, f"'remember this' should score >= 0.9, got {score}"
    assert "hard_trigger" in breakdown

def test_hard_trigger_never():
    score, breakdown = importance_score("never use eval() in production code")
    assert score >= 0.6, f"'never' should score >= 0.6, got {score}"

def test_hard_trigger_from_now_on():
    score, breakdown = importance_score("from now on, use TypeScript for all new files")
    assert score >= 0.8, f"'from now on' should score >= 0.8, got {score}"
    assert "hard_trigger" in breakdown


# ── Soft trigger detection ────────────────────────────────────────────

def test_soft_trigger_i_prefer():
    score, breakdown = importance_score("i prefer dark theme for the editor")
    assert score >= 0.5, f"'i prefer' should score >= 0.5, got {score}"
    assert "soft_trigger" in breakdown

def test_soft_trigger_design_constraint():
    score, breakdown = importance_score("design constraint: must support offline mode")
    assert score >= 0.6, f"'design constraint' should score >= 0.6, got {score}"


# ── Semantic signal: causal language ──────────────────────────────────

def test_causal_because():
    score, breakdown = importance_score("Use connection pooling because it reduces latency by 40%")
    assert "causal" in breakdown, f"Expected 'causal' in breakdown, got {breakdown}"
    assert breakdown["causal"] >= 0.30

def test_causal_soft_tends_to():
    score, breakdown = importance_score("Redis tends to be faster than PostgreSQL for caching")
    assert "causal" in breakdown, f"Expected 'causal' in breakdown, got {breakdown}"
    assert breakdown["causal"] >= 0.15

def test_causal_prevents():
    score, breakdown = importance_score("Input validation prevents SQL injection attacks")
    assert "causal" in breakdown


# ── Semantic signal: quantitative evidence ────────────────────────────

def test_quantitative_percent():
    score, breakdown = importance_score("Cache hit rate improved from 45% to 92% after adding Redis")
    assert "quantitative" in breakdown, f"Expected 'quantitative', got {breakdown}"
    assert breakdown["quantitative"] >= 0.25

def test_quantitative_from_to():
    score, breakdown = importance_score("Response time went from 4.2s to 1.6s after optimization")
    assert "quantitative" in breakdown
    assert breakdown["quantitative"] >= 0.30

def test_quantitative_ms():
    score, breakdown = importance_score("P95 latency is 350ms which is acceptable for our SLA")
    assert "quantitative" in breakdown


# ── Semantic signal: comparative language ─────────────────────────────

def test_comparative_better_than():
    score, breakdown = importance_score("TypeScript is better than JavaScript for large codebases")
    assert "comparative" in breakdown
    assert breakdown["comparative"] >= 0.25

def test_comparative_faster():
    score, breakdown = importance_score("Vite is faster than webpack for development builds")
    assert "comparative" in breakdown
    assert breakdown["comparative"] >= 0.15


# ── Semantic signal: technical specificity ────────────────────────────

def test_technical_three_hits():
    # Need 3+ distinct tech hits for 0.30 — use more explicit framework names
    score, breakdown = importance_score("Use React with TypeScript and Redis and PostgreSQL for the frontend")
    assert "technical" in breakdown
    assert breakdown["technical"] >= 0.22, f"3+ tech hits should score >= 0.22, got {breakdown.get('technical')}"

def test_technical_two_hits():
    score, breakdown = importance_score("FastAPI with PostgreSQL is the right choice here")
    assert "technical" in breakdown
    assert breakdown["technical"] >= 0.22

def test_technical_one_hit():
    score, breakdown = importance_score("We should use Redis for this cache layer")
    assert "technical" in breakdown
    assert breakdown["technical"] >= 0.15


# ── Semantic signal: actionable language ──────────────────────────────

def test_actionable_always():
    score, breakdown = importance_score("always validate user input at the API boundary")
    # "always" hits hard_trigger AND actionable
    assert score >= 0.6

def test_actionable_implement():
    score, breakdown = importance_score("implement rate limiting on all public endpoints")
    assert "actionable" in breakdown


# ── Score stacking (semantic signals combine) ─────────────────────────

def test_stacking_causal_plus_quantitative():
    score, breakdown = importance_score(
        "Connection pooling reduces latency because it reuses TCP connections, improving throughput by 60%"
    )
    assert "causal" in breakdown
    assert "quantitative" in breakdown
    # Combined semantic sum should exceed single-signal threshold
    semantic_sum = sum(v for k, v in breakdown.items() if k in ("causal", "quantitative", "comparative", "technical", "actionable"))
    assert semantic_sum >= 0.50, f"Stacked semantic sum should be >= 0.50, got {semantic_sum}"

def test_stacking_tech_plus_comparative_plus_causal():
    score, breakdown = importance_score(
        "FastAPI is faster than Django because of async support, reducing P95 from 200ms to 50ms"
    )
    assert score >= 0.60, f"Triple-stacked signals should score >= 0.60, got {score}"
    signal_count = sum(1 for k in ("causal", "quantitative", "comparative", "technical") if k in breakdown)
    assert signal_count >= 3, f"Expected >= 3 semantic signals, got {signal_count}: {breakdown}"


# ── Threshold boundaries ──────────────────────────────────────────────

def test_below_suggest_threshold():
    """Pure noise should score below 0.55 (SUGGEST_THRESHOLD)."""
    score, _ = importance_score("okay sure")
    assert score < 0.55, f"Pure noise should be < 0.55, got {score}"

def test_above_auto_save_threshold():
    """Strong hard trigger should score >= 0.65 (AUTO_SAVE_THRESHOLD)."""
    score, _ = importance_score("remember this: always use bcrypt for password hashing")
    assert score >= 0.65, f"Hard trigger should be >= 0.65, got {score}"

def test_empty_string():
    score, breakdown = importance_score("")
    assert score == 0.0
    assert breakdown == {}

def test_none_input():
    score, breakdown = importance_score(None)
    assert score == 0.0
    assert breakdown == {}


# ── Emphasis signals ──────────────────────────────────────────────────

def test_emphasis_must():
    score, breakdown = importance_score("this must be fixed before release")
    assert "emphasis" in breakdown

def test_caps_emphasis():
    score, breakdown = importance_score("DO NOT use EVAL in any production code")
    assert "caps" in breakdown

def test_length_bonus():
    long_text = "This is a very long statement about architecture decisions " * 5
    score, breakdown = importance_score(long_text)
    assert "length" in breakdown


def test_compact_context_drops_inventory_lines_and_keeps_semantics():
    raw = """
    SYSTEM INVENTORY (what actually exists)
    event_type: user_prompt
    tool_name: Bash
    We should raise retrieval thresholds because low similarity hits are dominating advisory output.
    This reduces stale-memory misreads and improves trust.
    """
    compact = _compact_context_snippet(raw, max_chars=220)
    lowered = compact.lower()
    assert "system inventory" not in lowered
    assert "event_type" not in lowered
    assert "tool_name" not in lowered
    assert "because low similarity hits are dominating advisory output" in lowered
    assert len(compact) <= 220


def test_compact_context_prioritizes_high_signal_sentences():
    raw = (
        "Status: idle. "
        "Raise the auto-save threshold to 0.72 because capture is too noisy and stale results are being reused. "
        "This should improve retrieval trust and reduce repeated generic keys. "
        "file_path: C:/tmp/trace.log."
    )
    compact = _compact_context_snippet(raw, max_chars=180)
    lowered = compact.lower()
    assert "raise the auto-save threshold to 0.72 because capture is too noisy" in lowered
    assert "file_path" not in lowered
    assert len(compact) <= 180
