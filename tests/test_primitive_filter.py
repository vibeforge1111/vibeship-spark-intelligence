"""Tests for lib/primitive_filter.py

Covers all branches of is_primitive_text() including:
- tool_error key patterns
- struggle/error phrase patterns
- error_pattern keyword
- 404 + webfetch patterns
- arrow sequence indicators (-> and →)
- sequence + work/pattern combos
- tool token + primitive keyword combos
- edge cases (empty, None, non-primitive text)
"""

import pytest

from lib.primitive_filter import is_primitive_text


# ---------------------------------------------------------------------------
# Non-primitive text — should return False
# ---------------------------------------------------------------------------

def test_empty_string_returns_false():
    assert is_primitive_text("") is False


def test_none_returns_false():
    assert is_primitive_text(None) is False


def test_normal_insight_is_not_primitive():
    assert is_primitive_text("Always validate user input before passing to the database") is False


def test_short_sentence_not_primitive():
    assert is_primitive_text("Use context managers for file handling") is False


def test_unrelated_error_word_not_primitive():
    # "error" alone without a matching tool token is not flagged
    assert is_primitive_text("Human error is unavoidable") is False


def test_unrelated_sequence_word_not_primitive():
    # "sequence" alone without work/pattern is not flagged
    assert is_primitive_text("The DNA sequence was analyzed") is False


# ---------------------------------------------------------------------------
# tool_N_error patterns — should return True
# ---------------------------------------------------------------------------

def test_tool_underscore_number_error():
    assert is_primitive_text("tool_1_error occurred") is True


def test_tool_space_number_error():
    assert is_primitive_text("tool 2 error in pipeline") is True


def test_tool_dash_number_error():
    assert is_primitive_text("tool-3-error detected") is True


def test_tool_error_pattern_case_insensitive():
    assert is_primitive_text("TOOL_4_ERROR was raised") is True


# ---------------------------------------------------------------------------
# "i struggle with tool_X_error" pattern — should return True
# ---------------------------------------------------------------------------

def test_struggle_with_tool_error():
    assert is_primitive_text("I struggle with tool_5_error handling") is True


def test_struggle_tool_error_lowercase():
    assert is_primitive_text("i struggle with tool_read_error in sessions") is True


# ---------------------------------------------------------------------------
# error_pattern keyword — should return True
# ---------------------------------------------------------------------------

def test_error_pattern_keyword():
    assert is_primitive_text("error_pattern: read followed by bash timeout") is True


def test_error_pattern_mixed_case():
    assert is_primitive_text("ERROR_PATTERN: write failure on retry") is True


# ---------------------------------------------------------------------------
# 404 + webfetch/request failed — should return True
# ---------------------------------------------------------------------------

def test_404_with_webfetch():
    assert is_primitive_text("status code 404 from webfetch on docs page") is True


def test_404_with_request_failed():
    assert is_primitive_text("status code 404 request failed after 3 retries") is True


def test_404_without_webfetch_or_request_failed():
    # 404 alone should not be flagged
    assert is_primitive_text("HTTP status code 404 is not found") is False


# ---------------------------------------------------------------------------
# Arrow sequence indicators — should return True
# ---------------------------------------------------------------------------

def test_ascii_arrow_sequence():
    assert is_primitive_text("Read -> Edit -> Bash") is True


def test_unicode_arrow_sequence():
    assert is_primitive_text("Read → Write → Glob") is True


def test_ascii_arrow_in_longer_text():
    assert is_primitive_text("The flow was: Read -> Edit -> Bash -> success") is True


# ---------------------------------------------------------------------------
# "sequence" + "work" or "pattern" — should return True
# ---------------------------------------------------------------------------

def test_sequence_with_work():
    assert is_primitive_text("This sequence works every time") is True


def test_sequence_with_pattern():
    assert is_primitive_text("Sequence pattern detected in logs") is True


def test_sequence_with_neither():
    # "sequence" without work/pattern is not flagged
    assert is_primitive_text("The sequence of events is unclear") is False


# ---------------------------------------------------------------------------
# Tool token + primitive keyword combos — should return True
# ---------------------------------------------------------------------------

def test_bash_with_error():
    assert is_primitive_text("bash error on startup") is True


def test_read_with_failed():
    assert is_primitive_text("read failed to open the file") is True


def test_write_with_timeout():
    assert is_primitive_text("write timeout after 30 seconds") is True


def test_grep_with_fails():
    assert is_primitive_text("grep fails on binary files") is True


def test_glob_with_pattern():
    assert is_primitive_text("glob pattern match sequence") is True


def test_python_with_usage():
    assert is_primitive_text("python usage of subprocess module") is True


def test_cli_with_struggle():
    assert is_primitive_text("cli struggle with argument parsing") is True


def test_webfetch_with_error():
    assert is_primitive_text("webfetch error on redirect") is True


def test_powershell_with_failed():
    assert is_primitive_text("powershell script failed to execute") is True


def test_tool_token_alone_not_primitive():
    # A tool token without any primitive keyword should not be flagged
    assert is_primitive_text("use grep to find the function definition") is False


def test_primitive_keyword_alone_not_primitive():
    # A primitive keyword without a tool token should not be flagged
    assert is_primitive_text("this approach struggles conceptually") is False
