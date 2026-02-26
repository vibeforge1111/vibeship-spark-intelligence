"""
Meta-Ralph Test Suite

Tests the quality gate for Spark's self-evolution.
Verifies cognitive vs operational classification and scoring accuracy.

Usage:
    python tests/test_meta_ralph.py
    pytest tests/test_meta_ralph.py -v
"""

import sys
import pytest
from pathlib import Path
from datetime import datetime, timedelta

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.meta_ralph import MetaRalph, RoastVerdict


@pytest.fixture(autouse=True)
def _isolate_meta_ralph(tmp_path, monkeypatch):
    """Redirect MetaRalph's persistent state to a temp directory so tests
    don't leak across runs or pick up stale roast history from ~/.spark/."""
    data_dir = tmp_path / "meta_ralph"
    monkeypatch.setattr(MetaRalph, "DATA_DIR", data_dir)
    monkeypatch.setattr(MetaRalph, "ROAST_HISTORY_FILE", data_dir / "roast_history.json")
    monkeypatch.setattr(MetaRalph, "OUTCOME_TRACKING_FILE", data_dir / "outcome_tracking.json")
    monkeypatch.setattr(MetaRalph, "LEARNINGS_STORE_FILE", data_dir / "learnings_store.json")
    monkeypatch.setattr(MetaRalph, "SELF_ROAST_FILE", data_dir / "self_roast.json")


def test_primitive_detection():
    """Test that primitive patterns are correctly rejected."""
    ralph = MetaRalph()

    primitives = [
        "Read task succeeded with Read tool",
        "Success rate: 95% over 1000 uses",
        "Pattern using Write.",
        "Bash → Edit sequence detected",
        "For shell tasks, use standard approach",
    ]

    passed = 0
    for text in primitives:
        result = ralph.roast(text, source="test")
        if result.verdict == RoastVerdict.PRIMITIVE:
            passed += 1
        else:
            print(f"FAIL: Expected PRIMITIVE for: {text[:50]}")
            print(f"  Got: {result.verdict.value} (score {result.score.total})")

    print(f"Primitive detection: {passed}/{len(primitives)} correct")
    assert passed == len(primitives), (
        f"expected {len(primitives)} primitive detections, got {passed}"
    )


def test_quality_detection():
    """Test that quality patterns are correctly passed."""
    ralph = MetaRalph()

    quality = [
        "User prefers dark theme because it reduces eye strain during late night sessions",
        "Remember this: always validate input before database operations",
        "I decided to use TypeScript instead of JavaScript for better type safety",
        "For authentication, use OAuth with PKCE because it prevents token interception",
        "The user corrected me - they want PostgreSQL, not MySQL",
    ]

    passed = 0
    for text in quality:
        result = ralph.roast(text, source="test")
        if result.verdict == RoastVerdict.QUALITY:
            passed += 1
        else:
            print(f"FAIL: Expected QUALITY for: {text[:50]}")
            print(f"  Got: {result.verdict.value} (score {result.score.total})")

    print(f"Quality detection: {passed}/{len(quality)} correct")
    assert passed == len(quality), (
        f"expected {len(quality)} quality detections, got {passed}"
    )


def test_scoring_dimensions():
    """Test individual scoring dimensions."""
    ralph = MetaRalph()

    # Test reasoning detection
    result = ralph.roast("Use X because Y", source="test")
    assert result.score.reasoning >= 1, f"Expected reasoning >= 1, got {result.score.reasoning}"

    # Test actionability
    result = ralph.roast("Always validate input", source="test")
    assert result.score.actionability >= 1, f"Expected actionability >= 1, got {result.score.actionability}"

    # Test that priority/remember signals boost novelty but don't bypass quality gates.
    # Vague "remember this" text without reasoning/action should NOT reach QUALITY.
    result = ralph.roast("Remember this: important project insight", source="test")
    assert result.score.novelty >= 1, f"Expected novelty >= 1 for remember signal, got {result.score.novelty}"
    # But a concrete "remember" with action SHOULD reach quality:
    result2 = ralph.roast("Remember this: always validate user input because SQL injection is real", source="test")
    assert result2.verdict == RoastVerdict.QUALITY, f"Expected QUALITY for concrete remember, got {result2.verdict.value}"

    print("Scoring dimensions: PASSED")


