"""Shared advisory runtime log path helpers.

Alpha log is canonical for live runtime. Compatibility log is retained during
cutover so legacy consumers can continue reading without breakage.
"""

from __future__ import annotations

from pathlib import Path


SPARK_DIR = Path.home() / ".spark"
ADVISORY_ENGINE_ALPHA_LOG = SPARK_DIR / "advisory_engine_alpha.jsonl"
ADVISORY_ENGINE_COMPAT_LOG = SPARK_DIR / "advisory_engine.jsonl"


def advisory_engine_log_default() -> Path:
    """Preferred advisory runtime log for readers.

    Use alpha when present; otherwise fall back to compatibility log.
    """
    if ADVISORY_ENGINE_ALPHA_LOG.exists():
        return ADVISORY_ENGINE_ALPHA_LOG
    return ADVISORY_ENGINE_COMPAT_LOG


def advisory_engine_log_alpha() -> Path:
    return ADVISORY_ENGINE_ALPHA_LOG


def advisory_engine_log_compat() -> Path:
    return ADVISORY_ENGINE_COMPAT_LOG

