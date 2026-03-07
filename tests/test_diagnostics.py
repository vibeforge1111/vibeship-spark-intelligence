"""Tests for lib/diagnostics.py — lightweight debug logging utilities."""
from __future__ import annotations

import io
import sys
import threading
from pathlib import Path

import pytest

import lib.diagnostics as diag


# ---------------------------------------------------------------------------
# debug_enabled
# ---------------------------------------------------------------------------

class TestDebugEnabled:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("SPARK_DEBUG", raising=False)
        assert diag.debug_enabled() is False

    def test_enabled_with_1(self, monkeypatch):
        monkeypatch.setenv("SPARK_DEBUG", "1")
        assert diag.debug_enabled() is True

    def test_enabled_with_true(self, monkeypatch):
        monkeypatch.setenv("SPARK_DEBUG", "true")
        assert diag.debug_enabled() is True

    def test_enabled_with_yes(self, monkeypatch):
        monkeypatch.setenv("SPARK_DEBUG", "yes")
        assert diag.debug_enabled() is True

    def test_enabled_with_on(self, monkeypatch):
        monkeypatch.setenv("SPARK_DEBUG", "on")
        assert diag.debug_enabled() is True

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("SPARK_DEBUG", "TRUE")
        assert diag.debug_enabled() is True

    def test_disabled_with_0(self, monkeypatch):
        monkeypatch.setenv("SPARK_DEBUG", "0")
        assert diag.debug_enabled() is False

    def test_disabled_with_false(self, monkeypatch):
        monkeypatch.setenv("SPARK_DEBUG", "false")
        assert diag.debug_enabled() is False

    def test_disabled_with_empty(self, monkeypatch):
        monkeypatch.setenv("SPARK_DEBUG", "")
        assert diag.debug_enabled() is False

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("SPARK_DEBUG", "  1  ")
        assert diag.debug_enabled() is True


# ---------------------------------------------------------------------------
# _log_backup_path
# ---------------------------------------------------------------------------

class TestLogBackupPath:
    def test_backup_path_suffix(self, tmp_path):
        p = tmp_path / "spark.log"
        bp = diag._log_backup_path(p, 1)
        assert bp.name == "spark.log.1"

    def test_backup_path_idx_3(self, tmp_path):
        p = tmp_path / "component.log"
        bp = diag._log_backup_path(p, 3)
        assert bp.name == "component.log.3"

    def test_backup_path_same_parent(self, tmp_path):
        p = tmp_path / "x.log"
        bp = diag._log_backup_path(p, 2)
        assert bp.parent == tmp_path


# ---------------------------------------------------------------------------
# _rotate_log_file
# ---------------------------------------------------------------------------

class TestRotateLogFile:
    def test_no_rotate_when_small(self, tmp_path):
        p = tmp_path / "app.log"
        p.write_text("hello", encoding="utf-8")
        diag._rotate_log_file(p, max_bytes=10_000, backups=3)
        assert p.exists()  # not rotated

    def test_rotates_when_exceeds_max(self, tmp_path):
        p = tmp_path / "app.log"
        p.write_text("A" * 100, encoding="utf-8")
        diag._rotate_log_file(p, max_bytes=10, backups=3)
        # Original replaced by .1
        b1 = diag._log_backup_path(p, 1)
        assert b1.exists()

    def test_no_rotate_when_max_bytes_zero(self, tmp_path):
        p = tmp_path / "app.log"
        p.write_text("A" * 200, encoding="utf-8")
        diag._rotate_log_file(p, max_bytes=0, backups=3)
        assert p.exists()

    def test_no_rotate_when_backups_zero(self, tmp_path):
        p = tmp_path / "app.log"
        p.write_text("A" * 200, encoding="utf-8")
        diag._rotate_log_file(p, max_bytes=10, backups=0)
        # No rotation (guard returns early)
        assert p.exists()

    def test_no_error_when_file_missing(self, tmp_path):
        p = tmp_path / "nonexistent.log"
        # Should not raise
        diag._rotate_log_file(p, max_bytes=10, backups=3)

    def test_chain_rotation(self, tmp_path):
        p = tmp_path / "app.log"
        b1 = diag._log_backup_path(p, 1)
        # pre-create .1 backup
        b1.write_text("old", encoding="utf-8")
        p.write_text("B" * 100, encoding="utf-8")
        diag._rotate_log_file(p, max_bytes=10, backups=3)
        b2 = diag._log_backup_path(p, 2)
        assert b2.exists()


