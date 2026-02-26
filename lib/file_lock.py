"""Lightweight inter-process file lock using lock files.

Used for JSONL append+rotate critical sections where row loss is unacceptable.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

LOCK_TIMEOUT_S = 2.0
LOCK_POLL_S = 0.01
LOCK_STALE_S = 30.0


def acquire_file_lock(
    lock_path: Path,
    *,
    timeout_s: float = LOCK_TIMEOUT_S,
    poll_s: float = LOCK_POLL_S,
    stale_s: float = LOCK_STALE_S,
) -> int:
    """Acquire an exclusive lock-file descriptor or raise TimeoutError."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + max(0.1, float(timeout_s))
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            try:
                os.write(fd, f"pid={os.getpid()} ts={time.time():.6f}\n".encode("utf-8"))
            except Exception:
                pass
            return fd
        except FileExistsError:
            try:
                age_s = time.time() - float(lock_path.stat().st_mtime or 0.0)
                if age_s >= float(stale_s):
                    lock_path.unlink(missing_ok=True)
                    continue
            except Exception:
                pass
            if time.time() >= deadline:
                raise TimeoutError(f"timed out acquiring lock: {lock_path}")
            time.sleep(max(0.001, float(poll_s)))


def release_file_lock(fd: Optional[int], lock_path: Path) -> None:
    """Release lock file descriptor and remove lock file."""
    try:
        if fd is not None:
            os.close(fd)
    except Exception:
        pass
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        pass


@contextmanager
def file_lock_for(
    path: Path,
    *,
    timeout_s: float = LOCK_TIMEOUT_S,
    poll_s: float = LOCK_POLL_S,
    stale_s: float = LOCK_STALE_S,
    fail_open: bool = True,
) -> Iterator[None]:
    """Context manager that acquires lock at `<path>.lock`."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    fd: Optional[int] = None
    try:
        try:
            fd = acquire_file_lock(lock_path, timeout_s=timeout_s, poll_s=poll_s, stale_s=stale_s)
        except TimeoutError:
            if not fail_open:
                raise
        yield
    finally:
        release_file_lock(fd, lock_path)
