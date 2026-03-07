"""Tests for lib.run_log."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import lib.run_log as rl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def _make_episode(**kw):
    defaults = dict(
        episode_id="ep-1",
        goal="do something",
        phase=SimpleNamespace(value="active"),
        outcome=SimpleNamespace(value="success"),
        final_evaluation="ok",
        start_ts=1000.0,
        end_ts=2000.0,
        step_count=2,
        escape_protocol_triggered=False,
        error_counts={},
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _make_step(**kw):
    defaults = dict(
        step_id="s-1",
        trace_id="t-1",
        intent="read file",
        decision="use Read tool",
        evaluation=SimpleNamespace(value="good"),
        validated=True,
        created_at=1500.0,
        result="file contents",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# _read_jsonl
# ---------------------------------------------------------------------------

def test_read_jsonl_no_file(tmp_path):
    assert rl._read_jsonl(tmp_path / "missing.jsonl") == []


def test_read_jsonl_empty_file(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    assert rl._read_jsonl(p) == []


def test_read_jsonl_valid_rows(tmp_path):
    p = tmp_path / "data.jsonl"
    rows = [{"a": 1}, {"b": 2}]
    _write_jsonl(p, rows)
    result = rl._read_jsonl(p)
    assert result == rows


def test_read_jsonl_skips_bad_lines(tmp_path):
    p = tmp_path / "data.jsonl"
    p.write_text('{"ok": 1}\n{bad}\n{"ok": 2}\n', encoding="utf-8")
    result = rl._read_jsonl(p)
    assert len(result) == 2
    assert all("ok" in r for r in result)


def test_read_jsonl_limit(tmp_path):
    p = tmp_path / "data.jsonl"
    rows = [{"i": i} for i in range(20)]
    _write_jsonl(p, rows)
    result = rl._read_jsonl(p, limit=5)
    assert len(result) == 5
    # last 5 rows (lines[-limit:])
    assert result[0]["i"] == 15


def test_read_jsonl_always_returns_list(tmp_path):
    # _read_jsonl is resilient: always returns a list regardless of file state
    # (the source wraps read_text in a try/except returning [])
    result = rl._read_jsonl(tmp_path / "nonexistent_file.jsonl")
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# _count_evidence_for_steps
# ---------------------------------------------------------------------------

def test_count_evidence_empty_step_ids(monkeypatch):
    monkeypatch.setattr(rl, "get_evidence_store", MagicMock())
    assert rl._count_evidence_for_steps([]) == 0


def test_count_evidence_sqlite_error_returns_zero(monkeypatch):
    mock_store = MagicMock()
    mock_store.db_path = ":memory:"
    monkeypatch.setattr(rl, "get_evidence_store", lambda: mock_store)
    # Corrupt db_path to trigger exception
    mock_store.db_path = "/nonexistent/path/db.sqlite"
    result = rl._count_evidence_for_steps(["step-1"])
    assert result == 0


def test_count_evidence_counts_from_db(tmp_path, monkeypatch):
    db_path = tmp_path / "ev.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE evidence (step_id TEXT)")
    conn.execute("INSERT INTO evidence VALUES ('s1')")
    conn.execute("INSERT INTO evidence VALUES ('s1')")
    conn.execute("INSERT INTO evidence VALUES ('s2')")
    conn.commit()
    conn.close()

    mock_store = MagicMock()
    mock_store.db_path = str(db_path)
    monkeypatch.setattr(rl, "get_evidence_store", lambda: mock_store)

    result = rl._count_evidence_for_steps(["s1", "s2"])
    assert result == 3


# ---------------------------------------------------------------------------
# get_recent_runs
# ---------------------------------------------------------------------------

def _make_mock_store(episodes, steps_by_id=None):
    store = MagicMock()
    store.get_recent_episodes = MagicMock(return_value=episodes)
    steps_by_id = steps_by_id or {}
    store.get_episode_steps = MagicMock(
        side_effect=lambda eid: steps_by_id.get(eid, [])
    )
    return store


def test_get_recent_runs_no_episodes(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "get_store", lambda: _make_mock_store([]))
    monkeypatch.setattr(rl, "get_evidence_store", MagicMock())
    monkeypatch.setattr(rl, "OUTCOMES_FILE", tmp_path / "outcomes.jsonl")
    result = rl.get_recent_runs()
    assert result == []


def _bad_ev_store():
    """Return a fake ev_store whose db_path doesn't exist — sqlite3.connect raises OperationalError,
    which is caught inside _count_evidence_for_steps and returns 0."""
    m = MagicMock()
    m.db_path = "/nonexistent/__test_ev__.db"
    return m


def test_get_recent_runs_one_episode(tmp_path, monkeypatch):
    ep = _make_episode(episode_id="ep-1")
    step = _make_step(step_id="s1", trace_id="t1")
    store = _make_mock_store([ep], {"ep-1": [step]})

    monkeypatch.setattr(rl, "get_store", lambda: store)
    monkeypatch.setattr(rl, "get_evidence_store", _bad_ev_store)
    monkeypatch.setattr(rl, "OUTCOMES_FILE", tmp_path / "no.jsonl")

    runs = rl.get_recent_runs(limit=5)
    assert len(runs) == 1
    r = runs[0]
    assert r["episode_id"] == "ep-1"
    assert r["step_count"] == 1
    assert r["trace_count"] == 1


def test_get_recent_runs_deduplicates_trace_ids(tmp_path, monkeypatch):
    ep = _make_episode(episode_id="ep-1")
    steps = [
        _make_step(step_id="s1", trace_id="t1"),
        _make_step(step_id="s2", trace_id="t1"),  # duplicate trace
        _make_step(step_id="s3", trace_id="t2"),
    ]
    store = _make_mock_store([ep], {"ep-1": steps})
    monkeypatch.setattr(rl, "get_store", lambda: store)
    monkeypatch.setattr(rl, "get_evidence_store", _bad_ev_store)
    monkeypatch.setattr(rl, "OUTCOMES_FILE", tmp_path / "no.jsonl")

    runs = rl.get_recent_runs()
    assert runs[0]["trace_count"] == 2  # t1, t2 deduplicated


def test_get_recent_runs_outcomes_count(tmp_path, monkeypatch):
    ep = _make_episode(episode_id="ep-1")
    step = _make_step(step_id="s1", trace_id="t1")
    store = _make_mock_store([ep], {"ep-1": [step]})

    outcomes = tmp_path / "outcomes.jsonl"
    _write_jsonl(outcomes, [{"trace_id": "t1"}, {"trace_id": "t1"}, {"trace_id": "other"}])

    monkeypatch.setattr(rl, "get_store", lambda: store)
    monkeypatch.setattr(rl, "get_evidence_store", _bad_ev_store)
    monkeypatch.setattr(rl, "OUTCOMES_FILE", outcomes)

    runs = rl.get_recent_runs()
    assert runs[0]["outcomes_count"] == 2


def test_get_recent_runs_no_steps_last_step_ts_none(tmp_path, monkeypatch):
    ep = _make_episode(episode_id="ep-1")
    store = _make_mock_store([ep], {"ep-1": []})
    monkeypatch.setattr(rl, "get_store", lambda: store)
    monkeypatch.setattr(rl, "get_evidence_store", MagicMock(side_effect=Exception("no db")))
    monkeypatch.setattr(rl, "OUTCOMES_FILE", tmp_path / "no.jsonl")

    runs = rl.get_recent_runs()
    assert runs[0]["last_step_ts"] is None


# ---------------------------------------------------------------------------
# get_run_detail
# ---------------------------------------------------------------------------

def test_get_run_detail_not_found(tmp_path, monkeypatch):
    store = MagicMock()
    store.get_episode = MagicMock(return_value=None)
    monkeypatch.setattr(rl, "get_store", lambda: store)

    result = rl.get_run_detail("ep-missing")
    assert result["found"] is False
    assert result["episode_id"] == "ep-missing"


def test_get_run_detail_found(tmp_path, monkeypatch):
    ep = _make_episode(episode_id="ep-1")
    step = _make_step(step_id="s1", trace_id="t1")

    store = MagicMock()
    store.get_episode = MagicMock(return_value=ep)
    store.get_episode_steps = MagicMock(return_value=[step])

    ev_store = MagicMock()
    ev_store.get_for_step = MagicMock(return_value=[])

    monkeypatch.setattr(rl, "get_store", lambda: store)
    monkeypatch.setattr(rl, "get_evidence_store", lambda: ev_store)
    monkeypatch.setattr(rl, "OUTCOMES_FILE", tmp_path / "no.jsonl")

    result = rl.get_run_detail("ep-1")
    assert result["found"] is True
    assert result["episode"]["episode_id"] == "ep-1"
    assert len(result["steps"]) == 1
    assert result["steps"][0]["step_id"] == "s1"


def test_get_run_detail_outcomes_matched(tmp_path, monkeypatch):
    ep = _make_episode(episode_id="ep-1")
    step = _make_step(step_id="s1", trace_id="t1")

    store = MagicMock()
    store.get_episode = MagicMock(return_value=ep)
    store.get_episode_steps = MagicMock(return_value=[step])

    ev_store = MagicMock()
    ev_store.get_for_step = MagicMock(return_value=[])

    outcomes = tmp_path / "outcomes.jsonl"
    _write_jsonl(outcomes, [{"trace_id": "t1", "result": "ok"}, {"trace_id": "other"}])

    monkeypatch.setattr(rl, "get_store", lambda: store)
    monkeypatch.setattr(rl, "get_evidence_store", lambda: ev_store)
    monkeypatch.setattr(rl, "OUTCOMES_FILE", outcomes)

    result = rl.get_run_detail("ep-1")
    assert len(result["outcomes"]) == 1
    assert result["outcomes"][0]["trace_id"] == "t1"


# ---------------------------------------------------------------------------
# get_run_kpis
# ---------------------------------------------------------------------------

def test_get_run_kpis_no_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "get_store", lambda: _make_mock_store([]))
    monkeypatch.setattr(rl, "get_evidence_store", MagicMock())
    monkeypatch.setattr(rl, "OUTCOMES_FILE", tmp_path / "no.jsonl")

    kpis = rl.get_run_kpis()
    assert kpis == {"avg_steps": 0, "escape_rate": 0.0, "evidence_ratio": 0.0, "runs": 0}


def test_get_run_kpis_with_runs(tmp_path, monkeypatch):
    eps = [
        _make_episode(episode_id="ep-1", escape_protocol_triggered=True),
        _make_episode(episode_id="ep-2", escape_protocol_triggered=False),
    ]
    steps_map = {
        "ep-1": [_make_step(step_id="s1"), _make_step(step_id="s2")],
        "ep-2": [_make_step(step_id="s3")],
    }
    store = _make_mock_store(eps, steps_map)
    monkeypatch.setattr(rl, "get_store", lambda: store)
    monkeypatch.setattr(rl, "get_evidence_store", _bad_ev_store)
    monkeypatch.setattr(rl, "OUTCOMES_FILE", tmp_path / "no.jsonl")

    kpis = rl.get_run_kpis(limit=10)
    assert kpis["runs"] == 2
    assert kpis["avg_steps"] == 1.5  # (2+1)/2
    assert kpis["escape_rate"] == 0.5  # 1/2
