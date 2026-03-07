"""Tests for lib/self_report.py

Covers:
- _report_dir(): explicit directory wins, falls back to SPARK_REPORT_DIR env,
  falls back to DEFAULT_REPORT_DIR
- report(): raises ValueError for invalid kind, creates directory, writes JSON
  file, file name contains kind, returned path exists, payload fields stored,
  ts field present, kind field present, arbitrary kwargs stored
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import lib.self_report as sr
from lib.self_report import _report_dir, report, VALID_KINDS


# ---------------------------------------------------------------------------
# _report_dir
# ---------------------------------------------------------------------------

def test_report_dir_explicit_path(tmp_path):
    result = _report_dir(tmp_path)
    assert result == tmp_path


def test_report_dir_env_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_REPORT_DIR", str(tmp_path))
    result = _report_dir(None)
    assert result == tmp_path


def test_report_dir_default_when_no_env(monkeypatch):
    monkeypatch.delenv("SPARK_REPORT_DIR", raising=False)
    result = _report_dir(None)
    assert result == sr.DEFAULT_REPORT_DIR


def test_report_dir_explicit_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_REPORT_DIR", str(tmp_path / "env_dir"))
    explicit = tmp_path / "explicit"
    result = _report_dir(explicit)
    assert result == explicit


# ---------------------------------------------------------------------------
# report — validation
# ---------------------------------------------------------------------------

def test_report_raises_on_invalid_kind(tmp_path):
    with pytest.raises(ValueError, match="Invalid report kind"):
        report("nonsense", directory=tmp_path)


def test_report_valid_kinds_do_not_raise(tmp_path):
    for kind in VALID_KINDS:
        path = report(kind, directory=tmp_path, note="test")
        assert path.exists()


# ---------------------------------------------------------------------------
# report — file creation
# ---------------------------------------------------------------------------

def test_report_creates_directory(tmp_path):
    d = tmp_path / "nested" / "reports"
    report("decision", directory=d, intent="use cache")
    assert d.exists()


def test_report_returns_path(tmp_path):
    result = report("decision", directory=tmp_path, intent="test")
    assert isinstance(result, Path)


def test_report_path_exists(tmp_path):
    path = report("outcome", directory=tmp_path, result="success")
    assert path.exists()


def test_report_filename_contains_kind(tmp_path):
    path = report("preference", directory=tmp_path, liked="dark mode")
    assert "preference" in path.name


def test_report_filename_is_json(tmp_path):
    path = report("decision", directory=tmp_path, intent="caching")
    assert path.suffix == ".json"


# ---------------------------------------------------------------------------
# report — content
# ---------------------------------------------------------------------------

def test_report_stores_kind(tmp_path):
    path = report("outcome", directory=tmp_path, result="ok")
    data = json.loads(path.read_text())
    assert data["kind"] == "outcome"


def test_report_stores_ts(tmp_path):
    path = report("decision", directory=tmp_path, intent="x")
    data = json.loads(path.read_text())
    assert "ts" in data
    assert data["ts"] > 0


def test_report_stores_kwargs(tmp_path):
    path = report("decision", directory=tmp_path, intent="use caching", reasoning="reduces latency")
    data = json.loads(path.read_text())
    assert data["intent"] == "use caching"
    assert data["reasoning"] == "reduces latency"


def test_report_outcome_stores_result(tmp_path):
    path = report("outcome", directory=tmp_path, result="cache hit 92%", lesson="TTL=5m optimal")
    data = json.loads(path.read_text())
    assert data["result"] == "cache hit 92%"
    assert data["lesson"] == "TTL=5m optimal"


def test_report_preference_stores_liked_disliked(tmp_path):
    path = report("preference", directory=tmp_path, liked="short summaries", disliked="verbose output")
    data = json.loads(path.read_text())
    assert data["liked"] == "short summaries"
    assert data["disliked"] == "verbose output"


def test_report_is_valid_json(tmp_path):
    path = report("decision", directory=tmp_path, intent="test")
    # Should not raise
    data = json.loads(path.read_text())
    assert isinstance(data, dict)
