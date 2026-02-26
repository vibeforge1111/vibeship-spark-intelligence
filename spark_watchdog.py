#!/usr/bin/env python3
# ruff: noqa: S603,S607
"""Lightweight Spark watchdog: restarts critical workers and warns on queue growth."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Optional
from urllib import request

from lib.ports import (
    MIND_HEALTH_URL,
    PULSE_DOCS_URL,
    PULSE_UI_URL,
    SPARKD_HEALTH_URL,
)


SPARK_DIR = Path(__file__).resolve().parent
LOG_DIR = Path.home() / ".spark" / "logs"
STATE_FILE = Path.home() / ".spark" / "watchdog_state.json"
PID_FILE = Path.home() / ".spark" / "pids" / "watchdog.pid"
PLUGIN_ONLY_SENTINEL = Path.home() / ".spark" / "plugin_only_mode"
PLUGIN_ONLY_SKIP_RESTARTS = {"bridge_worker", "pulse"}

# OpenClaw integration: keep the OpenClaw tailer alive whenever OpenClaw Gateway is running.
# (Does not require core ownership; safe to run in plugin-only mode.)
OPENCLAW_GW_KEYWORDS = ["openclaw.mjs gateway", "openclaw gateway"]

LOG_MAX_BYTES = int(os.environ.get("SPARK_LOG_MAX_BYTES", "10485760"))
LOG_BACKUPS = int(os.environ.get("SPARK_LOG_BACKUPS", "5"))


def _check_single_instance() -> bool:
    """Ensure only one watchdog runs. Returns True if we can proceed, False if another is running."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Fast path: if *any* other watchdog process is already present, exit.
    # Relying only on PID_FILE is racy (simultaneous startups can both proceed).
    try:
        snapshot = _process_snapshot()
        for pid, cmd in snapshot:
            if pid == os.getpid():
                continue
            if (
                "-m spark_watchdog" in cmd
                or "spark_watchdog.py" in cmd
                or "scripts/watchdog.py" in cmd
            ):
                return False
    except Exception:
        # Fall back to PID file heuristics below.
        pass

    def _pid_is_watchdog(pid: int) -> bool:
        snapshot = _process_snapshot()
        for spid, cmd in snapshot:
            if spid != pid:
                continue
            if (
                "-m spark_watchdog" in cmd
                or "spark_watchdog.py" in cmd
                or "scripts/watchdog.py" in cmd
            ):
                return True
        return False

    # Check if another watchdog is already running
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            if old_pid == os.getpid():
                return True
            # Check if that process is still alive
            if os.name == "nt":
                out = subprocess.check_output(
                    ["tasklist", "/FI", f"PID eq {old_pid}"],
                    text=True,
                    errors="ignore",
                )
                if str(old_pid) in out and _pid_is_watchdog(old_pid):
                    return False  # Another watchdog is running
            else:
                try:
                    os.kill(old_pid, 0)
                    if _pid_is_watchdog(old_pid):
                        return False  # Another watchdog is running
                except ProcessLookupError:
                    pass  # Process doesn't exist, we can proceed
        except Exception:
            pass  # Couldn't read/parse PID, proceed anyway

    # Write our PID
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _cleanup_pid_file() -> None:
    """Remove PID file on exit."""
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _rewrite_pid_file() -> None:
    """Best-effort PID refresh so operators don't get stuck with stale PIDs after a crash/duplicate exit."""
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass


def _ensure_log_dir() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[watchdog] {ts} {msg}"
    try:
        _ensure_log_dir()
        log_path = LOG_DIR / "watchdog.log"
        _rotate_log(log_path, LOG_MAX_BYTES, LOG_BACKUPS)
        with open(log_path, "a", encoding="utf-8", errors="replace") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)


