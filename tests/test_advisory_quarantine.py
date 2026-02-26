"""Tests for lib/advisory_quarantine.py

Covers:
- _coerce_float01(): numeric coercion to [0.0, 1.0], NaN, None, strings
- _safe_dict(): dict pass-through, non-dict fallback to {}
- _sanitize_text(): truncation at limit with ellipsis, edge cases
- _tail_jsonl(): reads valid jsonl, skips malformed lines, handles missing file
- _append_jsonl_capped(): appends entries, caps file at max_lines
- record_quarantine_item(): end-to-end write with all field combinations
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from lib.advisory_quarantine import (
    _append_jsonl_capped,
    _coerce_float01,
    _safe_dict,
    _sanitize_text,
    _tail_jsonl,
    record_quarantine_item,
)


# ---------------------------------------------------------------------------
# _coerce_float01
# ---------------------------------------------------------------------------

def test_coerce_float01_midrange_value():
    assert _coerce_float01(0.5) == pytest.approx(0.5)


def test_coerce_float01_zero():
    assert _coerce_float01(0) == pytest.approx(0.0)


def test_coerce_float01_one():
    assert _coerce_float01(1) == pytest.approx(1.0)


def test_coerce_float01_below_zero_clamped():
    assert _coerce_float01(-0.5) == pytest.approx(0.0)


def test_coerce_float01_above_one_clamped():
    assert _coerce_float01(1.5) == pytest.approx(1.0)


def test_coerce_float01_large_negative_clamped():
    assert _coerce_float01(-999) == pytest.approx(0.0)


def test_coerce_float01_large_positive_clamped():
    assert _coerce_float01(999) == pytest.approx(1.0)


def test_coerce_float01_from_string():
    assert _coerce_float01("0.75") == pytest.approx(0.75)


def test_coerce_float01_from_invalid_string():
    assert _coerce_float01("not_a_number") is None


def test_coerce_float01_none_returns_none():
    assert _coerce_float01(None) is None


def test_coerce_float01_nan_returns_none():
    assert _coerce_float01(float("nan")) is None


def test_coerce_float01_rounded_to_4_places():
    result = _coerce_float01(0.123456789)
    assert result == pytest.approx(0.1235, abs=1e-4)


def test_coerce_float01_exact_boundary_values():
    assert _coerce_float01(0.0) == pytest.approx(0.0)
    assert _coerce_float01(1.0) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _safe_dict
# ---------------------------------------------------------------------------

def test_safe_dict_with_dict_returns_copy():
    d = {"key": "value", "num": 42}
    result = _safe_dict(d)
    assert result == d


def test_safe_dict_returns_new_object():
    d = {"key": "value"}
    result = _safe_dict(d)
    assert result is not d


def test_safe_dict_with_none_returns_empty():
    assert _safe_dict(None) == {}


def test_safe_dict_with_string_returns_empty():
    assert _safe_dict("not_a_dict") == {}


def test_safe_dict_with_list_returns_empty():
    assert _safe_dict([1, 2, 3]) == {}


def test_safe_dict_with_int_returns_empty():
    assert _safe_dict(42) == {}


def test_safe_dict_with_empty_dict():
    assert _safe_dict({}) == {}


# ---------------------------------------------------------------------------
# _sanitize_text
# ---------------------------------------------------------------------------

def test_sanitize_text_short_string_unchanged():
    assert _sanitize_text("hello") == "hello"


def test_sanitize_text_empty_string():
    assert _sanitize_text("") == ""


def test_sanitize_text_none_becomes_empty():
    assert _sanitize_text(None) == ""


def test_sanitize_text_strips_whitespace():
    assert _sanitize_text("  hello  ") == "hello"


def test_sanitize_text_at_exact_limit_unchanged():
    text = "x" * 420
    assert _sanitize_text(text) == text


def test_sanitize_text_over_limit_truncated():
    text = "a" * 500
    result = _sanitize_text(text)
    assert len(result) <= 420
    assert result.endswith("...")


def test_sanitize_text_custom_limit():
    text = "abcdefghij"  # 10 chars
    result = _sanitize_text(text, limit=5)
    assert len(result) <= 5
    assert result.endswith("...")


def test_sanitize_text_custom_limit_short_text_unchanged():
    assert _sanitize_text("hi", limit=10) == "hi"


# ---------------------------------------------------------------------------
# _tail_jsonl
# ---------------------------------------------------------------------------

def test_tail_jsonl_reads_valid_lines(tmp_path):
    f = tmp_path / "events.jsonl"
    rows = [{"a": 1}, {"b": 2}, {"c": 3}]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    result = _tail_jsonl(f, 10)
    assert result == rows


def test_tail_jsonl_respects_limit(tmp_path):
    f = tmp_path / "events.jsonl"
    rows = [{"i": i} for i in range(10)]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    result = _tail_jsonl(f, 3)
    assert len(result) == 3
    assert result[-1] == {"i": 9}


def test_tail_jsonl_skips_malformed_lines(tmp_path):
    f = tmp_path / "events.jsonl"
    f.write_text('{"good": 1}\nnot-json\n{"also": "good"}\n', encoding="utf-8")
    result = _tail_jsonl(f, 10)
    assert len(result) == 2
    assert {"good": 1} in result
    assert {"also": "good"} in result


def test_tail_jsonl_skips_non_dict_json(tmp_path):
    f = tmp_path / "events.jsonl"
    f.write_text('{"ok": 1}\n[1, 2, 3]\n', encoding="utf-8")
    result = _tail_jsonl(f, 10)
    assert result == [{"ok": 1}]


def test_tail_jsonl_missing_file_returns_empty(tmp_path):
    result = _tail_jsonl(tmp_path / "nonexistent.jsonl", 10)
    assert result == []


def test_tail_jsonl_zero_limit_returns_empty(tmp_path):
    f = tmp_path / "events.jsonl"
    f.write_text('{"a": 1}\n', encoding="utf-8")
    assert _tail_jsonl(f, 0) == []


def test_tail_jsonl_empty_file(tmp_path):
    f = tmp_path / "events.jsonl"
    f.write_text("", encoding="utf-8")
    assert _tail_jsonl(f, 10) == []


# ---------------------------------------------------------------------------
# _append_jsonl_capped
# ---------------------------------------------------------------------------

def test_append_jsonl_capped_creates_file(tmp_path):
    f = tmp_path / "out.jsonl"
    _append_jsonl_capped(f, {"x": 1}, max_lines=100)
    assert f.exists()
    rows = [json.loads(line) for line in f.read_text().splitlines() if line]
    assert rows == [{"x": 1}]


def test_append_jsonl_capped_appends_multiple(tmp_path):
    f = tmp_path / "out.jsonl"
    for i in range(3):
        _append_jsonl_capped(f, {"i": i}, max_lines=100)
    rows = [json.loads(line) for line in f.read_text().splitlines() if line]
    assert len(rows) == 3


def test_append_jsonl_capped_trims_when_over_limit(tmp_path):
    f = tmp_path / "out.jsonl"
    # Pre-fill with 10 entries
    f.write_text("\n".join(json.dumps({"i": i}) for i in range(10)) + "\n", encoding="utf-8")
    # Append one more with max_lines=5 → should trim to 5
    _append_jsonl_capped(f, {"i": 10}, max_lines=5)
    rows = [json.loads(line) for line in f.read_text().splitlines() if line]
    assert len(rows) == 5
    # Should keep the most recent entries
    assert rows[-1] == {"i": 10}


def test_append_jsonl_capped_creates_parent_dirs(tmp_path):
    f = tmp_path / "deep" / "nested" / "out.jsonl"
    _append_jsonl_capped(f, {"x": 1}, max_lines=10)
    assert f.exists()


def test_append_jsonl_capped_zero_max_lines_still_appends(tmp_path):
    f = tmp_path / "out.jsonl"
    _append_jsonl_capped(f, {"x": 1}, max_lines=0)
    assert f.exists()


# ---------------------------------------------------------------------------
# record_quarantine_item — end-to-end
# ---------------------------------------------------------------------------

def test_record_quarantine_item_writes_file(tmp_path, monkeypatch):
    import lib.advisory_quarantine as aq
    qfile = tmp_path / "quarantine.jsonl"
    monkeypatch.setattr(aq, "QUARANTINE_FILE", qfile)
    monkeypatch.setattr(aq, "QUARANTINE_DIR", tmp_path)

    record_quarantine_item(source="advisor", stage="gate", reason="score too low")
    assert qfile.exists()
    rows = [json.loads(line) for line in qfile.read_text().splitlines() if line]
    assert len(rows) == 1


def test_record_quarantine_item_fields_present(tmp_path, monkeypatch):
    import lib.advisory_quarantine as aq
    qfile = tmp_path / "quarantine.jsonl"
    monkeypatch.setattr(aq, "QUARANTINE_FILE", qfile)
    monkeypatch.setattr(aq, "QUARANTINE_DIR", tmp_path)

    record_quarantine_item(source="advisor", stage="gate", reason="score too low", text="some advice text")
    row = json.loads(qfile.read_text().splitlines()[0])
    assert "ts" in row
    assert "source" in row
    assert "stage" in row
    assert "reason" in row
    assert "text_len" in row
    assert "text_snippet" in row


def test_record_quarantine_item_text_length_recorded(tmp_path, monkeypatch):
    import lib.advisory_quarantine as aq
    qfile = tmp_path / "quarantine.jsonl"
    monkeypatch.setattr(aq, "QUARANTINE_FILE", qfile)
    monkeypatch.setattr(aq, "QUARANTINE_DIR", tmp_path)

    text = "hello world"
    record_quarantine_item(source="s", stage="s", reason="r", text=text)
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["text_len"] == len(text)


def test_record_quarantine_item_readiness_included_when_valid(tmp_path, monkeypatch):
    import lib.advisory_quarantine as aq
    qfile = tmp_path / "quarantine.jsonl"
    monkeypatch.setattr(aq, "QUARANTINE_FILE", qfile)
    monkeypatch.setattr(aq, "QUARANTINE_DIR", tmp_path)

    record_quarantine_item(source="s", stage="s", reason="r", advisory_readiness=0.8)
    row = json.loads(qfile.read_text().splitlines()[0])
    assert "advisory_readiness" in row
    assert row["advisory_readiness"] == pytest.approx(0.8)


def test_record_quarantine_item_invalid_readiness_omitted(tmp_path, monkeypatch):
    import lib.advisory_quarantine as aq
    qfile = tmp_path / "quarantine.jsonl"
    monkeypatch.setattr(aq, "QUARANTINE_FILE", qfile)
    monkeypatch.setattr(aq, "QUARANTINE_DIR", tmp_path)

    record_quarantine_item(source="s", stage="s", reason="r", advisory_readiness=None)
    row = json.loads(qfile.read_text().splitlines()[0])
    assert "advisory_readiness" not in row


def test_record_quarantine_item_reason_truncated_at_120(tmp_path, monkeypatch):
    import lib.advisory_quarantine as aq
    qfile = tmp_path / "quarantine.jsonl"
    monkeypatch.setattr(aq, "QUARANTINE_FILE", qfile)
    monkeypatch.setattr(aq, "QUARANTINE_DIR", tmp_path)

    long_reason = "x" * 200
    record_quarantine_item(source="s", stage="s", reason=long_reason)
    row = json.loads(qfile.read_text().splitlines()[0])
    assert len(row["reason"]) <= 120


def test_record_quarantine_item_empty_source_defaults_to_unknown(tmp_path, monkeypatch):
    import lib.advisory_quarantine as aq
    qfile = tmp_path / "quarantine.jsonl"
    monkeypatch.setattr(aq, "QUARANTINE_FILE", qfile)
    monkeypatch.setattr(aq, "QUARANTINE_DIR", tmp_path)

    record_quarantine_item(source="", stage="gate", reason="r")
    row = json.loads(qfile.read_text().splitlines()[0])
    assert row["source"] == "unknown"


def test_record_quarantine_item_does_not_raise_on_bad_inputs(tmp_path, monkeypatch):
    import lib.advisory_quarantine as aq
    qfile = tmp_path / "quarantine.jsonl"
    monkeypatch.setattr(aq, "QUARANTINE_FILE", qfile)
    monkeypatch.setattr(aq, "QUARANTINE_DIR", tmp_path)

    # Should never raise, even with weird inputs
    record_quarantine_item(source=None, stage=None, reason=None)
