from __future__ import annotations

import json
from pathlib import Path

import lib.chip_merger as chip_merger
import lib.memory_banks as memory_banks
import lib.memory_capture as memory_capture
import lib.observatory.config as observatory_config
import lib.pattern_detection.request_tracker as request_tracker
from lib.config_authority import resolve_section


def test_memory_capture_load_config_reads_runtime(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "memory_capture": {
                    "auto_save_threshold": 0.72,
                    "suggest_threshold": 0.61,
                    "max_capture_chars": 4096,
                    "context_capture_chars": 360,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(memory_capture, "TUNEABLES_FILE", tuneables)

    cfg = memory_capture._load_memory_capture_config()

    assert cfg["auto_save_threshold"] == 0.72
    assert cfg["suggest_threshold"] == 0.61
    assert cfg["max_capture_chars"] == 4096
    assert cfg["context_capture_chars"] == 360


def test_request_tracker_load_config_reads_runtime(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "request_tracker": {
                    "max_pending": 77,
                    "max_completed": 333,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(request_tracker, "TUNEABLES_FILE", tuneables)

    cfg = request_tracker._load_request_tracker_config()

    assert cfg["max_pending"] == 77
    assert cfg["max_completed"] == 333
    assert cfg["max_age_seconds"] == 3600.0


def test_chip_merger_skips_host_tuneables_in_pytest(monkeypatch):
    monkeypatch.setattr(chip_merger, "TUNEABLES_FILE", Path.home() / ".spark" / "tuneables.json")
    monkeypatch.delenv("SPARK_TEST_ALLOW_HOME_TUNEABLES", raising=False)
    monkeypatch.setattr(
        chip_merger,
        "resolve_section",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("resolve_section should not be called")),
    )

    loaded = chip_merger._load_merge_tuneables()

    assert loaded["duplicate_churn_ratio"] == chip_merger.DUPLICATE_CHURN_RATIO
    assert loaded["duplicate_churn_min_processed"] == chip_merger.DUPLICATE_CHURN_MIN_PROCESSED
    assert loaded["duplicate_churn_cooldown_s"] == chip_merger.DUPLICATE_CHURN_COOLDOWN_S


def test_memory_banks_emotion_write_capture_env_override(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps({"memory_emotion": {"write_capture_enabled": False}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(memory_banks, "TUNEABLES_FILE", tuneables)
    monkeypatch.setenv("SPARK_MEMORY_EMOTION_WRITE_CAPTURE", "1")

    assert memory_banks._emotion_write_capture_enabled() is True


def test_observatory_load_config_uses_runtime_over_baseline(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    baseline = tmp_path / "baseline.json"
    runtime = runtime_root / "tuneables.json"
    baseline.write_text(
        json.dumps({"observatory": {"enabled": False, "sync_cooldown_s": 999}}),
        encoding="utf-8",
    )
    runtime.write_text(
        json.dumps({"observatory": {"enabled": True, "sync_cooldown_s": 45}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(observatory_config, "_BASELINE_FILE", baseline)
    monkeypatch.setattr(observatory_config, "_SPARK_DIR", runtime_root)

    cfg = observatory_config.load_config()

    assert cfg.enabled is True
    assert cfg.sync_cooldown_s == 45


def test_resolve_section_does_not_leak_mutable_schema_defaults(tmp_path):
    # Use non-existent files so section values come from schema defaults only.
    baseline = tmp_path / "missing-baseline.json"
    runtime = tmp_path / "missing-runtime.json"

    first = resolve_section("sync", baseline_path=baseline, runtime_path=runtime).data
    first["adapters_enabled"].append("codex")
    first["adapters_disabled"].append("cursor")

    second = resolve_section("sync", baseline_path=baseline, runtime_path=runtime).data
    assert second["adapters_enabled"] == []
    assert second["adapters_disabled"] == []
