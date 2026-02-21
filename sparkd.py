#!/usr/bin/env python3
"""sparkd - Spark daemon (platform-agnostic ingest)

Minimal HTTP server:
  GET  /health
  GET  /status
  POST /ingest  (SparkEventV1 JSON)

Stores events into the existing Spark queue (events.jsonl) so the rest of Spark
can process them.

This is intentionally dependency-free.
"""

import atexit
import json
import os
import secrets
import time
from collections import defaultdict, deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Lock
from threading import Thread
from urllib.parse import urlparse

import sys
sys.path.insert(0, str(Path(__file__).parent))

from lib.events import SparkEventV1, validate_event_dict
from lib.queue import quick_capture, EventType
from lib.orchestration import register_agent, recommend_agent, record_handoff, get_orchestrator
from lib.bridge_cycle import read_bridge_heartbeat, run_bridge_cycle, write_bridge_heartbeat
from lib.pattern_detection.worker import get_pattern_backlog
from lib.validation_loop import get_validation_backlog
from lib.diagnostics import setup_component_logging, log_debug
from lib.ports import SPARKD_PORT

PORT = SPARKD_PORT
TOKEN_FILE = Path.home() / ".spark" / "sparkd.token"
_ALLOWED_POST_HOSTS = {
    f"127.0.0.1:{PORT}",
    f"localhost:{PORT}",
    f"[::1]:{PORT}",
}
TOKEN = os.environ.get("SPARKD_TOKEN")
MAX_BODY_BYTES = int(os.environ.get("SPARKD_MAX_BODY_BYTES", "262144"))
INVALID_EVENTS_FILE = Path.home() / ".spark" / "invalid_events.jsonl"
TUNEABLES_FILE = Path.home() / ".spark" / "tuneables.json"
RATE_LIMIT_PER_MIN = int(os.environ.get("SPARKD_RATE_LIMIT_PER_MIN", "240"))
RATE_LIMIT_WINDOW_S = int(os.environ.get("SPARKD_RATE_LIMIT_WINDOW_S", "60"))
INVALID_EVENTS_MAX_LINES = int(os.environ.get("SPARKD_INVALID_EVENTS_MAX_LINES", "2000"))
INVALID_EVENTS_MAX_PAYLOAD_CHARS = int(os.environ.get("SPARKD_INVALID_EVENTS_MAX_PAYLOAD_CHARS", "4000"))

_RATE_LIMIT_BUCKETS = defaultdict(deque)
_RATE_LIMIT_LOCK = Lock()
OPENCLAW_RUNTIME_DEFAULTS = {
    "advisory_bridge_enabled": True,
    "emotion_updates_enabled": True,
    "emotion_trigger_intensity": 0.7,
    "async_dispatch_enabled": True,
}
_OPENCLAW_RUNTIME_CFG_CACHE = dict(OPENCLAW_RUNTIME_DEFAULTS)
_OPENCLAW_RUNTIME_CFG_MTIME = None


