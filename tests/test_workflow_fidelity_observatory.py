from pathlib import Path

from scripts import workflow_fidelity_observatory as wf


def test_summarize_openclaw_uses_window_deltas():
    rows = [
        {
            "ts": 1000.0,
            "metrics": {
                "rows_seen": 10,
                "rows_skipped_filter": 2,
                "events_posted": 8,
                "tool_events": 4,
                "tool_calls": 3,
                "tool_results": 2,
                "tool_result_truncated": 1,
                "hook_rows_seen": 0,
                "report_files_seen": 0,
            },
        },
        {
            "ts": 1060.0,
            "metrics": {
                "rows_seen": 20,
                "rows_skipped_filter": 3,
                "events_posted": 16,
                "tool_events": 8,
                "tool_calls": 6,
                "tool_results": 4,
                "tool_result_truncated": 2,
                "hook_rows_seen": 2,
                "report_files_seen": 1,
            },
        },
    ]
    out = wf.summarize_openclaw(rows, window_minutes=60)
    assert out["available"] is True
    assert out["kpis"]["workflow_event_ratio"] == 0.5
    assert out["kpis"]["tool_result_capture_rate"] == round(2 / 3, 4)
    assert out["kpis"]["truncated_tool_result_ratio"] == 0.5
    assert out["kpis"]["skipped_by_filter_ratio"] == 0.1


def test_summarize_claude_from_observe_rows():
    rows = [
        {
            "ts": 2000.0,
            "source": "claude_code",
            "workflow_event": True,
            "pre_event": True,
            "tool_result_event": False,
            "tool_result_captured": False,
            "tool_result_truncated": False,
            "payload_truncated": False,
            "capture_ok": True,
        },
        {
            "ts": 2001.0,
            "source": "claude_code",
            "workflow_event": True,
            "pre_event": False,
            "tool_result_event": True,
            "tool_result_captured": True,
            "tool_result_truncated": True,
            "payload_truncated": True,
            "capture_ok": True,
        },
        {
            "ts": 2002.0,
            "source": "codex",
            "workflow_event": True,
            "pre_event": False,
            "tool_result_event": True,
            "tool_result_captured": True,
            "tool_result_truncated": False,
            "payload_truncated": False,
            "capture_ok": True,
        },
    ]
    out = wf.summarize_claude(rows, window_minutes=60)
    assert out["available"] is True
    assert out["window_rows"] == 2
    assert out["kpis"]["workflow_event_ratio"] == 1.0
    assert out["kpis"]["tool_result_capture_rate"] == 1.0
    assert out["kpis"]["truncated_tool_result_ratio"] == 1.0


def test_evaluate_alerts_escalates_to_critical_when_stale_and_repeated(tmp_path):
    state_file = tmp_path / "wf_state.json"
    providers = {
        "openclaw": {
            "available": True,
            "latest_ts": 1000.0,
            "window_activity_rows": 20,
            "kpis": {
                "workflow_event_ratio": 0.3,
                "tool_result_capture_rate": 0.4,
                "truncated_tool_result_ratio": 0.1,
                "skipped_by_filter_ratio": 0.1,
                "mode_shadow_ratio": 0.0,
            },
        },
        "claude": {"available": False},
        "codex": {"available": False},
    }
    first = wf.evaluate_alerts(providers, state_file=state_file, now_ts=1100.0)
    assert first["providers"]["openclaw"]["level"] == "warning"
    assert first["providers"]["openclaw"]["consecutive_breach_windows"] == 1

    second = wf.evaluate_alerts(providers, state_file=state_file, now_ts=4000.0)
    assert second["providers"]["openclaw"]["level"] == "critical"
    assert second["providers"]["openclaw"]["consecutive_breach_windows"] == 2
    assert second["providers"]["openclaw"]["stale"] is True
