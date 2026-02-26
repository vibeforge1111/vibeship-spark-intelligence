from __future__ import annotations

import json
from pathlib import Path

import lib.config_authority as config_authority
import lib.eidos.models as eidos_models


def test_load_eidos_config_merges_runtime_and_values(monkeypatch, tmp_path):
    """_load_eidos_config merges eidos + values sections via resolve_section.

    resolve_section applies 4 layers: schema -> baseline -> runtime -> env.
    The eidos schema defines max_retries_per_error, max_file_touches, and
    no_evidence_limit, so those always exist in resolved eidos.  But max_steps
    was removed from eidos schema (Batch 5) — so it CAN be inherited from
    values section when not set in eidos runtime.

    We test:
      1) eidos-section runtime overrides beat schema defaults
      2) max_steps inherited from values when absent from eidos runtime
      3) Schema defaults for eidos-only keys are present
    """
    spark_dir = tmp_path / ".spark"
    spark_dir.mkdir()
    tuneables = spark_dir / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "values": {
                    "max_steps": 77,
                },
                "eidos": {
                    "max_time_seconds": 1800,
                    "max_retries_per_error": 6,
                },
            }
        ),
        encoding="utf-8",
    )

    # Point both baseline and runtime at our tmp file so resolve_section is isolated
    empty_baseline = tmp_path / "empty_baseline.json"
    empty_baseline.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config_authority, "DEFAULT_BASELINE_PATH", empty_baseline)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    cfg = eidos_models._load_eidos_config()

    # eidos-section runtime overrides beat schema defaults
    assert cfg["max_time_seconds"] == 1800
    assert cfg["max_retries_per_error"] == 6
    # max_steps inherited from values (removed from eidos schema)
    assert cfg["max_steps"] == 77
    # no_evidence_limit comes from eidos schema default (6)
    assert cfg["no_evidence_limit"] == 6


def test_merge_eidos_with_values_helper():
    """_merge_eidos_with_values merges shared keys correctly."""
    eidos = {"max_time_seconds": 900}
    values = {"max_steps": 50, "no_evidence_steps": 3}

    result = eidos_models._merge_eidos_with_values(eidos, values)

    assert result["max_time_seconds"] == 900
    assert result["max_steps"] == 50
    assert result["no_evidence_limit"] == 3


def test_merge_eidos_with_values_eidos_takes_precedence():
    """eidos section keys take precedence over values section."""
    eidos = {"max_steps": 100}
    values = {"max_steps": 50}

    result = eidos_models._merge_eidos_with_values(eidos, values)

    assert result["max_steps"] == 100
