"""Tests for lib.memory_migrate."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

import lib.memory_migrate as mm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# _load_jsonl — thin wrapper around _read_jsonl
# ---------------------------------------------------------------------------

def test_load_jsonl_delegates_to_read_jsonl(monkeypatch):
    fake_path = MagicMock()
    captured = []
    monkeypatch.setattr(mm, "_read_jsonl", lambda p, limit=20000: captured.append((p, limit)) or [])
    mm._load_jsonl(fake_path, limit=500)
    assert captured == [(fake_path, 500)]


def test_load_jsonl_default_limit(monkeypatch):
    captured = []
    monkeypatch.setattr(mm, "_read_jsonl", lambda p, limit=20000: captured.append(limit) or [])
    mm._load_jsonl(MagicMock())
    assert captured[0] == 20000


# ---------------------------------------------------------------------------
# migrate — no files present
# ---------------------------------------------------------------------------

def test_migrate_no_global_no_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "GLOBAL_FILE", tmp_path / "nonexistent_global.jsonl")
    monkeypatch.setattr(mm, "PROJECTS_DIR", tmp_path / "nonexistent_projects")
    mock_upsert = MagicMock()
    monkeypatch.setattr(mm, "upsert_entry", mock_upsert)
    result = mm.migrate()
    assert result == {"migrated": 0, "skipped": 0, "files": 0}
    mock_upsert.assert_not_called()


# ---------------------------------------------------------------------------
# migrate — GLOBAL_FILE only
# ---------------------------------------------------------------------------

def test_migrate_global_file_rows(tmp_path, monkeypatch):
    global_file = tmp_path / "global.jsonl"
    rows = [
        {"entry_id": "e1", "text": "hello", "scope": "global", "source": "spark"},
        {"entry_id": "e2", "text": "world", "scope": "global"},
    ]
    _write_jsonl(global_file, rows)
    monkeypatch.setattr(mm, "GLOBAL_FILE", global_file)
    monkeypatch.setattr(mm, "PROJECTS_DIR", tmp_path / "no-projects")

    calls_made = []
    def fake_upsert(**kwargs):
        calls_made.append(kwargs)
    monkeypatch.setattr(mm, "upsert_entry", fake_upsert)
    monkeypatch.setattr(mm, "_read_jsonl", lambda p, limit=20000: rows if p == global_file else [])

    result = mm.migrate()
    assert result["migrated"] == 2
    assert result["skipped"] == 0
    assert result["files"] == 1


def test_migrate_maps_fields_correctly(tmp_path, monkeypatch):
    global_file = tmp_path / "global.jsonl"
    row = {
        "entry_id": "eid-1",
        "text": "my content",
        "scope": "project",
        "project_key": "proj-x",
        "category": "decision",
        "created_at": 1234567.0,
        "source": "agent",
        "meta": {"key": "val"},
    }
    _write_jsonl(global_file, [row])
    monkeypatch.setattr(mm, "GLOBAL_FILE", global_file)
    monkeypatch.setattr(mm, "PROJECTS_DIR", tmp_path / "no-projects")

    calls_made = []
    monkeypatch.setattr(mm, "upsert_entry", lambda **kwargs: calls_made.append(kwargs))
    monkeypatch.setattr(mm, "_read_jsonl", lambda p, limit=20000: [row])

    mm.migrate()
    assert len(calls_made) == 1
    kw = calls_made[0]
    assert kw["memory_id"] == "eid-1"
    assert kw["content"] == "my content"
    assert kw["scope"] == "project"
    assert kw["project_key"] == "proj-x"
    assert kw["category"] == "decision"
    assert kw["created_at"] == 1234567.0
    assert kw["source"] == "agent"
    assert kw["meta"] == {"key": "val"}


def test_migrate_missing_fields_use_defaults(tmp_path, monkeypatch):
    global_file = tmp_path / "global.jsonl"
    row = {}
    _write_jsonl(global_file, [row])
    monkeypatch.setattr(mm, "GLOBAL_FILE", global_file)
    monkeypatch.setattr(mm, "PROJECTS_DIR", tmp_path / "no-projects")

    calls_made = []
    monkeypatch.setattr(mm, "upsert_entry", lambda **kwargs: calls_made.append(kwargs))
    monkeypatch.setattr(mm, "_read_jsonl", lambda p, limit=20000: [row])

    mm.migrate()
    kw = calls_made[0]
    assert kw["memory_id"] == ""
    assert kw["content"] == ""
    assert kw["scope"] == "global"
    assert kw["category"] == "memory"
    assert kw["created_at"] == 0.0
    assert kw["source"] == "spark"
    assert kw["meta"] == {}


# ---------------------------------------------------------------------------
# migrate — PROJECTS_DIR with files
# ---------------------------------------------------------------------------

def test_migrate_project_files(tmp_path, monkeypatch):
    global_file = tmp_path / "nonexistent_global.jsonl"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    proj_rows = [{"entry_id": "p1", "text": "proj content"}]
    _write_jsonl(projects_dir / "proj-a.jsonl", proj_rows)

    monkeypatch.setattr(mm, "GLOBAL_FILE", global_file)
    monkeypatch.setattr(mm, "PROJECTS_DIR", projects_dir)

    calls_made = []
    monkeypatch.setattr(mm, "upsert_entry", lambda **kwargs: calls_made.append(kwargs))
    monkeypatch.setattr(mm, "_read_jsonl", lambda p, limit=20000: proj_rows)

    result = mm.migrate()
    assert result["migrated"] == 1
    assert result["files"] == 1


def test_migrate_multiple_project_files(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    rows_a = [{"entry_id": "a1", "text": "a"}]
    rows_b = [{"entry_id": "b1", "text": "b"}, {"entry_id": "b2", "text": "c"}]
    _write_jsonl(projects_dir / "proj-a.jsonl", rows_a)
    _write_jsonl(projects_dir / "proj-b.jsonl", rows_b)

    monkeypatch.setattr(mm, "GLOBAL_FILE", tmp_path / "no-global.jsonl")
    monkeypatch.setattr(mm, "PROJECTS_DIR", projects_dir)

    def fake_read(p, limit=20000):
        if "proj-a" in str(p):
            return rows_a
        return rows_b

    calls_made = []
    monkeypatch.setattr(mm, "upsert_entry", lambda **kwargs: calls_made.append(kwargs))
    monkeypatch.setattr(mm, "_read_jsonl", fake_read)

    result = mm.migrate()
    assert result["migrated"] == 3
    assert result["files"] == 2


# ---------------------------------------------------------------------------
# migrate — upsert_entry raises → skipped count
# ---------------------------------------------------------------------------

def test_migrate_upsert_exception_counted_as_skipped(tmp_path, monkeypatch):
    global_file = tmp_path / "global.jsonl"
    rows = [{"entry_id": "e1", "text": "x"}, {"entry_id": "e2", "text": "y"}]
    _write_jsonl(global_file, rows)
    monkeypatch.setattr(mm, "GLOBAL_FILE", global_file)
    monkeypatch.setattr(mm, "PROJECTS_DIR", tmp_path / "no-projects")
    monkeypatch.setattr(mm, "_read_jsonl", lambda p, limit=20000: rows)
    monkeypatch.setattr(mm, "upsert_entry", MagicMock(side_effect=RuntimeError("db error")))

    result = mm.migrate()
    assert result["migrated"] == 0
    assert result["skipped"] == 2


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_returns_zero(monkeypatch):
    monkeypatch.setattr(mm, "migrate", lambda **kw: {"migrated": 5, "skipped": 0, "files": 1})
    assert mm.main() == 0