def test_duplicate_detection():
    """Test that duplicates are caught."""
    ralph = MetaRalph()

    text = "User prefers dark theme for better focus"
    ralph.roast(text, source="test")
    result2 = ralph.roast(text, source="test")

    assert result2.verdict == RoastVerdict.DUPLICATE, f"Expected DUPLICATE, got {result2.verdict.value}"
    print("Duplicate detection: PASSED")


def test_context_boost():
    """Test that context (importance_score, is_priority) boosts scoring."""
    ralph = MetaRalph()

    # Use text that won't trigger refinement (already has reasoning)
    text = "Consider this approach because it works well"

    # Without priority context
    result1 = ralph.roast(text, source="test", context={})

    # Same text with priority context - should boost novelty
    result2 = ralph.roast(text + " v2", source="test", context={"is_priority": True, "importance_score": 0.9})

    # Priority context should boost novelty score
    assert result2.score.novelty >= result1.score.novelty, "Priority context should boost novelty"
    # Both should pass as quality
    assert result1.verdict == RoastVerdict.QUALITY, "Base text should be quality"
    assert result2.verdict == RoastVerdict.QUALITY, "Priority text should be quality"
    print("Context boost: PASSED")


def test_alpha_scorer_is_primary(monkeypatch):
    """Alpha scorer is the primary Meta-Ralph scorer."""
    import lib.meta_ralph as mr

    def _legacy_low(_self, _learning, _context):
        return mr.QualityScore(
            actionability=0,
            novelty=0,
            reasoning=0,
            specificity=0,
            outcome_linked=0,
            ethics=0,
        )

    monkeypatch.setattr(mr.MetaRalph, "_score_learning", _legacy_low)
    monkeypatch.setattr(
        mr,
        "score_alpha_learning",
        lambda _learning, _context: {
            "actionability": 2,
            "novelty": 2,
            "reasoning": 2,
            "specificity": 2,
            "outcome_linked": 2,
            "ethics": 1,
        },
    )

    ralph = mr.MetaRalph()
    result = ralph.roast("User chose strict schema validation because malformed payloads broke deploys")

    assert result.verdict == mr.RoastVerdict.QUALITY
    assert isinstance(result.scoring, dict)
    assert result.scoring["primary"] == "alpha"
    assert isinstance(result.scoring.get("alpha"), dict)
    stats = ralph.get_stats()
    assert stats["alpha_scoring_runs"] >= 1


def test_alpha_scorer_uses_legacy_fallback_on_error(monkeypatch):
    """If alpha scorer errors, Meta-Ralph falls back to legacy scorer."""
    import lib.meta_ralph as mr

    def _legacy_low(_self, _learning, _context):
        return mr.QualityScore(
            actionability=0,
            novelty=0,
            reasoning=0,
            specificity=0,
            outcome_linked=0,
            ethics=0,
        )

    monkeypatch.setattr(mr.MetaRalph, "_score_learning", _legacy_low)
    monkeypatch.setattr(
        mr,
        "score_alpha_learning",
        lambda _learning, _context: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    ralph = mr.MetaRalph()
    result = ralph.roast("User chose strict schema validation because malformed payloads broke deploys")

    assert result.verdict == mr.RoastVerdict.PRIMITIVE
    assert isinstance(result.scoring, dict)
    assert result.scoring["primary"] == "legacy_fallback"
    assert isinstance(result.scoring.get("alpha"), dict)
    stats = ralph.get_stats()
    assert stats["legacy_fallback_runs"] >= 1


def test_stats():
    """Test that stats are tracked correctly."""
    ralph = MetaRalph()

    # Roast a few items
    ralph.roast("Primitive: Bash → Edit", source="test")
    ralph.roast("Quality because reasoning here", source="test")

    stats = ralph.get_stats()
    assert stats["total_roasted"] >= 2, f"Expected total_roasted >= 2, got {stats['total_roasted']}"
    assert "pass_rate" in stats, "Missing pass_rate in stats"

    print("Stats tracking: PASSED")


def test_quality_rate_window_filters_trace_churn_and_nonprod_prefixes():
    ralph = MetaRalph()
    ralph.roast_history = []

    for i in range(8):
        ralph.roast_history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "source": "user_prompt",
                "trace_id": f"bench-case-{i}",
                "result": {"verdict": "needs_work", "original": "scope:operation op:cinematic_creation"},
            }
        )

    for _ in range(8):
        ralph.roast_history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "source": "user_prompt",
                "trace_id": "live-heavy-trace",
                "result": {"verdict": "primitive", "original": "low quality sample"},
            }
        )

    for idx in range(2):
        ralph.roast_history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "source": "user_prompt",
                "trace_id": f"live-keep-{idx}",
                "result": {
                    "verdict": "quality",
                    "original": "Use schema validation because it prevents malformed payload regressions.",
                },
            }
        )

    stats = ralph.get_stats()
    assert stats["quality_rate_window_samples"] == 8
    assert stats["quality_rate"] == 0.25
    assert stats["quality_rate_window_filtered_trace_prefix"] >= 8
    assert stats["quality_rate_window_filtered_trace_churn"] >= 2


