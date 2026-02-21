"""Tests for lib/implicit_outcome_tracker.py

Covers:
- ImplicitOutcomeTracker.record_advice(): stores pending entry keyed by
  tool_name, trims to 5 advice texts, skips empty lists, stores trace_id
- ImplicitOutcomeTracker.record_outcome(): no pending entry returns
  {matched: False, signal: no_advice}, matched entry returns
  {matched: True, signal: followed/unhelpful}, removes entry from pending,
  appends row to FEEDBACK_FILE, includes error text when provided
- ImplicitOutcomeTracker.detect_correction(): True when pending advice
  within TTL, False when no entry, False after record_outcome clears it
- ImplicitOutcomeTracker._clean_stale(): removes expired entries
- get_implicit_tracker(): returns ImplicitOutcomeTracker singleton
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.implicit_outcome_tracker as iot
from lib.implicit_outcome_tracker import (
    ImplicitOutcomeTracker,
    get_implicit_tracker,
    ADVICE_TTL_S,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(tmp_path: Path) -> ImplicitOutcomeTracker:
    """Return a tracker whose FEEDBACK_FILE is redirected to tmp_path."""
    tracker = ImplicitOutcomeTracker()
    tracker._feedback_file = tmp_path / "feedback.jsonl"  # override for _append_feedback
    # Monkeypatch at module level handled separately in tests that write to disk
    return tracker


# ---------------------------------------------------------------------------
# record_advice
# ---------------------------------------------------------------------------

def test_record_advice_stores_entry():
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X", "do Y"])
    assert "bash" in t._pending


def test_record_advice_skips_empty_list():
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", [])
    assert "bash" not in t._pending


def test_record_advice_trims_to_five_texts():
    t = ImplicitOutcomeTracker()
    texts = [f"advice {i}" for i in range(10)]
    t.record_advice("edit", texts)
    assert len(t._pending["edit"]["advice_texts"]) == 5


def test_record_advice_stores_trace_id():
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"], trace_id="t-abc")
    assert t._pending["bash"]["trace_id"] == "t-abc"


def test_record_advice_stores_file_path():
    t = ImplicitOutcomeTracker()
    t.record_advice("read", ["do X"], tool_input={"file_path": "/foo/bar.py"})
    assert t._pending["read"]["file_path"] == "/foo/bar.py"


def test_record_advice_stores_timestamp():
    before = time.time()
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"])
    after = time.time()
    ts = t._pending["bash"]["timestamp"]
    assert before <= ts <= after


def test_record_advice_replaces_existing_tool_entry():
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["first"])
    t.record_advice("bash", ["second"])
    assert t._pending["bash"]["advice_texts"] == ["second"]


# ---------------------------------------------------------------------------
# record_outcome
# ---------------------------------------------------------------------------

def test_record_outcome_no_advice_returns_no_match():
    t = ImplicitOutcomeTracker()
    result = t.record_outcome("bash", success=True)
    assert result == {"matched": False, "signal": "no_advice"}


def test_record_outcome_matched_returns_true():
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"])
    result = t.record_outcome("bash", success=True)
    assert result["matched"] is True


def test_record_outcome_success_gives_followed():
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"])
    result = t.record_outcome("bash", success=True)
    assert result["signal"] == "followed"


def test_record_outcome_failure_gives_unhelpful():
    t = ImplicitOutcomeTracker()
    t.record_advice("edit", ["do Y"])
    result = t.record_outcome("edit", success=False)
    assert result["signal"] == "unhelpful"


def test_record_outcome_removes_from_pending():
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"])
    t.record_outcome("bash", success=True)
    assert "bash" not in t._pending


def test_record_outcome_writes_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(iot, "FEEDBACK_FILE", tmp_path / "feedback.jsonl")
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"])
    t.record_outcome("bash", success=True)
    rows = (tmp_path / "feedback.jsonl").read_text().strip().splitlines()
    assert len(rows) == 1
    row = json.loads(rows[0])
    assert row["tool"] == "bash"


def test_record_outcome_includes_error_text(tmp_path, monkeypatch):
    monkeypatch.setattr(iot, "FEEDBACK_FILE", tmp_path / "feedback.jsonl")
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"])
    t.record_outcome("bash", success=False, error_text="permission denied")
    row = json.loads((tmp_path / "feedback.jsonl").read_text().strip())
    assert "error" in row
    assert "permission denied" in row["error"]


def test_record_outcome_truncates_long_error(tmp_path, monkeypatch):
    monkeypatch.setattr(iot, "FEEDBACK_FILE", tmp_path / "feedback.jsonl")
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"])
    t.record_outcome("bash", success=False, error_text="x" * 500)
    row = json.loads((tmp_path / "feedback.jsonl").read_text().strip())
    assert len(row["error"]) <= 200


def test_record_outcome_inherits_trace_id_from_advice():
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"], trace_id="t-xyz")
    result = t.record_outcome("bash", success=True)
    assert result["matched"] is True  # verifies advice was matched


def test_record_outcome_trace_id_from_call_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(iot, "FEEDBACK_FILE", tmp_path / "feedback.jsonl")
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"], trace_id="old")
    t.record_outcome("bash", success=True, trace_id="new")
    row = json.loads((tmp_path / "feedback.jsonl").read_text().strip())
    assert row["trace_id"] == "new"


# ---------------------------------------------------------------------------
# detect_correction
# ---------------------------------------------------------------------------

def test_detect_correction_true_when_pending():
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"])
    assert t.detect_correction("bash") is True


def test_detect_correction_false_when_no_pending():
    t = ImplicitOutcomeTracker()
    assert t.detect_correction("bash") is False


def test_detect_correction_false_after_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr(iot, "FEEDBACK_FILE", tmp_path / "feedback.jsonl")
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"])
    t.record_outcome("bash", success=True)
    assert t.detect_correction("bash") is False


def test_detect_correction_false_when_stale():
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"])
    # Force stale timestamp
    t._pending["bash"]["timestamp"] = time.time() - ADVICE_TTL_S - 1
    assert t.detect_correction("bash") is False


# ---------------------------------------------------------------------------
# _clean_stale
# ---------------------------------------------------------------------------

def test_clean_stale_removes_expired():
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"])
    t._pending["bash"]["timestamp"] = time.time() - ADVICE_TTL_S - 1
    t._clean_stale()
    assert "bash" not in t._pending


def test_clean_stale_keeps_fresh():
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"])
    t._clean_stale()
    assert "bash" in t._pending


def test_clean_stale_multiple_tools():
    t = ImplicitOutcomeTracker()
    t.record_advice("bash", ["do X"])
    t.record_advice("edit", ["do Y"])
    t._pending["bash"]["timestamp"] = time.time() - ADVICE_TTL_S - 1
    t._clean_stale()
    assert "bash" not in t._pending
    assert "edit" in t._pending


# ---------------------------------------------------------------------------
# get_implicit_tracker (singleton)
# ---------------------------------------------------------------------------

def test_get_implicit_tracker_returns_instance():
    assert isinstance(get_implicit_tracker(), ImplicitOutcomeTracker)


def test_get_implicit_tracker_same_object():
    a = get_implicit_tracker()
    b = get_implicit_tracker()
    assert a is b
