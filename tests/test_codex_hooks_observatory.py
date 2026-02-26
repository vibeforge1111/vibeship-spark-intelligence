from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.codex_hooks_observatory import (
    evaluate_fidelity_alert,
    evaluate_gates,
    summarize_telemetry,
)


def _row(ts: float, mode: str, metrics: dict) -> dict:
    return {
        "ts": ts,
        "mode": mode,
        "observe_forwarding_enabled": mode == "observe",
        "active_files": 10,
        "pending_calls": 0,
        "metrics": metrics,
    }


def test_shadow_gates_pass_with_healthy_metrics():
    rows = [
        _row(
            1000.0,
            "shadow",
            {
                "rows_seen": 100,
                "json_decode_errors": 0,
                "relevant_rows": 40,
                "mapped_events": 38,
                "pre_events": 15,
                "post_events": 14,
                "post_unknown_exit": 1,
                "post_unmatched_call_id": 0,
                "observe_calls": 0,
                "observe_success": 0,
                "observe_failures": 0,
                "pre_input_truncated": 1,
                "post_output_truncated": 2,
                "coverage_ratio": 0.95,
                "pairing_ratio": 1.0,
                "observe_latency_p95_ms": 0.0,
            },
        ),
        _row(
            1060.0,
            "shadow",
            {
                "rows_seen": 200,
                "json_decode_errors": 0,
                "relevant_rows": 80,
                "mapped_events": 78,
                "pre_events": 30,
                "post_events": 28,
                "post_unknown_exit": 2,
                "post_unmatched_call_id": 0,
                "observe_calls": 0,
                "observe_success": 0,
                "observe_failures": 0,
                "pre_input_truncated": 2,
                "post_output_truncated": 3,
                "coverage_ratio": 0.975,
                "pairing_ratio": 1.0,
                "observe_latency_p95_ms": 0.0,
            },
        ),
    ]

    summary = summarize_telemetry(rows, window_minutes=30, now_ts=1060.0)
    gates = evaluate_gates(summary)

    assert summary["available"] is True
    assert summary["derived"]["coverage_ratio"] >= 0.9
    assert summary["derived"]["pairing_ratio"] >= 0.9
    assert summary["derived"]["workflow_event_ratio"] > 0.0
    assert summary["derived"]["tool_result_capture_rate"] > 0.0
    assert summary["derived"]["truncated_tool_result_ratio"] >= 0.0
    assert summary["derived"]["mode_shadow_ratio"] == 1.0
    assert summary["derived"]["observe_forwarding_enabled_ratio"] == 0.0
    assert gates["passing"] is True
    assert gates["failed_count"] == 0


def test_observe_gates_fail_on_low_success_and_high_latency():
    rows = [
        _row(
            2000.0,
            "observe",
            {
                "rows_seen": 100,
                "json_decode_errors": 0,
                "relevant_rows": 50,
                "mapped_events": 48,
                "pre_events": 20,
                "post_events": 20,
                "post_unknown_exit": 2,
                "post_unmatched_call_id": 0,
                "observe_calls": 100,
                "observe_success": 90,
                "observe_failures": 10,
                "pre_input_truncated": 5,
                "post_output_truncated": 6,
                "coverage_ratio": 0.96,
                "pairing_ratio": 1.0,
                "observe_latency_p95_ms": 2600.0,
            },
        ),
        _row(
            2060.0,
            "observe",
            {
                "rows_seen": 200,
                "json_decode_errors": 0,
                "relevant_rows": 100,
                "mapped_events": 96,
                "pre_events": 40,
                "post_events": 40,
                "post_unknown_exit": 4,
                "post_unmatched_call_id": 0,
                "observe_calls": 200,
                "observe_success": 180,
                "observe_failures": 20,
                "pre_input_truncated": 10,
                "post_output_truncated": 12,
                "coverage_ratio": 0.96,
                "pairing_ratio": 1.0,
                "observe_latency_p95_ms": 2700.0,
            },
        ),
    ]

    summary = summarize_telemetry(rows, window_minutes=30, now_ts=2060.0)
    gates = evaluate_gates(summary)

    assert summary["mode"] == "observe"
    assert summary["derived"]["observe_success_ratio_window"] == 0.9
    assert summary["derived"]["mode_shadow_ratio"] == 0.0
    assert summary["derived"]["observe_forwarding_enabled_ratio"] == 1.0
    assert gates["passing"] is False
    assert "observe.success_ratio" in gates["failed_names"]
    assert "observe.latency_p95_ms" in gates["failed_names"]


