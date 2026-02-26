import importlib.util
import json
import sys
from pathlib import Path

import pytest


_BRIDGE_PATH = Path(__file__).resolve().parents[1] / "adapters" / "codex_hook_bridge.py"
_SPEC = importlib.util.spec_from_file_location("codex_hook_bridge", _BRIDGE_PATH)
bridge = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules[_SPEC.name] = bridge
_SPEC.loader.exec_module(bridge)


def test_map_function_call_and_output_pairing_success():
    runtime = bridge.BridgeRuntime()
    session_id = "2026:02:26:session-abc"

    ctx_row = {
        "timestamp": "2026-02-26T12:00:00.000Z",
        "type": "turn_context",
        "payload": {"cwd": "C:\\repo"},
    }
    assert bridge.map_codex_row(ctx_row, session_id=session_id, runtime=runtime) == []

    pre_row = {
        "timestamp": "2026-02-26T12:00:01.000Z",
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "exec_command",
            "call_id": "call_1",
            "arguments": json.dumps({"cmd": "rg -n foo ."}),
        },
    }
    pre_events = bridge.map_codex_row(pre_row, session_id=session_id, runtime=runtime)
    assert len(pre_events) == 1
    pre = pre_events[0]
    assert pre["hook_event_name"] == "PreToolUse"
    assert pre["tool_name"] == "exec_command"
    assert pre["tool_input"]["cmd"] == "rg -n foo ."
    assert pre["cwd"] == "C:\\repo"

    post_row = {
        "timestamp": "2026-02-26T12:00:02.000Z",
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "Process exited with code 0\nOutput:\nok",
        },
    }
    post_events = bridge.map_codex_row(post_row, session_id=session_id, runtime=runtime)
    assert len(post_events) == 1
    post = post_events[0]
    assert post["hook_event_name"] == "PostToolUse"
    assert post["tool_name"] == "exec_command"
    assert post["trace_id"] == pre["trace_id"]


def test_map_function_call_output_failure():
    runtime = bridge.BridgeRuntime()
    session_id = "2026:02:26:session-def"

    bridge.map_codex_row(
        {
            "timestamp": "2026-02-26T12:10:00.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "call_id": "call_2",
                "arguments": json.dumps({"cmd": "false"}),
            },
        },
        session_id=session_id,
        runtime=runtime,
    )
    events = bridge.map_codex_row(
        {
            "timestamp": "2026-02-26T12:10:01.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_2",
                "output": "Process exited with code 1\nstderr...",
            },
        },
        session_id=session_id,
        runtime=runtime,
    )
    assert len(events) == 1
    evt = events[0]
    assert evt["hook_event_name"] == "PostToolUseFailure"
    assert evt["tool_name"] == "exec_command"
    assert "stderr" in evt["tool_error"]


def test_map_custom_tool_output_exit_code():
    runtime = bridge.BridgeRuntime()
    session_id = "2026:02:26:session-ghi"

    bridge.map_codex_row(
        {
            "timestamp": "2026-02-26T12:20:00.000Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "apply_patch",
                "call_id": "call_3",
                "input": "*** Begin Patch\n*** End Patch\n",
            },
        },
        session_id=session_id,
        runtime=runtime,
    )
    events = bridge.map_codex_row(
        {
            "timestamp": "2026-02-26T12:20:01.000Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call_3",
                "output": json.dumps({"output": "failed", "metadata": {"exit_code": 2}}),
            },
        },
        session_id=session_id,
        runtime=runtime,
    )
    assert len(events) == 1
    evt = events[0]
    assert evt["hook_event_name"] == "PostToolUseFailure"
    assert evt["tool_name"] == "apply_patch"


def test_map_user_message_and_stop():
    runtime = bridge.BridgeRuntime()
    session_id = "2026:02:26:session-jkl"

    prompt_events = bridge.map_codex_row(
        {
            "timestamp": "2026-02-26T12:30:00.000Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "please run tests"},
        },
        session_id=session_id,
        runtime=runtime,
    )
    assert len(prompt_events) == 1
    assert prompt_events[0]["hook_event_name"] == "UserPromptSubmit"
    assert prompt_events[0]["prompt"] == "please run tests"

    stop_events = bridge.map_codex_row(
        {
            "timestamp": "2026-02-26T12:31:00.000Z",
            "type": "event_msg",
            "payload": {"type": "task_complete"},
        },
        session_id=session_id,
        runtime=runtime,
    )
    assert len(stop_events) == 1
    assert stop_events[0]["hook_event_name"] == "Stop"