def test_outcome_stats_ignore_unknown_for_effectiveness():
    """Unknown outcomes should not dilute explicit good/bad effectiveness."""
    ralph = MetaRalph()

    # Retrievals create records.
    ralph.track_retrieval("a1", "advice one")
    ralph.track_retrieval("a2", "advice two")
    ralph.track_retrieval("a3", "advice three")

    ralph.track_outcome("a1", "good", "worked")
    ralph.track_outcome("a2", "bad", "failed")
    ralph.track_outcome("a3", "unknown", "unclear")

    stats = ralph.get_outcome_stats()
    assert stats["acted_on"] == 3
    assert stats["good_outcomes"] == 1
    assert stats["bad_outcomes"] == 1
    assert stats["unknown_outcomes"] == 1
    assert stats["with_outcome"] == 2
    assert stats["effectiveness_rate"] == 0.5


def test_outcome_stats_exclude_task_orchestration_records():
    """task-level orchestration cautions should not dilute acted-on rate."""
    ralph = MetaRalph()

    ralph.track_retrieval(
        "task_rec",
        "[Caution] I struggle with tool_0_error tasks",
        insight_key="tool:task",
        source="self_awareness",
    )
    ralph.track_retrieval("a1", "real advice", insight_key="reasoning:k1", source="semantic")
    ralph.track_outcome("task_rec", "bad", "task-level not actionable")
    ralph.track_outcome("a1", "good", "worked")

    stats = ralph.get_outcome_stats()
    assert stats["total_tracked"] == 2
    assert stats["actionable_tracked"] == 1
    assert stats["ignored_non_actionable"] == 1
    assert stats["acted_on_all"] == 2
    assert stats["acted_on"] == 1
    assert stats["with_outcome"] == 1
    assert stats["effectiveness_rate"] == 1.0


def test_outcome_retention_keeps_actionable_records():
    """Retention trimming should preserve actionable/acted-on records."""
    ralph = MetaRalph()
    ralph.begin_batch()
    for i in range(520):
        ralph.track_retrieval(
            f"task_{i}",
            "[Caution] I struggle with tool_0_error tasks",
            insight_key="tool:task",
            source="self_awareness",
        )

    ralph.track_retrieval("a1", "real actionable advice", insight_key="reasoning:key", source="semantic")
    ralph.track_outcome("a1", "good", "worked")
    ralph.end_batch()

    assert "a1" in ralph.outcome_records
    assert len(ralph.outcome_records) <= 500
    stats = ralph.get_outcome_stats()
    assert stats["acted_on"] >= 1
    assert stats["actionable_tracked"] >= 1


def test_outcome_save_merges_concurrent_writers():
    """A stale writer should merge disk outcomes instead of clobbering them."""
    stale_writer = MetaRalph()  # Loads initial empty state.

    fresh_writer = MetaRalph()
    fresh_writer.track_retrieval("a1", "first advice", insight_key="k1", source="semantic")
    fresh_writer.track_outcome("a1", "good", "worked")

    stale_writer.track_retrieval("a2", "second advice", insight_key="k2", source="cognitive")
    stale_writer.track_outcome("a2", "good", "worked")

    final_state = MetaRalph()
    assert "a1" in final_state.outcome_records
    assert "a2" in final_state.outcome_records
    stats = final_state.get_outcome_stats()
    assert stats["actionable_tracked"] >= 2
    assert stats["acted_on"] >= 2


