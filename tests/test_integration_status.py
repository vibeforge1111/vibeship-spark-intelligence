"""Tests for lib/integration_status.py."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.integration_status as ist
from lib.integration_status import (
    _codex_sync_enabled,
    check_advice_log_growing,
    check_codex_sync_outputs,
    check_effectiveness,
    check_pre_tool_events,
    check_recent_events,
    check_settings_json,
    get_full_status,
)


# ---------------------------------------------------------------------------
# check_settings_json
# ---------------------------------------------------------------------------

def _write_settings(path: Path, hooks: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"hooks": hooks}), encoding="utf-8")


def _valid_hook_entry(py_path="/opt/spark/hooks/observe.py"):
    return [{"matcher": "", "hooks": [{"type": "command", "command": f"python {py_path}"}]}]


def test_check_settings_json_missing_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(ist, "SETTINGS_FILE", tmp_path / "no_settings.json")
    ok, msg = check_settings_json()
    assert ok is False
    assert "Missing" in msg


def test_check_settings_json_missing_hooks_returns_false(monkeypatch, tmp_path):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(ist, "SETTINGS_FILE", f)
    ok, msg = check_settings_json()
    assert ok is False


def test_check_settings_json_missing_required_hook_type(monkeypatch, tmp_path):
    f = tmp_path / "settings.json"
    hooks = {
        "PreToolUse": _valid_hook_entry(),
        "PostToolUse": _valid_hook_entry(),
        # PostToolUseFailure missing
    }
    _write_settings(f, hooks)
    monkeypatch.setattr(ist, "SETTINGS_FILE", f)
    ok, msg = check_settings_json()
    assert ok is False
    assert "PostToolUseFailure" in msg


def test_check_settings_json_missing_observe_py(monkeypatch, tmp_path):
    f = tmp_path / "settings.json"
    hooks = {
        "PreToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": "python other.py"}]}],
        "PostToolUse": _valid_hook_entry(),
        "PostToolUseFailure": _valid_hook_entry(),
    }
    _write_settings(f, hooks)
    monkeypatch.setattr(ist, "SETTINGS_FILE", f)
    ok, msg = check_settings_json()
    assert ok is False
    assert "observe.py" in msg


def test_check_settings_json_valid_returns_true(monkeypatch, tmp_path):
    f = tmp_path / "settings.json"
    hooks = {
        "PreToolUse": _valid_hook_entry(),
        "PostToolUse": _valid_hook_entry(),
        "PostToolUseFailure": _valid_hook_entry(),
    }
    _write_settings(f, hooks)
    monkeypatch.setattr(ist, "SETTINGS_FILE", f)
    ok, msg = check_settings_json()
    assert ok is True
    assert "correctly" in msg.lower()


def test_check_settings_json_invalid_json(monkeypatch, tmp_path):
    f = tmp_path / "settings.json"
    f.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(ist, "SETTINGS_FILE", f)
    ok, _ = check_settings_json()
    assert ok is False


# ---------------------------------------------------------------------------
# check_recent_events
# ---------------------------------------------------------------------------

def _write_events(path: Path, events: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def test_check_recent_events_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(ist, "EVENTS_FILE", tmp_path / "no_events.jsonl")
    ok, _ = check_recent_events(60)
    assert ok is False


def test_check_recent_events_empty_file(monkeypatch, tmp_path):
    f = tmp_path / "events.jsonl"
    f.write_text("", encoding="utf-8")
    monkeypatch.setattr(ist, "EVENTS_FILE", f)
    ok, _ = check_recent_events(60)
    assert ok is False


def test_check_recent_events_recent_event_returns_true(monkeypatch, tmp_path):
    f = tmp_path / "events.jsonl"
    _write_events(f, [{"timestamp": time.time(), "event_type": "pre_tool"}])
    monkeypatch.setattr(ist, "EVENTS_FILE", f)
    ok, msg = check_recent_events(60)
    assert ok is True
    assert "1" in msg


def test_check_recent_events_stale_event_returns_false(monkeypatch, tmp_path):
    f = tmp_path / "events.jsonl"
    old_ts = time.time() - 7200  # 2h ago
    _write_events(f, [{"timestamp": old_ts}])
    monkeypatch.setattr(ist, "EVENTS_FILE", f)
    ok, _ = check_recent_events(60)
    assert ok is False


def test_check_recent_events_counts_recent_only(monkeypatch, tmp_path):
    f = tmp_path / "events.jsonl"
    events = [
        {"timestamp": time.time()},          # recent
        {"timestamp": time.time() - 7200},   # stale
    ]
    _write_events(f, events)
    monkeypatch.setattr(ist, "EVENTS_FILE", f)
    ok, msg = check_recent_events(60)
    assert ok is True
    assert "1" in msg


def test_check_recent_events_ts_field_also_works(monkeypatch, tmp_path):
    f = tmp_path / "events.jsonl"
    _write_events(f, [{"ts": time.time()}])
    monkeypatch.setattr(ist, "EVENTS_FILE", f)
    ok, _ = check_recent_events(60)
    assert ok is True


def test_check_recent_events_bad_json_lines_skipped(monkeypatch, tmp_path):
    f = tmp_path / "events.jsonl"
    f.write_text('{"timestamp": ' + str(time.time()) + "}\nnot json\n", encoding="utf-8")
    monkeypatch.setattr(ist, "EVENTS_FILE", f)
    ok, _ = check_recent_events(60)
    assert ok is True


# ---------------------------------------------------------------------------
# check_advice_log_growing
# ---------------------------------------------------------------------------

def test_check_advice_log_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(ist, "ADVICE_LOG", tmp_path / "no_advice.jsonl")
    monkeypatch.setattr(ist, "RECENT_ADVICE", tmp_path / "no_recent.jsonl")
    ok, _ = check_advice_log_growing()
    assert ok is False


def test_check_advice_log_fresh_file(monkeypatch, tmp_path):
    f = tmp_path / "advice.jsonl"
    f.write_text('{"advice": "test"}\n', encoding="utf-8")
    monkeypatch.setattr(ist, "ADVICE_LOG", f)
    monkeypatch.setattr(ist, "RECENT_ADVICE", tmp_path / "no_recent.jsonl")
    ok, _ = check_advice_log_growing()
    assert ok is True


def test_check_advice_log_stale_file(monkeypatch, tmp_path):
    import os
    f = tmp_path / "advice.jsonl"
    f.write_text('{"advice": "test"}\n', encoding="utf-8")
    old_time = time.time() - 90000  # > 24h ago
    os.utime(f, (old_time, old_time))
    monkeypatch.setattr(ist, "ADVICE_LOG", f)
    monkeypatch.setattr(ist, "RECENT_ADVICE", tmp_path / "no_recent.jsonl")
    ok, _ = check_advice_log_growing()
    assert ok is False


def test_check_advice_log_prefers_recent_advice(monkeypatch, tmp_path):
    advice = tmp_path / "advice.jsonl"
    recent = tmp_path / "recent.jsonl"
    recent.write_text('{"advice": "recent"}\n', encoding="utf-8")
    monkeypatch.setattr(ist, "ADVICE_LOG", advice)
    monkeypatch.setattr(ist, "RECENT_ADVICE", recent)
    ok, _ = check_advice_log_growing()
    assert ok is True


# ---------------------------------------------------------------------------
# check_effectiveness
# ---------------------------------------------------------------------------

def _write_effectiveness(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_check_effectiveness_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(ist, "EFFECTIVENESS", tmp_path / "no_eff.json")
    ok, _ = check_effectiveness()
    assert ok is False


def test_check_effectiveness_zero_advice(monkeypatch, tmp_path):
    f = tmp_path / "effectiveness.json"
    _write_effectiveness(f, {"total_advice_given": 0})
    monkeypatch.setattr(ist, "EFFECTIVENESS", f)
    ok, _ = check_effectiveness()
    assert ok is False


def test_check_effectiveness_valid_counters(monkeypatch, tmp_path):
    f = tmp_path / "effectiveness.json"
    _write_effectiveness(f, {"total_advice_given": 100, "total_followed": 40, "total_helpful": 30})
    monkeypatch.setattr(ist, "EFFECTIVENESS", f)
    ok, msg = check_effectiveness()
    assert ok is True
    assert "40/100" in msg


def test_check_effectiveness_followed_exceeds_total(monkeypatch, tmp_path):
    f = tmp_path / "effectiveness.json"
    _write_effectiveness(f, {"total_advice_given": 10, "total_followed": 20, "total_helpful": 5})
    monkeypatch.setattr(ist, "EFFECTIVENESS", f)
    ok, _ = check_effectiveness()
    assert ok is False


def test_check_effectiveness_helpful_exceeds_followed(monkeypatch, tmp_path):
    f = tmp_path / "effectiveness.json"
    _write_effectiveness(f, {"total_advice_given": 100, "total_followed": 30, "total_helpful": 50})
    monkeypatch.setattr(ist, "EFFECTIVENESS", f)
    ok, _ = check_effectiveness()
    assert ok is False


def test_check_effectiveness_zero_followed_high_total(monkeypatch, tmp_path):
    f = tmp_path / "effectiveness.json"
    _write_effectiveness(f, {"total_advice_given": 200, "total_followed": 0, "total_helpful": 0})
    monkeypatch.setattr(ist, "EFFECTIVENESS", f)
    ok, msg = check_effectiveness()
    assert ok is False
    assert "broken" in msg.lower() or "outcome" in msg.lower()


# ---------------------------------------------------------------------------
# _codex_sync_enabled
# ---------------------------------------------------------------------------

def test_codex_sync_enabled_via_spark_codex_cmd(monkeypatch):
    monkeypatch.setenv("SPARK_CODEX_CMD", "codex")
    monkeypatch.delenv("CODEX_CMD", raising=False)
    monkeypatch.delenv("SPARK_SYNC_TARGETS", raising=False)
    assert _codex_sync_enabled() is True


def test_codex_sync_enabled_via_codex_cmd(monkeypatch):
    monkeypatch.delenv("SPARK_CODEX_CMD", raising=False)
    monkeypatch.setenv("CODEX_CMD", "codex")
    monkeypatch.delenv("SPARK_SYNC_TARGETS", raising=False)
    assert _codex_sync_enabled() is True


def test_codex_sync_enabled_via_sync_targets(monkeypatch):
    monkeypatch.delenv("SPARK_CODEX_CMD", raising=False)
    monkeypatch.delenv("CODEX_CMD", raising=False)
    monkeypatch.setenv("SPARK_SYNC_TARGETS", "cursor,codex")
    assert _codex_sync_enabled() is True


def test_codex_sync_not_enabled_without_env(monkeypatch):
    monkeypatch.delenv("SPARK_CODEX_CMD", raising=False)
    monkeypatch.delenv("CODEX_CMD", raising=False)
    monkeypatch.delenv("SPARK_SYNC_TARGETS", raising=False)
    assert _codex_sync_enabled() is False


def test_codex_sync_not_enabled_wrong_targets(monkeypatch):
    monkeypatch.delenv("SPARK_CODEX_CMD", raising=False)
    monkeypatch.delenv("CODEX_CMD", raising=False)
    monkeypatch.setenv("SPARK_SYNC_TARGETS", "cursor,windsurf")
    assert _codex_sync_enabled() is False


# ---------------------------------------------------------------------------
# check_codex_sync_outputs
# ---------------------------------------------------------------------------

def test_check_codex_sync_not_configured_returns_true(monkeypatch):
    monkeypatch.setattr(ist, "_codex_sync_enabled", lambda: False)
    ok, msg = check_codex_sync_outputs()
    assert ok is True
    assert "not configured" in msg.lower()


def test_check_codex_sync_missing_both_files(monkeypatch, tmp_path):
    monkeypatch.setattr(ist, "_codex_sync_enabled", lambda: True)
    monkeypatch.setattr(ist, "CODEX_CONTEXT_FILE", tmp_path / "no_context.md")
    monkeypatch.setattr(ist, "CODEX_PAYLOAD_FILE", tmp_path / "no_payload.json")
    # Patch Path.cwd to avoid filesystem interference
    monkeypatch.chdir(tmp_path)
    ok, _ = check_codex_sync_outputs()
    assert ok is False


def test_check_codex_sync_valid_files(monkeypatch, tmp_path):
    monkeypatch.setattr(ist, "_codex_sync_enabled", lambda: True)
    ctx = tmp_path / "SPARK_CONTEXT_FOR_CODEX.md"
    payload = tmp_path / "SPARK_ADVISORY_PAYLOAD.json"
    ctx.write_text("# Context", encoding="utf-8")
    payload.write_text(json.dumps({"schema_version": "v1"}), encoding="utf-8")
    monkeypatch.setattr(ist, "CODEX_CONTEXT_FILE", ctx)
    monkeypatch.setattr(ist, "CODEX_PAYLOAD_FILE", payload)
    monkeypatch.chdir(tmp_path)
    ok, msg = check_codex_sync_outputs()
    assert ok is True


# ---------------------------------------------------------------------------
# check_pre_tool_events
# ---------------------------------------------------------------------------

def test_check_pre_tool_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(ist, "EVENTS_FILE", tmp_path / "no_events.jsonl")
    ok, _ = check_pre_tool_events(60)
    assert ok is False


def test_check_pre_tool_both_types_present(monkeypatch, tmp_path):
    f = tmp_path / "events.jsonl"
    events = [
        {"timestamp": time.time(), "event_type": "pre_tool"},
        {"timestamp": time.time(), "event_type": "post_tool"},
    ]
    _write_events(f, events)
    monkeypatch.setattr(ist, "EVENTS_FILE", f)
    ok, msg = check_pre_tool_events(60)
    assert ok is True
    assert "pre_tool" in msg


def test_check_pre_tool_only_pre_returns_false(monkeypatch, tmp_path):
    f = tmp_path / "events.jsonl"
    _write_events(f, [{"timestamp": time.time(), "event_type": "pre_tool"}])
    monkeypatch.setattr(ist, "EVENTS_FILE", f)
    ok, _ = check_pre_tool_events(60)
    assert ok is False


def test_check_pre_tool_none_returns_false(monkeypatch, tmp_path):
    f = tmp_path / "events.jsonl"
    _write_events(f, [{"timestamp": time.time(), "event_type": "other"}])
    monkeypatch.setattr(ist, "EVENTS_FILE", f)
    ok, _ = check_pre_tool_events(60)
    assert ok is False


# ---------------------------------------------------------------------------
# get_full_status
# ---------------------------------------------------------------------------

def test_get_full_status_returns_dict(monkeypatch, tmp_path):
    # Patch all file paths to nonexistent → all checks fail → DEGRADED
    monkeypatch.setattr(ist, "SETTINGS_FILE", tmp_path / "s.json")
    monkeypatch.setattr(ist, "EVENTS_FILE", tmp_path / "e.jsonl")
    monkeypatch.setattr(ist, "ADVICE_LOG", tmp_path / "a.jsonl")
    monkeypatch.setattr(ist, "RECENT_ADVICE", tmp_path / "r.jsonl")
    monkeypatch.setattr(ist, "EFFECTIVENESS", tmp_path / "ef.json")
    monkeypatch.setattr(ist, "_codex_sync_enabled", lambda: False)
    monkeypatch.setattr(ist, "check_advisory_packet_store", lambda: (False, "no packets"))
    result = get_full_status()
    assert isinstance(result, dict)
    assert "status" in result
    assert "checks" in result
    assert "all_ok" in result


def test_get_full_status_degraded_when_checks_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(ist, "SETTINGS_FILE", tmp_path / "s.json")
    monkeypatch.setattr(ist, "EVENTS_FILE", tmp_path / "e.jsonl")
    monkeypatch.setattr(ist, "ADVICE_LOG", tmp_path / "a.jsonl")
    monkeypatch.setattr(ist, "RECENT_ADVICE", tmp_path / "r.jsonl")
    monkeypatch.setattr(ist, "EFFECTIVENESS", tmp_path / "ef.json")
    monkeypatch.setattr(ist, "_codex_sync_enabled", lambda: False)
    monkeypatch.setattr(ist, "check_advisory_packet_store", lambda: (False, "no packets"))
    result = get_full_status()
    assert result["status"] == "DEGRADED"
    assert result["all_ok"] is False


def test_get_full_status_checks_is_list(monkeypatch, tmp_path):
    monkeypatch.setattr(ist, "SETTINGS_FILE", tmp_path / "s.json")
    monkeypatch.setattr(ist, "EVENTS_FILE", tmp_path / "e.jsonl")
    monkeypatch.setattr(ist, "ADVICE_LOG", tmp_path / "a.jsonl")
    monkeypatch.setattr(ist, "RECENT_ADVICE", tmp_path / "r.jsonl")
    monkeypatch.setattr(ist, "EFFECTIVENESS", tmp_path / "ef.json")
    monkeypatch.setattr(ist, "_codex_sync_enabled", lambda: False)
    monkeypatch.setattr(ist, "check_advisory_packet_store", lambda: (False, "no packets"))
    result = get_full_status()
    assert isinstance(result["checks"], list)
    assert len(result["checks"]) > 0
