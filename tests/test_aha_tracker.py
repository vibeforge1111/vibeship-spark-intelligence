"""Tests for lib/aha_tracker.py — capture and analyze surprising moments."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

import lib.aha_tracker as aha_mod
from lib.aha_tracker import (
    AhaMoment,
    AhaTracker,
    SurpriseType,
    dedupe_aha_moments,
    get_aha_tracker,
    maybe_capture_surprise,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_aha_file(tmp_path, monkeypatch):
    """Redirect AHA_FILE and SPARK_DIR to tmp_path so tests don't touch ~/.spark."""
    spark_dir = tmp_path / ".spark"
    aha_file = spark_dir / "aha_moments.json"
    monkeypatch.setattr(aha_mod, "SPARK_DIR", spark_dir)
    monkeypatch.setattr(aha_mod, "AHA_FILE", aha_file)
    yield spark_dir


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    """Reset the module-level singleton before each test."""
    monkeypatch.setattr(aha_mod, "_tracker", None)
    yield
    monkeypatch.setattr(aha_mod, "_tracker", None)


def _fresh_tracker() -> AhaTracker:
    return AhaTracker()


def _capture(tracker: AhaTracker, **kwargs) -> AhaMoment:
    defaults = dict(
        surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
        predicted="failure",
        actual="success",
        confidence_gap=0.8,
        context={"tool": "Bash"},
        lesson=None,
        auto_surface=False,
    )
    defaults.update(kwargs)
    return tracker.capture_surprise(**defaults)


# ---------------------------------------------------------------------------
# SurpriseType enum
# ---------------------------------------------------------------------------

class TestSurpriseType:
    def test_all_six_types_exist(self):
        values = {st.value for st in SurpriseType}
        assert values == {
            "unexpected_success",
            "unexpected_failure",
            "faster_than_expected",
            "slower_than_expected",
            "different_path",
            "recovery_success",
        }

    def test_types_are_unique(self):
        vals = [st.value for st in SurpriseType]
        assert len(vals) == len(set(vals))


# ---------------------------------------------------------------------------
# AhaMoment.format_visible
# ---------------------------------------------------------------------------

class TestAhaMomentFormatVisible:
    def _moment(self, **kwargs) -> AhaMoment:
        defaults = dict(
            id="abc123",
            timestamp=1000.0,
            surprise_type="unexpected_success",
            predicted_outcome="failure",
            actual_outcome="success",
            confidence_gap=0.8,
            context={"tool": "Bash"},
            lesson_extracted=None,
            importance=0.8,
            occurrences=1,
        )
        defaults.update(kwargs)
        return AhaMoment(**defaults)

    def test_contains_emoji(self):
        txt = self._moment(surprise_type="unexpected_success").format_visible()
        assert "🎉" in txt

    def test_unexpected_failure_emoji(self):
        txt = self._moment(surprise_type="unexpected_failure").format_visible()
        assert "😮" in txt

    def test_faster_emoji(self):
        txt = self._moment(surprise_type="faster_than_expected").format_visible()
        assert "⚡" in txt

    def test_slower_emoji(self):
        txt = self._moment(surprise_type="slower_than_expected").format_visible()
        assert "🐢" in txt

    def test_different_path_emoji(self):
        txt = self._moment(surprise_type="different_path").format_visible()
        assert "🔀" in txt

    def test_recovery_success_emoji(self):
        txt = self._moment(surprise_type="recovery_success").format_visible()
        assert "💪" in txt

    def test_unknown_type_uses_bulb_emoji(self):
        txt = self._moment(surprise_type="mystery_type").format_visible()
        assert "💡" in txt

    def test_contains_predicted_and_actual(self):
        txt = self._moment(predicted_outcome="boom", actual_outcome="ok").format_visible()
        assert "boom" in txt
        assert "ok" in txt

    def test_contains_confidence_gap(self):
        txt = self._moment(confidence_gap=0.75).format_visible()
        assert "75%" in txt

    def test_shows_lesson_when_present(self):
        txt = self._moment(lesson_extracted="cache more aggressively").format_visible()
        assert "cache more aggressively" in txt

    def test_no_lesson_line_when_absent(self):
        txt = self._moment(lesson_extracted=None).format_visible()
        assert "Lesson" not in txt

    def test_shows_occurrences_when_gt_1(self):
        txt = self._moment(occurrences=3).format_visible()
        assert "x3" in txt

    def test_no_occurrences_suffix_when_1(self):
        txt = self._moment(occurrences=1).format_visible()
        assert "x1" not in txt


