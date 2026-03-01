"""Tests for lib/memory_ops.py — ADD/UPDATE/DELETE/NOOP engine."""

import pytest
from dataclasses import dataclass, field
from typing import List, Optional

from lib.memory_ops import MemoryOp, MemoryDecision, MemoryOpsEngine


# ── Minimal mock insight for testing ────────────────────────────

@dataclass
class MockInsight:
    insight: str = ""
    confidence: float = 0.7
    times_validated: int = 0
    times_contradicted: int = 0
    last_validated_at: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
    counter_examples: List[str] = field(default_factory=list)


@pytest.fixture
def engine():
    return MemoryOpsEngine()


# ── ADD: no similar existing insight ────────────────────────────

class TestADD:
    def test_add_when_empty_store(self, engine):
        decision = engine.decide(
            new_text="Always validate auth tokens before API calls",
            new_category="wisdom",
            existing_insights={},
        )
        assert decision.op == MemoryOp.ADD

    def test_add_when_no_similar(self, engine):
        existing = {
            "wisdom:prefer_reading_first": MockInsight(
                insight="Always read a file before editing"
            ),
        }
        decision = engine.decide(
            new_text="Use circuit breakers for external API calls",
            new_category="reasoning",
            existing_insights=existing,
        )
        assert decision.op == MemoryOp.ADD

    def test_add_empty_text_is_noop(self, engine):
        decision = engine.decide(
            new_text="",
            new_category="wisdom",
            existing_insights={},
        )
        assert decision.op == MemoryOp.NOOP


# ── NOOP: near-duplicate ───────────────────────────────────────

class TestNOOP:
    def test_noop_exact_duplicate(self, engine):
        text = "Always validate auth tokens before API calls"
        existing = {"wisdom:always_validate_auth": MockInsight(insight=text)}
        decision = engine.decide(
            new_text=text,
            new_category="wisdom",
            existing_insights=existing,
        )
        assert decision.op == MemoryOp.NOOP
        assert "duplicate" in decision.reason

    def test_noop_near_duplicate(self, engine):
        existing = {
            "wisdom:always_validate_auth": MockInsight(
                insight="Always validate authentication tokens before processing API requests"
            ),
        }
        decision = engine.decide(
            new_text="Always validate authentication tokens before processing API calls",
            new_category="wisdom",
            existing_insights=existing,
        )
        # High word overlap → NOOP or UPDATE, not ADD.
        assert decision.op in (MemoryOp.NOOP, MemoryOp.UPDATE)


# ── UPDATE: similar but not duplicate ───────────────────────────

class TestUPDATE:
    def test_update_similar_insight(self, engine):
        """High word-overlap text should UPDATE or NOOP (not ADD).

        Uses texts with Jaccard > 0.75 so word-overlap fallback works
        even without embedding model loaded.
        """
        existing = {
            "wisdom:always_read_the_file_before_mak": MockInsight(
                insight="Always Read the file before making an Edit to verify current content"
            ),
        }
        decision = engine.decide(
            new_text="Always Read the file before making an Edit to check current content",
            new_category="wisdom",
            existing_insights=existing,
        )
        # Jaccard = 11/13 = 0.846 > 0.75 → should UPDATE or NOOP.
        assert decision.op in (MemoryOp.UPDATE, MemoryOp.NOOP)


# ── DELETE: contradiction detected ──────────────────────────────

class TestDELETE:
    def test_delete_on_contradiction(self, engine):
        # Texts must share enough words for Jaccard > 0.60 (sim_contradiction)
        # while containing opposition pair (always/never).
        # Jaccard("Always use verbose logging in production for debugging",
        #         "Never use verbose logging in production for debugging") = 7/9 = 0.778
        existing = {
            "wisdom:always_use_verbose_logging": MockInsight(
                insight="Always use verbose logging in production for debugging"
            ),
        }
        decision = engine.decide(
            new_text="Never use verbose logging in production for debugging",
            new_category="wisdom",
            existing_insights=existing,
        )
        # "Always" vs "Never" with same topic → contradiction.
        # Should be DELETE or UPDATE depending on activation.
        assert decision.op in (MemoryOp.DELETE, MemoryOp.UPDATE)
        if decision.op == MemoryOp.DELETE:
            assert decision.contradiction_confidence > 0


# ── Contradiction detection internals ───────────────────────────

class TestContradictionDetection:
    def test_negation_asymmetry(self):
        engine = MemoryOpsEngine()
        is_contr, conf = engine._detect_contradiction(
            "Don't use inline styles",
            "Use inline styles for quick prototyping",
        )
        assert is_contr is True
        assert conf > 0

    def test_opposition_pairs(self):
        engine = MemoryOpsEngine()
        # "always" vs "never" is a clean opposition pair.
        is_contr, conf = engine._detect_contradiction(
            "Always use dark mode for readability",
            "Never use dark mode for readability",
        )
        assert is_contr is True

    def test_no_contradiction(self):
        engine = MemoryOpsEngine()
        is_contr, _ = engine._detect_contradiction(
            "Use React for frontend",
            "Use PostgreSQL for database",
        )
        assert is_contr is False


# ── Decision matrix shape ───────────────────────────────────────

class TestDecisionMatrix:
    def test_decision_has_required_fields(self, engine):
        decision = engine.decide(
            new_text="Test insight",
            new_category="wisdom",
            existing_insights={},
        )
        assert isinstance(decision, MemoryDecision)
        assert isinstance(decision.op, MemoryOp)
        assert isinstance(decision.reason, str)
        d = decision.to_dict()
        assert "op" in d
        assert "similarity" in d

    def test_merge_texts_keeps_more_specific(self):
        # Text with more action verbs should win.
        engine = MemoryOpsEngine()
        merged = engine._merge_texts(
            "Always validate and sanitize user inputs at API boundaries to prevent injection",
            "Validate inputs at boundary",
            similarity=0.78,
        )
        # The longer, more specific text should be chosen.
        assert len(merged) > 30
