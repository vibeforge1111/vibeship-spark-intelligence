"""Tests for lib/error_taxonomy.py

Covers:
- ERROR_KINDS constant: tuple, 7 entries, all expected strings present
- classify_error_kind(): all seven canonical kinds via representative
  trigger tokens, priority ordering (policy > auth > timeout > transport),
  case-insensitive matching, None/empty → "unknown"
- build_error_fields(): all returned keys present, kind forwarded from
  classify when not overridden, explicit kind= overrides classification,
  error_code None when blank, message truncated to max_message_chars,
  None message produces None error_message
"""

from __future__ import annotations

import pytest

from lib.error_taxonomy import (
    ERROR_KINDS,
    build_error_fields,
    classify_error_kind,
)


# ---------------------------------------------------------------------------
# ERROR_KINDS constant
# ---------------------------------------------------------------------------

def test_error_kinds_is_tuple():
    assert isinstance(ERROR_KINDS, tuple)


def test_error_kinds_has_seven_entries():
    assert len(ERROR_KINDS) == 7


def test_error_kinds_contains_expected():
    for kind in ("policy", "auth", "timeout", "transport", "no_hit", "stale", "unknown"):
        assert kind in ERROR_KINDS


# ---------------------------------------------------------------------------
# classify_error_kind — happy-path per kind
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message,expected", [
    ("blocked by rule: content policy", "policy"),
    ("guardrail triggered", "policy"),
    ("not allowed by policy", "policy"),
    ("forbidden by policy", "policy"),
    ("safety policy violation", "policy"),
    ("restricted by rule: content", "policy"),
    ("401 unauthorized", "auth"),
    ("403 forbidden access", "auth"),
    ("authentication failed", "auth"),
    ("invalid credential", "auth"),
    ("api key missing", "auth"),
    ("apikey not found", "auth"),
    ("token invalid", "auth"),
    ("token missing from header", "auth"),
    ("request timeout", "timeout"),
    ("timed out after 30s", "timeout"),
    ("deadline exceeded", "timeout"),
    ("took too long to complete", "timeout"),
    ("time limit reached", "timeout"),
    ("transport error", "transport"),
    ("network unreachable", "transport"),
    ("connection refused", "transport"),
    ("connection reset by peer", "transport"),
    ("dns resolution failed", "transport"),
    ("ssl handshake failed", "transport"),
    ("tls error", "transport"),
    ("gateway error", "transport"),
    ("no advice found", "no_hit"),
    ("no results returned", "no_hit"),
    ("no retrieval possible", "no_hit"),
    ("no hit in index", "no_hit"),
    ("empty result set", "no_hit"),
    ("nothing found in store", "no_hit"),
    ("stale data detected", "stale"),
    ("outdated cache entry", "stale"),
    ("expired token cache", "stale"),
    ("index lag detected", "stale"),
    ("age exceeded limit", "stale"),
    ("some random unrelated error", "unknown"),
    ("oops something went wrong", "unknown"),
])
def test_classify_error_kind_tokens(message, expected):
    assert classify_error_kind(message) == expected


# ---------------------------------------------------------------------------
# classify_error_kind — original tests (kept intact)
# ---------------------------------------------------------------------------

def test_classify_error_kind_priority_order():
    # policy should win over auth when both appear.
    assert classify_error_kind("blocked by policy: 401 token missing") == "policy"


def test_classify_error_kind_mappings():
    assert classify_error_kind("HTTP 401 unauthorized token missing") == "auth"
    assert classify_error_kind("request timeout after 30s") == "timeout"
    assert classify_error_kind("connection refused by upstream") == "transport"
    assert classify_error_kind("no advice available for this tool") == "no_hit"
    assert classify_error_kind("stale index lag detected") == "stale"
    assert classify_error_kind("unexpected issue") == "unknown"


# ---------------------------------------------------------------------------
# classify_error_kind — case-insensitive
# ---------------------------------------------------------------------------

def test_classify_uppercase_policy():
    assert classify_error_kind("BLOCKED BY RULE") == "policy"


def test_classify_mixed_case_auth():
    assert classify_error_kind("Unauthorized Access") == "auth"


def test_classify_uppercase_timeout():
    assert classify_error_kind("TIMEOUT") == "timeout"


def test_classify_uppercase_transport():
    assert classify_error_kind("CONNECTION REFUSED") == "transport"


