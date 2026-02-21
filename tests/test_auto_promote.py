"""Tests for lib/auto_promote.py

Covers:
- _load_promotion_config_interval(): default when no file, reads interval from
  tuneables.json, handles missing key, handles corrupt JSON
- _should_run(): True when no last-run file, False when run was recent,
  True when run was old, handles corrupt last-run file
- _mark_run(): creates parent dir, writes numeric timestamp string
- maybe_promote_on_session_end(): returns None on rate-limit, calls
  check_and_promote when allowed, returns stats dict, marks run after
  execution, handles promoter exception gracefully
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import lib.auto_promote as ap
from lib.auto_promote import (
    _load_promotion_config_interval,
    _should_run,
    _mark_run,
    maybe_promote_on_session_end,
    DEFAULT_INTERVAL_S,
)


# ---------------------------------------------------------------------------
# _load_promotion_config_interval
# ---------------------------------------------------------------------------

def test_load_interval_default_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", tmp_path / "nope.txt")
    # Point home away so no tuneables.json is found
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    # Re-run with no tuneables
    result = _load_promotion_config_interval()
    assert result == DEFAULT_INTERVAL_S


def test_load_interval_reads_from_tuneables(tmp_path, monkeypatch):
    spark = tmp_path / ".spark"
    spark.mkdir()
    tuneables = spark / "tuneables.json"
    tuneables.write_text(json.dumps({"promotion": {"auto_interval_s": 7200}}), encoding="utf-8")
    # Patch Path.home() to return tmp_path
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))
    result = _load_promotion_config_interval()
    assert result == 7200


def test_load_interval_missing_promotion_key(tmp_path, monkeypatch):
    spark = tmp_path / ".spark"
    spark.mkdir()
    (spark / "tuneables.json").write_text(json.dumps({"other": {}}), encoding="utf-8")
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))
    assert _load_promotion_config_interval() == DEFAULT_INTERVAL_S


def test_load_interval_corrupt_json(tmp_path, monkeypatch):
    spark = tmp_path / ".spark"
    spark.mkdir()
    (spark / "tuneables.json").write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))
    assert _load_promotion_config_interval() == DEFAULT_INTERVAL_S


def test_load_interval_returns_int(tmp_path, monkeypatch):
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))
    assert isinstance(_load_promotion_config_interval(), int)


# ---------------------------------------------------------------------------
# _should_run
# ---------------------------------------------------------------------------

def test_should_run_true_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", tmp_path / "missing.txt")
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))
    assert _should_run() is True


def test_should_run_false_when_recent(tmp_path, monkeypatch):
    f = tmp_path / "last.txt"
    f.write_text(str(time.time()), encoding="utf-8")
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", f)
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))
    assert _should_run() is False


def test_should_run_true_when_old(tmp_path, monkeypatch):
    f = tmp_path / "last.txt"
    # Write timestamp 2 hours ago
    f.write_text(str(time.time() - 7200), encoding="utf-8")
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", f)
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))
    assert _should_run() is True


def test_should_run_true_with_corrupt_file(tmp_path, monkeypatch):
    f = tmp_path / "last.txt"
    f.write_text("not-a-number", encoding="utf-8")
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", f)
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))
    assert _should_run() is True


def test_should_run_returns_bool(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", tmp_path / "x.txt")
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))
    result = _should_run()
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _mark_run
# ---------------------------------------------------------------------------

def test_mark_run_creates_file(tmp_path, monkeypatch):
    f = tmp_path / "sub" / "last.txt"
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", f)
    _mark_run()
    assert f.exists()


def test_mark_run_writes_numeric_timestamp(tmp_path, monkeypatch):
    f = tmp_path / "last.txt"
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", f)
    before = time.time()
    _mark_run()
    after = time.time()
    ts = float(f.read_text(encoding="utf-8").strip())
    assert before <= ts <= after


def test_mark_run_overwrites_existing(tmp_path, monkeypatch):
    f = tmp_path / "last.txt"
    f.write_text("0.0", encoding="utf-8")
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", f)
    _mark_run()
    ts = float(f.read_text(encoding="utf-8").strip())
    assert ts > 1_000_000  # Modern epoch, not 0


# ---------------------------------------------------------------------------
# maybe_promote_on_session_end
# ---------------------------------------------------------------------------

def test_maybe_promote_returns_none_when_rate_limited(tmp_path, monkeypatch):
    f = tmp_path / "last.txt"
    f.write_text(str(time.time()), encoding="utf-8")
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", f)
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))
    result = maybe_promote_on_session_end()
    assert result is None


def test_maybe_promote_calls_check_and_promote(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", tmp_path / "last.txt")
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))

    mock_stats = {"promoted": 3, "skipped": 0}
    mock_promoter = MagicMock()
    mock_promoter.check_and_promote.return_value = mock_stats

    import sys
    dummy = MagicMock()
    dummy.check_and_promote = mock_promoter.check_and_promote
    monkeypatch.setitem(sys.modules, "lib.promoter", dummy)

    result = maybe_promote_on_session_end()
    assert result is not None
    assert result["promoted"] == 3


def test_maybe_promote_marks_run_on_success(tmp_path, monkeypatch):
    last_file = tmp_path / "last.txt"
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", last_file)
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))

    import sys
    dummy = MagicMock()
    dummy.check_and_promote.return_value = {"promoted": 0}
    monkeypatch.setitem(sys.modules, "lib.promoter", dummy)

    maybe_promote_on_session_end()
    assert last_file.exists()


def test_maybe_promote_handles_promoter_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", tmp_path / "last.txt")
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))

    import sys
    dummy = MagicMock()
    dummy.check_and_promote.side_effect = RuntimeError("boom")
    monkeypatch.setitem(sys.modules, "lib.promoter", dummy)

    # Should not raise
    result = maybe_promote_on_session_end()
    assert result is None


def test_maybe_promote_marks_run_even_on_exception(tmp_path, monkeypatch):
    last_file = tmp_path / "last.txt"
    monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", last_file)
    monkeypatch.setattr(ap.Path, "home", staticmethod(lambda: tmp_path))

    import sys
    dummy = MagicMock()
    dummy.check_and_promote.side_effect = RuntimeError("boom")
    monkeypatch.setitem(sys.modules, "lib.promoter", dummy)

    maybe_promote_on_session_end()
    assert last_file.exists()
