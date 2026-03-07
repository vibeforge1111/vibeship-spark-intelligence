"""Tests for lib/soul_metrics.py

Covers:
- record_metric(): creates JSONL file, writes row with kind + payload,
  adds ts field, appends multiple rows, handles None payload, swallows
  exceptions silently
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import lib.soul_metrics as sm
from lib.soul_metrics import record_metric


def test_record_metric_creates_file(tmp_path, monkeypatch):
    f = tmp_path / "soul_metrics.jsonl"
    monkeypatch.setattr(sm, "SOUL_METRICS_FILE", f)
    record_metric("test_kind", {"value": 1})
    assert f.exists()


def test_record_metric_writes_kind(tmp_path, monkeypatch):
    f = tmp_path / "soul_metrics.jsonl"
    monkeypatch.setattr(sm, "SOUL_METRICS_FILE", f)
    record_metric("happiness", {"level": 0.9})
    row = json.loads(f.read_text().strip())
    assert row["kind"] == "happiness"


def test_record_metric_includes_payload(tmp_path, monkeypatch):
    f = tmp_path / "soul_metrics.jsonl"
    monkeypatch.setattr(sm, "SOUL_METRICS_FILE", f)
    record_metric("curiosity", {"topic": "black holes", "intensity": 5})
    row = json.loads(f.read_text().strip())
    assert row["topic"] == "black holes"
    assert row["intensity"] == 5


def test_record_metric_adds_ts(tmp_path, monkeypatch):
    f = tmp_path / "soul_metrics.jsonl"
    monkeypatch.setattr(sm, "SOUL_METRICS_FILE", f)
    before = time.time()
    record_metric("growth", {})
    after = time.time()
    row = json.loads(f.read_text().strip())
    assert before <= row["ts"] <= after


def test_record_metric_appends_multiple(tmp_path, monkeypatch):
    f = tmp_path / "soul_metrics.jsonl"
    monkeypatch.setattr(sm, "SOUL_METRICS_FILE", f)
    record_metric("a", {"x": 1})
    record_metric("b", {"x": 2})
    lines = f.read_text().strip().splitlines()
    assert len(lines) == 2


def test_record_metric_handles_none_payload(tmp_path, monkeypatch):
    f = tmp_path / "soul_metrics.jsonl"
    monkeypatch.setattr(sm, "SOUL_METRICS_FILE", f)
    record_metric("empty", None)  # should not raise
    row = json.loads(f.read_text().strip())
    assert row["kind"] == "empty"


def test_record_metric_swallows_exceptions(tmp_path, monkeypatch):
    # Point to an unwritable path — should not raise
    monkeypatch.setattr(sm, "SOUL_METRICS_FILE", Path("/proc/unwritable/nope.jsonl"))
    record_metric("test", {"x": 1})  # silently swallowed


def test_record_metric_creates_parent_dirs(tmp_path, monkeypatch):
    f = tmp_path / "nested" / "deep" / "soul_metrics.jsonl"
    monkeypatch.setattr(sm, "SOUL_METRICS_FILE", f)
    record_metric("nested_kind", {"val": True})
    assert f.exists()