def _http_ok(url: str, timeout: float = 1.5) -> bool:
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _rotate_log(path: Path, max_bytes: int, backups: int) -> None:
    if max_bytes <= 0 or backups <= 0:
        return
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
    except Exception:
        return

    try:
        for i in range(backups - 1, 0, -1):
            src = path.with_name(f"{path.name}.{i}")
            dst = path.with_name(f"{path.name}.{i + 1}")
            if src.exists():
                if dst.exists():
                    dst.unlink(missing_ok=True)
                src.replace(dst)
        first = path.with_name(f"{path.name}.1")
        if first.exists():
            first.unlink(missing_ok=True)
        path.replace(first)
    except Exception:
        return


def _process_snapshot() -> list[tuple[int, str]]:
    if os.name == "nt":
        try:
            out = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
                ],
                text=True,
                errors="ignore",
            )
            data = json.loads(out) if out.strip() else []
            if isinstance(data, dict):
                data = [data]
            snapshot = []
            for row in data or []:
                try:
                    pid = int(row.get("ProcessId") or 0)
                except Exception:
                    pid = 0
                cmd = row.get("CommandLine") or ""
                if pid:
                    snapshot.append((pid, cmd))
            return snapshot
        except Exception:
            return []
    try:
        out = subprocess.check_output(
            ["ps", "-ax", "-o", "pid=,command="],
            text=True,
            errors="ignore",
        )
        snapshot = []
        for line in out.splitlines():
            parts = line.strip().split(None, 1)
            if not parts:
                continue
            try:
                pid = int(parts[0])
            except Exception:
                continue
            cmd = parts[1] if len(parts) > 1 else ""
            snapshot.append((pid, cmd))
        return snapshot
    except Exception:
        return []


def _find_pids_by_keywords(keywords: list[str], snapshot: Optional[list[tuple[int, str]]] = None) -> list[int]:
    if not keywords:
        return []
    if snapshot is None:
        snapshot = _process_snapshot()
    matches = []
    for pid, cmd in snapshot:
        if all(k in cmd for k in keywords):
            matches.append(pid)
    return matches


def _find_pids_by_any_keywords(
    keyword_sets: list[list[str]],
    snapshot: Optional[list[tuple[int, str]]] = None,
) -> list[int]:
    """Find PIDs matching any keyword set, where each set is AND-matched."""
    if not keyword_sets:
        return []
    if snapshot is None:
        snapshot = _process_snapshot()
    matches: set[int] = set()
    for keywords in keyword_sets:
        for pid in _find_pids_by_keywords(keywords, snapshot):
            matches.add(pid)
    return sorted(matches)


def _pulse_keyword_sets() -> list[list[str]]:
    sets: list[list[str]] = [["vibeship-spark-pulse", "app.py"]]
    try:
        from lib.service_control import SPARK_PULSE_DIR
    except Exception:
        return sets

    app_path = SPARK_PULSE_DIR / "app.py"
    app_str = str(app_path)
    sets.append([SPARK_PULSE_DIR.name, "app.py"])
    sets.append([app_str])
    app_posix = app_str.replace("\\", "/")
    if app_posix != app_str:
        sets.append([app_posix])

    deduped: list[list[str]] = []
    for item in sets:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _process_exists(keywords: list[str], snapshot: Optional[list[tuple[int, str]]] = None) -> bool:
    return bool(_find_pids_by_keywords(keywords, snapshot))


def _openclaw_gateway_running(snapshot: Optional[list[tuple[int, str]]] = None) -> bool:
    """Best-effort detection for whether OpenClaw Gateway is running on this host."""
    if snapshot is None:
        snapshot = _process_snapshot()
    for _, cmd in snapshot:
        if not cmd:
            continue
        if any(k in cmd for k in OPENCLAW_GW_KEYWORDS):
            return True
    return False


def _terminate_pids(pids: list[int]) -> None:
    for pid in pids:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                os.kill(pid, 15)
        except Exception:
            continue


