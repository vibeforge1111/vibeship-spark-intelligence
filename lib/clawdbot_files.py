"""Helpers for interacting with Clawdbot's file-based constitution + memory.

These helpers are *workspace-relative* and are designed to support proposal-first
workflows (write patches, not direct edits).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


def workspace() -> Path:
    return Path(os.environ.get("SPARK_WORKSPACE", str(Path.home() / "clawd"))).expanduser()


def memory_md() -> Path:
    return workspace() / "MEMORY.md"


def user_md() -> Path:
    return workspace() / "USER.md"


def daily_memory_dir() -> Path:
    return workspace() / "memory"


def daily_memory_path(date: Optional[datetime] = None) -> Path:
    d = date or datetime.now()
    return daily_memory_dir() / f"{d.strftime('%Y-%m-%d')}.md"
