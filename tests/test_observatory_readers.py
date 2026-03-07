"""Tests for lib/observatory/readers.py

Covers the private helper functions (pure file I/O, no pipeline deps):
- _load_json(): valid JSON, BOM-safe, missing file, bad JSON, returns list too
- _tail_jsonl(): small file reads, last-N limit, skips bad lines, missing/empty
- _count_jsonl(): small file count, missing file, empty file
- _file_mtime(): existing file, missing file
- _file_size(): existing file, missing file, zero-byte file

Also covers the stage reader return contracts — each reader is called with
_SD patched to an empty tmp_path dir so no real ~/.spark data is needed:
- All 12 stage readers return a dict
- Each dict contains the expected 'stage' number and 'name' string
- read_all_stages() returns all 12 stage numbers as keys
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.observatory.readers as readers_mod
from lib.observatory.readers import (
    _count_jsonl,
    _file_mtime,
    _file_size,
    _load_json,
    _tail_jsonl,
    read_advisory,
    read_all_stages,
    read_chips,
    read_cognitive,
    read_eidos,
    read_event_capture,
    read_memory_capture,
    read_meta_ralph,
    read_pipeline,
    read_predictions,
    read_promotion,
    read_queue,
    read_tuneables,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_sd(monkeypatch, tmp_path: Path) -> Path:
    """Redirect _SD to tmp_path so readers don't touch ~/.spark."""
    monkeypatch.setattr(readers_mod, "_SD", tmp_path)
    return tmp_path


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# _load_json
# ---------------------------------------------------------------------------

def test_load_json_valid_dict(tmp_path):
    f = tmp_path / "data.json"
    f.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert _load_json(f) == {"a": 1}


def test_load_json_valid_list(tmp_path):
    f = tmp_path / "data.json"
    f.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert _load_json(f) == [1, 2, 3]


def test_load_json_bom_safe(tmp_path):
    f = tmp_path / "data.json"
    f.write_bytes(b"\xef\xbb\xbf" + json.dumps({"bom": True}).encode("utf-8"))
    assert _load_json(f) == {"bom": True}


def test_load_json_missing_file_returns_none(tmp_path):
    assert _load_json(tmp_path / "nonexistent.json") is None