def test_source_attribution_rollup():
    """Source attribution should roll up source -> action -> outcome correctly."""
    ralph = MetaRalph()

    ralph.track_retrieval("a1", "semantic guidance", source="semantic", insight_key="k1")
    ralph.track_retrieval("a2", "semantic guidance 2", source="semantic", insight_key="k2")
    ralph.track_retrieval("a3", "cognitive guidance", source="cognitive", insight_key="k3")
    ralph.track_retrieval(
        "task_skip",
        "[Caution] I struggle with tool_0_error tasks",
        source="self_awareness",
        insight_key="tool:task",
    )

    ralph.track_outcome("a1", "good", "tool=Bash success=True")
    ralph.track_outcome("a2", "bad", "tool=Edit success=False")
    ralph.track_outcome("a3", "neutral", "tool=Read success=True")
    ralph.track_outcome("task_skip", "good", "tool=Task success=True")

    attr = ralph.get_source_attribution(limit=10)
    assert attr["total_sources"] == 2
    assert attr["totals"]["retrieved"] == 3
    assert attr["totals"]["acted_on"] == 3
    assert attr["totals"]["good"] == 1
    assert attr["totals"]["bad"] == 1
    assert attr["totals"]["unknown"] == 1
    assert attr["totals"]["strict_acted_on"] == 0
    assert attr["totals"]["strict_with_explicit_outcome"] == 0
    assert attr["totals"]["strict_effectiveness_rate"] is None

    rows = {r["source"]: r for r in attr["rows"]}
    assert rows["semantic"]["retrieved"] == 2
    assert rows["semantic"]["acted_on"] == 2
    assert rows["semantic"]["good"] == 1
    assert rows["semantic"]["bad"] == 1
    assert rows["semantic"]["with_explicit_outcome"] == 2
    assert rows["semantic"]["effectiveness_rate"] == 0.5
    assert rows["semantic"]["top_tool"]["name"] in {"Bash", "Edit"}
    assert rows["semantic"]["strict_acted_on"] == 0
    assert rows["semantic"]["strict_effectiveness_rate"] is None

    assert rows["cognitive"]["retrieved"] == 1
    assert rows["cognitive"]["acted_on"] == 1
    assert rows["cognitive"]["with_explicit_outcome"] == 0
    assert rows["cognitive"]["effectiveness_rate"] is None


def test_source_attribution_strict_trace_window():
    """Strict attribution requires trace match within the configured window."""
    ralph = MetaRalph()

    # Strict match: same trace, within window.
    ralph.track_retrieval("s1", "semantic guidance", source="semantic", insight_key="k1", trace_id="t1")
    ralph.track_outcome("s1", "good", "tool=Bash success=True", trace_id="t1")

    # Trace mismatch: should be excluded from strict attribution.
    ralph.track_retrieval("s2", "semantic guidance", source="semantic", insight_key="k2", trace_id="t2")
    ralph.track_outcome("s2", "good", "tool=Bash success=True", trace_id="t2_mismatch")

    # Window miss: same trace but retrieval too old.
    ralph.track_retrieval("s3", "semantic guidance", source="semantic", insight_key="k3", trace_id="t3")
    ralph.outcome_records["s3"].retrieved_at = (datetime.now() - timedelta(hours=1)).isoformat()
    # Persist the synthetic retrieval time because track_outcome may reload state.
    ralph._save_state()
    ralph.track_outcome("s3", "good", "tool=Bash success=True", trace_id="t3")

    attr = ralph.get_source_attribution(limit=10, window_s=1200, require_trace=True)
    rows = {r["source"]: r for r in attr["rows"]}
    sem = rows["semantic"]

    assert attr["attribution_mode"]["window_s"] == 1200
    assert attr["attribution_mode"]["require_trace"] is True

    assert sem["retrieved"] == 3
    assert sem["acted_on"] == 3
    assert sem["good"] == 3

    assert sem["strict_acted_on"] == 1
    assert sem["strict_good"] == 1
    assert sem["strict_bad"] == 0
    assert sem["strict_with_explicit_outcome"] == 1
    assert sem["strict_effectiveness_rate"] == 1.0
    assert sem["strict_top_tool"]["name"] == "Bash"

    assert attr["totals"]["strict_acted_on"] == 1
    assert attr["totals"]["strict_with_explicit_outcome"] == 1
    assert attr["totals"]["strict_effectiveness_rate"] == 1.0


