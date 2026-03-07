"""Tests for lib/advisory_quarantine.py — advisory quarantine JSONL sink."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import lib.advisory_quarantine as aq
from lib.advisory_quarantine import (
    record_quarantine_item,
    _coerce_float01,
    _safe_dict,
    _sanitize_text,
    _tail_jsonl,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch(monkeypatch, tmp_path: Path) -> Path:
    qfile = tmp_path / "advisory_quarantine.jsonl"
    monkeypatch.setattr(aq, "QUARANTINE_FILE", qfile)
    return qfile


def _record(monkeypatch, tmp_path, **overrides):
    qfile = _patch(monkeypatch, tmp_path)
    kwargs = dict(source="test", stage="gate", reason="low_quality")
    kwargs.update(overrides)
    record_quarantine_item(**kwargs)
    return qfile


# ---------------------------------------------------------------------------
# _coerce_float01
# ---------------------------------------------------------------------------


def test_coerce_float01_normal():
    assert _coerce_float01(0.5) == 0.5


def test_coerce_float01_clamps_below_zero():
    assert _coerce_float01(-0.5) == 0.0


def test_coerce_float01_clamps_above_one():
    assert _coerce_float01(1.5) == 1.0


def test_coerce_float01_zero():
    assert _coerce_float01(0.0) == 0.0


def test_coerce_float01_one():
    assert _coerce_float01(1.0) == 1.0


def test_coerce_float01_nan_returns_none():
    import math
    assert _coerce_float01(math.nan) is None


def test_coerce_float01_string_invalid_returns_none():
    assert _coerce_float01("not a float") is None


def test_coerce_float01_none_returns_none():
    assert _coerce_float01(None) is None


def test_coerce_float01_rounds_to_4():
    result = _coerce_float01(0.123456789)
    assert result == round(0.123456789, 4)


# ---------------------------------------------------------------------------
# _safe_dict
# ---------------------------------------------------------------------------


def test_safe_dict_returns_dict_copy():
    d = {"a": 1}
    result = _safe_dict(d)
    assert result == {"a": 1}
    assert result is not d


def test_safe_dict_non_dict_returns_empty():
    assert _safe_dict("string") == {}
    assert _safe_dict(42) == {}
    assert _safe_dict(None) == {}
    assert _safe_dict([1, 2]) == {}


# ---------------------------------------------------------------------------
# _sanitize_text
# ---------------------------------------------------------------------------


def test_sanitize_text_short_unchanged():
    assert _sanitize_text("hello") == "hello"


def test_sanitize_text_at_limit_unchanged():
    text = "x" * 420
    assert _sanitize_text(text) == text


def test_sanitize_text_over_limit_truncated():
    text = "x" * 500
    result = _sanitize_text(text)
    assert len(result) <= 420
    assert result.endswith("...")


def test_sanitize_text_custom_limit():
    text = "a" * 100
    result = _sanitize_text(text, limit=50)
    assert len(result) <= 50
    assert result.endswith("...")


def test_sanitize_text_empty():
    assert _sanitize_text("") == ""


def test_sanitize_text_strips_whitespace():
    assert _sanitize_text("  hello  ") == "hello"


# ---------------------------------------------------------------------------
# _tail_jsonl
# ---------------------------------------------------------------------------


def test_tail_jsonl_empty_when_no_file(tmp_path):
    result = _tail_jsonl(tmp_path / "nonexistent.jsonl", 10)
    assert result == []


def test_tail_jsonl_zero_limit_returns_empty(tmp_path):
    f = tmp_path / "test.jsonl"
    f.write_text('{"a":1}\n', encoding="utf-8")
    assert _tail_jsonl(f, 0) == []


def test_tail_jsonl_reads_lines(tmp_path):
    f = tmp_path / "test.jsonl"
    f.write_text('{"a":1}\n{"b":2}\n', encoding="utf-8")
    result = _tail_jsonl(f, 10)
    assert len(result) == 2


def test_tail_jsonl_respects_limit(tmp_path):
    f = tmp_path / "test.jsonl"
    f.write_text("\n".join(f'{{"n":{i}}}' for i in range(10)) + "\n", encoding="utf-8")
    result = _tail_jsonl(f, 3)
    assert len(result) == 3


def test_tail_jsonl_skips_empty_lines(tmp_path):
    f = tmp_path / "test.jsonl"
    f.write_text('{"a":1}\n\n{"b":2}\n', encoding="utf-8")
    result = _tail_jsonl(f, 10)
    assert len(result) == 2


def test_tail_jsonl_skips_invalid_json(tmp_path):
    f = tmp_path / "test.jsonl"
    f.write_text('{"a":1}\nnot json\n{"b":2}\n', encoding="utf-8")
    result = _tail_jsonl(f, 10)
    assert len(result) == 2


def test_tail_jsonl_skips_non_dict_rows(tmp_path):
    f = tmp_path / "test.jsonl"
    f.write_text('{"a":1}\n[1,2,3]\n', encoding="utf-8")
    result = _tail_jsonl(f, 10)
    assert len(result) == 1
    assert result[0] == {"a": 1}


# ---------------------------------------------------------------------------
# record_quarantine_item — basic behaviour
# ---------------------------------------------------------------------------


def test_record_creates_file(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path)
    assert qfile.exists()


def test_record_writes_valid_json(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, source="pipe", stage="filter", reason="too_short")
    line = json.loads(qfile.read_text().splitlines()[0])
    assert isinstance(line, dict)


def test_record_contains_required_fields(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path)
    row = json.loads(qfile.read_text().splitlines()[0])
    for key in ("ts", "recorded_at", "source", "stage", "reason", "text_len", "text_snippet", "advisory_quality"):
        assert key in row


def test_record_source_stored(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, source="my_source")
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["source"] == "my_source"


def test_record_stage_stored(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, stage="my_stage")
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["stage"] == "my_stage"


def test_record_reason_stored(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, reason="low_score")
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["reason"] == "low_score"


def test_record_reason_truncated_at_120(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, reason="r" * 200)
    row = json.loads(qfile.read_text().splitlines()[0])
    assert len(row["reason"]) <= 120


def test_record_text_len_correct(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, text="hello world")
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["text_len"] == len("hello world")


def test_record_text_snippet_present(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, text="important advisory text")
    row = json.loads(qfile.read_text().splitlines()[0])
    assert "important advisory text" in row["text_snippet"]


def test_record_text_none_gives_zero_len(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, text=None)
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["text_len"] == 0


def test_record_advisory_quality_dict_stored(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, advisory_quality={"score": 0.3})
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["advisory_quality"] == {"score": 0.3}


def test_record_advisory_quality_none_gives_empty_dict(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, advisory_quality=None)
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["advisory_quality"] == {}


def test_record_advisory_readiness_stored_when_valid(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, advisory_readiness=0.75)
    row = json.loads(qfile.read_text().splitlines()[0])
    assert "advisory_readiness" in row
    assert abs(row["advisory_readiness"] - 0.75) < 0.001


def test_record_advisory_readiness_absent_when_none(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, advisory_readiness=None)
    row = json.loads(qfile.read_text().splitlines()[0])
    assert "advisory_readiness" not in row


def test_record_meta_stored(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, meta={"tool": "Bash"})
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["source_meta"] == {"tool": "Bash"}


def test_record_meta_none_not_stored(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, meta=None)
    row = json.loads(qfile.read_text().splitlines()[0])
    assert "source_meta" not in row


def test_record_extras_stored(monkeypatch, tmp_path):
    qfile = _record(monkeypatch, tmp_path, extras={"debug": True})
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["extras"] == {"debug": True}


def test_record_ts_is_recent(monkeypatch, tmp_path):
    before = time.time()
    qfile = _record(monkeypatch, tmp_path)
    after = time.time()
    row = json.loads(qfile.read_text().splitlines()[0])
    assert before <= row["ts"] <= after


# ---------------------------------------------------------------------------
# record_quarantine_item — appends multiple entries
# ---------------------------------------------------------------------------


def test_record_appends_multiple_entries(monkeypatch, tmp_path):
    qfile = _patch(monkeypatch, tmp_path)
    for i in range(5):
        record_quarantine_item(source=f"src{i}", stage="gate", reason="test")
    lines = [l for l in qfile.read_text().splitlines() if l.strip()]
    assert len(lines) == 5


# ---------------------------------------------------------------------------
# record_quarantine_item — cap enforcement
# ---------------------------------------------------------------------------


def test_record_respects_max_lines_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SPARK_ADVISORY_QUARANTINE_MAX_LINES", "5")
    qfile = _patch(monkeypatch, tmp_path)
    for i in range(10):
        record_quarantine_item(source=f"s{i}", stage="g", reason="r")
    lines = [l for l in qfile.read_text().splitlines() if l.strip()]
    assert len(lines) <= 5


# ---------------------------------------------------------------------------
# record_quarantine_item — empty/falsy inputs don't raise
# ---------------------------------------------------------------------------


def test_record_empty_source_uses_unknown(monkeypatch, tmp_path):
    qfile = _patch(monkeypatch, tmp_path)
    record_quarantine_item(source="", stage="gate", reason="test")
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["source"] == "unknown"


def test_record_empty_stage_uses_unknown(monkeypatch, tmp_path):
    qfile = _patch(monkeypatch, tmp_path)
    record_quarantine_item(source="src", stage="", reason="test")
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["stage"] == "unknown"


def test_record_empty_reason_uses_unspecified(monkeypatch, tmp_path):
    qfile = _patch(monkeypatch, tmp_path)
    record_quarantine_item(source="src", stage="gate", reason="")
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["reason"] == "unspecified"
