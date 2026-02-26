"""Tests for lib/openclaw_paths.py

Covers:
- read_openclaw_config(): valid JSON, BOM-safe, missing file, bad JSON, non-dict JSON
- _append_unique(): deduplication, empty strings ignored, case-insensitive dedup,
  expanduser, whitespace-stripped paths
- discover_openclaw_workspaces(): env var override, config agent defaults,
  config agent list, glob of workspace* dirs, include_nonexistent flag
- primary_openclaw_workspace(): returns first discovered or default
- discover_openclaw_advisory_files(): finds SPARK_ADVISORY.md in workspaces
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.openclaw_paths as ocp
from lib.openclaw_paths import (
    _append_unique,
    discover_openclaw_advisory_files,
    discover_openclaw_workspaces,
    primary_openclaw_workspace,
    read_openclaw_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_openclaw(monkeypatch, tmp_path):
    """Redirect module-level path constants to tmp_path."""
    openclaw_dir = tmp_path / ".openclaw"
    openclaw_dir.mkdir()
    config_path = openclaw_dir / "openclaw.json"
    monkeypatch.setattr(ocp, "OPENCLAW_DIR", openclaw_dir)
    monkeypatch.setattr(ocp, "OPENCLAW_CONFIG", config_path)
    monkeypatch.setattr(ocp, "DEFAULT_WORKSPACE", openclaw_dir / "workspace")
    return openclaw_dir, config_path


# ---------------------------------------------------------------------------
# read_openclaw_config
# ---------------------------------------------------------------------------

def test_read_openclaw_config_valid_json(tmp_path):
    cfg = tmp_path / "openclaw.json"
    cfg.write_text(json.dumps({"key": "value"}), encoding="utf-8")
    assert read_openclaw_config(cfg) == {"key": "value"}


def test_read_openclaw_config_bom_safe(tmp_path):
    cfg = tmp_path / "openclaw.json"
    # Write with UTF-8 BOM
    cfg.write_bytes(b"\xef\xbb\xbf" + json.dumps({"bom": True}).encode("utf-8"))
    assert read_openclaw_config(cfg) == {"bom": True}


def test_read_openclaw_config_missing_file_returns_empty(tmp_path):
    result = read_openclaw_config(tmp_path / "nonexistent.json")
    assert result == {}


def test_read_openclaw_config_bad_json_returns_empty(tmp_path):
    cfg = tmp_path / "openclaw.json"
    cfg.write_text("this is not json", encoding="utf-8")
    assert read_openclaw_config(cfg) == {}


def test_read_openclaw_config_non_dict_json_returns_empty(tmp_path):
    cfg = tmp_path / "openclaw.json"
    cfg.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert read_openclaw_config(cfg) == {}


def test_read_openclaw_config_empty_dict(tmp_path):
    cfg = tmp_path / "openclaw.json"
    cfg.write_text(json.dumps({}), encoding="utf-8")
    assert read_openclaw_config(cfg) == {}


# ---------------------------------------------------------------------------
# _append_unique
# ---------------------------------------------------------------------------

def test_append_unique_adds_new_path(tmp_path):
    paths = []
    seen = set()
    _append_unique(paths, seen, str(tmp_path))
    assert len(paths) == 1
    assert paths[0] == tmp_path


def test_append_unique_deduplicates():
    paths = []
    seen = set()
    _append_unique(paths, seen, "/some/path")
    _append_unique(paths, seen, "/some/path")
    assert len(paths) == 1


def test_append_unique_case_insensitive_dedup():
    paths = []
    seen = set()
    _append_unique(paths, seen, "/Some/Path")
    _append_unique(paths, seen, "/some/path")
    assert len(paths) == 1


def test_append_unique_ignores_empty_string():
    paths = []
    seen = set()
    _append_unique(paths, seen, "")
    assert paths == []


def test_append_unique_ignores_none():
    paths = []
    seen = set()
    _append_unique(paths, seen, None)
    assert paths == []


def test_append_unique_strips_whitespace():
    paths = []
    seen = set()
    _append_unique(paths, seen, "  /some/path  ")
    assert len(paths) == 1
    assert str(paths[0]) == "/some/path"


def test_append_unique_multiple_different_paths(tmp_path):
    p1 = tmp_path / "a"
    p2 = tmp_path / "b"
    paths = []
    seen = set()
    _append_unique(paths, seen, str(p1))
    _append_unique(paths, seen, str(p2))
    assert len(paths) == 2


# ---------------------------------------------------------------------------
# discover_openclaw_workspaces — env var override
# ---------------------------------------------------------------------------

def test_discover_workspaces_env_var_existing_dir(tmp_path, monkeypatch):
    ws = tmp_path / "myworkspace"
    ws.mkdir()
    monkeypatch.setenv("SPARK_OPENCLAW_WORKSPACE", str(ws))
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
    result = discover_openclaw_workspaces()
    assert result == [ws]


def test_discover_workspaces_env_var_nonexistent_excluded_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_OPENCLAW_WORKSPACE", str(tmp_path / "nonexistent"))
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
    result = discover_openclaw_workspaces()
    assert result == []


def test_discover_workspaces_env_var_nonexistent_included_with_flag(tmp_path, monkeypatch):
    ws = tmp_path / "nonexistent"
    monkeypatch.setenv("SPARK_OPENCLAW_WORKSPACE", str(ws))
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
    result = discover_openclaw_workspaces(include_nonexistent=True)
    assert ws in result


def test_discover_workspaces_fallback_env_var(tmp_path, monkeypatch):
    ws = tmp_path / "fallback_ws"
    ws.mkdir()
    monkeypatch.delenv("SPARK_OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(ws))
    result = discover_openclaw_workspaces()
    assert result == [ws]


# ---------------------------------------------------------------------------
# discover_openclaw_workspaces — config-based discovery
# ---------------------------------------------------------------------------

def test_discover_workspaces_from_agent_defaults(tmp_path, monkeypatch):
    # read_openclaw_config's default arg is bound at import time, so patch the
    # function itself to return the config we want.
    openclaw_dir, _ = _patch_openclaw(monkeypatch, tmp_path)
    monkeypatch.delenv("SPARK_OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)

    ws = tmp_path / "default_ws"
    ws.mkdir()
    cfg = {"agents": {"defaults": {"workspace": str(ws)}}}
    monkeypatch.setattr(ocp, "read_openclaw_config", lambda *a, **kw: cfg)

    result = discover_openclaw_workspaces()
    assert ws in result


def test_discover_workspaces_from_agent_list(tmp_path, monkeypatch):
    openclaw_dir, _ = _patch_openclaw(monkeypatch, tmp_path)
    monkeypatch.delenv("SPARK_OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)

    ws = tmp_path / "agent_ws"
    ws.mkdir()
    cfg = {"agents": {"list": [{"workspace": str(ws)}]}}
    monkeypatch.setattr(ocp, "read_openclaw_config", lambda *a, **kw: cfg)

    result = discover_openclaw_workspaces()
    assert ws in result


def test_discover_workspaces_globs_workspace_dirs(tmp_path, monkeypatch):
    openclaw_dir, config_path = _patch_openclaw(monkeypatch, tmp_path)
    monkeypatch.delenv("SPARK_OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
    config_path.write_text("{}", encoding="utf-8")

    # Create workspace* dirs that should be auto-discovered
    ws1 = openclaw_dir / "workspace-alpha"
    ws2 = openclaw_dir / "workspace-beta"
    ws1.mkdir()
    ws2.mkdir()

    result = discover_openclaw_workspaces()
    assert ws1 in result
    assert ws2 in result


def test_discover_workspaces_no_duplicates(tmp_path, monkeypatch):
    openclaw_dir, config_path = _patch_openclaw(monkeypatch, tmp_path)
    monkeypatch.delenv("SPARK_OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)

    ws = openclaw_dir / "workspace"
    ws.mkdir()
    # Same path in both agent defaults and workspace glob
    config_path.write_text(json.dumps({
        "agents": {"defaults": {"workspace": str(ws)}}
    }), encoding="utf-8")

    result = discover_openclaw_workspaces()
    paths_strs = [str(p) for p in result]
    assert len(paths_strs) == len(set(paths_strs))


# ---------------------------------------------------------------------------
# primary_openclaw_workspace
# ---------------------------------------------------------------------------

def test_primary_openclaw_workspace_returns_first(tmp_path, monkeypatch):
    openclaw_dir, config_path = _patch_openclaw(monkeypatch, tmp_path)
    monkeypatch.delenv("SPARK_OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)

    ws = tmp_path / "primary_ws"
    ws.mkdir()
    monkeypatch.setenv("SPARK_OPENCLAW_WORKSPACE", str(ws))

    result = primary_openclaw_workspace()
    assert result == ws


def test_primary_openclaw_workspace_falls_back_to_default(tmp_path, monkeypatch):
    openclaw_dir, config_path = _patch_openclaw(monkeypatch, tmp_path)
    monkeypatch.delenv("SPARK_OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
    config_path.write_text("{}", encoding="utf-8")

    default = openclaw_dir / "workspace"
    # Don't create it — should still return as fallback via include_nonexistent
    result = primary_openclaw_workspace()
    assert result == default


# ---------------------------------------------------------------------------
# discover_openclaw_advisory_files
# ---------------------------------------------------------------------------

def test_discover_advisory_files_finds_spark_advisory_md(tmp_path, monkeypatch):
    openclaw_dir, config_path = _patch_openclaw(monkeypatch, tmp_path)
    monkeypatch.delenv("SPARK_OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)

    ws = openclaw_dir / "workspace"
    ws.mkdir()
    advisory = ws / "SPARK_ADVISORY.md"
    advisory.write_text("# Spark Advisory", encoding="utf-8")

    config_path.write_text("{}", encoding="utf-8")

    result = discover_openclaw_advisory_files()
    assert advisory in result


def test_discover_advisory_files_empty_when_no_workspaces(tmp_path, monkeypatch):
    openclaw_dir, config_path = _patch_openclaw(monkeypatch, tmp_path)
    monkeypatch.delenv("SPARK_OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
    config_path.write_text("{}", encoding="utf-8")

    result = discover_openclaw_advisory_files()
    assert result == []


def test_discover_advisory_files_skips_workspace_without_advisory(tmp_path, monkeypatch):
    openclaw_dir, config_path = _patch_openclaw(monkeypatch, tmp_path)
    monkeypatch.delenv("SPARK_OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)

    ws = openclaw_dir / "workspace"
    ws.mkdir()
    # No SPARK_ADVISORY.md here
    config_path.write_text("{}", encoding="utf-8")

    result = discover_openclaw_advisory_files()
    assert result == []
