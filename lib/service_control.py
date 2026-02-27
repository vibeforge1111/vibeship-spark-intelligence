#!/usr/bin/env python3
# ruff: noqa: S603,S607
"""Service control helpers for Spark daemons (mind, sparkd, bridge_worker, codex_bridge, pulse, watchdog)."""

from __future__ import annotations

import json
import importlib.util
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from urllib import request

from lib.diagnostics import _rotate_log_file, _LOG_MAX_BYTES, _LOG_BACKUPS

from lib.ports import (
    MIND_HEALTH_URL,
    PULSE_DOCS_URL,
    PULSE_UI_URL,
    PULSE_URL,
    SPARKD_HEALTH_URL,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
REPO_ENV_FILE = ROOT_DIR / ".env"


def _resolve_pulse_dir() -> Path:
    env_value = os.environ.get("SPARK_PULSE_DIR")
    if env_value:
        return Path(env_value).expanduser()

    candidates = [
        ROOT_DIR.parent / "vibeship-spark-pulse",
    ]
    for candidate in candidates:
        if (candidate / "app.py").exists():
            return candidate
    return candidates[0]


# External Spark Pulse directory (full-featured FastAPI app with neural visualization)
# This is the ONLY pulse that should run. No fallback to the primitive internal spark_pulse.py.
SPARK_PULSE_DIR = _resolve_pulse_dir()
STARTUP_READY_TIMEOUT_S = float(os.environ.get("SPARK_STARTUP_READY_TIMEOUT_S", "12"))
STARTUP_READY_POLL_S = float(os.environ.get("SPARK_STARTUP_READY_POLL_S", "0.4"))
CODEX_BRIDGE_TELEMETRY = Path.home() / ".spark" / "logs" / "codex_hook_bridge_telemetry.jsonl"


def _get_pulse_command() -> list[str]:
    """Get the command to start Spark Pulse (external vibeship-spark-pulse only)."""
    import sys
    external_app = SPARK_PULSE_DIR / "app.py"
    if external_app.exists():
        return [sys.executable, str(external_app)]
    raise FileNotFoundError(
        f"Spark Pulse not found at {external_app}. "
        f"Clone vibeship-spark-pulse to {SPARK_PULSE_DIR} or set SPARK_PULSE_DIR env var."
    )


def _pid_dir() -> Path:
    return Path.home() / ".spark" / "pids"


def _log_dir() -> Path:
    env_dir = os.environ.get("SPARK_LOG_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".spark" / "logs"


def _ensure_dirs() -> tuple[Path, Path]:
    pid_dir = _pid_dir()
    log_dir = _log_dir()
    pid_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    return pid_dir, log_dir


def _pid_file(name: str) -> Path:
    return _pid_dir() / f"{name}.pid"


def _read_pid(name: str) -> Optional[int]:
    try:
        return int(_pid_file(name).read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _write_pid(name: str, pid: int) -> None:
    _pid_file(name).write_text(str(pid), encoding="utf-8")


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}"],
                text=True,
                errors="ignore",
            )
            return str(pid) in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except Exception:
        return False


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


def _cmd_matches(cmd: str, patterns: list[list[str]]) -> bool:
    for pattern in patterns:
        if pattern and all(k in cmd for k in pattern):
            return True
    return False


def _pulse_process_patterns() -> list[list[str]]:
    app_path = SPARK_PULSE_DIR / "app.py"
    app_str = str(app_path)
    patterns: list[list[str]] = [
        [SPARK_PULSE_DIR.name, "app.py"],
        ["vibeship-spark-pulse", "app.py"],
        [app_str],
    ]
    app_posix = app_str.replace("\\", "/")
    if app_posix != app_str:
        patterns.append([app_posix])

    deduped: list[list[str]] = []
    for pattern in patterns:
        if pattern and pattern not in deduped:
            deduped.append(pattern)
    return deduped


def _pid_matches(pid: Optional[int], patterns: list[list[str]], snapshot: Optional[list[tuple[int, str]]] = None) -> bool:
    if not pid:
        return False
    if snapshot is None:
        snapshot = _process_snapshot()
    for spid, cmd in snapshot:
        if spid != pid:
            continue
        if _cmd_matches(cmd, patterns):
            return True
    return False


def _pid_alive_fallback(pid: Optional[int], snapshot: Optional[list[tuple[int, str]]] = None) -> bool:
    """Fallback when command line matching is unavailable (avoid duplicate spawns)."""
    if not pid:
        return False
    if snapshot is None:
        snapshot = _process_snapshot()
    if not snapshot:
        return _pid_alive(pid)
    for spid, cmd in snapshot:
        if spid != pid:
            continue
        if not cmd:
            return _pid_alive(pid)
        return False
    return False


def _any_process_matches(patterns: list[list[str]], snapshot: Optional[list[tuple[int, str]]] = None) -> bool:
    if not patterns:
        return False
    if snapshot is None:
        snapshot = _process_snapshot()
    for _, cmd in snapshot:
        if _cmd_matches(cmd, patterns):
            return True
    return False


def _find_pids_by_patterns(patterns: list[list[str]], snapshot: Optional[list[tuple[int, str]]] = None) -> list[int]:
    if not patterns:
        return []
    if snapshot is None:
        snapshot = _process_snapshot()
    matches = []
    for pid, cmd in snapshot:
        if _cmd_matches(cmd, patterns):
            matches.append(pid)
    return matches


def _http_ok(url: str, timeout: float = 1.5) -> bool:
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _pulse_ok() -> bool:
    """Pulse is healthy only when both app docs and UI respond."""
    return _http_ok(PULSE_DOCS_URL, timeout=2.0) and _http_ok(PULSE_UI_URL, timeout=2.0)


def _bridge_heartbeat_age() -> Optional[float]:
    from lib.bridge_cycle import bridge_heartbeat_age_s

    return bridge_heartbeat_age_s()


def _scheduler_heartbeat_age() -> Optional[float]:
    try:
        from spark_scheduler import scheduler_heartbeat_age_s

        return scheduler_heartbeat_age_s()
    except ModuleNotFoundError:
        # Support script invocations (e.g. `python scripts/...`) where repo root
        # may not be on sys.path.
        scheduler_file = ROOT_DIR / "spark_scheduler.py"
        if not scheduler_file.exists():
            return None
        try:
            spec = importlib.util.spec_from_file_location(
                "spark_scheduler_runtime",
                scheduler_file,
            )
            if spec is None or spec.loader is None:
                return None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            fn = getattr(mod, "scheduler_heartbeat_age_s", None)
            if callable(fn):
                return fn()
            return None
        except Exception:
            return None
    except Exception:
        return None


def _looks_like_codex_bridge_process(cmd: str) -> bool:
    text = str(cmd or "").strip()
    if not text:
        return False
    norm = text.lower().replace("\\", "/")
    if "codex_hook_bridge.py" not in norm:
        return False
    # Avoid false positives from introspection commands that include the string.
    if "powershell" in norm or "python -c" in norm or " -command " in norm:
        return False
    abs_script = str((ROOT_DIR / "adapters" / "codex_hook_bridge.py")).lower().replace("\\", "/")
    has_script_path = ("adapters/codex_hook_bridge.py" in norm) or (abs_script in norm)
    return has_script_path and ("--mode" in norm)


def _codex_bridge_telemetry_age() -> Optional[float]:
    if not CODEX_BRIDGE_TELEMETRY.exists():
        return None
    try:
        lines = CODEX_BRIDGE_TELEMETRY.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None
    for raw in reversed(lines[-200:]):
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        try:
            ts = float(row.get("ts"))
        except Exception:
            continue
        if ts <= 0:
            continue
        return max(0.0, time.time() - ts)
    return None


def _load_repo_env(path: Path | None = None) -> dict[str, str]:
    """Load simple KEY=VALUE pairs from repo .env file.

    This avoids requiring python-dotenv for daemon startup paths.
    """
    if path is None:
        path = REPO_ENV_FILE

    if not path.exists():
        return {}
    out: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            val = value.strip()
            if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
                val = val[1:-1]
            out[key] = val
    except Exception:
        return {}
    return out


def _env_for_child(log_dir: Path) -> dict:
    env = os.environ.copy()
    # Import repo-level .env values for daemon processes (e.g., API keys/models).
    for k, v in _load_repo_env().items():
        env.setdefault(k, v)
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("SPARK_LOG_DIR", str(log_dir))
    # Child services should not pop browsers on startup when managed.
    env.setdefault("SPARK_SERVICE_MODE", "1")
    return env


def _start_process(name: str, args: list[str], cwd: Optional[Path] = None) -> Optional[int]:
    _, log_dir = _ensure_dirs()
    log_path = log_dir / f"{name}.log"
    env = _env_for_child(log_dir)

    creationflags = 0
    if os.name == "nt":
        # CREATE_NO_WINDOW (0x08000000) prevents console windows from opening
        # DETACHED_PROCESS alone is NOT enough on Windows
        CREATE_NO_WINDOW = 0x08000000
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | CREATE_NO_WINDOW
        )

    # Rotate log before opening so external services (pulse) that lack
    # their own _RotatingFile still get bounded log files.
    _rotate_log_file(log_path, _LOG_MAX_BYTES, _LOG_BACKUPS)

    with open(log_path, "a", encoding="utf-8", errors="replace") as log_f:
        proc = subprocess.Popen(
            args,
            stdout=log_f,
            stderr=log_f,
            env=env,
            cwd=str(cwd) if cwd else None,
            creationflags=creationflags,
            start_new_session=(os.name != "nt"),
        )
    _write_pid(name, proc.pid)
    return proc.pid