# ---------------------------------------------------------------------------
# AhaMoment.format_shareable
# ---------------------------------------------------------------------------

class TestAhaMomentFormatShareable:
    def _moment(self) -> AhaMoment:
        return AhaMoment(
            id="abc", timestamp=1.0,
            surprise_type="unexpected_success",
            predicted_outcome="I expected X",
            actual_outcome="Y happened",
            confidence_gap=0.9,
            context={},
            lesson_extracted="Always test edge cases",
            importance=0.9,
            occurrences=1,
        )

    def test_contains_predicted(self):
        txt = self._moment().format_shareable()
        assert "I expected X" in txt

    def test_contains_actual(self):
        txt = self._moment().format_shareable()
        assert "Y happened" in txt

    def test_contains_lesson(self):
        txt = self._moment().format_shareable()
        assert "Always test edge cases" in txt

    def test_contains_vibeship_hashtag(self):
        txt = self._moment().format_shareable()
        assert "#Vibeship" in txt

    def test_fallback_when_no_lesson(self):
        m = AhaMoment(
            id="x", timestamp=1.0, surprise_type="unexpected_success",
            predicted_outcome="p", actual_outcome="a",
            confidence_gap=0.5, context={}, lesson_extracted=None,
            importance=0.5, occurrences=1,
        )
        txt = m.format_shareable()
        assert "Still processing" in txt


# ---------------------------------------------------------------------------
# AhaTracker._load
# ---------------------------------------------------------------------------

class TestAhaTrackerLoad:
    def test_returns_default_when_no_file(self):
        tracker = _fresh_tracker()
        assert tracker.data["moments"] == []
        assert tracker.data["lessons"] == []
        assert "stats" in tracker.data

    def test_loads_existing_file(self, tmp_path, monkeypatch):
        spark_dir = tmp_path / ".spark"
        aha_file = spark_dir / "aha_moments.json"
        spark_dir.mkdir()
        data = {
            "moments": [{"id": "x", "timestamp": 1.0, "surprise_type": "unexpected_success",
                         "predicted_outcome": "p", "actual_outcome": "a",
                         "confidence_gap": 0.5, "context": {}, "lesson_extracted": None,
                         "importance": 0.5, "occurrences": 1}],
            "lessons": [],
            "patterns": {},
            "pending_surface": [],
            "stats": {"total_captured": 1, "unexpected_successes": 1,
                      "unexpected_failures": 0, "lessons_extracted": 0},
        }
        aha_file.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(aha_mod, "AHA_FILE", aha_file)
        monkeypatch.setattr(aha_mod, "SPARK_DIR", spark_dir)

        tracker = _fresh_tracker()
        assert len(tracker.data["moments"]) == 1

    def test_handles_corrupt_file_gracefully(self, tmp_path, monkeypatch):
        spark_dir = tmp_path / ".spark"
        aha_file = spark_dir / "aha_moments.json"
        spark_dir.mkdir()
        aha_file.write_text("not valid json!!!", encoding="utf-8")
        monkeypatch.setattr(aha_mod, "AHA_FILE", aha_file)
        monkeypatch.setattr(aha_mod, "SPARK_DIR", spark_dir)

        tracker = _fresh_tracker()
        assert tracker.data["moments"] == []


# ---------------------------------------------------------------------------
# AhaTracker.capture_surprise
# ---------------------------------------------------------------------------

