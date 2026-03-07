"""Tests for lib/advice_feedback.py — 55 tests."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import lib.advice_feedback as af


# ---------------------------------------------------------------------------
# _session_lineage
# ---------------------------------------------------------------------------

class TestSessionLineage:
    def test_empty_session_id_returns_unknown(self):
        r = af._session_lineage("")
        assert r["session_kind"] == "unknown"
        assert r["is_subagent"] is False
        assert r["depth_hint"] == 0

    def test_none_session_id_returns_unknown(self):
        r = af._session_lineage(None)
        assert r["session_kind"] == "unknown"

    def test_subagent_detected(self):
        r = af._session_lineage("abc123:subagent:xyz")
        assert r["session_kind"] == "subagent"
        assert r["is_subagent"] is True
        assert r["depth_hint"] == 2
        assert r["session_tree_key"] == "abc123"
        assert r["root_session_hint"] == "abc123:main"
        assert r["parent_session_hint"] == "abc123:main"

    def test_cron_detected(self):
        r = af._session_lineage("abc123:cron:job1")
        assert r["session_kind"] == "cron"
        assert r["is_subagent"] is False
        assert r["depth_hint"] == 1
        assert r["session_tree_key"] == "abc123"
        assert r["root_session_hint"] == "abc123:cron:job1"
        assert r["parent_session_hint"] == ""

    def test_main_detected(self):
        r = af._session_lineage("abc123:main")
        assert r["session_kind"] == "main"
        assert r["is_subagent"] is False
        assert r["depth_hint"] == 1
        assert r["session_tree_key"] == "abc123"
        assert r["root_session_hint"] == "abc123:main"
        assert r["parent_session_hint"] == ""

    def test_other_session(self):
        r = af._session_lineage("random-id")
        assert r["session_kind"] == "other"
        assert r["is_subagent"] is False
        assert r["depth_hint"] == 1
        assert r["session_tree_key"] == "random-id"

    def test_whitespace_stripped(self):
        r = af._session_lineage("  ")
        assert r["session_kind"] == "unknown"

    def test_all_lineage_keys_present(self):
        for sid in ["", "abc:main", "abc:subagent:x", "abc:cron:y", "other"]:
            r = af._session_lineage(sid)
            for key in ("session_kind", "is_subagent", "depth_hint",
                        "session_tree_key", "root_session_hint", "parent_session_hint"):
                assert key in r, f"Missing key {key} for sid={sid!r}"


# ---------------------------------------------------------------------------
# _correlation_ids
# ---------------------------------------------------------------------------

class TestCorrelationIds:
    def test_returns_expected_keys(self):
        r = af._correlation_ids(
            session_id="s1", tool="tool1", trace_id="t1",
            advice_ids=["a1", "a2"],
        )
        for key in ("trace_id", "run_id", "primary_advisory_id", "advisory_group_key"):
            assert key in r

    def test_primary_advisory_id_is_first_advice_id(self):
        r = af._correlation_ids(
            session_id="s", tool="t", trace_id="tid", advice_ids=["first", "second"]
        )
        assert r["primary_advisory_id"] == "first"

    def test_no_advice_ids_primary_is_none(self):
        r = af._correlation_ids(session_id="s", tool="t", trace_id="tid", advice_ids=[])
        assert r["primary_advisory_id"] is None

    def test_deterministic_group_key(self):
        kwargs = dict(session_id="s", tool="t", trace_id="tid", advice_ids=["a"])
        r1 = af._correlation_ids(**kwargs)
        r2 = af._correlation_ids(**kwargs)
        assert r1["advisory_group_key"] == r2["advisory_group_key"]

    def test_different_inputs_different_group_key(self):
        r1 = af._correlation_ids(session_id="s1", tool="t", trace_id="tid", advice_ids=["a"])
        r2 = af._correlation_ids(session_id="s2", tool="t", trace_id="tid", advice_ids=["a"])
        assert r1["advisory_group_key"] != r2["advisory_group_key"]

    def test_explicit_run_id_preserved(self):
        r = af._correlation_ids(
            session_id="s", tool="t", trace_id="tid", advice_ids=[], run_id="explicit-run"
        )
        assert r["run_id"] == "explicit-run"

    def test_auto_generated_run_id_when_none(self):
        r = af._correlation_ids(session_id="s", tool="t", trace_id="tid", advice_ids=[])
        assert r["run_id"] and len(r["run_id"]) == 20

    def test_empty_trace_id_returns_none(self):
        r = af._correlation_ids(session_id="s", tool="t", trace_id="", advice_ids=[])
        assert r["trace_id"] is None

    def test_group_key_length_is_24(self):
        r = af._correlation_ids(session_id="s", tool="t", trace_id="tid", advice_ids=["x"])
        assert len(r["advisory_group_key"]) == 24


# ---------------------------------------------------------------------------
# _load_state / _save_state
# ---------------------------------------------------------------------------

class TestStateIO:
    def test_load_returns_empty_dict_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(af, "STATE_FILE", tmp_path / "nope.json")
        assert af._load_state() == {}

    def test_load_returns_empty_dict_on_corrupt(self, tmp_path, monkeypatch):
        p = tmp_path / "s.json"
        p.write_text("BAD", encoding="utf-8")
        monkeypatch.setattr(af, "STATE_FILE", p)
        assert af._load_state() == {}

    def test_save_creates_parents(self, tmp_path, monkeypatch):
        p = tmp_path / "a" / "b" / "s.json"
        monkeypatch.setattr(af, "STATE_FILE", p)
        monkeypatch.setattr(af, "log_debug", lambda *a: None)
        af._save_state({"x": 1})
        assert p.exists()

    def test_roundtrip(self, tmp_path, monkeypatch):
        p = tmp_path / "s.json"
        monkeypatch.setattr(af, "STATE_FILE", p)
        monkeypatch.setattr(af, "log_debug", lambda *a: None)
        af._save_state({"last_by_tool": {"my_tool": 12345}})
        loaded = af._load_state()
        assert loaded["last_by_tool"]["my_tool"] == 12345


# ---------------------------------------------------------------------------
# record_advice_request
# ---------------------------------------------------------------------------

class TestRecordAdviceRequest:
    def _patch(self, monkeypatch, tmp_path):
        monkeypatch.setattr(af, "REQUESTS_FILE", tmp_path / "requests.jsonl")
        monkeypatch.setattr(af, "STATE_FILE", tmp_path / "state.json")
        monkeypatch.setattr(af, "log_debug", lambda *a: None)

    def test_records_request_with_trace_id(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        result = af.record_advice_request(
            session_id="s:main",
            tool="Bash",
            advice_ids=["a1"],
            trace_id="trace-abc",
        )
        assert result is True
        lines = (tmp_path / "requests.jsonl").read_text().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["tool"] == "Bash"
        assert row["trace_id"] == "trace-abc"

    def test_skipped_when_no_trace_id(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        result = af.record_advice_request(
            session_id="s", tool="Bash", advice_ids=["a1"],
        )
        assert result is False

    def test_rate_limited_within_min_interval(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        # Write state showing tool was called just now
        state_p = tmp_path / "state.json"
        state_p.write_text(json.dumps({"last_by_tool": {"Bash": time.time()}}))
        result = af.record_advice_request(
            session_id="s", tool="Bash", advice_ids=["a"],
            trace_id="t", min_interval_s=600,
        )
        assert result is False

    def test_not_rate_limited_when_interval_elapsed(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        state_p = tmp_path / "state.json"
        state_p.write_text(json.dumps({"last_by_tool": {"Bash": time.time() - 700}}))
        result = af.record_advice_request(
            session_id="s", tool="Bash", advice_ids=["a"],
            trace_id="t", min_interval_s=600,
        )
        assert result is True

    def test_advice_ids_capped_at_20(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        ids = [f"a{i}" for i in range(30)]
        af.record_advice_request(
            session_id="s", tool="T", advice_ids=ids, trace_id="t"
        )
        row = json.loads((tmp_path / "requests.jsonl").read_text().splitlines()[0])
        assert len(row["advice_ids"]) <= 20

    def test_schema_version_in_row(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        af.record_advice_request(session_id="s", tool="T", advice_ids=["x"], trace_id="t")
        row = json.loads((tmp_path / "requests.jsonl").read_text().splitlines()[0])
        assert row["schema_version"] == af.CORRELATION_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# list_requests / has_recent_requests
# ---------------------------------------------------------------------------

class TestListRequests:
    def test_empty_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(af, "REQUESTS_FILE", tmp_path / "nope.jsonl")
        assert af.list_requests() == []

    def test_returns_up_to_limit(self, tmp_path, monkeypatch):
        p = tmp_path / "req.jsonl"
        for i in range(20):
            p.open("a").write(json.dumps({"created_at": time.time(), "idx": i}) + "\n")
        monkeypatch.setattr(af, "REQUESTS_FILE", p)
        result = af.list_requests(limit=5)
        assert len(result) <= 5

    def test_max_age_filter(self, tmp_path, monkeypatch):
        p = tmp_path / "req.jsonl"
        old_ts = time.time() - 7200
        p.write_text(json.dumps({"created_at": old_ts}) + "\n")
        monkeypatch.setattr(af, "REQUESTS_FILE", p)
        result = af.list_requests(limit=10, max_age_s=3600)
        assert result == []

    def test_recent_request_not_filtered(self, tmp_path, monkeypatch):
        p = tmp_path / "req.jsonl"
        p.write_text(json.dumps({"created_at": time.time()}) + "\n")
        monkeypatch.setattr(af, "REQUESTS_FILE", p)
        result = af.list_requests(limit=10, max_age_s=3600)
        assert len(result) == 1

    def test_has_recent_requests_true(self, tmp_path, monkeypatch):
        p = tmp_path / "req.jsonl"
        p.write_text(json.dumps({"created_at": time.time()}) + "\n")
        monkeypatch.setattr(af, "REQUESTS_FILE", p)
        assert af.has_recent_requests() is True

    def test_has_recent_requests_false_when_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(af, "REQUESTS_FILE", tmp_path / "nope.jsonl")
        assert af.has_recent_requests() is False

    def test_skips_corrupt_lines(self, tmp_path, monkeypatch):
        p = tmp_path / "req.jsonl"
        p.write_text("BAD JSON\n" + json.dumps({"created_at": time.time()}) + "\n")
        monkeypatch.setattr(af, "REQUESTS_FILE", p)
        result = af.list_requests(limit=10)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# record_feedback
# ---------------------------------------------------------------------------

class TestRecordFeedback:
    def _patch(self, monkeypatch, tmp_path):
        monkeypatch.setattr(af, "FEEDBACK_FILE", tmp_path / "feedback.jsonl")
        monkeypatch.setattr(af, "log_debug", lambda *a: None)

    def test_basic_record_returns_true(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        r = af.record_feedback(
            advice_ids=["a1"], tool="Bash", helpful=True, followed=True
        )
        assert r is True

    def test_row_written_to_file(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        af.record_feedback(
            advice_ids=["a1"], tool="Bash", helpful=True, followed=False,
            status="acted", outcome="good", notes="nice"
        )
        row = json.loads((tmp_path / "feedback.jsonl").read_text().splitlines()[0])
        assert row["tool"] == "Bash"
        assert row["helpful"] is True
        assert row["followed"] is False
        assert row["status"] == "acted"
        assert row["outcome"] == "good"
        assert row["notes"] == "nice"

    def test_invalid_status_cleared(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        af.record_feedback(advice_ids=["a"], tool="T", helpful=None,
                           followed=True, status="INVALID_STATUS")
        row = json.loads((tmp_path / "feedback.jsonl").read_text().splitlines()[0])
        assert row["status"] is None

    def test_invalid_outcome_cleared(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        af.record_feedback(advice_ids=["a"], tool="T", helpful=None,
                           followed=True, outcome="WEIRD")
        row = json.loads((tmp_path / "feedback.jsonl").read_text().splitlines()[0])
        assert row["outcome"] is None

    def test_valid_status_values_preserved(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        for status in ("acted", "blocked", "harmful", "ignored", "skipped"):
            af.record_feedback(advice_ids=["a"], tool="T", helpful=None,
                               followed=False, status=status)
        rows = [json.loads(l) for l in (tmp_path / "feedback.jsonl").read_text().splitlines()]
        found = {r["status"] for r in rows}
        assert found == {"acted", "blocked", "harmful", "ignored", "skipped"}

    def test_schema_version_set(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        af.record_feedback(advice_ids=["a"], tool="T", helpful=True, followed=True)
        row = json.loads((tmp_path / "feedback.jsonl").read_text().splitlines()[0])
        assert row["schema_version"] == af.CORRELATION_SCHEMA_VERSION

    def test_notes_truncated_at_200(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        af.record_feedback(advice_ids=["a"], tool="T", helpful=None,
                           followed=False, notes="X" * 300)
        row = json.loads((tmp_path / "feedback.jsonl").read_text().splitlines()[0])
        assert len(row["notes"]) <= 200


# ---------------------------------------------------------------------------
# analyze_feedback
# ---------------------------------------------------------------------------

class TestAnalyzeFeedback:
    def _patch(self, monkeypatch, tmp_path):
        monkeypatch.setattr(af, "FEEDBACK_FILE", tmp_path / "fb.jsonl")
        monkeypatch.setattr(af, "SUMMARY_FILE", tmp_path / "summary.json")
        monkeypatch.setattr(af, "log_debug", lambda *a: None)
        return tmp_path / "fb.jsonl"

    def test_returns_empty_message_when_no_file(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        result = af.analyze_feedback()
        assert result["total"] == 0
        assert "No advice feedback yet" in result.get("message", "")

    def test_counts_total_feedback(self, monkeypatch, tmp_path):
        fb_file = self._patch(monkeypatch, tmp_path)
        for i in range(5):
            fb_file.open("a").write(json.dumps({
                "helpful": True, "tool": "Bash", "sources": [], "insight_keys": []
            }) + "\n")
        result = af.analyze_feedback(write_summary=False)
        assert result["total_feedback"] == 5

    def test_helpful_rate_calculated(self, monkeypatch, tmp_path):
        fb_file = self._patch(monkeypatch, tmp_path)
        for helpful in [True, True, False]:
            fb_file.open("a").write(json.dumps({
                "helpful": helpful, "tool": "T", "sources": [], "insight_keys": []
            }) + "\n")
        result = af.analyze_feedback(write_summary=False)
        assert abs(result["helpful_rate"] - 2/3) < 0.01

    def test_summary_written_to_file(self, monkeypatch, tmp_path):
        fb_file = self._patch(monkeypatch, tmp_path)
        fb_file.write_text(json.dumps({"helpful": True, "tool": "T", "sources": [], "insight_keys": []}) + "\n")
        af.analyze_feedback(write_summary=True)
        assert (tmp_path / "summary.json").exists()

    def test_recommendations_for_low_helpful_rate(self, monkeypatch, tmp_path):
        fb_file = self._patch(monkeypatch, tmp_path)
        # All unhelpful for the same tool, min_samples met
        for _ in range(5):
            fb_file.open("a").write(json.dumps({
                "helpful": False, "tool": "BadTool", "sources": [], "insight_keys": []
            }) + "\n")
        result = af.analyze_feedback(min_samples=3, write_summary=False)
        assert any("BadTool" in r for r in result["recommendations"])

    def test_skips_corrupt_lines(self, monkeypatch, tmp_path):
        fb_file = self._patch(monkeypatch, tmp_path)
        fb_file.write_text("BAD LINE\n" + json.dumps({
            "helpful": True, "tool": "T", "sources": [], "insight_keys": []
        }) + "\n")
        result = af.analyze_feedback(write_summary=False)
        assert result["total_feedback"] == 1
