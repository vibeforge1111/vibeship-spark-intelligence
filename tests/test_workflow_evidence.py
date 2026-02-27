"""Tests for lib/workflow_evidence.py — Phase D workflow-weighted learning."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture()
def workflow_dir(tmp_path):
    """Create a temp workflow report directory structure."""
    dirs = {
        "claude": tmp_path / "claude",
        "codex": tmp_path / "codex",
        "openclaw": tmp_path / "openclaw",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def _write_summary(directory: Path, provider: str, **overrides):
    """Helper: write a workflow_summary JSON file."""
    now = time.time()
    payload = {
        "kind": "workflow_summary",
        "ts": now,
        "provider": provider,
        "session_key": f"test-session-{provider}",
        "event_count": 20,
        "tool_events": 15,
        "tool_calls": 10,
        "tool_results": 8,
        "tool_successes": 6,
        "tool_failures": 2,
        "top_tools": [{"tool_name": "Edit", "count": 5}, {"tool_name": "Bash", "count": 3}],
        "files_touched": ["main.py", "test.py"],
        "recovery_tools": ["Edit"],
        "outcome_confidence": 0.75,
    }
    payload.update(overrides)
    fp = directory / f"workflow_{int(now * 1000)}_{provider[:4]}.json"
    fp.write_text(json.dumps(payload), encoding="utf-8")
    return fp


# ── Reader tests ──────────────────────────────────────────────────

def test_read_summaries_empty(workflow_dir, monkeypatch):
    import lib.workflow_evidence as we
    monkeypatch.setattr(we, "WORKFLOW_REPORT_DIRS", workflow_dir)
    result = we.get_all_recent_summaries()
    assert result == []


def test_read_summaries_finds_recent(workflow_dir, monkeypatch):
    import lib.workflow_evidence as we
    monkeypatch.setattr(we, "WORKFLOW_REPORT_DIRS", workflow_dir)
    _write_summary(workflow_dir["claude"], "claude")
    _write_summary(workflow_dir["codex"], "codex")
    result = we.get_all_recent_summaries()
    assert len(result) == 2
    providers = {s["provider"] for s in result}
    assert providers == {"claude", "codex"}


def test_read_summaries_respects_max_age(workflow_dir, monkeypatch):
    import lib.workflow_evidence as we
    monkeypatch.setattr(we, "WORKFLOW_REPORT_DIRS", workflow_dir)
    # Write an old summary (2 hours ago)
    _write_summary(workflow_dir["claude"], "claude", ts=time.time() - 7200)
    result = we.get_all_recent_summaries(max_age_s=3600)
    assert len(result) == 0


def test_read_summaries_limits_per_provider(workflow_dir, monkeypatch):
    import lib.workflow_evidence as we
    monkeypatch.setattr(we, "WORKFLOW_REPORT_DIRS", workflow_dir)
    for i in range(5):
        _write_summary(workflow_dir["claude"], "claude", ts=time.time() + i * 0.01)
    result = we.get_all_recent_summaries(limit_per_provider=2)
    assert len(result) == 2


# ── Advisory evidence tests ──────────────────────────────────────

def test_evidence_recovery_item(workflow_dir, monkeypatch):
    import lib.workflow_evidence as we
    monkeypatch.setattr(we, "WORKFLOW_REPORT_DIRS", workflow_dir)
    _write_summary(workflow_dir["claude"], "claude", recovery_tools=["Edit", "Bash"])
    evidence = we.summaries_to_advisory_evidence()
    assert len(evidence) >= 2
    recovery_items = [e for e in evidence if e["signal_type"] == "recovery"]
    assert len(recovery_items) == 2
    tools = {e["tool_name"] for e in recovery_items}
    assert tools == {"Edit", "Bash"}
    assert all(e["source"] == "workflow" for e in recovery_items)


def test_evidence_failure_rate(workflow_dir, monkeypatch):
    import lib.workflow_evidence as we
    monkeypatch.setattr(we, "WORKFLOW_REPORT_DIRS", workflow_dir)
    _write_summary(
        workflow_dir["codex"], "codex",
        tool_failures=5, tool_results=10, tool_successes=5,
        recovery_tools=[],
    )
    evidence = we.summaries_to_advisory_evidence()
    failure_items = [e for e in evidence if e["signal_type"] == "failure_rate"]
    assert len(failure_items) == 1
    assert "50%" in failure_items[0]["text"]


def test_evidence_skips_low_failure(workflow_dir, monkeypatch):
    import lib.workflow_evidence as we
    monkeypatch.setattr(we, "WORKFLOW_REPORT_DIRS", workflow_dir)
    _write_summary(
        workflow_dir["claude"], "claude",
        tool_failures=0, tool_results=10,
        recovery_tools=[],
    )
    evidence = we.summaries_to_advisory_evidence()
    assert len(evidence) == 0


def test_evidence_deduplicates(workflow_dir, monkeypatch):
    import lib.workflow_evidence as we
    monkeypatch.setattr(we, "WORKFLOW_REPORT_DIRS", workflow_dir)
    # Two summaries from same provider with same recovery tool
    _write_summary(workflow_dir["claude"], "claude", recovery_tools=["Edit"], ts=time.time())
    _write_summary(workflow_dir["claude"], "claude", recovery_tools=["Edit"], ts=time.time() + 1)
    evidence = we.summaries_to_advisory_evidence()
    recovery_items = [e for e in evidence if e["signal_type"] == "recovery"]
    # Same provider+tool = same key, so deduplicated
    assert len(recovery_items) == 1


# ── Recovery metrics tests ───────────────────────────────────────

def test_recovery_metrics_basic(workflow_dir, monkeypatch):
    import lib.workflow_evidence as we
    monkeypatch.setattr(we, "WORKFLOW_REPORT_DIRS", workflow_dir)
    _write_summary(workflow_dir["claude"], "claude",
                   tool_failures=3, tool_successes=7, tool_results=10,
                   recovery_tools=["Edit"])
    _write_summary(workflow_dir["codex"], "codex",
                   tool_failures=0, tool_successes=5, tool_results=5,
                   recovery_tools=[])
    metrics = we.compute_recovery_metrics()
    assert metrics["total_sessions"] == 2
    assert metrics["sessions_with_failures"] == 1
    assert metrics["sessions_with_recovery"] == 1
    assert metrics["recovery_rate"] == 1.0  # 1/1 failures had recovery
    assert "claude" in metrics["per_provider"]
    assert metrics["per_provider"]["claude"]["recoveries"] == 1
    assert "Edit" in metrics["per_tool"]
    assert metrics["per_tool"]["Edit"]["recoveries_total"] == 1


def test_recovery_metrics_empty():
    import lib.workflow_evidence as we
    metrics = we.compute_recovery_metrics(summaries=[])
    assert metrics["total_sessions"] == 0
    assert metrics["recovery_rate"] == 0.0


# ── importance_score workflow context boost tests ─────────────────

def test_importance_score_failure_recovery():
    from lib.memory_capture import importance_score
    text = "The Edit tool failed with a permission error, but after retrying with correct path it recovered successfully."
    score, breakdown = importance_score(text)
    assert "workflow_context" in breakdown
    assert breakdown["workflow_context"] >= 0.25
    assert score >= 0.25


def test_importance_score_tool_failure():
    from lib.memory_capture import importance_score
    text = "There was a tool failure when running the Bash command."
    score, breakdown = importance_score(text)
    assert "workflow_context" in breakdown
    assert breakdown["workflow_context"] >= 0.20


def test_importance_score_no_workflow_for_normal():
    from lib.memory_capture import importance_score
    text = "The weather is nice today and the code looks clean."
    score, breakdown = importance_score(text)
    assert "workflow_context" not in breakdown


# ── Observatory page tests ───────────────────────────────────────

def test_recovery_observatory_page(workflow_dir, monkeypatch):
    import lib.workflow_evidence as we
    monkeypatch.setattr(we, "WORKFLOW_REPORT_DIRS", workflow_dir)
    _write_summary(workflow_dir["claude"], "claude",
                   tool_failures=2, tool_successes=8, tool_results=10,
                   recovery_tools=["Edit"])
    from lib.observatory.recovery_metrics import generate_recovery_metrics
    content = generate_recovery_metrics()
    assert "Recovery Effectiveness" in content
    assert "claude" in content
    assert "Edit" in content


def test_recovery_observatory_empty_page():
    from lib.observatory.recovery_metrics import generate_recovery_metrics
    # With no workflow dirs existing, should produce empty page gracefully
    content = generate_recovery_metrics()
    assert "Recovery Effectiveness" in content


def test_load_tuneables_uses_config_authority(monkeypatch):
    import lib.workflow_evidence as we

    payload = {
        "max_summaries_per_provider": 7,
        "max_age_s": 900,
        "min_tool_failures_for_advisory": 2,
        "recovery_boost": 0.33,
        "source_quality": 0.77,
    }

    monkeypatch.setattr(we, "resolve_section", lambda *a, **k: SimpleNamespace(data=payload))
    we.load_tuneables()

    assert we.MAX_SUMMARIES_PER_PROVIDER == 7
    assert we.MAX_AGE_S == 900
    assert we.MIN_TOOL_FAILURES_FOR_ADVISORY == 2
    assert we.RECOVERY_BOOST == pytest.approx(0.33)
    assert we.WORKFLOW_SOURCE_QUALITY == pytest.approx(0.77)
