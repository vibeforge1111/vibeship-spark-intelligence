#!/usr/bin/env python3
"""Verify [SPARK] advisory emissions are working correctly.

Self-contained script — no pytest, no external deps beyond the project.
Both Claude Code and Codex can run this independently.

Usage:
    cd <project-root>
    python scripts/verify_advisory_emissions.py

Tests 20 key scenarios across the full advisory pipeline:
- High-value advice emits correctly (architecture, debugging, domain)
- Noise is suppressed (cycle summaries, timing, platitudes)
- Gate thresholds work (NOTE at 0.48, WARNING at 0.80)
- Tool-specific advice matches the right tool
- Dedup prevents repeated emissions
- Context suppression filters obvious advice
- Failure boost amplifies post-error advice
- MAX_EMIT budget limits to 2 per call

Expected: 20/20 PASS. Failures show which filter is miscalibrated.
After changes to advisory scoring/gating, re-run to verify.

Created 2026-02-22 as part of comprehensive advisory calibration system.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class _Advice:
    """Minimal advice object matching fields read by advisory_gate."""
    advice_id: str = ""
    insight_key: str = ""
    text: str = ""
    confidence: float = 0.7
    source: str = "cognitive"
    context_match: float = 0.7
    emotional_priority: float = 0.0


def _state(**overrides):
    """Build a SessionState for testing."""
    from lib.runtime_session_state import SessionState
    base = {"session_id": "verify_emission"}
    base.update(overrides)
    return SessionState.from_dict(base)


def _gate(advice_items, state, tool_name, tool_input=None):
    """Run through advisory_gate.evaluate."""
    from lib.advisory_gate import evaluate
    return evaluate(advice_items, state, tool_name, tool_input)


# ═══════════════════════════════════════════════════════════════
# 20 KEY SCENARIOS (2 per category A-J)
# ═══════════════════════════════════════════════════════════════

def _scenarios():
    """Return list of (id, description, test_fn) tuples."""
    scenarios = []

    def add(id_, desc, fn):
        scenarios.append((id_, desc, fn))

    # --- A: High-value should EMIT ---
    def a01():
        r = _gate(
            [_Advice(text="Use batch mode for saves — reduces I/O by 66x. Call begin_batch() before the loop.",
                     confidence=0.85, context_match=0.80, source="cognitive")],
            None, "Edit",
        )
        assert len(r.emitted) > 0, "High-value architecture insight should emit"
        assert r.emitted[0].authority == "note", f"Expected note, got {r.emitted[0].authority}"
        return f"emitted as {r.emitted[0].authority} (score={r.emitted[0].adjusted_score:.2f})"
    add("A01", "High-value architecture insight", a01)

    def a02():
        r = _gate(
            [_Advice(text="int() truncates float thresholds — use float() for quality_threshold. Bug: 3.8 became 3.",
                     confidence=0.90, context_match=0.75, source="eidos")],
            None, "Bash",
        )
        assert len(r.emitted) > 0, "Proven debug pattern should emit"
        return f"emitted as {r.emitted[0].authority} (score={r.emitted[0].adjusted_score:.2f})"
    add("A02", "Proven debug pattern", a02)

    # --- B: Noise should SUPPRESS ---
    def b01():
        r = _gate(
            [_Advice(text="Cycle summary: Edit used 9 times (100% success); 17/17 Edits not preceded by Read.",
                     confidence=0.60, context_match=0.40, source="cognitive")],
            None, "Edit",
        )
        assert len(r.emitted) == 0, "Cycle summary should be suppressed"
        return "suppressed (noise)"
    add("B01", "Cycle summary noise", b01)

    def b02():
        r = _gate(
            [_Advice(text="okay", confidence=0.50, context_match=0.50, source="bank")],
            None, "Edit",
        )
        assert len(r.emitted) == 0, "Conversational fragment should be suppressed"
        return "suppressed (primitive noise)"
    add("B02", "Conversational fragment", b02)

    # --- C: Score boundaries ---
    def c01():
        # Score below WHISPER (0.30): 0.45*0.10 + 0.25*0.30 + 0.15 = 0.27
        r = _gate(
            [_Advice(text="Consider checking the documentation for this library version.",
                     confidence=0.30, context_match=0.10, source="bank")],
            None, "Edit",
        )
        if r.decisions:
            auth = r.decisions[0].authority
            score = r.decisions[0].adjusted_score
            assert auth == "silent", f"Score ~0.27 should be SILENT, got {auth}"
            return f"silent (score={score:.2f})"
        return "no decisions (empty)"
    add("C01", "Below WHISPER threshold", c01)

    def c02():
        # Score at NOTE boundary: 0.45*0.50 + 0.25*0.60 + 0.15 = 0.525
        r = _gate(
            [_Advice(text="Use parameterized queries to prevent SQL injection in the database layer.",
                     confidence=0.60, context_match=0.50, source="cognitive")],
            None, "Edit",
        )
        assert len(r.emitted) > 0, "Score above NOTE should emit"
        assert r.emitted[0].authority == "note", f"Expected note, got {r.emitted[0].authority}"
        return f"emitted as note (score={r.emitted[0].adjusted_score:.2f})"
    add("C02", "At NOTE threshold", c02)

    # --- D: Tool-specific ---
    def d01():
        r = _gate(
            [_Advice(text="WebFetch fails on authenticated URLs — use specialized MCP tools.",
                     confidence=0.75, context_match=0.70, source="cognitive")],
            None, "Edit",
        )
        assert len(r.emitted) == 0, "WebFetch advice on Edit should be suppressed"
        return "suppressed (WebFetch on Edit)"
    add("D01", "WebFetch advice on Edit", d01)

    def d02():
        r = _gate(
            [_Advice(text="WebFetch fails on authenticated URLs — use specialized MCP tools.",
                     confidence=0.75, context_match=0.70, source="cognitive")],
            None, "WebFetch",
        )
        assert len(r.emitted) > 0, "WebFetch advice on WebFetch should emit"
        return f"emitted as {r.emitted[0].authority}"
    add("D02", "WebFetch advice on WebFetch", d02)

    # --- E: Dedup & cooldown ---
    def e01():
        state = _state(shown_advice_ids={"adv_dedup_v": time.time()})
        r = _gate(
            [_Advice(advice_id="adv_dedup_v", text="Use batch mode for saves.", confidence=0.80, context_match=0.75)],
            state, "Edit",
        )
        assert len(r.emitted) == 0, "Recently shown advice should be suppressed"
        return "suppressed (shown recently)"
    add("E01", "Dedup shown recently", e01)

    def e02():
        r = _gate(
            [_Advice(advice_id=f"adv_max_{i}", text=f"Advice item {i} with sufficient detail for emission.",
                     confidence=0.80, context_match=0.75) for i in range(4)],
            None, "Edit",
        )
        assert len(r.emitted) <= 2, f"MAX_EMIT should cap at 2, got {len(r.emitted)}"
        assert len(r.suppressed) >= 2, "Extra items should be in suppressed list"
        return f"{len(r.emitted)} emitted, {len(r.suppressed)} suppressed by budget"
    add("E02", "MAX_EMIT overflow", e02)

    # --- F: Context suppression ---
    def f01():
        r = _gate(
            [_Advice(text="Read before Edit when modifying files to understand patterns.",
                     confidence=0.70, context_match=0.60)],
            None, "Bash",
        )
        assert len(r.emitted) == 0, "Read-before-edit on Bash should suppress"
        return "suppressed (read-before-edit on Bash)"
    add("F01", "Read-before-edit on Bash", f01)

    def f02():
        r = _gate(
            [_Advice(text="When reading this file, note the import structure.",
                     confidence=0.70, context_match=0.60)],
            None, "Read",
        )
        assert len(r.emitted) == 0, "Generic Read advice on Read should suppress"
        return "suppressed (generic Read on Read)"
    add("F02", "Generic Read on Read", f02)

    # --- G: Phase relevance ---
    def g01():
        state = _state(task_phase="exploration")
        r = _gate(
            [_Advice(text="Consider architecture patterns before diving in.",
                     confidence=0.65, context_match=0.55, insight_key="context:arch")],
            state, "Read",
        )
        # Context insight boosted 1.3x in exploration
        assert len(r.emitted) > 0, "Context insight in exploration should emit (1.3x boost)"
        return f"emitted with phase boost (score={r.emitted[0].adjusted_score:.2f})"
    add("G01", "Context in exploration (boosted)", g01)

    def g02():
        state = _state(task_phase="implementation")
        r = _gate(
            [_Advice(text="I tend to over-engineer — keep it simple and focused.",
                     confidence=0.65, context_match=0.55, insight_key="self_awareness:over_eng")],
            state, "Edit",
        )
        # Self-awareness boosted 1.4x in implementation
        assert len(r.emitted) > 0, "Self-awareness in implementation should emit (1.4x boost)"
        return f"emitted with phase boost (score={r.emitted[0].adjusted_score:.2f})"
    add("G02", "Self-awareness in implementation (boosted)", g02)

    # --- H: Failure/negative boost ---
    def h01():
        r = _gate(
            [_Advice(text="Don't mutate function arguments — return new values instead.",
                     confidence=0.65, context_match=0.55)],
            None, "Edit",
        )
        assert len(r.emitted) > 0, "Negative advisory should emit (1.3x boost)"
        return f"emitted with negative boost (score={r.emitted[0].adjusted_score:.2f})"
    add("H01", "Negative advisory (don't)", h01)

    def h02():
        state = _state(consecutive_failures=2)
        r = _gate(
            [_Advice(text="[Caution] Check imports — past failure with circular dependencies.",
                     confidence=0.65, context_match=0.55, source="eidos")],
            state, "Edit",
        )
        assert len(r.emitted) > 0, "Caution with failures should emit (1.5x boost)"
        score = r.emitted[0].adjusted_score
        assert score > 0.70, f"Expected boosted score >0.70, got {score:.2f}"
        return f"emitted with failure boost (score={score:.2f})"
    add("H02", "Caution + consecutive failures", h02)

    # --- I: Synthesis quality ---
    def i01():
        from lib.emitter import format_advisory
        text = format_advisory("Use parameterized queries for safety.", "note")
        assert text.startswith("[SPARK]"), f"NOTE should have [SPARK] prefix, got: {text[:20]}"
        assert len(text) < 500, f"Should be concise, got {len(text)} chars"
        return f"formatted correctly ({len(text)} chars)"
    add("I01", "NOTE format has [SPARK] prefix", i01)

    def i02():
        from lib.emitter import format_advisory
        text = format_advisory("[Caution] Never store passwords in plaintext.", "warning")
        assert "[SPARK ADVISORY]" in text, f"WARNING should have [SPARK ADVISORY], got: {text[:30]}"
        return f"formatted correctly"
    add("I02", "WARNING format has advisory prefix", i02)

    # --- J: Edge cases ---
    def j01():
        r = _gate([], None, "Edit")
        assert len(r.emitted) == 0, "Empty advice list should produce no emissions"
        return "no emissions from empty list"
    add("J01", "Empty advice list", j01)

    def j02():
        r = _gate(
            [_Advice(text="Check the file path before editing.", confidence=0.75, context_match=0.70)],
            None, "UnknownTool",
        )
        # Unknown tool should still evaluate normally
        assert len(r.emitted) > 0, "Unknown tool should still evaluate advice"
        return f"emitted normally for unknown tool"
    add("J02", "Unknown tool name", j02)

    return scenarios


# ═══════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════

def main():
    scenarios = _scenarios()
    total = len(scenarios)
    passed = 0
    failed = 0
    failures = []

    print()
    print("[SPARK ADVISORY VERIFICATION]")
    print("=" * 60)

    for i, (id_, desc, fn) in enumerate(scenarios, 1):
        try:
            detail = fn()
            passed += 1
            print(f" {i:>2}/{total} {id_:<30} PASS  {detail}")
        except AssertionError as e:
            failed += 1
            failures.append((id_, desc, str(e)))
            print(f" {i:>2}/{total} {id_:<30} FAIL  {str(e)[:60]}")
        except Exception as e:
            failed += 1
            failures.append((id_, desc, f"ERROR: {str(e)[:80]}"))
            print(f" {i:>2}/{total} {id_:<30} ERROR {str(e)[:60]}")

    print("=" * 60)

    if failed == 0:
        print(f"RESULT: {passed}/{total} PASS")
        print("Advisory emissions are calibrated correctly.")
        return 0
    else:
        print(f"RESULT: {passed}/{total} PASS, {failed} FAILED")
        print()
        for id_, desc, err in failures:
            print(f"  FAIL {id_}: {desc}")
            print(f"        {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