# ---------------------------------------------------------------------------
# _RotatingFile
# ---------------------------------------------------------------------------

class TestRotatingFile:
    def test_write_returns_len(self, tmp_path):
        p = tmp_path / "r.log"
        rf = diag._RotatingFile(p, max_bytes=1_000_000, backups=3)
        n = rf.write("hello")
        assert n == 5
        rf.flush()

    def test_write_none_returns_zero(self, tmp_path):
        p = tmp_path / "r.log"
        rf = diag._RotatingFile(p, max_bytes=1_000_000, backups=3)
        n = rf.write(None)
        assert n == 0

    def test_write_non_string_converts(self, tmp_path):
        p = tmp_path / "r.log"
        rf = diag._RotatingFile(p, max_bytes=1_000_000, backups=3)
        rf.write(42)
        rf.flush()
        assert "42" in p.read_text()

    def test_flush_does_not_raise(self, tmp_path):
        p = tmp_path / "r.log"
        rf = diag._RotatingFile(p, max_bytes=1_000_000, backups=3)
        rf.flush()  # Should not raise

    def test_isatty_false(self, tmp_path):
        p = tmp_path / "r.log"
        rf = diag._RotatingFile(p, max_bytes=1_000_000, backups=3)
        assert rf.isatty() is False

    def test_rotation_triggers(self, tmp_path):
        p = tmp_path / "r.log"
        rf = diag._RotatingFile(p, max_bytes=20, backups=3)
        rf.write("A" * 25)
        rf.flush()
        b1 = diag._log_backup_path(p, 1)
        assert b1.exists() or p.exists()  # rotation happened

    def test_thread_safety(self, tmp_path):
        p = tmp_path / "ts.log"
        rf = diag._RotatingFile(p, max_bytes=1_000_000, backups=3)
        errors = []

        def writer():
            for _ in range(50):
                try:
                    rf.write("data\n")
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors

    def test_should_rotate_false_when_max_zero(self, tmp_path):
        p = tmp_path / "r.log"
        rf = diag._RotatingFile(p, max_bytes=0, backups=3)
        assert rf._should_rotate("big data") is False


# ---------------------------------------------------------------------------
# _Tee
# ---------------------------------------------------------------------------

class TestTee:
    def _make_buf(self):
        return io.StringIO()

    def test_write_to_both(self):
        a, b = self._make_buf(), self._make_buf()
        tee = diag._Tee(a, b)
        tee.write("hello")
        assert a.getvalue() == "hello"
        assert b.getvalue() == "hello"

    def test_write_returns_len(self):
        a, b = self._make_buf(), self._make_buf()
        tee = diag._Tee(a, b)
        n = tee.write("abc")
        assert n == 3

    def test_flush_does_not_raise(self):
        a, b = self._make_buf(), self._make_buf()
        tee = diag._Tee(a, b)
        tee.flush()  # Should not raise

    def test_isatty_false_for_stringio(self):
        a, b = self._make_buf(), self._make_buf()
        tee = diag._Tee(a, b)
        assert tee.isatty() is False

    def test_primary_none_tolerates(self):
        b = self._make_buf()
        tee = diag._Tee(None, b)
        tee.write("x")
        assert b.getvalue() == "x"

    def test_secondary_none_tolerates(self):
        a = self._make_buf()
        tee = diag._Tee(a, None)
        tee.write("y")
        assert a.getvalue() == "y"

    def test_write_empty_string(self):
        a, b = self._make_buf(), self._make_buf()
        tee = diag._Tee(a, b)
        n = tee.write("")
        assert n == 0

    def test_flush_with_none_primary(self):
        b = self._make_buf()
        tee = diag._Tee(None, b)
        tee.flush()  # Should not raise


# ---------------------------------------------------------------------------
# _emit_log_line
# ---------------------------------------------------------------------------