class TestCaptureSurprise:
    def test_returns_aha_moment(self):
        tracker = _fresh_tracker()
        m = _capture(tracker)
        assert isinstance(m, AhaMoment)

    def test_moment_stored_in_data(self):
        tracker = _fresh_tracker()
        _capture(tracker)
        assert len(tracker.data["moments"]) == 1

    def test_total_captured_incremented(self):
        tracker = _fresh_tracker()
        _capture(tracker)
        assert tracker.data["stats"]["total_captured"] == 1

    def test_unexpected_success_counter(self):
        tracker = _fresh_tracker()
        _capture(tracker, surprise_type=SurpriseType.UNEXPECTED_SUCCESS)
        assert tracker.data["stats"]["unexpected_successes"] == 1

    def test_unexpected_failure_counter(self):
        tracker = _fresh_tracker()
        _capture(tracker, surprise_type=SurpriseType.UNEXPECTED_FAILURE)
        assert tracker.data["stats"]["unexpected_failures"] == 1

    def test_other_type_does_not_bump_success_or_failure(self):
        tracker = _fresh_tracker()
        _capture(tracker, surprise_type=SurpriseType.FASTER_THAN_EXPECTED)
        assert tracker.data["stats"]["unexpected_successes"] == 0
        assert tracker.data["stats"]["unexpected_failures"] == 0

    def test_lesson_stored_when_provided(self):
        tracker = _fresh_tracker()
        _capture(tracker, lesson="Use smaller steps")
        assert len(tracker.data["lessons"]) == 1
        assert tracker.data["lessons"][0]["lesson"] == "Use smaller steps"

    def test_lessons_extracted_stat_incremented(self):
        tracker = _fresh_tracker()
        _capture(tracker, lesson="something learned")
        assert tracker.data["stats"]["lessons_extracted"] == 1

    def test_pattern_recorded(self):
        tracker = _fresh_tracker()
        _capture(tracker, surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
                 context={"tool": "Write"})
        assert "unexpected_success:Write" in tracker.data["patterns"]

    def test_pattern_count_increments(self):
        tracker = _fresh_tracker()
        _capture(tracker, context={"tool": "Bash"})
        _capture(tracker, actual="different_outcome", context={"tool": "Bash"})
        key = f"{SurpriseType.UNEXPECTED_SUCCESS.value}:Bash"
        assert tracker.data["patterns"][key] == 2

    def test_moment_written_to_file(self):
        tracker = _fresh_tracker()
        _capture(tracker)
        assert aha_mod.AHA_FILE.exists()

    def test_id_is_12_hex_chars(self):
        tracker = _fresh_tracker()
        m = _capture(tracker)
        assert len(m.id) == 12
        assert all(c in "0123456789abcdef" for c in m.id)

    def test_importance_capped_at_1(self):
        tracker = _fresh_tracker()
        # failure type with gap=1.0 → importance *= 1.2, capped at 1.0
        m = _capture(tracker, surprise_type=SurpriseType.UNEXPECTED_FAILURE,
                     confidence_gap=1.0)
        assert m.importance <= 1.0

    def test_failure_type_boosts_importance(self):
        tracker = _fresh_tracker()
        m_success = _capture(tracker, surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
                             confidence_gap=0.5, actual="outcome_a")
        tracker2 = _fresh_tracker()
        m_failure = _capture(tracker2, surprise_type=SurpriseType.UNEXPECTED_FAILURE,
                             confidence_gap=0.5, actual="outcome_b")
        assert m_failure.importance >= m_success.importance

    def test_recovery_success_boosts_importance(self):
        tracker = _fresh_tracker()
        m_recovery = _capture(tracker, surprise_type=SurpriseType.RECOVERY_SUCCESS,
                               confidence_gap=0.5)
        assert m_recovery.importance >= 0.5

    def test_moments_capped_at_200(self):
        tracker = _fresh_tracker()
        for i in range(210):
            _capture(tracker, predicted=f"p{i}", actual=f"a{i}",
                     context={"tool": f"tool{i}"})
        assert len(tracker.data["moments"]) <= 200

    def test_high_importance_added_to_surface_queue(self):
        tracker = _fresh_tracker()
        m = tracker.capture_surprise(
            surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
            predicted="failure", actual="big win",
            confidence_gap=0.9,
            context={"tool": "Bash"},
            auto_surface=True,
        )
        assert m.id in tracker.pending_surface

    def test_low_importance_not_added_to_surface_queue(self):
        tracker = _fresh_tracker()
        m = tracker.capture_surprise(
            surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
            predicted="p", actual="low_imp",
            confidence_gap=0.1,  # importance < 0.5
            context={"tool": "Bash"},
            auto_surface=True,
        )
        assert m.id not in tracker.pending_surface

    def test_auto_surface_false_does_not_queue(self):
        tracker = _fresh_tracker()
        m = _capture(tracker, confidence_gap=0.9, auto_surface=False)
        assert m.id not in tracker.pending_surface


