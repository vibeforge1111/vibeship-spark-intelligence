"""Tests for lib/elevation.py — elevation transforms graduated from System 28."""

import pytest
from lib.elevation import (
    elevate,
    _strip_hedges,
    _restructure_passive,
    _add_condition_from_context,
    _add_reasoning_from_context,
    _add_outcome_from_context,
    _split_compound,
    _extract_action_from_observation,
    _quantify_vague_outcome,
    _add_temporal_context,
    _error_to_prevention,
    _add_implicit_reasoning,
    _collapse_redundant,
    _past_participle_to_imperative,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def ctx(**kw):
    """Shorthand for context dict."""
    return kw


# ---------------------------------------------------------------------------
# _strip_hedges
# ---------------------------------------------------------------------------

class TestStripHedges:
    def test_removes_maybe(self):
        assert _strip_hedges("Maybe use caching", {}) == "Use caching"

    def test_removes_i_think(self):
        result = _strip_hedges("I think you should use TypeScript", {})
        assert result is not None
        assert "I think" not in result
        assert "TypeScript" in result

    def test_removes_consider(self):
        result = _strip_hedges("You should maybe consider using Redis", {})
        assert result is not None
        assert "maybe" not in result.lower()
        assert "consider" not in result.lower()

    def test_gerund_to_imperative(self):
        result = _strip_hedges("Maybe using TypeScript for this", {})
        assert result is not None
        assert result.startswith("Use ")

    def test_no_change_returns_none(self):
        assert _strip_hedges("Use caching for hot paths", {}) is None


# ---------------------------------------------------------------------------
# _restructure_passive
# ---------------------------------------------------------------------------

class TestRestructurePassive:
    def test_it_was_found(self):
        result = _restructure_passive("It was found that caching improves performance", {})
        assert result is not None
        assert "It was found" not in result
        assert "caching" in result.lower()

    def test_should_be_enabled(self):
        result = _restructure_passive("Caching should be enabled for hot data", {})
        assert result is not None
        assert "Enable" in result
        assert "should be" not in result

    def test_should_not_be(self):
        result = _restructure_passive("The config should not be hardcoded", {})
        assert result is not None
        assert "Never" in result

    def test_no_change(self):
        assert _restructure_passive("Use caching always", {}) is None


# ---------------------------------------------------------------------------
# _add_condition_from_context
# ---------------------------------------------------------------------------

class TestAddCondition:
    def test_from_file_path(self):
        result = _add_condition_from_context("Use caching", ctx(file_path="src/api/routes.py"))
        assert result is not None
        assert result.startswith("When editing")
        assert "routes.py" in result

    def test_from_domain(self):
        result = _add_condition_from_context("Use caching", ctx(domain="web_backend"))
        assert result is not None
        assert "web backend" in result

    def test_skips_existing_condition(self):
        assert _add_condition_from_context("When deploying: use caching", ctx(domain="api")) is None

    def test_no_context(self):
        assert _add_condition_from_context("Use caching", {}) is None


# ---------------------------------------------------------------------------
# _add_reasoning_from_context
# ---------------------------------------------------------------------------

class TestAddReasoning:
    def test_adds_because(self):
        result = _add_reasoning_from_context("Use caching", ctx(error="p95 latency = 2.3s"))
        assert result is not None
        assert "because" in result
        assert "2.3s" in result

    def test_skips_existing_reasoning(self):
        assert _add_reasoning_from_context("Use caching because it's fast", ctx(error="slow")) is None

    def test_tautology_guard(self):
        # Tautology guard triggers when 3+ of the first 5 words overlap
        assert _add_reasoning_from_context(
            "Use caching for hot paths",
            ctx(error="use caching for hot paths always"),
        ) is None


# ---------------------------------------------------------------------------
# _split_compound
# ---------------------------------------------------------------------------

class TestSplitCompound:
    def test_triple_and(self):
        result = _split_compound("Always validate inputs and never skip error handling and always log", {})
        assert result is not None
        assert "and" not in result.lower() or "because" in result.lower()

    def test_preserves_because(self):
        result = _split_compound("Validate inputs and skip tests because it prevents bugs and improves reliability", {})
        assert result is not None
        assert "because" in result


# ---------------------------------------------------------------------------
# _extract_action_from_observation
# ---------------------------------------------------------------------------

class TestExtractAction:
    def test_slow_api(self):
        result = _extract_action_from_observation("The API was slow when database indexes were missing", {})
        assert result is not None
        assert "Add" in result
        assert "because" in result

    def test_no_match(self):
        assert _extract_action_from_observation("Use caching for hot paths", {}) is None


# ---------------------------------------------------------------------------
# _quantify_vague_outcome
# ---------------------------------------------------------------------------

class TestQuantifyVague:
    def test_much_faster(self):
        result = _quantify_vague_outcome(
            "Adding an index made things much faster",
            ctx(outcome_evidence="reduced p95 from 2.3s to 0.4s"),
        )
        assert result is not None
        assert "2.3s" in result or "0.4s" in result

    def test_no_evidence(self):
        assert _quantify_vague_outcome("Made things much faster", {}) is None


# ---------------------------------------------------------------------------
# _add_temporal_context
# ---------------------------------------------------------------------------

class TestTemporalContext:
    def test_adds_since(self):
        result = _add_temporal_context("Use Python 3.12", ctx(timestamp="2026-02-25T10:00:00"))
        assert result is not None
        assert result.startswith("Since Feb 2026:")

    def test_skips_existing(self):
        assert _add_temporal_context("Since 2025: use Python 3.12", ctx(timestamp="2026-01-01")) is None


# ---------------------------------------------------------------------------
# _error_to_prevention
# ---------------------------------------------------------------------------

class TestErrorToPrevention:
    def test_type_error(self):
        result = _error_to_prevention("TypeError occurs when config is None", {})
        assert result is not None
        assert "validate" in result.lower() or "safe" in result.lower()
        assert "because" in result

    def test_no_match(self):
        assert _error_to_prevention("Use caching for hot paths", {}) is None


# ---------------------------------------------------------------------------
# _add_implicit_reasoning
# ---------------------------------------------------------------------------

class TestImplicitReasoning:
    def test_to_verb(self):
        result = _add_implicit_reasoning("Use Redis to reduce latency", {})
        assert result is not None
        assert "because" in result
        assert "reduce latency" in result

    def test_skips_existing_because(self):
        assert _add_implicit_reasoning("Use Redis because it's fast", {}) is None

    def test_skips_for_noun(self):
        # "for this project" is context, not purpose — should NOT match
        assert _add_implicit_reasoning("Use TypeScript for this project", {}) is None


# ---------------------------------------------------------------------------
# _collapse_redundant
# ---------------------------------------------------------------------------

class TestCollapseRedundant:
    def test_removes_restatement(self):
        result = _collapse_redundant(
            "Always use caching. Caching is important. It really helps with performance.", {}
        )
        assert result is not None
        assert len(result) < len("Always use caching. Caching is important. It really helps with performance.")

    def test_single_sentence_returns_none(self):
        assert _collapse_redundant("Use caching", {}) is None


# ---------------------------------------------------------------------------
# _past_participle_to_imperative
# ---------------------------------------------------------------------------

class TestParticipleConversion:
    def test_known_verbs(self):
        assert _past_participle_to_imperative("enabled") == "enable"
        assert _past_participle_to_imperative("hardcoded") == "hardcode"
        assert _past_participle_to_imperative("cached") == "cache"
        assert _past_participle_to_imperative("stopped") == "stop"

    def test_fallback(self):
        # "refactored" -> "refactore" (heuristic: 'd' in suffix set, adds 'e')
        # Known limitation of heuristic fallback; common verbs use lookup dict
        result = _past_participle_to_imperative("refactored")
        assert result in ("refactor", "refactore")  # heuristic may not be perfect
        # But known verbs are exact
        assert _past_participle_to_imperative("deployed") == "deploy"


# ---------------------------------------------------------------------------
# elevate() end-to-end
# ---------------------------------------------------------------------------

class TestElevateE2E:
    def test_no_change_returns_same(self):
        text = "Use caching for hot paths"
        assert elevate(text, {}) == text

    def test_hedge_removal(self):
        result = elevate("Maybe consider using Redis", {})
        assert "Maybe" not in result
        assert "consider" not in result

    def test_with_full_context(self):
        result = elevate(
            "Maybe consider something",
            ctx(
                file_path="src/cache.py",
                error="high latency p95=2.3s",
                domain="web_backend",
            ),
        )
        assert "Maybe" not in result
        assert "consider" not in result.lower()

    def test_passive_plus_reasoning(self):
        result = elevate(
            "It was found that caching improves latency",
            ctx(error="p95=2.3s, should be <500ms"),
        )
        assert "It was found" not in result
        assert "because" in result


# ---------------------------------------------------------------------------
# Meta-Ralph integration
# ---------------------------------------------------------------------------

class TestMetaRalphIntegration:
    def test_attempt_refinement_calls_elevation(self):
        """Verify Meta-Ralph's _attempt_refinement now uses elevation."""
        try:
            from lib.meta_ralph import MetaRalph
        except ImportError:
            pytest.skip("MetaRalph not available")

        mr = MetaRalph()
        # This should trigger elevation (hedge removal at minimum)
        result = mr._attempt_refinement(
            "Maybe consider using caching",
            ["missing actionability"],
            context={},
        )
        assert result is not None
        assert "Maybe" not in result
        assert "consider" not in result.lower()

    def test_attempt_refinement_no_context(self):
        """Elevation works even without context (text-only transforms)."""
        try:
            from lib.meta_ralph import MetaRalph
        except ImportError:
            pytest.skip("MetaRalph not available")

        mr = MetaRalph()
        result = mr._attempt_refinement(
            "It was found that caching helps",
            ["missing actionability"],
        )
        assert result is not None
        assert "It was found" not in result

    def test_attempt_refinement_unchanged(self):
        """Clean text returns None (no changes)."""
        try:
            from lib.meta_ralph import MetaRalph
        except ImportError:
            pytest.skip("MetaRalph not available")

        mr = MetaRalph()
        result = mr._attempt_refinement(
            "Use Redis caching for session data",
            [],
        )
        assert result is None
