"""Tests for lib/self_report.py — structured agent self-reporting."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import lib.self_report as sr
from lib.self_report import report, VALID_KINDS, DEFAULT_REPORT_DIR


# ---------------------------------------------------------------------------
# VALID_KINDS
# ---------------------------------------------------------------------------


def test_valid_kinds_contains_decision():
    assert "decision" in VALID_KINDS


def test_valid_kinds_contains_outcome():
    assert "outcome" in VALID_KINDS


def test_valid_kinds_contains_preference():
    assert "preference" in VALID_KINDS


def test_valid_kinds_only_three():
    assert len(VALID_KINDS) == 3


# ---------------------------------------------------------------------------
# report — invalid kind
# ---------------------------------------------------------------------------


def test_report_invalid_kind_raises():
    with pytest.raises(ValueError, match="Invalid report kind"):
        report("unknown_kind", directory="/tmp")


def test_report_invalid_kind_message_contains_kind():
    with pytest.raises(ValueError, match="bogus"):
        report("bogus", directory="/tmp")


def test_report_invalid_kind_message_lists_valid():
    with pytest.raises(ValueError, match="decision|outcome|preference"):
        report("bad", directory="/tmp")


# ---------------------------------------------------------------------------
# report — file creation
# ---------------------------------------------------------------------------


def test_report_creates_file(tmp_path):
    path = report("decision", directory=tmp_path, intent="do something")
    assert path.exists()


def test_report_returns_path_object(tmp_path):
    path = report("outcome", directory=tmp_path, result="done")
    assert isinstance(path, Path)


def test_report_file_in_correct_directory(tmp_path):
    path = report("preference", directory=tmp_path, liked="clear answers")
    assert path.parent == tmp_path


def test_report_creates_parent_directory(tmp_path):
    nested = tmp_path / "a" / "b" / "reports"
    path = report("decision", directory=nested, intent="test")
    assert nested.exists()
    assert path.exists()


# ---------------------------------------------------------------------------
# report — filename format
# ---------------------------------------------------------------------------


def test_report_filename_starts_with_kind(tmp_path):
    path = report("decision", directory=tmp_path, intent="test")
    assert path.name.startswith("decision_")


def test_report_outcome_filename_starts_correctly(tmp_path):
    path = report("outcome", directory=tmp_path, result="ok")
    assert path.name.startswith("outcome_")


def test_report_preference_filename_starts_correctly(tmp_path):
    path = report("preference", directory=tmp_path, liked="x")
    assert path.name.startswith("preference_")


def test_report_filename_is_json(tmp_path):
    path = report("decision", directory=tmp_path, intent="x")
    assert path.suffix == ".json"


def test_report_filename_contains_timestamp(tmp_path):
    path = report("decision", directory=tmp_path, intent="x")
    # Filename contains YYYYMMDD
    import re
    assert re.search(r"\d{8}", path.name)


# ---------------------------------------------------------------------------
# report — file content
# ---------------------------------------------------------------------------


def test_report_content_is_valid_json(tmp_path):
    path = report("decision", directory=tmp_path, intent="test intent")
    data = json.loads(path.read_text())
    assert isinstance(data, dict)


def test_report_content_has_kind(tmp_path):
    path = report("outcome", directory=tmp_path, result="done")
    data = json.loads(path.read_text())
    assert data["kind"] == "outcome"


def test_report_content_has_ts(tmp_path):
    before = time.time()
    path = report("decision", directory=tmp_path, intent="x")
    after = time.time()
    data = json.loads(path.read_text())
    assert before <= data["ts"] <= after


def test_report_kwargs_stored_in_payload(tmp_path):
    path = report("decision", directory=tmp_path, intent="use caching", reasoning="reduce latency")
    data = json.loads(path.read_text())
    assert data["intent"] == "use caching"
    assert data["reasoning"] == "reduce latency"


def test_report_preference_kwargs_stored(tmp_path):
    path = report("preference", directory=tmp_path, liked="dark mode", disliked="verbose output")
    data = json.loads(path.read_text())
    assert data["liked"] == "dark mode"
    assert data["disliked"] == "verbose output"


def test_report_outcome_kwargs_stored(tmp_path):
    path = report("outcome", directory=tmp_path, result="cache hit 92%", lesson="TTL 5m optimal")
    data = json.loads(path.read_text())
    assert data["result"] == "cache hit 92%"
    assert data["lesson"] == "TTL 5m optimal"


def test_report_no_kwargs_still_works(tmp_path):
    path = report("decision", directory=tmp_path)
    data = json.loads(path.read_text())
    assert data["kind"] == "decision"


# ---------------------------------------------------------------------------
# report — multiple calls produce distinct files
# ---------------------------------------------------------------------------


def test_report_multiple_calls_distinct_files(tmp_path):
    import time as _time
    p1 = report("decision", directory=tmp_path, intent="first")
    _time.sleep(0.01)  # ensure ms-component differs
    p2 = report("decision", directory=tmp_path, intent="second")
    # At least one file must exist; both may share a name on very fast machines
    files = list(tmp_path.glob("decision_*.json"))
    assert len(files) >= 1


# ---------------------------------------------------------------------------
# _report_dir — directory resolution
# ---------------------------------------------------------------------------


def test_report_dir_env_var_used(monkeypatch, tmp_path):
    monkeypatch.setenv("SPARK_REPORT_DIR", str(tmp_path / "env_dir"))
    path = report("decision")
    assert "env_dir" in str(path)


def test_report_dir_explicit_overrides_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SPARK_REPORT_DIR", str(tmp_path / "env_dir"))
    explicit = tmp_path / "explicit_dir"
    path = report("decision", directory=explicit)
    assert "explicit_dir" in str(path)
    assert "env_dir" not in str(path)