def _start_process(
    name: str,
    args: list[str],
    cwd: Optional[Path] = None,
    env_overrides: Optional[dict] = None,
) -> bool:
    try:
        _ensure_log_dir()
        log_path = LOG_DIR / f"{name}.log"
        env = os.environ.copy()
        env["SPARK_LOG_DIR"] = str(LOG_DIR)
        # Child services should not pop browsers on startup when managed.
        env.setdefault("SPARK_SERVICE_MODE", "1")
        if env_overrides:
            try:
                env.update({k: str(v) for k, v in env_overrides.items()})
            except Exception:
                pass
        creationflags = 0
        if os.name == "nt":
            # CREATE_NO_WINDOW (0x08000000) prevents console windows from opening
            # DETACHED_PROCESS alone is NOT enough on Windows
            CREATE_NO_WINDOW = 0x08000000
            creationflags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | CREATE_NO_WINDOW
            )
        with open(log_path, "a", encoding="utf-8", errors="replace") as log_f:
            subprocess.Popen(
                args,
                cwd=str(cwd or SPARK_DIR),
                stdout=log_f,
                stderr=log_f,
                env=env,
                creationflags=creationflags,
                start_new_session=(os.name != "nt"),
            )
        _log(f"started {name}")
        return True
    except Exception as e:
        _log(f"failed to start {name}: {e}")
        return False


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# Restart limiter: prevent infinite restart loops
MAX_RESTARTS_PER_HOUR = 5
RESTART_COOLDOWN_S = 3600  # 1 hour cooldown after hitting max restarts


def _can_restart(state: dict, service: str) -> bool:
    """Check if we can restart a service (not hitting restart limits)."""
    key = f"restarts_{service}"
    cooldown_key = f"cooldown_{service}"
    now = time.time()

    # Check if in cooldown period
    cooldown_until = state.get(cooldown_key, 0)
    if now < cooldown_until:
        return False

    # Get restart history (list of timestamps)
    restarts = state.get(key, [])

    # Filter to only last hour
    one_hour_ago = now - 3600
    recent_restarts = [t for t in restarts if t > one_hour_ago]

    return len(recent_restarts) < MAX_RESTARTS_PER_HOUR


def _record_restart(state: dict, service: str) -> None:
    """Record a restart attempt for rate limiting."""
    key = f"restarts_{service}"
    cooldown_key = f"cooldown_{service}"
    now = time.time()

    # Get restart history
    restarts = state.get(key, [])

    # Filter to only last hour and add new one
    one_hour_ago = now - 3600
    restarts = [t for t in restarts if t > one_hour_ago]
    restarts.append(now)

    state[key] = restarts

    # If we hit the limit, set cooldown
    if len(restarts) >= MAX_RESTARTS_PER_HOUR:
        state[cooldown_key] = now + RESTART_COOLDOWN_S
        _log(f"{service} hit max restarts ({MAX_RESTARTS_PER_HOUR}/hour), entering 1-hour cooldown")


def _queue_counts() -> tuple[int, int]:
    sys.path.insert(0, str(SPARK_DIR))
    from lib.queue import count_events
    from lib.pattern_detection.worker import get_pattern_backlog

    return count_events(), get_pattern_backlog()


def _bridge_heartbeat_age() -> Optional[float]:
    sys.path.insert(0, str(SPARK_DIR))
    from lib.bridge_cycle import bridge_heartbeat_age_s

    return bridge_heartbeat_age_s()


def _scheduler_heartbeat_age() -> Optional[float]:
    sys.path.insert(0, str(SPARK_DIR))
    from spark_scheduler import scheduler_heartbeat_age_s

    return scheduler_heartbeat_age_s()