# ---------------------------------------------------------------------------
# AhaTracker._find_duplicate
# ---------------------------------------------------------------------------

class TestFindDuplicate:
    def test_no_duplicate_when_empty(self):
        tracker = _fresh_tracker()
        assert tracker._find_duplicate("Bash", "success") is None

    def test_finds_duplicate_by_tool_and_actual(self):
        tracker = _fresh_tracker()
        _capture(tracker, context={"tool": "Bash"}, actual="the outcome")
        idx = tracker._find_duplicate("Bash", "the outcome")
        assert idx == 0

    def test_no_match_different_tool(self):
        tracker = _fresh_tracker()
        _capture(tracker, context={"tool": "Bash"}, actual="the outcome")
        assert tracker._find_duplicate("Write", "the outcome") is None

    def test_no_match_different_actual(self):
        tracker = _fresh_tracker()
        _capture(tracker, context={"tool": "Bash"}, actual="outcome a")
        assert tracker._find_duplicate("Bash", "outcome b") is None

    def test_duplicate_increments_occurrences(self):
        tracker = _fresh_tracker()
        _capture(tracker, context={"tool": "Bash"}, actual="the result")
        _capture(tracker, context={"tool": "Bash"}, actual="the result")
        assert tracker.data["moments"][0].get("occurrences", 1) >= 2

    def test_duplicate_updates_timestamp(self):
        tracker = _fresh_tracker()
        _capture(tracker, context={"tool": "Bash"}, actual="same result")
        old_ts = tracker.data["moments"][0]["timestamp"]
        time.sleep(0.01)
        _capture(tracker, context={"tool": "Bash"}, actual="same result")
        new_ts = tracker.data["moments"][0]["timestamp"]
        assert new_ts >= old_ts


# ---------------------------------------------------------------------------
# AhaTracker.get_pending_surface / surface / surface_all_pending
# ---------------------------------------------------------------------------

class TestSurfacing:
    def test_get_pending_surface_empty_initially(self):
        tracker = _fresh_tracker()
        assert tracker.get_pending_surface() == []

    def test_get_pending_surface_returns_queued(self):
        tracker = _fresh_tracker()
        m = tracker.capture_surprise(
            surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
            predicted="p", actual="a",
            confidence_gap=0.9,
            context={"tool": "Bash"},
            auto_surface=True,
        )
        pending = tracker.get_pending_surface()
        assert any(p.id == m.id for p in pending)

    def test_surface_removes_from_queue(self):
        tracker = _fresh_tracker()
        m = tracker.capture_surprise(
            surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
            predicted="p", actual="high_imp",
            confidence_gap=0.9,
            context={"tool": "Bash"},
            auto_surface=True,
        )
        tracker.surface(m.id)
        assert m.id not in tracker.pending_surface

    def test_surface_returns_formatted_string(self):
        tracker = _fresh_tracker()
        m = tracker.capture_surprise(
            surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
            predicted="p", actual="high_imp",
            confidence_gap=0.9,
            context={"tool": "Bash"},
            auto_surface=True,
        )
        txt = tracker.surface(m.id)
        assert txt is not None
        assert isinstance(txt, str)
        assert len(txt) > 0

    def test_surface_unknown_id_returns_none(self):
        tracker = _fresh_tracker()
        assert tracker.surface("nonexistent_id") is None

    def test_surface_all_pending_clears_queue(self):
        tracker = _fresh_tracker()
        for i in range(3):
            tracker.capture_surprise(
                surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
                predicted=f"p{i}", actual=f"high{i}",
                confidence_gap=0.9,
                context={"tool": "Bash"},
                auto_surface=True,
            )
        tracker.surface_all_pending()
        assert tracker.pending_surface == []

    def test_surface_all_pending_returns_list_of_strings(self):
        tracker = _fresh_tracker()
        tracker.capture_surprise(
            surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
            predicted="p", actual="high",
            confidence_gap=0.9,
            context={"tool": "Bash"},
            auto_surface=True,
        )
        results = tracker.surface_all_pending()
        assert isinstance(results, list)
        assert all(isinstance(r, str) for r in results)