def test_pending_call_pairing_is_session_scoped():
    runtime = bridge.BridgeRuntime()
    session_a = "2026:02:26:session-a"
    session_b = "2026:02:26:session-b"

    for session_id, cmd in ((session_a, "echo a"), (session_b, "echo b")):
        bridge.map_codex_row(
            {
                "timestamp": "2026-02-26T12:40:00.000Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call_shared",
                    "arguments": json.dumps({"cmd": cmd}),
                },
            },
            session_id=session_id,
            runtime=runtime,
        )

    post_a = bridge.map_codex_row(
        {
            "timestamp": "2026-02-26T12:40:01.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_shared",
                "output": "Process exited with code 0\nok",
            },
        },
        session_id=session_a,
        runtime=runtime,
    )[0]
    post_b = bridge.map_codex_row(
        {
            "timestamp": "2026-02-26T12:40:02.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_shared",
                "output": "Process exited with code 0\nok",
            },
        },
        session_id=session_b,
        runtime=runtime,
    )[0]

    assert post_a["tool_input"]["cmd"] == "echo a"
    assert post_b["tool_input"]["cmd"] == "echo b"
    assert runtime.metrics.post_unmatched_call_id == 0


def test_singleton_lock_replaces_stale_owner(tmp_path, monkeypatch):
    lock_file = tmp_path / "bridge.lock"
    lock_file.write_text(json.dumps({"pid": 4567, "mode": "shadow"}), encoding="utf-8")

    monkeypatch.setattr(bridge, "_is_pid_running", lambda pid: False)
    monkeypatch.setattr(bridge.os, "getpid", lambda: 2222)

    bridge._acquire_singleton_lock(lock_file, mode="observe")
    payload = json.loads(lock_file.read_text(encoding="utf-8"))
    assert payload["pid"] == 2222
    assert payload["mode"] == "observe"

    bridge._release_singleton_lock(lock_file)
    assert not lock_file.exists()


def test_singleton_lock_blocks_active_owner(tmp_path, monkeypatch):
    lock_file = tmp_path / "bridge.lock"
    lock_file.write_text(json.dumps({"pid": 9999, "mode": "observe"}), encoding="utf-8")

    monkeypatch.setattr(bridge.os, "getpid", lambda: 1111)
    monkeypatch.setattr(bridge, "_is_pid_running", lambda pid: pid == 9999)

    with pytest.raises(SystemExit):
        bridge._acquire_singleton_lock(lock_file, mode="shadow")


def test_telemetry_snapshot_includes_forwarding_flags(tmp_path):
    telemetry_file = tmp_path / "telemetry.jsonl"
    runtime = bridge.BridgeRuntime()

    bridge._write_telemetry_snapshot(
        telemetry_file=telemetry_file,
        mode="observe",
        runtime=runtime,
        active_files=3,
        observe_forwarding_enabled=True,
        shadow_mode_warning_emitted=False,
        environment="dev",
        shadow_in_production=False,
    )

    rows = telemetry_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["mode"] == "observe"
    assert payload["observe_forwarding_enabled"] is True
    assert payload["shadow_mode_warning_emitted"] is False
    assert payload["environment"] == "dev"
    assert payload["shadow_in_production"] is False


def test_emit_shadow_mode_warning_writes_event(tmp_path):
    telemetry_file = tmp_path / "telemetry.jsonl"

    bridge._emit_shadow_mode_warning(
        telemetry_file=telemetry_file,
        sessions_root=Path.home() / ".codex" / "sessions",
    )

    rows = telemetry_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["event"] == "startup_warning"
    assert payload["warning_code"] == "shadow_mode_active"
    assert payload["observe_forwarding_enabled"] is False
    assert payload["environment"] == "dev"
    assert payload["shadow_in_production"] is False


def test_emit_shadow_mode_warning_marks_production(tmp_path):
    telemetry_file = tmp_path / "telemetry.jsonl"

    bridge._emit_shadow_mode_warning(
        telemetry_file=telemetry_file,
        sessions_root=Path.home() / ".codex" / "sessions",
        environment="production",
        warning_code="shadow_mode_in_production",
    )

    rows = telemetry_file.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(rows[0])
    assert payload["warning_code"] == "shadow_mode_in_production"
    assert payload["environment"] == "production"
    assert payload["shadow_in_production"] is True


def test_map_truncation_metrics_increment(monkeypatch):
    monkeypatch.setattr(bridge, "HOOK_INPUT_TEXT_LIMIT", 5)
    monkeypatch.setattr(bridge, "HOOK_OUTPUT_TEXT_LIMIT", 5)
    runtime = bridge.BridgeRuntime()
    session_id = "2026:02:26:session-trunc"

    bridge.map_codex_row(
        {
            "timestamp": "2026-02-26T13:00:00.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "call_id": "call_1",
                "arguments": json.dumps({"cmd": "very-long-command"}),
            },
        },
        session_id=session_id,
        runtime=runtime,
    )
    bridge.map_codex_row(
        {
            "timestamp": "2026-02-26T13:00:01.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "Process exited with code 0\nthis output is very long",
            },
        },
        session_id=session_id,
        runtime=runtime,
    )
    assert runtime.metrics.pre_input_truncated == 1
    assert runtime.metrics.post_output_truncated == 1
