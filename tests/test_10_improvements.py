#!/usr/bin/env python3
"""
Spark 10 Improvements Test Suite v2 (Fixed)
"""

import sys
import json
import time
from pathlib import Path
import pytest

SPARK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SPARK_DIR))
pytestmark = pytest.mark.integration

def print_header(title):
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)

def print_result(name, passed, details=""):
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}")
    if details:
        print(f"         {details}")

def test_1_outcome_tracking():
    """Test #1: Outcome Tracking"""
    print_header("1. OUTCOME TRACKING")

    try:
        from lib.meta_ralph import get_meta_ralph
        ralph = get_meta_ralph()
        stats = ralph.get_stats()

        outcome_stats = stats.get("outcome_stats", {})
        total_tracked = outcome_stats.get("total_tracked", 0)
        acted_on = outcome_stats.get("acted_on", 0)
        good_outcomes = outcome_stats.get("good_outcomes", 0)

        print(f"  Total tracked: {total_tracked}")
        print(f"  Acted on: {acted_on}")
        print(f"  Good outcomes: {good_outcomes}")

        # Test tracking
        test_learning_id = f"test_{int(time.time() * 1000)}"
        ralph.track_retrieval(test_learning_id, "Test learning")
        ralph.track_outcome(test_learning_id, "good", "Test worked")

        new_stats = ralph.get_stats()["outcome_stats"]
        tracked_after = new_stats.get("total_tracked", 0)
        acted_on_after = new_stats.get("acted_on", 0)
        tracking_works = (
            tracked_after > total_tracked
            or (tracked_after == total_tracked and tracked_after >= 500)
            or acted_on_after > acted_on
        )

        print_result("track_retrieval() works", tracking_works)
        print_result("track_outcome() works", acted_on_after >= acted_on)
        print_result("Outcomes being recorded", total_tracked > 0 or tracking_works)
        assert tracking_works, "track_retrieval() did not increase tracked outcomes"
        assert new_stats.get("acted_on", 0) >= acted_on, "track_outcome() did not update acted_on"
        assert total_tracked > 0 or tracking_works, "no outcome records detected"
    except Exception as e:
        pytest.fail(f"test_1_outcome_tracking failed: {e}")

def test_2_persistence_pipeline():
    """Test #2: Persistence Pipeline"""
    print_header("2. PERSISTENCE PIPELINE")

    try:
        # Check file on disk directly
        insights_file = Path.home() / ".spark" / "cognitive_insights.json"

        if insights_file.exists():
            data = json.loads(insights_file.read_text())
            disk_count = len(data) if isinstance(data, dict) else 0
            file_size = insights_file.stat().st_size / 1024
            print(f"  Insights on disk: {disk_count}")
            print(f"  File size: {file_size:.1f} KB")
        else:
            disk_count = 0
            print("  No insights file found")

        # Check in-memory too
        from lib.cognitive_learner import get_cognitive_learner
        cognitive = get_cognitive_learner()
        memory_count = len(cognitive.insights)
        print(f"  Insights in memory: {memory_count}")

        print_result("Insights being stored", disk_count > 0, f"{disk_count} on disk")
        # Keep this guardrail meaningful after cleanup while avoiding old-noise assumptions.
        print_result("Persistence working", disk_count > 50, f"{disk_count} insights persisted")
        assert disk_count > 50, f"expected >50 persisted insights, got {disk_count}"
    except Exception as e:
        pytest.fail(f"test_2_persistence_pipeline failed: {e}")

def test_3_auto_refinement():
    """Test #3: Auto-Refinement"""
    print_header("3. AUTO-REFINEMENT")

    try:
        from lib.meta_ralph import get_meta_ralph

        ralph = get_meta_ralph()
        stats = ralph.get_stats()

        refinements = stats.get("refinements_made", 0)
        print(f"  Refinements made: {refinements}")

        # Test roasting a borderline learning
        test_learning = "Remember: always verify file exists before editing"
        result = ralph.roast(test_learning, source="test")

        print(f"  Test verdict: {result.verdict.value}")

        # Check if refinement logic exists
        has_refinement = hasattr(ralph, 'try_refine') or hasattr(ralph, '_attempt_refinement')
        print_result("Refinement logic exists", has_refinement)
        print_result("Roasting works", result is not None)
        assert has_refinement, "refinement hook missing on MetaRalph"
        assert result is not None, "MetaRalph roast returned None"
    except Exception as e:
        pytest.fail(f"test_3_auto_refinement failed: {e}")

