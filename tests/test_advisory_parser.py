"""Tests for lib/advisory_parser.py — parse advisories into atomic recommendations."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

import lib.advisory_parser as ap


# ---------------------------------------------------------------------------
# _hash_id
# ---------------------------------------------------------------------------

class TestHashId:
    def test_deterministic(self):
        assert ap._hash_id("a", "b") == ap._hash_id("a", "b")

    def test_different_inputs_differ(self):
        assert ap._hash_id("x", "y") != ap._hash_id("x", "z")

    def test_length_12(self):
        h = ap._hash_id("hello", "world")
        assert len(h) == 12

    def test_hex_chars_only(self):
        h = ap._hash_id("foo", "bar", "baz")
        assert all(c in "0123456789abcdef" for c in h)

    def test_single_part(self):
        h = ap._hash_id("only")
        assert len(h) == 12

    def test_empty_parts(self):
        h = ap._hash_id("", "")
        assert len(h) == 12


# ---------------------------------------------------------------------------
# normalize_recommendation
# ---------------------------------------------------------------------------

class TestNormalizeRecommendation:
    def test_strips_spark_prefix(self):
        assert ap.normalize_recommendation("[SPARK] do the thing") == "do the thing"

    def test_strips_spark_advisory_prefix(self):
        r = ap.normalize_recommendation("[SPARK ADVISORY] do it")
        assert r == "do it"

    def test_strips_spark_colon_prefix(self):
        r = ap.normalize_recommendation("(spark: abc)")
        assert r == "abc"

    def test_collapses_whitespace(self):
        r = ap.normalize_recommendation("  hello   world  ")
        assert r == "hello world"

    def test_empty_string(self):
        assert ap.normalize_recommendation("") == ""

    def test_none_like(self):
        assert ap.normalize_recommendation(None) == ""  # type: ignore[arg-type]

    def test_preserves_plain_text(self):
        r = ap.normalize_recommendation("Use fewer loops")
        assert r == "Use fewer loops"

    def test_case_insensitive_prefix(self):
        r = ap.normalize_recommendation("[spark] lowercase prefix")
        assert r == "lowercase prefix"


# ---------------------------------------------------------------------------
# split_atomic_recommendations
# ---------------------------------------------------------------------------

class TestSplitAtomicRecommendations:
    def test_bullet_dash(self):
        text = "- First item\n- Second item"
        items = ap.split_atomic_recommendations(text)
        assert items == ["First item", "Second item"]

    def test_bullet_star(self):
        text = "* item one\n* item two"
        items = ap.split_atomic_recommendations(text)
        assert items == ["item one", "item two"]

    def test_numbered_list(self):
        text = "1. Do this\n2. Do that"
        items = ap.split_atomic_recommendations(text)
        assert items == ["Do this", "Do that"]

    def test_checkbox_unchecked(self):
        text = "- [ ] task alpha\n- [ ] task beta"
        items = ap.split_atomic_recommendations(text)
        assert items == ["task alpha", "task beta"]

    def test_checkbox_checked(self):
        text = "- [x] done item"
        items = ap.split_atomic_recommendations(text)
        assert items == ["done item"]

    def test_checkbox_uppercase_X(self):
        text = "- [X] done item"
        items = ap.split_atomic_recommendations(text)
        assert items == ["done item"]

    def test_fallback_prose(self):
        text = "Just a plain sentence."
        items = ap.split_atomic_recommendations(text)
        assert items == ["Just a plain sentence."]

    def test_empty_input(self):
        assert ap.split_atomic_recommendations("") == []

    def test_blank_lines_skipped(self):
        text = "- item\n\n- item2"
        items = ap.split_atomic_recommendations(text)
        assert len(items) == 2

    def test_strips_spark_prefix_from_items(self):
        text = "- [SPARK] do something"
        items = ap.split_atomic_recommendations(text)
        assert items == ["do something"]

    def test_plus_bullet(self):
        text = "+ plus item"
        items = ap.split_atomic_recommendations(text)
        assert items == ["plus item"]


# ---------------------------------------------------------------------------
# _read_jsonl
# ---------------------------------------------------------------------------

class TestReadJsonl:
    def test_missing_file_returns_empty(self, tmp_path):
        p = tmp_path / "missing.jsonl"
        rows = ap._read_jsonl(p)
        assert rows == []

    def test_reads_valid_jsonl(self, tmp_path):
        p = tmp_path / "data.jsonl"
        p.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
        rows = ap._read_jsonl(p)
        assert len(rows) == 2
        assert rows[0][1] == {"a": 1}
        assert rows[1][1] == {"b": 2}

    def test_skips_invalid_lines(self, tmp_path):
        p = tmp_path / "mixed.jsonl"
        p.write_text('{"ok": true}\nBAD LINE\n{"ok2": true}\n', encoding="utf-8")
        rows = ap._read_jsonl(p)
        assert len(rows) == 2

    def test_limit_takes_last_n(self, tmp_path):
        p = tmp_path / "big.jsonl"
        lines = [json.dumps({"i": i}) for i in range(10)]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rows = ap._read_jsonl(p, limit=3)
        assert len(rows) == 3
        # Last 3 entries have i=7,8,9
        vals = [r[1]["i"] for r in rows]
        assert vals == [7, 8, 9]

    def test_line_numbers_attached(self, tmp_path):
        p = tmp_path / "nums.jsonl"
        p.write_text('{"x": 1}\n{"x": 2}\n', encoding="utf-8")
        rows = ap._read_jsonl(p)
        line_nos = [r[0] for r in rows]
        assert line_nos[0] < line_nos[1]


# ---------------------------------------------------------------------------
# parse_feedback_requests
# ---------------------------------------------------------------------------

class TestParseFeedbackRequests:
    def test_empty_file_returns_empty(self, tmp_path):
        p = tmp_path / "req.jsonl"
        p.write_text("", encoding="utf-8")
        items = ap.parse_feedback_requests(path=p)
        assert items == []

    def test_missing_file_returns_empty(self, tmp_path):
        p = tmp_path / "nope.jsonl"
        items = ap.parse_feedback_requests(path=p)
        assert items == []

    def test_parses_valid_entry(self, tmp_path):
        p = tmp_path / "req.jsonl"
        row = {
            "created_at": 1000.0,
            "advice_texts": ["Do X", "Do Y"],
            "advice_ids": ["id-x", "id-y"],
            "session_id": "sess1",
            "tool": "Write",
            "trace_id": "tr1",
            "packet_id": "pk1",
            "route": "primary",
        }
        p.write_text(json.dumps(row) + "\n", encoding="utf-8")
        items = ap.parse_feedback_requests(path=p)
        assert len(items) == 2
        assert items[0]["recommendation"] == "Do X"
        assert items[0]["advisory_id"] == "id-x"
        assert items[0]["source_kind"] == "feedback_request"
        assert items[1]["recommendation"] == "Do Y"

    def test_skips_empty_recommendation(self, tmp_path):
        p = tmp_path / "req.jsonl"
        row = {
            "created_at": 1000.0,
            "advice_texts": ["", "   "],
            "advice_ids": [],
            "session_id": "s",
        }
        p.write_text(json.dumps(row) + "\n", encoding="utf-8")
        items = ap.parse_feedback_requests(path=p)
        assert items == []

    def test_generates_hash_id_when_no_advice_id(self, tmp_path):
        p = tmp_path / "req.jsonl"
        row = {
            "created_at": 500.0,
            "advice_texts": ["Some advice"],
            "advice_ids": [],
            "session_id": "s",
        }
        p.write_text(json.dumps(row) + "\n", encoding="utf-8")
        items = ap.parse_feedback_requests(path=p)
        assert len(items) == 1
        # advisory_id should be a 12-char hash
        assert len(items[0]["advisory_id"]) == 12

    def test_evidence_refs_contains_path(self, tmp_path):
        p = tmp_path / "req.jsonl"
        row = {"created_at": 1.0, "advice_texts": ["tip"], "advice_ids": []}
        p.write_text(json.dumps(row) + "\n", encoding="utf-8")
        items = ap.parse_feedback_requests(path=p)
        assert str(p) in items[0]["evidence_refs"][0]


# ---------------------------------------------------------------------------
# parse_advisory_markdown
# ---------------------------------------------------------------------------

class TestParseAdvisoryMarkdown:
    def test_missing_file_returns_empty(self, tmp_path):
        p = tmp_path / "missing.md"
        items = ap.parse_advisory_markdown(p)
        assert items == []

    def test_parses_bullet_list(self, tmp_path):
        p = tmp_path / "adv.md"
        p.write_text("- Tip one\n- Tip two\n", encoding="utf-8")
        items = ap.parse_advisory_markdown(p)
        assert len(items) == 2
        assert items[0]["recommendation"] == "Tip one"
        assert items[0]["source_kind"] == "advisory_markdown"
        assert str(p) in items[0]["source_file"]

    def test_advisory_ids_are_stable(self, tmp_path):
        p = tmp_path / "adv.md"
        p.write_text("- Fixed advice\n", encoding="utf-8")
        items1 = ap.parse_advisory_markdown(p)
        items2 = ap.parse_advisory_markdown(p)
        assert items1[0]["advisory_id"] == items2[0]["advisory_id"]

    def test_empty_file_returns_empty(self, tmp_path):
        p = tmp_path / "empty.md"
        p.write_text("", encoding="utf-8")
        items = ap.parse_advisory_markdown(p)
        assert items == []

    def test_source_file_field(self, tmp_path):
        p = tmp_path / "src.md"
        p.write_text("- advice\n", encoding="utf-8")
        items = ap.parse_advisory_markdown(p)
        assert items[0]["source_file"] == str(p)


# ---------------------------------------------------------------------------
# parse_engine_previews
# ---------------------------------------------------------------------------

class TestParseEnginePreviews:
    def test_missing_file_returns_empty(self, tmp_path):
        p = tmp_path / "engine.jsonl"
        items = ap.parse_engine_previews(path=p)
        assert items == []

    def test_skips_non_emitted_events(self, tmp_path):
        p = tmp_path / "engine.jsonl"
        row = {"event": "other", "emitted_text_preview": "blah", "ts": 1.0}
        p.write_text(json.dumps(row) + "\n", encoding="utf-8")
        items = ap.parse_engine_previews(path=p)
        assert items == []

    def test_parses_emitted_event(self, tmp_path):
        p = tmp_path / "engine.jsonl"
        row = {
            "event": "emitted",
            "emitted_text_preview": "Consider X",
            "ts": 2000.0,
            "session_id": "sess",
            "tool": "Bash",
            "trace_id": "tr",
            "packet_id": "pk",
            "route": "r",
        }
        p.write_text(json.dumps(row) + "\n", encoding="utf-8")
        items = ap.parse_engine_previews(path=p)
        assert len(items) == 1
        assert items[0]["recommendation"] == "Consider X"
        assert items[0]["source_kind"] == "engine_preview"

    def test_skips_empty_preview(self, tmp_path):
        p = tmp_path / "engine.jsonl"
        row = {"event": "emitted", "emitted_text_preview": "", "ts": 1.0}
        p.write_text(json.dumps(row) + "\n", encoding="utf-8")
        items = ap.parse_engine_previews(path=p)
        assert items == []

    def test_advisory_id_from_packet_id(self, tmp_path):
        p = tmp_path / "engine.jsonl"
        row = {"event": "emitted", "emitted_text_preview": "tip", "ts": 1.0, "packet_id": "PK123"}
        p.write_text(json.dumps(row) + "\n", encoding="utf-8")
        items = ap.parse_engine_previews(path=p)
        assert items[0]["advisory_id"] == "PK123"


# ---------------------------------------------------------------------------
# load_advisories
# ---------------------------------------------------------------------------

class TestLoadAdvisories:
    def test_returns_sorted_by_created_at(self, tmp_path, monkeypatch):
        req_file = tmp_path / "req.jsonl"
        rows = [
            {"created_at": 300.0, "advice_texts": ["Later"], "advice_ids": []},
            {"created_at": 100.0, "advice_texts": ["Earlier"], "advice_ids": []},
        ]
        req_file.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

        result = ap.load_advisories(
            request_file=req_file,
            advisory_paths=[],
            engine_file=tmp_path / "missing.jsonl",
            include_engine_fallback=False,
        )
        timestamps = [float(x.get("created_at") or 0) for x in result]
        assert timestamps == sorted(timestamps)

    def test_merges_markdown_advisories(self, tmp_path):
        req_file = tmp_path / "req.jsonl"
        req_file.write_text("", encoding="utf-8")
        md_file = tmp_path / "adv.md"
        md_file.write_text("- Markdown tip\n", encoding="utf-8")

        result = ap.load_advisories(
            request_file=req_file,
            advisory_paths=[md_file],
            engine_file=tmp_path / "missing.jsonl",
            include_engine_fallback=False,
        )
        assert any(x["recommendation"] == "Markdown tip" for x in result)

    def test_engine_fallback_when_no_advisories(self, tmp_path):
        req_file = tmp_path / "req.jsonl"
        req_file.write_text("", encoding="utf-8")
        engine_file = tmp_path / "engine.jsonl"
        row = {"event": "emitted", "emitted_text_preview": "engine tip", "ts": 1.0}
        engine_file.write_text(json.dumps(row) + "\n", encoding="utf-8")

        result = ap.load_advisories(
            request_file=req_file,
            advisory_paths=[],
            engine_file=engine_file,
            include_engine_fallback=True,
        )
        assert any(x["recommendation"] == "engine tip" for x in result)

    def test_no_engine_fallback_when_disabled(self, tmp_path):
        req_file = tmp_path / "req.jsonl"
        req_file.write_text("", encoding="utf-8")
        engine_file = tmp_path / "engine.jsonl"
        row = {"event": "emitted", "emitted_text_preview": "engine tip", "ts": 1.0}
        engine_file.write_text(json.dumps(row) + "\n", encoding="utf-8")

        result = ap.load_advisories(
            request_file=req_file,
            advisory_paths=[],
            engine_file=engine_file,
            include_engine_fallback=False,
        )
        assert result == []
