#!/usr/bin/env python3
"""Codex hook bridge: tail Codex session JSONL and synthesize hook events.

This adapter is designed for a staged rollout:
1) shadow mode (default): parse/map only and write stability telemetry
2) observe mode: forward mapped events into hooks/observe.py

It intentionally does not require Codex-native hooks.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


STATE_DIR = Path.home() / ".spark" / "adapters"
DEFAULT_STATE_FILE = STATE_DIR / "codex_hook_bridge_state.json"
DEFAULT_TELEMETRY_FILE = Path.home() / ".spark" / "logs" / "codex_hook_bridge_telemetry.jsonl"
DEFAULT_LOCK_FILE = STATE_DIR / "codex_hook_bridge.lock"
DEFAULT_CODEX_SESSIONS_ROOT = Path.home() / ".codex" / "sessions"
DEFAULT_OBSERVE_PATH = Path(__file__).resolve().parent.parent / "hooks" / "observe.py"
DEFAULT_WORKFLOW_REPORT_DIR = Path.home() / ".spark" / "workflow_reports" / "codex"
TOOL_RESULT_REF_DIR = Path.home() / ".spark" / "workflow_refs" / "codex_tool_results"


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        value = int(raw)
    except Exception:
        return int(default)
    return max(int(lo), min(int(hi), value))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    s = str(raw).strip().lower()
    if not s:
        return bool(default)
    return s in ("1", "true", "yes", "on")


def _is_production_environment(value: Any) -> bool:
    env = str(value or "").strip().lower()
    return env in ("prod", "production")


HOOK_INPUT_TEXT_LIMIT = _env_int("SPARK_CODEX_HOOK_INPUT_TEXT_LIMIT", 6000, 500, 50000)
HOOK_OUTPUT_TEXT_LIMIT = _env_int("SPARK_CODEX_HOOK_OUTPUT_TEXT_LIMIT", 12000, 500, 100000)
PENDING_CALL_TTL_S = 1800
WORKFLOW_SUMMARY_ENABLED = _env_bool("SPARK_CODEX_WORKFLOW_SUMMARY_ENABLED", True)
WORKFLOW_SUMMARY_MIN_INTERVAL_S = _env_int("SPARK_CODEX_WORKFLOW_SUMMARY_MIN_INTERVAL_S", 120, 10, 86400)


def _now() -> float:
    return time.time()


def _short_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()[:16]


def _parse_ts(raw: Any) -> float:
    if raw is None:
        return _now()
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value / 1000.0 if value > 2e10 else value
    if isinstance(raw, str):
        try:
            return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except Exception:
            return _now()
    return _now()


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _is_pid_running(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _acquire_singleton_lock(lock_file: Path, *, mode: str) -> None:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    my_pid = int(os.getpid())

    if lock_file.exists():
        owner: Dict[str, Any] = {}
        try:
            owner = json.loads(lock_file.read_text(encoding="utf-8"))
        except Exception:
            owner = {}
        owner_pid = owner.get("pid")
        try:
            owner_pid = int(owner_pid)
        except Exception:
            owner_pid = 0
        if owner_pid and owner_pid != my_pid and _is_pid_running(owner_pid):
            raise SystemExit(
                f"codex_hook_bridge already running (pid={owner_pid}) lock={lock_file}"
            )
        try:
            lock_file.unlink()
        except Exception:
            pass

    payload = {"pid": my_pid, "mode": str(mode), "ts": _now()}
    lock_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _release_singleton_lock(lock_file: Path) -> None:
    if not lock_file.exists():
        return
    my_pid = int(os.getpid())
    try:
        owner = json.loads(lock_file.read_text(encoding="utf-8"))
    except Exception:
        owner = {}
    owner_pid = owner.get("pid")
    try:
        owner_pid = int(owner_pid)
    except Exception:
        owner_pid = 0
    if owner_pid in (0, my_pid):
        try:
            lock_file.unlink()
        except Exception:
            pass


def _emit_shadow_mode_warning(
    *,
    telemetry_file: Path,
    sessions_root: Path,
    environment: str = "dev",
    warning_code: str = "shadow_mode_active",
) -> None:
    row = {
        "ts": _now(),
        "adapter": "codex_hook_bridge",
        "event": "startup_warning",
        "warning_code": str(warning_code or "shadow_mode_active"),
        "warning": "Bridge is running in shadow mode; events are not forwarded to hooks/observe.py",
        "mode": "shadow",
        "observe_forwarding_enabled": False,
        "sessions_root": str(sessions_root),
        "environment": str(environment or "dev"),
        "shadow_in_production": _is_production_environment(environment),
    }
    _append_jsonl(telemetry_file, row)


def _extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: List[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        if block_type in ("input_text", "output_text", "text"):
            txt = block.get("text")
            if isinstance(txt, str) and txt:
                parts.append(txt)
    return "\n".join(parts).strip()


def _truncate_text(value: str, limit: int) -> Dict[str, Any]:
    text = value if isinstance(value, str) else str(value)
    if len(text) <= limit:
        return {"text": text, "truncated": False, "len": len(text), "hash": None}
    return {
        "text": text[:limit],
        "truncated": True,
        "len": len(text),
        "hash": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
    }


def _persist_tool_result_reference(text: str, ref_dir: Path = TOOL_RESULT_REF_DIR) -> Dict[str, Any] | None:
    raw = str(text or "")
    if not raw:
        return None
    try:
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
        ref_dir.mkdir(parents=True, exist_ok=True)
        path = ref_dir / f"{digest}.txt"
        if not path.exists():
            path.write_text(raw, encoding="utf-8")
        return {"tool_result_hash": digest, "tool_result_ref": str(path)}
    except Exception:
        return None


def _extract_paths_from_tool_input(tool_input: Any) -> List[str]:
    if not isinstance(tool_input, dict):
        return []
    paths: List[str] = []
    direct_keys = ("file_path", "path", "cwd", "workdir", "directory", "target_path", "destination")
    for key in direct_keys:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(value.strip())
    list_value = tool_input.get("paths")
    if isinstance(list_value, list):
        for row in list_value:
            if isinstance(row, str) and row.strip():
                paths.append(row.strip())
    return paths


def _new_workflow_summary(session_id: str, session_file: Path) -> Dict[str, Any]:
    return {
        "session_id": str(session_id),
        "session_file": str(session_file),
        "rows_processed": 0,
        "event_count": 0,
        "tool_events": 0,
        "tool_calls": 0,
        "tool_results": 0,
        "tool_successes": 0,
        "tool_failures": 0,
        "tools": {},
        "files_touched": set(),
        "tool_failure_tools": set(),
        "tool_success_tools": set(),
        "window_start_ts": None,
        "window_end_ts": None,
    }


def _accumulate_workflow_summary(summary: Dict[str, Any], events: List[Dict[str, Any]]) -> None:
    if not isinstance(summary, dict) or not isinstance(events, list):
        return
    for evt in events:
        if not isinstance(evt, dict):
            continue
        summary["event_count"] += 1
        evt_ts = evt.get("ts")
        if isinstance(evt_ts, (int, float)):
            if summary["window_start_ts"] is None:
                summary["window_start_ts"] = float(evt_ts)
            summary["window_end_ts"] = float(evt_ts)

        if str(evt.get("hook_event_name") or "") not in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            continue

        summary["tool_events"] += 1
        tool_name = str(evt.get("tool_name") or "unknown_tool")
        tools = summary["tools"]
        tools[tool_name] = int(tools.get(tool_name, 0)) + 1

        for path in _extract_paths_from_tool_input(evt.get("tool_input")):
            summary["files_touched"].add(path)

        hook = str(evt.get("hook_event_name") or "")
        if hook == "PreToolUse":
            summary["tool_calls"] += 1
        elif hook == "PostToolUse":
            summary["tool_results"] += 1
            summary["tool_successes"] += 1
            summary["tool_success_tools"].add(tool_name)
        elif hook == "PostToolUseFailure":
            summary["tool_results"] += 1
            summary["tool_failures"] += 1
            summary["tool_failure_tools"].add(tool_name)


def _materialize_workflow_summary(summary: Dict[str, Any], *, ts: float) -> Dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None
    tool_events = int(summary.get("tool_events") or 0)
    if tool_events <= 0:
        return None
    tool_results = int(summary.get("tool_results") or 0)
    tool_successes = int(summary.get("tool_successes") or 0)
    confidence = 0.0
    if tool_results > 0:
        confidence = round(tool_successes / float(tool_results), 3)
    elif int(summary.get("tool_calls") or 0) > 0:
        confidence = 0.5

    tools = summary.get("tools") if isinstance(summary.get("tools"), dict) else {}
    top_tools = [
        {"tool_name": name, "count": int(count)}
        for name, count in sorted(tools.items(), key=lambda row: (-int(row[1]), row[0]))[:10]
    ]
    failures = summary.get("tool_failure_tools") if isinstance(summary.get("tool_failure_tools"), set) else set()
    successes = summary.get("tool_success_tools") if isinstance(summary.get("tool_success_tools"), set) else set()
    recovery_tools = sorted(failures.intersection(successes))
    files_touched = summary.get("files_touched") if isinstance(summary.get("files_touched"), set) else set()

    return {
        "kind": "workflow_summary",
        "provider": "codex",
        "ts": float(ts),
        "session_id": summary.get("session_id"),
        "session_file": summary.get("session_file"),
        "rows_processed": int(summary.get("rows_processed") or 0),
        "event_count": int(summary.get("event_count") or 0),
        "tool_events": int(summary.get("tool_events") or 0),
        "tool_calls": int(summary.get("tool_calls") or 0),
        "tool_results": int(summary.get("tool_results") or 0),
        "tool_successes": int(summary.get("tool_successes") or 0),
        "tool_failures": int(summary.get("tool_failures") or 0),
        "top_tools": top_tools,
        "files_touched": sorted(files_touched)[:50],
        "recovery_tools": recovery_tools,
        "outcome_confidence": confidence,
        "window_start_ts": summary.get("window_start_ts"),
        "window_end_ts": summary.get("window_end_ts"),
    }


def _write_workflow_summary_report(
    *,
    report_dir: Path,
    summary: Dict[str, Any],
    verbose: bool = False,
) -> Path | None:
    payload = _materialize_workflow_summary(summary, ts=_now())
    if not payload:
        return None
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        suffix = _short_hash(str(payload.get("session_id") or "session"))[:8]
        filename = f"workflow_{int(_now() * 1000)}_{suffix}.json"
        path = report_dir / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if verbose:
            print(f"[codex_hook_bridge] wrote workflow summary {path}", flush=True)
        return path
    except Exception as exc:
        if verbose:
            print(f"[codex_hook_bridge] workflow summary write failed: {exc}", flush=True)
        return None


def _normalize_tool_input(raw_input: Any) -> Dict[str, Any]:
    if isinstance(raw_input, dict):
        sanitized: Dict[str, Any] = {}
        for key, value in raw_input.items():
            if isinstance(value, str):
                txt = _truncate_text(value, HOOK_INPUT_TEXT_LIMIT)
                sanitized[key] = txt["text"]
                if txt["truncated"]:
                    sanitized[f"{key}_truncated"] = True
                    sanitized[f"{key}_len"] = txt["len"]
                    sanitized[f"{key}_hash"] = txt["hash"]
            else:
                sanitized[key] = value
        return sanitized
    if isinstance(raw_input, str):
        txt = _truncate_text(raw_input, HOOK_INPUT_TEXT_LIMIT)
        out = {"raw_input": txt["text"], "raw_input_len": txt["len"]}
        if txt["truncated"]:
            out["raw_input_truncated"] = True
            out["raw_input_hash"] = txt["hash"]
        return out
    return {"raw_input": str(raw_input)[:HOOK_INPUT_TEXT_LIMIT]}


def _parse_function_arguments(raw_args: Any) -> Dict[str, Any]:
    if isinstance(raw_args, dict):
        return raw_args
    if not isinstance(raw_args, str) or not raw_args.strip():
        return {}
    try:
        parsed = json.loads(raw_args)
        return parsed if isinstance(parsed, dict) else {"raw_arguments": raw_args}
    except Exception:
        return {"raw_arguments": raw_args}


def _parse_exit_code_from_output(output: str) -> Optional[int]:
    if not output:
        return None
    match = re.search(r"Process exited with code\s+(-?\d+)", output)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None
    return None


def _parse_custom_tool_output(payload_output: Any) -> tuple[str, Optional[int]]:
    if isinstance(payload_output, dict):
        text = str(payload_output.get("output") or "")
        metadata = payload_output.get("metadata") if isinstance(payload_output.get("metadata"), dict) else {}
        exit_code = metadata.get("exit_code")
        return text, int(exit_code) if isinstance(exit_code, int) else None

    if not isinstance(payload_output, str):
        return str(payload_output), None

    raw = payload_output
    try:
        parsed = json.loads(raw)
    except Exception:
        return raw, _parse_exit_code_from_output(raw)

    if isinstance(parsed, dict):
        text = str(parsed.get("output") or raw)
        metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
        exit_code = metadata.get("exit_code")
        if isinstance(exit_code, int):
            return text, exit_code
        return text, _parse_exit_code_from_output(text)
    return raw, _parse_exit_code_from_output(raw)


def _is_relevant_row(row: Dict[str, Any]) -> bool:
    row_type = str(row.get("type") or "")
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    payload_type = str(payload.get("type") or "")

    if row_type == "event_msg" and payload_type in ("user_message", "task_complete"):
        return True
    if row_type == "response_item" and payload_type in (
        "function_call",
        "function_call_output",
        "custom_tool_call",
        "custom_tool_call_output",
    ):
        return True
    return False


@dataclass
class PendingCall:
    session_id: str
    tool_name: str
    tool_input: Dict[str, Any]
    trace_id: str
    ts: float


@dataclass
class SessionContext:
    cwd: Optional[str] = None


@dataclass
class BridgeMetrics:
    rows_seen: int = 0
    json_decode_errors: int = 0
    relevant_rows: int = 0
    mapped_events: int = 0
    pre_events: int = 0
    post_events: int = 0
    post_success: int = 0
    post_failure: int = 0
    post_unknown_exit: int = 0
    post_unmatched_call_id: int = 0
    observe_calls: int = 0
    observe_success: int = 0
    observe_failures: int = 0
    pre_input_truncated: int = 0
    post_output_truncated: int = 0
    row_type_counts: Counter = field(default_factory=Counter)
    unknown_response_item_types: Counter = field(default_factory=Counter)
    unknown_event_msg_types: Counter = field(default_factory=Counter)
    hook_event_counts: Counter = field(default_factory=Counter)
    observe_latency_ms: List[float] = field(default_factory=list)

    def coverage_ratio(self) -> float:
        if self.relevant_rows <= 0:
            return 0.0
        return round(self.mapped_events / float(self.relevant_rows), 4)

    def pairing_ratio(self) -> float:
        if self.post_events <= 0:
            return 0.0
        matched = self.post_events - self.post_unmatched_call_id
        return round(max(0, matched) / float(self.post_events), 4)

    def observe_success_ratio(self) -> float:
        if self.observe_calls <= 0:
            return 0.0
        return round(self.observe_success / float(self.observe_calls), 4)

    def observe_latency_p95(self) -> float:
        if not self.observe_latency_ms:
            return 0.0
        values = sorted(self.observe_latency_ms)
        idx = min(len(values) - 1, int(0.95 * (len(values) - 1)))
        return round(values[idx], 2)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rows_seen": self.rows_seen,
            "json_decode_errors": self.json_decode_errors,
            "relevant_rows": self.relevant_rows,
            "mapped_events": self.mapped_events,
            "pre_events": self.pre_events,
            "post_events": self.post_events,
            "post_success": self.post_success,
            "post_failure": self.post_failure,
            "post_unknown_exit": self.post_unknown_exit,
            "post_unmatched_call_id": self.post_unmatched_call_id,
            "observe_calls": self.observe_calls,
            "observe_success": self.observe_success,
            "observe_failures": self.observe_failures,
            "pre_input_truncated": self.pre_input_truncated,
            "post_output_truncated": self.post_output_truncated,
            "coverage_ratio": self.coverage_ratio(),
            "pairing_ratio": self.pairing_ratio(),
            "observe_success_ratio": self.observe_success_ratio(),
            "observe_latency_p95_ms": self.observe_latency_p95(),
            "row_type_counts": dict(self.row_type_counts),
            "unknown_response_item_types": dict(self.unknown_response_item_types),
            "unknown_event_msg_types": dict(self.unknown_event_msg_types),
            "hook_event_counts": dict(self.hook_event_counts),
        }


@dataclass
class BridgeRuntime:
    unknown_exit_policy: str = "success"
    pending_calls: Dict[str, PendingCall] = field(default_factory=dict)
    session_contexts: Dict[str, SessionContext] = field(default_factory=dict)
    metrics: BridgeMetrics = field(default_factory=BridgeMetrics)

    def get_context(self, session_id: str) -> SessionContext:
        if session_id not in self.session_contexts:
            self.session_contexts[session_id] = SessionContext()
        return self.session_contexts[session_id]

    def prune_pending_calls(self, now_ts: Optional[float] = None) -> None:
        now_value = now_ts if now_ts is not None else _now()
        stale = [
            call_id
            for call_id, pending in self.pending_calls.items()
            if now_value - pending.ts > PENDING_CALL_TTL_S
        ]
        for call_id in stale:
            self.pending_calls.pop(call_id, None)


class OffsetState:
    def __init__(self, state_file: Path):
        self._path = state_file
        self._data: Dict[str, Any] = {"files": {}}
        if state_file.exists():
            try:
                self._data = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                self._data = {"files": {}}
        if "files" not in self._data or not isinstance(self._data["files"], dict):
            self._data = {"files": {}}

    def is_new_file(self, file_key: str) -> bool:
        return file_key not in self._data["files"]

    def get_offset(self, file_key: str) -> int:
        row = self._data["files"].get(file_key, {})
        return int(row.get("offset") or 0)

    def set_offset(self, file_key: str, offset: int) -> None:
        if file_key not in self._data["files"]:
            self._data["files"][file_key] = {}
        self._data["files"][file_key]["offset"] = int(offset)

    def register_file(self, file_key: str, offset: int) -> None:
        if file_key not in self._data["files"]:
            self._data["files"][file_key] = {"offset": int(offset)}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")


def _session_key(root: Path, session_file: Path) -> str:
    rel = session_file.relative_to(root).with_suffix("")
    return str(rel).replace("\\", ":").replace("/", ":")


def _pending_call_key(session_id: str, call_id: str) -> str:
    return f"{session_id}:{call_id}"


def discover_session_files(root: Path) -> List[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime)


def map_codex_row(
    row: Dict[str, Any],
    *,
    session_id: str,
    runtime: BridgeRuntime,
) -> List[Dict[str, Any]]:
    runtime.metrics.rows_seen += 1
    row_type = str(row.get("type") or "")
    runtime.metrics.row_type_counts[row_type] += 1

    if _is_relevant_row(row):
        runtime.metrics.relevant_rows += 1

    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    payload_type = str(payload.get("type") or "")
    ts = _parse_ts(row.get("timestamp") or row.get("ts"))

    ctx = runtime.get_context(session_id)
    if row_type == "turn_context":
        cwd = payload.get("cwd")
        if isinstance(cwd, str) and cwd.strip():
            ctx.cwd = cwd.strip()
        return []

    events: List[Dict[str, Any]] = []

    if row_type == "event_msg":
        if payload_type == "user_message":
            message = str(payload.get("message") or "").strip()
            if message:
                trace_id = _short_hash(f"user:{session_id}:{ts}:{message[:120]}")
                event = {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": session_id,
                    "source": "codex",
                    "trace_id": trace_id,
                    "prompt": message,
                }
                if ctx.cwd:
                    event["cwd"] = ctx.cwd
                events.append(event)
        elif payload_type == "task_complete":
            trace_id = _short_hash(f"stop:{session_id}:{ts}")
            event = {
                "hook_event_name": "Stop",
                "session_id": session_id,
                "source": "codex",
                "trace_id": trace_id,
            }
            if ctx.cwd:
                event["cwd"] = ctx.cwd
            events.append(event)
        else:
            runtime.metrics.unknown_event_msg_types[payload_type or ""] += 1

    elif row_type == "response_item":
        if payload_type in ("function_call", "custom_tool_call"):
            tool_name = str(payload.get("name") or "").strip()
            call_id = str(payload.get("call_id") or "")
            if not tool_name:
                return []

            if payload_type == "function_call":
                tool_input_raw = _parse_function_arguments(payload.get("arguments"))
            else:
                tool_input_raw = payload.get("input")
            tool_input = _normalize_tool_input(tool_input_raw)
            if any(str(k).endswith("_truncated") and bool(v) for k, v in tool_input.items()):
                runtime.metrics.pre_input_truncated += 1
            trace_id = _short_hash(f"pre:{session_id}:{call_id}:{tool_name}:{ts}")

            if call_id:
                runtime.pending_calls[_pending_call_key(session_id, call_id)] = PendingCall(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    trace_id=trace_id,
                    ts=ts,
                )

            event = {
                "hook_event_name": "PreToolUse",
                "session_id": session_id,
                "source": "codex",
                "trace_id": trace_id,
                "tool_name": tool_name,
                "tool_input": tool_input,
            }
            if ctx.cwd:
                event["cwd"] = ctx.cwd
            events.append(event)

        elif payload_type in ("function_call_output", "custom_tool_call_output"):
            call_id = str(payload.get("call_id") or "")
            pending_key = _pending_call_key(session_id, call_id) if call_id else ""
            pending = runtime.pending_calls.pop(pending_key, None) if pending_key else None
            if pending:
                tool_name = pending.tool_name
                tool_input = pending.tool_input
                trace_id = pending.trace_id
            else:
                runtime.metrics.post_unmatched_call_id += 1
                tool_name = "unknown_tool"
                tool_input = {}
                trace_id = _short_hash(f"post:{session_id}:{call_id}:{ts}")

            if payload_type == "function_call_output":
                output_text = str(payload.get("output") or "")
                exit_code = _parse_exit_code_from_output(output_text)
            else:
                output_text, exit_code = _parse_custom_tool_output(payload.get("output"))

            normalized_output = _truncate_text(output_text, HOOK_OUTPUT_TEXT_LIMIT)
            if bool(normalized_output.get("truncated")):
                runtime.metrics.post_output_truncated += 1
            result_ref: Dict[str, Any] = {}
            if bool(normalized_output.get("truncated")):
                persisted = _persist_tool_result_reference(output_text)
                if isinstance(persisted, dict):
                    result_ref = persisted
            is_failure = False
            unknown_exit = False

            if exit_code is None:
                unknown_exit = True
                if runtime.unknown_exit_policy == "failure":
                    is_failure = True
                elif runtime.unknown_exit_policy == "skip":
                    return []
                else:
                    is_failure = False
            else:
                is_failure = exit_code != 0

            if is_failure:
                event = {
                    "hook_event_name": "PostToolUseFailure",
                    "session_id": session_id,
                    "source": "codex",
                    "trace_id": trace_id,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "tool_error": normalized_output["text"],
                }
                if normalized_output.get("truncated"):
                    event["tool_error_truncated"] = True
                if normalized_output.get("len") is not None:
                    event["tool_error_len"] = int(normalized_output.get("len") or 0)
                if normalized_output.get("hash"):
                    event["tool_error_hash"] = normalized_output.get("hash")
                if result_ref:
                    event.update(result_ref)
            else:
                event = {
                    "hook_event_name": "PostToolUse",
                    "session_id": session_id,
                    "source": "codex",
                    "trace_id": trace_id,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "tool_result": normalized_output["text"],
                }
                if normalized_output.get("truncated"):
                    event["tool_result_truncated"] = True
                if normalized_output.get("len") is not None:
                    event["tool_result_len"] = int(normalized_output.get("len") or 0)
                if normalized_output.get("hash"):
                    event["tool_result_hash"] = normalized_output.get("hash")
                if result_ref:
                    event.update(result_ref)
            if ctx.cwd:
                event["cwd"] = ctx.cwd
            if unknown_exit:
                event["bridge_unknown_exit_code"] = True
            events.append(event)
        else:
            runtime.metrics.unknown_response_item_types[payload_type or ""] += 1

    for event in events:
        runtime.metrics.mapped_events += 1
        runtime.metrics.hook_event_counts[event["hook_event_name"]] += 1
        if event["hook_event_name"] == "PreToolUse":
            runtime.metrics.pre_events += 1
        elif event["hook_event_name"] in ("PostToolUse", "PostToolUseFailure"):
            runtime.metrics.post_events += 1
            if event["hook_event_name"] == "PostToolUse":
                runtime.metrics.post_success += 1
            else:
                runtime.metrics.post_failure += 1
            if event.get("bridge_unknown_exit_code"):
                runtime.metrics.post_unknown_exit += 1

    return events


def _invoke_observe(observe_path: Path, event: Dict[str, Any], timeout_s: float = 8.0) -> tuple[bool, float, str]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, str(observe_path)],
            input=json.dumps(event, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return False, elapsed_ms, f"invoke_error:{type(exc).__name__}:{exc}"

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if proc.returncode == 0:
        return True, elapsed_ms, proc.stderr.strip()
    return False, elapsed_ms, f"rc={proc.returncode} stderr={proc.stderr.strip()}"


def _write_telemetry_snapshot(
    *,
    telemetry_file: Path,
    mode: str,
    runtime: BridgeRuntime,
    active_files: int,
    observe_forwarding_enabled: bool,
    shadow_mode_warning_emitted: bool,
    environment: str,
    shadow_in_production: bool,
) -> None:
    row = {
        "ts": _now(),
        "adapter": "codex_hook_bridge",
        "mode": mode,
        "environment": str(environment or "dev"),
        "shadow_in_production": bool(shadow_in_production),
        "observe_forwarding_enabled": bool(observe_forwarding_enabled),
        "shadow_mode_warning_emitted": bool(shadow_mode_warning_emitted),
        "active_files": int(active_files),
        "pending_calls": len(runtime.pending_calls),
        "metrics": runtime.metrics.as_dict(),
    }
    _append_jsonl(telemetry_file, row)


def run_bridge(args: argparse.Namespace) -> int:
    sessions_root = Path(args.sessions_root).expanduser()
    state_file = Path(args.state_file).expanduser()
    telemetry_file = Path(args.telemetry_file).expanduser()
    observe_path = Path(args.observe_path).expanduser()
    lock_file = Path(args.lock_file).expanduser()
    workflow_report_dir = Path(args.workflow_report_dir).expanduser()

    if not sessions_root.exists():
        raise SystemExit(f"No Codex sessions root at {sessions_root}")

    state = OffsetState(state_file)
    runtime = BridgeRuntime(unknown_exit_policy=args.unknown_exit_policy)
    mode = str(args.mode or "shadow").strip().lower()
    if mode not in ("shadow", "observe"):
        raise SystemExit(f"Unsupported mode: {mode}")
    environment = str(args.environment or os.environ.get("SPARK_ENV") or "dev").strip().lower() or "dev"
    shadow_in_production = bool(mode == "shadow" and _is_production_environment(environment))
    observe_forwarding_enabled = mode == "observe"
    shadow_mode_warning_emitted = False
    workflow_summary_enabled = bool(WORKFLOW_SUMMARY_ENABLED and not bool(args.no_workflow_summary))
    workflow_summary_min_interval_s = max(
        10, min(86400, int(args.workflow_summary_min_interval_s or WORKFLOW_SUMMARY_MIN_INTERVAL_S))
    )
    workflow_last_emit_ts: Dict[str, float] = {}

    _acquire_singleton_lock(lock_file, mode=mode)
    try:
        if shadow_in_production:
            _emit_shadow_mode_warning(
                telemetry_file=telemetry_file,
                sessions_root=sessions_root,
                environment=environment,
                warning_code="shadow_mode_in_production",
            )
            shadow_mode_warning_emitted = True
            if args.verbose:
                print(
                    (
                        f"[codex_hook_bridge] WARNING: shadow mode in production "
                        f"(environment={environment}); observe forwarding disabled"
                    ),
                    flush=True,
                )
            if bool(args.fail_on_shadow_prod):
                raise SystemExit(
                    (
                        f"Refusing to run in shadow mode for production environment "
                        f"(environment={environment})"
                    )
                )
        elif mode == "shadow" and not args.once:
            _emit_shadow_mode_warning(
                telemetry_file=telemetry_file,
                sessions_root=sessions_root,
                environment=environment,
                warning_code="shadow_mode_active",
            )
            shadow_mode_warning_emitted = True
            if args.verbose:
                print(
                    "[codex_hook_bridge] WARNING: shadow mode active; observe forwarding disabled",
                    flush=True,
                )

        while True:
            files = discover_session_files(sessions_root)
            for session_file in files:
                file_key = str(session_file)
                try:
                    lines = session_file.read_text(encoding="utf-8").splitlines()
                except Exception:
                    continue

                if state.is_new_file(file_key):
                    initial_offset = 0 if args.backfill else len(lines)
                    state.register_file(file_key, initial_offset)
                    state.save()
                    if args.verbose:
                        print(f"[codex_hook_bridge] tracking {session_file} offset={initial_offset}", flush=True)
                    if not args.backfill:
                        continue

                off = state.get_offset(file_key)
                new_lines = lines[off:]
                if not new_lines:
                    continue

                session_id = _session_key(sessions_root, session_file)
                consumed = 0
                batch = new_lines[: max(1, int(args.max_per_tick))]
                workflow_summary = _new_workflow_summary(session_id, session_file)
                for line in batch:
                    consumed += 1
                    try:
                        row = json.loads(line)
                    except Exception:
                        runtime.metrics.json_decode_errors += 1
                        continue

                    events = map_codex_row(row, session_id=session_id, runtime=runtime)
                    if not events:
                        continue
                    _accumulate_workflow_summary(workflow_summary, events)

                    if mode == "observe":
                        for event in events:
                            runtime.metrics.observe_calls += 1
                            ok, elapsed_ms, err = _invoke_observe(observe_path, event, timeout_s=float(args.observe_timeout_s))
                            runtime.metrics.observe_latency_ms.append(elapsed_ms)
                            if ok:
                                runtime.metrics.observe_success += 1
                            else:
                                runtime.metrics.observe_failures += 1
                                if args.verbose:
                                    print(f"[codex_hook_bridge] observe failed: {err}", flush=True)

                state.set_offset(file_key, off + consumed)
                state.save()

                workflow_summary["rows_processed"] = int(consumed)
                if (
                    workflow_summary_enabled
                    and consumed > 0
                    and int(workflow_summary.get("tool_events") or 0) > 0
                ):
                    now_ts = _now()
                    last_emit = float(workflow_last_emit_ts.get(session_id) or 0.0)
                    if (now_ts - last_emit) >= float(workflow_summary_min_interval_s):
                        path = _write_workflow_summary_report(
                            report_dir=workflow_report_dir,
                            summary=workflow_summary,
                            verbose=args.verbose,
                        )
                        if path is not None:
                            workflow_last_emit_ts[session_id] = now_ts

            runtime.prune_pending_calls()
            _write_telemetry_snapshot(
                telemetry_file=telemetry_file,
                mode=mode,
                runtime=runtime,
                active_files=len(files),
                observe_forwarding_enabled=observe_forwarding_enabled,
                shadow_mode_warning_emitted=shadow_mode_warning_emitted,
                environment=environment,
                shadow_in_production=shadow_in_production,
            )

            if args.once:
                print(json.dumps({"mode": mode, "metrics": runtime.metrics.as_dict()}, indent=2))
                return 0

            time.sleep(max(0.25, float(args.poll)))
    finally:
        _release_singleton_lock(lock_file)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Codex hook bridge (shadow-first)")
    ap.add_argument("--mode", default="shadow", choices=["shadow", "observe"], help="shadow=metrics only, observe=forward to hooks/observe.py")
    ap.add_argument("--sessions-root", default=str(DEFAULT_CODEX_SESSIONS_ROOT), help="Codex sessions directory")
    ap.add_argument("--state-file", default=str(DEFAULT_STATE_FILE), help="Offset state file")
    ap.add_argument("--telemetry-file", default=str(DEFAULT_TELEMETRY_FILE), help="Telemetry JSONL output")
    ap.add_argument("--observe-path", default=str(DEFAULT_OBSERVE_PATH), help="Path to hooks/observe.py")
    ap.add_argument("--observe-timeout-s", type=float, default=8.0, help="observe.py timeout per event")
    ap.add_argument("--unknown-exit-policy", default="success", choices=["success", "failure", "skip"], help="How to classify outputs when exit code is unknown")
    ap.add_argument("--workflow-report-dir", default=str(DEFAULT_WORKFLOW_REPORT_DIR), help="Directory for codex workflow summary reports")
    ap.add_argument("--workflow-summary-min-interval-s", type=int, default=WORKFLOW_SUMMARY_MIN_INTERVAL_S, help="Min seconds between workflow summary emissions per session")
    ap.add_argument("--no-workflow-summary", action="store_true", help="Disable workflow summary report emission")
    ap.add_argument("--environment", default=str(os.environ.get("SPARK_ENV") or "dev"), help="Bridge environment tag (dev/staging/prod)")
    ap.add_argument("--fail-on-shadow-prod", action="store_true", default=_env_bool("SPARK_CODEX_FAIL_ON_SHADOW_PROD", False), help="Exit if mode=shadow and environment is production")
    ap.add_argument("--lock-file", default=str(DEFAULT_LOCK_FILE), help="Singleton lock file path")
    ap.add_argument("--poll", type=float, default=2.0, help="Poll interval in seconds")
    ap.add_argument("--max-per-tick", type=int, default=200, help="Max new lines per file per tick")
    ap.add_argument("--backfill", action="store_true", help="Start at offset 0 for new files")
    ap.add_argument("--once", action="store_true", help="Single pass and print summary JSON")
    ap.add_argument("--verbose", action="store_true", help="Print bridge activity")
    return ap


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    raise SystemExit(run_bridge(args))


if __name__ == "__main__":
    main()