def test_insight_effectiveness_dual_gate_warmup_uses_weak_coverage(monkeypatch):
    """Before strict sample minimum, weak coverage should drive score (no early suppression)."""
    import lib.meta_ralph as mr

    monkeypatch.setattr(mr, "INSIGHT_WARMUP_WEAK_SAMPLES", 2)
    monkeypatch.setattr(mr, "INSIGHT_MIN_STRICT_SAMPLES", 3)
    monkeypatch.setattr(mr, "INSIGHT_STRICT_QUALITY_FLOOR", 0.6)

    ralph = mr.MetaRalph()
    # Two weak explicit outcomes with mismatched traces => strict samples remain 0.
    ralph.track_retrieval("w1", "advice", insight_key="k:warm", source="cognitive", trace_id="t1")
    ralph.track_outcome("w1", "good", "ok", trace_id="t1-mismatch")
    ralph.track_retrieval("w2", "advice", insight_key="k:warm", source="cognitive", trace_id="t2")
    ralph.track_outcome("w2", "bad", "nope", trace_id="t2-mismatch")

    score = ralph.get_insight_effectiveness("k:warm")
    assert score == 0.5  # weak_rate = 1/2


def test_insight_effectiveness_dual_gate_enforces_strict_floor(monkeypatch):
    """Once strict samples are sufficient and below floor, score should be suppressed."""
    import lib.meta_ralph as mr

    monkeypatch.setattr(mr, "INSIGHT_WARMUP_WEAK_SAMPLES", 2)
    monkeypatch.setattr(mr, "INSIGHT_MIN_STRICT_SAMPLES", 2)
    monkeypatch.setattr(mr, "INSIGHT_STRICT_QUALITY_FLOOR", 0.75)
    monkeypatch.setattr(mr, "INSIGHT_SUPPRESSION_RETEST_AFTER_S", 999999)

    ralph = mr.MetaRalph()
    ralph.track_retrieval("s1", "advice", insight_key="k:strict", source="cognitive", trace_id="ts1")
    ralph.track_outcome("s1", "bad", "nope", trace_id="ts1")
    ralph.track_retrieval("s2", "advice", insight_key="k:strict", source="cognitive", trace_id="ts2")
    ralph.track_outcome("s2", "bad", "nope", trace_id="ts2")

    score = ralph.get_insight_effectiveness("k:strict")
    assert score < 0.2


def test_insight_effectiveness_retest_after_cooldown(monkeypatch):
    """Stale low-quality strict evidence should reopen for re-test (not hard-suppressed forever)."""
    import lib.meta_ralph as mr

    monkeypatch.setattr(mr, "INSIGHT_WARMUP_WEAK_SAMPLES", 2)
    monkeypatch.setattr(mr, "INSIGHT_MIN_STRICT_SAMPLES", 2)
    monkeypatch.setattr(mr, "INSIGHT_STRICT_QUALITY_FLOOR", 0.8)
    monkeypatch.setattr(mr, "INSIGHT_SUPPRESSION_RETEST_AFTER_S", 60)

    ralph = mr.MetaRalph()
    ralph.track_retrieval("r1", "advice", insight_key="k:retest", source="cognitive", trace_id="tr1")
    ralph.track_outcome("r1", "bad", "nope", trace_id="tr1")
    ralph.track_retrieval("r2", "advice", insight_key="k:retest", source="cognitive", trace_id="tr2")
    ralph.track_outcome("r2", "bad", "nope", trace_id="tr2")

    # Age strict outcomes beyond retest window.
    old = (datetime.now() - timedelta(minutes=5)).isoformat()
    ralph.outcome_records["r1"].outcome_at = old
    ralph.outcome_records["r2"].outcome_at = old

    score = ralph.get_insight_effectiveness("k:retest")
    assert score >= 0.5


def run_all_tests():
    """Run all tests and report results."""
    print("=" * 60)
    print(" META-RALPH TEST SUITE")
    print("=" * 60)
    print()

    tests = [
        ("Primitive Detection", test_primitive_detection),
        ("Quality Detection", test_quality_detection),
        ("Scoring Dimensions", test_scoring_dimensions),
        ("Duplicate Detection", test_duplicate_detection),
        ("Context Boost", test_context_boost),
        ("Stats Tracking", test_stats),
        ("Outcome Stats", test_outcome_stats_ignore_unknown_for_effectiveness),
        ("Actionable Outcome Stats", test_outcome_stats_exclude_task_orchestration_records),
        ("Outcome Retention", test_outcome_retention_keeps_actionable_records),
        ("Source Attribution", test_source_attribution_rollup),
        ("Strict Attribution", test_source_attribution_strict_trace_window),
        ("Dual Gate Warmup", test_insight_effectiveness_dual_gate_warmup_uses_weak_coverage),
        ("Dual Gate Strict Floor", test_insight_effectiveness_dual_gate_enforces_strict_floor),
        ("Dual Gate Retest", test_insight_effectiveness_retest_after_cooldown),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"ASSERTION FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f" RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
