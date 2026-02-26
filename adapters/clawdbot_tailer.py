#!/usr/bin/env python3
"""Clawdbot adapter: tail session JSONL -> sparkd /ingest

This makes Spark model/provider-agnostic and (mostly) runtime-agnostic.
It reads what Clawdbot already writes (session transcripts) and emits normalized
SparkEventV1 events.

Usage:
  python3 adapters/clawdbot_tailer.py --sparkd http://127.0.0.1:<sparkd-port> --agent main

Notes:
- This is intentionally simple: it tails the latest session file for an agent.
- It de-dupes using a simple line offset persisted in ~/.spark/adapters/*.json.
"""

import argparse
import json
import os
import time
import hashlib
from pathlib import Path
from urllib.request import Request, urlopen

from adapters._common import (
    DEFAULT_SPARKD,
    resolve_token as _resolve_token,
    normalize_sparkd_base_url as _normalize_sparkd_base_url,
)


STATE_DIR = Path.home() / ".spark" / "adapters"


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sparkd", default=DEFAULT_SPARKD, help="sparkd base URL")
    ap.add_argument("--agent", default="main", help="Clawdbot agent id")
    ap.add_argument("--poll", type=float, default=2.0, help="Poll interval seconds (default: 2.0)")
    ap.add_argument("--max-per-tick", type=int, default=50, help="Max lines to ingest per tick (default: 50)")
    ap.add_argument("--backfill", action="store_true", help="Backfill from the start of the transcript (DANGEROUS; default is tail-from-end)")
    ap.add_argument("--verbose", action="store_true", help="Log adapter activity")
    ap.add_argument("--token", default=None, help="sparkd auth token (or set SPARKD_TOKEN env, or use ~/.spark/sparkd.token)")
    ap.add_argument("--allow-remote", action="store_true", help="allow non-local sparkd URL (disabled by default)")
    args = ap.parse_args()

    token = _resolve_token(args.token)
    sparkd_base = _normalize_sparkd_base_url(args.sparkd, allow_remote=args.allow_remote)

    agent_dir = Path.home() / ".clawdbot" / "agents" / args.agent / "sessions"
    sessions_json = agent_dir / "sessions.json"
    if not sessions_json.exists():
        raise SystemExit(f"No sessions.json at {sessions_json}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"clawdbot-{args.agent}.json"
    state = {"sessionFile": None, "offset": 0}
    if state_file.exists():
        try:
            state.update(json.loads(state_file.read_text(encoding="utf-8")))
        except Exception:
            pass

    def save_state():
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    while True:
        try:
            if args.verbose:
                print("[clawdbot_tailer] tick", flush=True)
            sj = json.loads(sessions_json.read_text(encoding="utf-8"))
            # sessions.json is a map; pick most recent by updatedAt/lastMessageAt if present.
            entries = []
            for k, v in sj.items():
                entries.append((k, v))
            if not entries:
                time.sleep(args.poll)
                continue
            # heuristic: sort by "updatedAt" or "lastMessageAt"; fallback stable order
            def keyfn(item):
                v = item[1] or {}
                # these are often epoch millis
                return float(v.get("updatedAt") or v.get("lastMessageAt") or v.get("createdAt") or 0)
            entries.sort(key=keyfn, reverse=True)
            session_key, info = entries[0]
            session_file = Path(info.get("sessionFile") or info.get("transcript") or "")
            if args.verbose:
                print(f"[clawdbot_tailer] using session {session_key} file={session_file}", flush=True)
            if not session_file.exists():
                time.sleep(args.poll)
                continue

            # New session file? default to tail-from-end unless --backfill.
            if state.get("sessionFile") != str(session_file):
                state["sessionFile"] = str(session_file)
                if args.backfill:
                    state["offset"] = 0
                else:
                    try:
                        state["offset"] = len(session_file.read_text(encoding="utf-8").splitlines())
                    except Exception:
                        state["offset"] = 0
                save_state()

            lines = session_file.read_text(encoding="utf-8").splitlines()
            if args.verbose:
                print(f"[clawdbot_tailer] lines={len(lines)} offset={state.get('offset')}", flush=True)
            off = int(state.get("offset") or 0)
            new_lines = lines[off:]
            if not new_lines:
                time.sleep(args.poll)
                continue

            # Process in bounded batches so we don't overload the system.
            batch_size = max(1, int(args.max_per_tick))
            batch = new_lines[:batch_size]

            sent = 0
            for line in batch:
                trace_id = _hash(line)
                try:
                    obj = json.loads(line)
                except Exception:
                    obj = {"raw": line}

                kind = "system"
                payload = {"raw": obj}
                if isinstance(obj, dict):
                    raw_ts = obj.get("ts") or obj.get("timestamp")
                else:
                    raw_ts = None

                def parse_ts(x):
                    if x is None:
                        return time.time()
                    # epoch millis
                    if isinstance(x, (int, float)):
                        return float(x) / 1000.0 if x > 2e10 else float(x)
                    # ISO string
                    if isinstance(x, str):
                        try:
                            # 2026-01-26T23:52:26.101Z
                            import datetime
                            s = x.replace("Z", "+00:00")
                            return datetime.datetime.fromisoformat(s).timestamp()
                        except Exception:
                            return time.time()
                    return time.time()

                ts = parse_ts(raw_ts)

                if isinstance(obj, dict):
                    # Clawdbot session JSONL shape (common):
                    # {"type":"message", "timestamp":..., "message": {"role":"user|assistant", "content": [...] }}
                    msg = obj.get("message") if isinstance(obj.get("message"), dict) else None
                    if msg and msg.get("role") in ("user", "assistant"):
                        kind = "message"
                        role = msg.get("role")
                        content = msg.get("content")
                        text = None
                        meta = {}

                        if isinstance(content, str):
                            text = content
                        elif isinstance(content, list):
                            # Prefer first text block
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text = block.get("text")
                                    break

                            # Also harvest cwd/workdir hints from toolCall blocks (common in Clawdbot transcripts)
                            for block in content:
                                if not isinstance(block, dict):
                                    continue
                                if block.get("type") == "toolCall" and isinstance(block.get("arguments"), dict):
                                    targs = block.get("arguments")
                                    wd = targs.get("workdir") or targs.get("cwd")
                                    if isinstance(wd, str) and wd:
                                        meta["cwd"] = wd
                                        break
                                    cmd = targs.get("command")
                                    if isinstance(cmd, str) and cmd.strip().startswith("cd "):
                                        # best-effort parse: take first token after `cd ` (stop at whitespace/newline/&&)
                                        try:
                                            part = cmd.strip()[3:]
                                            part = part.split("&&", 1)[0].strip()
                                            path = part.split()[0].strip()
                                            if path:
                                                meta["cwd"] = path
                                                break
                                        except Exception:
                                            pass

                        payload = {
                            "role": role,
                            "text": text,
                            "meta": meta,
                        }

                    # Legacy/other shapes
                    elif obj.get("kind") in ("user", "assistant") or obj.get("role") in ("user", "assistant"):
                        kind = "message"
                        payload = {
                            "role": obj.get("kind") or obj.get("role"),
                            "text": obj.get("text") or obj.get("content"),
                        }

                    # Tool payloads vary; keep it permissive.
                    if obj.get("tool") or obj.get("toolName") or obj.get("tool") == "tool" or obj.get("type") == "tool":
                        kind = "tool"
                        payload = {
                            "tool_name": obj.get("tool") or obj.get("toolName"),
                            "tool_input": obj.get("input") or obj.get("args") or obj.get("tool_input") or {},
                            "error": obj.get("error"),
                        }

                evt = _event(trace_id, session_id=session_key, source="clawdbot", kind=kind, ts=ts, payload=payload)
                _post_json(sparkd_base + "/ingest", evt, token=token)
                sent += 1

            state["offset"] = off + sent
            save_state()

            if args.verbose and sent:
                remaining = max(0, len(new_lines) - sent)
                print(f"[clawdbot_tailer] sent {sent}, remaining {remaining}, offset {state['offset']}", flush=True)

        except Exception as e:
            if args.verbose:
                print(f"[clawdbot_tailer] error: {e}", flush=True)

        time.sleep(args.poll)


if __name__ == "__main__":
    main()