# ---------------------------------------------------------------------------
# AhaTracker.extract_lesson
# ---------------------------------------------------------------------------

class TestExtractLesson:
    def test_adds_lesson_to_moment(self):
        tracker = _fresh_tracker()
        m = _capture(tracker)
        tracker.extract_lesson(m.id, "Don't assume the happy path")
        updated = next(x for x in tracker.data["moments"] if x["id"] == m.id)
        assert updated["lesson_extracted"] == "Don't assume the happy path"

    def test_appends_to_lessons_list(self):
        tracker = _fresh_tracker()
        m = _capture(tracker)
        tracker.extract_lesson(m.id, "A key insight")
        assert any(l["lesson"] == "A key insight" for l in tracker.data["lessons"])

    def test_increments_lessons_extracted_stat(self):
        tracker = _fresh_tracker()
        m = _capture(tracker)
        before = tracker.data["stats"]["lessons_extracted"]
        tracker.extract_lesson(m.id, "new lesson")
        assert tracker.data["stats"]["lessons_extracted"] == before + 1

    def test_returns_true_on_success(self):
        tracker = _fresh_tracker()
        m = _capture(tracker)
        assert tracker.extract_lesson(m.id, "lesson") is True

    def test_returns_false_for_unknown_id(self):
        tracker = _fresh_tracker()
        assert tracker.extract_lesson("no_such_id", "lesson") is False


# ---------------------------------------------------------------------------
# AhaTracker.get_recent_surprises
# ---------------------------------------------------------------------------

class TestGetRecentSurprises:
    def test_empty_when_no_moments(self):
        tracker = _fresh_tracker()
        assert tracker.get_recent_surprises() == []

    def test_returns_limited_count(self):
        tracker = _fresh_tracker()
        for i in range(15):
            _capture(tracker, actual=f"unique_{i}", predicted=f"p{i}",
                     context={"tool": f"t{i}"})
        recent = tracker.get_recent_surprises(limit=5)
        assert len(recent) <= 5

    def test_sorted_newest_first(self):
        tracker = _fresh_tracker()
        _capture(tracker, actual="first", context={"tool": "t1"})
        time.sleep(0.01)
        _capture(tracker, actual="second", context={"tool": "t2"})
        recent = tracker.get_recent_surprises(limit=10)
        timestamps = [r["timestamp"] for r in recent]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_occurrences_field_present(self):
        tracker = _fresh_tracker()
        _capture(tracker)
        recent = tracker.get_recent_surprises()
        assert "occurrences" in recent[0]


# ---------------------------------------------------------------------------
# AhaTracker.dedupe_existing
# ---------------------------------------------------------------------------

