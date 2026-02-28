from __future__ import annotations

from types import SimpleNamespace

import lib.auto_tuner as auto_tuner


def test_auto_tuner_reads_config_authority_when_runtime_file_missing(monkeypatch, tmp_path):
    runtime_tuneables = tmp_path / "missing_runtime_tuneables.json"

    monkeypatch.setattr(
        auto_tuner,
        "resolve_section",
        lambda section_name, runtime_path=None: SimpleNamespace(
            data={
                "enabled": True,
                "run_interval_s": 43200,
                "last_run": "1970-01-01T00:00:00+00:00",
                "source_boosts": {},
            }
        ),
    )

    tuner = auto_tuner.AutoTuner(tuneables_path=runtime_tuneables)

    assert tuner.enabled is True
    assert tuner.run_interval == 43200
    assert tuner.should_run() is True


def test_auto_tuner_refresh_preserves_effective_enabled_flag(monkeypatch, tmp_path):
    runtime_tuneables = tmp_path / "runtime_tuneables.json"

    monkeypatch.setattr(
        auto_tuner,
        "resolve_section",
        lambda section_name, runtime_path=None: SimpleNamespace(
            data={
                "enabled": True,
                "run_interval_s": 43200,
                "last_run": "1970-01-01T00:00:00+00:00",
                "source_boosts": {},
            }
        ),
    )

    tuner = auto_tuner.AutoTuner(tuneables_path=runtime_tuneables)
    tuner._record_noop_run({}, "2026-02-28T00:00:00+00:00", "test")

    assert tuner.enabled is True
