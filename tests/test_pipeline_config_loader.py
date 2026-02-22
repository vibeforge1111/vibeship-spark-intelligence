"""Tests for pipeline._load_pipeline_config() exception specificity fixes."""
import importlib
import json
from pathlib import Path

import pytest


def test_corrupt_json_logs_and_keeps_default(tmp_path, monkeypatch):
    """Corrupt tuneables.json should log via log_debug and leave DEFAULT_BATCH_SIZE unchanged."""
    spark_dir = tmp_path / ".spark"
    spark_dir.mkdir(parents=True)
    (spark_dir / "tuneables.json").write_text("not valid json", encoding="utf-8")

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    import lib.pipeline as pipeline_mod

    captured = []
    monkeypatch.setattr(
        pipeline_mod, "log_debug", lambda tag, msg, exc: captured.append((tag, msg, exc))
    )

    original = pipeline_mod.DEFAULT_BATCH_SIZE
    pipeline_mod._load_pipeline_config()

    assert pipeline_mod.DEFAULT_BATCH_SIZE == original
    assert len(captured) == 1
    assert captured[0][0] == "pipeline"
    assert "tuneables" in captured[0][1]


def test_valid_batch_size_applied(tmp_path, monkeypatch):
    """Valid tuneables.json with queue_batch_size should update DEFAULT_BATCH_SIZE."""
    spark_dir = tmp_path / ".spark"
    spark_dir.mkdir(parents=True)
    (spark_dir / "tuneables.json").write_text(
        json.dumps({"values": {"queue_batch_size": 300}}), encoding="utf-8"
    )

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    import lib.pipeline as pipeline_mod

    pipeline_mod._load_pipeline_config()

    assert pipeline_mod.DEFAULT_BATCH_SIZE == 300
