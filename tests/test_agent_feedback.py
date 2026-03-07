"""Tests for lib/agent_feedback.py — agent-side advisory feedback helpers."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.agent_feedback as af
from lib.agent_feedback import (
    advisory_acted,
    advisory_skipped,
    learned_something,
    preference,
    decision_made,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(af, "REPORTS_DIR", tmp_path)
    return tmp_path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# _write_report internals (via public API)
# ---------------------------------------------------------------------------


def test_write_report_creates_parent_dir(monkeypatch, tmp_path):
    nested = tmp_path / "a" / "b"
    monkeypatch.setattr(af, "REPORTS_DIR", nested)
    advisory_acted("do x", "x worked")
    assert nested.exists()


def test_write_report_returns_path(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    result = advisory_acted("advice", "outcome")
    assert isinstance(result, Path)
    assert result.exists()


def test_write_report_filename_has_kind(monkeypatch, tmp_path):
    d = _patch(monkeypatch, tmp_path)
    path = advisory_acted("x", "y")
    assert path.name.startswith("outcome_")


def test_write_report_filename_has_timestamp(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    import re
    path = advisory_acted("x", "y")
    assert re.search(r"\d{8}_\d{6}", path.name)


def test_write_report_filename_ends_with_json(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    path = advisory_acted("x", "y")
    assert path.suffix == ".json"


def test_write_report_has_ts(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    before = time.time()
    path = advisory_acted("x", "y")
    after = time.time()
    data = _read(path)
    assert before <= data["ts"] <= after


def test_write_report_multiple_calls_unique_files(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    p1 = advisory_acted("x", "y")
    p2 = advisory_acted("a", "b")
    assert p1 != p2


# ---------------------------------------------------------------------------
# advisory_acted
# ---------------------------------------------------------------------------


def test_advisory_acted_kind_is_outcome(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(advisory_acted("use cache", "cache hit 92%"))
    assert data["kind"] == "outcome"


def test_advisory_acted_result_stored(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(advisory_acted("advice text", "RAM dropped to 68MB"))
    assert data["result"] == "RAM dropped to 68MB"


def test_advisory_acted_lesson_contains_recommendation(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(advisory_acted("disable fastembed", "memory improved"))
    assert "disable fastembed" in data["lesson"]


def test_advisory_acted_success_true_by_default(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(advisory_acted("x", "y"))
    assert data["success"] is True


def test_advisory_acted_success_false_stored(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(advisory_acted("x", "y", success=False))
    assert data["success"] is False


def test_advisory_acted_advisory_ref_stored(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(advisory_acted("use caching", "hit rate improved"))
    assert "advisory_ref" in data
    assert "use caching" in data["advisory_ref"]


def test_advisory_acted_advisory_ref_truncated_at_200(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    long_rec = "r" * 400
    data = _read(advisory_acted(long_rec, "result"))
    assert len(data["advisory_ref"]) <= 200


def test_advisory_acted_source_is_spark_advisory(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(advisory_acted("x", "y"))
    assert data["source"] == "spark_advisory"


# ---------------------------------------------------------------------------
# advisory_skipped
# ---------------------------------------------------------------------------


def test_advisory_skipped_kind_is_decision(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(advisory_skipped("run tests"))
    assert data["kind"] == "decision"


def test_advisory_skipped_intent_stored(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(advisory_skipped("run tests"))
    assert "intent" in data


def test_advisory_skipped_reason_in_reasoning(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(advisory_skipped("run tests", reason="no CI available"))
    assert "no CI available" in data["reasoning"]


def test_advisory_skipped_default_reason_uses_recommendation(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(advisory_skipped("add auth check"))
    assert "add auth check" in data["reasoning"]


def test_advisory_skipped_source_is_spark_advisory(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(advisory_skipped("x"))
    assert data["source"] == "spark_advisory"


def test_advisory_skipped_confidence_stored(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(advisory_skipped("x"))
    assert "confidence" in data


# ---------------------------------------------------------------------------
# learned_something
# ---------------------------------------------------------------------------


def test_learned_something_kind_is_outcome(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(learned_something("TTL 5m is optimal"))
    assert data["kind"] == "outcome"


def test_learned_something_lesson_stored(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(learned_something("PowerShell chokes on large responses"))
    assert data["lesson"] == "PowerShell chokes on large responses"


def test_learned_something_context_in_result(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(learned_something("lesson here", context="during debug session"))
    assert data["result"] == "during debug session"


def test_learned_something_default_result_when_no_context(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(learned_something("lesson here"))
    assert data["result"] == "Session learning"


def test_learned_something_success_true(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(learned_something("x"))
    assert data["success"] is True


def test_learned_something_source_is_agent_session(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(learned_something("x"))
    assert data["source"] == "agent_session"


# ---------------------------------------------------------------------------
# preference
# ---------------------------------------------------------------------------


def test_preference_kind_is_preference(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(preference(liked="dark mode"))
    assert data["kind"] == "preference"


def test_preference_liked_stored(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(preference(liked="concise summaries"))
    assert data["liked"] == "concise summaries"


def test_preference_disliked_stored(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(preference(disliked="verbose tool output"))
    assert data["disliked"] == "verbose tool output"


def test_preference_source_is_agent_preference(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(preference(liked="x"))
    assert data["source"] == "agent_preference"


def test_preference_defaults_to_empty_strings(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(preference())
    assert data["liked"] == ""
    assert data["disliked"] == ""


# ---------------------------------------------------------------------------
# decision_made
# ---------------------------------------------------------------------------


def test_decision_made_kind_is_decision(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(decision_made("use 2MB threshold", "44MB was excessive"))
    assert data["kind"] == "decision"


def test_decision_made_intent_stored(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(decision_made("use caching", "reduce latency"))
    assert data["intent"] == "use caching"


def test_decision_made_reasoning_stored(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(decision_made("x", "because of latency"))
    assert data["reasoning"] == "because of latency"


def test_decision_made_confidence_default_07(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(decision_made("x", "y"))
    assert data["confidence"] == 0.7


def test_decision_made_confidence_custom(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(decision_made("x", "y", confidence=0.95))
    assert data["confidence"] == 0.95


def test_decision_made_source_is_agent_decision(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    data = _read(decision_made("x", "y"))
    assert data["source"] == "agent_decision"
