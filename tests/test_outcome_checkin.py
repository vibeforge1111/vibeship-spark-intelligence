"""Tests for lib/outcome_checkin.py

Covers:
- _load_state(): missing file → {}, reads existing file, handles corrupt file
- _save_state(): creates directories, writes JSON, overwrites existing
- record_checkin_request(): returns True on first call, writes JSONL row,
  returns False when rate-limited (within min_interval_s), returns True
  when interval elapsed, row includes session_id/event/reason/created_at
- list_checkins(): missing file → [], returns rows in reverse order (newest first),
  limit respected, handles corrupt lines gracefully
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.outcome_checkin as oc
from lib.outcome_checkin import (
    _load_state,
    _save_state,
    record_checkin_request,
    list_checkins,
)


# ---------------------------------------------------------------------------
# _load_state
# ---------------------------------------------------------------------------

def test_load_state_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "STATE_FILE", tmp_path / "missing.json")
    assert _load_state() == {}


def test_load_state_reads_existing_file(tmp_path, monkeypatch):
    f = tmp_path / "state.json"
    f.write_text(json.dumps({"last_ts": 12345.0}), encoding="utf-8")
    monkeypatch.setattr(oc, "STATE_FILE", f)
    state = _load_state()
    assert state["last_ts"] == 12345.0


def test_load_state_corrupt_returns_empty(tmp_path, monkeypatch):
    f = tmp_path / "state.json"
    f.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(oc, "STATE_FILE", f)
    assert _load_state() == {}


# ---------------------------------------------------------------------------
# _save_state
# ---------------------------------------------------------------------------

def test_save_state_creates_directories(tmp_path, monkeypatch):
    f = tmp_path / "nested" / "state.json"
    monkeypatch.setattr(oc, "STATE_FILE", f)
    _save_state({"key": "val"})
    assert f.exists()


def test_save_state_writes_json(tmp_path, monkeypatch):
    f = tmp_path / "state.json"
    monkeypatch.setattr(oc, "STATE_FILE", f)
    _save_state({"last_ts": 99.0})
    data = json.loads(f.read_text())
    assert data["last_ts"] == 99.0


def test_save_state_overwrites_existing(tmp_path, monkeypatch):
    f = tmp_path / "state.json"
    f.write_text(json.dumps({"last_ts": 1.0}), encoding="utf-8")
    monkeypatch.setattr(oc, "STATE_FILE", f)
    _save_state({"last_ts": 999.0})
    data = json.loads(f.read_text())
    assert data["last_ts"] == 999.0


# ---------------------------------------------------------------------------
# record_checkin_request
# ---------------------------------------------------------------------------

def test_record_checkin_first_call_returns_true(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "CHECKIN_FILE", tmp_path / "checkins.jsonl")
    monkeypatch.setattr(oc, "STATE_FILE", tmp_path / "state.json")
    result = record_checkin_request(session_id="s1", event="session_end", min_interval_s=0)
    assert result is True


def test_record_checkin_creates_jsonl_file(tmp_path, monkeypatch):
    f = tmp_path / "checkins.jsonl"
    monkeypatch.setattr(oc, "CHECKIN_FILE", f)
    monkeypatch.setattr(oc, "STATE_FILE", tmp_path / "state.json")
    record_checkin_request(session_id="s1", event="session_end", min_interval_s=0)
    assert f.exists()


def test_record_checkin_writes_row_fields(tmp_path, monkeypatch):
    f = tmp_path / "checkins.jsonl"
    monkeypatch.setattr(oc, "CHECKIN_FILE", f)
    monkeypatch.setattr(oc, "STATE_FILE", tmp_path / "state.json")
    record_checkin_request(session_id="sess-abc", event="stop", reason="done", min_interval_s=0)
    row = json.loads(f.read_text().strip())
    assert row["session_id"] == "sess-abc"
    assert row["event"] == "stop"
    assert row["reason"] == "done"
    assert "created_at" in row


def test_record_checkin_rate_limited_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "CHECKIN_FILE", tmp_path / "checkins.jsonl")
    monkeypatch.setattr(oc, "STATE_FILE", tmp_path / "state.json")
    record_checkin_request(session_id="s1", event="end", min_interval_s=3600)
    result = record_checkin_request(session_id="s1", event="end", min_interval_s=3600)
    assert result is False


def test_record_checkin_allowed_after_interval(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(oc, "CHECKIN_FILE", tmp_path / "checkins.jsonl")
    monkeypatch.setattr(oc, "STATE_FILE", state_file)
    # Write an old timestamp
    state_file.write_text(json.dumps({"last_ts": time.time() - 7200}), encoding="utf-8")
    result = record_checkin_request(session_id="s1", event="end", min_interval_s=3600)
    assert result is True


def test_record_checkin_appends_multiple(tmp_path, monkeypatch):
    f = tmp_path / "checkins.jsonl"
    monkeypatch.setattr(oc, "CHECKIN_FILE", f)
    monkeypatch.setattr(oc, "STATE_FILE", tmp_path / "state.json")
    record_checkin_request(session_id="s1", event="e1", min_interval_s=0)
    record_checkin_request(session_id="s2", event="e2", min_interval_s=0)
    lines = f.read_text().strip().splitlines()
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# list_checkins
# ---------------------------------------------------------------------------

def test_list_checkins_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "CHECKIN_FILE", tmp_path / "missing.jsonl")
    assert list_checkins() == []


def test_list_checkins_returns_list(tmp_path, monkeypatch):
    f = tmp_path / "checkins.jsonl"
    f.write_text(json.dumps({"session_id": "s1", "event": "end"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(oc, "CHECKIN_FILE", f)
    assert isinstance(list_checkins(), list)


def test_list_checkins_returns_rows(tmp_path, monkeypatch):
    f = tmp_path / "checkins.jsonl"
    f.write_text(
        json.dumps({"event": "a"}) + "\n" + json.dumps({"event": "b"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(oc, "CHECKIN_FILE", f)
    rows = list_checkins(limit=10)
    assert len(rows) == 2


def test_list_checkins_newest_first(tmp_path, monkeypatch):
    f = tmp_path / "checkins.jsonl"
    f.write_text(
        json.dumps({"event": "first"}) + "\n" + json.dumps({"event": "second"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(oc, "CHECKIN_FILE", f)
    rows = list_checkins()
    # Reversed: second row first
    assert rows[0]["event"] == "second"


def test_list_checkins_limit_respected(tmp_path, monkeypatch):
    f = tmp_path / "checkins.jsonl"
    lines = "\n".join(json.dumps({"event": f"e{i}"}) for i in range(20))
    f.write_text(lines + "\n", encoding="utf-8")
    monkeypatch.setattr(oc, "CHECKIN_FILE", f)
    assert len(list_checkins(limit=5)) == 5


def test_list_checkins_skips_corrupt_lines(tmp_path, monkeypatch):
    f = tmp_path / "checkins.jsonl"
    f.write_text(
        "not-json\n" + json.dumps({"event": "good"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(oc, "CHECKIN_FILE", f)
    rows = list_checkins()
    assert len(rows) == 1
    assert rows[0]["event"] == "good"