class TestDedupeExisting:
    def test_empty_moments_returns_zero(self):
        tracker = _fresh_tracker()
        assert tracker.dedupe_existing() == 0

    def test_no_duplicates_returns_zero(self):
        tracker = _fresh_tracker()
        _capture(tracker, actual="outcome_A", context={"tool": "Bash"})
        _capture(tracker, actual="outcome_B", context={"tool": "Bash"})
        assert tracker.dedupe_existing() == 0

    def test_merges_duplicates(self):
        tracker = _fresh_tracker()
        # Manually inject duplicate entries
        base_moment = {
            "id": "dup1", "timestamp": 100.0,
            "surprise_type": "unexpected_success",
            "predicted_outcome": "p", "actual_outcome": "dup_actual",
            "confidence_gap": 0.5, "context": {"tool": "Bash"},
            "lesson_extracted": None, "importance": 0.5, "occurrences": 1,
        }
        tracker.data["moments"] = [dict(base_moment), dict(base_moment)]
        count = tracker.dedupe_existing()
        assert count == 1
        assert len(tracker.data["moments"]) == 1

    def test_merged_occurrences_summed(self):
        tracker = _fresh_tracker()
        base = {
            "id": "m1", "timestamp": 100.0,
            "surprise_type": "unexpected_success",
            "predicted_outcome": "p", "actual_outcome": "same",
            "confidence_gap": 0.5, "context": {"tool": "T"},
            "lesson_extracted": None, "importance": 0.5, "occurrences": 2,
        }
        dup = dict(base)
        dup["occurrences"] = 3
        tracker.data["moments"] = [base, dup]
        tracker.dedupe_existing()
        assert tracker.data["moments"][0]["occurrences"] == 5

    def test_lesson_preserved_from_duplicate_if_original_lacks_it(self):
        tracker = _fresh_tracker()
        m1 = {"id": "a", "timestamp": 100.0, "surprise_type": "unexpected_success",
               "predicted_outcome": "p", "actual_outcome": "same",
               "confidence_gap": 0.5, "context": {"tool": "T"},
               "lesson_extracted": None, "importance": 0.5, "occurrences": 1}
        m2 = dict(m1)
        m2["lesson_extracted"] = "the lesson"
        tracker.data["moments"] = [m1, m2]
        tracker.dedupe_existing()
        assert tracker.data["moments"][0]["lesson_extracted"] == "the lesson"


# ---------------------------------------------------------------------------
# AhaTracker.get_high_importance_surprises
# ---------------------------------------------------------------------------

class TestGetHighImportanceSurprises:
    def test_returns_only_high_importance(self):
        tracker = _fresh_tracker()
        _capture(tracker, confidence_gap=0.9, actual="high_imp", context={"tool": "A"})
        _capture(tracker, confidence_gap=0.2, actual="low_imp", context={"tool": "B"})
        high = tracker.get_high_importance_surprises(min_importance=0.7)
        assert all(m.importance >= 0.7 for m in high)

    def test_empty_when_none_qualify(self):
        tracker = _fresh_tracker()
        _capture(tracker, confidence_gap=0.1, actual="low")
        high = tracker.get_high_importance_surprises(min_importance=0.99)
        assert high == []

    def test_returns_aha_moment_instances(self):
        tracker = _fresh_tracker()
        _capture(tracker, confidence_gap=0.9, actual="high")
        high = tracker.get_high_importance_surprises(min_importance=0.5)
        assert all(isinstance(m, AhaMoment) for m in high)


# ---------------------------------------------------------------------------
# AhaTracker.get_unlearned_surprises
# ---------------------------------------------------------------------------

class TestGetUnlearnedSurprises:
    def test_all_unlearned_initially(self):
        tracker = _fresh_tracker()
        _capture(tracker)
        _capture(tracker, actual="second", context={"tool": "B"})
        unlearned = tracker.get_unlearned_surprises()
        assert len(unlearned) == 2

    def test_excludes_moments_with_lessons(self):
        tracker = _fresh_tracker()
        m = _capture(tracker, lesson="already learned")
        unlearned = tracker.get_unlearned_surprises()
        assert all(x.id != m.id for x in unlearned)

    def test_returns_aha_moment_instances(self):
        tracker = _fresh_tracker()
        _capture(tracker)
        unlearned = tracker.get_unlearned_surprises()
        assert all(isinstance(m, AhaMoment) for m in unlearned)


# ---------------------------------------------------------------------------
# AhaTracker.get_surprise_patterns
# ---------------------------------------------------------------------------