def _read_token_file(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return raw if raw else None
    except Exception:
        return None


def _resolve_token() -> str:
    if env_token := os.environ.get("SPARKD_TOKEN"):
        return env_token.strip()

    existing = _read_token_file(TOKEN_FILE)
    if existing:
        return existing

    generated = secrets.token_urlsafe(24)
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(generated, encoding="utf-8")
    except Exception:
        pass
    return generated


def _normalize_origin(raw: str) -> str | None:
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.netloc:
        return parsed.netloc
    return None


def _is_allowed_origin(headers) -> bool:
    if headers is None:
        return False

    for header_name in ("Origin", "Referer"):
        raw = headers.get(header_name)
        if not raw:
            continue
        normalized = _normalize_origin(raw)
        if normalized is None:
            return False
        if normalized in _ALLOWED_POST_HOSTS:
            return True
        return False

    host = (headers.get("Host") or "").strip()
    return host in _ALLOWED_POST_HOSTS


def _is_csrf_safe(headers) -> bool:
    fetch_site = (headers.get("Sec-Fetch-Site") or "").strip().lower() if headers is not None else ""
    if not fetch_site:
        return True
    return fetch_site in {"same-origin", "same-site", "none"}


TOKEN = _resolve_token()


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except Exception:
        return False


def _acquire_single_instance_lock(name: str) -> Path | None:
    lock_dir = Path.home() / ".spark" / "pids"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / f"{name}.lock"
    pid = os.getpid()

    if lock_file.exists():
        try:
            existing_pid = int(lock_file.read_text(encoding="utf-8").strip())
            if existing_pid != pid and _pid_is_alive(existing_pid):
                print(f"[SPARK] {name} already running with pid {existing_pid}; exiting duplicate instance")
                return None
        except Exception:
            pass

    lock_file.write_text(str(pid), encoding="utf-8")

    def _cleanup_lock() -> None:
        try:
            if lock_file.exists() and lock_file.read_text(encoding="utf-8").strip() == str(pid):
                lock_file.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(_cleanup_lock)
    return lock_file


def _json(handler: BaseHTTPRequestHandler, code: int, payload):
    raw = json.dumps(payload).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _text(handler: BaseHTTPRequestHandler, code: int, body: str):
    raw = body.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _is_authorized(handler: BaseHTTPRequestHandler) -> bool:
    """Require Bearer token for mutating POST endpoints."""
    auth = (handler.headers.get("Authorization") or "").strip()
    return auth == f"Bearer {TOKEN}"


def _allow_rate_limited_request(client_ip: str, now: float | None = None) -> tuple[bool, int]:
    """Simple sliding-window limiter per client IP."""
    if RATE_LIMIT_PER_MIN <= 0 or RATE_LIMIT_WINDOW_S <= 0:
        return True, 0

    ts = float(now if now is not None else time.time())
    cutoff = ts - RATE_LIMIT_WINDOW_S
    key = str(client_ip or "unknown")

    with _RATE_LIMIT_LOCK:
        bucket = _RATE_LIMIT_BUCKETS[key]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= RATE_LIMIT_PER_MIN:
            retry_after = int(max(1, RATE_LIMIT_WINDOW_S - (ts - bucket[0])))
            return False, retry_after

        bucket.append(ts)
        return True, 0


def _trim_jsonl_tail(path: Path, max_lines: int) -> None:
    if max_lines <= 0 or not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) <= max_lines:
            return
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")
        tmp.replace(path)
    except Exception:
        return


def _truncate_payload(payload):
    """Limit payload size for invalid-event quarantine safety."""
    if isinstance(payload, str):
        if len(payload) <= INVALID_EVENTS_MAX_PAYLOAD_CHARS:
            return payload
        return payload[:INVALID_EVENTS_MAX_PAYLOAD_CHARS] + "...<truncated>"
    if isinstance(payload, dict):
        text = json.dumps(payload, ensure_ascii=False)
        if len(text) <= INVALID_EVENTS_MAX_PAYLOAD_CHARS:
            return payload
        return text[:INVALID_EVENTS_MAX_PAYLOAD_CHARS] + "...<truncated>"
    return str(payload)[:INVALID_EVENTS_MAX_PAYLOAD_CHARS]


def _quarantine_invalid(payload, reason: str) -> None:
    try:
        INVALID_EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "reason": reason,
            "received_at": time.time(),
            "payload": _truncate_payload(payload),
        }
        with INVALID_EVENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        _trim_jsonl_tail(INVALID_EVENTS_FILE, INVALID_EVENTS_MAX_LINES)
    except Exception:
        return


def _parse_bool(value, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "off", "no"}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return float(default)


