from __future__ import annotations

import json
from pathlib import Path

from lib import carmack_kpi as ck


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_window_metrics_computes_aligned_gaur_and_burdens():
    start = 1000.0
    end = 2000.0
    events = [
        {"ts": 1200.0, "event": "emitted"},
        {"ts": 1300.0, "event": "fallback_emit"},
        {"ts": 1400.0, "event": "no_emit"},
        {"ts": 1500.0, "event": "synth_empty"},
        {"ts": 5000.0, "event": "emitted"},  # out-of-window
    ]
    feedback = [
        {"created_at": 1600.0, "advice_ids": ["a", "b", "c"], "schema_version": 2},
        {"created_at": 5000.0, "advice_ids": ["d"]},  # out-of-window
    ]
    outcomes = {
        "a": {"ts": 1700.0, "followed_counted": True, "helpful_counted": True},
        "b": {"ts": 1750.0, "followed_counted": True, "helpful_counted": True},
        "x": {"ts": 5100.0, "followed_counted": True, "helpful_counted": True},  # out-of-window
    }

    out = ck._window_metrics(
        advisory_rows=events,
        feedback_rows=feedback,
        recent_outcomes=outcomes,
        start_ts=start,
        end_ts=end,
    )

    assert out["delivered"] == 2
    assert round(out["fallback_burden"], 4) == 0.5
    assert out["emitted_advice_items"] == 3
    assert out["good_advice_used"] == 2
    assert round(out["gaur"], 4) == round(2.0 / 3.0, 4)
    assert round(out["noise_burden"], 4) == round(2.0 / 4.0, 4)


def test_window_metrics_counts_alpha_suppression_events_as_noise():
    start = 1000.0
    end = 2000.0
    events = [
        {"ts": 1200.0, "event": "emitted"},
        {"ts": 1300.0, "event": "gate_no_emit"},
        {"ts": 1400.0, "event": "context_repeat_blocked"},
        {"ts": 1500.0, "event": "dedupe_empty"},
    ]
    out = ck._window_metrics(
        advisory_rows=events,
        feedback_rows=[],
        recent_outcomes={},
        start_ts=start,
        end_ts=end,
    )
    assert out["alpha_suppressed"] == 3
    assert out["no_emit"] == 3
    assert round(out["suppression_burden"], 4) == round(3.0 / 4.0, 4)
    assert round(out["noise_burden"], 4) == round(3.0 / 4.0, 4)


def test_build_scorecard_reads_files_and_computes_core_reliability(tmp_path, monkeypatch):
    advisory = tmp_path / "advisory.jsonl"
    feedback = tmp_path / "feedback.jsonl"
    effectiveness = tmp_path / "effectiveness.json"
    sync = tmp_path / "sync.json"
    chip = tmp_path / "chip.json"

    _write_jsonl(
        advisory,
        [
            {"ts": 1900.0, "event": "emitted"},         # current window (>=1600)
            {"ts": 1910.0, "event": "fallback_emit"},   # current window
            {"ts": 1500.0, "event": "fallback_emit"},   # previous window (>=1200,<1600)
        ],
    )
    _write_jsonl(
        feedback,
        [
            {"created_at": 1950.0, "advice_ids": ["a", "b"], "schema_version": 2},
            {"created_at": 1300.0, "advice_ids": ["c"], "schema_version": 2},
        ],
    )
    _write_json(
        effectiveness,
        {
            "recent_outcomes": {
                "a": {"ts": 1960.0, "followed_counted": True, "helpful_counted": True},
                "b": {"ts": 1970.0, "followed_counted": False, "helpful_counted": False},
                "c": {"ts": 1350.0, "followed_counted": True, "helpful_counted": True},
            }
        },
    )
    _write_json(sync, {"last_full_sync": "t", "total_syncs": 1, "adapters": {"openclaw": {"status": "success"}}})
    _write_json(chip, {"last_merge": "t2", "last_stats": {"processed": 20}})

    monkeypatch.setattr(ck, "ADVISORY_LOG", advisory)
    monkeypatch.setattr(ck, "ADVICE_FEEDBACK_REQUESTS", feedback)
    monkeypatch.setattr(ck, "EFFECTIVENESS_FILE", effectiveness)
    monkeypatch.setattr(ck, "SYNC_STATS_FILE", sync)
    monkeypatch.setattr(ck, "CHIP_MERGE_FILE", chip)
    monkeypatch.setattr(
        ck,
        "_service_status_snapshot",
        lambda: {
            "sparkd": {"running": True},
            "bridge_worker": {"running": True},
            "scheduler": {"running": False},
            "watchdog": {"running": True},
        },
    )

    score = ck.build_scorecard(window_hours=0.111111111, now_ts=2000.0)  # ~400s window

    assert score["current"]["emitted"] == 1
    assert score["current"]["fallback_emit"] == 1
    assert score["current"]["emitted_advice_items"] == 2
    assert score["current"]["good_advice_used"] == 1
    assert round(score["metrics"]["gaur"]["current"], 4) == 0.5
    assert round(score["metrics"]["feedback_schema_v2_ratio"]["current"], 4) == 1.0
    assert round(score["core"]["core_reliability"], 4) == 0.75