class TestGetSurprisePatterns:
    def test_empty_when_no_captures(self):
        tracker = _fresh_tracker()
        assert tracker.get_surprise_patterns() == {}

    def test_records_pattern(self):
        tracker = _fresh_tracker()
        _capture(tracker, surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
                 context={"tool": "Bash"})
        patterns = tracker.get_surprise_patterns()
        assert "unexpected_success:Bash" in patterns

    def test_sorted_descending(self):
        tracker = _fresh_tracker()
        for _ in range(3):
            _capture(tracker, surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
                     context={"tool": "Bash"}, actual=f"a{_}")
        _capture(tracker, surprise_type=SurpriseType.UNEXPECTED_FAILURE,
                 context={"tool": "Bash"}, actual="b")
        patterns = tracker.get_surprise_patterns()
        counts = list(patterns.values())
        assert counts == sorted(counts, reverse=True)


# ---------------------------------------------------------------------------
# AhaTracker.get_lessons
# ---------------------------------------------------------------------------

class TestGetLessons:
    def test_empty_initially(self):
        tracker = _fresh_tracker()
        assert tracker.get_lessons() == []

    def test_captures_lesson_from_capture_surprise(self):
        tracker = _fresh_tracker()
        _capture(tracker, lesson="always handle edge cases")
        lessons = tracker.get_lessons()
        assert len(lessons) == 1
        assert lessons[0]["lesson"] == "always handle edge cases"

    def test_lesson_has_moment_id(self):
        tracker = _fresh_tracker()
        m = _capture(tracker, lesson="test lesson")
        lessons = tracker.get_lessons()
        assert lessons[0]["moment_id"] == m.id


# ---------------------------------------------------------------------------
# AhaTracker.get_insights
# ---------------------------------------------------------------------------

class TestGetInsights:
    def test_no_moments_returns_message(self):
        tracker = _fresh_tracker()
        result = tracker.get_insights()
        assert "message" in result

    def test_with_moments_returns_analysis(self):
        tracker = _fresh_tracker()
        _capture(tracker, surprise_type=SurpriseType.UNEXPECTED_SUCCESS)
        result = tracker.get_insights()
        assert "total_surprises" in result
        assert "avg_confidence_gap" in result
        assert "most_surprising_type" in result
        assert "most_surprising_tool" in result
        assert "lessons_learned" in result
        assert "learning_rate" in result

    def test_total_surprises_correct(self):
        tracker = _fresh_tracker()
        _capture(tracker, actual="a1", context={"tool": "t1"})
        _capture(tracker, actual="a2", context={"tool": "t2"})
        result = tracker.get_insights()
        assert result["total_surprises"] == 2

    def test_recommendations_present(self):
        tracker = _fresh_tracker()
        _capture(tracker)
        result = tracker.get_insights()
        assert "recommendations" in result
        assert isinstance(result["recommendations"], list)

    def test_high_gap_triggers_overconfident_recommendation(self):
        tracker = _fresh_tracker()
        # Many high-gap captures to drive avg above 0.6
        for i in range(5):
            _capture(tracker, confidence_gap=0.9, actual=f"a{i}", context={"tool": "T"})
        result = tracker.get_insights()
        assert any("overconfident" in r for r in result["recommendations"])

    def test_low_lesson_rate_triggers_recommendation(self):
        tracker = _fresh_tracker()
        # Capture without lessons → learning_rate = 0
        for i in range(4):
            _capture(tracker, confidence_gap=0.3, actual=f"a{i}", context={"tool": "T"})
        result = tracker.get_insights()
        assert any("lesson" in r.lower() for r in result["recommendations"])


# ---------------------------------------------------------------------------
# AhaTracker.get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_returns_dict_with_all_keys(self):
        tracker = _fresh_tracker()
        stats = tracker.get_stats()
        for key in ("total_captured", "unexpected_successes", "unexpected_failures",
                    "lessons_extracted", "pattern_count", "unlearned_count",
                    "pending_surface", "unique_moments", "total_occurrences"):
            assert key in stats, f"Missing key: {key}"

    def test_initial_counts_all_zero(self):
        tracker = _fresh_tracker()
        stats = tracker.get_stats()
        assert stats["total_captured"] == 0
        assert stats["unique_moments"] == 0

    def test_counts_update_after_capture(self):
        tracker = _fresh_tracker()
        _capture(tracker)
        stats = tracker.get_stats()
        assert stats["total_captured"] == 1
        assert stats["unique_moments"] == 1
        assert stats["total_occurrences"] == 1


