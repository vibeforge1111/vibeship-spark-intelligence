"""
spark doctor — comprehensive system diagnostics and optional repair.

Check categories:
  1. Environment (Python, pip, git, repo structure)
  2. Services (sparkd, bridge_worker, mind, pulse, watchdog)
  3. Hooks (Claude Code / Cursor hook config)
  4. Queue & Pipeline (event queue, bridge heartbeat)
  5. Advisory Readiness (cognitive store, advisory engine)
  6. Config Integrity (tuneables schema, drift)

Usage:
  spark doctor              # quick diagnostics
  spark doctor --deep       # full deep check (slower)
  spark doctor --repair     # attempt safe auto-repair
  spark doctor --json       # machine-readable output
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ── Spark imports (lazy where possible to keep startup fast) ──

SPARK_DIR = Path.home() / ".spark"


@dataclass
class Check:
    """Single diagnostic check result."""
    id: str
    category: str
    status: str  # "pass", "warn", "fail", "skip"
    message: str
    details: str = ""
    repair_cmd: str = ""
    repaired: bool = False


@dataclass
class DoctorResult:
    """Full doctor run output."""
    ok: bool = True
    command: str = "doctor"
    checks: list[Check] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    repaired_count: int = 0

    def add(self, check: Check):
        self.checks.append(check)
        if check.status == "fail":
            self.ok = False
            if check.repair_cmd:
                self.actions.append({
                    "label": check.message,
                    "command": check.repair_cmd,
                    "safe": True,
                })

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "command": self.command,
            "checks": [asdict(c) for c in self.checks],
            "actions": self.actions,
            "errors": self.errors,
            "repaired_count": self.repaired_count,
        }


# ── Category 1: Environment ──

def _check_python(result: DoctorResult):
    ver = sys.version_info
    if ver >= (3, 10):
        result.add(Check(
            id="python_version",
            category="environment",
            status="pass",
            message=f"Python {ver.major}.{ver.minor}.{ver.micro}",
        ))
    else:
        result.add(Check(
            id="python_version",
            category="environment",
            status="fail",
            message=f"Python {ver.major}.{ver.minor} — need 3.10+",
            details="Spark requires Python 3.10 or higher.",
        ))


def _check_git(result: DoctorResult):
    git = shutil.which("git")
    if git:
        result.add(Check(
            id="git_installed",
            category="environment",
            status="pass",
            message="git available",
        ))
    else:
        result.add(Check(
            id="git_installed",
            category="environment",
            status="warn",
            message="git not found on PATH",
            details="Git is needed for updates and hook scripts.",
        ))


def _check_spark_dir(result: DoctorResult):
    if SPARK_DIR.exists():
        result.add(Check(
            id="spark_dir",
            category="environment",
            status="pass",
            message=f"~/.spark/ exists ({SPARK_DIR})",
        ))
    else:
        result.add(Check(
            id="spark_dir",
            category="environment",
            status="fail",
            message="~/.spark/ directory missing",
            details="Created automatically on first `spark up`.",
            repair_cmd="spark up",
        ))


def _check_repo_structure(result: DoctorResult):
    """Verify key repo files exist."""
    repo_root = Path(__file__).resolve().parent.parent
    required = ["spark/cli.py", "hooks/observe.py", "lib/ports.py", "config/tuneables.json"]
    missing = [f for f in required if not (repo_root / f).exists()]
    if not missing:
        result.add(Check(
            id="repo_structure",
            category="environment",
            status="pass",
            message="Repo structure intact",
        ))
    else:
        result.add(Check(
            id="repo_structure",
            category="environment",
            status="fail",
            message=f"Missing repo files: {', '.join(missing)}",
            details="Repo may be incomplete. Try git pull or re-clone.",
        ))


# ── Category 2: Services ──

def _check_services(result: DoctorResult):
    """Check service health using existing service_control."""
    try:
        from lib.service_control import service_status
        status = service_status(include_pulse_probe=True)
    except Exception as e:
        result.add(Check(
            id="services_load",
            category="services",
            status="fail",
            message=f"Cannot load service_control: {e}",
        ))
        return

    for name in ["sparkd", "bridge_worker"]:
        svc = status.get(name, {})
        running = svc.get("running", False)
        healthy = svc.get("healthy", False)
        if running and (healthy or name == "bridge_worker"):
            msg = f"{name}: running"
            if name == "bridge_worker":
                hb = svc.get("heartbeat_age_s")
                if hb is not None:
                    msg += f" (heartbeat {int(hb)}s ago)"
            result.add(Check(
                id=f"service_{name}",
                category="services",
                status="pass",
                message=msg,
            ))
        elif running and not healthy:
            result.add(Check(
                id=f"service_{name}",
                category="services",
                status="warn",
                message=f"{name}: running but not healthy",
                repair_cmd=f"spark down && spark up",
            ))
        else:
            result.add(Check(
                id=f"service_{name}",
                category="services",
                status="fail",
                message=f"{name}: not running",
                repair_cmd="spark up",
            ))

    # Optional services — warn only
    for name in ["mind", "pulse", "watchdog"]:
        svc = status.get(name, {})
        running = svc.get("running", False)
        if running:
            result.add(Check(
                id=f"service_{name}",
                category="services",
                status="pass",
                message=f"{name}: running",
            ))
        else:
            result.add(Check(
                id=f"service_{name}",
                category="services",
                status="skip",
                message=f"{name}: not running (optional)",
                details=f"Start with: spark up (or spark up --lite to skip)",
            ))


# ── Category 3: Hooks ──

def _check_hooks(result: DoctorResult):
    """Check if Claude Code hooks are configured."""
    claude_settings = Path.home() / ".claude" / "settings.json"
    if not claude_settings.exists():
        result.add(Check(
            id="hook_settings_file",
            category="hooks",
            status="warn",
            message="~/.claude/settings.json not found",
            details="Create it by running: scripts/install_claude_hooks.ps1 (Windows) or scripts/install_claude_hooks.sh (Mac/Linux)",
        ))
        return

    try:
        settings = json.loads(claude_settings.read_text(encoding="utf-8"))
    except Exception as e:
        result.add(Check(
            id="hook_settings_parse",
            category="hooks",
            status="fail",
            message=f"Cannot parse settings.json: {e}",
        ))
        return

    hooks = settings.get("hooks", {})
    required_events = ["PreToolUse", "PostToolUse", "PostToolUseFailure"]
    found_events = []
    observe_found = False

    for event in required_events:
        event_hooks = hooks.get(event, [])
        if event_hooks:
            found_events.append(event)
            # Check if any hook references observe.py
            for matcher_block in event_hooks:
                for hook in matcher_block.get("hooks", []):
                    cmd = hook.get("command", "")
                    if "observe.py" in cmd:
                        observe_found = True

    if len(found_events) == len(required_events) and observe_found:
        result.add(Check(
            id="hook_config",
            category="hooks",
            status="pass",
            message=f"Claude Code hooks configured ({len(found_events)}/{len(required_events)} events)",
        ))
    elif found_events:
        missing = set(required_events) - set(found_events)
        result.add(Check(
            id="hook_config",
            category="hooks",
            status="warn",
            message=f"Hooks partially configured (missing: {', '.join(missing)})",
            details="Re-run hook installer and merge into settings.json",
        ))
    else:
        result.add(Check(
            id="hook_config",
            category="hooks",
            status="fail",
            message="No Spark hooks in settings.json",
            details="Run: scripts/install_claude_hooks.ps1 (Windows) or scripts/install_claude_hooks.sh (Mac/Linux), then merge spark-hooks.json into settings.json",
        ))

    # Check if observe.py path is valid
    if observe_found:
        for event in required_events:
            for matcher_block in hooks.get(event, []):
                for hook in matcher_block.get("hooks", []):
                    cmd = hook.get("command", "")
                    if "observe.py" in cmd:
                        # Extract path from command
                        parts = cmd.split()
                        for part in parts:
                            if "observe.py" in part:
                                observe_path = Path(part.strip('"').strip("'"))
                                if observe_path.exists():
                                    result.add(Check(
                                        id="hook_observe_path",
                                        category="hooks",
                                        status="pass",
                                        message="observe.py path valid",
                                    ))
                                else:
                                    result.add(Check(
                                        id="hook_observe_path",
                                        category="hooks",
                                        status="fail",
                                        message=f"observe.py not found at: {observe_path}",
                                        details="Re-run hook installer to regenerate with correct path",
                                    ))
                                return


# ── Category 4: Queue & Pipeline ──

def _check_queue(result: DoctorResult):
    """Check event queue health."""
    try:
        from lib.queue import get_queue_stats
        stats = get_queue_stats()
        count = stats.get("event_count", 0)
        size_mb = stats.get("size_mb", 0) or (stats.get("size_bytes", 0) / (1024 * 1024))

        if count > 0:
            result.add(Check(
                id="queue_events",
                category="queue",
                status="pass",
                message=f"Event queue: {count} events ({size_mb:.1f} MB)",
            ))
        else:
            result.add(Check(
                id="queue_events",
                category="queue",
                status="warn",
                message="Event queue: 0 events",
                details="Normal if you haven't run any tool interactions yet. Events appear after first Claude Code session with hooks.",
            ))

        if size_mb > 8:
            result.add(Check(
                id="queue_size",
                category="queue",
                status="warn",
                message=f"Queue size large ({size_mb:.1f} MB) — rotation may be needed",
                repair_cmd="spark process --drain",
            ))
    except Exception as e:
        result.add(Check(
            id="queue_load",
            category="queue",
            status="fail",
            message=f"Cannot read queue: {e}",
        ))

    # Check bridge heartbeat
    try:
        from lib.bridge_cycle import bridge_heartbeat_age_s
        hb_age = bridge_heartbeat_age_s()
        if hb_age is not None and hb_age < 120:
            result.add(Check(
                id="bridge_heartbeat",
                category="queue",
                status="pass",
                message=f"Bridge worker heartbeat: {int(hb_age)}s ago",
            ))
        elif hb_age is not None:
            result.add(Check(
                id="bridge_heartbeat",
                category="queue",
                status="warn",
                message=f"Bridge worker heartbeat stale: {int(hb_age)}s ago",
                repair_cmd="spark up",
            ))
        else:
            result.add(Check(
                id="bridge_heartbeat",
                category="queue",
                status="warn",
                message="No bridge worker heartbeat found",
                details="Bridge worker may not have run yet. Start with: spark up",
                repair_cmd="spark up",
            ))
    except Exception:
        pass


# ── Category 5: Advisory Readiness ──

def _check_advisory(result: DoctorResult):
    """Check advisory system readiness."""
    try:
        from lib.cognitive_learner import get_cognitive_learner
        cognitive = get_cognitive_learner()
        stats = cognitive.get_stats()
        total = stats.get("total_insights", 0)
        avg_rel = stats.get("avg_reliability", 0)

        if total > 0:
            result.add(Check(
                id="cognitive_store",
                category="advisory",
                status="pass",
                message=f"Cognitive store: {total} insights (avg reliability {avg_rel:.0%})",
            ))
        else:
            result.add(Check(
                id="cognitive_store",
                category="advisory",
                status="warn",
                message="Cognitive store: empty",
                details="Insights accumulate over time from your coding sessions. Keep using your agent normally.",
            ))
    except Exception as e:
        result.add(Check(
            id="cognitive_store",
            category="advisory",
            status="fail",
            message=f"Cannot load cognitive store: {e}",
        ))

    # Check for stale lock file
    lock_file = SPARK_DIR / ".cognitive.lock"
    if lock_file.exists():
        try:
            lock_age = time.time() - lock_file.stat().st_mtime
            if lock_age > 300:  # 5 minutes
                result.add(Check(
                    id="cognitive_lock",
                    category="advisory",
                    status="warn",
                    message=f"Stale .cognitive.lock ({int(lock_age)}s old)",
                    details="This can block cognitive saves. Safe to delete if no Spark process is running.",
                    repair_cmd="",  # handled by repair logic
                ))
        except Exception:
            pass

    # Check advisory engine enabled
    adv_enabled = os.environ.get("SPARK_ADVISORY_ENGINE", "1") != "0"
    if adv_enabled:
        result.add(Check(
            id="advisory_engine",
            category="advisory",
            status="pass",
            message="Advisory engine: enabled",
        ))
    else:
        result.add(Check(
            id="advisory_engine",
            category="advisory",
            status="warn",
            message="Advisory engine: disabled (SPARK_ADVISORY_ENGINE=0)",
            details="Set SPARK_ADVISORY_ENGINE=1 to enable pre-tool advice.",
        ))


# ── Category 6: Config Integrity ──

def _check_config(result: DoctorResult):
    """Check tuneables config integrity."""
    runtime_config = SPARK_DIR / "tuneables.json"
    repo_root = Path(__file__).resolve().parent.parent
    versioned_config = repo_root / "config" / "tuneables.json"

    if runtime_config.exists():
        try:
            data = json.loads(runtime_config.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                sections = len(data)
                result.add(Check(
                    id="config_runtime",
                    category="config",
                    status="pass",
                    message=f"Runtime tuneables: {sections} sections ({runtime_config})",
                ))
            else:
                result.add(Check(
                    id="config_runtime",
                    category="config",
                    status="fail",
                    message="Runtime tuneables: invalid format (not a JSON object)",
                    repair_cmd="spark config validate",
                ))
        except json.JSONDecodeError as e:
            result.add(Check(
                id="config_runtime",
                category="config",
                status="fail",
                message=f"Runtime tuneables: invalid JSON — {e}",
                details=f"File: {runtime_config}",
            ))
    else:
        result.add(Check(
            id="config_runtime",
            category="config",
            status="warn",
            message="No runtime tuneables (will use versioned defaults)",
            details=f"Copy {versioned_config} to {runtime_config} to customize.",
        ))

    if versioned_config.exists():
        result.add(Check(
            id="config_versioned",
            category="config",
            status="pass",
            message="Versioned tuneables template present",
        ))
    else:
        result.add(Check(
            id="config_versioned",
            category="config",
            status="warn",
            message="Versioned tuneables template missing",
            details=f"Expected at: {versioned_config}",
        ))


# ── Deep checks (optional, slower) ──

def _deep_check_port_conflicts(result: DoctorResult):
    """Check for port conflicts."""
    from lib.ports import SPARKD_PORT, PULSE_PORT, MIND_PORT
    import socket

    for name, port in [("sparkd", SPARKD_PORT), ("pulse", PULSE_PORT), ("mind", MIND_PORT)]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(("127.0.0.1", port))
                # Port is in use — either by Spark or something else
                result.add(Check(
                    id=f"port_{name}",
                    category="ports",
                    status="pass",
                    message=f"Port {port} ({name}): in use",
                ))
        except (ConnectionRefusedError, OSError):
            result.add(Check(
                id=f"port_{name}",
                category="ports",
                status="skip",
                message=f"Port {port} ({name}): free",
                details="Service not running or port available.",
            ))


def _deep_check_recent_events(result: DoctorResult):
    """Check for recent event capture activity."""
    try:
        from lib.queue import read_recent_events
        events = read_recent_events(count=5)
        if events:
            latest = events[0]
            ts = getattr(latest, "timestamp", 0) if not isinstance(latest, dict) else latest.get("timestamp", 0)
            age_s = time.time() - ts if ts else None
            age_str = f"{int(age_s)}s ago" if age_s and age_s < 86400 else "unknown age"
            result.add(Check(
                id="recent_events",
                category="pipeline",
                status="pass",
                message=f"Recent events: {len(events)} found (latest: {age_str})",
            ))
        else:
            result.add(Check(
                id="recent_events",
                category="pipeline",
                status="warn",
                message="No recent events found",
                details="Events appear after tool interactions in a Claude Code session with hooks configured.",
            ))
    except Exception as e:
        result.add(Check(
            id="recent_events",
            category="pipeline",
            status="fail",
            message=f"Cannot read events: {e}",
        ))


# ── Repair logic ──

def _apply_repairs(result: DoctorResult) -> int:
    """Attempt safe repairs for failed checks. Returns count of repairs applied."""
    repaired = 0

    for check in result.checks:
        if check.status != "fail" and check.status != "warn":
            continue

        # Repair: stale cognitive lock
        if check.id == "cognitive_lock":
            lock_file = SPARK_DIR / ".cognitive.lock"
            if lock_file.exists():
                try:
                    lock_file.unlink()
                    check.repaired = True
                    check.details = "Stale lock file removed."
                    repaired += 1
                except Exception:
                    pass

        # Repair: missing ~/.spark/ directory
        if check.id == "spark_dir":
            try:
                SPARK_DIR.mkdir(parents=True, exist_ok=True)
                check.repaired = True
                check.details = "Created ~/.spark/ directory."
                repaired += 1
            except Exception:
                pass

    result.repaired_count = repaired
    return repaired


# ── Main entry ──

def run_doctor(deep: bool = False, repair: bool = False) -> DoctorResult:
    """Run all diagnostic checks and optionally repair."""
    result = DoctorResult()

    # Category 1: Environment
    _check_python(result)
    _check_git(result)
    _check_spark_dir(result)
    _check_repo_structure(result)

    # Category 2: Services
    _check_services(result)

    # Category 3: Hooks
    _check_hooks(result)

    # Category 4: Queue & Pipeline
    _check_queue(result)

    # Category 5: Advisory Readiness
    _check_advisory(result)

    # Category 6: Config Integrity
    _check_config(result)

    # Deep checks
    if deep:
        _deep_check_port_conflicts(result)
        _deep_check_recent_events(result)

    # Repair phase
    if repair:
        _apply_repairs(result)

    return result


def format_doctor_human(result: DoctorResult) -> str:
    """Format doctor result for human terminal output."""
    lines = []
    lines.append("")
    lines.append("=" * 56)
    lines.append("  SPARK DOCTOR")
    lines.append("=" * 56)
    lines.append("")

    # Group by category
    categories: dict[str, list[Check]] = {}
    for check in result.checks:
        categories.setdefault(check.category, []).append(check)

    category_labels = {
        "environment": "Environment",
        "services": "Services",
        "hooks": "Hook Configuration",
        "queue": "Queue & Pipeline",
        "advisory": "Advisory Readiness",
        "config": "Configuration",
        "ports": "Port Status",
        "pipeline": "Pipeline Activity",
    }

    status_icons = {
        "pass": "+",
        "warn": "!",
        "fail": "X",
        "skip": "-",
    }

    for cat_id, checks in categories.items():
        label = category_labels.get(cat_id, cat_id.title())
        lines.append(f"  [{label}]")
        for check in checks:
            icon = status_icons.get(check.status, "?")
            repaired_tag = " (repaired)" if check.repaired else ""
            lines.append(f"    [{icon}] {check.message}{repaired_tag}")
            if check.details and check.status in ("warn", "fail"):
                lines.append(f"        {check.details}")
        lines.append("")

    # Summary
    pass_count = sum(1 for c in result.checks if c.status == "pass")
    warn_count = sum(1 for c in result.checks if c.status == "warn")
    fail_count = sum(1 for c in result.checks if c.status == "fail")
    skip_count = sum(1 for c in result.checks if c.status == "skip")

    lines.append("-" * 56)
    summary_parts = [f"{pass_count} passed"]
    if warn_count:
        summary_parts.append(f"{warn_count} warnings")
    if fail_count:
        summary_parts.append(f"{fail_count} failed")
    if skip_count:
        summary_parts.append(f"{skip_count} skipped")
    if result.repaired_count:
        summary_parts.append(f"{result.repaired_count} repaired")

    verdict = "HEALTHY" if result.ok else "ISSUES FOUND"
    lines.append(f"  {verdict}: {', '.join(summary_parts)}")

    # Actions
    if result.actions:
        lines.append("")
        lines.append("  Suggested actions:")
        for action in result.actions:
            lines.append(f"    -> {action['command']}")
    lines.append("")

    return "\n".join(lines)