def _load_openclaw_runtime_config(*, force: bool = False) -> dict:
    global _OPENCLAW_RUNTIME_CFG_CACHE
    global _OPENCLAW_RUNTIME_CFG_MTIME

    mtime = None
    try:
        if TUNEABLES_FILE.exists():
            mtime = float(TUNEABLES_FILE.stat().st_mtime)
    except Exception:
        mtime = None

    if not force and _OPENCLAW_RUNTIME_CFG_MTIME == mtime:
        return dict(_OPENCLAW_RUNTIME_CFG_CACHE)

    cfg = dict(OPENCLAW_RUNTIME_DEFAULTS)
    try:
        if TUNEABLES_FILE.exists():
            data = json.loads(TUNEABLES_FILE.read_text(encoding="utf-8-sig"))
            section = data.get("openclaw_runtime") if isinstance(data, dict) else None
            if isinstance(section, dict):
                cfg["advisory_bridge_enabled"] = _parse_bool(
                    section.get("advisory_bridge_enabled"),
                    cfg["advisory_bridge_enabled"],
                )
                cfg["emotion_updates_enabled"] = _parse_bool(
                    section.get("emotion_updates_enabled"),
                    cfg["emotion_updates_enabled"],
                )
                cfg["emotion_trigger_intensity"] = _safe_float(
                    section.get("emotion_trigger_intensity"),
                    cfg["emotion_trigger_intensity"],
                )
                cfg["async_dispatch_enabled"] = _parse_bool(
                    section.get("async_dispatch_enabled"),
                    cfg["async_dispatch_enabled"],
                )
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        log_debug("sparkd", f"failed to load openclaw runtime config from {TUNEABLES_FILE}", e)

    env_advisory = os.environ.get("SPARKD_OPENCLAW_ADVISORY_BRIDGE_ENABLED")
    if env_advisory is not None:
        cfg["advisory_bridge_enabled"] = _parse_bool(
            env_advisory,
            cfg["advisory_bridge_enabled"],
        )

    env_emotion = os.environ.get("SPARKD_OPENCLAW_EMOTION_UPDATES_ENABLED")
    if env_emotion is not None:
        cfg["emotion_updates_enabled"] = _parse_bool(
            env_emotion,
            cfg["emotion_updates_enabled"],
        )

    env_intensity = os.environ.get("SPARKD_OPENCLAW_EMOTION_TRIGGER_INTENSITY")
    if env_intensity is not None:
        cfg["emotion_trigger_intensity"] = _safe_float(
            env_intensity,
            cfg["emotion_trigger_intensity"],
        )
    env_async = os.environ.get("SPARKD_OPENCLAW_BRIDGE_ASYNC_ENABLED")
    if env_async is not None:
        cfg["async_dispatch_enabled"] = _parse_bool(
            env_async,
            cfg["async_dispatch_enabled"],
        )

    cfg["emotion_trigger_intensity"] = max(0.2, min(1.0, float(cfg["emotion_trigger_intensity"])))
    _OPENCLAW_RUNTIME_CFG_CACHE = dict(cfg)
    _OPENCLAW_RUNTIME_CFG_MTIME = mtime
    return dict(cfg)


def _resolve_queue_event_type(evt: SparkEventV1) -> EventType:
    payload = evt.payload if isinstance(evt.payload, dict) else {}
    kind = str(getattr(evt.kind, "value", ""))
    if kind == "message":
        return EventType.USER_PROMPT
    if kind == "tool":
        is_result = "tool_result" in payload or "is_error" in payload
        if is_result:
            return EventType.POST_TOOL_FAILURE if bool(payload.get("is_error")) else EventType.POST_TOOL
        return EventType.PRE_TOOL
    if kind == "command" and str(payload.get("command") or "").strip().lower() == "session_start":
        return EventType.SESSION_START
    return EventType.LEARNING


def _infer_user_emotion_trigger(text: str):
    t = str(text or "").strip().lower()
    if not t:
        return None
    if any(tok in t for tok in ("frustrated", "annoyed", "angry", "upset", "not working", "stuck", "broken")):
        return "user_frustration"
    if any(tok in t for tok in ("confused", "unclear", "not sure", "don't understand", "dont understand")):
        return "user_confusion"
    if any(tok in t for tok in ("urgent", "asap", "production", "incident", "critical", "immediately")):
        return "high_stakes_request"
    if any(tok in t for tok in ("great", "awesome", "nice", "perfect", "thanks", "thank you", "good job")):
        return "user_celebration"
    return None