def _plugin_only_mode_enabled() -> bool:
    env = (os.environ.get("SPARK_PLUGIN_ONLY") or "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    return PLUGIN_ONLY_SENTINEL.exists()


def _restart_allowed(service: str, plugin_only_mode: bool) -> bool:
    if not plugin_only_mode:
        return True
    return service not in PLUGIN_ONLY_SKIP_RESTARTS


def _env_disabled(service: str) -> bool:
    """Allow operators to disable watchdog management for specific services."""
    v = None
    if service == "pulse":
        v = os.environ.get("SPARK_NO_PULSE")
    elif service == "sparkd":
        v = os.environ.get("SPARK_NO_SPARKD")
    elif service == "bridge_worker":
        v = os.environ.get("SPARK_NO_BRIDGE_WORKER")
    elif service == "scheduler":
        v = os.environ.get("SPARK_NO_SCHEDULER")
    elif service == "mind":
        v = os.environ.get("SPARK_NO_MIND")
    elif service == "openclaw_tailer":
        v = os.environ.get("SPARK_NO_OPENCLAW_TAILER")
    if v is None:
        return False
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=60, help="seconds between checks")
    ap.add_argument("--max-queue", type=int, default=500, help="warn if queue exceeds this")
    ap.add_argument("--queue-warn-mins", type=int, default=5, help="minutes before warning")
    ap.add_argument("--bridge-stale-s", type=int, default=90, help="heartbeat stale threshold")
    ap.add_argument("--fail-threshold", type=int, default=3, help="consecutive failed checks before restart")
    ap.add_argument("--once", action="store_true", help="run one check and exit")
    ap.add_argument("--no-restart", action="store_true", help="only report, never restart")
    ap.add_argument("--startup-delay", type=int, default=15, help="seconds to wait before first check (grace period for services to start)")
    args = ap.parse_args()

    plugin_only_mode = _plugin_only_mode_enabled()

    _ensure_log_dir()

    # Prevent multiple watchdogs from running simultaneously
    if not _check_single_instance():
        _log("another watchdog is already running, exiting")
        sys.exit(0)

    import atexit
    atexit.register(_cleanup_pid_file)

    _log("watchdog started")
    if plugin_only_mode:
        blocked = ", ".join(sorted(PLUGIN_ONLY_SKIP_RESTARTS))
        _log(f"plugin-only mode enabled: suppressing restarts for {blocked}")

    # Grace period: wait for other services to fully start before checking
    # This prevents race condition where watchdog starts spawning services
    # that are still initializing from `spark up`
    if args.startup_delay > 0 and not args.once:
        _log(f"waiting {args.startup_delay}s startup grace period...")
        time.sleep(args.startup_delay)
        _log("grace period complete, starting health checks")

    state = _load_state()
    over_since = float(state.get("queue_over_since") or 0.0)
    last_warn = float(state.get("queue_last_warn") or 0.0)
    failures = state.get("failures", {})

    stop_event = threading.Event()

    def _shutdown(signum=None, frame=None):
        stop_event.set()

    try:
        import signal
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)
    except Exception:
        pass

    while not stop_event.is_set():
        _rewrite_pid_file()
        snapshot = _process_snapshot()

        def _bump_fail(name: str, ok: bool) -> int:
            if ok:
                failures[name] = 0
            else:
                failures[name] = int(failures.get(name, 0)) + 1
            return failures.get(name, 0)

        # mind
        manage_mind = _restart_allowed("mind", plugin_only_mode) and not _env_disabled("mind")
        mind_ok = _http_ok(MIND_HEALTH_URL, timeout=3.0)
        mind_fail = _bump_fail("mind", mind_ok or not manage_mind)
        if manage_mind and (not mind_ok):
            mind_pids = _find_pids_by_any_keywords(
                [["mind_server.py"], ["lite_tier"], ["mind.serve"]],
                snapshot,
            )
            if mind_pids and mind_fail < args.fail_threshold:
                _log(f"mind unhealthy (fail {mind_fail}/{args.fail_threshold}) but process exists")
            elif not args.no_restart and _can_restart(state, "mind"):
                if mind_pids:
                    _terminate_pids(mind_pids)
                if _start_process("mind", [sys.executable, str(SPARK_DIR / "mind_server.py")]):
                    _record_restart(state, "mind")
                    failures["mind"] = 0

        # sparkd
        manage_sparkd = _restart_allowed("sparkd", plugin_only_mode) and not _env_disabled("sparkd")
        sparkd_ok = _http_ok(SPARKD_HEALTH_URL)
        sparkd_fail = _bump_fail("sparkd", sparkd_ok or not manage_sparkd)
        if manage_sparkd and (not sparkd_ok):
            # Match either invocation style:
            # - python -m sparkd
            # - python sparkd.py
            sparkd_pids = _find_pids_by_any_keywords(
                [["sparkd.py"], ["-m sparkd"]],
                snapshot,
            )
            if sparkd_pids and sparkd_fail < args.fail_threshold:
                _log(f"sparkd unhealthy (fail {sparkd_fail}/{args.fail_threshold}) but process exists")
            elif not args.no_restart and _can_restart(state, "sparkd"):
                if sparkd_pids:
                    _terminate_pids(sparkd_pids)
                if _start_process("sparkd", [sys.executable, "-m", "sparkd"]):
                    _record_restart(state, "sparkd")
                    failures["sparkd"] = 0

        # spark pulse -- unified startup via service_control
        manage_pulse = _restart_allowed("pulse", plugin_only_mode) and not _env_disabled("pulse")
        pulse_ok = _http_ok(PULSE_DOCS_URL, timeout=2.0) and _http_ok(PULSE_UI_URL, timeout=2.0)
        pulse_fail = _bump_fail("pulse", pulse_ok or not manage_pulse)
        if manage_pulse and (not pulse_ok):
            # Check PID file first (covers external pulse started by service_control)
            try:
                from lib.service_control import _read_pid, _pid_alive, _get_pulse_command
                pulse_pid_from_file = _read_pid("pulse")
                pid_file_alive = _pid_alive(pulse_pid_from_file)
            except Exception:
                pulse_pid_from_file = None
                pid_file_alive = False

            # Search by command patterns for external pulse only.
            pulse_pids = _find_pids_by_any_keywords(_pulse_keyword_sets(), snapshot)
            pulse_running = pid_file_alive or bool(pulse_pids)

            if pulse_running and pulse_fail < args.fail_threshold:
                _log(f"pulse unhealthy (fail {pulse_fail}/{args.fail_threshold}) but process exists")
            elif not args.no_restart and _can_restart(state, "pulse"):
                all_pulse_pids = set(pulse_pids)
                if pulse_pid_from_file and _pid_alive(pulse_pid_from_file):
                    all_pulse_pids.add(pulse_pid_from_file)
                if all_pulse_pids:
                    _terminate_pids(list(all_pulse_pids))
                try:
                    from lib.service_control import SPARK_PULSE_DIR
                    pulse_cmd = _get_pulse_command()
                except FileNotFoundError as fnf:
                    _log(f"pulse not available: {fnf}")
                    pulse_cmd = None
                except Exception:
                    pulse_cmd = None
                if pulse_cmd and _start_process("pulse", pulse_cmd, cwd=SPARK_PULSE_DIR):
                    _record_restart(state, "pulse")
                    failures["pulse"] = 0

        # bridge_worker
        manage_bridge = _restart_allowed("bridge_worker", plugin_only_mode) and not _env_disabled("bridge_worker")
        hb_age = _bridge_heartbeat_age()
        bridge_ok = hb_age is not None and hb_age <= args.bridge_stale_s
        bridge_fail = _bump_fail("bridge_worker", bridge_ok or not manage_bridge)
        if manage_bridge and (not bridge_ok):
            bridge_pids = _find_pids_by_any_keywords(
                [["bridge_worker.py"], ["-m bridge_worker"]],
                snapshot,
            )
            if bridge_pids and bridge_fail < args.fail_threshold:
                _log(f"bridge_worker heartbeat stale (fail {bridge_fail}/{args.fail_threshold}) but process exists")
            elif not args.no_restart and _can_restart(state, "bridge_worker"):
                if bridge_pids:
                    _terminate_pids(bridge_pids)
                if _start_process(
                    "bridge_worker",
                    [sys.executable, "-m", "bridge_worker", "--interval", "30"],
                ):
                    _record_restart(state, "bridge_worker")
                    failures["bridge_worker"] = 0

        # scheduler (heartbeat-based, longer stale threshold)
        sched_stale_s = args.bridge_stale_s * 2
        sched_hb = _scheduler_heartbeat_age()
        sched_ok = sched_hb is not None and sched_hb <= sched_stale_s
        sched_fail = _bump_fail("scheduler", sched_ok)
        if not sched_ok:
            manage_sched = _restart_allowed("scheduler", plugin_only_mode) and not _env_disabled("scheduler")
            if not manage_sched:
                pass
            else:
                sched_pids = _find_pids_by_keywords(["spark_scheduler.py"], snapshot)
                if sched_pids and sched_fail < args.fail_threshold:
                    _log(f"scheduler heartbeat stale (fail {sched_fail}/{args.fail_threshold}) but process exists")
                elif not args.no_restart and _can_restart(state, "scheduler"):
                    if sched_pids:
                        _terminate_pids(sched_pids)
                    if _start_process(
                        "scheduler",
                        [sys.executable, str(SPARK_DIR / "spark_scheduler.py")],
                    ):
                        _record_restart(state, "scheduler")
                        failures["scheduler"] = 0

        # openclaw_tailer (integration adapter)
        # If OpenClaw Gateway is up, keep the OpenClaw->Spark tailer alive so Spark can learn from sessions.
        try:
            openclaw_up = _openclaw_gateway_running(snapshot)
            manage_tailer = openclaw_up and not _env_disabled("openclaw_tailer")

            tailer_pids = _find_pids_by_keywords(["openclaw_tailer.py"], snapshot)
            tailer_ok = bool(tailer_pids)
            tailer_fail = _bump_fail("openclaw_tailer", tailer_ok or not manage_tailer)

            # Enforce single instance (duplicate tailers can contend on offset state).
            if len(tailer_pids) > 1 and not args.no_restart:
                keep = tailer_pids[0]
                extras = [p for p in tailer_pids[1:] if p != keep]
                if extras:
                    _terminate_pids(extras)
                    _log(f"openclaw_tailer multiple instances detected; terminated extras: {extras}")

            if manage_tailer and (not tailer_ok):
                if tailer_fail < args.fail_threshold:
                    _log(f"openclaw_tailer missing (fail {tailer_fail}/{args.fail_threshold}); waiting")
                elif not args.no_restart and _can_restart(state, "openclaw_tailer"):
                    sparkd_port = os.environ.get("SPARKD_PORT", "8787")
                    sparkd_url = f"http://127.0.0.1:{sparkd_port}"
                    hb_env = {}
                    # Enable tailer heartbeat by default (low frequency) unless operator overrides.
                    if "SPARK_OPENCLAW_HEARTBEAT" not in os.environ:
                        hb_env["SPARK_OPENCLAW_HEARTBEAT"] = "1"
                    if "SPARK_OPENCLAW_HEARTBEAT_MINUTES" not in os.environ:
                        hb_env["SPARK_OPENCLAW_HEARTBEAT_MINUTES"] = "15"

                    if _start_process(
                        "openclaw_tailer",
                        [
                            sys.executable,
                            str(SPARK_DIR / "adapters" / "openclaw_tailer.py"),
                            "--sparkd",
                            sparkd_url,
                            "--agent",
                            "main",
                            "--include-subagents",
                        ],
                        cwd=SPARK_DIR,
                        env_overrides=hb_env,
                    ):
                        _record_restart(state, "openclaw_tailer")
                        failures["openclaw_tailer"] = 0
        except Exception as e:
            _log(f"openclaw_tailer check failed: {e}")

        # queue pressure warning
        try:
            queue_count, backlog = _queue_counts()
            if queue_count > args.max_queue:
                now = time.time()
                if over_since <= 0:
                    over_since = now
                if now - over_since >= args.queue_warn_mins * 60:
                    if now - last_warn >= 60:
                        _log(f"queue high: {queue_count} events (backlog {backlog})")
                        last_warn = now
            else:
                over_since = 0.0
        except Exception as e:
            _log(f"queue check failed: {e}")

        state["queue_over_since"] = over_since
        state["queue_last_warn"] = last_warn
        state["failures"] = failures
        _save_state(state)

        if args.once:
            break
        stop_event.wait(max(10, int(args.interval)))


if __name__ == "__main__":
    main()