def _is_service_ready(name: str, bridge_stale_s: int = 90) -> bool:
    if name == "mind":
        return _http_ok(MIND_HEALTH_URL)
    if name == "sparkd":
        return _http_ok(SPARKD_HEALTH_URL)
    if name == "pulse":
        return _pulse_ok()
    if name == "bridge_worker":
        hb_age = _bridge_heartbeat_age()
        return hb_age is not None and hb_age <= bridge_stale_s
    if name == "scheduler":
        hb_age = _scheduler_heartbeat_age()
        return hb_age is not None and hb_age <= bridge_stale_s * 2
    if name == "codex_bridge":
        pid = _read_pid("codex_bridge")
        if pid is not None:
            return _pid_alive(pid)
        hb_age = _codex_bridge_telemetry_age()
        return hb_age is not None and hb_age <= bridge_stale_s * 2
    if name == "watchdog":
        pid = _read_pid("watchdog")
        return _pid_alive(pid)
    return False


def _wait_for_service_ready(name: str, pid: Optional[int], bridge_stale_s: int = 90) -> bool:
    if not pid:
        return False

    # Services without HTTP endpoints should at least remain alive.
    if name in ("watchdog", "scheduler"):
        return _pid_alive(pid)

    deadline = time.time() + max(0.5, STARTUP_READY_TIMEOUT_S)
    while time.time() < deadline:
        if not _pid_alive(pid):
            return False
        if _is_service_ready(name, bridge_stale_s=bridge_stale_s):
            return True
        time.sleep(max(0.1, STARTUP_READY_POLL_S))

    return _is_service_ready(name, bridge_stale_s=bridge_stale_s)


