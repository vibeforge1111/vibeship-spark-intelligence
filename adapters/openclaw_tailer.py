#!/usr/bin/env python3
"""OpenClaw adapter: tail session JSONL -> sparkd /ingest

Reads OpenClaw session transcripts (~/.openclaw/agents/<agent>/sessions/) and
emits normalized SparkEventV1 events to sparkd.

Usage:
  python3 adapters/openclaw_tailer.py --sparkd http://127.0.0.1:8787 --agent main

Features (Phase 2):
- Tails the latest session file for a given agent.
- Optionally discovers and tails subagent sessions (--include-subagents).
- Watches a self-report directory for structured agent reports.
- Emits session boundary events when new sessions appear.
- De-dupes using per-file line offsets persisted in ~/.spark/adapters/.
- Handles all OpenClaw JSONL types: session, message, model_change,
  thinking_level_change, custom.
- Extracts tool calls from assistant content blocks AND separate toolResult messages.
"""

import argparse
import datetime
import json
import hashlib
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen

from adapters._common import (
    DEFAULT_SPARKD,
    TOKEN_FILE,
    resolve_token as _resolve_token,
    normalize_sparkd_base_url as _normalize_sparkd_base_url,
)

STATE_DIR = Path.home() / ".spark" / "adapters"

MAX_TOOL_RESULT_CHARS = 4000

DEFAULT_REPORT_DIR = Path.home() / ".openclaw" / "workspace" / "spark_reports"
DEFAULT_HOOK_EVENTS_FILE = Path(
    os.environ.get("SPARK_OPENCLAW_HOOK_EVENTS_FILE")
    or (Path.home() / ".spark" / "openclaw_hook_events.jsonl")
)

# Optional integration heartbeat (off by default)
HEARTBEAT_ENABLED = os.environ.get("SPARK_OPENCLAW_HEARTBEAT", "").strip().lower() not in ("", "0", "false", "no")
HEARTBEAT_EVERY_SECONDS = int(float(os.environ.get("SPARK_OPENCLAW_HEARTBEAT_MINUTES", "15")) * 60)
HEARTBEAT_PATH = Path(
    os.environ.get("SPARK_OPENCLAW_HEARTBEAT_PATH")
    or (Path.home() / ".spark" / "logs" / "openclaw_tailer_heartbeat.jsonl")
)


def _append_jsonl(path: Path, row: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _post_json(url: str, payload: dict, token: str = None):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method="POST")
    with urlopen(req, timeout=5) as resp:
        resp.read()


def _event(trace_id: str, session_id: str, source: str, kind: str, ts: float, payload: dict):
    return {
        "v": 1,
        "source": source,
        "kind": kind,
        "ts": ts,
        "session_id": session_id,
        "payload": payload,
        "trace_id": trace_id,
    }


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:20]


def _parse_ts(x):
    """Parse timestamp from various formats to epoch float."""
    if x is None:
        return time.time()
    if isinstance(x, (int, float)):
        return float(x) / 1000.0 if x > 2e10 else float(x)
    if isinstance(x, str):
        try:
            s = x.replace("Z", "+00:00")
            return datetime.datetime.fromisoformat(s).timestamp()
        except Exception:
            return time.time()
    return time.time()