def test_shadow_pairing_checks_not_required_while_pending_calls_exist():
    rows = [
        _row(
            3000.0,
            "shadow",
            {
                "rows_seen": 50,
                "json_decode_errors": 0,
                "relevant_rows": 20,
                "mapped_events": 20,
                "pre_events": 10,
                "post_events": 8,
                "post_unknown_exit": 0,
                "post_unmatched_call_id": 2,
                "observe_calls": 0,
                "observe_success": 0,
                "observe_failures": 0,
                "pre_input_truncated": 0,
                "post_output_truncated": 0,
                "coverage_ratio": 1.0,
                "pairing_ratio": 0.8,
                "observe_latency_p95_ms": 0.0,
            },
        ),
    ]
    summary = summarize_telemetry(rows, window_minutes=30, now_ts=3000.0)
    summary["pending_calls"] = 2

    gates = evaluate_gates(summary)

    checks = {c["name"]: c for c in gates["checks"]}
    assert checks["shadow.pairing_ratio"]["required"] is False
    assert checks["shadow.post_unmatched_delta"]["required"] is False
    assert gates["passing"] is True


def test_fidelity_alert_warning_then_critical_with_stale_repetition(tmp_path):
    rows = [
        _row(
            4000.0,
            "shadow",
            {
                "rows_seen": 100,
                "json_decode_errors": 0,
                "relevant_rows": 80,
                "mapped_events": 80,
                "pre_events": 40,
                "post_events": 10,
                "post_unknown_exit": 0,
                "post_unmatched_call_id": 0,
                "observe_calls": 0,
                "observe_success": 0,
                "observe_failures": 0,
                "coverage_ratio": 1.0,
                "pairing_ratio": 1.0,
                "observe_latency_p95_ms": 0.0,
            },
        ),
        _row(
            4060.0,
            "shadow",
            {
                "rows_seen": 200,
                "json_decode_errors": 0,
                "relevant_rows": 160,
                "mapped_events": 160,
                "pre_events": 80,
                "post_events": 20,
                "post_unknown_exit": 0,
                "post_unmatched_call_id": 0,
                "observe_calls": 0,
                "observe_success": 0,
                "observe_failures": 0,
                "coverage_ratio": 1.0,
                "pairing_ratio": 1.0,
                "observe_latency_p95_ms": 0.0,
            },
        ),
    ]

    summary = summarize_telemetry(rows, window_minutes=30, now_ts=4060.0)
    state_file = tmp_path / "alert_state.json"

    first = evaluate_fidelity_alert(summary, state_file=state_file, now_ts=4065.0)
    assert first["level"] == "warning"
    assert first["consecutive_breach_windows"] == 1
    assert first["stale"] is False

    second = evaluate_fidelity_alert(summary, state_file=state_file, now_ts=8000.0)
    assert second["level"] == "critical"
    assert second["consecutive_breach_windows"] == 2
    assert second["stale"] is True


def test_fidelity_alert_resets_after_healthy_window(tmp_path):
    state_file = tmp_path / "alert_state.json"

    warning_summary = {
        "available": True,
        "latest_ts": 1000.0,
        "derived": {
            "window_activity_rows": 10,
            "workflow_event_ratio": 0.4,
            "tool_result_capture_rate": 0.5,
        },
    }
    warning = evaluate_fidelity_alert(warning_summary, state_file=state_file, now_ts=1005.0)
    assert warning["level"] == "warning"
    assert warning["consecutive_breach_windows"] == 1

    healthy_summary = {
        "available": True,
        "latest_ts": 1010.0,
        "derived": {
            "window_activity_rows": 10,
            "workflow_event_ratio": 0.9,
            "tool_result_capture_rate": 0.95,
        },
    }
    healthy = evaluate_fidelity_alert(healthy_summary, state_file=state_file, now_ts=1011.0)
    assert healthy["level"] == "ok"
    assert healthy["consecutive_breach_windows"] == 0