def _call_advisory_on_user_prompt(session_id: str, prompt_text: str, trace_id: str | None = None) -> None:
    from lib.advisory_engine import on_user_prompt

    on_user_prompt(session_id, prompt_text, trace_id=trace_id)


def _call_advisory_on_pre_tool(
    session_id: str,
    tool_name: str,
    tool_input: dict | None = None,
    trace_id: str | None = None,
):
    from lib.advisory_engine import on_pre_tool

    return on_pre_tool(session_id, tool_name, tool_input=tool_input or {}, trace_id=trace_id)


def _call_advisory_on_post_tool(
    session_id: str,
    tool_name: str,
    success: bool,
    tool_input: dict | None = None,
    trace_id: str | None = None,
    error: str | None = None,
) -> None:
    from lib.advisory_engine import on_post_tool

    on_post_tool(
        session_id,
        tool_name,
        success=bool(success),
        tool_input=tool_input or {},
        trace_id=trace_id,
        error=error,
    )


def _emotion_register_trigger(trigger: str, *, intensity: float = 0.7, note: str = "") -> None:
    from lib.spark_emotions import SparkEmotions

    SparkEmotions().register_trigger(trigger, intensity=float(intensity), note=note)


def _emotion_recover() -> None:
    from lib.spark_emotions import SparkEmotions

    SparkEmotions().recover()


def _maybe_bridge_openclaw_runtime(evt: SparkEventV1, event_type: EventType) -> None:
    source = str(getattr(evt, "source", "") or "").strip().lower()
    if source != "openclaw":
        return

    cfg = _load_openclaw_runtime_config()
    advisory_enabled = bool(cfg.get("advisory_bridge_enabled", True))
    emotion_enabled = bool(cfg.get("emotion_updates_enabled", True))
    if not advisory_enabled and not emotion_enabled:
        return

    payload = evt.payload if isinstance(evt.payload, dict) else {}
    kind = str(getattr(evt.kind, "value", ""))
    session_id = str(getattr(evt, "session_id", "") or "")
    trace_id = getattr(evt, "trace_id", None)
    intensity = float(cfg.get("emotion_trigger_intensity", 0.7) or 0.7)

    if kind == "message":
        role = str(payload.get("role") or "").strip().lower()
        text = str(payload.get("text") or "").strip()
        if role != "user" or not text:
            return
        if advisory_enabled:
            try:
                _call_advisory_on_user_prompt(session_id, text, trace_id=trace_id)
            except Exception:
                pass
        if emotion_enabled:
            try:
                trigger = _infer_user_emotion_trigger(text)
                if trigger:
                    _emotion_register_trigger(trigger, intensity=intensity, note="openclaw_user_prompt")
                else:
                    _emotion_recover()
            except Exception:
                pass
        return

    if kind != "tool":
        return

    tool_name = str(payload.get("tool_name") or "").strip()
    if not tool_name:
        return
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}

    if event_type == EventType.PRE_TOOL:
        if advisory_enabled:
            try:
                _call_advisory_on_pre_tool(session_id, tool_name, tool_input=tool_input, trace_id=trace_id)
            except Exception:
                pass
        return

    if event_type not in {EventType.POST_TOOL, EventType.POST_TOOL_FAILURE}:
        return

    success = bool(event_type == EventType.POST_TOOL and not payload.get("is_error"))
    error_text = ""
    if not success:
        error_text = str(payload.get("error") or payload.get("tool_result") or "")[:200]

    if advisory_enabled:
        try:
            _call_advisory_on_post_tool(
                session_id,
                tool_name,
                success=success,
                tool_input=tool_input,
                trace_id=trace_id,
                error=error_text or None,
            )
        except Exception:
            pass

    if emotion_enabled:
        try:
            if success:
                _emotion_recover()
            else:
                _emotion_register_trigger(
                    "repair_after_mistake",
                    intensity=max(0.5, intensity),
                    note=f"openclaw_tool_failure:{tool_name}",
                )
        except Exception:
            pass