def _truncate_content(content) -> str:
    """Extract text from content blocks and truncate to MAX_TOOL_RESULT_CHARS."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        text = "\n".join(parts)
    else:
        text = str(content) if content else ""
    if len(text) > MAX_TOOL_RESULT_CHARS:
        return text[:MAX_TOOL_RESULT_CHARS] + f"\n... [truncated {len(text) - MAX_TOOL_RESULT_CHARS} chars]"
    return text


def _should_skip_event(obj: dict) -> bool:
    """Filter out low-value events to reduce noise in the pipeline."""
    line_type = obj.get("type")
    if line_type != "message":
        return False
    
    msg = obj.get("message") if isinstance(obj.get("message"), dict) else None
    if not msg:
        return False
    
    role = msg.get("role")
    content = msg.get("content", "")
    
    # Skip heartbeat acks
    if role == "assistant":
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    break
        if "HEARTBEAT_OK" in text or "NO_REPLY" in text:
            return True
    
    # Skip successful tool results (keep errors)
    if role == "toolResult":
        if not msg.get("isError", False):
            # Keep tool results that are short (likely meaningful responses)
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text += block.get("text", "")
            # Skip large routine tool outputs (file reads, exec outputs)
            if len(text) > 2000:
                return True
    
    # Skip routine Read tool calls from assistant
    if role == "assistant" and isinstance(content, list):
        # If the only tool calls are Read, skip
        tool_calls = [b for b in content if isinstance(b, dict) and b.get("type") == "toolCall"]
        text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if tool_calls and not text_blocks:
            all_reads = all(tc.get("name") == "Read" for tc in tool_calls)
            if all_reads:
                return True
    
    return False


def parse_openclaw_line(obj: dict, session_key: str) -> list:
    """Parse one JSONL line into zero or more SparkEventV1 events."""
    events = []
    if _should_skip_event(obj):
        return events  # empty list, skip this event
    line_type = obj.get("type")
    ts = _parse_ts(obj.get("timestamp"))

    if line_type == "session":
        events.append(_event(
            trace_id=_hash(obj.get("id", "")),
            session_id=session_key,
            source="openclaw",
            kind="command",
            ts=ts,
            payload={"command": "session_start", "cwd": obj.get("cwd")},
        ))

    elif line_type == "message":
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else None
        if not msg:
            return events
        role = msg.get("role")
        content = msg.get("content", [])

        if role in ("user", "assistant"):
            text = None
            tool_calls = []
            meta = {}

            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and text is None:
                        text = block.get("text")
                    elif block.get("type") == "toolCall":
                        tool_calls.append({
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "arguments": block.get("arguments"),
                        })
                        targs = block.get("arguments") or {}
                        wd = targs.get("workdir") or targs.get("cwd")
                        if isinstance(wd, str) and wd and "cwd" not in meta:
                            meta["cwd"] = wd

            events.append(_event(
                trace_id=_hash(obj.get("id", "")),
                session_id=session_key,
                source="openclaw",
                kind="message",
                ts=ts,
                payload={
                    "role": role,
                    "text": text,
                    "meta": meta,
                    "model": msg.get("model"),
                    "provider": msg.get("provider"),
                    "usage": msg.get("usage"),
                    "stop_reason": msg.get("stopReason"),
                },
            ))

            for tc in tool_calls:
                events.append(_event(
                    trace_id=_hash(tc.get("id") or ""),
                    session_id=session_key,
                    source="openclaw",
                    kind="tool",
                    ts=ts,
                    payload={
                        "tool_name": tc["name"],
                        "tool_input": tc.get("arguments") or {},
                        "call_id": tc.get("id"),
                    },
                ))

        elif role == "toolResult":
            result_text = _truncate_content(content)
            events.append(_event(
                trace_id=_hash(obj.get("id", "")),
                session_id=session_key,
                source="openclaw",
                kind="tool",
                ts=ts,
                payload={
                    "tool_name": msg.get("toolName"),
                    "tool_input": {},
                    "tool_result": result_text,
                    "call_id": msg.get("toolCallId"),
                    "is_error": msg.get("isError", False),
                },
            ))

    elif line_type in ("model_change", "thinking_level_change", "custom"):
        payload_data = {"type": line_type}
        if line_type == "model_change":
            payload_data["model"] = obj.get("modelId")
            payload_data["provider"] = obj.get("provider")
        elif line_type == "thinking_level_change":
            payload_data["thinking_level"] = obj.get("thinkingLevel")
        elif line_type == "custom":
            payload_data["custom_type"] = obj.get("customType")
            payload_data["data"] = obj.get("data")
        events.append(_event(
            trace_id=_hash(obj.get("id", "")),
            session_id=session_key,
            source="openclaw",
            kind="system",
            ts=ts,
            payload=payload_data,
        ))

    return events


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------

def _discover_sessions(agent_dir: Path, include_subagents: bool = False):
    """Discover session files. Returns list of (session_key, Path).

    When include_subagents is True, returns ALL sessions from sessions.json,
    not just the latest one. Each entry is tagged with its session key so
    subagent sessions carry identifiers like 'agent:main:subagent:<uuid>'.
    """
    sessions_json = agent_dir / "sessions.json"
    results = []

    if sessions_json.exists():
        try:
            sj = json.loads(sessions_json.read_text(encoding="utf-8"))
            entries = list(sj.items())

            if not include_subagents:
                # Only latest session (original behaviour)
                if entries:
                    def keyfn(item):
                        v = item[1] or {}
                        return float(v.get("updatedAt") or v.get("lastMessageAt") or v.get("createdAt") or 0)
                    entries.sort(key=keyfn, reverse=True)
                    entries = entries[:1]

            for session_key, info in entries:
                info = info or {}
                session_file = info.get("sessionFile") or info.get("transcript")
                if session_file:
                    p = Path(session_file)
                    if p.exists():
                        results.append((session_key, p))
                        continue
                # Try constructing path from key
                # Session keys may contain colons; filename is usually the last segment or a hash
                candidate = agent_dir / f"{session_key}.jsonl"
                if candidate.exists():
                    results.append((session_key, candidate))
                    continue
                # Try matching by UUID portion of key
                parts = session_key.split(":")
                if len(parts) > 1:
                    candidate2 = agent_dir / f"{parts[-1]}.jsonl"
                    if candidate2.exists():
                        results.append((session_key, candidate2))

        except Exception:
            pass

    # Fallback: glob for newest .jsonl if nothing found
    if not results:
        jsonl_files = sorted(agent_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if jsonl_files:
            f = jsonl_files[0]
            results.append((f.stem, f))

    return results


def _find_latest_session(agent_dir: Path):
    """Find the latest session file and key (backwards compat helper)."""
    found = _discover_sessions(agent_dir, include_subagents=False)
    if found:
        return found[0]
    return None, None


# ---------------------------------------------------------------------------
# Self-report watcher
# ---------------------------------------------------------------------------

def _scan_reports(report_dir: Path, sparkd_url: str, token: str = None, verbose: bool = False):
    """Scan report_dir for new self-report JSON files, ingest them, then archive."""
    if not report_dir.exists():
        return 0

    processed_dir = report_dir / ".processed"
    count = 0

    for f in sorted(report_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            if verbose:
                print(f"[openclaw_tailer] bad report file {f.name}: {e}", flush=True)
            continue

        report_kind = data.pop("kind", "unknown")
        ts = data.pop("ts", time.time())

        evt = _event(
            trace_id=_hash(f.name),
            session_id="self_report",
            source="openclaw",
            kind="system",
            ts=ts,
            payload={
                "type": "self_report",
                "report_kind": report_kind,
                **data,
            },
        )

        try:
            _post_json(sparkd_url.rstrip("/") + "/ingest", evt, token=token)
        except Exception as e:
            if verbose:
                print(f"[openclaw_tailer] POST report error: {e}", flush=True)
            break  # Retry next tick

        # Archive the processed file
        try:
            processed_dir.mkdir(parents=True, exist_ok=True)
            f.rename(processed_dir / f.name)
        except Exception:
            try:
                f.unlink()
            except Exception:
                pass

        count += 1
        if verbose:
            print(f"[openclaw_tailer] ingested report {f.name} ({report_kind})", flush=True)

    return count


def _history_tool_stats(history_messages) -> dict:
    """Best-effort tool context summary from llm_input history rows."""
    if not isinstance(history_messages, list):
        return {}
    tool_messages = 0
    tool_blocks = 0
    for msg in history_messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").lower()
        if role in ("tool", "toolresult"):
            tool_messages += 1
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block_type = str(block.get("type") or "").lower()
                    if block_type in ("toolcall", "toolresult"):
                        tool_blocks += 1
    return {
        "history_tool_message_count": int(tool_messages),
        "history_tool_block_count": int(tool_blocks),
    }


def _parse_hook_event_row(row: dict):
    """Map hook spool row -> SparkEventV1 (or None when unsupported)."""
    if not isinstance(row, dict):
        return None

    hook = str(row.get("hook") or row.get("event") or "").strip().lower()
    if hook not in ("llm_input", "llm_output"):
        return None

    ts = _parse_ts(row.get("ts") or row.get("timestamp"))
    session_id = str(
        row.get("session_id")
        or row.get("sessionId")
        or row.get("session_key")
        or row.get("sessionKey")
        or "openclaw_hook"
    )
    trace_seed = str(
        row.get("trace_id")
        or row.get("traceId")
        or row.get("run_id")
        or row.get("runId")
        or json.dumps(row, sort_keys=True)
    )

    payload = {
        "type": "openclaw_hook",
        "hook": hook,
        "schema_version": int(row.get("schema_version") or 1),
        "run_id": row.get("run_id") or row.get("runId"),
        "session_key": row.get("session_key") or row.get("sessionKey"),
        "agent_id": row.get("agent_id") or row.get("agentId"),
        "provider": row.get("provider"),
        "model": row.get("model"),
    }

    if hook == "llm_input":
        prompt = row.get("prompt")
        system_prompt = row.get("system_prompt") or row.get("systemPrompt")
        history = row.get("history_messages") or row.get("historyMessages")

        payload["prompt_chars"] = int(
            row.get("prompt_chars")
            or (len(prompt) if isinstance(prompt, str) else 0)
        )
        payload["system_prompt_chars"] = int(
            row.get("system_prompt_chars")
            or (len(system_prompt) if isinstance(system_prompt, str) else 0)
        )
        payload["history_count"] = int(
            row.get("history_count")
            or (len(history) if isinstance(history, list) else 0)
        )
        payload["images_count"] = int(row.get("images_count") or row.get("imagesCount") or 0)
        payload.update(_history_tool_stats(history))

    if hook == "llm_output":
        assistant_texts = row.get("assistant_texts") or row.get("assistantTexts")
        output_count = len(assistant_texts) if isinstance(assistant_texts, list) else 0
        output_chars = 0
        if isinstance(assistant_texts, list):
            output_chars = sum(len(x) for x in assistant_texts if isinstance(x, str))

        usage = row.get("usage")
        payload["output_count"] = int(row.get("output_count") or output_count)
        payload["output_chars"] = int(row.get("output_chars") or output_chars)
        if isinstance(usage, dict):
            payload["usage"] = {
                "input": usage.get("input"),
                "output": usage.get("output"),
                "cacheRead": usage.get("cacheRead"),
                "cacheWrite": usage.get("cacheWrite"),
                "total": usage.get("total"),
            }

    payload = {k: v for k, v in payload.items() if v not in (None, "")}
    return _event(
        trace_id=_hash(trace_seed),
        session_id=session_id,
        source="openclaw",
        kind="system",
        ts=ts,
        payload=payload,
    )


def _scan_hook_events(
    hook_file: Path,
    state,
    sparkd_url: str,
    *,
    token: str = None,
    max_per_tick: int = 50,
    backfill: bool = False,
    verbose: bool = False,
):
    """Scan hook spool JSONL file and ingest mapped events."""
    if not hook_file.exists():
        return 0

    try:
        lines = hook_file.read_text(encoding="utf-8").splitlines()
    except Exception:
        return 0

    file_key = f"hook::{hook_file}"
    if state.is_new_file(file_key):
        initial_offset = 0 if backfill else len(lines)
        state.register_file(file_key, initial_offset)
        if verbose:
            print(
                f"[openclaw_tailer] hook spool registered: {hook_file} "
                f"(offset={initial_offset})",
                flush=True,
            )
        return 0

    off = state.get_offset(file_key)
    new_lines = lines[off:]
    if not new_lines:
        return 0

    batch_size = max(1, int(max_per_tick))
    batch = new_lines[:batch_size]
    sent = 0
    for line in batch:
        try:
            row = json.loads(line)
        except Exception:
            sent += 1
            continue

        evt = _parse_hook_event_row(row)
        if evt is None:
            sent += 1
            continue

        try:
            _post_json(sparkd_url.rstrip("/") + "/ingest", evt, token=token)
        except Exception as e:
            if verbose:
                print(f"[openclaw_tailer] hook POST error: {e}", flush=True)
            break
        sent += 1

    state.set_offset(file_key, off + sent)
    if sent and verbose:
        print(f"[openclaw_tailer] hook events sent {sent}", flush=True)
    return sent


# ---------------------------------------------------------------------------
# Multi-session state manager
# ---------------------------------------------------------------------------

class SessionState:
    """Tracks per-file offsets and detects new sessions."""

    def __init__(self, state_file: Path):
        self._path = state_file
        self._data = {"files": {}}
        if state_file.exists():
            try:
                self._data = json.loads(state_file.read_text(encoding="utf-8"))
                if "files" not in self._data:
                    # Migrate from Phase 1 single-session state
                    old_file = self._data.get("sessionFile")
                    old_offset = self._data.get("offset", 0)
                    self._data = {"files": {}}
                    if old_file:
                        self._data["files"][old_file] = {"offset": old_offset}
            except Exception:
                self._data = {"files": {}}

    def get_offset(self, file_path: str) -> int:
        return self._data["files"].get(file_path, {}).get("offset", 0)

    def set_offset(self, file_path: str, offset: int):
        if file_path not in self._data["files"]:
            self._data["files"][file_path] = {}
        self._data["files"][file_path]["offset"] = offset

    def is_new_file(self, file_path: str) -> bool:
        return file_path not in self._data["files"]

    def register_file(self, file_path: str, offset: int = 0):
        if file_path not in self._data["files"]:
            self._data["files"][file_path] = {"offset": offset}

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="OpenClaw adapter: tail session JSONL -> sparkd /ingest")
    ap.add_argument("--sparkd", default=DEFAULT_SPARKD, help="sparkd base URL")
    ap.add_argument("--agent", default="main", help="OpenClaw agent id")
    ap.add_argument("--poll", type=float, default=2.0, help="Poll interval seconds (default: 2.0)")
    ap.add_argument("--max-per-tick", type=int, default=50, help="Max lines to ingest per tick (default: 50)")
    ap.add_argument("--backfill", action="store_true", help="Backfill from the start of the transcript (default is tail-from-end)")
    ap.add_argument("--verbose", action="store_true", help="Log adapter activity")
    ap.add_argument("--token", default=None, help="sparkd auth token (or set SPARKD_TOKEN env, or use ~/.spark/sparkd.token)")
    ap.add_argument("--allow-remote", action="store_true", help="allow non-local sparkd URL (disabled by default)")
    ap.add_argument("--include-subagents", action="store_true", default=True,
                     help="Also tail subagent sessions (default: True)")
    ap.add_argument("--no-subagents", action="store_true", default=False,
                     help="Disable subagent tailing")
    ap.add_argument("--report-dir", type=str, default=None,
                     help="Directory to watch for self-report JSON files")
    ap.add_argument(
        "--hook-events-file",
        type=str,
        default=str(DEFAULT_HOOK_EVENTS_FILE),
        help="JSONL spool for OpenClaw llm_input/llm_output plugin events",
    )
    args = ap.parse_args()

    include_subagents = args.include_subagents and not args.no_subagents
    token = _resolve_token(args.token)

    report_dir = Path(args.report_dir) if args.report_dir else DEFAULT_REPORT_DIR
    hook_events_file = Path(args.hook_events_file) if args.hook_events_file else DEFAULT_HOOK_EVENTS_FILE

    agent_dir = Path.home() / ".openclaw" / "agents" / args.agent / "sessions"
    if not agent_dir.exists():
        raise SystemExit(f"No sessions directory at {agent_dir}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"openclaw-{args.agent}.json"
    state = SessionState(state_file)

    sparkd_url = _normalize_sparkd_base_url(args.sparkd, allow_remote=args.allow_remote)

    # Heartbeat state
    total_lines_sent = 0
    last_send_ts = None
    last_session_file = None
    next_hb_ts = time.time() if HEARTBEAT_ENABLED else None
    if HEARTBEAT_ENABLED:
        _append_jsonl(HEARTBEAT_PATH, {
            "ts": time.time(),
            "kind": "startup",
            "adapter": "openclaw_tailer",
            "agent": args.agent,
            "pid": os.getpid(),
            "sparkd": sparkd_url,
            "interval_sec": HEARTBEAT_EVERY_SECONDS,
            "include_subagents": include_subagents,
        })
        next_hb_ts = time.time() + max(5, HEARTBEAT_EVERY_SECONDS)

    while True:
        try:
            if args.verbose:
                print("[openclaw_tailer] tick", flush=True)

            # --- Discover sessions ---
            sessions = _discover_sessions(agent_dir, include_subagents=include_subagents)
            if not sessions:
                if args.verbose:
                    print("[openclaw_tailer] no session files found", flush=True)
                time.sleep(args.poll)
                continue

            # --- Process each session file ---
            for session_key, session_file in sessions:
                file_key = str(session_file)

                # Detect new session file -> emit session boundary event
                if state.is_new_file(file_key):
                    if args.backfill:
                        state.register_file(file_key, 0)
                    else:
                        try:
                            initial_offset = len(session_file.read_text(encoding="utf-8").splitlines())
                        except Exception:
                            initial_offset = 0
                        state.register_file(file_key, initial_offset)

                    # Emit session_start boundary event
                    boundary_evt = _event(
                        trace_id=_hash(f"boundary:{session_key}:{time.time()}"),
                        session_id=session_key,
                        source="openclaw",
                        kind="command",
                        ts=time.time(),
                        payload={"command": "session_start", "session_key": session_key},
                    )
                    try:
                        _post_json(sparkd_url.rstrip("/") + "/ingest", boundary_evt, token=token)
                        if args.verbose:
                            print(f"[openclaw_tailer] new session detected: {session_key}", flush=True)
                    except Exception as e:
                        if args.verbose:
                            print(f"[openclaw_tailer] boundary POST error: {e}", flush=True)

                    state.save()

                # Read and process lines
                try:
                    lines = session_file.read_text(encoding="utf-8").splitlines()
                except Exception:
                    continue

                off = state.get_offset(file_key)
                new_lines = lines[off:]
                if not new_lines:
                    continue

                batch_size = max(1, int(args.max_per_tick))
                batch = new_lines[:batch_size]

                sent = 0
                for line in batch:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        evt = _event(
                            trace_id=_hash(line),
                            session_id=session_key,
                            source="openclaw",
                            kind="system",
                            ts=time.time(),
                            payload={"raw": line},
                        )
                        try:
                            _post_json(sparkd_url.rstrip("/") + "/ingest", evt, token=token)
                        except Exception as post_err:
                            if args.verbose:
                                print(f"[openclaw_tailer] POST error: {post_err}", flush=True)
                            break
                        sent += 1
                        continue

                    events = parse_openclaw_line(obj, session_key)
                    if not events:
                        events = [_event(
                            trace_id=_hash(json.dumps(obj, sort_keys=True)),
                            session_id=session_key,
                            source="openclaw",
                            kind="system",
                            ts=_parse_ts(obj.get("timestamp")),
                            payload={"raw": obj},
                        )]

                    post_ok = True
                    for evt in events:
                        try:
                            _post_json(sparkd_url.rstrip("/") + "/ingest", evt, token=token)
                        except Exception as post_err:
                            if args.verbose:
                                print(f"[openclaw_tailer] POST error: {post_err}", flush=True)
                            post_ok = False
                            break

                    if not post_ok:
                        break
                    sent += 1

                state.set_offset(file_key, off + sent)

                if sent:
                    total_lines_sent += sent
                    last_send_ts = time.time()
                    last_session_file = str(session_file)

                if args.verbose and sent:
                    remaining = max(0, len(new_lines) - sent)
                    print(f"[openclaw_tailer] [{session_key}] sent {sent}, remaining {remaining}", flush=True)

            _scan_hook_events(
                hook_events_file,
                state,
                sparkd_url,
                token=token,
                max_per_tick=args.max_per_tick,
                backfill=args.backfill,
                verbose=args.verbose,
            )

            state.save()

            # --- Scan self-reports ---
            try:
                _scan_reports(report_dir, sparkd_url, token=token, verbose=args.verbose)
            except Exception as e:
                if args.verbose:
                    print(f"[openclaw_tailer] report scan error: {e}", flush=True)

            # --- Optional integration heartbeat ---
            if HEARTBEAT_ENABLED and next_hb_ts is not None and time.time() >= next_hb_ts:
                _append_jsonl(HEARTBEAT_PATH, {
                    "ts": time.time(),
                    "kind": "heartbeat",
                    "adapter": "openclaw_tailer",
                    "agent": args.agent,
                    "pid": os.getpid(),
                    "sparkd": sparkd_url,
                    "sessions_count": len(sessions) if 'sessions' in locals() else None,
                    "last_session_file": last_session_file,
                    "total_lines_sent": total_lines_sent,
                    "last_send_ts": last_send_ts,
                    "since_last_send_sec": (time.time() - last_send_ts) if last_send_ts else None,
                })
                next_hb_ts = time.time() + max(5, HEARTBEAT_EVERY_SECONDS)

        except Exception as e:
            if args.verbose:
                print(f"[openclaw_tailer] error: {e}", flush=True)

        time.sleep(args.poll)


if __name__ == "__main__":
    main()
