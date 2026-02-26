import json

from adapters import openclaw_tailer as tailer


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_track_posted_event_counts_tool_metrics():
    metrics = tailer._new_fidelity_metrics()

    tailer._track_posted_event(
        metrics,
        {
            "kind": "tool",
            "payload": {"tool_name": "Read", "tool_input": {"file_path": "README.md"}},
        },
    )
    tailer._track_posted_event(
        metrics,
        {
            "kind": "tool",
            "payload": {
                "tool_name": "Bash",
                "tool_result": "output",
                "is_error": False,
                "tool_result_truncated": True,
            },
        },
    )

    assert metrics["events_posted"] == 2
    assert metrics["tool_events"] == 2
    assert metrics["tool_calls"] == 1
    assert metrics["tool_results"] == 1
    assert metrics["tool_result_truncated"] == 1


def test_fidelity_derived_ratios():
    metrics = {
        "rows_seen": 10,
        "rows_skipped_filter": 2,
        "events_posted": 8,
        "tool_events": 4,
        "tool_calls": 3,
        "tool_results": 2,
        "tool_result_truncated": 1,
    }
    out = tailer._fidelity_derived(metrics)
    assert out["workflow_event_ratio"] == 0.5
    assert out["tool_result_capture_rate"] == round(2 / 3, 4)
    assert out["truncated_tool_result_ratio"] == 0.5
    assert out["skipped_by_filter_ratio"] == 0.2
    assert out["mode_shadow_ratio"] == 0.0


def test_scan_hook_events_updates_telemetry(tmp_path, monkeypatch):
    spool = tmp_path / "openclaw_hook_events.jsonl"
    spool.parent.mkdir(parents=True, exist_ok=True)
    with spool.open("w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "hook": "llm_input",
                    "ts": 1000.0,
                    "run_id": "r-1",
                    "session_id": "s-1",
                    "provider": "openai",
                    "model": "gpt-5",
                    "prompt": "abc",
                    "history_messages": [],
                }
            )
            + "\n"
        )
        f.write(json.dumps({"hook": "something_else", "ts": 1002.0}) + "\n")
        f.write("{not-json\n")

    posted = []

    def _fake_post(url, payload, token=None):
        posted.append((url, payload, token))

    monkeypatch.setattr(tailer, "_post_json", _fake_post)
    state = tailer.SessionState(tmp_path / "state.json")
    metrics = tailer._new_fidelity_metrics()

    assert (
        tailer._scan_hook_events(
            spool,
            state,
            "http://127.0.0.1:8787",
            max_per_tick=50,
            backfill=True,
            telemetry=metrics,
        )
        == 0
    )
    assert (
        tailer._scan_hook_events(
            spool,
            state,
            "http://127.0.0.1:8787",
            max_per_tick=50,
            backfill=True,
            telemetry=metrics,
        )
        == 3
    )
    assert len(posted) == 1
    assert metrics["hook_rows_seen"] == 3
    assert metrics["hook_rows_ignored"] == 1
    assert metrics["hook_json_decode_errors"] == 1
    assert metrics["hook_events_posted"] == 1
    assert metrics["events_posted"] == 1
