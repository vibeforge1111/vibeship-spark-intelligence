"""Tests for lib/diagnostics.py

Covers:
- _log_backup_path(): naming scheme (".N" suffix)
- _rotate_log_file(): no-ops when size below threshold or backups <= 0,
  performs rotation when file exceeds max_bytes
- debug_enabled(): truthy/falsy SPARK_DEBUG values
- log_debug(): emits to stderr only when debug enabled, silent otherwise
- log_exception(): always emits to stderr
- _RotatingFile: write() appends content, flush() doesn't raise, isatty() False
- _Tee: routes writes to both streams, isatty() delegates to primary
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pytest

from lib.diagnostics import (
    _log_backup_path,
    _rotate_log_file,
    _RotatingFile,
    _Tee,
    debug_enabled,
    log_debug,
    log_exception,
)


# ---------------------------------------------------------------------------
# _log_backup_path
# ---------------------------------------------------------------------------

def test_log_backup_path_appends_index(tmp_path):
    p = tmp_path / "spark.log"
    result = _log_backup_path(p, 1)
    assert result.name == "spark.log.1"


def test_log_backup_path_correct_index(tmp_path):
    p = tmp_path / "spark.log"
    result = _log_backup_path(p, 3)
    assert result.name == "spark.log.3"


def test_log_backup_path_same_parent(tmp_path):
    p = tmp_path / "spark.log"
    result = _log_backup_path(p, 2)
    assert result.parent == tmp_path


def test_log_backup_path_returns_path(tmp_path):
    p = tmp_path / "spark.log"
    assert isinstance(_log_backup_path(p, 1), Path)


# ---------------------------------------------------------------------------
# _rotate_log_file — no-op cases
# ---------------------------------------------------------------------------

def test_rotate_noop_when_max_bytes_zero(tmp_path):
    log = tmp_path / "spark.log"
    log.write_text("x" * 100, encoding="utf-8")
    # Should not raise and should leave file intact
    _rotate_log_file(log, max_bytes=0, backups=3)
    assert log.exists()


def test_rotate_noop_when_backups_zero(tmp_path):
    log = tmp_path / "spark.log"
    log.write_text("x" * 100, encoding="utf-8")
    _rotate_log_file(log, max_bytes=10, backups=0)
    assert log.exists()


def test_rotate_noop_when_file_missing(tmp_path):
    log = tmp_path / "missing.log"
    _rotate_log_file(log, max_bytes=10, backups=3)
    # Should not raise


def test_rotate_noop_when_below_size_threshold(tmp_path):
    log = tmp_path / "spark.log"
    log.write_text("small", encoding="utf-8")
    original_size = log.stat().st_size
    _rotate_log_file(log, max_bytes=10_000, backups=3)
    # File still present, not rotated
    assert log.exists()
    assert log.stat().st_size == original_size


# ---------------------------------------------------------------------------
# _rotate_log_file — active rotation
# ---------------------------------------------------------------------------

def test_rotate_moves_file_to_dot1(tmp_path):
    log = tmp_path / "spark.log"
    log.write_text("A" * 200, encoding="utf-8")
    _rotate_log_file(log, max_bytes=50, backups=3)
    backup1 = _log_backup_path(log, 1)
    assert backup1.exists()


def test_rotate_creates_fresh_log_after_rotation(tmp_path):
    log = tmp_path / "spark.log"
    log.write_text("A" * 200, encoding="utf-8")
    _rotate_log_file(log, max_bytes=50, backups=3)
    # Original log should no longer exist (replaced by .1)
    assert not log.exists() or log.stat().st_size == 0


def test_rotate_backup_contains_original_content(tmp_path):
    log = tmp_path / "spark.log"
    content = "X" * 200
    log.write_text(content, encoding="utf-8")
    _rotate_log_file(log, max_bytes=50, backups=3)
    backup1 = _log_backup_path(log, 1)
    assert backup1.read_text(encoding="utf-8") == content


def test_rotate_cascades_existing_backups(tmp_path):
    log = tmp_path / "spark.log"
    backup1 = _log_backup_path(log, 1)
    log.write_text("CURRENT" * 30, encoding="utf-8")
    backup1.write_text("OLD" * 30, encoding="utf-8")
    _rotate_log_file(log, max_bytes=50, backups=3)
    backup2 = _log_backup_path(log, 2)
    assert backup2.exists()
    assert "OLD" in backup2.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# debug_enabled
# ---------------------------------------------------------------------------

def test_debug_enabled_false_by_default(monkeypatch):
    monkeypatch.delenv("SPARK_DEBUG", raising=False)
    assert debug_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "True", "TRUE", "yes", "on"])
def test_debug_enabled_truthy_values(monkeypatch, val):
    monkeypatch.setenv("SPARK_DEBUG", val)
    assert debug_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
def test_debug_enabled_falsy_values(monkeypatch, val):
    monkeypatch.setenv("SPARK_DEBUG", val)
    assert debug_enabled() is False


def test_debug_enabled_returns_bool(monkeypatch):
    monkeypatch.setenv("SPARK_DEBUG", "1")
    assert isinstance(debug_enabled(), bool)


# ---------------------------------------------------------------------------
# log_debug
# ---------------------------------------------------------------------------

def test_log_debug_silent_when_disabled(monkeypatch, capsys):
    monkeypatch.delenv("SPARK_DEBUG", raising=False)
    log_debug("test", "should not appear")
    captured = capsys.readouterr()
    assert "should not appear" not in captured.err


def test_log_debug_emits_when_enabled(monkeypatch, capsys):
    monkeypatch.setenv("SPARK_DEBUG", "1")
    log_debug("mycomp", "hello from debug")
    captured = capsys.readouterr()
    assert "hello from debug" in captured.err


def test_log_debug_includes_component(monkeypatch, capsys):
    monkeypatch.setenv("SPARK_DEBUG", "1")
    log_debug("mycomp", "msg")
    captured = capsys.readouterr()
    assert "mycomp" in captured.err


def test_log_debug_includes_spark_prefix(monkeypatch, capsys):
    monkeypatch.setenv("SPARK_DEBUG", "1")
    log_debug("x", "y")
    captured = capsys.readouterr()
    assert "[SPARK]" in captured.err


def test_log_debug_includes_exception_message(monkeypatch, capsys):
    monkeypatch.setenv("SPARK_DEBUG", "1")
    exc = ValueError("boom")
    log_debug("comp", "something failed", exc)
    captured = capsys.readouterr()
    assert "boom" in captured.err


# ---------------------------------------------------------------------------
# log_exception
# ---------------------------------------------------------------------------

def test_log_exception_always_emits(monkeypatch, capsys):
    monkeypatch.delenv("SPARK_DEBUG", raising=False)
    log_exception("comp", "critical failure")
    captured = capsys.readouterr()
    assert "critical failure" in captured.err


def test_log_exception_includes_component(monkeypatch, capsys):
    log_exception("pipeline", "err msg")
    captured = capsys.readouterr()
    assert "pipeline" in captured.err


def test_log_exception_includes_exc_message(capsys):
    log_exception("c", "failed", ValueError("oops"))
    captured = capsys.readouterr()
    assert "oops" in captured.err


def test_log_exception_includes_traceback_when_exc_has_one(capsys):
    try:
        raise RuntimeError("trace me")
    except RuntimeError as exc:
        log_exception("c", "msg", exc)
    captured = capsys.readouterr()
    assert "RuntimeError" in captured.err


# ---------------------------------------------------------------------------
# _RotatingFile
# ---------------------------------------------------------------------------

def test_rotating_file_write_creates_content(tmp_path):
    p = tmp_path / "test.log"
    rf = _RotatingFile(p, max_bytes=10_000, backups=3)
    rf.write("hello world\n")
    rf.flush()
    assert "hello world" in p.read_text(encoding="utf-8")


def test_rotating_file_write_returns_int(tmp_path):
    p = tmp_path / "test.log"
    rf = _RotatingFile(p, max_bytes=10_000, backups=3)
    result = rf.write("data")
    assert isinstance(result, int)


def test_rotating_file_write_none_returns_zero(tmp_path):
    p = tmp_path / "test.log"
    rf = _RotatingFile(p, max_bytes=10_000, backups=3)
    result = rf.write(None)
    assert result == 0


def test_rotating_file_flush_does_not_raise(tmp_path):
    p = tmp_path / "test.log"
    rf = _RotatingFile(p, max_bytes=10_000, backups=3)
    rf.flush()  # Should not raise


def test_rotating_file_isatty_false(tmp_path):
    p = tmp_path / "test.log"
    rf = _RotatingFile(p, max_bytes=10_000, backups=3)
    assert rf.isatty() is False


def test_rotating_file_rotates_when_full(tmp_path):
    p = tmp_path / "test.log"
    # Create with a very small max_bytes to force rotation
    rf = _RotatingFile(p, max_bytes=10, backups=3)
    rf.write("X" * 100)
    rf.write("Y" * 100)
    backup1 = _log_backup_path(p, 1)
    assert backup1.exists()


def test_rotating_file_write_non_string(tmp_path):
    p = tmp_path / "test.log"
    rf = _RotatingFile(p, max_bytes=10_000, backups=3)
    # Should coerce to string
    rf.write(42)
    rf.flush()
    assert "42" in p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# _Tee
# ---------------------------------------------------------------------------

def test_tee_write_goes_to_primary():
    primary = StringIO()
    secondary = StringIO()
    tee = _Tee(primary, secondary)
    tee.write("hello")
    assert "hello" in primary.getvalue()


def test_tee_write_goes_to_secondary():
    primary = StringIO()
    secondary = StringIO()
    tee = _Tee(primary, secondary)
    tee.write("hello")
    assert "hello" in secondary.getvalue()


def test_tee_write_returns_length():
    primary = StringIO()
    secondary = StringIO()
    tee = _Tee(primary, secondary)
    result = tee.write("abc")
    assert result == 3


def test_tee_flush_does_not_raise():
    primary = StringIO()
    secondary = StringIO()
    tee = _Tee(primary, secondary)
    tee.flush()  # Should not raise


def test_tee_isatty_false_for_stringio():
    tee = _Tee(StringIO(), StringIO())
    assert tee.isatty() is False


def test_tee_tolerates_none_primary():
    secondary = StringIO()
    tee = _Tee(None, secondary)
    tee.write("data")
    assert "data" in secondary.getvalue()


def test_tee_tolerates_none_secondary():
    primary = StringIO()
    tee = _Tee(primary, None)
    tee.write("data")
    assert "data" in primary.getvalue()