def _terminate_pid(pid: int, timeout_s: float = 5.0) -> bool:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            return False
        end = time.time() + timeout_s
        while time.time() < end:
            if not _pid_alive(pid):
                return True
            time.sleep(0.2)
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            return False
        return not _pid_alive(pid)

    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        return False

    end = time.time() + timeout_s
    while time.time() < end:
        if not _pid_alive(pid):
            return True
        time.sleep(0.2)
    return not _pid_alive(pid)


def _service_cmds(
    bridge_interval: int = 30,
    bridge_query: Optional[str] = None,
    watchdog_interval: int = 60,
    include_pulse: bool = True,
    include_mind: bool = True,
    include_codex_bridge: bool = True,
) -> dict[str, Optional[list[str]]]:
    codex_mode = str(os.environ.get("SPARK_CODEX_BRIDGE_MODE", "observe") or "observe").strip().lower()
    if codex_mode not in {"shadow", "observe"}:
        codex_mode = "observe"
    codex_poll = str(os.environ.get("SPARK_CODEX_BRIDGE_POLL", "2") or "2").strip() or "2"
    codex_max_per_tick = str(os.environ.get("SPARK_CODEX_BRIDGE_MAX_PER_TICK", "200") or "200").strip() or "200"
    codex_telemetry_min_interval_s = str(
        os.environ.get("SPARK_CODEX_BRIDGE_TELEMETRY_MIN_INTERVAL_S", "10") or "10"
    ).strip() or "10"
    codex_bridge_script = ROOT_DIR / "adapters" / "codex_hook_bridge.py"

    cmds = {
        "sparkd": [sys.executable, "-m", "sparkd"],
        "bridge_worker": [
            sys.executable,
            "-m",
            "bridge_worker",
            "--interval",
            str(bridge_interval),
        ],
        "scheduler": [sys.executable, str(ROOT_DIR / "spark_scheduler.py")],
        "watchdog": [
            sys.executable,
            "-m",
            "spark_watchdog",
            "--interval",
            str(watchdog_interval),
        ],
    }
    if include_codex_bridge:
        if codex_bridge_script.exists():
            cmds["codex_bridge"] = [
                sys.executable,
                str(codex_bridge_script),
                "--mode",
                codex_mode,
                "--poll",
                codex_poll,
                "--max-per-tick",
                codex_max_per_tick,
                "--telemetry-min-interval-s",
                codex_telemetry_min_interval_s,
            ]
        else:
            cmds["codex_bridge"] = None
    if include_mind:
        cmds["mind"] = [sys.executable, str(ROOT_DIR / "mind_server.py")]
    if include_pulse:
        try:
            cmds["pulse"] = _get_pulse_command()
        except FileNotFoundError:
            cmds["pulse"] = None
    if bridge_query:
        cmds["bridge_worker"].extend(["--query", bridge_query])
    return cmds


