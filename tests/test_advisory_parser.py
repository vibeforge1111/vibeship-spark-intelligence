"""Tests for lib/advisory_parser.py

Covers:
- _hash_id(): deterministic, 12-char hex, varies with input
- normalize_recommendation(): strips [SPARK] / [SPARK ADVISORY] prefixes,
  strips (spark: ...) wrappers, collapses whitespace, handles empty input
- split_atomic_recommendations(): parses bullet lists (-, *, +, numbered),
  parses checkbox lines, returns prose fallback when no bullets, skips blanks
- parse_feedback_requests(): reads JSONL, expands advice_texts, hashes IDs,
  skips empty recommendations, handles missing/empty file
- parse_advisory_markdown(): reads markdown file, splits bullets, populates
  advisory fields, handles missing file
- parse_engine_previews(): filters rows where event != "emitted", extracts
  emitted_text_preview, handles missing file
- load_advisories(): integrates the above, accepts explicit advisory_paths
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.advisory_parser import (
    _hash_id,
    normalize_recommendation,
    split_atomic_recommendations,
    parse_feedback_requests,
    parse_advisory_markdown,
    parse_engine_previews,
    load_advisories,
)


# ---------------------------------------------------------------------------
# _hash_id
# ---------------------------------------------------------------------------

def test_hash_id_returns_string():
    assert isinstance(_hash_id("a", "b"), str)


def test_hash_id_length_12():
    assert len(_hash_id("foo", "bar")) == 12


def test_hash_id_deterministic():
    assert _hash_id("x", "y") == _hash_id("x", "y")


def test_hash_id_varies_with_parts():
    assert _hash_id("a") != _hash_id("b")


def test_hash_id_order_sensitive():
    assert _hash_id("a", "b") != _hash_id("b", "a")


def test_hash_id_hex_chars_only():
    result = _hash_id("hello", "world")
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_id_empty_parts():
    result = _hash_id("", "")
    assert len(result) == 12


# ---------------------------------------------------------------------------
# normalize_recommendation
# ---------------------------------------------------------------------------

def test_normalize_strips_spark_prefix():
    assert normalize_recommendation("[SPARK] do something") == "do something"


def test_normalize_strips_spark_advisory_prefix():
    assert normalize_recommendation("[SPARK ADVISORY] check logs") == "check logs"


def test_normalize_case_insensitive_prefix():
    assert normalize_recommendation("[spark] run tests") == "run tests"


def test_normalize_strips_spark_paren_wrapper():
    assert normalize_recommendation("(spark: use retries)") == "use retries"


def test_normalize_collapses_whitespace():
    assert normalize_recommendation("use   retries   now") == "use retries now"


def test_normalize_strips_leading_trailing_whitespace():
    assert normalize_recommendation("  check logs  ") == "check logs"


def test_normalize_empty_string_returns_empty():
    assert normalize_recommendation("") == ""


def test_normalize_none_returns_empty():
    assert normalize_recommendation(None) == ""


def test_normalize_plain_text_unchanged():
    assert normalize_recommendation("add error handling") == "add error handling"


def test_normalize_returns_string():
    assert isinstance(normalize_recommendation("abc"), str)


# ---------------------------------------------------------------------------
# split_atomic_recommendations
# ---------------------------------------------------------------------------

def test_split_dash_bullets():
    text = "- First item\n- Second item"
    result = split_atomic_recommendations(text)
    assert len(result) == 2


def test_split_star_bullets():
    text = "* Item A\n* Item B"
    result = split_atomic_recommendations(text)
    assert len(result) == 2


def test_split_plus_bullets():
    text = "+ thing one\n+ thing two"
    result = split_atomic_recommendations(text)
    assert len(result) == 2


def test_split_numbered_list():
    text = "1. First\n2. Second\n3. Third"
    result = split_atomic_recommendations(text)
    assert len(result) == 3


def test_split_numbered_with_parens():
    text = "1) Alpha\n2) Beta"
    result = split_atomic_recommendations(text)
    assert len(result) == 2


def test_split_checkbox_unchecked():
    text = "- [ ] do this\n- [ ] do that"
    result = split_atomic_recommendations(text)
    assert len(result) == 2


def test_split_checkbox_checked():
    text = "- [x] already done\n- [X] also done"
    result = split_atomic_recommendations(text)
    assert len(result) == 2


def test_split_skips_blank_lines():
    text = "- item one\n\n- item two\n"
    result = split_atomic_recommendations(text)
    assert len(result) == 2


def test_split_prose_fallback_when_no_bullets():
    text = "This is a plain prose recommendation."
    result = split_atomic_recommendations(text)
    assert len(result) == 1
    assert "plain prose" in result[0]


def test_split_empty_text_returns_empty():
    assert split_atomic_recommendations("") == []


def test_split_none_text_returns_empty():
    assert split_atomic_recommendations(None) == []


def test_split_normalizes_spark_prefix_in_bullets():
    text = "- [SPARK] run the test suite"
    result = split_atomic_recommendations(text)
    assert result[0] == "run the test suite"


def test_split_returns_list():
    assert isinstance(split_atomic_recommendations("- item"), list)


def test_split_items_are_strings():
    for item in split_atomic_recommendations("- one\n- two"):
        assert isinstance(item, str)


# ---------------------------------------------------------------------------
# parse_feedback_requests
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, rows: list) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_parse_feedback_missing_file_returns_empty(tmp_path):
    assert parse_feedback_requests(path=tmp_path / "missing.jsonl") == []


def test_parse_feedback_empty_file_returns_empty(tmp_path):
    p = tmp_path / "req.jsonl"
    p.write_text("", encoding="utf-8")
    assert parse_feedback_requests(path=p) == []


def test_parse_feedback_returns_list(tmp_path):
    p = tmp_path / "req.jsonl"
    row = {"advice_texts": ["check logs"], "created_at": 1700000000.0, "session_id": "s1"}
    _write_jsonl(p, [row])
    assert isinstance(parse_feedback_requests(path=p), list)


def test_parse_feedback_one_text_one_item(tmp_path):
    p = tmp_path / "req.jsonl"
    row = {"advice_texts": ["check logs"], "created_at": 1700000000.0, "session_id": "s1"}
    _write_jsonl(p, [row])
    result = parse_feedback_requests(path=p)
    assert len(result) == 1


def test_parse_feedback_multiple_texts_multiple_items(tmp_path):
    p = tmp_path / "req.jsonl"
    row = {"advice_texts": ["item one", "item two", "item three"], "created_at": 1700000000.0, "session_id": "s1"}
    _write_jsonl(p, [row])
    result = parse_feedback_requests(path=p)
    assert len(result) == 3


def test_parse_feedback_item_has_required_keys(tmp_path):
    p = tmp_path / "req.jsonl"
    _write_jsonl(p, [{"advice_texts": ["do something"], "created_at": 1.0, "session_id": "s"}])
    item = parse_feedback_requests(path=p)[0]
    for key in ("advisory_instance_id", "advisory_id", "recommendation", "source_kind"):
        assert key in item


def test_parse_feedback_source_kind_is_feedback_request(tmp_path):
    p = tmp_path / "req.jsonl"
    _write_jsonl(p, [{"advice_texts": ["use retries"], "created_at": 1.0, "session_id": "s"}])
    item = parse_feedback_requests(path=p)[0]
    assert item["source_kind"] == "feedback_request"


def test_parse_feedback_skips_empty_recommendations(tmp_path):
    p = tmp_path / "req.jsonl"
    _write_jsonl(p, [{"advice_texts": ["", "   ", "[SPARK] "], "created_at": 1.0, "session_id": "s"}])
    result = parse_feedback_requests(path=p)
    assert result == []


def test_parse_feedback_recommendation_is_normalized(tmp_path):
    p = tmp_path / "req.jsonl"
    _write_jsonl(p, [{"advice_texts": ["[SPARK] check logs"], "created_at": 1.0, "session_id": "s"}])
    item = parse_feedback_requests(path=p)[0]
    assert item["recommendation"] == "check logs"


def test_parse_feedback_advisory_instance_id_is_12_chars(tmp_path):
    p = tmp_path / "req.jsonl"
    _write_jsonl(p, [{"advice_texts": ["do x"], "created_at": 1.0, "session_id": "s"}])
    item = parse_feedback_requests(path=p)[0]
    assert len(item["advisory_instance_id"]) == 12


def test_parse_feedback_skips_invalid_json_lines(tmp_path):
    p = tmp_path / "req.jsonl"
    p.write_text('{"advice_texts": ["valid"], "created_at": 1.0, "session_id": "s"}\nnot-json\n', encoding="utf-8")
    result = parse_feedback_requests(path=p)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# parse_advisory_markdown
# ---------------------------------------------------------------------------

def test_parse_advisory_markdown_missing_file_returns_empty(tmp_path):
    assert parse_advisory_markdown(tmp_path / "missing.md") == []


def test_parse_advisory_markdown_returns_list(tmp_path):
    p = tmp_path / "advisory.md"
    p.write_text("- do something useful", encoding="utf-8")
    assert isinstance(parse_advisory_markdown(p), list)


def test_parse_advisory_markdown_one_bullet_one_item(tmp_path):
    p = tmp_path / "advisory.md"
    p.write_text("- run the test suite", encoding="utf-8")
    result = parse_advisory_markdown(p)
    assert len(result) == 1


def test_parse_advisory_markdown_multiple_bullets(tmp_path):
    p = tmp_path / "advisory.md"
    p.write_text("- first\n- second\n- third", encoding="utf-8")
    result = parse_advisory_markdown(p)
    assert len(result) == 3


def test_parse_advisory_markdown_item_has_recommendation(tmp_path):
    p = tmp_path / "advisory.md"
    p.write_text("- use retry logic", encoding="utf-8")
    item = parse_advisory_markdown(p)[0]
    assert item["recommendation"] == "use retry logic"


def test_parse_advisory_markdown_source_kind(tmp_path):
    p = tmp_path / "advisory.md"
    p.write_text("- check logs", encoding="utf-8")
    item = parse_advisory_markdown(p)[0]
    assert item["source_kind"] == "advisory_markdown"


def test_parse_advisory_markdown_source_file_matches_path(tmp_path):
    p = tmp_path / "advisory.md"
    p.write_text("- item", encoding="utf-8")
    item = parse_advisory_markdown(p)[0]
    assert str(p) in item["source_file"]


def test_parse_advisory_markdown_advisory_id_is_12_chars(tmp_path):
    p = tmp_path / "advisory.md"
    p.write_text("- do something", encoding="utf-8")
    item = parse_advisory_markdown(p)[0]
    assert len(item["advisory_id"]) == 12


def test_parse_advisory_markdown_empty_file_returns_empty(tmp_path):
    p = tmp_path / "advisory.md"
    p.write_text("", encoding="utf-8")
    assert parse_advisory_markdown(p) == []


# ---------------------------------------------------------------------------
# parse_engine_previews
# ---------------------------------------------------------------------------

def test_parse_engine_previews_missing_file_returns_empty(tmp_path):
    assert parse_engine_previews(path=tmp_path / "missing.jsonl") == []


def test_parse_engine_previews_filters_non_emitted_events(tmp_path):
    p = tmp_path / "engine.jsonl"
    rows = [
        {"event": "created", "emitted_text_preview": "should be ignored", "ts": 1.0},
        {"event": "emitted", "emitted_text_preview": "check this out", "ts": 2.0},
    ]
    _write_jsonl(p, rows)
    result = parse_engine_previews(path=p)
    assert len(result) == 1


def test_parse_engine_previews_returns_emitted_rows(tmp_path):
    p = tmp_path / "engine.jsonl"
    _write_jsonl(p, [{"event": "emitted", "emitted_text_preview": "add logging", "ts": 1.0}])
    result = parse_engine_previews(path=p)
    assert len(result) == 1


def test_parse_engine_previews_item_has_recommendation(tmp_path):
    p = tmp_path / "engine.jsonl"
    _write_jsonl(p, [{"event": "emitted", "emitted_text_preview": "use retries", "ts": 1.0}])
    item = parse_engine_previews(path=p)[0]
    assert item["recommendation"] == "use retries"


def test_parse_engine_previews_source_kind(tmp_path):
    p = tmp_path / "engine.jsonl"
    _write_jsonl(p, [{"event": "emitted", "emitted_text_preview": "something", "ts": 1.0}])
    item = parse_engine_previews(path=p)[0]
    assert item["source_kind"] == "engine_preview"


def test_parse_engine_previews_skips_empty_preview(tmp_path):
    p = tmp_path / "engine.jsonl"
    _write_jsonl(p, [{"event": "emitted", "emitted_text_preview": "", "ts": 1.0}])
    result = parse_engine_previews(path=p)
    assert result == []


def test_parse_engine_previews_skips_invalid_json(tmp_path):
    p = tmp_path / "engine.jsonl"
    p.write_text('{"event": "emitted", "emitted_text_preview": "ok", "ts": 1.0}\nnot-json\n', encoding="utf-8")
    result = parse_engine_previews(path=p)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# load_advisories
# ---------------------------------------------------------------------------

def test_load_advisories_returns_list(tmp_path):
    req = tmp_path / "req.jsonl"
    req.write_text("", encoding="utf-8")
    result = load_advisories(request_file=req, advisory_paths=[], engine_file=tmp_path / "eng.jsonl")
    assert isinstance(result, list)


def test_load_advisories_combines_requests_and_markdown(tmp_path):
    req = tmp_path / "req.jsonl"
    _write_jsonl(req, [{"advice_texts": ["request item"], "created_at": 1.0, "session_id": "s"}])
    md = tmp_path / "advisory.md"
    md.write_text("- markdown item", encoding="utf-8")
    result = load_advisories(
        request_file=req,
        advisory_paths=[md],
        engine_file=tmp_path / "missing.jsonl",
    )
    assert len(result) == 2


def test_load_advisories_sorted_by_created_at(tmp_path):
    req = tmp_path / "req.jsonl"
    req.write_text("", encoding="utf-8")
    md1 = tmp_path / "a.md"
    md2 = tmp_path / "b.md"
    # Write two files, check sort
    md1.write_text("- later item", encoding="utf-8")
    md2.write_text("- earlier item", encoding="utf-8")
    # Touch md2 to have an older mtime
    import os, time
    os.utime(md2, (time.time() - 1000, time.time() - 1000))
    result = load_advisories(
        request_file=req,
        advisory_paths=[md1, md2],
        engine_file=tmp_path / "missing.jsonl",
    )
    timestamps = [float(r.get("created_at") or 0) for r in result]
    assert timestamps == sorted(timestamps)


def test_load_advisories_engine_fallback_when_empty(tmp_path):
    req = tmp_path / "req.jsonl"
    req.write_text("", encoding="utf-8")
    eng = tmp_path / "engine.jsonl"
    _write_jsonl(eng, [{"event": "emitted", "emitted_text_preview": "fallback item", "ts": 99.0}])
    result = load_advisories(
        request_file=req,
        advisory_paths=[],
        engine_file=eng,
        include_engine_fallback=True,
    )
    assert any(r["recommendation"] == "fallback item" for r in result)


def test_load_advisories_no_engine_fallback_when_disabled(tmp_path):
    req = tmp_path / "req.jsonl"
    req.write_text("", encoding="utf-8")
    eng = tmp_path / "engine.jsonl"
    _write_jsonl(eng, [{"event": "emitted", "emitted_text_preview": "fallback item", "ts": 99.0}])
    result = load_advisories(
        request_file=req,
        advisory_paths=[],
        engine_file=eng,
        include_engine_fallback=False,
    )
    assert result == []
