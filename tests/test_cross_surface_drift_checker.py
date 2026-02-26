from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.cross_surface_drift_checker as drift


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row) for row in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def test_compute_drift_report_ok_when_emit_rates_are_close(tmp_path, monkeypatch):
    now = time.time()
    obs_snapshot = tmp_path / "_observatory" / "memory_quality_snapshot.json"
    obs_state = tmp_path / "_observatory" / ".observatory_snapshot.json"
    engine_log = tmp_path / "advisory_engine.jsonl"
    decision_log = tmp_path / "advisory_decision_ledger.jsonl"

    _write_json(
        obs_snapshot,
        {
            "capture": {"noise_like_ratio": 0.12},
            "context": {"p50": 130},
            "advisory_engine": {"emit_rate": 0.20},
        },
    )
    _write_json(obs_state, {"decision_emit_rate": 20.5})
    _write_jsonl(
        engine_log,
        [
            {"ts": now - 5, "event": "emitted"},
            {"ts": now - 4, "event": "no_emit"},
            {"ts": now - 3.5, "event": "no_emit"},
            {"ts": now - 3.1, "event": "no_emit"},
            {"ts": now - 2.9, "event": "no_emit"},
        ],
    )
    _write_jsonl(
        decision_log,
        [
            {"ts": now - 3, "outcome": "emitted"},
            {"ts": now - 2, "outcome": "blocked"},
            {"ts": now - 1.8, "outcome": "blocked"},
            {"ts": now - 1.6, "outcome": "blocked"},
            {"ts": now - 1.4, "outcome": "blocked"},
        ],
    )

    monkeypatch.setattr(drift, "OBSERVATORY_SNAPSHOT", obs_snapshot)
    monkeypatch.setattr(drift, "OBSERVATORY_STATE", obs_state)
    monkeypatch.setattr(drift, "ADVISORY_ENGINE_LOG", engine_log)
    monkeypatch.setattr(drift, "ADVISORY_DECISION_LEDGER", decision_log)

    report = drift.compute_drift_report(window_hours=24.0)
    assert report["drift_incidents"] == 0
    statuses = {item["metric"]: item["status"] for item in report["comparisons"]}
    assert statuses["advisory_emit_rate"] in {"OK", "INSUFFICIENT"}


def test_compute_drift_report_flags_emit_rate_drift(tmp_path, monkeypatch):
    now = time.time()
    obs_snapshot = tmp_path / "_observatory" / "memory_quality_snapshot.json"
    obs_state = tmp_path / "_observatory" / ".observatory_snapshot.json"
    engine_log = tmp_path / "advisory_engine.jsonl"
    decision_log = tmp_path / "advisory_decision_ledger.jsonl"

    _write_json(
        obs_snapshot,
        {
            "capture": {"noise_like_ratio": 0.12},
            "context": {"p50": 130},
            "advisory_engine": {"emit_rate": 0.80},
        },
    )
    _write_json(obs_state, {"decision_emit_rate": 10.0})
    _write_jsonl(
        engine_log,
        [{"ts": now - 5, "event": "emitted"}, {"ts": now - 4, "event": "no_emit"}],
    )
    _write_jsonl(
        decision_log,
        [{"ts": now - 3, "outcome": "emitted"}, {"ts": now - 2, "outcome": "blocked"}],
    )

    monkeypatch.setattr(drift, "OBSERVATORY_SNAPSHOT", obs_snapshot)
    monkeypatch.setattr(drift, "OBSERVATORY_STATE", obs_state)
    monkeypatch.setattr(drift, "ADVISORY_ENGINE_LOG", engine_log)
    monkeypatch.setattr(drift, "ADVISORY_DECISION_LEDGER", decision_log)

    report = drift.compute_drift_report(window_hours=24.0)
    statuses = {item["metric"]: item["status"] for item in report["comparisons"]}
    assert statuses["advisory_emit_rate"] == "DRIFT"
    assert report["drift_incidents"] >= 1