def service_status(bridge_stale_s: int = 90, include_pulse_probe: bool = True) -> dict[str, dict]:
    mind_ok = _http_ok(MIND_HEALTH_URL)
    sparkd_ok = _http_ok(SPARKD_HEALTH_URL)
    pulse_ok = _pulse_ok() if include_pulse_probe else False
    hb_age = _bridge_heartbeat_age()

    sched_hb_age = _scheduler_heartbeat_age()

    mind_pid = _read_pid("mind")
    sparkd_pid = _read_pid("sparkd")
    pulse_pid = _read_pid("pulse")
    bridge_pid = _read_pid("bridge_worker")
    codex_bridge_pid = _read_pid("codex_bridge")
    scheduler_pid = _read_pid("scheduler")
    watchdog_pid = _read_pid("watchdog")

    snapshot = _process_snapshot()
    mind_keys = [["mind_server.py"], ["lite_tier"], ["mind.serve"]]
    sparkd_keys = [["-m sparkd"], ["sparkd.py"]]
    pulse_keys = _pulse_process_patterns()
    bridge_keys = [["-m bridge_worker"], ["bridge_worker.py"]]
    codex_bridge_keys = [["codex_hook_bridge.py"]]
    scheduler_keys = [["spark_scheduler.py"]]
    watchdog_keys = [["-m spark_watchdog"], ["spark_watchdog.py"], ["scripts/watchdog.py"]]

    mind_running = (
        mind_ok
        or _pid_matches(mind_pid, mind_keys, snapshot)
        or _any_process_matches(mind_keys, snapshot)
        or _pid_alive_fallback(mind_pid, snapshot)
    )
    sparkd_running = (
        sparkd_ok
        or _pid_matches(sparkd_pid, sparkd_keys, snapshot)
        or _any_process_matches(sparkd_keys, snapshot)
        or _pid_alive_fallback(sparkd_pid, snapshot)
    )
    pulse_running = (
        pulse_ok
        or _pid_matches(pulse_pid, pulse_keys, snapshot)
        or _any_process_matches(pulse_keys, snapshot)
    )
    bridge_process_running = (
        _pid_matches(bridge_pid, bridge_keys, snapshot)
        or _any_process_matches(bridge_keys, snapshot)
        or _pid_alive_fallback(bridge_pid, snapshot)
    )
    bridge_heartbeat_fresh = (hb_age is not None and hb_age <= bridge_stale_s)
    bridge_running = bridge_process_running or bridge_heartbeat_fresh
    codex_telemetry_age = _codex_bridge_telemetry_age()
    codex_telemetry_fresh = (
        codex_telemetry_age is not None and codex_telemetry_age <= bridge_stale_s * 2
    )
    codex_bridge_process_running = False
    if codex_bridge_pid:
        codex_bridge_process_running = (
            _pid_matches(codex_bridge_pid, codex_bridge_keys, snapshot)
            or _pid_alive_fallback(codex_bridge_pid, snapshot)
        )
    if not codex_bridge_process_running:
        codex_bridge_process_running = any(_looks_like_codex_bridge_process(cmd) for _, cmd in snapshot)
    codex_bridge_running = codex_bridge_process_running

    scheduler_process_running = (
        _pid_matches(scheduler_pid, scheduler_keys, snapshot)
        or _any_process_matches(scheduler_keys, snapshot)
        or _pid_alive_fallback(scheduler_pid, snapshot)
    )
    scheduler_heartbeat_fresh = (sched_hb_age is not None and sched_hb_age <= bridge_stale_s * 2)
    scheduler_running = scheduler_process_running or scheduler_heartbeat_fresh
    watchdog_running = (
        _pid_matches(watchdog_pid, watchdog_keys, snapshot)
        or _any_process_matches(watchdog_keys, snapshot)
        or _pid_alive_fallback(watchdog_pid, snapshot)
    )

    return {
        "mind": {
            "running": mind_running,
            "healthy": mind_ok,
            "pid": mind_pid,
        },
        "sparkd": {
            "running": sparkd_running,
            "healthy": sparkd_ok,
            "pid": sparkd_pid,
        },
        "pulse": {
            "running": pulse_running,
            "healthy": pulse_ok,
            "pid": pulse_pid,
        },
        "bridge_worker": {
            "running": bridge_running,
            "heartbeat_age_s": hb_age,
            "pid": bridge_pid,
            # Heartbeat can remain fresh briefly after a crash; do not use it as the sole
            # indicator for whether we should (re)start the worker.
            "process_running": bridge_process_running,
            "heartbeat_fresh": bridge_heartbeat_fresh,
        },
        "codex_bridge": {
            "running": codex_bridge_running,
            "telemetry_age_s": codex_telemetry_age,
            "pid": codex_bridge_pid,
            "process_running": codex_bridge_process_running,
            "telemetry_fresh": codex_telemetry_fresh,
        },
        "scheduler": {
            "running": scheduler_running,
            "heartbeat_age_s": sched_hb_age,
            "pid": scheduler_pid,
            "process_running": scheduler_process_running,
            "heartbeat_fresh": scheduler_heartbeat_fresh,
        },
        "watchdog": {
            "running": watchdog_running,
            "pid": watchdog_pid,
        },
        "log_dir": str(_log_dir()),
    }


