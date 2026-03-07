"""Tests for lib/action_matcher.py

Covers:
- _norm(): lowercases, strips, collapses whitespace
- _text_sim(): exact match → 1.0, substring → 1.0, similar text > 0,
  empty inputs → 0.0, symmetric
- _parse_ts(): reads created_at / ts / timestamp keys, falls back to 0.0,
  handles non-numeric gracefully
- _match_explicit_feedback(): returns None when advisory_id absent, None when
  no matching advice_ids, returns match dict when found, skips rows before
  advisory created_at, skips rows outside window, picks earliest match
- _match_implicit_outcome(): returns None when session_id or tool missing,
  returns None when advisory_created <= 0, matches by session_id+tool,
  applies polarity hint correctly
- match_actions(): unresolved default when no match, propagates advisory_instance_id,
  returns one match per advisory, uses explicit_feedback path when present
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from lib.action_matcher import (
    _norm,
    _text_sim,
    _parse_ts,
    _match_explicit_feedback,
    _match_implicit_outcome,
    match_actions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _advisory(**kwargs) -> Dict[str, Any]:
    base = {
        "advisory_instance_id": "inst-001",
        "advisory_id": "adv-001",
        "recommendation": "run the test suite",
        "created_at": 1_700_000_000.0,
        "session_id": "sess-1",
        "tool": "bash",
    }
    base.update(kwargs)
    return base


def _feedback_row(advice_ids=None, ts=None, followed=True, helpful=True, notes="") -> Dict[str, Any]:
    return {
        "advice_ids": advice_ids or ["adv-001"],
        "created_at": ts or 1_700_001_000.0,
        "followed": followed,
        "helpful": helpful,
        "notes": notes,
    }


def _outcome_row(session_id="sess-1", tool="bash", ts=None, event_type="success", polarity="") -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "tool": tool,
        "created_at": ts or 1_700_001_000.0,
        "event_type": event_type,
        "polarity": polarity,
        "text": "result text",
    }


def _write_jsonl(path: Path, rows: list) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# _norm
# ---------------------------------------------------------------------------

def test_norm_lowercases():
    assert _norm("HELLO") == "hello"


def test_norm_strips():
    assert _norm("  hello  ") == "hello"


def test_norm_collapses_whitespace():
    assert _norm("hello   world") == "hello world"


def test_norm_empty_string():
    assert _norm("") == ""


def test_norm_none():
    assert _norm(None) == ""


def test_norm_returns_string():
    assert isinstance(_norm("test"), str)


# ---------------------------------------------------------------------------
# _text_sim
# ---------------------------------------------------------------------------

def test_text_sim_identical_returns_1():
    assert _text_sim("run tests", "run tests") == 1.0


def test_text_sim_substring_returns_1():
    # "test" is a substring of "run tests"
    assert _text_sim("test", "run tests") == 1.0


def test_text_sim_superset_returns_1():
    assert _text_sim("run tests now", "test") == 1.0


def test_text_sim_similar_above_zero():
    assert _text_sim("run test suite", "run test suites") > 0.8


def test_text_sim_unrelated_below_threshold():
    assert _text_sim("run tests", "buy groceries") < 0.6


def test_text_sim_empty_a_returns_zero():
    assert _text_sim("", "hello") == 0.0


def test_text_sim_empty_b_returns_zero():
    assert _text_sim("hello", "") == 0.0


def test_text_sim_both_empty_returns_zero():
    assert _text_sim("", "") == 0.0


def test_text_sim_returns_float():
    assert isinstance(_text_sim("a", "b"), float)


def test_text_sim_symmetric():
    a, b = "retry logic", "add retry"
    assert abs(_text_sim(a, b) - _text_sim(b, a)) < 1e-9


def test_text_sim_case_insensitive():
    assert _text_sim("Run Tests", "run tests") == 1.0


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

def test_parse_ts_reads_created_at():
    assert _parse_ts({"created_at": 1234.5}) == 1234.5


def test_parse_ts_reads_ts():
    assert _parse_ts({"ts": 9999.0}) == 9999.0


def test_parse_ts_reads_timestamp():
    assert _parse_ts({"timestamp": 5555.0}) == 5555.0


def test_parse_ts_prefers_created_at_over_ts():
    # created_at is checked first
    assert _parse_ts({"created_at": 100.0, "ts": 200.0}) == 100.0


def test_parse_ts_falls_back_to_ts_when_no_created_at():
    assert _parse_ts({"ts": 200.0}) == 200.0


def test_parse_ts_returns_zero_when_all_missing():
    assert _parse_ts({}) == 0.0


def test_parse_ts_returns_zero_for_none_values():
    assert _parse_ts({"created_at": None, "ts": None}) == 0.0


def test_parse_ts_handles_non_numeric():
    assert _parse_ts({"created_at": "not-a-number"}) == 0.0


def test_parse_ts_returns_float():
    assert isinstance(_parse_ts({"created_at": 1.0}), float)


# ---------------------------------------------------------------------------
# _match_explicit_feedback — no match cases
# ---------------------------------------------------------------------------

def test_match_explicit_feedback_no_advisory_id_returns_none():
    adv = _advisory(advisory_id="")
    result = _match_explicit_feedback(adv, [(1, _feedback_row())], 3600)
    assert result is None


def test_match_explicit_feedback_no_created_at_returns_none():
    adv = _advisory(created_at=0.0)
    result = _match_explicit_feedback(adv, [(1, _feedback_row())], 3600)
    assert result is None


def test_match_explicit_feedback_wrong_advice_id_returns_none():
    adv = _advisory(advisory_id="adv-001")
    row = _feedback_row(advice_ids=["adv-999"])
    result = _match_explicit_feedback(adv, [(1, row)], 3600)
    assert result is None


def test_match_explicit_feedback_row_before_advisory_skipped():
    adv = _advisory(advisory_id="adv-001", created_at=1_000_000.0)
    row = _feedback_row(advice_ids=["adv-001"], ts=999_000.0)
    result = _match_explicit_feedback(adv, [(1, row)], 3600)
    assert result is None


def test_match_explicit_feedback_row_outside_window_skipped():
    adv = _advisory(advisory_id="adv-001", created_at=1_000_000.0)
    # 8 hours later, window is 3600s (1 hour)
    row = _feedback_row(advice_ids=["adv-001"], ts=1_000_000.0 + 8 * 3600)
    result = _match_explicit_feedback(adv, [(1, row)], 3600)
    assert result is None


# ---------------------------------------------------------------------------
# _match_explicit_feedback — match cases
# ---------------------------------------------------------------------------

def test_match_explicit_feedback_returns_dict_on_match():
    adv = _advisory()
    row = _feedback_row()
    result = _match_explicit_feedback(adv, [(1, row)], 3600 * 6)
    assert isinstance(result, dict)


def test_match_explicit_feedback_followed_gives_acted():
    adv = _advisory()
    row = _feedback_row(followed=True)
    result = _match_explicit_feedback(adv, [(1, row)], 3600 * 6)
    assert result["status"] == "acted"


def test_match_explicit_feedback_not_followed_gives_skipped():
    adv = _advisory()
    row = _feedback_row(followed=False, helpful=None)
    result = _match_explicit_feedback(adv, [(1, row)], 3600 * 6)
    assert result["status"] == "skipped"


def test_match_explicit_feedback_helpful_true_gives_positive():
    adv = _advisory()
    row = _feedback_row(helpful=True)
    result = _match_explicit_feedback(adv, [(1, row)], 3600 * 6)
    assert result["effect_hint"] == "positive"


def test_match_explicit_feedback_helpful_false_gives_negative():
    adv = _advisory()
    row = _feedback_row(helpful=False)
    result = _match_explicit_feedback(adv, [(1, row)], 3600 * 6)
    assert result["effect_hint"] == "negative"


def test_match_explicit_feedback_match_type():
    adv = _advisory()
    row = _feedback_row()
    result = _match_explicit_feedback(adv, [(1, row)], 3600 * 6)
    assert result["match_type"] == "explicit_feedback"


def test_match_explicit_feedback_latency_non_negative():
    adv = _advisory(created_at=1_700_000_000.0)
    row = _feedback_row(ts=1_700_001_000.0)
    result = _match_explicit_feedback(adv, [(1, row)], 3600 * 6)
    assert result["latency_s"] >= 0.0


def test_match_explicit_feedback_picks_earliest_row():
    adv = _advisory(advisory_id="adv-001", created_at=1_000_000.0)
    row_early = _feedback_row(advice_ids=["adv-001"], ts=1_000_100.0)
    row_late = _feedback_row(advice_ids=["adv-001"], ts=1_000_500.0)
    result = _match_explicit_feedback(adv, [(1, row_early), (2, row_late)], 3600 * 6)
    assert result["matched_at"] == 1_000_100.0


# ---------------------------------------------------------------------------
# _match_implicit_outcome — no match cases
# ---------------------------------------------------------------------------

def test_match_implicit_outcome_no_session_id_returns_none():
    adv = _advisory(session_id="", tool="bash", created_at=1_000_000.0)
    result = _match_implicit_outcome(adv, [(1, _outcome_row())], 3600)
    assert result is None


def test_match_implicit_outcome_no_tool_returns_none():
    adv = _advisory(session_id="sess-1", tool="", created_at=1_000_000.0)
    result = _match_implicit_outcome(adv, [(1, _outcome_row())], 3600)
    assert result is None


def test_match_implicit_outcome_zero_created_at_returns_none():
    adv = _advisory(created_at=0.0)
    result = _match_implicit_outcome(adv, [(1, _outcome_row())], 3600)
    assert result is None


def test_match_implicit_outcome_wrong_session_returns_none():
    adv = _advisory(session_id="sess-1", tool="bash", created_at=1_000_000.0)
    row = _outcome_row(session_id="sess-other", tool="bash", ts=1_000_100.0)
    result = _match_implicit_outcome(adv, [(1, row)], 3600 * 6)
    assert result is None


def test_match_implicit_outcome_wrong_tool_returns_none():
    adv = _advisory(session_id="sess-1", tool="bash", created_at=1_000_000.0)
    row = _outcome_row(session_id="sess-1", tool="grep", ts=1_000_100.0)
    result = _match_implicit_outcome(adv, [(1, row)], 3600 * 6)
    assert result is None


# ---------------------------------------------------------------------------
# _match_implicit_outcome — match cases
# ---------------------------------------------------------------------------

def test_match_implicit_outcome_returns_dict_on_match():
    adv = _advisory(session_id="sess-1", tool="bash", created_at=1_000_000.0)
    row = _outcome_row(session_id="sess-1", tool="bash", ts=1_000_100.0)
    result = _match_implicit_outcome(adv, [(1, row)], 3600 * 6)
    assert isinstance(result, dict)


def test_match_implicit_outcome_status_is_acted():
    adv = _advisory(session_id="sess-1", tool="bash", created_at=1_000_000.0)
    row = _outcome_row(session_id="sess-1", tool="bash", ts=1_000_100.0)
    result = _match_implicit_outcome(adv, [(1, row)], 3600 * 6)
    assert result["status"] == "acted"


def test_match_implicit_outcome_polarity_pos_gives_positive():
    adv = _advisory(session_id="sess-1", tool="bash", created_at=1_000_000.0)
    row = _outcome_row(session_id="sess-1", tool="bash", ts=1_000_100.0, polarity="pos")
    result = _match_implicit_outcome(adv, [(1, row)], 3600 * 6)
    assert result["effect_hint"] == "positive"


def test_match_implicit_outcome_polarity_neg_gives_negative():
    adv = _advisory(session_id="sess-1", tool="bash", created_at=1_000_000.0)
    # Use a neutral event_type so polarity drives the hint
    row = _outcome_row(session_id="sess-1", tool="bash", ts=1_000_100.0, event_type="observed", polarity="neg")
    result = _match_implicit_outcome(adv, [(1, row)], 3600 * 6)
    assert result["effect_hint"] == "negative"


def test_match_implicit_outcome_event_type_success_gives_positive():
    adv = _advisory(session_id="sess-1", tool="bash", created_at=1_000_000.0)
    row = _outcome_row(session_id="sess-1", tool="bash", ts=1_000_100.0, event_type="post_tool_success")
    result = _match_implicit_outcome(adv, [(1, row)], 3600 * 6)
    assert result["effect_hint"] == "positive"


def test_match_implicit_outcome_match_type():
    adv = _advisory(session_id="sess-1", tool="bash", created_at=1_000_000.0)
    row = _outcome_row(session_id="sess-1", tool="bash", ts=1_000_100.0)
    result = _match_implicit_outcome(adv, [(1, row)], 3600 * 6)
    assert result["match_type"] == "implicit_outcome"


def test_match_implicit_outcome_tool_case_insensitive():
    adv = _advisory(session_id="sess-1", tool="Bash", created_at=1_000_000.0)
    row = _outcome_row(session_id="sess-1", tool="bash", ts=1_000_100.0)
    result = _match_implicit_outcome(adv, [(1, row)], 3600 * 6)
    assert result is not None


# ---------------------------------------------------------------------------
# match_actions — integration
# ---------------------------------------------------------------------------

def test_match_actions_returns_list(tmp_path):
    result = match_actions(
        [_advisory()],
        feedback_file=tmp_path / "f.jsonl",
        reports_dir=tmp_path / "reports",
        outcomes_file=tmp_path / "out.jsonl",
    )
    assert isinstance(result, list)


def test_match_actions_one_advisory_one_result(tmp_path):
    result = match_actions(
        [_advisory()],
        feedback_file=tmp_path / "f.jsonl",
        reports_dir=tmp_path / "reports",
        outcomes_file=tmp_path / "out.jsonl",
    )
    assert len(result) == 1


def test_match_actions_unresolved_when_no_match(tmp_path):
    result = match_actions(
        [_advisory()],
        feedback_file=tmp_path / "f.jsonl",
        reports_dir=tmp_path / "reports",
        outcomes_file=tmp_path / "out.jsonl",
    )
    assert result[0]["status"] == "unresolved"


def test_match_actions_propagates_advisory_instance_id(tmp_path):
    adv = _advisory(advisory_instance_id="my-inst-id")
    result = match_actions(
        [adv],
        feedback_file=tmp_path / "f.jsonl",
        reports_dir=tmp_path / "reports",
        outcomes_file=tmp_path / "out.jsonl",
    )
    assert result[0]["advisory_instance_id"] == "my-inst-id"


def test_match_actions_uses_feedback_file(tmp_path):
    fb = tmp_path / "feedback.jsonl"
    row = _feedback_row(advice_ids=["adv-001"], ts=1_700_001_000.0, followed=True, helpful=True)
    _write_jsonl(fb, [row])
    adv = _advisory(advisory_id="adv-001", created_at=1_700_000_000.0)
    result = match_actions(
        [adv],
        feedback_file=fb,
        reports_dir=tmp_path / "reports",
        outcomes_file=tmp_path / "out.jsonl",
        max_match_window_s=6 * 3600,
    )
    assert result[0]["status"] == "acted"
    assert result[0]["match_type"] == "explicit_feedback"


def test_match_actions_empty_advisories_returns_empty(tmp_path):
    result = match_actions(
        [],
        feedback_file=tmp_path / "f.jsonl",
        reports_dir=tmp_path / "reports",
        outcomes_file=tmp_path / "out.jsonl",
    )
    assert result == []
