from __future__ import annotations

import json
from pathlib import Path

from adapters import openclaw_tailer as tailer


def test_scan_reports_recurses_workflow_subdir(tmp_path, monkeypatch):
    report_dir = tmp_path / "spark_reports"
    workflow_dir = report_dir / "workflow"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    report_file = workflow_dir / "workflow_sample.json"
    report_file.write_text(
        json.dumps(
            {
                "kind": "workflow_summary",
                "ts": 1000.0,
                "session_key": "session-1",
                "tool_events": 3,
            }
        ),
        encoding="utf-8",
    )

    posted = []

    def _fake_post(url, payload, token=None):
        posted.append((url, payload, token))

    monkeypatch.setattr(tailer, "_post_json", _fake_post)

    count = tailer._scan_reports(report_dir, "http://127.0.0.1:8787")
    assert count == 1
    assert len(posted) == 1
    payload = posted[0][1]["payload"]
    assert payload["type"] == "self_report"
    assert payload["report_kind"] == "workflow_summary"
    assert str(payload.get("report_path") or "").replace("\\", "/").endswith("workflow/workflow_sample.json")
    assert not report_file.exists()
    assert (workflow_dir / ".processed" / "workflow_sample.json").exists()


def test_tool_result_payload_persists_reference_for_large_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(tailer, "MAX_TOOL_RESULT_CHARS", 10)
    monkeypatch.setattr(tailer, "TOOL_RESULT_REF_DIR", tmp_path / "refs")

    payload = tailer._build_tool_result_payload(
        {"toolName": "Bash", "toolCallId": "call-1", "isError": True},
        "abcdefghijklmnop",
    )

    assert payload["tool_result_truncated"] is True
    assert payload["tool_result_chars"] == 16
    assert payload["tool_result_hash"]
    assert payload["tool_result_ref"]
    ref_path = Path(payload["tool_result_ref"])
    assert ref_path.exists()
    assert ref_path.read_text(encoding="utf-8") == "abcdefghijklmnop"


def test_workflow_summary_materializes_recovery_and_paths():
    summary = tailer._new_workflow_summary("session-1", Path("s.jsonl"))
    events = [
        {
            "kind": "tool",
            "ts": 10.0,
            "payload": {
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
            },
        },
        {
            "kind": "tool",
            "ts": 11.0,
            "payload": {
                "tool_name": "Bash",
                "tool_input": {"cwd": "C:/repo"},
                "tool_result": "failed",
                "is_error": True,
            },
        },
        {
            "kind": "tool",
            "ts": 12.0,
            "payload": {
                "tool_name": "Bash",
                "tool_input": {"cwd": "C:/repo"},
                "tool_result": "ok",
                "is_error": False,
            },
        },
    ]
    tailer._accumulate_workflow_summary(summary, events)
    summary["rows_processed"] = 3

    out = tailer._materialize_workflow_summary(summary, ts=1234.0)
    assert out is not None
    assert out["tool_events"] == 3
    assert out["tool_calls"] == 1
    assert out["tool_results"] == 2
    assert out["tool_failures"] == 1
    assert out["tool_successes"] == 1
    assert out["recovery_tools"] == ["Bash"]
    assert "README.md" in out["files_touched"]
    assert "C:/repo" in out["files_touched"]
    assert out["outcome_confidence"] == 0.5
