import json
from pathlib import Path

from hooks import observe
from lib.queue import EventType


def test_has_truncated_tool_input_fields():
    assert observe._has_truncated_tool_input_fields(None) is False
    assert observe._has_truncated_tool_input_fields({"cmd": "ls"}) is False
    assert observe._has_truncated_tool_input_fields({"cmd_truncated": True}) is True


def test_build_observe_telemetry_row_marks_workflow_fields():
    row = observe._build_observe_telemetry_row(
        session_id="s-1",
        source="claude_code",
        hook_event="PostToolUse",
        event_type=EventType.POST_TOOL,
        tool_name="Read",
        payload_truncated=True,
        tool_input_truncated=False,
        tool_result_captured=True,
        tool_result_truncated=False,
        captured=True,
    )
    assert row["adapter"] == "observe_hook"
    assert row["workflow_event"] is True
    assert row["tool_result_event"] is True
    assert row["payload_truncated"] is True
    assert row["tool_result_captured"] is True
    assert row["capture_ok"] is True


def test_emit_observe_telemetry_writes_jsonl(tmp_path, monkeypatch):
    telemetry_file = tmp_path / "observe_hook_telemetry.jsonl"
    monkeypatch.setattr(observe, "OBSERVE_TELEMETRY_ENABLED", True)
    row = observe._build_observe_telemetry_row(
        session_id="s-2",
        source="claude_code",
        hook_event="PreToolUse",
        event_type=EventType.PRE_TOOL,
        tool_name="Edit",
        payload_truncated=False,
        tool_input_truncated=True,
        tool_result_captured=False,
        tool_result_truncated=False,
        captured=True,
    )
    observe._emit_observe_telemetry(row, telemetry_file=telemetry_file)
    lines = telemetry_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["hook_event"] == "PreToolUse"
    assert payload["tool_input_truncated"] is True


def test_persist_tool_result_reference(tmp_path, monkeypatch):
    monkeypatch.setattr(observe, "CLAUDE_TOOL_RESULT_REF_DIR", tmp_path / "refs")
    out = observe._persist_tool_result_reference("large output text")
    assert out is not None
    assert out["tool_result_hash"]
    ref_path = Path(out["tool_result_ref"])
    assert ref_path.exists()
    assert ref_path.read_text(encoding="utf-8") == "large output text"


def test_workflow_summary_state_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr(observe, "CLAUDE_WORKFLOW_SUMMARY_DIR", tmp_path / "workflow")
    monkeypatch.setattr(observe, "CLAUDE_WORKFLOW_SUMMARY_STATE_DIR", tmp_path / "workflow" / "_state")
    monkeypatch.setattr(observe, "CLAUDE_WORKFLOW_SUMMARY_MIN_INTERVAL_S", 0)

    session_id = "session-abc"
    observe._update_workflow_summary_state(
        session_id,
        hook_event="PreToolUse",
        tool_name="Read",
        tool_input={"file_path": "README.md"},
        ts=1000.0,
    )
    observe._update_workflow_summary_state(
        session_id,
        hook_event="PostToolUseFailure",
        tool_name="Bash",
        tool_input={"cwd": "C:/repo"},
        ts=1001.0,
    )
    observe._update_workflow_summary_state(
        session_id,
        hook_event="PostToolUse",
        tool_name="Bash",
        tool_input={"cwd": "C:/repo"},
        ts=1002.0,
    )
    out = observe._write_workflow_summary_report_if_due(session_id)
    assert out is not None
    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    assert payload["provider"] == "claude"
    assert payload["tool_events"] == 3
    assert payload["tool_calls"] == 1
    assert payload["tool_results"] == 2
    assert payload["tool_failures"] == 1
    assert payload["tool_successes"] == 1
    assert payload["recovery_tools"] == ["Bash"]
