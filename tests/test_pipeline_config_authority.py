from __future__ import annotations

import json

import lib.config_authority as config_authority
import lib.pipeline as pipeline


def test_load_pipeline_config_reads_batch_size_from_values(monkeypatch, tmp_path):
    """Boot loader reads queue_batch_size from 'values' section via resolve_section."""
    spark_dir = tmp_path / ".spark"
    spark_dir.mkdir()
    tuneables = spark_dir / "tuneables.json"
    tuneables.write_text(
        json.dumps({"values": {"queue_batch_size": 150}}),
        encoding="utf-8",
    )

    original = pipeline.DEFAULT_BATCH_SIZE
    monkeypatch.setattr(pipeline, "DEFAULT_BATCH_SIZE", 200)

    # Isolate from real baseline config
    empty_baseline = tmp_path / "empty_baseline.json"
    empty_baseline.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config_authority, "DEFAULT_BASELINE_PATH", empty_baseline)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    pipeline._load_pipeline_config()

    assert pipeline.DEFAULT_BATCH_SIZE == 150


def test_reload_pipeline_from_applies_batch_size():
    """reload_pipeline_from sets DEFAULT_BATCH_SIZE from cfg dict."""
    import lib.pipeline as p
    original = p.DEFAULT_BATCH_SIZE
    try:
        p.reload_pipeline_from({"queue_batch_size": 300})
        assert p.DEFAULT_BATCH_SIZE == 300
    finally:
        p.DEFAULT_BATCH_SIZE = original
