"""Tests for lib/action_matcher.py — map advisory recommendations to observed actions."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.action_matcher as am


# ---------------------------------------------------------------------------
# _norm
# ---------------------------------------------------------------------------

class TestNorm:
    def test_lowercases(self):
        assert am._norm("HELLO") == "hello"

    def test_collapses_whitespace(self):
        assert am._norm("a  b   c") == "a b c"

    def test_strips(self):
        assert am._norm("  hi  ") == "hi"

    def test_none_like(self):
        assert am._norm(None) == ""  # type: ignore[arg-type]

    def test_empty(self):
        assert am._norm("") == ""

    def test_mixed_whitespace(self):
        assert am._norm("a\t  b\n  c") == "a b c"


# ---------------------------------------------------------------------------
# _text_sim
# ---------------------------------------------------------------------------

class TestTextSim:
    def test_identical_strings_return_1(self):
        assert am._text_sim("hello world", "hello world") == 1.0

    def test_substring_returns_1(self):
        assert am._text_sim("fix the bug", "fix the bug in the code") == 1.0

    def test_empty_a_returns_0(self):
        assert am._text_sim("", "something") == 0.0

    def test_empty_b_returns_0(self):
        assert am._text_sim("something", "") == 0.0

    def test_both_empty_returns_0(self):
        assert am._text_sim("", "") == 0.0

    def test_partial_similarity(self):
        sim = am._text_sim("hello world", "hello earth")
        assert 0.0 < sim < 1.0

    def test_completely_different(self):
        sim = am._text_sim("aaaa", "zzzz")
        assert sim < 0.5

    def test_case_insensitive(self):
        assert am._text_sim("HELLO", "hello") == 1.0


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTs:
    def test_created_at(self):
        row = {"created_at": 1234.5}
        assert am._parse_ts(row) == 1234.5

    def test_ts(self):
        row = {"ts": 9999.0}
        assert am._parse_ts(row) == 9999.0

    def test_timestamp(self):
        row = {"timestamp": 5555.0}
        assert am._parse_ts(row) == 5555.0

    def test_priority_created_at_first(self):
        row = {"created_at": 100.0, "ts": 200.0}
        assert am._parse_ts(row) == 100.0

    def test_missing_returns_zero(self):
        assert am._parse_ts({}) == 0.0

    def test_non_numeric_value_skipped(self):
        row = {"created_at": "not_a_number", "ts": 42.0}
        assert am._parse_ts(row) == 42.0

    def test_float_string_parses(self):
        row = {"created_at": "1234.5"}
        assert am._parse_ts(row) == 1234.5


# ---------------------------------------------------------------------------
# _read_jsonl
# ---------------------------------------------------------------------------

class TestReadJsonl:
    def test_missing_file_returns_empty(self, tmp_path):
        p = tmp_path / "missing.jsonl"
        assert am._read_jsonl(p) == []

    def test_reads_valid_lines(self, tmp_path):
        p = tmp_path / "data.jsonl"
        p.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
        rows = am._read_jsonl(p)
        assert len(rows) == 2
        assert rows[0] == (1, {"a": 1})
        assert rows[1] == (2, {"b": 2})

    def test_skips_invalid_json(self, tmp_path):
        p = tmp_path / "mixed.jsonl"
        p.write_text('{"ok": 1}\nBAD\n{"ok2": 2}\n', encoding="utf-8")
        rows = am._read_jsonl(p)
        assert len(rows) == 2

    def test_line_numbers_start_at_1(self, tmp_path):
        p = tmp_path / "nums.jsonl"
        p.write_text('{"x": 1}\n', encoding="utf-8")
        rows = am._read_jsonl(p)
        assert rows[0][0] == 1


# ---------------------------------------------------------------------------
# _load_reports
# ---------------------------------------------------------------------------

class TestLoadReports:
    def test_missing_dir_returns_empty(self, tmp_path):
        p = tmp_path / "nonexistent"
        assert am._load_reports(p) == []

    def test_loads_json_files(self, tmp_path):
        d = tmp_path / "reports"
        d.mkdir()
        (d / "r1.json").write_text('{"kind": "outcome"}', encoding="utf-8")
        (d / "r2.json").write_text('{"kind": "decision"}', encoding="utf-8")
        rows = am._load_reports(d)
        assert len(rows) == 2

    def test_skips_invalid_json(self, tmp_path):
        d = tmp_path / "reports"
        d.mkdir()
        (d / "bad.json").write_text("not json", encoding="utf-8")
        (d / "ok.json").write_text('{"kind": "outcome"}', encoding="utf-8")
        rows = am._load_reports(d)
        assert len(rows) == 1

    def test_ignores_non_json_files(self, tmp_path):
        d = tmp_path / "reports"
        d.mkdir()
        (d / "notes.txt").write_text("not json", encoding="utf-8")
        rows = am._load_reports(d)
        assert rows == []

    def test_returns_filepath_and_row(self, tmp_path):
        d = tmp_path / "reports"
        d.mkdir()
        (d / "r1.json").write_text('{"key": "val"}', encoding="utf-8")
        rows = am._load_reports(d)
        fp, row = rows[0]
        assert fp.endswith(".json")
        assert row == {"key": "val"}


# ---------------------------------------------------------------------------
# _match_explicit_feedback
# ---------------------------------------------------------------------------

class TestMatchExplicitFeedback:
    def _advisory(self, advisory_id="adv1", created_at=1000.0):
        return {"advisory_id": advisory_id, "created_at": created_at}

    def _fb_row(self, advice_ids, followed=True, helpful=True, ts=1500.0, notes=""):
        return (1, {
            "advice_ids": advice_ids,
            "followed": followed,
            "helpful": helpful,
            "created_at": ts,
            "notes": notes,
        })

    def test_no_match_returns_none(self):
        adv = self._advisory()
        rows = [self._fb_row(["other_id"])]
        result = am._match_explicit_feedback(adv, rows, 6 * 3600)
        assert result is None

    def test_matches_by_advisory_id(self):
        adv = self._advisory("adv1", 1000.0)
        rows = [self._fb_row(["adv1"], followed=True, helpful=True, ts=1500.0)]
        result = am._match_explicit_feedback(adv, rows, 6 * 3600)
        assert result is not None
        assert result["status"] == "acted"
        assert result["effect_hint"] == "positive"

    def test_skipped_when_not_followed(self):
        adv = self._advisory("adv1", 1000.0)
        rows = [self._fb_row(["adv1"], followed=False, helpful=False, ts=1500.0)]
        result = am._match_explicit_feedback(adv, rows, 6 * 3600)
        assert result["status"] == "skipped"
        assert result["effect_hint"] == "negative"

    def test_outside_window_returns_none(self):
        adv = self._advisory("adv1", 1000.0)
        # ts is 8 hours after advisory — outside 6h window
        rows = [self._fb_row(["adv1"], ts=1000.0 + 8 * 3600)]
        result = am._match_explicit_feedback(adv, rows, 6 * 3600)
        assert result is None

    def test_before_advisory_returns_none(self):
        adv = self._advisory("adv1", 1000.0)
        rows = [self._fb_row(["adv1"], ts=500.0)]
        result = am._match_explicit_feedback(adv, rows, 6 * 3600)
        assert result is None

    def test_missing_advisory_id_returns_none(self):
        adv = {"advisory_id": "", "created_at": 1000.0}
        rows = [self._fb_row([""], ts=1500.0)]
        result = am._match_explicit_feedback(adv, rows, 6 * 3600)
        assert result is None

    def test_helpful_none_is_neutral(self):
        adv = self._advisory("adv1", 1000.0)
        rows = [(1, {"advice_ids": ["adv1"], "followed": True, "helpful": None, "created_at": 1500.0})]
        result = am._match_explicit_feedback(adv, rows, 6 * 3600)
        assert result["effect_hint"] == "neutral"

    def test_latency_non_negative(self):
        adv = self._advisory("adv1", 1000.0)
        rows = [self._fb_row(["adv1"], ts=1500.0)]
        result = am._match_explicit_feedback(adv, rows, 6 * 3600)
        assert result["latency_s"] >= 0

    def test_match_type_is_explicit_feedback(self):
        adv = self._advisory("adv1", 1000.0)
        rows = [self._fb_row(["adv1"], ts=1500.0)]
        result = am._match_explicit_feedback(adv, rows, 6 * 3600)
        assert result["match_type"] == "explicit_feedback"


# ---------------------------------------------------------------------------
# _match_implicit_outcome
# ---------------------------------------------------------------------------

class TestMatchImplicitOutcome:
    def _advisory(self, session_id="sess1", tool="Bash", created_at=1000.0):
        return {"advisory_instance_id": "inst1", "created_at": created_at, "session_id": session_id, "tool": tool}

    def test_no_match_different_session(self):
        adv = self._advisory(session_id="s1", tool="Bash")
        rows = [(1, {"created_at": 1500.0, "session_id": "s2", "tool": "Bash", "event_type": "success"})]
        result = am._match_implicit_outcome(adv, rows, 6 * 3600)
        assert result is None

    def test_no_match_different_tool(self):
        adv = self._advisory(session_id="s1", tool="Bash")
        rows = [(1, {"created_at": 1500.0, "session_id": "s1", "tool": "Write", "event_type": "success"})]
        result = am._match_implicit_outcome(adv, rows, 6 * 3600)
        assert result is None

    def test_matches_session_and_tool(self):
        adv = self._advisory(session_id="s1", tool="Bash", created_at=1000.0)
        rows = [(1, {"created_at": 1500.0, "session_id": "s1", "tool": "bash", "event_type": "tool_success"})]
        result = am._match_implicit_outcome(adv, rows, 6 * 3600)
        assert result is not None
        assert result["status"] == "acted"

    def test_success_polarity(self):
        adv = self._advisory(session_id="s1", tool="Bash", created_at=1000.0)
        rows = [(1, {"created_at": 1500.0, "session_id": "s1", "tool": "bash", "event_type": "tool_success"})]
        result = am._match_implicit_outcome(adv, rows, 6 * 3600)
        assert result["effect_hint"] == "positive"

    def test_failure_polarity(self):
        adv = self._advisory(session_id="s1", tool="Bash", created_at=1000.0)
        rows = [(1, {"created_at": 1500.0, "session_id": "s1", "tool": "bash", "event_type": "tool_failure"})]
        result = am._match_implicit_outcome(adv, rows, 6 * 3600)
        assert result["effect_hint"] == "negative"

    def test_missing_session_or_tool_returns_none(self):
        adv = {"created_at": 1000.0, "session_id": "", "tool": ""}
        rows = [(1, {"created_at": 1500.0})]
        result = am._match_implicit_outcome(adv, rows, 6 * 3600)
        assert result is None

    def test_confidence_hint_lower(self):
        adv = self._advisory(session_id="s1", tool="Bash", created_at=1000.0)
        rows = [(1, {"created_at": 1500.0, "session_id": "s1", "tool": "bash"})]
        result = am._match_implicit_outcome(adv, rows, 6 * 3600)
        if result:
            assert result["confidence_hint"] < 0.9


# ---------------------------------------------------------------------------
# match_actions (integration)
# ---------------------------------------------------------------------------

class TestMatchActions:
    def test_empty_advisories_returns_empty(self, tmp_path):
        result = am.match_actions(
            [],
            feedback_file=tmp_path / "f.jsonl",
            reports_dir=tmp_path / "rep",
            outcomes_file=tmp_path / "o.jsonl",
        )
        assert result == []

    def test_unresolved_when_no_match(self, tmp_path):
        advisories = [{"advisory_instance_id": "i1", "advisory_id": "a1", "created_at": 1000.0,
                       "session_id": "s", "tool": "t", "recommendation": "Do X"}]
        result = am.match_actions(
            advisories,
            feedback_file=tmp_path / "f.jsonl",
            reports_dir=tmp_path / "rep",
            outcomes_file=tmp_path / "o.jsonl",
        )
        assert len(result) == 1
        assert result[0]["status"] == "unresolved"
        assert result[0]["advisory_instance_id"] == "i1"

    def test_match_via_explicit_feedback(self, tmp_path):
        fb = tmp_path / "feedback.jsonl"
        fb.write_text(json.dumps({
            "advice_ids": ["adv1"],
            "followed": True,
            "helpful": True,
            "created_at": 2000.0,
        }) + "\n", encoding="utf-8")

        advisories = [{"advisory_instance_id": "inst1", "advisory_id": "adv1",
                       "created_at": 1000.0, "session_id": "s", "tool": "t",
                       "recommendation": "Do X"}]
        result = am.match_actions(
            advisories,
            feedback_file=fb,
            reports_dir=tmp_path / "rep",
            outcomes_file=tmp_path / "o.jsonl",
            max_match_window_s=6 * 3600,
        )
        assert result[0]["status"] == "acted"
        assert result[0]["match_type"] == "explicit_feedback"

    def test_advisory_instance_id_preserved_in_unresolved(self, tmp_path):
        advisories = [{"advisory_instance_id": "XYZ123", "created_at": 1.0,
                       "session_id": "", "tool": "", "recommendation": "tip"}]
        result = am.match_actions(advisories, feedback_file=tmp_path / "f.jsonl",
                                  reports_dir=tmp_path / "r", outcomes_file=tmp_path / "o.jsonl")
        assert result[0]["advisory_instance_id"] == "XYZ123"

    def test_multiple_advisories_all_returned(self, tmp_path):
        advisories = [
            {"advisory_instance_id": f"i{k}", "advisory_id": f"a{k}",
             "created_at": float(k), "session_id": "s", "tool": "t", "recommendation": f"tip{k}"}
            for k in range(5)
        ]
        result = am.match_actions(advisories, feedback_file=tmp_path / "f.jsonl",
                                  reports_dir=tmp_path / "r", outcomes_file=tmp_path / "o.jsonl")
        assert len(result) == 5