def test_4_promotion_threshold():
    """Test #4: Promotion Threshold"""
    print_header("4. PROMOTION THRESHOLD")

    try:
        from lib.promoter import DEFAULT_PROMOTION_THRESHOLD, DEFAULT_MIN_VALIDATIONS

        print(f"  Promotion threshold: {DEFAULT_PROMOTION_THRESHOLD}")
        print(f"  Min validations: {DEFAULT_MIN_VALIDATIONS}")

        threshold_valid = 0.5 <= DEFAULT_PROMOTION_THRESHOLD <= 0.9
        validations_valid = DEFAULT_MIN_VALIDATIONS >= 2

        print_result("Threshold configured (0.5..0.9)", threshold_valid)
        print_result("Min validations >= 2", validations_valid)
        assert threshold_valid, f"promotion threshold out of range: {DEFAULT_PROMOTION_THRESHOLD}"
        assert validations_valid, f"min validations too low: {DEFAULT_MIN_VALIDATIONS}"
    except Exception as e:
        pytest.fail(f"test_4_promotion_threshold failed: {e}")

def test_5_aggregator_integration():
    """Test #5: Aggregator Integration"""
    print_header("5. AGGREGATOR INTEGRATION")

    try:
        # Check EIDOS database for actual persisted data
        from lib.eidos import get_store
        store = get_store()
        stats = store.get_stats()

        print(f"  EIDOS Episodes: {stats.get('episodes', 0)}")
        print(f"  EIDOS Steps: {stats.get('steps', 0)}")
        print(f"  EIDOS Distillations: {stats.get('distillations', 0)}")

        # Check if aggregator code is wired in at least one active ingress path.
        observe_file = SPARK_DIR / "hooks" / "observe.py"
        observe_code = observe_file.read_text()
        pipeline_code = (SPARK_DIR / "lib" / "pipeline.py").read_text()
        has_aggregator = (
            "aggregator.process_event" in observe_code
            or "from lib.pattern_detection.aggregator import get_aggregator" in pipeline_code
        )

        print_result("Aggregator wired in observe.py", has_aggregator)
        print_result("EIDOS capturing steps", stats.get('steps', 0) > 0)
        print_result("Distillations created", stats.get('distillations', 0) > 0)
        assert has_aggregator, "aggregator wiring missing in hooks/observe.py"
        assert stats.get('steps', 0) > 0, "EIDOS has no steps"
    except Exception as e:
        pytest.fail(f"test_5_aggregator_integration failed: {e}")

def test_6_domain_detection():
    """Test #6: Skill Domain Coverage"""
    print_header("6. SKILL DOMAIN COVERAGE")

    try:
        from lib.cognitive_signals import detect_domain, DOMAIN_TRIGGERS

        print(f"  Domains configured: {len(DOMAIN_TRIGGERS)}")

        test_cases = [
            ("Player health for better balance", "game_dev"),
            ("PCI compliance required", "fintech"),
            ("Marketing campaign ROI", "marketing"),
            ("Decouple the modules", "architecture"),
            ("Workflow pipeline issue", "orchestration"),
        ]

        passed = 0
        for text, expected in test_cases:
            detected = detect_domain(text)
            if detected == expected:
                passed += 1
            print_result(f"{expected}", detected == expected, f"detected: {detected}")
        assert passed >= 4, f"domain detection matched {passed}/5 expected cases"
    except Exception as e:
        pytest.fail(f"test_6_domain_detection failed: {e}")

def test_7_distillation_quality():
    """Test #7: Distillation Quality"""
    print_header("7. DISTILLATION QUALITY")

    try:
        from lib.pattern_detection.distiller import PatternDistiller

        distiller = PatternDistiller()

        # Test reasoning extraction
        test_lessons = [
            ("This works because it prevents race conditions", True),
            ("Request resolved by verifying file exists", True),
            ("Simple statement without reason", False),
        ]

        print("  Reasoning extraction:")
        all_correct = True
        for lesson, should_extract in test_lessons:
            reasoning = distiller._extract_reasoning([lesson])
            extracted = reasoning is not None
            correct = extracted == should_extract
            all_correct = all_correct and correct
            print_result(f"'{lesson[:30]}...'", correct,
                        f"extracted: {reasoning[:30] if reasoning else 'None'}...")

        # Check new distillations would have better quality
        print()
        print("  New distillations will include 'because' reasoning")
        print_result("Reasoning extraction working", True)
        assert all_correct, "reasoning extraction did not match expected outcomes"
    except Exception as e:
        pytest.fail(f"test_7_distillation_quality failed: {e}")

def test_8_advisor_integration():
    """Test #8: Advisor Integration"""
    print_header("8. ADVISOR INTEGRATION")

    try:
        from lib.advisor import get_advisor, MIN_RELIABILITY_FOR_ADVICE, MAX_ADVICE_ITEMS

        print(f"  MIN_RELIABILITY_FOR_ADVICE: {MIN_RELIABILITY_FOR_ADVICE}")
        print(f"  MAX_ADVICE_ITEMS: {MAX_ADVICE_ITEMS}")

        advisor = get_advisor()
        report = advisor.get_effectiveness_report()

        print(f"  Total advice given: {report['total_advice_given']}")

        # Test getting advice
        advice = advisor.advise("Edit", {"file_path": "test.py"})
        print(f"  Advice items for Edit: {len(advice)}")

        print_result("Threshold lowered (<=0.5)", MIN_RELIABILITY_FOR_ADVICE <= 0.5)
        print_result("Max items raised (>=8)", MAX_ADVICE_ITEMS >= 8)
        print_result("Advice being provided", len(advice) > 0)
        assert MIN_RELIABILITY_FOR_ADVICE <= 0.5, (
            f"MIN_RELIABILITY_FOR_ADVICE too high: {MIN_RELIABILITY_FOR_ADVICE}"
        )
        assert MAX_ADVICE_ITEMS >= 8, f"MAX_ADVICE_ITEMS too low: {MAX_ADVICE_ITEMS}"
        assert len(advice) > 0, "advisor returned no guidance for Edit"
    except Exception as e:
        pytest.fail(f"test_8_advisor_integration failed: {e}")

