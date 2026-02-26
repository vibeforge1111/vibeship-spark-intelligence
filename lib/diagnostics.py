"""Lightweight debug logging utilities for Spark."""

from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Optional, List


_DEBUG_VALUES = {"1", "true", "yes", "on"}
_LOG_SETUP = set()
_LOG_HANDLES: List[object] = []

_LOG_MAX_BYTES = int(os.environ.get("SPARK_LOG_MAX_BYTES", "10485760"))  # 10 MB
_LOG_BACKUPS = int(os.environ.get("SPARK_LOG_BACKUPS", "5"))


def _log_backup_path(path: Path, idx: int) -> Path:
    return path.with_name(f"{path.name}.{idx}")


def _rotate_log_file(path: Path, max_bytes: int, backups: int) -> None:
    if max_bytes <= 0 or backups <= 0:
        return
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
    except Exception:
        return

    # Rotate: file -> .1, .1 -> .2, etc.
    try:
        for i in range(backups - 1, 0, -1):
            src = _log_backup_path(path, i)
            dst = _log_backup_path(path, i + 1)
            if src.exists():
                if dst.exists():
                    dst.unlink(missing_ok=True)
                src.replace(dst)
        first = _log_backup_path(path, 1)
        if first.exists():
            first.unlink(missing_ok=True)
        path.replace(first)
    except Exception:
        return


class _RotatingFile:
    def __init__(self, path: Path, max_bytes: int, backups: int) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.backups = backups
        self._lock = threading.Lock()
        self._handle = open(path, "a", encoding="utf-8", errors="replace")

    def _should_rotate(self, data: str) -> bool:
        if self.max_bytes <= 0:
            return False
        try:
            size = self.path.stat().st_size if self.path.exists() else 0
        except Exception:
            return False
        try:
            delta = len(data.encode("utf-8", errors="replace"))
        except Exception:
            delta = len(data)
        return size + delta >= self.max_bytes

    def _rotate(self) -> None:
        try:
            self._handle.flush()
            self._handle.close()
        except Exception:
            pass
        _rotate_log_file(self.path, self.max_bytes, self.backups)
        self._handle = open(self.path, "a", encoding="utf-8", errors="replace")

    def write(self, data: str) -> int:
        if data is None:
            return 0
        text = data if isinstance(data, str) else str(data)
        with self._lock:
            if self._should_rotate(text):
                self._rotate()
            try:
                return self._handle.write(text)
            except Exception:
                return len(text)

    def flush(self) -> None:
        try:
            self._handle.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False


def debug_enabled() -> bool:
    """Return True when SPARK_DEBUG is set to a truthy value."""
    return os.environ.get("SPARK_DEBUG", "").strip().lower() in _DEBUG_VALUES


def _emit_log_line(component: str, message: str, exc: Optional[BaseException] = None) -> None:
    try:
        line = f"[SPARK][{component}] {message}"
        if exc is not None:
            line = f"{line}: {exc}"
        sys.stderr.write(line + "\n")
        if exc is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            sys.stderr.write(tb + "\n")
    except Exception:
        return


def log_debug(component: str, message: str, exc: Optional[BaseException] = None) -> None:
    """Emit a debug log line to stderr when SPARK_DEBUG is enabled."""
    if not debug_enabled():
        return
    _emit_log_line(component, message, exc)


def log_exception(component: str, message: str, exc: Optional[BaseException] = None) -> None:
    """Emit an error log line regardless of SPARK_DEBUG."""
    _emit_log_line(component, message, exc)


class _Tee:
    def __init__(self, primary: Any, secondary: Any) -> None:
        self.primary = primary
        self.secondary = secondary

    def write(self, data: str) -> int:
        try:
            if self.primary:
                self.primary.write(data)
        except Exception:
            pass
        try:
            if self.secondary:
                self.secondary.write(data)
        except Exception:
            pass
        return len(data)

    def flush(self) -> None:
        try:
            if self.primary:
                self.primary.flush()
        except Exception:
            pass
        try:
            if self.secondary:
                self.secondary.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return bool(getattr(self.primary, "isatty", lambda: False)())
        except Exception:
            return False


def setup_component_logging(component: str) -> Optional[Path]:
    """Ensure logs are written to ~/.spark/logs even when not started by scripts."""
    if component in _LOG_SETUP:
        return None
    log_dir = Path(os.environ.get("SPARK_LOG_DIR") or (Path.home() / ".spark" / "logs"))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None

    log_file = log_dir / f"{component}.log"
    _rotate_log_file(log_file, _LOG_MAX_BYTES, _LOG_BACKUPS)
    try:
        handle = _RotatingFile(log_file, _LOG_MAX_BYTES, _LOG_BACKUPS)
    except Exception:
        return None

    _LOG_HANDLES.append(handle)
    tee_enabled = os.environ.get("SPARK_LOG_TEE", "1").strip().lower() in _DEBUG_VALUES

    already_redirected = False
    try:
        stdout_name = getattr(sys.stdout, "name", "")
        stderr_name = getattr(sys.stderr, "name", "")
        if stdout_name and Path(stdout_name).resolve() == log_file.resolve():
            already_redirected = True
        if stderr_name and Path(stderr_name).resolve() == log_file.resolve():
            already_redirected = True
    except Exception:
        already_redirected = False

    if tee_enabled and not already_redirected:
        sys.stdout = _Tee(sys.stdout, handle)
        sys.stderr = _Tee(sys.stderr, handle)
    else:
        sys.stdout = handle
        sys.stderr = handle

    _LOG_SETUP.add(component)
    return log_file
