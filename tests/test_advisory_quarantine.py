"""Tests for lib/advisory_quarantine.py — bounded JSONL quarantine sink."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import lib.advisory_quarantine as aq


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_paths(tmp_path, monkeypatch):
    qdir = tmp_path / "advisory_quarantine"
    qfile = qdir / "advisory_quarantine.jsonl"
    monkeypatch.setattr(aq, "QUARANTINE_DIR", qdir)
    monkeypatch.setattr(aq, "QUARANTINE_FILE", qfile)
    yield qfile


# ---------------------------------------------------------------------------
# _max_lines
# ---------------------------------------------------------------------------

class TestMaxLines:
    def test_default_is_1200(self, monkeypatch):
        monkeypatch.delenv("SPARK_ADVISORY_QUARANTINE_MAX_LINES", raising=False)
        assert aq._max_lines() == 1200

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SPARK_ADVISORY_QUARANTINE_MAX_LINES", "500")
        assert aq._max_lines() == 500

    def test_minimum_clamped_to_1(self, monkeypatch):
        monkeypatch.setenv("SPARK_ADVISORY_QUARANTINE_MAX_LINES", "0")
        assert aq._max_lines() == 1

    def test_negative_clamped_to_1(self, monkeypatch):
        monkeypatch.setenv("SPARK_ADVISORY_QUARANTINE_MAX_LINES", "-10")
        assert aq._max_lines() == 1

    def test_invalid_falls_back_to_1200(self, monkeypatch):
        monkeypatch.setenv("SPARK_ADVISORY_QUARANTINE_MAX_LINES", "not_a_number")
        assert aq._max_lines() == 1200


# ---------------------------------------------------------------------------
# _coerce_float01
# ---------------------------------------------------------------------------

class TestCoerceFloat01:
    def test_valid_float_in_range(self):
        assert aq._coerce_float01(0.5) == 0.5

    def test_zero(self):
        assert aq._coerce_float01(0.0) == 0.0

    def test_one(self):
        assert aq._coerce_float01(1.0) == 1.0

    def test_below_zero_clamps_to_zero(self):
        assert aq._coerce_float01(-0.5) == 0.0

    def test_above_one_clamps_to_one(self):
        assert aq._coerce_float01(1.5) == 1.0

    def test_rounds_to_4_decimal_places(self):
        result = aq._coerce_float01(0.12345678)
        assert result == round(0.12345678, 4)

    def test_nan_returns_none(self):
        assert aq._coerce_float01(math.nan) is None

    def test_none_returns_none(self):
        assert aq._coerce_float01(None) is None

    def test_string_number_parses(self):
        assert aq._coerce_float01("0.75") == 0.75

    def test_non_numeric_string_returns_none(self):
        assert aq._coerce_float01("bad") is None

    def test_int_input(self):
        assert aq._coerce_float01(1) == 1.0


# ---------------------------------------------------------------------------
# _safe_dict
# ---------------------------------------------------------------------------

class TestSafeDict:
    def test_dict_input_returns_copy(self):
        d = {"a": 1}
        result = aq._safe_dict(d)
        assert result == {"a": 1}
        assert result is not d  # copy, not same obj

    def test_none_returns_empty(self):
        assert aq._safe_dict(None) == {}

    def test_list_returns_empty(self):
        assert aq._safe_dict([1, 2]) == {}

    def test_string_returns_empty(self):
        assert aq._safe_dict("hello") == {}

    def test_empty_dict(self):
        assert aq._safe_dict({}) == {}


# ---------------------------------------------------------------------------
# _sanitize_text
# ---------------------------------------------------------------------------

class TestSanitizeText:
    def test_short_text_unchanged(self):
        assert aq._sanitize_text("hello") == "hello"

    def test_strips_whitespace(self):
        assert aq._sanitize_text("  hi  ") == "hi"

    def test_truncates_at_limit(self):
        long = "A" * 500
        result = aq._sanitize_text(long, limit=420)
        assert len(result) <= 420
        assert result.endswith("...")

    def test_exact_limit_not_truncated(self):
        text = "A" * 420
        result = aq._sanitize_text(text, limit=420)
        assert not result.endswith("...")

    def test_none_like_converts(self):
        result = aq._sanitize_text(None)  # type: ignore[arg-type]
        assert result == ""

    def test_custom_limit(self):
        text = "B" * 100
        result = aq._sanitize_text(text, limit=10)
        assert len(result) <= 10


# ---------------------------------------------------------------------------
# _tail_jsonl
# ---------------------------------------------------------------------------

class TestTailJsonl:
    def test_missing_file_returns_empty(self, tmp_path):
        assert aq._tail_jsonl(tmp_path / "nope.jsonl", 10) == []

    def test_limit_zero_returns_empty(self, tmp_path):
        p = tmp_path / "f.jsonl"
        p.write_text('{"a":1}\n', encoding="utf-8")
        assert aq._tail_jsonl(p, 0) == []

    def test_reads_valid_lines(self, tmp_path):
        p = tmp_path / "f.jsonl"
        p.write_text('{"a":1}\n{"b":2}\n', encoding="utf-8")
        rows = aq._tail_jsonl(p, 10)
        assert len(rows) == 2

    def test_skips_invalid_json(self, tmp_path):
        p = tmp_path / "f.jsonl"
        p.write_text('{"a":1}\nBAD\n{"b":2}\n', encoding="utf-8")
        rows = aq._tail_jsonl(p, 10)
        assert len(rows) == 2

    def test_skips_non_dict_rows(self, tmp_path):
        p = tmp_path / "f.jsonl"
        p.write_text('["list"]\n{"ok":1}\n', encoding="utf-8")
        rows = aq._tail_jsonl(p, 10)
        assert len(rows) == 1

    def test_limit_takes_last_n(self, tmp_path):
        p = tmp_path / "f.jsonl"
        lines = [json.dumps({"i": i}) for i in range(20)]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rows = aq._tail_jsonl(p, 5)
        assert len(rows) == 5
        assert rows[-1]["i"] == 19


# ---------------------------------------------------------------------------
# _append_jsonl_capped
# ---------------------------------------------------------------------------

class TestAppendJsonlCapped:
    def test_creates_file_and_appends(self, tmp_path):
        p = tmp_path / "sub" / "f.jsonl"
        aq._append_jsonl_capped(p, {"x": 1}, max_lines=100)
        assert p.exists()
        rows = [json.loads(l) for l in p.read_text().splitlines() if l]
        assert rows == [{"x": 1}]

    def test_cap_enforced(self, tmp_path):
        p = tmp_path / "f.jsonl"
        for i in range(15):
            aq._append_jsonl_capped(p, {"i": i}, max_lines=10)
        rows = [json.loads(l) for l in p.read_text().splitlines() if l]
        assert len(rows) <= 10

    def test_cap_zero_no_trim(self, tmp_path):
        p = tmp_path / "f.jsonl"
        for i in range(5):
            aq._append_jsonl_capped(p, {"i": i}, max_lines=0)
        rows = [json.loads(l) for l in p.read_text().splitlines() if l]
        assert len(rows) == 5

    def test_latest_entries_kept_after_cap(self, tmp_path):
        p = tmp_path / "f.jsonl"
        for i in range(15):
            aq._append_jsonl_capped(p, {"i": i}, max_lines=5)
        rows = [json.loads(l) for l in p.read_text().splitlines() if l]
        vals = [r["i"] for r in rows]
        # Last 5 entries should be 10-14
        assert max(vals) == 14


# ---------------------------------------------------------------------------
# record_quarantine_item
# ---------------------------------------------------------------------------

class TestRecordQuarantineItem:
    def test_creates_file(self, isolate_paths):
        aq.record_quarantine_item(source="test", stage="gate", reason="too_short")
        assert isolate_paths.exists()

    def test_writes_required_fields(self, isolate_paths):
        aq.record_quarantine_item(source="advisor", stage="quality", reason="low_score")
        row = json.loads(isolate_paths.read_text().strip().splitlines()[-1])
        assert row["source"] == "advisor"
        assert row["stage"] == "quality"
        assert row["reason"] == "low_score"
        assert "ts" in row
        assert "recorded_at" in row

    def test_text_snippet_and_length(self, isolate_paths):
        aq.record_quarantine_item(source="s", stage="st", reason="r", text="Hello world")
        row = json.loads(isolate_paths.read_text().strip())
        assert row["text_snippet"] == "Hello world"
        assert row["text_len"] == 11

    def test_text_snippet_truncated(self, isolate_paths):
        long_text = "X" * 500
        aq.record_quarantine_item(source="s", stage="st", reason="r", text=long_text)
        row = json.loads(isolate_paths.read_text().strip())
        assert len(row["text_snippet"]) <= 423  # 420 + "..."
        assert row["text_len"] == 500

    def test_advisory_quality_stored(self, isolate_paths):
        aq.record_quarantine_item(
            source="s", stage="st", reason="r",
            advisory_quality={"score": 0.3}
        )
        row = json.loads(isolate_paths.read_text().strip())
        assert row["advisory_quality"] == {"score": 0.3}

    def test_advisory_readiness_stored(self, isolate_paths):
        aq.record_quarantine_item(source="s", stage="st", reason="r", advisory_readiness=0.55)
        row = json.loads(isolate_paths.read_text().strip())
        assert "advisory_readiness" in row
        assert abs(row["advisory_readiness"] - 0.55) < 0.001

    def test_advisory_readiness_invalid_omitted(self, isolate_paths):
        aq.record_quarantine_item(source="s", stage="st", reason="r", advisory_readiness="bad")
        row = json.loads(isolate_paths.read_text().strip())
        assert "advisory_readiness" not in row

    def test_meta_stored_as_source_meta(self, isolate_paths):
        aq.record_quarantine_item(source="s", stage="st", reason="r", meta={"k": "v"})
        row = json.loads(isolate_paths.read_text().strip())
        assert row["source_meta"] == {"k": "v"}

    def test_extras_stored(self, isolate_paths):
        aq.record_quarantine_item(source="s", stage="st", reason="r", extras={"e": 1})
        row = json.loads(isolate_paths.read_text().strip())
        assert row["extras"] == {"e": 1}

    def test_meta_none_omitted(self, isolate_paths):
        aq.record_quarantine_item(source="s", stage="st", reason="r", meta=None)
        row = json.loads(isolate_paths.read_text().strip())
        assert "source_meta" not in row

    def test_empty_source_defaults_to_unknown(self, isolate_paths):
        aq.record_quarantine_item(source="", stage="st", reason="r")
        row = json.loads(isolate_paths.read_text().strip())
        assert row["source"] == "unknown"

    def test_reason_truncated_to_120_chars(self, isolate_paths):
        long_reason = "R" * 200
        aq.record_quarantine_item(source="s", stage="st", reason=long_reason)
        row = json.loads(isolate_paths.read_text().strip())
        assert len(row["reason"]) <= 120

    def test_never_raises(self, monkeypatch):
        # Even if the write explodes, no exception should propagate
        monkeypatch.setattr(aq, "_append_jsonl_capped", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
        # Should not raise
        aq.record_quarantine_item(source="s", stage="st", reason="r")

    def test_multiple_entries_appended(self, isolate_paths):
        for i in range(3):
            aq.record_quarantine_item(source=f"s{i}", stage="st", reason="r")
        lines = [l for l in isolate_paths.read_text().splitlines() if l]
        assert len(lines) == 3