def _dispatch_openclaw_runtime_bridge(evt: SparkEventV1, event_type: EventType) -> None:
    source = str(getattr(evt, "source", "") or "").strip().lower()
    if source != "openclaw":
        return
    cfg = _load_openclaw_runtime_config()
    if not bool(cfg.get("advisory_bridge_enabled", True)) and not bool(cfg.get("emotion_updates_enabled", True)):
        return
    if not bool(cfg.get("async_dispatch_enabled", True)):
        _maybe_bridge_openclaw_runtime(evt, event_type)
        return
    try:
        Thread(
            target=_maybe_bridge_openclaw_runtime,
            args=(evt, event_type),
            daemon=True,
        ).start()
    except Exception:
        return


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return _text(self, 200, "ok")
        if path == "/status":
            heartbeat = read_bridge_heartbeat() or {}
            # Include pipeline health if available
            pipeline_health = {}
            try:
                from lib.pipeline import get_pipeline_health
                pipeline_health = get_pipeline_health()
            except Exception:
                pass
            return _json(self, 200, {
                "ok": True,
                "now": time.time(),
                "port": PORT,
                "bridge_worker": {
                    "last_heartbeat": heartbeat.get("ts"),
                    "stats": heartbeat.get("stats") or {},
                    "pattern_backlog": get_pattern_backlog(),
                    "validation_backlog": get_validation_backlog(),
                },
                "pipeline": pipeline_health,
            })
        if path == "/agents":
            orch = get_orchestrator()
            return _json(self, 200, {"ok": True, "agents": orch.list_agents()})
        return _text(self, 404, "not found")

    def do_POST(self):
        path = urlparse(self.path).path

        # Safety: only accept POSTs from localhost by default.
        remote = str(self.client_address[0]) if getattr(self, 'client_address', None) else ''
        allow_remote = (os.environ.get('SPARKD_ALLOW_REMOTE_POST') or '').strip().lower() in {'1','true','yes','on'}
        if not allow_remote and remote not in {'127.0.0.1', '::1'}:
            return _json(self, 403, {'ok': False, 'error': 'remote POST forbidden'})

        if not _is_allowed_origin(self.headers):
            return _json(self, 403, {'ok': False, 'error': 'origin not allowed'})

        if not _is_csrf_safe(self.headers):
            return _json(self, 403, {'ok': False, 'error': 'cross-site POST blocked'})

        client_ip = self.client_address[0] if self.client_address else "unknown"
        allowed, retry_after = _allow_rate_limited_request(client_ip)
        if not allowed:
            return _json(self, 429, {
                "ok": False,
                "error": "rate_limited",
                "retry_after_s": retry_after,
            })

        # Mutable POST endpoints require bearer token auth.
        if not _is_authorized(self):
            return _json(self, 401, {"ok": False, "error": "unauthorized"})

        if path == "/process":
            # Run a bridge cycle to process pending events
            try:
                stats = run_bridge_cycle()
                write_bridge_heartbeat(stats)
                return _json(self, 200, {
                    "ok": True,
                    "processed": stats.get("pattern_processed", 0),
                    "learnings": stats.get("content_learned", 0),
                    "patterns": stats.get("pattern_processed", 0),
                    "memory": stats.get("memory", {}),
                    "validation": stats.get("validation", {}),
                    "errors": stats.get("errors", []),
                })
            except Exception as e:
                return _json(self, 500, {"ok": False, "error": str(e)[:200]})

        if path == "/reflect":
            # Trigger deep reflection (run multiple cycles + analyze)
            try:
                all_stats = []
                for _ in range(3):  # Run 3 cycles for deeper analysis
                    stats = run_bridge_cycle()
                    all_stats.append(stats)
                    write_bridge_heartbeat(stats)

                total_patterns = sum(s.get("pattern_processed", 0) for s in all_stats)
                total_learnings = sum(s.get("content_learned", 0) for s in all_stats)

                return _json(self, 200, {
                    "ok": True,
                    "cycles": len(all_stats),
                    "meta_patterns": total_patterns,
                    "insights": total_learnings,
                    "message": f"Reflected across {len(all_stats)} cycles",
                })
            except Exception as e:
                return _json(self, 500, {"ok": False, "error": str(e)[:200]})

        if path == "/agent":
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(body.decode("utf-8") or "{}")
                ok = register_agent(
                    agent_id=data.get("agent_id") or data.get("name", "").lower().replace(" ", "-"),
                    name=data.get("name"),
                    capabilities=data.get("capabilities", []),
                    specialization=data.get("specialization", "general"),
                )
                return _json(self, 201 if ok else 400, {"ok": ok})
            except Exception as e:
                return _json(self, 400, {"ok": False, "error": str(e)[:200]})

        if path == "/orchestration/recommend":
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(body.decode("utf-8") or "{}")
                agent_id, reason = recommend_agent(
                    query=data.get("query", "") or data.get("task", ""),
                    task_type=data.get("task_type", ""),
                )
                return _json(self, 200, {"ok": True, "recommended_agent": agent_id, "reason": reason})
            except Exception as e:
                return _json(self, 400, {"ok": False, "error": str(e)[:200]})

        if path == "/handoff":
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(body.decode("utf-8") or "{}")
                hid = record_handoff(
                    from_agent=data.get("from_agent"),
                    to_agent=data.get("to_agent"),
                    context=data.get("context", {}),
                    success=data.get("success"),
                )
                return _json(self, 201, {"ok": True, "handoff_id": hid})
            except Exception as e:
                return _json(self, 400, {"ok": False, "error": str(e)[:200]})

        if path != "/ingest":
            return _text(self, 404, "not found")

        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > MAX_BODY_BYTES:
            return _json(self, 413, {"ok": False, "error": "payload_too_large"})
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except Exception as e:
            _quarantine_invalid(body.decode("utf-8", errors="replace"), f"json_decode:{type(e).__name__}")
            return _json(self, 400, {"ok": False, "error": "invalid_json", "detail": str(e)[:200]})

        ok, err = validate_event_dict(data, strict=True)
        if not ok:
            _quarantine_invalid(data, err)
            return _json(self, 400, {"ok": False, "error": "invalid_event", "detail": err})

        try:
            evt = SparkEventV1.from_dict(data)
        except Exception as e:
            _quarantine_invalid(data, f"parse_error:{type(e).__name__}")
            return _json(self, 400, {"ok": False, "error": "invalid_event", "detail": str(e)[:200]})

        et = _resolve_queue_event_type(evt)

        # Try to propagate working-directory hints for project inference.
        meta = (evt.payload or {}).get("meta") or {}
        cwd_hint = meta.get("cwd") or meta.get("workdir") or meta.get("workspace")

        ok = quick_capture(
            event_type=et,
            session_id=evt.session_id,
            data={
                "source": evt.source,
                "kind": evt.kind.value,
                "payload": evt.payload,
                "trace_id": evt.trace_id,
                "v": evt.v,
                "ts": evt.ts,
                "cwd": cwd_hint,
            },
            tool_name=evt.payload.get("tool_name"),
            tool_input=evt.payload.get("tool_input"),
            error=evt.payload.get("error"),
        )

        _dispatch_openclaw_runtime_bridge(evt, et)

        return _json(self, 200, {"ok": bool(ok)})


def main():
    setup_component_logging("sparkd")
    lock_file = _acquire_single_instance_lock("sparkd")
    if lock_file is None:
        return

    print(f"sparkd listening on http://127.0.0.1:{PORT}")
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    stop_event = False

    def _shutdown(signum=None, frame=None):
        nonlocal stop_event
        if stop_event:
            return
        stop_event = True
        print("\n[SPARK] sparkd shutting down...")
        server.shutdown()

    try:
        import signal
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)
    except Exception:
        pass
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
