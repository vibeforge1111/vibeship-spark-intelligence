"""Tests for lib/ingest_validation.py — 35 tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.ingest_validation as iv
from lib.queue import EventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_row(**overrides) -> dict:
    row = {
        "event_type": EventType.PRE_TOOL.value,
        "session_id": "sess-abc",
        "timestamp": time.time(),
        "data": {"key": "value"},
    }
    row.update(overrides)
    return row


def _write_events(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# _tail_lines
# ---------------------------------------------------------------------------

class TestTailLines:
    def test_returns_last_n_lines(self, tmp_path, monkeypatch):
        monkeypatch.setattr(iv, "log_debug", lambda *a: None)
        p = tmp_path / "events.jsonl"
        lines = [f"line{i}\n" for i in range(20)]
        p.write_text("".join(lines))
        result = list(iv._tail_lines(p, 5))
        assert len(result) == 5

    def test_returns_all_when_fewer_than_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(iv, "log_debug", lambda *a: None)
        p = tmp_path / "events.jsonl"
        p.write_text("a\nb\nc\n")
        result = list(iv._tail_lines(p, 100))
        assert len(result) == 3

    def test_returns_empty_deque_on_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(iv, "log_debug", lambda *a: None)
        result = iv._tail_lines(tmp_path / "nope.jsonl", 10)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# _validate_event_row
# ---------------------------------------------------------------------------

class TestValidateEventRow:
    def test_valid_row_returns_empty_string(self):
        assert iv._validate_event_row(_valid_row()) == ""

    def test_not_a_dict_returns_not_object(self):
        assert iv._validate_event_row("string") == "not_object"  # type: ignore
        assert iv._validate_event_row(None) == "not_object"  # type: ignore
        assert iv._validate_event_row([]) == "not_object"  # type: ignore

    def test_missing_event_type_field(self):
        row = _valid_row()
        del row["event_type"]
        assert iv._validate_event_row(row) == "missing_event_type"

    def test_invalid_event_type_value(self):
        row = _valid_row(event_type="NOT_A_REAL_TYPE")
        assert iv._validate_event_row(row) == "invalid_event_type"

    def test_all_valid_event_types_accepted(self):
        for et in EventType:
            row = _valid_row(event_type=et.value)
            assert iv._validate_event_row(row) == "", f"EventType {et} should be valid"

    def test_missing_session_id(self):
        row = _valid_row()
        del row["session_id"]
        assert iv._validate_event_row(row) == "invalid_session_id"

    def test_empty_session_id(self):
        row = _valid_row(session_id="")
        assert iv._validate_event_row(row) == "invalid_session_id"

    def test_whitespace_only_session_id(self):
        row = _valid_row(session_id="   ")
        assert iv._validate_event_row(row) == "invalid_session_id"

    def test_non_string_session_id(self):
        row = _valid_row(session_id=123)
        assert iv._validate_event_row(row) == "invalid_session_id"

    def test_zero_timestamp(self):
        row = _valid_row(timestamp=0)
        assert iv._validate_event_row(row) == "invalid_timestamp"

    def test_negative_timestamp(self):
        row = _valid_row(timestamp=-1.0)
        assert iv._validate_event_row(row) == "invalid_timestamp"

    def test_none_timestamp(self):
        row = _valid_row(timestamp=None)
        assert iv._validate_event_row(row) == "invalid_timestamp"

    def test_non_numeric_timestamp(self):
        row = _valid_row(timestamp="not-a-number")
        assert iv._validate_event_row(row) == "invalid_timestamp"

    def test_missing_data_field(self):
        row = _valid_row()
        del row["data"]
        assert iv._validate_event_row(row) == "invalid_data"

    def test_null_data_field(self):
        row = _valid_row(data=None)
        assert iv._validate_event_row(row) == "invalid_data"

    def test_data_as_list_invalid(self):
        row = _valid_row(data=[1, 2, 3])
        assert iv._validate_event_row(row) == "invalid_data"

    def test_invalid_tool_input_type(self):
        row = _valid_row(tool_input="string-not-dict")
        assert iv._validate_event_row(row) == "invalid_tool_input"

    def test_tool_input_none_is_valid(self):
        row = _valid_row(tool_input=None)
        assert iv._validate_event_row(row) == ""

    def test_tool_input_dict_is_valid(self):
        row = _valid_row(tool_input={"cmd": "ls"})
        assert iv._validate_event_row(row) == ""

    def test_invalid_tool_name_type(self):
        row = _valid_row(tool_name=42)
        assert iv._validate_event_row(row) == "invalid_tool_name"

    def test_tool_name_string_valid(self):
        row = _valid_row(tool_name="Bash")
        assert iv._validate_event_row(row) == ""

    def test_tool_name_none_valid(self):
        row = _valid_row(tool_name=None)
        assert iv._validate_event_row(row) == ""


# ---------------------------------------------------------------------------
# scan_queue_events
# ---------------------------------------------------------------------------

class TestScanQueueEvents:
    def _patch(self, monkeypatch, events_file: Path):
        monkeypatch.setattr(iv, "EVENTS_FILE", events_file)
        monkeypatch.setattr(iv, "log_debug", lambda *a: None)

    def test_returns_zero_stats_when_file_missing(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path / "nope.jsonl")
        stats = iv.scan_queue_events()
        assert stats["processed"] == 0
        assert stats["valid"] == 0
        assert stats["invalid"] == 0

    def test_counts_valid_rows(self, tmp_path, monkeypatch):
        ef = tmp_path / "events.jsonl"
        _write_events(ef, [_valid_row() for _ in range(5)])
        self._patch(monkeypatch, ef)
        stats = iv.scan_queue_events()
        assert stats["valid"] == 5
        assert stats["invalid"] == 0

    def test_counts_invalid_json_rows(self, tmp_path, monkeypatch):
        ef = tmp_path / "events.jsonl"
        ef.write_text("BAD JSON\nMORE BAD\n")
        self._patch(monkeypatch, ef)
        stats = iv.scan_queue_events()
        assert stats["invalid"] == 2
        assert stats["reasons"].get("invalid_json", 0) == 2

    def test_counts_schema_violation_rows(self, tmp_path, monkeypatch):
        ef = tmp_path / "events.jsonl"
        _write_events(ef, [_valid_row(event_type="BOGUS")])
        self._patch(monkeypatch, ef)
        stats = iv.scan_queue_events()
        assert stats["invalid"] == 1

    def test_mixed_valid_and_invalid(self, tmp_path, monkeypatch):
        ef = tmp_path / "events.jsonl"
        rows = [_valid_row(), _valid_row(event_type="BAD"), _valid_row()]
        _write_events(ef, rows)
        self._patch(monkeypatch, ef)
        stats = iv.scan_queue_events()
        assert stats["valid"] == 2
        assert stats["invalid"] == 1

    def test_window_limits_rows_scanned(self, tmp_path, monkeypatch):
        ef = tmp_path / "events.jsonl"
        _write_events(ef, [_valid_row() for _ in range(100)])
        self._patch(monkeypatch, ef)
        stats = iv.scan_queue_events(limit=10)
        assert stats["processed"] <= 10


# ---------------------------------------------------------------------------
# write_ingest_report
# ---------------------------------------------------------------------------

class TestWriteIngestReport:
    def test_writes_json_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(iv, "log_debug", lambda *a: None)
        report_path = tmp_path / "report.json"
        stats = {"valid": 5, "invalid": 2}
        iv.write_ingest_report(stats, report_path)
        loaded = json.loads(report_path.read_text())
        assert loaded["valid"] == 5

    def test_creates_parent_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(iv, "log_debug", lambda *a: None)
        nested = tmp_path / "a" / "b" / "report.json"
        iv.write_ingest_report({"x": 1}, nested)
        assert nested.exists()

    def test_pretty_printed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(iv, "log_debug", lambda *a: None)
        p = tmp_path / "r.json"
        iv.write_ingest_report({"a": 1}, p)
        content = p.read_text()
        # indent=2 means newlines in output
        assert "\n" in content