def test_load_json_bad_json_returns_none(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("not json", encoding="utf-8")
    assert _load_json(f) is None


def test_load_json_empty_file_returns_none(tmp_path):
    f = tmp_path / "empty.json"
    f.write_text("", encoding="utf-8")
    assert _load_json(f) is None


# ---------------------------------------------------------------------------
# _tail_jsonl
# ---------------------------------------------------------------------------

def test_tail_jsonl_reads_all_lines(tmp_path):
    f = tmp_path / "events.jsonl"
    rows = [{"i": i} for i in range(5)]
    _write_jsonl(f, rows)
    result = _tail_jsonl(f, 10)
    assert result == rows


def test_tail_jsonl_respects_n_limit(tmp_path):
    f = tmp_path / "events.jsonl"
    rows = [{"i": i} for i in range(10)]
    _write_jsonl(f, rows)
    result = _tail_jsonl(f, 3)
    assert len(result) == 3
    assert result[-1] == {"i": 9}


def test_tail_jsonl_skips_bad_lines(tmp_path):
    f = tmp_path / "events.jsonl"
    f.write_text('{"ok": 1}\nnot-json\n{"also": "good"}\n', encoding="utf-8")
    result = _tail_jsonl(f, 10)
    assert len(result) == 2


def test_tail_jsonl_missing_file_returns_empty(tmp_path):
    assert _tail_jsonl(tmp_path / "missing.jsonl", 10) == []


def test_tail_jsonl_empty_file_returns_empty(tmp_path):
    f = tmp_path / "empty.jsonl"
    f.write_text("", encoding="utf-8")
    assert _tail_jsonl(f, 10) == []


def test_tail_jsonl_returns_list(tmp_path):
    f = tmp_path / "events.jsonl"
    _write_jsonl(f, [{"x": 1}])
    assert isinstance(_tail_jsonl(f, 5), list)


# ---------------------------------------------------------------------------
# _count_jsonl
# ---------------------------------------------------------------------------

def test_count_jsonl_counts_lines(tmp_path):
    f = tmp_path / "events.jsonl"
    _write_jsonl(f, [{"i": i} for i in range(7)])
    assert _count_jsonl(f) == 7


def test_count_jsonl_missing_file_returns_zero(tmp_path):
    assert _count_jsonl(tmp_path / "missing.jsonl") == 0


def test_count_jsonl_empty_file_returns_zero(tmp_path):
    f = tmp_path / "empty.jsonl"
    f.write_text("", encoding="utf-8")
    assert _count_jsonl(f) == 0


def test_count_jsonl_returns_int(tmp_path):
    f = tmp_path / "events.jsonl"
    _write_jsonl(f, [{"x": 1}])
    assert isinstance(_count_jsonl(f), int)


# ---------------------------------------------------------------------------
# _file_mtime
# ---------------------------------------------------------------------------

def test_file_mtime_existing_file_returns_float(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("hi")
    result = _file_mtime(f)
    assert isinstance(result, float)
    assert result > 0


def test_file_mtime_missing_file_returns_none(tmp_path):
    assert _file_mtime(tmp_path / "missing.txt") is None


# ---------------------------------------------------------------------------
# _file_size
# ---------------------------------------------------------------------------

def test_file_size_existing_file(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("hello")
    assert _file_size(f) == 5


def test_file_size_missing_file_returns_zero(tmp_path):
    assert _file_size(tmp_path / "missing.txt") == 0


def test_file_size_empty_file_returns_zero(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("")
    assert _file_size(f) == 0


def test_file_size_returns_int(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("data")
    assert isinstance(_file_size(f), int)


# ---------------------------------------------------------------------------
# Stage readers — return contract (empty spark dir)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reader,stage_num,stage_name", [
    (read_event_capture, 1, "Event Capture"),
    (read_queue,         2, "Queue"),
    (read_pipeline,      3, "Pipeline"),
    (read_memory_capture,4, "Memory Capture"),
    (read_meta_ralph,    5, "Meta-Ralph"),
    (read_cognitive,     6, "Cognitive Learner"),
    (read_eidos,         7, "EIDOS"),
    (read_advisory,      8, "Advisory"),
    (read_promotion,     9, "Promotion"),
    (read_chips,        10, "Chips"),
    (read_predictions,  11, "Predictions"),
    (read_tuneables,    12, "Tuneables"),
])
def test_stage_reader_returns_dict(reader, stage_num, stage_name, tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    result = reader()
    assert isinstance(result, dict)


@pytest.mark.parametrize("reader,stage_num,stage_name", [
    (read_event_capture, 1, "Event Capture"),
    (read_queue,         2, "Queue"),
    (read_pipeline,      3, "Pipeline"),
    (read_memory_capture,4, "Memory Capture"),
    (read_meta_ralph,    5, "Meta-Ralph"),
    (read_cognitive,     6, "Cognitive Learner"),
    (read_eidos,         7, "EIDOS"),
    (read_advisory,      8, "Advisory"),
    (read_promotion,     9, "Promotion"),
    (read_chips,        10, "Chips"),
    (read_predictions,  11, "Predictions"),
    (read_tuneables,    12, "Tuneables"),
])
def test_stage_reader_has_correct_stage_number(reader, stage_num, stage_name, tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    assert reader()["stage"] == stage_num


@pytest.mark.parametrize("reader,stage_num,stage_name", [
    (read_event_capture, 1, "Event Capture"),
    (read_queue,         2, "Queue"),
    (read_pipeline,      3, "Pipeline"),
    (read_memory_capture,4, "Memory Capture"),
    (read_meta_ralph,    5, "Meta-Ralph"),
    (read_cognitive,     6, "Cognitive Learner"),
    (read_eidos,         7, "EIDOS"),
    (read_advisory,      8, "Advisory"),
    (read_promotion,     9, "Promotion"),
    (read_chips,        10, "Chips"),
    (read_predictions,  11, "Predictions"),
    (read_tuneables,    12, "Tuneables"),
])
def test_stage_reader_has_correct_name(reader, stage_num, stage_name, tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    assert reader()["name"] == stage_name


# ---------------------------------------------------------------------------
# Stage readers — graceful empty defaults (no files present)
# ---------------------------------------------------------------------------

def test_read_event_capture_empty_defaults(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    d = read_event_capture()
    assert d["errors"] == []
    assert d["context_updated"] is False
    assert d["scheduler_running"] is False
    assert d["watchdog_status"] == "unknown"


def test_read_queue_empty_defaults(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    d = read_queue()
    assert d["events_file_size"] == 0
    assert d["overflow_exists"] is False


def test_read_pipeline_empty_defaults(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    d = read_pipeline()
    assert d["total_events_processed"] == 0
    assert d["recent_cycles"] == []


def test_read_memory_capture_empty_defaults(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    d = read_memory_capture()
    assert d["pending_count"] == 0
    assert d["recent_pending"] == []
    assert d["category_distribution"] == {}


def test_read_meta_ralph_empty_defaults(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    d = read_meta_ralph()
    assert d["learnings_count"] == 0
    assert d["total_roasted"] == 0
    assert d["recent_verdicts"] == []
    assert d["verdict_distribution"] == {}


def test_read_cognitive_empty_defaults(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    d = read_cognitive()
    assert d["total_insights"] == 0
    assert d["top_insights"] == []
    assert d["category_distribution"] == {}


def test_read_eidos_empty_defaults(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    d = read_eidos()
    assert d["db_exists"] is False
    assert d["episodes"] == 0
    assert d["steps"] == 0
    assert d["distillations"] == 0
    assert d["recent_distillations"] == []


def test_read_advisory_empty_defaults(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    d = read_advisory()
    assert d["total_advice_given"] == 0
    assert d["recent_advice"] == []
    assert d["recent_decisions"] == []


def test_read_promotion_empty_defaults(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    d = read_promotion()
    assert d["total_entries"] == 0
    assert d["recent_promotions"] == []


def test_read_chips_empty_defaults(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    d = read_chips()
    assert d["chips"] == []
    assert d["total_chips"] == 0
    assert d["total_size"] == 0


def test_read_predictions_empty_defaults(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    d = read_predictions()
    assert d["predictions_count"] == 0
    assert d["outcomes_count"] == 0
    assert d["recent_outcomes"] == []


def test_read_tuneables_source_is_valid_value(tmp_path, monkeypatch):
    # read_tuneables also checks the versioned config/tuneables.json in the
    # repo, so 'source' may be 'versioned' even with an empty _SD.
    _patch_sd(monkeypatch, tmp_path)
    d = read_tuneables()
    assert d["source"] in ("none", "runtime", "versioned")


def test_read_tuneables_sections_is_dict(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    assert isinstance(read_tuneables()["sections"], dict)


# ---------------------------------------------------------------------------
# read_all_stages
# ---------------------------------------------------------------------------

def test_read_all_stages_returns_dict(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    result = read_all_stages()
    assert isinstance(result, dict)


def test_read_all_stages_has_all_12_keys(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    result = read_all_stages()
    assert set(result.keys()) == set(range(1, 13))


def test_read_all_stages_each_value_is_dict(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    for stage_num, data in read_all_stages().items():
        assert isinstance(data, dict), f"Stage {stage_num} returned non-dict"


def test_read_all_stages_stage_numbers_match_keys(tmp_path, monkeypatch):
    _patch_sd(monkeypatch, tmp_path)
    for key, data in read_all_stages().items():
        assert data["stage"] == key