def start_services(
    bridge_interval: int = 30,
    bridge_query: Optional[str] = None,
    watchdog_interval: int = 60,
    include_mind: bool = True,
    include_pulse: bool = True,
    include_watchdog: bool = True,
    include_codex_bridge: bool = True,
    bridge_stale_s: int = 90,
) -> dict[str, str]:
    cmds = _service_cmds(
        bridge_interval=bridge_interval,
        bridge_query=bridge_query,
        watchdog_interval=watchdog_interval,
        include_mind=include_mind,
        include_pulse=include_pulse,
        include_codex_bridge=include_codex_bridge,
    )
    statuses = service_status(bridge_stale_s=bridge_stale_s)
    results: dict[str, str] = {}

    order = ["mind", "sparkd", "bridge_worker", "codex_bridge", "scheduler", "pulse", "watchdog"]
    if not include_mind:
        order.remove("mind")
    if not include_pulse:
        order.remove("pulse")
    if not include_watchdog:
        order.remove("watchdog")
    if not include_codex_bridge:
        order.remove("codex_bridge")

    for name in order:
        current = statuses.get(name, {})
        # For background loops, a fresh heartbeat file alone is not strong enough to
        # prove a live process (it can be stale-but-recent after a crash). Prefer
        # process detection to avoid skipping restarts.
        if name in {"bridge_worker", "scheduler", "codex_bridge"}:
            if current.get("process_running"):
                results[name] = "already_running"
                continue
        elif current.get("running"):
            results[name] = "already_running"
            continue
        cmd = cmds.get(name)
        if not cmd:
            results[name] = "unavailable"
            continue
        process_cwd = SPARK_PULSE_DIR if name == "pulse" else ROOT_DIR
        pid = _start_process(name, cmd, cwd=process_cwd)
        if not pid:
            results[name] = "failed"
            continue
        ready = _wait_for_service_ready(name, pid, bridge_stale_s=bridge_stale_s)
        results[name] = f"started:{pid}" if ready else f"started_unhealthy:{pid}"

    return results


