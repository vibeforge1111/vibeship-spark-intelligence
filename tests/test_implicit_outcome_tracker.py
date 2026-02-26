"""Tests for lib/implicit_outcome_tracker.py — advice → outcome linker."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.implicit_outcome_tracker as iot
from lib.implicit_outcome_tracker import ImplicitOutcomeTracker, get_implicit_tracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tracker(monkeypatch, tmp_path: Path) -> ImplicitOutcomeTracker:
    fake_file = tmp_path / "implicit_feedback.jsonl"
    monkeypatch.setattr(iot, "FEEDBACK_FILE", fake_file)
    return ImplicitOutcomeTracker()


# ---------------------------------------------------------------------------
# record_advice
# ---------------------------------------------------------------------------


def test_record_advice_stores_pending(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("BashTool", ["use -n flag"])
    assert "BashTool" in tracker._pending


def test_record_advice_stores_up_to_5_texts(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("BashTool", [f"advice {i}" for i in range(10)])
    assert len(tracker._pending["BashTool"]["advice_texts"]) <= 5


def test_record_advice_stores_sources(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("BashTool", ["advice"], advice_sources=["rule:123"])
    assert tracker._pending["BashTool"]["advice_sources"] == ["rule:123"]


def test_record_advice_stores_file_path(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("Edit", ["advice"], tool_input={"file_path": "/foo/bar.py"})
    assert tracker._pending["Edit"]["file_path"] == "/foo/bar.py"


def test_record_advice_stores_trace_id(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("BashTool", ["advice"], trace_id="t-007")
    assert tracker._pending["BashTool"]["trace_id"] == "t-007"


def test_record_advice_empty_texts_ignored(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("BashTool", [])
    assert "BashTool" not in tracker._pending


def test_record_advice_overwrites_previous_for_same_tool(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("BashTool", ["old advice"])
    tracker.record_advice("BashTool", ["new advice"])
    assert tracker._pending["BashTool"]["advice_texts"] == ["new advice"]


def test_record_advice_stores_timestamp(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    before = time.time()
    tracker.record_advice("BashTool", ["advice"])
    after = time.time()
    ts = tracker._pending["BashTool"]["timestamp"]
    assert before <= ts <= after


# ---------------------------------------------------------------------------
# record_outcome — unmatched (no prior advice)
# ---------------------------------------------------------------------------


def test_record_outcome_no_match_returns_no_advice(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    result = tracker.record_outcome("BashTool", success=True)
    assert result["matched"] is False
    assert result["signal"] == "no_advice"


def test_record_outcome_no_match_does_not_write_file(monkeypatch, tmp_path):
    fake_file = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(iot, "FEEDBACK_FILE", fake_file)
    tracker = ImplicitOutcomeTracker()
    tracker.record_outcome("BashTool", success=True)
    assert not fake_file.exists()


# ---------------------------------------------------------------------------
# record_outcome — matched
# ---------------------------------------------------------------------------


def test_record_outcome_matched_returns_followed_on_success(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("BashTool", ["use -n flag"])
    result = tracker.record_outcome("BashTool", success=True)
    assert result["matched"] is True
    assert result["signal"] == "followed"


def test_record_outcome_matched_returns_unhelpful_on_failure(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("Edit", ["check indentation"])
    result = tracker.record_outcome("Edit", success=False)
    assert result["matched"] is True
    assert result["signal"] == "unhelpful"


def test_record_outcome_removes_from_pending(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("BashTool", ["advice"])
    tracker.record_outcome("BashTool", success=True)
    assert "BashTool" not in tracker._pending


def test_record_outcome_persists_feedback(monkeypatch, tmp_path):
    fake_file = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(iot, "FEEDBACK_FILE", fake_file)
    tracker = ImplicitOutcomeTracker()
    tracker.record_advice("BashTool", ["advice"])
    tracker.record_outcome("BashTool", success=True)
    assert fake_file.exists()
    line = json.loads(fake_file.read_text().splitlines()[0])
    assert line["tool"] == "BashTool"
    assert line["signal"] == "followed"
    assert line["success"] is True


def test_record_outcome_feedback_contains_latency(monkeypatch, tmp_path):
    fake_file = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(iot, "FEEDBACK_FILE", fake_file)
    tracker = ImplicitOutcomeTracker()
    tracker.record_advice("BashTool", ["advice"])
    tracker.record_outcome("BashTool", success=True)
    line = json.loads(fake_file.read_text().splitlines()[0])
    assert "latency_s" in line
    assert line["latency_s"] >= 0


def test_record_outcome_stores_error_text(monkeypatch, tmp_path):
    fake_file = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(iot, "FEEDBACK_FILE", fake_file)
    tracker = ImplicitOutcomeTracker()
    tracker.record_advice("BashTool", ["advice"])
    tracker.record_outcome("BashTool", success=False, error_text="FileNotFoundError")
    line = json.loads(fake_file.read_text().splitlines()[0])
    assert "error" in line
    assert "FileNotFoundError" in line["error"]


def test_record_outcome_error_truncated_at_200(monkeypatch, tmp_path):
    fake_file = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(iot, "FEEDBACK_FILE", fake_file)
    tracker = ImplicitOutcomeTracker()
    tracker.record_advice("BashTool", ["advice"])
    tracker.record_outcome("BashTool", success=False, error_text="x" * 500)
    line = json.loads(fake_file.read_text().splitlines()[0])
    assert len(line["error"]) <= 200


def test_record_outcome_no_error_key_when_no_error(monkeypatch, tmp_path):
    fake_file = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(iot, "FEEDBACK_FILE", fake_file)
    tracker = ImplicitOutcomeTracker()
    tracker.record_advice("BashTool", ["advice"])
    tracker.record_outcome("BashTool", success=True, error_text="")
    line = json.loads(fake_file.read_text().splitlines()[0])
    assert "error" not in line


def test_record_outcome_advice_count_in_feedback(monkeypatch, tmp_path):
    fake_file = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(iot, "FEEDBACK_FILE", fake_file)
    tracker = ImplicitOutcomeTracker()
    tracker.record_advice("BashTool", ["a1", "a2", "a3"])
    tracker.record_outcome("BashTool", success=True)
    line = json.loads(fake_file.read_text().splitlines()[0])
    assert line["advice_count"] == 3


def test_record_outcome_multiple_tools_independent(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("BashTool", ["bash advice"])
    tracker.record_advice("EditTool", ["edit advice"])
    r1 = tracker.record_outcome("BashTool", success=True)
    assert r1["matched"] is True
    # EditTool still pending
    assert "EditTool" in tracker._pending


# ---------------------------------------------------------------------------
# detect_correction
# ---------------------------------------------------------------------------


def test_detect_correction_true_when_pending(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("BashTool", ["advice"])
    assert tracker.detect_correction("BashTool") is True


def test_detect_correction_false_when_not_pending(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    assert tracker.detect_correction("BashTool") is False


def test_detect_correction_false_after_outcome_recorded(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("BashTool", ["advice"])
    tracker.record_outcome("BashTool", success=True)
    assert tracker.detect_correction("BashTool") is False


# ---------------------------------------------------------------------------
# _clean_stale
# ---------------------------------------------------------------------------


def test_clean_stale_removes_expired_entries(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    old_ts = time.time() - 9999
    tracker._pending["OldTool"] = {
        "advice_texts": ["stale"],
        "advice_sources": [],
        "file_path": "",
        "timestamp": old_ts,
        "trace_id": "",
    }
    tracker._clean_stale()
    assert "OldTool" not in tracker._pending


def test_clean_stale_keeps_recent_entries(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch, tmp_path)
    tracker.record_advice("BashTool", ["fresh"])
    tracker._clean_stale()
    assert "BashTool" in tracker._pending


# ---------------------------------------------------------------------------
# get_implicit_tracker singleton
# ---------------------------------------------------------------------------


def test_get_implicit_tracker_returns_instance(monkeypatch, tmp_path):
    monkeypatch.setattr(iot, "FEEDBACK_FILE", tmp_path / "fb.jsonl")
    monkeypatch.setattr(iot, "_tracker", None)
    tracker = get_implicit_tracker()
    assert isinstance(tracker, ImplicitOutcomeTracker)


def test_get_implicit_tracker_is_singleton(monkeypatch, tmp_path):
    monkeypatch.setattr(iot, "FEEDBACK_FILE", tmp_path / "fb.jsonl")
    monkeypatch.setattr(iot, "_tracker", None)
    t1 = get_implicit_tracker()
    t2 = get_implicit_tracker()
    assert t1 is t2
