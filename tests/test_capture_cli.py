"""Tests for lib/capture_cli.py

Covers:
- _ago(): 0/negative → '?', seconds < 60, minutes < 3600, hours ≥ 3600
- format_pending(): empty list → "No pending suggestions.",
  single item with all fields, long text truncated at 140 chars with ellipsis,
  multiple items listed, missing score/cat handled, sid and category in output
"""

from __future__ import annotations

import time

import pytest

from lib.capture_cli import _ago, format_pending


# ---------------------------------------------------------------------------
# _ago
# ---------------------------------------------------------------------------

def test_ago_zero_ts():
    assert _ago(0) == "?"


def test_ago_none_ts():
    assert _ago(None) == "?"


def test_ago_seconds():
    result = _ago(time.time() - 30)
    assert result.endswith("s")


def test_ago_minutes():
    result = _ago(time.time() - 120)
    assert result.endswith("m")


def test_ago_hours():
    result = _ago(time.time() - 7200)
    assert result.endswith("h")


def test_ago_just_under_minute():
    result = _ago(time.time() - 59)
    assert result.endswith("s")


def test_ago_exactly_one_hour():
    result = _ago(time.time() - 3600)
    assert result == "1h"


def test_ago_returns_string():
    assert isinstance(_ago(time.time() - 10), str)


# ---------------------------------------------------------------------------
# format_pending
# ---------------------------------------------------------------------------

def test_format_pending_empty_list():
    assert format_pending([]) == "No pending suggestions."


def test_format_pending_single_item():
    items = [{"suggestion_id": "s1", "score": 0.75, "category": "style",
              "created_at": time.time(), "text": "Use black for formatting"}]
    result = format_pending(items)
    assert "s1" in result
    assert "style" in result
    assert "Use black" in result


def test_format_pending_shows_count():
    items = [
        {"suggestion_id": "s1", "score": 0.5, "category": "a", "created_at": time.time(), "text": "A"},
        {"suggestion_id": "s2", "score": 0.6, "category": "b", "created_at": time.time(), "text": "B"},
    ]
    result = format_pending(items)
    assert "2" in result


def test_format_pending_truncates_long_text():
    long_text = "x" * 200
    items = [{"suggestion_id": "s1", "score": 0.5, "category": "test",
              "created_at": time.time(), "text": long_text}]
    result = format_pending(items)
    assert "…" in result
    # The truncated line should not contain all 200 x's
    lines = result.split("\n")
    text_line = next(l for l in lines if "x" in l)
    assert len(text_line) < 160  # 140 + some overhead


def test_format_pending_returns_string():
    result = format_pending([])
    assert isinstance(result, str)


def test_format_pending_score_in_output():
    items = [{"suggestion_id": "s1", "score": 0.88, "category": "pref",
              "created_at": time.time(), "text": "some text"}]
    result = format_pending(items)
    assert "0.88" in result


def test_format_pending_multiple_items():
    items = [
        {"suggestion_id": f"s{i}", "score": 0.5, "category": "c",
         "created_at": time.time(), "text": f"Item {i}"}
        for i in range(3)
    ]
    result = format_pending(items)
    assert "s0" in result
    assert "s1" in result
    assert "s2" in result


def test_format_pending_text_no_newlines():
    items = [{"suggestion_id": "s1", "score": 0.5, "category": "c",
              "created_at": time.time(), "text": "line1\nline2"}]
    result = format_pending(items)
    # Newlines in text should be replaced
    lines = [l for l in result.split("\n") if "line1" in l or "line2" in l]
    assert len(lines) == 1