def ensure_services(
    bridge_interval: int = 30,
    bridge_query: Optional[str] = None,
    watchdog_interval: int = 60,
    include_mind: bool = True,
    include_pulse: bool = True,
    include_watchdog: bool = True,
    include_codex_bridge: bool = True,
    bridge_stale_s: int = 90,
) -> dict[str, str]:
    return start_services(
        bridge_interval=bridge_interval,
        bridge_query=bridge_query,
        watchdog_interval=watchdog_interval,
        include_mind=include_mind,
        include_pulse=include_pulse,
        include_watchdog=include_watchdog,
        include_codex_bridge=include_codex_bridge,
        bridge_stale_s=bridge_stale_s,
    )


def stop_services() -> dict[str, str]:
    results: dict[str, str] = {}
    for name in ["watchdog", "pulse", "scheduler", "codex_bridge", "bridge_worker", "sparkd", "mind"]:
        pid = _read_pid(name)
        patterns = {
            "mind": [["mind_server.py"], ["lite_tier"], ["mind.serve"]],
            "sparkd": [["-m sparkd"], ["sparkd.py"]],
            "bridge_worker": [["-m bridge_worker"], ["bridge_worker.py"]],
            "codex_bridge": [["codex_hook_bridge.py"]],
            "scheduler": [["spark_scheduler.py"]],
            "pulse": _pulse_process_patterns(),
            "watchdog": [["-m spark_watchdog"], ["spark_watchdog.py"], ["scripts/watchdog.py"]],
        }.get(name, [])

        killed_any = False
        # Processes can be restarted by a surviving watchdog while we're stopping.
        # Re-snapshot a few times to aggressively converge to "stopped".
        for _ in range(3):
            snapshot = _process_snapshot()
            matched_pids = _find_pids_by_patterns(patterns, snapshot)
            if matched_pids:
                for mpid in matched_pids:
                    if _terminate_pid(mpid):
                        killed_any = True
                time.sleep(0.15)
                continue
            break

        snapshot = _process_snapshot()
        matched_pids = _find_pids_by_patterns(patterns, snapshot)
        if matched_pids:
            results[name] = "stopped" if killed_any else "failed"
        elif killed_any:
            # We successfully terminated something earlier and nothing matches now.
            results[name] = "stopped"
        elif pid and _pid_matches(pid, patterns, snapshot):
            if _pid_alive(pid):
                ok = _terminate_pid(pid)
                killed_any = ok
                results[name] = "stopped" if ok else "failed"
            else:
                results[name] = "not_running"
        else:
            results[name] = "pid_mismatch" if pid else "no_pid"

        try:
            _pid_file(name).unlink(missing_ok=True)
        except Exception:
            pass

        # Remove heartbeat sentinels so future status checks don't treat a recent file
        # as evidence of a running background loop.
        if name == "bridge_worker":
            try:
                (Path.home() / ".spark" / "bridge_worker_heartbeat.json").unlink(missing_ok=True)
            except Exception:
                pass
        if name == "scheduler":
            try:
                spark_root = Path.home() / ".spark"
                (spark_root / "scheduler_heartbeat.json").unlink(missing_ok=True)
                (spark_root / "scheduler" / "heartbeat.json").unlink(missing_ok=True)
            except Exception:
                pass
        if name == "codex_bridge":
            try:
                (Path.home() / ".spark" / "adapters" / "codex_hook_bridge.lock").unlink(missing_ok=True)
            except Exception:
                pass
    return results