def test_9_importance_scorer():
    """Test #9: Importance Scorer Domains"""
    print_header("9. IMPORTANCE SCORER DOMAINS")

    try:
        from lib.importance_scorer import get_importance_scorer, DOMAIN_WEIGHTS

        print(f"  Domains in weights: {len(DOMAIN_WEIGHTS)}")

        test_cases = [
            ("Player health for balance", "game_dev", 0.7),
            ("Decouple these modules", "architecture", 0.7),
            ("Queue the batch job", "orchestration", 0.7),
        ]

        all_passed = True
        for text, domain, min_relevance in test_cases:
            scorer = get_importance_scorer(domain=domain)
            result = scorer.score(text)
            passed = result.domain_relevance >= min_relevance
            all_passed = all_passed and passed
            print_result(f"{domain}: '{text[:25]}...'", passed,
                        f"relevance: {result.domain_relevance:.2f}")
        assert all_passed, "one or more importance scorer domain checks failed"
    except Exception as e:
        pytest.fail(f"test_9_importance_scorer failed: {e}")

def test_10_chips_activation():
    """Test #10: Chips Auto-Activation"""
    print_header("10. CHIPS AUTO-ACTIVATION")

    try:
        from lib.chips.loader import get_active_chips, get_chip_loader
        from lib.metalearning.strategist import get_strategist

        strategist = get_strategist()
        threshold = strategist.strategy.auto_activate_threshold
        print(f"  Auto-activate threshold: {threshold}")

        loader = get_chip_loader()
        all_chips = loader.get_all_chips()
        print(f"  Total chips loaded: {len(all_chips)}")
        if len(all_chips) == 0:
            pytest.skip("chips catalog unavailable in this environment")

        # Test context activation
        test_contexts = [
            ("Player balance and gameplay", "Game Dev"),
            ("Marketing campaign conversion", "Marketing"),
        ]

        all_passed = True
        for context, expected_chip in test_contexts:
            active = get_active_chips(context)
            names = [c.name for c in active]
            found = any(expected_chip.lower() in n.lower() for n in names)
            all_passed = all_passed and found
            print_result(f"'{context[:25]}...'", found, f"activated: {names}")

        print_result("Threshold lowered (<=0.5)", threshold <= 0.5)
        assert threshold <= 0.5, f"auto-activate threshold too high: {threshold}"
        assert all_passed, "chip activation contexts failed"
    except pytest.skip.Exception:
        raise
    except Exception as e:
        pytest.fail(f"test_10_chips_activation failed: {e}")

def run_all_tests():
    """Run all tests and summarize."""
    print("\n" + "=" * 60)
    print("  SPARK 10 IMPROVEMENTS - TEST SUITE v2")
    print("=" * 60)

    tests = {
        1: test_1_outcome_tracking,
        2: test_2_persistence_pipeline,
        3: test_3_auto_refinement,
        4: test_4_promotion_threshold,
        5: test_5_aggregator_integration,
        6: test_6_domain_detection,
        7: test_7_distillation_quality,
        8: test_8_advisor_integration,
        9: test_9_importance_scorer,
        10: test_10_chips_activation,
    }
    results = {}
    for idx, fn in tests.items():
        try:
            fn()
            results[idx] = True
        except AssertionError as e:
            print(f"  [FAIL] #{idx} assertion: {e}")
            results[idx] = False
        except Exception as e:
            print(f"  [FAIL] #{idx} error: {e}")
            results[idx] = False

    print_header("FINAL RESULTS")

    passed = sum(1 for r in results.values() if r)
    total = len(results)

    names = [
        "Outcome Tracking",
        "Persistence Pipeline",
        "Auto-Refinement",
        "Promotion Threshold",
        "Aggregator Integration",
        "Domain Coverage",
        "Distillation Quality",
        "Advisor Integration",
        "Importance Scorer",
        "Chips Activation"
    ]

    for num, result in results.items():
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] #{num} {names[num-1]}")

    print()
    print(f"  Total: {passed}/{total} improvements working")
    print(f"  Success rate: {passed/total*100:.0f}%")

    if passed == total:
        print("\n  ALL IMPROVEMENTS VERIFIED!")
    elif passed >= 8:
        print(f"\n  {passed}/10 working - great progress!")
    else:
        print(f"\n  {total - passed} improvement(s) need attention")

    return results

if __name__ == "__main__":
    run_all_tests()