# ---------------------------------------------------------------------------
# classify_error_kind — None and empty
# ---------------------------------------------------------------------------

def test_classify_none_returns_unknown():
    assert classify_error_kind(None) == "unknown"


def test_classify_empty_returns_unknown():
    assert classify_error_kind("") == "unknown"


def test_classify_whitespace_only_returns_unknown():
    assert classify_error_kind("   ") == "unknown"


# ---------------------------------------------------------------------------
# classify_error_kind — priority ordering
# ---------------------------------------------------------------------------

def test_classify_auth_beats_timeout():
    # Contains both "authentication" and "timeout"
    assert classify_error_kind("authentication timeout") == "auth"


def test_classify_timeout_beats_transport():
    # Contains both "timeout" and "connection"
    assert classify_error_kind("connection timeout") == "timeout"


def test_classify_transport_beats_no_hit():
    # Contains both "network" and "no results"
    assert classify_error_kind("network error: no results") == "transport"


# ---------------------------------------------------------------------------
# classify_error_kind — return type
# ---------------------------------------------------------------------------

def test_classify_returns_string():
    assert isinstance(classify_error_kind("something"), str)


def test_classify_result_always_in_error_kinds():
    for msg in ["", "timeout", "auth error", "blah blah", None]:
        result = classify_error_kind(msg)
        assert result in ERROR_KINDS, f"classify_error_kind({msg!r}) = {result!r} not in ERROR_KINDS"


# ---------------------------------------------------------------------------
# build_error_fields — original test (kept intact)
# ---------------------------------------------------------------------------

def test_build_error_fields_defaults_and_truncation():
    fields = build_error_fields("x" * 400, "AE_SAMPLE", max_message_chars=64)
    assert fields["error_kind"] == "unknown"
    assert fields["error_code"] == "AE_SAMPLE"
    assert len(fields["error_message"]) == 64


# ---------------------------------------------------------------------------
# build_error_fields — structure
# ---------------------------------------------------------------------------

def test_build_error_fields_returns_dict():
    assert isinstance(build_error_fields("some error"), dict)


def test_build_error_fields_has_error_kind():
    assert "error_kind" in build_error_fields("msg")


def test_build_error_fields_has_error_code():
    assert "error_code" in build_error_fields("msg")


def test_build_error_fields_has_error_message():
    assert "error_message" in build_error_fields("msg")


# ---------------------------------------------------------------------------
# build_error_fields — kind classification
# ---------------------------------------------------------------------------

def test_build_error_fields_classifies_kind():
    result = build_error_fields("401 unauthorized")
    assert result["error_kind"] == "auth"


def test_build_error_fields_kind_override():
    result = build_error_fields("some message", kind="stale")
    assert result["error_kind"] == "stale"


def test_build_error_fields_explicit_kind_ignores_text():
    # Text says "timeout" but explicit kind wins
    result = build_error_fields("request timeout", kind="policy")
    assert result["error_kind"] == "policy"


# ---------------------------------------------------------------------------
# build_error_fields — error_code
# ---------------------------------------------------------------------------

def test_build_error_fields_error_code_set():
    result = build_error_fields("msg", error_code="E404")
    assert result["error_code"] == "E404"


def test_build_error_fields_error_code_none_when_absent():
    result = build_error_fields("msg")
    assert result["error_code"] is None


def test_build_error_fields_error_code_none_when_empty():
    result = build_error_fields("msg", error_code="")
    assert result["error_code"] is None


def test_build_error_fields_error_code_none_when_whitespace():
    result = build_error_fields("msg", error_code="  ")
    assert result["error_code"] is None


# ---------------------------------------------------------------------------
# build_error_fields — error_message
# ---------------------------------------------------------------------------

def test_build_error_fields_error_message_matches_input():
    result = build_error_fields("connection reset")
    assert result["error_message"] == "connection reset"


def test_build_error_fields_error_message_truncated():
    long_msg = "x" * 500
    result = build_error_fields(long_msg, max_message_chars=100)
    assert len(result["error_message"]) == 100


def test_build_error_fields_error_message_none_when_empty():
    result = build_error_fields("")
    assert result["error_message"] is None


def test_build_error_fields_error_message_none_when_none_input():
    result = build_error_fields(None)
    assert result["error_message"] is None


def test_build_error_fields_default_max_is_300():
    msg = "a" * 400
    result = build_error_fields(msg)
    assert len(result["error_message"]) == 300

