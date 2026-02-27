"""Advisory Calibration Unit Tests — fast feedback loop for tuning.

Tests individual layers of the advisory gate pipeline in isolation.
Designed to run in <30s for rapid calibration iterations.

Usage:
    pytest tests/test_advisory_calibration.py -v --tb=short
    pytest tests/test_advisory_calibration.py::TestNoiseRejection -v

Created 2026-02-22 as part of comprehensive advisory calibration system.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import lib.advisory_gate as gate
from lib.advisory_gate import (
    AUTHORITY_THRESHOLDS,
    AuthorityLevel,
    _assign_authority,
    _check_obvious_suppression,
    _has_actionable_content,
    _is_caution,
    _is_negative_advisory,
    _is_primitive_noise,
    evaluate,
)


@dataclass
class _MockAdvice:
    """Minimal mock matching fields read by advisory_gate._evaluate_single."""
    advice_id: str = "adv_test_001"
    insight_key: str = "context:test"
    text: str = "Test advice"
    confidence: float = 0.7
    source: str = "cognitive"
    context_match: float = 0.7
    emotional_priority: float = 0.0


def _make_state(**overrides):
    """Build a minimal SessionState for testing."""
    from lib.runtime_session_state import SessionState
    base = {"session_id": "test_calibration"}
    base.update(overrides)
    return SessionState.from_dict(base)


# ═══════════════════════════════════════════════════════════════
# 1. TestScoreBoundaries: authority assignment at exact thresholds
# ═══════════════════════════════════════════════════════════════

class TestScoreBoundaries:
    """Verify _assign_authority at exact threshold boundaries.

    NOTE: Thresholds are loaded from tuneables.json at runtime and may differ
    from the defaults in advisory_gate.py. Tests use AUTHORITY_THRESHOLDS
    dynamically to stay correct regardless of tuning.
    """

    def test_below_whisper_is_silent(self):
        whisper = AUTHORITY_THRESHOLDS[AuthorityLevel.WHISPER]
        score = whisper - 0.05
        assert _assign_authority(score, 0.5, "Some reasonable advice text here.", "cognitive") == AuthorityLevel.SILENT

    def test_above_whisper(self):
        whisper = AUTHORITY_THRESHOLDS[AuthorityLevel.WHISPER]
        note = AUTHORITY_THRESHOLDS[AuthorityLevel.NOTE]
        score = whisper + 0.02
        result = _assign_authority(score, 0.5, "Some reasonable advice text here.", "cognitive")
        expected = AuthorityLevel.NOTE if score >= note else AuthorityLevel.WHISPER
        assert result == expected

    def test_above_whisper_below_note(self):
        whisper = AUTHORITY_THRESHOLDS[AuthorityLevel.WHISPER]
        note = AUTHORITY_THRESHOLDS[AuthorityLevel.NOTE]
        score = (whisper + note) / 2  # Midpoint between whisper and note
        # Could be WHISPER or NOTE depending on micro-boost. Non-actionable text → WHISPER.
        result = _assign_authority(score, 0.5, "Some reasonable advice text here.", "cognitive")
        assert result in (AuthorityLevel.WHISPER, AuthorityLevel.NOTE)

    def test_at_note_boundary(self):
        note = AUTHORITY_THRESHOLDS[AuthorityLevel.NOTE]
        score = note + 0.02
        assert _assign_authority(score, 0.5, "Some reasonable advice text here.", "cognitive") == AuthorityLevel.NOTE

    def test_above_note(self):
        assert _assign_authority(0.60, 0.5, "Some reasonable advice text here.", "cognitive") == AuthorityLevel.NOTE

    def test_at_warning_non_caution(self):
        warning = AUTHORITY_THRESHOLDS[AuthorityLevel.WARNING]
        score = warning + 0.02
        assert _assign_authority(score, 0.9, "This approach works well for production.", "eidos") == AuthorityLevel.NOTE

    def test_at_warning_with_caution(self):
        warning = AUTHORITY_THRESHOLDS[AuthorityLevel.WARNING]
        score = warning + 0.02
        assert _assign_authority(score, 0.9, "[Caution] Don't skip validation.", "eidos") == AuthorityLevel.WARNING

    def test_at_warning_with_negative(self):
        warning = AUTHORITY_THRESHOLDS[AuthorityLevel.WARNING]
        score = warning + 0.02
        assert _assign_authority(score, 0.9, "Avoid using eval() on untrusted input.", "eidos") == AuthorityLevel.WARNING

    def test_primitive_noise_overrides_high_score(self):
        # Even score 0.95 → SILENT if text is primitive noise
        assert _assign_authority(0.95, 0.95, "5 calls to Edit", "eidos") == AuthorityLevel.SILENT

    def test_actionable_micro_boost(self):
        # Score in [NOTE-0.08, NOTE) range + actionable → NOTE
        threshold = AUTHORITY_THRESHOLDS[AuthorityLevel.NOTE]
        score = threshold - 0.05  # Just below NOTE
        result = _assign_authority(score, 0.5, "Check the file before proceeding.", "cognitive")
        assert result == AuthorityLevel.NOTE, f"Actionable micro-boost should promote to NOTE, got {result}"

    def test_no_micro_boost_without_actionable(self):
        # Score in boost range but NOT actionable should not promote to NOTE.
        threshold = AUTHORITY_THRESHOLDS[AuthorityLevel.NOTE]
        whisper = AUTHORITY_THRESHOLDS[AuthorityLevel.WHISPER]
        score = threshold - 0.05
        result = _assign_authority(score, 0.5, "This pattern is commonly seen in codebases.", "bank")
        assert result != AuthorityLevel.NOTE, f"Non-actionable should not promote to NOTE, got {result}"
        expected = AuthorityLevel.WHISPER if score >= whisper else AuthorityLevel.SILENT
        assert result == expected


# ═══════════════════════════════════════════════════════════════
# 2. TestGateFilters: context suppression patterns
# ═══════════════════════════════════════════════════════════════

class TestGateFilters:
    """Test each context-suppression pattern in _check_obvious_suppression."""

    def test_read_before_edit_on_bash(self):
        suppressed, reason = _check_obvious_suppression(
            "Read before Edit when modifying files.", "Bash", {}, None,
        )
        assert suppressed is True
        assert "read-before-edit" in reason

    def test_read_before_edit_on_edit_allowed(self):
        suppressed, _ = _check_obvious_suppression(
            "Read before Edit when modifying files.", "Edit", {}, None,
        )
        assert suppressed is False

    def test_generic_read_on_read(self):
        suppressed, reason = _check_obvious_suppression(
            "When reading this file, note the structure.", "Read", {}, None,
        )
        assert suppressed is True
        assert "generic Read" in reason

    def test_read_with_before_on_read_allowed(self):
        suppressed, _ = _check_obvious_suppression(
            "Read the CHANGELOG before making changes.", "Read", {}, None,
        )
        assert suppressed is False

    def test_webfetch_on_non_web(self):
        suppressed, reason = _check_obvious_suppression(
            "WebFetch fails on auth URLs.", "Edit", {}, None,
        )
        assert suppressed is True
        assert "WebFetch" in reason

    def test_webfetch_on_webfetch_allowed(self):
        suppressed, _ = _check_obvious_suppression(
            "WebFetch fails on auth URLs.", "WebFetch", {}, None,
        )
        assert suppressed is False

    def test_telemetry_struggle(self):
        suppressed, reason = _check_obvious_suppression(
            "[Caution] I struggle with tool_49_error tasks", "Edit", {}, None,
        )
        assert suppressed is True
        assert "telemetry" in reason

    def test_telemetry_error_suffix(self):
        suppressed, reason = _check_obvious_suppression(
            "I struggle with tool_12_error consistently.", "Bash", {}, None,
        )
        assert suppressed is True

    def test_non_telemetry_struggle_allowed(self):
        suppressed, _ = _check_obvious_suppression(
            "I struggle with complex regex patterns.", "Edit", {}, None,
        )
        assert suppressed is False

    def test_meta_constraint_on_edit(self):
        suppressed, reason = _check_obvious_suppression(
            "Constraint: one state machine per session.", "Edit", {}, None,
        )
        assert suppressed is True
        assert "meta constraint" in reason

    def test_meta_constraint_on_plan_allowed(self):
        suppressed, _ = _check_obvious_suppression(
            "Constraint: one state machine per session.", "EnterPlanMode", {}, None,
        )
        assert suppressed is False

    def test_deploy_in_exploration(self):
        state = _make_state(task_phase="exploration")
        suppressed, reason = _check_obvious_suppression(
            "Deploy to staging after tests pass.", "Bash", {}, state,
        )
        assert suppressed is True
        assert "deployment" in reason

    def test_deploy_in_implementation_allowed(self):
        state = _make_state(task_phase="implementation")
        suppressed, _ = _check_obvious_suppression(
            "Deploy to staging after tests pass.", "Bash", {}, state,
        )
        assert suppressed is False

    def test_read_before_edit_file_recently_read(self):
        # had_recent_read() checks "timestamp" and "input_hint" fields
        state = _make_state(
            task_phase="implementation",
            recent_tools=[
                {"tool_name": "Read", "input_hint": "/src/app.py",
                 "timestamp": time.time(), "success": True},
            ],
        )
        result = evaluate(
            [_MockAdvice(text="Read before Edit to verify file state.",
                         confidence=0.75, context_match=0.70)],
            state, "Edit", {"file_path": "/src/app.py"},
        )
        assert len(result.emitted) == 0, "Read-before-edit should suppress when file was recently Read"

    def test_tool_cooldown_suppresses(self):
        state = _make_state(suppressed_tools={"Edit": time.time() + 600})
        result = evaluate(
            [_MockAdvice(text="Add type hints for clarity.", confidence=0.75, context_match=0.70)],
            state, "Edit",
        )
        assert len(result.emitted) == 0

    def test_shown_recently_suppresses(self):
        state = _make_state(shown_advice_ids={"adv_test_001": time.time()})
        result = evaluate(
            [_MockAdvice(advice_id="adv_test_001", text="Use type hints.", confidence=0.75, context_match=0.70)],
            state, "Edit",
        )
        assert len(result.emitted) == 0

    def test_category_multiplier_extends_shown_ttl(self):
        original = gate.get_gate_config()
        try:
            gate.apply_gate_config(
                {
                    "shown_advice_ttl_s": 60,
                    "category_cooldown_multipliers": {"security": 2.0},
                }
            )
            state = _make_state(shown_advice_ids={"adv_test_001": time.time() - 90})
            result = evaluate(
                [
                    _MockAdvice(
                        advice_id="adv_test_001",
                        insight_key="security:csrf",
                        source="security",
                        text="Validate auth headers server-side.",
                        confidence=0.75,
                        context_match=0.70,
                    )
                ],
                state,
                "Edit",
            )
            assert len(result.emitted) == 0
            assert any("TTL 120s" in d.reason for d in result.suppressed)
        finally:
            gate.apply_gate_config(original)

    def test_category_multiplier_extends_tool_cooldown(self):
        original = gate.get_gate_config()
        try:
            gate.apply_gate_config({"category_cooldown_multipliers": {"context": 2.0}})
            now = time.time()
            state = _make_state(
                suppressed_tools={
                    "Edit": {"started_at": now - 12, "duration_s": 10, "until": now - 2}
                }
            )
            result = evaluate(
                [
                    _MockAdvice(
                        advice_id="adv_test_002",
                        insight_key="context:sql",
                        text="Use parameterized queries for database safety.",
                        confidence=0.85,
                        context_match=0.85,
                    )
                ],
                state,
                "Edit",
            )
            assert len(result.emitted) == 0
            assert any("tool Edit on cooldown" in d.reason for d in result.suppressed)
        finally:
            gate.apply_gate_config(original)


# ═══════════════════════════════════════════════════════════════
# 3. TestToolCalibration: tool-advice alignment
# ═══════════════════════════════════════════════════════════════

class TestToolCalibration:
    """Verify advice reaches the right tool and gets suppressed for wrong tools."""

    def test_edit_advice_on_edit_passes(self):
        result = evaluate(
            [_MockAdvice(text="Check indentation when editing Python files.", confidence=0.75, context_match=0.70)],
            None, "Edit",
        )
        assert len(result.emitted) > 0

    def test_webfetch_advice_on_edit_suppressed(self):
        result = evaluate(
            [_MockAdvice(text="WebFetch times out on large pages.", confidence=0.75, context_match=0.70)],
            None, "Edit",
        )
        assert len(result.emitted) == 0

    def test_general_advice_passes_any_tool(self):
        result = evaluate(
            [_MockAdvice(text="Use parameterized queries for database safety.", confidence=0.75, context_match=0.70)],
            None, "Grep",
        )
        assert len(result.emitted) > 0


# ═══════════════════════════════════════════════════════════════
# 4. TestNoiseRejection: known noise patterns must suppress
# ═══════════════════════════════════════════════════════════════

class TestNoiseRejection:
    """10 known noise patterns that MUST be suppressed."""

    def test_cycle_summary(self):
        assert _is_primitive_noise("Cycle summary: Edit used 9 times (100% success)")

    def test_tool_sequence(self):
        assert _is_primitive_noise("Read \u2192 Edit \u2192 Write")

    def test_short_text(self):
        assert _is_primitive_noise("Use Bash.")

    def test_ok_response(self):
        assert _is_primitive_noise("okay")

    def test_success_rate(self):
        assert _is_primitive_noise("success rate for Edit: 95%")

    def test_invocation_count(self):
        assert _is_primitive_noise("47 calls to Edit in the last session")

    def test_generic_standard(self):
        assert _is_primitive_noise("For Write tasks, use standard approach and follow best practices.")

    def test_empty_string(self):
        assert _is_primitive_noise("")

    def test_whitespace(self):
        assert _is_primitive_noise("   \n  \t  ")

    def test_error_count(self):
        assert _is_primitive_noise("error count for last session: 12")


# ═══════════════════════════════════════════════════════════════
# 5. TestHighValuePass: known valuable patterns must emit
# ═══════════════════════════════════════════════════════════════

class TestHighValuePass:
    """10 known valuable patterns that MUST pass through to emission."""

    def _assert_emits(self, text, tool="Edit"):
        result = evaluate(
            [_MockAdvice(text=text, confidence=0.80, context_match=0.75, source="cognitive")],
            None, tool,
        )
        assert len(result.emitted) > 0, f"Expected emission for: {text[:60]}..."

    def test_batch_mode(self):
        self._assert_emits("Use batch mode for CognitiveLearner saves — reduces I/O by 66x.")

    def test_float_truncation(self):
        self._assert_emits("int() truncates float thresholds — use float() for quality_threshold.")

    def test_regex_pattern(self):
        self._assert_emits("Regex word boundary prevents stem matching — use word\\w* instead.")

    def test_save_merge_gotcha(self):
        self._assert_emits("_save_insights_now() MERGES with disk — use drop_keys to remove entries.")

    def test_read_before_edit(self):
        self._assert_emits("Read before Edit when modifying unfamiliar files to understand patterns.")

    def test_stale_lock(self):
        self._assert_emits("Stale .cognitive.lock can block saves — delete if process not running.")

    def test_additive_defaults(self):
        self._assert_emits("Use additive defaults to prevent multiplicative penalty crush on new insights.")

    def test_sql_injection(self):
        self._assert_emits("Use parameterized queries to prevent SQL injection in the database layer.")

    def test_git_force_push(self):
        self._assert_emits(
            "Don't use git push --force on shared branches — prefer --force-with-lease.",
            tool="Bash",
        )

    def test_connection_pool(self):
        self._assert_emits("Set connection pool max_size to 20 (not default 5) for production.")


# ═══════════════════════════════════════════════════════════════
# 6. TestDedup: deduplication behavior
# ═══════════════════════════════════════════════════════════════

class TestDedup:
    """Verify dedup/cooldown prevents repeated emissions."""

    def test_same_advice_id_shown_recently(self):
        state = _make_state(shown_advice_ids={"adv_dedup_001": time.time()})
        result = evaluate(
            [_MockAdvice(
                advice_id="adv_dedup_001",
                text="Use batch mode for saves.",
                confidence=0.80, context_match=0.75,
            )],
            state, "Edit",
        )
        assert len(result.emitted) == 0

    def test_same_advice_id_expired(self):
        state = _make_state(shown_advice_ids={"adv_dedup_002": 1000000000.0})
        result = evaluate(
            [_MockAdvice(
                advice_id="adv_dedup_002",
                text="Use batch mode for saves.",
                confidence=0.80, context_match=0.75,
            )],
            state, "Edit",
        )
        assert len(result.emitted) > 0

    def test_max_emit_limits_to_budget(self):
        # Dynamic budget: base MAX_EMIT_PER_CALL (2) + up to 2 bonus for
        # high-authority or high-confidence-spread items.  Hard cap = base + 2.
        from lib.advisory_gate import MAX_EMIT_PER_CALL

        items = [
            _MockAdvice(advice_id=f"adv_max_{i}", text=f"Advice item number {i} with enough text.",
                       confidence=0.80, context_match=0.75)
            for i in range(5)
        ]
        result = evaluate(items, None, "Edit")
        hard_cap = MAX_EMIT_PER_CALL + 2
        assert len(result.emitted) <= hard_cap, (
            f"Dynamic budget should cap at {hard_cap}, got {len(result.emitted)}"
        )
        # At least some items should be budget-suppressed
        budget_suppressed = [d for d in result.suppressed if "budget" in d.reason]
        assert len(budget_suppressed) > 0, "Some items should be budget-suppressed"

    def test_scope_key_shown_suppresses(self):
        # SessionState defaults to task_phase="exploration", so scope key
        # must match that. Set explicitly for clarity.
        state = _make_state(
            task_phase="implementation",
            shown_advice_ids={
                "adv_scope_001|edit|implementation": time.time(),
            },
        )
        result = evaluate(
            [_MockAdvice(
                advice_id="adv_scope_001",
                text="Check types carefully.",
                confidence=0.80, context_match=0.75,
            )],
            state, "Edit",
        )
        # The scope key matches tool=edit, phase=implementation
        assert len(result.emitted) == 0


# ═══════════════════════════════════════════════════════════════
# 7. TestSynthesisFormat: output format validation
# ═══════════════════════════════════════════════════════════════

class TestSynthesisFormat:
    """Verify synthesis output meets quality standards."""

    def test_note_has_spark_prefix(self):
        from lib.emitter import format_advisory
        text = format_advisory("Use batch mode for saves.", "note")
        assert text.startswith("[SPARK]"), f"NOTE should start with [SPARK], got: {text[:30]}"

    def test_warning_has_advisory_prefix(self):
        from lib.emitter import format_advisory
        text = format_advisory("Don't skip validation.", "warning")
        assert "[SPARK ADVISORY]" in text, f"WARNING should have [SPARK ADVISORY], got: {text[:30]}"

    def test_whisper_has_parenthetical(self):
        from lib.emitter import format_advisory
        text = format_advisory("Consider adding types.", "whisper")
        assert text.startswith("(spark:"), f"WHISPER should start with (spark:, got: {text[:30]}"

    def test_silent_produces_nothing(self):
        from lib.emitter import format_advisory
        text = format_advisory("This should be empty.", "silent")
        assert text == "", f"SILENT should produce empty string, got: {text[:30]}"

    def test_whisper_truncation(self):
        from lib.emitter import format_advisory
        long_text = "x" * 200
        text = format_advisory(long_text, "whisper")
        assert len(text) <= 160, f"WHISPER should truncate to ~150 chars, got {len(text)}"

    def test_programmatic_synthesis_not_empty(self):
        from lib.advisory_synthesizer import synthesize_programmatic
        items = [_MockAdvice(text="Use parameterized queries for safety.", confidence=0.80, context_match=0.75)]
        result = synthesize_programmatic(items, phase="implementation", tool_name="Edit")
        assert result and result.strip(), "Programmatic synthesis should produce non-empty output"

    def test_actionable_content_detection(self):
        assert _has_actionable_content("Check the file before proceeding.")
        assert _has_actionable_content("Use batch mode for saves.")
        assert _has_actionable_content("Avoid using eval() on input.")
        assert _has_actionable_content("Consider adding validation.")
        assert not _has_actionable_content("This pattern is commonly seen.")

    def test_negative_advisory_detection(self):
        assert _is_negative_advisory("Don't mutate arguments.")
        assert _is_negative_advisory("Avoid global state.")
        assert _is_negative_advisory("Never hardcode credentials.")
        assert not _is_negative_advisory("Use parameterized queries.")

    def test_caution_detection(self):
        assert _is_caution("[Caution] Check null values.")
        assert _is_caution("[Past Failure] Migration broke.")
        assert _is_caution("[Warning] Rate limit exceeded.")
        assert not _is_caution("Consider using batch mode.")