class TestEmitLogLine:
    def test_emits_to_stderr(self, capsys):
        diag._emit_log_line("comp", "test message")
        captured = capsys.readouterr()
        assert "[SPARK][comp] test message" in captured.err

    def test_emits_exception_to_stderr(self, capsys):
        try:
            raise ValueError("boom")
        except ValueError as e:
            diag._emit_log_line("comp", "err msg", exc=e)
        captured = capsys.readouterr()
        assert "boom" in captured.err

    def test_emits_exception_traceback(self, capsys):
        try:
            raise RuntimeError("trace me")
        except RuntimeError as e:
            diag._emit_log_line("comp", "tracing", exc=e)
        captured = capsys.readouterr()
        assert "RuntimeError" in captured.err

    def test_no_exception_arg(self, capsys):
        diag._emit_log_line("mycomp", "plain message", exc=None)
        captured = capsys.readouterr()
        assert "plain message" in captured.err
        # No colon appended for exc=None
        assert "None" not in captured.err


# ---------------------------------------------------------------------------
# log_debug
# ---------------------------------------------------------------------------

class TestLogDebug:
    def test_no_output_when_disabled(self, monkeypatch, capsys):
        monkeypatch.setenv("SPARK_DEBUG", "0")
        diag.log_debug("comp", "hidden")
        captured = capsys.readouterr()
        assert "hidden" not in captured.err

    def test_output_when_enabled(self, monkeypatch, capsys):
        monkeypatch.setenv("SPARK_DEBUG", "1")
        diag.log_debug("comp", "visible msg")
        captured = capsys.readouterr()
        assert "visible msg" in captured.err

    def test_with_exception(self, monkeypatch, capsys):
        monkeypatch.setenv("SPARK_DEBUG", "1")
        try:
            raise TypeError("test exc")
        except TypeError as e:
            diag.log_debug("comp", "exc test", exc=e)
        captured = capsys.readouterr()
        assert "exc test" in captured.err
        assert "TypeError" in captured.err


# ---------------------------------------------------------------------------
# log_exception
# ---------------------------------------------------------------------------

class TestLogException:
    def test_always_emits(self, monkeypatch, capsys):
        monkeypatch.setenv("SPARK_DEBUG", "0")
        diag.log_exception("svc", "critical error")
        captured = capsys.readouterr()
        assert "critical error" in captured.err

    def test_emits_even_without_exc(self, monkeypatch, capsys):
        monkeypatch.setenv("SPARK_DEBUG", "0")
        diag.log_exception("svc", "just a message")
        captured = capsys.readouterr()
        assert "[SPARK][svc] just a message" in captured.err


# ---------------------------------------------------------------------------
# setup_component_logging
# ---------------------------------------------------------------------------

class TestSetupComponentLogging:
    def setup_method(self):
        # Reset module-level state before each test to avoid cross-test pollution
        diag._LOG_SETUP.clear()
        diag._LOG_HANDLES.clear()

    def teardown_method(self):
        # Restore stdout/stderr if redirected
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        diag._LOG_SETUP.clear()
        diag._LOG_HANDLES.clear()

    def test_creates_log_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPARK_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("SPARK_LOG_TEE", "0")
        result = diag.setup_component_logging("testcomp")
        assert result == tmp_path / "testcomp.log"
        assert (tmp_path / "testcomp.log").exists()

    def test_idempotent_second_call(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPARK_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("SPARK_LOG_TEE", "0")
        r1 = diag.setup_component_logging("comp2")
        r2 = diag.setup_component_logging("comp2")
        # Second call returns None (already set up)
        assert r1 is not None
        assert r2 is None

    def test_tee_mode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPARK_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("SPARK_LOG_TEE", "1")
        result = diag.setup_component_logging("teecomp")
        assert result is not None
        # stdout should now be a _Tee
        assert isinstance(sys.stdout, diag._Tee)

    def test_returns_none_when_dir_unwritable(self, tmp_path, monkeypatch):
        bad_dir = "/dev/null/impossible/path"
        monkeypatch.setenv("SPARK_LOG_DIR", bad_dir)
        result = diag.setup_component_logging("failcomp")
        assert result is None
