"""Tests for lib/primitive_filter.py — operational telemetry filter.

Note: _TOOL_RE and _TOOL_ERROR_KEY_RE contain a pre-existing bug where
`\\b` is used in raw strings instead of `\\b`, so those regex paths never
match. Tests cover only the string-literal branches that actually work.
"""
from __future__ import annotations

import pytest

from lib.primitive_filter import is_primitive_text


# ---------------------------------------------------------------------------
# Empty / falsy inputs
# ---------------------------------------------------------------------------


def test_empty_string_returns_false():
    assert is_primitive_text("") is False


def test_none_is_safe():
    assert is_primitive_text(None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# "i struggle with tool_..._error" — string-literal branch
# ---------------------------------------------------------------------------


def test_struggle_with_tool_error_detected():
    assert is_primitive_text("I struggle with tool_read_error in my workflow") is True


def test_struggle_tool_error_case_insensitive_via_lower():
    # tl = text.lower() is applied before the check
    assert is_primitive_text("I STRUGGLE WITH TOOL_READ_ERROR HERE") is True


def test_struggle_with_tool_custom_suffix():
    assert is_primitive_text("i struggle with tool_bash_error constantly") is True


def test_struggle_alone_not_enough():
    # "struggle" + no "_error" → not flagged
    assert is_primitive_text("I struggle with communication sometimes") is False


def test_tool_prefix_alone_not_enough():
    # has "tool_" but no "_error"
    assert is_primitive_text("i struggle with tool_name only") is False


def test_error_suffix_alone_not_enough():
    # has "_error" but no "i struggle with tool_"
    assert is_primitive_text("some kind of _error happened") is False


# ---------------------------------------------------------------------------
# error_pattern: marker
# ---------------------------------------------------------------------------


def test_error_pattern_colon_detected():
    assert is_primitive_text("error_pattern: bash fails repeatedly") is True


def test_error_pattern_in_middle_of_text():
    assert is_primitive_text("Observed telemetry: error_pattern: timeout") is True


def test_error_pattern_no_colon_not_flagged():
    # must be "error_pattern:" with colon
    assert is_primitive_text("this is an error pattern without colon") is False


# ---------------------------------------------------------------------------
# status code 404 + webfetch / request failed
# ---------------------------------------------------------------------------


def test_status_404_webfetch_detected():
    assert is_primitive_text("status code 404, webfetch failed to load") is True


def test_status_404_request_failed_detected():
    assert is_primitive_text("status code 404 request failed on retry") is True


def test_status_404_webfetch_case_insensitive():
    assert is_primitive_text("STATUS CODE 404, WEBFETCH ERROR") is True


def test_status_404_without_webfetch_or_request_failed():
    # 404 alone doesn't trigger
    assert is_primitive_text("the endpoint returned status code 404") is False


def test_status_200_with_webfetch_not_flagged():
    # Only 404 triggers this branch
    assert is_primitive_text("status code 200 webfetch succeeded") is False


# ---------------------------------------------------------------------------
# Arrow patterns → or ->
# ---------------------------------------------------------------------------


def test_ascii_arrow_detected():
    assert is_primitive_text("read -> edit -> bash") is True


def test_unicode_arrow_detected():
    assert is_primitive_text("step1 → step2 → step3") is True


def test_arrow_at_end_of_string():
    assert is_primitive_text("final stage ->") is True


def test_single_ascii_arrow_detected():
    assert is_primitive_text("A -> B") is True


def test_text_without_arrows_not_flagged():
    assert is_primitive_text("use a dash for emphasis — like this") is False


# ---------------------------------------------------------------------------
# sequence + work or pattern
# ---------------------------------------------------------------------------


def test_sequence_and_work_detected():
    assert is_primitive_text("this sequence of operations will work together") is True


def test_sequence_and_pattern_detected():
    assert is_primitive_text("the sequence follows the expected pattern") is True


def test_sequence_alone_not_flagged():
    assert is_primitive_text("follow this sequence of ideas") is False


def test_sequence_with_unrelated_words_not_flagged():
    assert is_primitive_text("the sequence is interesting and novel") is False


# ---------------------------------------------------------------------------
# Genuine insight text — should NOT be flagged
# ---------------------------------------------------------------------------


def test_genuine_insight_not_flagged():
    text = "Users respond better to shorter replies with clear structure"
    assert is_primitive_text(text) is False


def test_learning_text_not_flagged():
    text = "The system learns faster when feedback is immediate"
    assert is_primitive_text(text) is False


def test_preference_text_not_flagged():
    text = "Prefer dark mode for late-night sessions"
    assert is_primitive_text(text) is False


def test_long_clean_paragraph_not_flagged():
    text = (
        "Concise answers improve user satisfaction significantly. "
        "The key is to focus on the most important information first."
    )
    assert is_primitive_text(text) is False