def format_status_lines(status: dict[str, dict], bridge_stale_s: int = 90) -> list[str]:
    lines: list[str] = []
    sparkd = status.get("sparkd", {})
    pulse = status.get("pulse", {})
    bridge = status.get("bridge_worker", {})
    codex_bridge = status.get("codex_bridge", {})
    scheduler = status.get("scheduler", {})
    watchdog = status.get("watchdog", {})

    mind = status.get("mind", {})
    lines.append(
        f"[spark] mind: {'RUNNING' if mind.get('running') else 'STOPPED'}"
        + (" (healthy)" if mind.get("healthy") else "")
    )
    lines.append(
        f"[spark] sparkd: {'RUNNING' if sparkd.get('running') else 'STOPPED'}"
        + (" (healthy)" if sparkd.get("healthy") else "")
    )
    lines.append(
        f"[spark] pulse: {'RUNNING' if pulse.get('running') else 'STOPPED'}"
        + (" (healthy)" if pulse.get("healthy") else "")
    )
    hb_age = bridge.get("heartbeat_age_s")
    if hb_age is None:
        if bridge.get("running"):
            lines.append("[spark] bridge_worker: RUNNING (no heartbeat)")
        else:
            lines.append("[spark] bridge_worker: UNKNOWN (no heartbeat)")
    else:
        status_label = "RUNNING" if hb_age <= bridge_stale_s else "STALE"
        lines.append(f"[spark] bridge_worker: {status_label} (last {int(hb_age)}s ago)")
    codex_age = codex_bridge.get("telemetry_age_s")
    if codex_age is None:
        lines.append(
            "[spark] codex_bridge: RUNNING (no telemetry)"
            if codex_bridge.get("running")
            else "[spark] codex_bridge: STOPPED"
        )
    else:
        if codex_bridge.get("running"):
            codex_label = "RUNNING" if codex_age <= bridge_stale_s * 2 else "STALE"
        else:
            codex_label = "STOPPED"
        lines.append(f"[spark] codex_bridge: {codex_label} (last {int(codex_age)}s ago)")
    sched_hb = scheduler.get("heartbeat_age_s")
    if sched_hb is None:
        if scheduler.get("running"):
            lines.append("[spark] scheduler: RUNNING (no heartbeat)")
        else:
            lines.append("[spark] scheduler: STOPPED")
    else:
        sched_label = "RUNNING" if sched_hb <= bridge_stale_s * 2 else "STALE"
        lines.append(f"[spark] scheduler: {sched_label} (last {int(sched_hb)}s ago)")
    lines.append(
        f"[spark] watchdog: {'RUNNING' if watchdog.get('running') else 'STOPPED'}"
    )
    log_dir = status.get("log_dir")
    if log_dir:
        lines.append(f"[spark] logs: {log_dir}")
    lines.append(
        f"[spark] pulse_dir: {SPARK_PULSE_DIR}"
        + ("" if (SPARK_PULSE_DIR / "app.py").exists() else " (app.py missing)")
    )
    lines.append(f"Spark Pulse: {PULSE_URL}")
    return lines
