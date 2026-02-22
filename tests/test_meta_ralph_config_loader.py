"""Regression tests for meta_ralph._load_meta_ralph_config error handling.

Before the fix, _load_meta_ralph_config() caught bare Exception with no
logging, making corrupt tuneables.json completely invisible in production.
"""
from __future__ import annotations

import json
import logging

import lib.meta_ralph as mr_mod


def _write_tuneables(tmp_path, content: str) -> None:
    spark_dir = tmp_path / ".spark"
    spark_dir.mkdir(parents=True, exist_ok=True)
    (spark_dir / "tuneables.json").write_text(content, encoding="utf-8")


def test_load_meta_ralph_config_corrupt_json_logs_warning(tmp_path, monkeypatch):
    """Corrupt tuneables.json must log a warning and leave module globals unchanged."""
    _write_tuneables(tmp_path, "{bad json!!!")

    monkeypatch.setattr(mr_mod.Path, "home", lambda: tmp_path)

    original_threshold = mr_mod.QUALITY_THRESHOLD

    logged = []
    logger = logging.getLogger("spark.meta_ralph")
    original_propagate = logger.propagate
    original_level = logger.level
    logger.propagate = False
    logger.setLevel(logging.WARNING)

    class _Capture(logging.Handler):
        def emit(self, record):
            logged.append(record.getMessage())

    cap = _Capture()
    logger.addHandler(cap)
    try:
        mr_mod._load_meta_ralph_config()
    finally:
        logger.removeHandler(cap)
        logger.propagate = original_propagate
        logger.setLevel(original_level)

    assert any("meta_ralph" in msg.lower() or "tuneables" in msg.lower() for msg in logged), (
        f"Expected a warning about config load failure; got: {logged}"
    )
    assert mr_mod.QUALITY_THRESHOLD == original_threshold


def test_load_meta_ralph_config_valid_section_applied(tmp_path, monkeypatch):
    """Valid meta_ralph config section must update module globals."""
    _write_tuneables(tmp_path, json.dumps({"meta_ralph": {"quality_threshold": 0.42}}))
    monkeypatch.setattr(mr_mod.Path, "home", lambda: tmp_path)

    mr_mod._load_meta_ralph_config()

    assert mr_mod.QUALITY_THRESHOLD == 0.42
