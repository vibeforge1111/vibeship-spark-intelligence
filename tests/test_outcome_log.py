"""Tests for lib/outcome_log.py

Covers:
- _hash_id() / make_outcome_id(): deterministic, 12-char hex
- _extract_keywords(): stopwords removed, short words removed, returns list
- _compute_similarity(): identical texts → 1.0, disjoint → 0.0, partial overlap
- build_explicit_outcome(): polarity mapping (pos/neutral/neg), default text,
  all required keys, trace_id forwarded
- build_chip_outcome(): polarity_map, event_type prefix, chip_id in row,
  session_id/trace_id forwarded when provided
- append_outcomes() / append_outcome(): writes rows to file, returns count,
  skips empty rows, _ensure_trace_id fills fallback
- read_outcomes(): reads from file, polarity filter, since filter, limit
- get_outcome_links(): missing file returns empty, reading + filters work
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.outcome_log as ol
from lib.outcome_log import (
    _hash_id,
    make_outcome_id,
    _extract_keywords,
    _compute_similarity,
    build_explicit_outcome,
    build_chip_outcome,
    append_outcomes,
    append_outcome,
    read_outcomes,
    get_outcome_links,
)


# ---------------------------------------------------------------------------
# _hash_id / make_outcome_id
# ---------------------------------------------------------------------------

def test_hash_id_returns_string():
    assert isinstance(_hash_id("a", "b"), str)


def test_hash_id_length_12():
    assert len(_hash_id("foo", "bar")) == 12


def test_hash_id_deterministic():
    assert _hash_id("x", "y") == _hash_id("x", "y")


def test_hash_id_varies_with_parts():
    assert _hash_id("a") != _hash_id("b")


def test_hash_id_hex_only():
    result = _hash_id("hello", "world")
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_id_none_parts():
    # None parts should become empty string
    result = _hash_id(None, "x")
    assert len(result) == 12


def test_make_outcome_id_same_as_hash_id():
    assert make_outcome_id("a", "b") == _hash_id("a", "b")


# ---------------------------------------------------------------------------
# _extract_keywords
# ---------------------------------------------------------------------------

def test_extract_keywords_returns_list():
    assert isinstance(_extract_keywords("run the tests"), list)


def test_extract_keywords_removes_stopwords():
    result = _extract_keywords("the user prefers this tool")
    # All those words are stopwords in the module
    assert "the" not in result
    assert "user" not in result
    assert "tool" not in result


def test_extract_keywords_removes_short_words():
    result = _extract_keywords("do it now")
    # "do", "it" are short/stopwords; "now" is 3 chars
    for w in result:
        assert len(w) >= 3


def test_extract_keywords_lowercases():
    result = _extract_keywords("Running Tests")
    assert all(w == w.lower() for w in result)


def test_extract_keywords_empty_string():
    assert _extract_keywords("") == []


def test_extract_keywords_caps_at_10():
    # Long text shouldn't return more than 10
    text = " ".join(f"keyword{i}" for i in range(30))
    assert len(_extract_keywords(text)) <= 10


def test_extract_keywords_meaningful_words_included():
    result = _extract_keywords("retry logic prevents failures")
    assert "retry" in result or "logic" in result or "prevents" in result or "failures" in result


# ---------------------------------------------------------------------------
# _compute_similarity
# ---------------------------------------------------------------------------

def test_compute_similarity_identical_returns_1():
    assert _compute_similarity("retry logic works", "retry logic works") == pytest.approx(1.0)


def test_compute_similarity_disjoint_returns_0():
    assert _compute_similarity("xyz abc", "qrs def") == pytest.approx(0.0)


def test_compute_similarity_partial_overlap():
    # Some keywords shared
    sim = _compute_similarity("retry logic prevents errors", "retry timeout errors")
    assert 0.0 < sim < 1.0


def test_compute_similarity_empty_returns_0():
    assert _compute_similarity("", "something") == pytest.approx(0.0)


def test_compute_similarity_returns_float():
    assert isinstance(_compute_similarity("a b c", "a b c"), float)


def test_compute_similarity_symmetric():
    a = "retry logic prevents errors"
    b = "error retry handling"
    assert abs(_compute_similarity(a, b) - _compute_similarity(b, a)) < 1e-9


# ---------------------------------------------------------------------------
# build_explicit_outcome — polarity mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("result,expected_polarity", [
    ("yes", "pos"),
    ("y", "pos"),
    ("success", "pos"),
    ("ok", "pos"),
    ("good", "pos"),
    ("worked", "pos"),
    ("partial", "neutral"),
    ("mixed", "neutral"),
    ("some", "neutral"),
    ("meh", "neutral"),
    ("unclear", "neutral"),
    ("no", "neg"),
    ("failed", "neg"),
    ("bad", "neg"),
    ("nope", "neg"),
])
def test_build_explicit_outcome_polarity(result, expected_polarity):
    row, polarity = build_explicit_outcome(result)
    assert polarity == expected_polarity
    assert row["polarity"] == expected_polarity


def test_build_explicit_outcome_returns_tuple():
    result = build_explicit_outcome("yes")
    assert isinstance(result, tuple) and len(result) == 2


def test_build_explicit_outcome_row_is_dict():
    row, _ = build_explicit_outcome("yes")
    assert isinstance(row, dict)


def test_build_explicit_outcome_has_required_keys():
    row, _ = build_explicit_outcome("yes")
    for key in ("outcome_id", "event_type", "text", "polarity", "result", "created_at"):
        assert key in row


def test_build_explicit_outcome_event_type():
    row, _ = build_explicit_outcome("yes")
    assert row["event_type"] == "explicit_checkin"


def test_build_explicit_outcome_outcome_id_is_12_chars():
    row, _ = build_explicit_outcome("yes")
    assert len(row["outcome_id"]) == 12


def test_build_explicit_outcome_custom_text():
    row, _ = build_explicit_outcome("yes", "It worked great")
    assert row["text"] == "It worked great"


def test_build_explicit_outcome_default_text_from_result():
    row, _ = build_explicit_outcome("no")
    assert "no" in row["text"]


def test_build_explicit_outcome_trace_id_forwarded():
    row, _ = build_explicit_outcome("yes", trace_id="trace-xyz")
    assert row["trace_id"] == "trace-xyz"


def test_build_explicit_outcome_no_trace_id_when_not_passed():
    row, _ = build_explicit_outcome("yes")
    assert "trace_id" not in row


def test_build_explicit_outcome_custom_created_at():
    ts = 1_700_000_000.0
    row, _ = build_explicit_outcome("yes", created_at=ts)
    assert row["created_at"] == ts


# ---------------------------------------------------------------------------
# build_chip_outcome
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("outcome_type,expected_polarity", [
    ("positive", "pos"),
    ("negative", "neg"),
    ("neutral", "neutral"),
    ("unknown", "neutral"),
])
def test_build_chip_outcome_polarity(outcome_type, expected_polarity):
    row = build_chip_outcome("chip-1", outcome_type, "result")
    assert row["polarity"] == expected_polarity


def test_build_chip_outcome_event_type_prefix():
    row = build_chip_outcome("chip-1", "positive", "it worked")
    assert row["event_type"] == "chip_positive"


def test_build_chip_outcome_chip_id_in_row():
    row = build_chip_outcome("chip-abc", "neutral", "ok")
    assert row["chip_id"] == "chip-abc"


def test_build_chip_outcome_text():
    row = build_chip_outcome("chip-1", "positive", "great result")
    assert row["text"] == "great result"


def test_build_chip_outcome_outcome_id_is_12():
    row = build_chip_outcome("chip-1", "positive", "r")
    assert len(row["outcome_id"]) == 12


def test_build_chip_outcome_session_id_forwarded():
    row = build_chip_outcome("chip-1", "neutral", "r", session_id="sess-9")
    assert row["session_id"] == "sess-9"


def test_build_chip_outcome_trace_id_forwarded():
    row = build_chip_outcome("chip-1", "neutral", "r", trace_id="t-123")
    assert row["trace_id"] == "t-123"


def test_build_chip_outcome_no_session_id_when_absent():
    row = build_chip_outcome("chip-1", "neutral", "r")
    assert "session_id" not in row


def test_build_chip_outcome_insight_field():
    row = build_chip_outcome("chip-1", "positive", "r", insight="use retries")
    assert row["insight"] == "use retries"


def test_build_chip_outcome_data_field():
    row = build_chip_outcome("chip-1", "positive", "r", data={"count": 5})
    assert row["data"] == {"count": 5}


def test_build_chip_outcome_returns_dict():
    assert isinstance(build_chip_outcome("c", "positive", "r"), dict)


# ---------------------------------------------------------------------------
# append_outcomes / append_outcome
# ---------------------------------------------------------------------------

def test_append_outcomes_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ol, "OUTCOMES_FILE", tmp_path / "outcomes.jsonl")
    append_outcomes([{"text": "hello", "outcome_id": "abc"}])
    assert (tmp_path / "outcomes.jsonl").exists()


def test_append_outcomes_returns_count(tmp_path, monkeypatch):
    monkeypatch.setattr(ol, "OUTCOMES_FILE", tmp_path / "outcomes.jsonl")
    count = append_outcomes([{"text": "a"}, {"text": "b"}])
    assert count == 2


def test_append_outcomes_skips_empty_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(ol, "OUTCOMES_FILE", tmp_path / "outcomes.jsonl")
    count = append_outcomes([{}, {}, {"text": "valid"}])
    assert count == 1


def test_append_outcomes_empty_list_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(ol, "OUTCOMES_FILE", tmp_path / "outcomes.jsonl")
    assert append_outcomes([]) == 0


def test_append_outcomes_content_readable(tmp_path, monkeypatch):
    f = tmp_path / "outcomes.jsonl"
    monkeypatch.setattr(ol, "OUTCOMES_FILE", f)
    append_outcomes([{"text": "test row", "polarity": "pos"}])
    lines = f.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["text"] == "test row"


def test_append_outcome_single_row(tmp_path, monkeypatch):
    monkeypatch.setattr(ol, "OUTCOMES_FILE", tmp_path / "outcomes.jsonl")
    count = append_outcome({"text": "single"})
    assert count == 1


def test_append_outcome_none_row_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(ol, "OUTCOMES_FILE", tmp_path / "outcomes.jsonl")
    assert append_outcome(None) == 0


def test_append_outcomes_adds_trace_id_when_missing(tmp_path, monkeypatch):
    f = tmp_path / "outcomes.jsonl"
    monkeypatch.setattr(ol, "OUTCOMES_FILE", f)
    append_outcomes([{"outcome_id": "abc", "event_type": "test", "created_at": 1.0}])
    row = json.loads(f.read_text().strip())
    # _ensure_trace_id should have added a trace_id fallback
    assert "trace_id" in row


# ---------------------------------------------------------------------------
# read_outcomes
# ---------------------------------------------------------------------------

def _write_outcomes(path: Path, rows: list) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_read_outcomes_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ol, "OUTCOMES_FILE", tmp_path / "missing.jsonl")
    assert read_outcomes() == []


def test_read_outcomes_returns_list(tmp_path, monkeypatch):
    f = tmp_path / "outcomes.jsonl"
    _write_outcomes(f, [{"polarity": "pos"}])
    monkeypatch.setattr(ol, "OUTCOMES_FILE", f)
    assert isinstance(read_outcomes(), list)


def test_read_outcomes_reads_rows(tmp_path, monkeypatch):
    f = tmp_path / "outcomes.jsonl"
    _write_outcomes(f, [{"polarity": "pos"}, {"polarity": "neg"}])
    monkeypatch.setattr(ol, "OUTCOMES_FILE", f)
    assert len(read_outcomes()) == 2


def test_read_outcomes_polarity_filter(tmp_path, monkeypatch):
    f = tmp_path / "outcomes.jsonl"
    _write_outcomes(f, [{"polarity": "pos"}, {"polarity": "neg"}, {"polarity": "pos"}])
    monkeypatch.setattr(ol, "OUTCOMES_FILE", f)
    result = read_outcomes(polarity="pos")
    assert all(r["polarity"] == "pos" for r in result)
    assert len(result) == 2


def test_read_outcomes_since_filter(tmp_path, monkeypatch):
    f = tmp_path / "outcomes.jsonl"
    _write_outcomes(f, [
        {"polarity": "pos", "created_at": 1_000_000.0},
        {"polarity": "pos", "created_at": 2_000_000.0},
    ])
    monkeypatch.setattr(ol, "OUTCOMES_FILE", f)
    result = read_outcomes(since=1_500_000.0)
    assert len(result) == 1
    assert result[0]["created_at"] == 2_000_000.0


def test_read_outcomes_limit(tmp_path, monkeypatch):
    f = tmp_path / "outcomes.jsonl"
    _write_outcomes(f, [{"polarity": "pos"}] * 20)
    monkeypatch.setattr(ol, "OUTCOMES_FILE", f)
    assert len(read_outcomes(limit=5)) == 5


# ---------------------------------------------------------------------------
# get_outcome_links
# ---------------------------------------------------------------------------

def test_get_outcome_links_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ol, "OUTCOME_LINKS_FILE", tmp_path / "missing.jsonl")
    assert get_outcome_links() == []


def test_get_outcome_links_returns_list(tmp_path, monkeypatch):
    f = tmp_path / "links.jsonl"
    f.write_text(json.dumps({"link_id": "l1", "insight_key": "k1", "outcome_id": "o1"}) + "\n")
    monkeypatch.setattr(ol, "OUTCOME_LINKS_FILE", f)
    assert isinstance(get_outcome_links(), list)


def test_get_outcome_links_insight_key_filter(tmp_path, monkeypatch):
    f = tmp_path / "links.jsonl"
    f.write_text(
        json.dumps({"insight_key": "k1", "outcome_id": "o1"}) + "\n" +
        json.dumps({"insight_key": "k2", "outcome_id": "o2"}) + "\n"
    )
    monkeypatch.setattr(ol, "OUTCOME_LINKS_FILE", f)
    result = get_outcome_links(insight_key="k1")
    assert len(result) == 1
    assert result[0]["insight_key"] == "k1"


def test_get_outcome_links_outcome_id_filter(tmp_path, monkeypatch):
    f = tmp_path / "links.jsonl"
    f.write_text(
        json.dumps({"insight_key": "k1", "outcome_id": "o1"}) + "\n" +
        json.dumps({"insight_key": "k2", "outcome_id": "o2"}) + "\n"
    )
    monkeypatch.setattr(ol, "OUTCOME_LINKS_FILE", f)
    result = get_outcome_links(outcome_id="o2")
    assert len(result) == 1