def test_build_scorecard_gates_quality_gaur_on_schema_v2(tmp_path, monkeypatch):
    advisory = tmp_path / "advisory.jsonl"
    feedback = tmp_path / "feedback.jsonl"
    effectiveness = tmp_path / "effectiveness.json"
    sync = tmp_path / "sync.json"
    chip = tmp_path / "chip.json"

    _write_jsonl(advisory, [{"ts": 1900.0, "event": "emitted"}])
    _write_jsonl(feedback, [{"created_at": 1950.0, "advice_ids": ["a"]}])  # legacy row (no schema_version)
    _write_json(
        effectiveness,
        {"recent_outcomes": {"a": {"ts": 1960.0, "followed_counted": True, "helpful_counted": True}}},
    )
    _write_json(sync, {})
    _write_json(chip, {})

    monkeypatch.setattr(ck, "ADVISORY_LOG", advisory)
    monkeypatch.setattr(ck, "ADVICE_FEEDBACK_REQUESTS", feedback)
    monkeypatch.setattr(ck, "EFFECTIVENESS_FILE", effectiveness)
    monkeypatch.setattr(ck, "SYNC_STATS_FILE", sync)
    monkeypatch.setattr(ck, "CHIP_MERGE_FILE", chip)
    monkeypatch.setattr(
        ck,
        "_service_status_snapshot",
        lambda: {"sparkd": {"running": True}, "bridge_worker": {"running": True}, "scheduler": {"running": True}, "watchdog": {"running": True}},
    )

    score = ck.build_scorecard(window_hours=0.111111111, now_ts=2000.0)
    assert score["metrics"]["gaur"]["current"] is None
    assert round(score["metrics"]["gaur_all"]["current"], 4) == 1.0
    assert round(score["metrics"]["feedback_schema_v2_ratio"]["current"], 4) == 0.0


def test_core_reliability_uses_effective_service_signals():
    status = {
        "sparkd": {"running": False, "healthy": True},
        "bridge_worker": {"running": False, "process_running": True, "heartbeat_fresh": False},
        "scheduler": {"running": False, "process_running": False, "heartbeat_fresh": True},
        "watchdog": {"running": False, "pid": 1234},
    }
    core = ck._core_reliability(status)
    assert core["core_running"] == 4
    assert core["core_reliability"] == 1.0
    assert core["core_effective_running"]["sparkd"] is True


def test_build_health_alert_ok_when_thresholds_clear(monkeypatch):
    monkeypatch.setattr(ck, "_sample_failure_snapshot", lambda limit=12: {"sampled_failures": [], "sample_count": 0})
    score = {
        "generated_at": 100.0,
        "window_hours": 4.0,
        "core": {"core_reliability": 1.0},
        "metrics": {"gaur": {"current": 0.4}, "noise_burden": {"current": 0.2}},
        "service_status": {"bridge_worker": {"heartbeat_age_s": 10.0}},
        "current": {"event_counts": {}, "delivered": 3},
    }

    alert = ck.build_health_alert(score)
    assert alert["status"] == "ok"
    assert alert["breach_count"] == 0
    assert "snapshot" not in alert


def test_build_health_alert_includes_snapshot_on_breach(monkeypatch):
    monkeypatch.setattr(
        ck,
        "_sample_failure_snapshot",
        lambda limit=12: {"sampled_failures": [{"event": "engine_error"}], "sample_count": 1},
    )
    score = {
        "generated_at": 100.0,
        "window_hours": 4.0,
        "core": {"core_reliability": 0.5},
        "metrics": {"gaur": {"current": 0.1}, "noise_burden": {"current": 0.9}},
        "service_status": {
            "sparkd": {"running": True},
            "bridge_worker": {"heartbeat_age_s": 999.0},
            "scheduler": {"running": True},
            "watchdog": {"running": True},
        },
        "current": {"event_counts": {"engine_error": 1}, "delivered": 0},
    }

    alert = ck.build_health_alert(score)
    assert alert["status"] == "breach"
    assert alert["breach_count"] >= 1
    assert "snapshot" in alert
    assert alert["snapshot"]["sample_count"] == 1
