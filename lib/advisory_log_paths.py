"""Shared advisory runtime log path helpers."""

from __future__ import annotations

from pathlib import Path


SPARK_DIR = Path.home() / ".spark"
ADVISORY_ENGINE_ALPHA_LOG = SPARK_DIR / "advisory_engine_alpha.jsonl"


def advisory_engine_log_default() -> Path:
    """Canonical advisory runtime log for readers and reports."""
    return ADVISORY_ENGINE_ALPHA_LOG
