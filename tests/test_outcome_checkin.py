"""Tests for lib/outcome_checkin.py — outcome check-in request helpers."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.outcome_checkin as oc
from lib.outcome_checkin import record_checkin_request, list_checkins


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch(monkeypatch, tmp_path: Path):
    checkin_file = tmp_path / "outcome_requests.jsonl"
    state_file = tmp_path / "outcome_checkin_state.json"
    monkeypatch.setattr(oc, "CHECKIN_FILE", checkin_file)
    monkeypatch.setattr(oc, "STATE_FILE", state_file)
    return checkin_file, state_file


# ---------------------------------------------------------------------------
# _load_state / _save_state (via record_checkin_request)
# ---------------------------------------------------------------------------


def test_initial_state_missing_file_returns_empty(monkeypatch, tmp_path):
    _, state_file = _patch(monkeypatch, tmp_path)
    # Import private helpers through module for white-box test
    from lib.outcome_checkin import _load_state
    state = _load_state()
    assert state == {}


def test_state_saved_after_record(monkeypatch, tmp_path):
    _, state_file = _patch(monkeypatch, tmp_path)
    record_checkin_request(session_id="s1", event="tool_call", min_interval_s=0)
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert "last_ts" in data


def test_load_state_handles_corrupt_file(monkeypatch, tmp_path):
    _, state_file = _patch(monkeypatch, tmp_path)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("not json", encoding="utf-8")
    from lib.outcome_checkin import _load_state
    state = _load_state()
    assert state == {}


# ---------------------------------------------------------------------------
# record_checkin_request — first call
# ---------------------------------------------------------------------------


def test_record_checkin_returns_true_first_time(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    result = record_checkin_request(session_id="s1", event="tool_call", min_interval_s=0)
    assert result is True


def test_record_checkin_creates_jsonl_file(monkeypatch, tmp_path):
    checkin_file, _ = _patch(monkeypatch, tmp_path)
    record_checkin_request(session_id="s1", event="tool_call", min_interval_s=0)
    assert checkin_file.exists()


def test_record_checkin_writes_valid_json_line(monkeypatch, tmp_path):
    checkin_file, _ = _patch(monkeypatch, tmp_path)
    record_checkin_request(session_id="sess_42", event="reply_sent", reason="curiosity", min_interval_s=0)
    line = checkin_file.read_text().splitlines()[0]
    row = json.loads(line)
    assert row["session_id"] == "sess_42"
    assert row["event"] == "reply_sent"
    assert row["reason"] == "curiosity"
    assert "created_at" in row


def test_record_checkin_created_at_is_recent(monkeypatch, tmp_path):
    checkin_file, _ = _patch(monkeypatch, tmp_path)
    before = time.time()
    record_checkin_request(session_id="s1", event="ev", min_interval_s=0)
    after = time.time()
    row = json.loads(checkin_file.read_text().splitlines()[0])
    assert before <= row["created_at"] <= after


def test_record_checkin_default_reason_empty(monkeypatch, tmp_path):
    checkin_file, _ = _patch(monkeypatch, tmp_path)
    record_checkin_request(session_id="s1", event="ev", min_interval_s=0)
    row = json.loads(checkin_file.read_text().splitlines()[0])
    assert row["reason"] == ""


def test_record_checkin_creates_parent_directories(monkeypatch, tmp_path):
    nested = tmp_path / "a" / "b" / "requests.jsonl"
    state = tmp_path / "a" / "b" / "state.json"
    monkeypatch.setattr(oc, "CHECKIN_FILE", nested)
    monkeypatch.setattr(oc, "STATE_FILE", state)
    record_checkin_request(session_id="s1", event="ev", min_interval_s=0)
    assert nested.exists()


# ---------------------------------------------------------------------------
# record_checkin_request — rate limiting
# ---------------------------------------------------------------------------


def test_record_checkin_rate_limited_returns_false(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    record_checkin_request(session_id="s1", event="ev", min_interval_s=9999)
    result = record_checkin_request(session_id="s2", event="ev2", min_interval_s=9999)
    assert result is False


def test_record_checkin_rate_limited_does_not_write_second_entry(monkeypatch, tmp_path):
    checkin_file, _ = _patch(monkeypatch, tmp_path)
    record_checkin_request(session_id="s1", event="ev", min_interval_s=9999)
    record_checkin_request(session_id="s2", event="ev2", min_interval_s=9999)
    lines = [l for l in checkin_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 1


def test_record_checkin_zero_interval_always_succeeds(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    r1 = record_checkin_request(session_id="s1", event="ev", min_interval_s=0)
    r2 = record_checkin_request(session_id="s2", event="ev2", min_interval_s=0)
    assert r1 is True
    assert r2 is True


def test_record_checkin_multiple_entries_appended(monkeypatch, tmp_path):
    checkin_file, _ = _patch(monkeypatch, tmp_path)
    for i in range(3):
        record_checkin_request(session_id=f"s{i}", event="ev", min_interval_s=0)
    lines = [l for l in checkin_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 3


# ---------------------------------------------------------------------------
# list_checkins — no file
# ---------------------------------------------------------------------------


def test_list_checkins_empty_when_no_file(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    assert list_checkins() == []


# ---------------------------------------------------------------------------
# list_checkins — with data
# ---------------------------------------------------------------------------


def test_list_checkins_returns_all(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    for i in range(4):
        record_checkin_request(session_id=f"s{i}", event="ev", min_interval_s=0)
    result = list_checkins(limit=10)
    assert len(result) == 4


def test_list_checkins_respects_limit(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    for i in range(10):
        record_checkin_request(session_id=f"s{i}", event="ev", min_interval_s=0)
    result = list_checkins(limit=3)
    assert len(result) <= 3


def test_list_checkins_returns_most_recent_first(monkeypatch, tmp_path):
    checkin_file, _ = _patch(monkeypatch, tmp_path)
    for i in range(5):
        record_checkin_request(session_id=f"s{i}", event=f"ev{i}", min_interval_s=0)
    result = list_checkins(limit=5)
    # list_checkins reverses the tail — most recently written is first
    assert result[0]["event"] == "ev4"


def test_list_checkins_each_entry_is_dict(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    record_checkin_request(session_id="s1", event="ev", min_interval_s=0)
    result = list_checkins()
    assert all(isinstance(r, dict) for r in result)


def test_list_checkins_entries_have_session_id(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    record_checkin_request(session_id="my_session", event="ev", min_interval_s=0)
    result = list_checkins()
    assert result[0]["session_id"] == "my_session"


def test_list_checkins_skips_corrupt_lines(monkeypatch, tmp_path):
    checkin_file, _ = _patch(monkeypatch, tmp_path)
    checkin_file.parent.mkdir(parents=True, exist_ok=True)
    # Write one corrupt and one valid line
    checkin_file.write_text('not json\n{"session_id":"s1","event":"ev","reason":"","created_at":1.0}\n', encoding="utf-8")
    result = list_checkins()
    assert len(result) == 1
    assert result[0]["session_id"] == "s1"
