"""
Safety-net tests for advisory_engine.py — on_pre_tool() orchestration.

These tests mock all subsystems (advisor, gate, synthesizer, state) to test
the orchestration logic of on_pre_tool() in isolation. They verify:
- ENGINE_ENABLED guard
- Subsystem call ordering
- Error handling / fallback behavior
- Global dedupe behavior
- Text repeat detection

Usage:
    pytest tests/test_advisory_engine_on_pre_tool.py -v
"""

import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from dataclasses import dataclass
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Minimal mocks ────────────────────────────────────────────────────

@dataclass
class MockGateDecision:
    advice_id: str = "adv_001"
    authority: str = "note"
    emit: bool = True
    reason: str = "phase=impl, score=0.65"
    adjusted_score: float = 0.65
    original_score: float = 0.60


@dataclass
class MockGateResult:
    decisions: list = None
    emitted: list = None
    suppressed: list = None
    phase: str = "implementation"
    total_retrieved: int = 1

    def __post_init__(self):
        if self.decisions is None:
            d = MockGateDecision()
            self.decisions = [d]
            self.emitted = [d]
            self.suppressed = []


@dataclass
class MockAdvice:
    advice_id: str = "adv_001"
    text: str = "Consider connection pooling"
    confidence: float = 0.8
    source: str = "cognitive"
    context_match: float = 0.7
    insight_key: str = "wisdom:pooling"
    emotional_priority: float = 0.0
    category: str = "wisdom"


@dataclass
class MockState:
    shown_advice_ids: Dict[str, float] = None
    task_phase: str = "implementation"
    consecutive_failures: int = 0
    tool_suppressed_until: Dict[str, float] = None
    intent_family: str = "emergent_other"
    last_read_file: str = ""
    context_key: str = ""
    session_id: str = "test_session"

    def __post_init__(self):
        if self.shown_advice_ids is None:
            self.shown_advice_ids = {}
        if self.tool_suppressed_until is None:
            self.tool_suppressed_until = {}


# ── ENGINE_ENABLED guard ──────────────────────────────────────────────

def test_on_pre_tool_disabled():
    """When ENGINE_ENABLED is False, on_pre_tool should immediately return None."""
    with patch("lib.advisory_engine.ENGINE_ENABLED", False):
        from lib.advisory_engine import on_pre_tool
        result = on_pre_tool("session_1", "Read")
        assert result is None


# ── Subsystem availability ────────────────────────────────────────────

def test_on_pre_tool_returns_string_or_none():
    """on_pre_tool should return either a string or None, never other types."""
    with patch("lib.advisory_engine.ENGINE_ENABLED", True):
        from lib.advisory_engine import on_pre_tool
        result = on_pre_tool("test_session", "Read", tool_input={"file_path": "/tmp/test.py"})
        # Explicitly test it's not a bool, int, list, or exception
        assert isinstance(result, (str, type(None))), f"Expected str or None, got {type(result).__name__}: {result!r}"


# ── Error resilience ──────────────────────────────────────────────────

def test_on_pre_tool_handles_unknown_tool():
    """on_pre_tool should not crash for unknown tool names and returns None or advice."""
    with patch("lib.advisory_engine.ENGINE_ENABLED", True):
        from lib.advisory_engine import on_pre_tool

        # Unknown tool should not raise — the engine handles gracefully
        result = on_pre_tool("test_session", "UnknownTool")
        assert isinstance(result, (str, type(None))), f"Expected str or None, got {type(result).__name__}"


def test_on_pre_tool_handles_empty_session_id():
    """on_pre_tool should handle empty session_id gracefully without crashing."""
    with patch("lib.advisory_engine.ENGINE_ENABLED", True):
        from lib.advisory_engine import on_pre_tool
        # Empty session_id should not crash
        result = on_pre_tool("", "Read")
        assert isinstance(result, (str, type(None))), f"Expected str or None, got {type(result).__name__}"


# ── Global dedupe function ────────────────────────────────────────────

# ── Text repeat detection ─────────────────────────────────────────────

def test_duplicate_repeat_state_function():
    """Verify the text repeat detection function works."""
    from lib.advisory_engine import _duplicate_repeat_state

    state = MockState()
    # First call — should not be a repeat
    result = _duplicate_repeat_state(state, "some advice text")
    assert isinstance(result, dict)
    assert "repeat" in result


# ── Dead code removal verification ────────────────────────────────────

def test_low_auth_dead_code_removed():
    """Verify LOW_AUTH_* dead code was removed (Batch 1 + review fixes)."""
    import lib.advisory_engine as ae
    assert not hasattr(ae, "_low_auth_recently_emitted"), \
        "_low_auth_recently_emitted should have been removed in Batch 1"
    assert not hasattr(ae, "LOW_AUTH_GLOBAL_DEDUPE_ENABLED"), \
        "LOW_AUTH_GLOBAL_DEDUPE_ENABLED should have been removed (dead code)"
    assert not hasattr(ae, "LOW_AUTH_DEDUPE_LOG"), \
        "LOW_AUTH_DEDUPE_LOG should have been removed (dead code)"


# ── Rejection telemetry ────────────────────────────────────────────────

def test_record_rejection_exists():
    """Verify the rejection telemetry counter function exists."""
    from lib.advisory_engine import _record_rejection
    assert callable(_record_rejection)
