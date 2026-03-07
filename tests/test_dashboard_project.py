"""Tests for lib.dashboard_project."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.dashboard_project as dp


# ---------------------------------------------------------------------------
# get_active_project
# ---------------------------------------------------------------------------

def test_get_active_project_returns_value(monkeypatch):
    monkeypatch.setattr(dp, "infer_project_key", lambda: "my-project")
    assert dp.get_active_project() == "my-project"


def test_get_active_project_returns_none(monkeypatch):
    monkeypatch.setattr(dp, "infer_project_key", lambda: None)
    assert dp.get_active_project() is None


def test_get_active_project_delegates_to_infer(monkeypatch):
    called = []
    monkeypatch.setattr(dp, "infer_project_key", lambda: called.append(1) or "proj")
    dp.get_active_project()
    assert called == [1]


# ---------------------------------------------------------------------------
# get_project_memory_preview — no project_key
# ---------------------------------------------------------------------------

def test_preview_no_project_key_returns_empty():
    assert dp.get_project_memory_preview(None) == []


def test_preview_empty_string_project_key_returns_empty():
    # empty string is falsy → returns []
    assert dp.get_project_memory_preview("") == []


# ---------------------------------------------------------------------------
# get_project_memory_preview — file missing
# ---------------------------------------------------------------------------

def test_preview_file_not_found_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "_PROJECTS_DIR", tmp_path)
    assert dp.get_project_memory_preview("my-project") == []


# ---------------------------------------------------------------------------
# get_project_memory_preview — valid JSONL
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )


def test_preview_returns_all_within_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "_PROJECTS_DIR", tmp_path)
    rows = [{"text": f"row{i}"} for i in range(3)]
    _write_jsonl(tmp_path / "proj.jsonl", rows)
    result = dp.get_project_memory_preview("proj", limit=5)
    assert len(result) == 3


def test_preview_respects_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "_PROJECTS_DIR", tmp_path)
    rows = [{"text": f"row{i}"} for i in range(10)]
    _write_jsonl(tmp_path / "proj.jsonl", rows)
    result = dp.get_project_memory_preview("proj", limit=3)
    assert len(result) == 3


def test_preview_returns_most_recent_first(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "_PROJECTS_DIR", tmp_path)
    rows = [{"text": "first"}, {"text": "second"}, {"text": "third"}]
    _write_jsonl(tmp_path / "proj.jsonl", rows)
    result = dp.get_project_memory_preview("proj", limit=3)
    # reversed(lines) → last line first
    assert result[0]["text"] == "third"
    assert result[1]["text"] == "second"
    assert result[2]["text"] == "first"


def test_preview_default_limit_is_5(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "_PROJECTS_DIR", tmp_path)
    rows = [{"text": f"r{i}"} for i in range(10)]
    _write_jsonl(tmp_path / "proj.jsonl", rows)
    result = dp.get_project_memory_preview("proj")
    assert len(result) == 5


def test_preview_skips_bad_json_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "_PROJECTS_DIR", tmp_path)
    path = tmp_path / "proj.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"text": "good"}\n{bad json}\n{"text": "also good"}\n', encoding="utf-8")
    result = dp.get_project_memory_preview("proj", limit=10)
    assert all("text" in r for r in result)
    assert len(result) == 2


def test_preview_empty_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "_PROJECTS_DIR", tmp_path)
    path = tmp_path / "proj.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    result = dp.get_project_memory_preview("proj", limit=5)
    assert result == []


def test_preview_unreadable_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "_PROJECTS_DIR", tmp_path)
    path = tmp_path / "proj.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe")  # invalid UTF-8 for read_text
    # Should return [] rather than raise
    result = dp.get_project_memory_preview("proj", limit=5)
    assert isinstance(result, list)


def test_preview_project_key_used_as_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "_PROJECTS_DIR", tmp_path)
    rows = [{"text": "x"}]
    _write_jsonl(tmp_path / "special-key.jsonl", rows)
    result = dp.get_project_memory_preview("special-key", limit=5)
    assert len(result) == 1
