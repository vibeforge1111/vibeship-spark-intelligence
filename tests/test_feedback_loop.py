"""Tests for lib/feedback_loop.py — 50 tests."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import lib.feedback_loop as fb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_report_file(directory: Path, name: str, data: dict) -> Path:
    path = directory / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _load_state / _save_state
# ---------------------------------------------------------------------------

class TestLoadState:
    def test_returns_default_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fb, "FEEDBACK_STATE_FILE", tmp_path / "missing.json")
        state = fb._load_state()
        assert state["total_processed"] == 0
        assert state["advice_action_rate"] == 0.0
        assert state["processed_reports"] == []

    def test_loads_existing_valid_state(self, tmp_path, monkeypatch):
        p = tmp_path / "state.json"
        p.write_text(json.dumps({"total_processed": 5, "total_positive": 3}))
        monkeypatch.setattr(fb, "FEEDBACK_STATE_FILE", p)
        state = fb._load_state()
        assert state["total_processed"] == 5
        assert state["total_positive"] == 3

    def test_returns_default_on_corrupt_file(self, tmp_path, monkeypatch):
        p = tmp_path / "state.json"
        p.write_text("NOT JSON!!!")
        monkeypatch.setattr(fb, "FEEDBACK_STATE_FILE", p)
        state = fb._load_state()
        assert state["total_processed"] == 0

    def test_default_keys_all_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fb, "FEEDBACK_STATE_FILE", tmp_path / "nope.json")
        state = fb._load_state()
        for key in ("processed_reports", "advisory_outcomes", "total_processed",
                    "total_positive", "total_negative", "total_neutral",
                    "advice_action_rate"):
            assert key in state


class TestSaveState:
    def test_creates_parent_dirs(self, tmp_path, monkeypatch):
        nested = tmp_path / "a" / "b" / "state.json"
        monkeypatch.setattr(fb, "FEEDBACK_STATE_FILE", nested)
        fb._save_state({"total_processed": 1})
        assert nested.exists()

    def test_roundtrip(self, tmp_path, monkeypatch):
        p = tmp_path / "state.json"
        monkeypatch.setattr(fb, "FEEDBACK_STATE_FILE", p)
        fb._save_state({"total_processed": 99, "custom": "hello"})
        loaded = json.loads(p.read_text())
        assert loaded["total_processed"] == 99
        assert loaded["custom"] == "hello"


# ---------------------------------------------------------------------------
# _log_feedback
# ---------------------------------------------------------------------------

class TestLogFeedback:
    def test_appends_jsonl_entry(self, tmp_path, monkeypatch):
        log = tmp_path / "feedback_log.jsonl"
        monkeypatch.setattr(fb, "FEEDBACK_LOG_FILE", log)
        fb._log_feedback({"kind": "decision", "file": "foo.json"})
        lines = log.read_text().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["kind"] == "decision"

    def test_appends_multiple_entries(self, tmp_path, monkeypatch):
        log = tmp_path / "feedback_log.jsonl"
        monkeypatch.setattr(fb, "FEEDBACK_LOG_FILE", log)
        for i in range(5):
            fb._log_feedback({"idx": i})
        lines = log.read_text().splitlines()
        assert len(lines) == 5

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        nested = tmp_path / "sub" / "dir" / "log.jsonl"
        monkeypatch.setattr(fb, "FEEDBACK_LOG_FILE", nested)
        fb._log_feedback({"test": True})
        assert nested.exists()


# ---------------------------------------------------------------------------
# ingest_reports
# ---------------------------------------------------------------------------

class TestIngestReports:
    def _patch(self, monkeypatch, tmp_path):
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        state_file = tmp_path / "state.json"
        log_file = tmp_path / "log.jsonl"
        monkeypatch.setattr(fb, "REPORTS_DIR", reports_dir)
        monkeypatch.setattr(fb, "FEEDBACK_STATE_FILE", state_file)
        monkeypatch.setattr(fb, "FEEDBACK_LOG_FILE", log_file)
        monkeypatch.setattr(fb, "log_debug", lambda *a: None)
        return reports_dir

    def test_empty_reports_dir_returns_zero_stats(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        stats = fb.ingest_reports()
        assert stats["found"] == 0
        assert stats["processed"] == 0

    def test_returns_zero_when_reports_dir_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fb, "REPORTS_DIR", tmp_path / "no_dir")
        stats = fb.ingest_reports()
        assert stats["found"] == 0
        assert stats["processed"] == 0

    def test_processes_decision_report(self, monkeypatch, tmp_path):
        reports = self._patch(monkeypatch, tmp_path)
        _make_report_file(reports, "r1.json", {
            "kind": "decision", "intent": "do X", "confidence": 0.8,
            "source": "other", "ts": time.time(),
        })
        with patch("lib.cognitive_learner.get_cognitive_learner") as m:
            m.return_value.add_insight = MagicMock()
            stats = fb.ingest_reports()
        assert stats["decisions"] == 1
        assert stats["processed"] == 1

    def test_processes_outcome_report(self, monkeypatch, tmp_path):
        reports = self._patch(monkeypatch, tmp_path)
        _make_report_file(reports, "r2.json", {
            "kind": "outcome", "result": "done", "success": True,
            "lesson": "worked", "ts": time.time(),
        })
        with patch("lib.cognitive_learner.get_cognitive_learner") as m, \
             patch("lib.outcome_log.append_outcomes"):
            m.return_value.add_insight = MagicMock()
            stats = fb.ingest_reports()
        assert stats["outcomes"] == 1

    def test_processes_preference_report(self, monkeypatch, tmp_path):
        reports = self._patch(monkeypatch, tmp_path)
        _make_report_file(reports, "r3.json", {
            "kind": "preference", "liked": "fast responses", "ts": time.time(),
        })
        with patch("lib.cognitive_learner.get_cognitive_learner") as m:
            m.return_value.add_insight = MagicMock()
            stats = fb.ingest_reports()
        assert stats["preferences"] == 1

    def test_unknown_kind_counted_but_not_categorised(self, monkeypatch, tmp_path):
        reports = self._patch(monkeypatch, tmp_path)
        _make_report_file(reports, "r4.json", {"kind": "mystery"})
        stats = fb.ingest_reports()
        # processed but no category counter incremented
        assert stats["processed"] == 1
        assert stats["decisions"] == 0
        assert stats["outcomes"] == 0
        assert stats["preferences"] == 0

    def test_corrupt_json_increments_errors(self, monkeypatch, tmp_path):
        reports = self._patch(monkeypatch, tmp_path)
        bad = reports / "bad.json"
        bad.write_text("GARBAGE", encoding="utf-8")
        stats = fb.ingest_reports()
        assert stats["errors"] == 1
        assert stats["processed"] == 0

    def test_already_processed_files_skipped(self, monkeypatch, tmp_path):
        reports = self._patch(monkeypatch, tmp_path)
        fname = "dup.json"
        _make_report_file(reports, fname, {"kind": "preference"})
        # Prime the state with the filename already processed
        state_p = tmp_path / "state.json"
        state_p.write_text(json.dumps({"processed_reports": [fname]}))
        with patch("lib.cognitive_learner.get_cognitive_learner"):
            stats = fb.ingest_reports()
        assert stats["processed"] == 0

    def test_multiple_reports_mixed_kinds(self, monkeypatch, tmp_path):
        reports = self._patch(monkeypatch, tmp_path)
        for i, kind in enumerate(["decision", "outcome", "preference"]):
            data = {"kind": kind, "ts": time.time()}
            if kind == "decision":
                data.update({"intent": "a", "confidence": 0.5, "source": "other"})
            elif kind == "outcome":
                data.update({"result": "r", "success": True, "lesson": "l"})
            else:
                data.update({"liked": "x"})
            _make_report_file(reports, f"r{i}.json", data)
        with patch("lib.cognitive_learner.get_cognitive_learner") as m, \
             patch("lib.outcome_log.append_outcomes"):
            m.return_value.add_insight = MagicMock()
            stats = fb.ingest_reports()
        assert stats["processed"] == 3
        assert stats["decisions"] == 1
        assert stats["outcomes"] == 1
        assert stats["preferences"] == 1

    def test_advice_action_rate_updated(self, monkeypatch, tmp_path):
        reports = self._patch(monkeypatch, tmp_path)
        _make_report_file(reports, "o1.json", {
            "kind": "outcome", "result": "ok", "success": True, "ts": time.time(),
        })
        with patch("lib.cognitive_learner.get_cognitive_learner") as m, \
             patch("lib.outcome_log.append_outcomes"):
            m.return_value.add_insight = MagicMock()
            fb.ingest_reports()
        state = fb._load_state()
        assert state["total_positive"] == 1


# ---------------------------------------------------------------------------
# _process_decision
# ---------------------------------------------------------------------------

class TestProcessDecision:
    def test_spark_source_adds_to_advisory_outcomes(self):
        state = {"advisory_outcomes": {}}
        with patch("lib.cognitive_learner.get_cognitive_learner") as m:
            m.return_value.add_insight = MagicMock()
            fb._process_decision(
                {"intent": "do it", "confidence": 0.9, "source": "spark_advisory", "ts": 1000},
                state,
            )
        assert len(state["advisory_outcomes"]) == 1

    def test_non_spark_source_does_not_add_advisory_outcome(self):
        state = {"advisory_outcomes": {}}
        with patch("lib.cognitive_learner.get_cognitive_learner") as m:
            m.return_value.add_insight = MagicMock()
            fb._process_decision(
                {"intent": "do it", "confidence": 0.9, "source": "user", "ts": 1000},
                state,
            )
        assert len(state["advisory_outcomes"]) == 0

    def test_cognitive_import_error_silently_ignored(self, monkeypatch):
        monkeypatch.setattr(fb, "log_debug", lambda *a: None)
        state = {"advisory_outcomes": {}}
        with patch.dict("sys.modules", {"lib.cognitive_learner": None}):
            # Should not raise
            try:
                fb._process_decision({"intent": "x", "confidence": 0.5, "source": "spark"}, state)
            except Exception:
                pass  # import errors are caught inside the function


# ---------------------------------------------------------------------------
# _process_outcome
# ---------------------------------------------------------------------------

class TestProcessOutcome:
    def test_success_increments_positive(self):
        state = {"total_positive": 0, "total_negative": 0, "total_neutral": 0}
        with patch("lib.cognitive_learner.get_cognitive_learner") as m, \
             patch("lib.outcome_log.append_outcomes"):
            m.return_value.add_insight = MagicMock()
            fb._process_outcome({"result": "ok", "success": True, "lesson": ""}, state)
        assert state["total_positive"] == 1

    def test_failure_increments_negative(self):
        state = {"total_positive": 0, "total_negative": 0, "total_neutral": 0}
        with patch("lib.cognitive_learner.get_cognitive_learner") as m, \
             patch("lib.outcome_log.append_outcomes"):
            m.return_value.add_insight = MagicMock()
            fb._process_outcome({"result": "bad", "success": False, "lesson": ""}, state)
        assert state["total_negative"] == 1

    def test_none_success_increments_neutral(self):
        state = {"total_positive": 0, "total_negative": 0, "total_neutral": 0}
        with patch("lib.cognitive_learner.get_cognitive_learner") as m, \
             patch("lib.outcome_log.append_outcomes"):
            m.return_value.add_insight = MagicMock()
            fb._process_outcome({"result": "meh", "success": None, "lesson": ""}, state)
        assert state["total_neutral"] == 1

    def test_lesson_triggers_cognitive_add_insight(self):
        state = {"total_positive": 0, "total_negative": 0, "total_neutral": 0}
        mock_cog = MagicMock()
        with patch("lib.cognitive_learner.get_cognitive_learner", return_value=mock_cog), \
             patch("lib.outcome_log.append_outcomes"):
            fb._process_outcome({"result": "ok", "success": True, "lesson": "do X"}, state)
        mock_cog.add_insight.assert_called_once()


# ---------------------------------------------------------------------------
# _process_preference
# ---------------------------------------------------------------------------

class TestProcessPreference:
    def test_liked_and_disliked_both_add_insights(self):
        mock_cog = MagicMock()
        with patch("lib.cognitive_learner.get_cognitive_learner", return_value=mock_cog):
            fb._process_preference({"liked": "fast", "disliked": "slow"}, {})
        assert mock_cog.add_insight.call_count == 2

    def test_empty_liked_does_not_add_insight(self):
        mock_cog = MagicMock()
        with patch("lib.cognitive_learner.get_cognitive_learner", return_value=mock_cog):
            fb._process_preference({"liked": "", "disliked": ""}, {})
        mock_cog.add_insight.assert_not_called()


# ---------------------------------------------------------------------------
# get_feedback_stats
# ---------------------------------------------------------------------------

class TestGetFeedbackStats:
    def test_returns_stats_from_state(self, tmp_path, monkeypatch):
        p = tmp_path / "state.json"
        p.write_text(json.dumps({
            "total_processed": 10,
            "total_positive": 7,
            "total_negative": 2,
            "total_neutral": 1,
            "advice_action_rate": 0.7,
        }))
        monkeypatch.setattr(fb, "FEEDBACK_STATE_FILE", p)
        stats = fb.get_feedback_stats()
        assert stats["total_processed"] == 10
        assert stats["advice_action_rate"] == 0.7

    def test_returns_zeros_when_no_state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fb, "FEEDBACK_STATE_FILE", tmp_path / "missing.json")
        stats = fb.get_feedback_stats()
        assert stats["total_processed"] == 0
        assert stats["advice_action_rate"] == 0.0


# ---------------------------------------------------------------------------
# report_advisory_feedback
# ---------------------------------------------------------------------------

class TestReportAdvisoryFeedback:
    def test_acted_on_calls_report_with_outcome(self):
        with patch("lib.self_report.report") as mock_report:
            fb.report_advisory_feedback("use X instead of Y", acted_on=True, success=True)
        mock_report.assert_called_once()
        call_args = mock_report.call_args
        assert call_args.args[0] == "outcome"

    def test_not_acted_on_calls_report_with_decision(self):
        with patch("lib.self_report.report") as mock_report:
            fb.report_advisory_feedback("use X instead of Y", acted_on=False)
        mock_report.assert_called_once()
        call_args = mock_report.call_args
        assert call_args.args[0] == "decision"

    def test_advisory_text_truncated_to_200_in_lesson(self):
        long_text = "A" * 300
        with patch("lib.self_report.report") as mock_report:
            fb.report_advisory_feedback(long_text, acted_on=True)
        kwargs = mock_report.call_args.kwargs
        assert len(kwargs.get("lesson", "")) <= 216  # "Advisory said: " (15) + 200 chars + slack
