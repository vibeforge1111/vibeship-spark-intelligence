from __future__ import annotations

import json
from pathlib import Path

import lib.observatory.tuneables_deep_dive as deep_dive
from lib.tuneables_schema import SCHEMA, SECTION_CONSUMERS


def test_deep_dive_sections_track_tuneables_schema():
    assert set(deep_dive.SCHEMA_SECTIONS) == set(SCHEMA.keys())


def test_deep_dive_consumers_track_schema_consumers():
    assert deep_dive.SECTION_CONSUMERS.get("opportunity_scanner") == SECTION_CONSUMERS.get("opportunity_scanner")
    assert deep_dive.SECTION_CONSUMERS.get("feature_gates") == SECTION_CONSUMERS.get("feature_gates")


def test_deep_dive_reload_map_has_recent_sections():
    assert "memory_deltas" in deep_dive.KNOWN_RELOAD_SECTIONS
    assert "opportunity_scanner" in deep_dive.KNOWN_RELOAD_SECTIONS


def test_deep_dive_uses_versioned_fallback_when_runtime_tuneables_missing(monkeypatch, tmp_path: Path):
    spark_dir = tmp_path / ".spark"
    repo_root = tmp_path / "repo"
    config_dir = repo_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "tuneables.json").write_text(
        json.dumps(
            {
                "advisory_gate": {"max_emit_per_call": 2},
                "advisory_engine": {"global_dedupe_cooldown_s": 300},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(deep_dive, "_SPARK_DIR", spark_dir)
    monkeypatch.setattr(deep_dive, "_REPO_ROOT", repo_root)

    page = deep_dive.generate_tuneables_deep_dive({})
    assert "Runtime source mode | versioned_fallback" in page
    assert "Runtime tuneables present | False" in page
    assert "Runtime tuneables file is absent" in page
    assert "Config drifts detected | 0" in page
