"""Tests for lib/ingest_validation.py

Covers:
- _validate_event_row(): returns "" for valid rows; returns specific error
  codes for not-a-dict, missing event_type, invalid event_type enum value,
  invalid session_id, invalid/zero/negative timestamp, missing/non-dict data,
  invalid tool_input type, invalid tool_name type; optional fields absent OK
- scan_queue_events(): returns stats dict with required keys when file missing;
  correctly counts valid/invalid when given a file with valid and invalid rows
- write_ingest_report(): creates file, content is valid JSON
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.ingest_validation as iv
from lib.ingest_validation import _validate_event_row, scan_queue_events, write_ingest_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_row(**overrides) -> dict:
    row = {
        "event_type": "user_prompt",
        "session_id": "sess-001",
        "timestamp": 1_700_000_000.0,
        "data": {"text": "hello"},
    }
    row.update(overrides)
    return row


def _write_jsonl(path: Path, rows: list) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# _validate_event_row — happy path
# ---------------------------------------------------------------------------

def test_validate_valid_row_returns_empty_string():
    assert _validate_event_row(_valid_row()) == ""


def test_validate_all_event_types_accepted():
    valid_types = ["session_start", "session_end", "user_prompt", "pre_tool",
                   "post_tool", "post_tool_failure", "stop", "learning", "error"]
    for et in valid_types:
        assert _validate_event_row(_valid_row(event_type=et)) == "", f"Failed for {et}"


def test_validate_optional_tool_input_absent_ok():
    row = _valid_row()
    row.pop("tool_input", None)
    assert _validate_event_row(row) == ""


def test_validate_optional_tool_name_absent_ok():
    row = _valid_row()
    row.pop("tool_name", None)
    assert _validate_event_row(row) == ""


def test_validate_tool_input_dict_ok():
    assert _validate_event_row(_valid_row(tool_input={"cmd": "ls"})) == ""


def test_validate_tool_name_string_ok():
    assert _validate_event_row(_valid_row(tool_name="bash")) == ""


def test_validate_tool_input_none_ok():
    assert _validate_event_row(_valid_row(tool_input=None)) == ""


def test_validate_tool_name_none_ok():
    assert _validate_event_row(_valid_row(tool_name=None)) == ""


# ---------------------------------------------------------------------------
# _validate_event_row — not a dict
# ---------------------------------------------------------------------------

def test_validate_not_dict_returns_not_object():
    assert _validate_event_row("string") == "not_object"


def test_validate_list_returns_not_object():
    assert _validate_event_row([1, 2, 3]) == "not_object"


def test_validate_none_returns_not_object():
    assert _validate_event_row(None) == "not_object"


# ---------------------------------------------------------------------------
# _validate_event_row — missing event_type
# ---------------------------------------------------------------------------

def test_validate_missing_event_type():
    row = _valid_row()
    del row["event_type"]
    assert _validate_event_row(row) == "missing_event_type"


# ---------------------------------------------------------------------------
# _validate_event_row — invalid event_type
# ---------------------------------------------------------------------------

def test_validate_invalid_event_type_returns_invalid():
    assert _validate_event_row(_valid_row(event_type="bogus_type")) == "invalid_event_type"


def test_validate_empty_event_type_returns_invalid():
    assert _validate_event_row(_valid_row(event_type="")) == "invalid_event_type"


# ---------------------------------------------------------------------------
# _validate_event_row — session_id
# ---------------------------------------------------------------------------

def test_validate_missing_session_id():
    row = _valid_row()
    del row["session_id"]
    assert _validate_event_row(row) == "invalid_session_id"


def test_validate_empty_session_id():
    assert _validate_event_row(_valid_row(session_id="")) == "invalid_session_id"


def test_validate_whitespace_session_id():
    assert _validate_event_row(_valid_row(session_id="   ")) == "invalid_session_id"


def test_validate_non_string_session_id():
    assert _validate_event_row(_valid_row(session_id=123)) == "invalid_session_id"


# ---------------------------------------------------------------------------
# _validate_event_row — timestamp
# ---------------------------------------------------------------------------

def test_validate_zero_timestamp():
    assert _validate_event_row(_valid_row(timestamp=0)) == "invalid_timestamp"


def test_validate_negative_timestamp():
    assert _validate_event_row(_valid_row(timestamp=-1.0)) == "invalid_timestamp"


def test_validate_none_timestamp():
    assert _validate_event_row(_valid_row(timestamp=None)) == "invalid_timestamp"


def test_validate_non_numeric_timestamp():
    assert _validate_event_row(_valid_row(timestamp="yesterday")) == "invalid_timestamp"


def test_validate_positive_timestamp_ok():
    assert _validate_event_row(_valid_row(timestamp=1.0)) == ""


# ---------------------------------------------------------------------------
# _validate_event_row — data field
# ---------------------------------------------------------------------------

def test_validate_none_data():
    assert _validate_event_row(_valid_row(data=None)) == "invalid_data"


def test_validate_list_data():
    assert _validate_event_row(_valid_row(data=[1, 2, 3])) == "invalid_data"


def test_validate_string_data():
    assert _validate_event_row(_valid_row(data="text")) == "invalid_data"


def test_validate_missing_data():
    row = _valid_row()
    del row["data"]
    assert _validate_event_row(row) == "invalid_data"


def test_validate_empty_dict_data_ok():
    assert _validate_event_row(_valid_row(data={})) == ""


# ---------------------------------------------------------------------------
# _validate_event_row — optional tool_input / tool_name
# ---------------------------------------------------------------------------

def test_validate_tool_input_non_dict_returns_invalid():
    assert _validate_event_row(_valid_row(tool_input="string")) == "invalid_tool_input"


def test_validate_tool_input_list_returns_invalid():
    assert _validate_event_row(_valid_row(tool_input=[1, 2])) == "invalid_tool_input"


def test_validate_tool_name_non_string_returns_invalid():
    assert _validate_event_row(_valid_row(tool_name=99)) == "invalid_tool_name"


def test_validate_tool_name_list_returns_invalid():
    assert _validate_event_row(_valid_row(tool_name=["bash"])) == "invalid_tool_name"


# ---------------------------------------------------------------------------
# scan_queue_events — structure
# ---------------------------------------------------------------------------

def test_scan_queue_events_returns_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(iv, "EVENTS_FILE", tmp_path / "missing.jsonl")
    result = scan_queue_events()
    assert isinstance(result, dict)


def test_scan_queue_events_has_required_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(iv, "EVENTS_FILE", tmp_path / "missing.jsonl")
    result = scan_queue_events()
    for key in ("checked_at", "window", "processed", "valid", "invalid", "reasons"):
        assert key in result


def test_scan_queue_events_missing_file_zero_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(iv, "EVENTS_FILE", tmp_path / "missing.jsonl")
    result = scan_queue_events()
    assert result["processed"] == 0
    assert result["valid"] == 0
    assert result["invalid"] == 0


# ---------------------------------------------------------------------------
# scan_queue_events — counting
# ---------------------------------------------------------------------------

def test_scan_queue_events_counts_valid(tmp_path, monkeypatch):
    events_file = tmp_path / "events.jsonl"
    _write_jsonl(events_file, [_valid_row(), _valid_row()])
    monkeypatch.setattr(iv, "EVENTS_FILE", events_file)
    result = scan_queue_events()
    assert result["valid"] == 2


def test_scan_queue_events_counts_invalid_event_type(tmp_path, monkeypatch):
    events_file = tmp_path / "events.jsonl"
    _write_jsonl(events_file, [_valid_row(event_type="bogus")])
    monkeypatch.setattr(iv, "EVENTS_FILE", events_file)
    result = scan_queue_events()
    assert result["invalid"] == 1


def test_scan_queue_events_counts_invalid_json(tmp_path, monkeypatch):
    events_file = tmp_path / "events.jsonl"
    events_file.write_text("not-json\n", encoding="utf-8")
    monkeypatch.setattr(iv, "EVENTS_FILE", events_file)
    result = scan_queue_events()
    assert result["invalid"] == 1
    assert "invalid_json" in result["reasons"]


def test_scan_queue_events_mixed_valid_invalid(tmp_path, monkeypatch):
    events_file = tmp_path / "events.jsonl"
    rows = [
        _valid_row(),
        _valid_row(event_type="bad"),
        _valid_row(),
    ]
    _write_jsonl(events_file, rows)
    monkeypatch.setattr(iv, "EVENTS_FILE", events_file)
    result = scan_queue_events()
    assert result["valid"] == 2
    assert result["invalid"] == 1


def test_scan_queue_events_processed_equals_total(tmp_path, monkeypatch):
    events_file = tmp_path / "events.jsonl"
    rows = [_valid_row(), _valid_row(session_id=""), _valid_row()]
    _write_jsonl(events_file, rows)
    monkeypatch.setattr(iv, "EVENTS_FILE", events_file)
    result = scan_queue_events()
    assert result["processed"] == result["valid"] + result["invalid"]


# ---------------------------------------------------------------------------
# write_ingest_report
# ---------------------------------------------------------------------------

def test_write_ingest_report_creates_file(tmp_path):
    out = tmp_path / "report.json"
    write_ingest_report({"valid": 5, "invalid": 1}, path=out)
    assert out.exists()


def test_write_ingest_report_content_is_valid_json(tmp_path):
    out = tmp_path / "report.json"
    write_ingest_report({"valid": 3, "reasons": {}}, path=out)
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert "valid" in parsed


def test_write_ingest_report_creates_parent_dirs(tmp_path):
    out = tmp_path / "nested" / "dir" / "report.json"
    write_ingest_report({}, path=out)
    assert out.exists()
