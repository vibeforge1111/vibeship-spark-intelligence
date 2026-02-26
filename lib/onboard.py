"""
spark onboard — guided first-time and re-onboarding wizard.

Modes:
  spark onboard                         # interactive wizard
  spark onboard --quick --yes           # non-interactive fast path
  spark onboard --agent claude|cursor   # agent-specific
  spark onboard status                  # show progress
  spark onboard reset                   # reset onboarding state

Steps:
  1. Preflight (Python, git, repo, ~/.spark/)
  2. Service bootstrap (spark up)
  3. Health verification
  4. Agent connection (hook config check)
  5. First event proof (queue has events)
  6. Next steps summary
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

SPARK_DIR = Path.home() / ".spark"
STATE_FILE = SPARK_DIR / "onboarding_state.json"


@dataclass
class OnboardStep:
    """Single onboarding step."""
    id: str
    label: str
    status: str = "pending"  # pending, running, pass, fail, skip
    message: str = ""
    detail: str = ""


@dataclass
class OnboardState:
    """Persistent onboarding progress."""
    steps: dict[str, str] = field(default_factory=dict)  # step_id -> status
    agent: str = ""
    started_at: str = ""
    completed_at: str = ""

    def save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "OnboardState":
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                return cls(**data)
            except Exception:
                pass
        return cls()

    @classmethod
    def reset(cls):
        if STATE_FILE.exists():
            STATE_FILE.unlink()


def _print_step(step: OnboardStep, index: int):
    """Print a single step with visual indicator."""
    icons = {"pass": "+", "fail": "X", "skip": "-", "running": "~", "pending": " "}
    icon = icons.get(step.status, "?")
    print(f"  [{icon}] Step {index}: {step.label}")
    if step.message:
        print(f"      {step.message}")
    if step.detail and step.status in ("fail", "skip"):
        print(f"      {step.detail}")


def _confirm(prompt: str, default: bool = True, auto_yes: bool = False, use_json: bool = False) -> bool:
    """Simple Y/N prompt with safe defaults."""
    if auto_yes or use_json:
        return True
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{prompt} {suffix} ").strip().lower()
    except Exception:
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def _is_claude_agent(agent: str) -> bool:
    return str(agent or "").strip().lower() in ("claude", "claude_code", "claudecode")


def _step_preflight() -> OnboardStep:
    """Step 1: Environment preflight checks."""
    step = OnboardStep(id="preflight", label="Environment check")
    step.status = "running"

    issues = []

    # Python version
    if sys.version_info < (3, 10):
        issues.append(f"Python {sys.version_info.major}.{sys.version_info.minor} — need 3.10+")

    # Repo structure
    repo_root = Path(__file__).resolve().parent.parent
    required = ["spark/cli.py", "hooks/observe.py", "config/tuneables.json"]
    missing = [f for f in required if not (repo_root / f).exists()]
    if missing:
        issues.append(f"Missing files: {', '.join(missing)}")

    # ~/.spark/ directory
    if not SPARK_DIR.exists():
        SPARK_DIR.mkdir(parents=True, exist_ok=True)

    if issues:
        step.status = "fail"
        step.message = "; ".join(issues)
    else:
        step.status = "pass"
        step.message = f"Python {sys.version_info.major}.{sys.version_info.minor}, repo intact, ~/.spark/ ready"

    return step


def _step_services(quick: bool = False) -> OnboardStep:
    """Step 2: Start services."""
    step = OnboardStep(id="services", label="Start Spark services")
    step.status = "running"

    try:
        from lib.service_control import start_services, service_status

        # Check if already running
        status = service_status(include_pulse_probe=False)
        sparkd_running = status.get("sparkd", {}).get("running", False)
        bridge_running = status.get("bridge_worker", {}).get("running", False)

        if sparkd_running and bridge_running:
            step.status = "pass"
            step.message = "Services already running"
            return step

        # Quick mode skips only Pulse. Mind + Watchdog stay enabled.
        results = start_services(
            include_mind=True,
            include_pulse=not quick,
            include_watchdog=True,
        )

        # Give services a moment to start
        time.sleep(2)

        # Re-check
        status = service_status(include_pulse_probe=False)
        sparkd_running = status.get("sparkd", {}).get("running", False)
        bridge_running = status.get("bridge_worker", {}).get("running", False)

        if sparkd_running and bridge_running:
            step.status = "pass"
            step.message = "Core services started successfully"
        elif sparkd_running:
            step.status = "pass"
            step.message = "sparkd running (bridge_worker starting...)"
        else:
            step.status = "fail"
            step.message = "Services failed to start"
            step.detail = "Try: spark down && spark up"
    except Exception as e:
        step.status = "fail"
        step.message = f"Service start error: {e}"

    return step


def _step_health() -> OnboardStep:
    """Step 3: Health verification."""
    step = OnboardStep(id="health", label="Health verification")
    step.status = "running"

    try:
        from lib.cognitive_learner import get_cognitive_learner
        from lib.queue import get_queue_stats

        checks_ok = []
        checks_warn = []

        # Cognitive learner
        try:
            cognitive = get_cognitive_learner()
            checks_ok.append("cognitive")
        except Exception:
            checks_warn.append("cognitive")

        # Queue
        try:
            stats = get_queue_stats()
            checks_ok.append(f"queue ({stats.get('event_count', 0)} events)")
        except Exception:
            checks_warn.append("queue")

        if checks_ok and not checks_warn:
            step.status = "pass"
            step.message = f"Healthy: {', '.join(checks_ok)}"
        elif checks_ok:
            step.status = "pass"
            step.message = f"OK: {', '.join(checks_ok)} | Warn: {', '.join(checks_warn)}"
        else:
            step.status = "fail"
            step.message = "Health checks failed"

    except Exception as e:
        step.status = "fail"
        step.message = f"Health check error: {e}"

    return step


def _step_hooks(agent: str = "", strict: bool = False) -> OnboardStep:
    """Step 4: Agent connection check."""
    step = OnboardStep(id="hooks", label="Agent hook configuration")
    step.status = "running"

    def _set_failure(message: str, detail: str = "") -> OnboardStep:
        if strict:
            step.status = "fail"
            step.message = message
            step.detail = detail
        else:
            step.status = "skip"
            step.message = message
            step.detail = detail
        return step

    if agent and not _is_claude_agent(agent):
        step.status = "skip"
        step.message = f"Hook check not applicable for agent: {agent}"
        step.detail = "See docs/cursor.md or docs/openclaw/ for your agent."
        return step

    claude_settings = Path.home() / ".claude" / "settings.json"
    if not claude_settings.exists():
        return _set_failure(
            "~/.claude/settings.json not found",
            "Run: scripts/install_claude_hooks.ps1 (Windows) or scripts/install_claude_hooks.sh (Mac/Linux)",
        )

    try:
        settings = json.loads(claude_settings.read_text(encoding="utf-8"))
        hooks = settings.get("hooks", {})
        required = ["PreToolUse", "PostToolUse", "PostToolUseFailure"]
        found = [e for e in required if hooks.get(e)]

        if len(found) == len(required):
            # Check if observe.py is referenced
            observe_found = False
            for event in required:
                for matcher in hooks.get(event, []):
                    for hook in matcher.get("hooks", []):
                        if "observe.py" in hook.get("command", ""):
                            observe_found = True
                            break

            if observe_found:
                step.status = "pass"
                step.message = f"Claude Code hooks configured ({len(found)}/{len(required)} events, observe.py linked)"
            else:
                return _set_failure(
                    "Hooks exist but observe.py not referenced",
                    "Re-run hook installer and merge spark-hooks.json into settings.json",
                )
        else:
            missing = set(required) - set(found)
            return _set_failure(
                f"Missing hook events: {', '.join(missing)}",
                "Run hook installer, then merge into settings.json",
            )
    except Exception as e:
        return _set_failure(f"Cannot parse settings.json: {e}")

    return step


def _step_first_events() -> OnboardStep:
    """Step 5: First event proof."""
    step = OnboardStep(id="first_events", label="Event capture proof")
    step.status = "running"

    try:
        from lib.queue import get_queue_stats
        stats = get_queue_stats()
        count = stats.get("event_count", 0)

        if count > 0:
            step.status = "pass"
            step.message = f"{count} events in queue — Spark is capturing"
        else:
            step.status = "skip"
            step.message = "No events yet (normal for fresh install)"
            step.detail = "Events appear after your first Claude Code session with hooks active."
    except Exception as e:
        step.status = "fail"
        step.message = f"Cannot check events: {e}"

    return step


def _step_next_steps(agent: str = "") -> OnboardStep:
    """Step 6: What to do next."""
    step = OnboardStep(id="next_steps", label="You're ready")
    step.status = "pass"

    lines = [
        "Spark is set up. Here's what to do next:",
        "",
        "  1. Code normally — Spark learns from your sessions automatically",
        "  2. Check learnings:   spark learnings",
        "  3. Check system:      spark doctor",
        "  4. Promote insights:  spark promote --dry-run",
        "  5. Full status:       spark status",
    ]

    if agent and agent.lower() in ("claude", "claude_code"):
        lines.append("")
        lines.append("  Claude Code tip: Spark delivers pre-tool advisory guidance.")
        lines.append("  The more you use it, the smarter it gets.")

    step.message = "\n".join(lines)
    return step


def run_onboard(
    agent: str = "",
    quick: bool = False,
    auto_yes: bool = False,
    use_json: bool = False,
) -> dict:
    """Run the full onboarding wizard."""
    import datetime

    state = OnboardState.load()
    state.agent = agent or state.agent
    state.started_at = state.started_at or datetime.datetime.now().isoformat()

    steps: list[OnboardStep] = []

    if not use_json:
        print("")
        print("=" * 56)
        print("  SPARK ONBOARDING")
        print("=" * 56)
        print("")

    # Step 1: Preflight
    s1 = _step_preflight()
    steps.append(s1)
    state.steps[s1.id] = s1.status
    if not use_json:
        _print_step(s1, 1)
    if s1.status == "fail":
        state.save()
        if not use_json:
            print("\n  Onboarding blocked — fix environment issues above first.\n")
        return _build_result(steps, state)

    # Step 2: Services
    run_services = True
    if not quick:
        run_services = _confirm(
            "  Start Spark services now?",
            default=True,
            auto_yes=auto_yes,
            use_json=use_json,
        )

    if run_services:
        s2 = _step_services(quick=quick)
    else:
        s2 = OnboardStep(
            id="services",
            label="Start Spark services",
            status="skip",
            message="Skipped by user",
            detail="Run `spark up` when ready.",
        )
    steps.append(s2)
    state.steps[s2.id] = s2.status
    if not use_json:
        _print_step(s2, 2)

    # Step 3: Health
    if run_services:
        s3 = _step_health()
    else:
        s3 = OnboardStep(
            id="health",
            label="Health verification",
            status="skip",
            message="Skipped because services were not started",
            detail="Run `spark health` after starting services.",
        )
    steps.append(s3)
    state.steps[s3.id] = s3.status
    if not use_json:
        _print_step(s3, 3)

    # Step 4: Hooks
    s4 = _step_hooks(agent=state.agent, strict=_is_claude_agent(state.agent))
    steps.append(s4)
    state.steps[s4.id] = s4.status
    if not use_json:
        _print_step(s4, 4)

    # Step 5: Events
    s5 = _step_first_events()
    steps.append(s5)
    state.steps[s5.id] = s5.status
    if not use_json:
        _print_step(s5, 5)

    # Step 6: Next steps
    s6 = _step_next_steps(agent=state.agent)
    steps.append(s6)
    state.steps[s6.id] = s6.status
    if not use_json:
        print("")
        print("-" * 56)
        print(f"  {s6.message}")
        print("")

    # Check completion
    failed = [s for s in steps if s.status == "fail"]
    if not failed:
        import datetime
        state.completed_at = datetime.datetime.now().isoformat()

    state.save()
    return _build_result(steps, state)


def _build_result(steps: list[OnboardStep], state: OnboardState) -> dict:
    failed = [s for s in steps if s.status == "fail"]
    return {
        "ok": len(failed) == 0,
        "command": "onboard",
        "steps": [asdict(s) for s in steps],
        "completed": state.completed_at != "",
        "agent": state.agent,
    }


def show_onboard_status() -> dict:
    """Show current onboarding progress."""
    state = OnboardState.load()
    if not state.started_at:
        return {"status": "not_started", "message": "Onboarding not started. Run: spark onboard"}

    total = len(state.steps)
    passed = sum(1 for s in state.steps.values() if s == "pass")
    return {
        "status": "complete" if state.completed_at else "in_progress",
        "agent": state.agent,
        "started_at": state.started_at,
        "completed_at": state.completed_at,
        "progress": f"{passed}/{total} steps passed",
        "steps": state.steps,
    }


def reset_onboard():
    """Reset onboarding state."""
    OnboardState.reset()
    return {"status": "reset", "message": "Onboarding state cleared. Run: spark onboard"}