# ---------------------------------------------------------------------------
# get_aha_tracker (singleton)
# ---------------------------------------------------------------------------

class TestGetAhaTracker:
    def test_returns_tracker_instance(self):
        tracker = get_aha_tracker()
        assert isinstance(tracker, AhaTracker)

    def test_same_instance_returned_twice(self):
        t1 = get_aha_tracker()
        t2 = get_aha_tracker()
        assert t1 is t2

    def test_reset_by_fixture(self):
        # After reset_singleton fixture runs, _tracker is None
        assert aha_mod._tracker is None
        get_aha_tracker()
        assert aha_mod._tracker is not None


# ---------------------------------------------------------------------------
# dedupe_aha_moments
# ---------------------------------------------------------------------------

class TestDedupeAhaMoments:
    def test_returns_zero_when_empty(self):
        assert dedupe_aha_moments() == 0

    def test_delegates_to_tracker(self):
        tracker = get_aha_tracker()
        _capture(tracker, actual="dup", context={"tool": "T"})
        _capture(tracker, actual="dup", context={"tool": "T"})
        # Two captures with same tool+actual → 1 dedup expected
        count = dedupe_aha_moments()
        assert isinstance(count, int)


# ---------------------------------------------------------------------------
# maybe_capture_surprise
# ---------------------------------------------------------------------------

class TestMaybeCaptureSuprise:
    def test_unexpected_failure_above_threshold(self):
        prediction = {"outcome": "success", "confidence": 0.9}
        outcome = {"success": False, "tool": "Bash"}
        m = maybe_capture_surprise(prediction, outcome, threshold=0.5)
        assert m is not None
        assert m.surprise_type == SurpriseType.UNEXPECTED_FAILURE.value

    def test_unexpected_success_above_threshold(self):
        prediction = {"outcome": "failure", "confidence": 0.2}
        outcome = {"success": True, "tool": "Bash"}
        # confidence_gap = 1 - 0.2 = 0.8
        m = maybe_capture_surprise(prediction, outcome, threshold=0.5)
        assert m is not None
        assert m.surprise_type == SurpriseType.UNEXPECTED_SUCCESS.value

    def test_no_surprise_when_prediction_matches(self):
        prediction = {"outcome": "success", "confidence": 0.9}
        outcome = {"success": True, "tool": "Bash"}
        m = maybe_capture_surprise(prediction, outcome, threshold=0.5)
        assert m is None

    def test_below_threshold_returns_none(self):
        prediction = {"outcome": "success", "confidence": 0.6}
        outcome = {"success": False, "tool": "Bash"}
        # confidence_gap = 0.6 < threshold 0.7
        m = maybe_capture_surprise(prediction, outcome, threshold=0.7)
        assert m is None

    def test_uses_singleton_tracker(self):
        prediction = {"outcome": "success", "confidence": 0.9}
        outcome = {"success": False, "tool": "Bash"}
        m = maybe_capture_surprise(prediction, outcome)
        tracker = get_aha_tracker()
        assert tracker.data["stats"]["total_captured"] >= 1

    def test_default_threshold_is_0_5(self):
        # confidence_gap = 0.6 ≥ 0.5 default → captures
        prediction = {"outcome": "success", "confidence": 0.6}
        outcome = {"success": False, "tool": "T"}
        m = maybe_capture_surprise(prediction, outcome)
        assert m is not None

    def test_at_exact_threshold_boundary(self):
        # confidence_gap = 0.5 exactly == threshold=0.5 → captures (>=)
        prediction = {"outcome": "success", "confidence": 0.5}
        outcome = {"success": False, "tool": "T"}
        m = maybe_capture_surprise(prediction, outcome, threshold=0.5)
        assert m is not None
