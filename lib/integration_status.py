"""
Integration Status Checker for Spark Intelligence

Verifies that Spark is properly integrated with Claude Code.
Prevents being fooled by "test metrics" when real UX is broken.

Usage:
    python -m lib.integration_status
    spark status  # via CLI
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

# Paths
CLAUDE_DIR = Path.home() / ".claude"
SPARK_DIR = Path.home() / ".spark"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"
SPARK_HOOKS_FILE = CLAUDE_DIR / "spark-hooks.json"
QUEUE_DIR = SPARK_DIR / "queue"
EVENTS_FILE = QUEUE_DIR / "events.jsonl"
ADVICE_LOG = SPARK_DIR / "advisor" / "advice_log.jsonl"
RECENT_ADVICE = SPARK_DIR / "advisor" / "recent_advice.jsonl"
EFFECTIVENESS = SPARK_DIR / "advisor" / "effectiveness.json"
CODEX_CONTEXT_FILE = Path("SPARK_CONTEXT_FOR_CODEX.md")
CODEX_PAYLOAD_FILE = Path("SPARK_ADVISORY_PAYLOAD.json")


def check_settings_json() -> Tuple[bool, str]:
    """Check if ~/.claude/settings.json exists with Spark hooks."""
    if not SETTINGS_FILE.exists():
        return False, "Missing: ~/.claude/settings.json not found"

    try:
        settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        hooks = settings.get("hooks", {})

        required = ["PreToolUse", "PostToolUse", "PostToolUseFailure"]
        missing = [h for h in required if h not in hooks]

        if missing:
            return False, f"Missing hooks: {', '.join(missing)}"

        # Check if hooks point to observe.py
        for hook_type in required:
            hook_list = hooks.get(hook_type, [])
            if not hook_list:
                return False, f"{hook_type} has no hooks configured"

            has_spark = any(
                "observe.py" in str(h.get("hooks", [{}])[0].get("command", ""))
                for h in hook_list
            )
            if not has_spark:
                return False, f"{hook_type} doesn't call observe.py"

        return True, "settings.json configured correctly"
    except Exception as e:
        return False, f"Error reading settings.json: {e}"


def check_recent_events(minutes: int = 60) -> Tuple[bool, str]:
    """Check if we've received events in the last N minutes."""
    if not EVENTS_FILE.exists():
        return False, f"No events file: {EVENTS_FILE}"

    try:
        cutoff = time.time() - (minutes * 60)
        recent_count = 0

        with open(EVENTS_FILE, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                try:
                    event = json.loads(line.strip())
                    ts = event.get("timestamp") or event.get("ts", 0)
                    if ts > cutoff:
                        recent_count += 1
                except (json.JSONDecodeError, ValueError):
                    continue

        if recent_count > 0:
            return True, f"{recent_count} events in last {minutes} min"
        else:
            return False, f"No events in last {minutes} min (file exists but stale)"
    except Exception as e:
        return False, f"Error reading events: {e}"


def check_advice_log_growing() -> Tuple[bool, str]:
    """Check if advice log is being written to."""
    log_file = RECENT_ADVICE if RECENT_ADVICE.exists() else ADVICE_LOG

    if not log_file.exists():
        return False, "No advice log found"

    try:
        # Check modification time
        mtime = log_file.stat().st_mtime
        age_hours = (time.time() - mtime) / 3600

        if age_hours > 24:
            return False, f"Advice log stale ({age_hours:.1f}h since last write)"

        # Count recent entries
        lines = log_file.read_text(encoding='utf-8', errors='replace').strip().split('\n')
        return True, f"{len(lines)} advice entries, last write {age_hours:.1f}h ago"
    except Exception as e:
        return False, f"Error reading advice log: {e}"


def check_effectiveness() -> Tuple[bool, str]:
    """Check if effectiveness tracking is working."""
    if not EFFECTIVENESS.exists():
        return False, "No effectiveness.json found"

    try:
        data = json.loads(EFFECTIVENESS.read_text(encoding="utf-8"))
        total = data.get("total_advice_given", 0)
        followed = data.get("total_followed", 0)
        helpful = data.get("total_helpful", 0)

        if total == 0:
            return False, "No advice tracked yet"

        if followed > total:
            return False, (
                f"Invalid counters: followed ({followed}) > total advice ({total})"
            )
        if helpful > followed:
            return False, (
                f"Invalid counters: helpful ({helpful}) > followed ({followed})"
            )

        if followed == 0 and total > 100:
            return False, f"0 followed out of {total} advice (outcome loop broken)"

        rate = (followed / total * 100) if total > 0 else 0
        return True, f"{followed}/{total} followed ({rate:.1f}%), {helpful} helpful"
    except Exception as e:
        return False, f"Error reading effectiveness: {e}"


def check_advisory_packet_store() -> Tuple[bool, str]:
    try:
        from .advisory_packet_store import get_store_status

        status = get_store_status()
    except Exception as e:
        return False, f"Advisory packet store unavailable: {e}"

    total = int(status.get("total_packets", 0) or 0)
    if total <= 0:
        return False, "No advisory packets stored yet"

    readiness = float(status.get("readiness_ratio", 0.0) or 0.0)
    if readiness <= 0.0:
        return False, "No fresh packets available"

    queue_depth = int(status.get("queue_depth", 0) or 0)
    if queue_depth > 4000:
        return False, f"Prefetch queue backlog too high: {queue_depth}"

    config = status.get("config", {}) if isinstance(status.get("config", {}), dict) else {}
    obsidian_enabled = (
        bool(status.get("obsidian_enabled", False))
        or bool(config.get("obsidian_enabled", False))
        or bool(config.get("obsidian_auto_export", False))
    )
    if obsidian_enabled and not bool(status.get("obsidian_export_dir_exists", False)):
        return False, f"Obsidian export enabled but directory missing: {status.get('obsidian_export_dir')}"

    return True, (
        f"{total} packets, readiness={readiness:.1%}, "
        f"freshness={float(status.get('freshness_ratio', 0.0) or 0.0):.1%}, "
        f"avg_effectiveness={float(status.get('avg_effectiveness_score', 0.0) or 0.0):.1%}, "
        f"queue_depth={queue_depth}"
    )


def _codex_sync_enabled() -> bool:
    if os.getenv("SPARK_CODEX_CMD") or os.getenv("CODEX_CMD"):
        return True
    sync_targets = os.getenv("SPARK_SYNC_TARGETS", "").strip().lower()
    if not sync_targets:
        return False
    targets = {s.strip() for s in sync_targets.split(",") if s.strip()}
    return "codex" in targets


def check_codex_sync_outputs() -> Tuple[bool, str]:
    """Check Codex adapter sync artifacts in the current working project."""
    if not _codex_sync_enabled():
        return True, "Codex sync not configured"

    context_path = (Path.cwd() / CODEX_CONTEXT_FILE).resolve()
    payload_path = (Path.cwd() / CODEX_PAYLOAD_FILE).resolve()

    if not context_path.exists() and not payload_path.exists():
        return False, "No Codex sync artifacts in current directory"
    if not context_path.exists():
        return False, f"Missing Codex context file: {context_path.name}"
    if not payload_path.exists():
        return False, f"Missing Codex advisory payload: {payload_path.name}"

    try:
        payload_text = payload_path.read_text(encoding="utf-8")
        payload = json.loads(payload_text)
        if not isinstance(payload, dict):
            return False, "SPARK_ADVISORY_PAYLOAD.json is not a JSON object"
        if not payload.get("schema_version"):
            return False, "SPARK_ADVISORY_PAYLOAD.json missing schema_version"
    except Exception as e:
        return False, f"Error reading SPARK_ADVISORY_PAYLOAD.json: {e}"

    age_hours = (time.time() - context_path.stat().st_mtime) / 3600
    if age_hours > 24:
        return False, (
            f"Codex context stale ({age_hours:.1f}h ago); run `spark-codex` or "
            "`python -m spark.cli sync-context`"
        )

    return True, f"Codex sync present at {context_path.name} and {payload_path.name}"


def check_pre_tool_events(minutes: int = 60) -> Tuple[bool, str]:
    """Check specifically for pre_tool events."""
    if not EVENTS_FILE.exists():
        return False, "No events file"

    try:
        cutoff = time.time() - (minutes * 60)
        pre_count = 0
        post_count = 0

        with open(EVENTS_FILE, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                try:
                    event = json.loads(line.strip())
                    ts = event.get("timestamp") or event.get("ts", 0)
                    if ts > cutoff:
                        et = str(event.get("event_type", "")).lower()
                        if et == "pre_tool":
                            pre_count += 1
                        elif et in ("post_tool", "post_tool_failure"):
                            post_count += 1
                except (json.JSONDecodeError, ValueError):
                    continue

        if pre_count > 0 and post_count > 0:
            return True, f"pre_tool: {pre_count}, post_tool: {post_count}"
        elif pre_count == 0 and post_count == 0:
            return False, "No pre_tool or post_tool events (hooks not firing)"
        else:
            return False, f"Partial: pre={pre_count}, post={post_count}"
    except Exception as e:
        return False, f"Error: {e}"


def get_full_status() -> Dict:
    """Get complete integration status."""
    checks = [
        ("settings.json", check_settings_json()),
        ("Recent Events", check_recent_events(60)),
        ("Pre/Post Tool Events", check_pre_tool_events(60)),
        ("Advice Log", check_advice_log_growing()),
        ("Advisory Packet Store", check_advisory_packet_store()),
        ("Codex Sync Outputs", check_codex_sync_outputs()),
        ("Effectiveness Tracking", check_effectiveness()),
    ]

    results = []
    all_ok = True

    for name, (ok, msg) in checks:
        results.append({
            "check": name,
            "ok": ok,
            "message": msg
        })
        if not ok:
            all_ok = False

    return {
        "status": "HEALTHY" if all_ok else "DEGRADED",
        "timestamp": datetime.now().isoformat(),
        "checks": results,
        "all_ok": all_ok
    }


def print_status() -> Dict[str, Any]:
    """Print formatted status to console."""
    status = get_full_status()

    print("\n" + "=" * 60)
    print("  SPARK INTELLIGENCE - INTEGRATION STATUS")
    print("=" * 60)

    if status["all_ok"]:
        print("\n  STATUS: [OK] HEALTHY - All systems operational\n")
    else:
        print("\n  STATUS: [!!] DEGRADED - Issues detected\n")

    for check in status["checks"]:
        icon = "[OK]" if check["ok"] else "[!!]"
        print(f"  {icon} {check['check']}")
        print(f"    {check['message']}")
        print()

    if not status["all_ok"]:
        print("-" * 60)
        print("  FIX INSTRUCTIONS:")
        print("-" * 60)

        for check in status["checks"]:
            if not check["ok"]:
                if "settings.json" in check["check"]:
                    print("""
  1. Create ~/.claude/settings.json with:
     {
       "hooks": {
         "PreToolUse": [{"matcher":"","hooks":[{"type":"command",
           "command":"python /path/to/spark/hooks/observe.py"}]}],
         "PostToolUse": [...same...],
         "PostToolUseFailure": [...same...]
       }
     }
  2. Restart Claude Code
""")
                elif "Events" in check["check"]:
                    print("""
  - Hooks may not be firing. Check:
    a) settings.json has correct paths
    b) observe.py is executable
    c) Python is in PATH
    d) Restart Claude Code after config changes
""")
                elif "Effectiveness" in check["check"]:
                    print("""
  - Outcome loop is broken. Ensure:
    a) PostToolUse hook is configured
    b) report_outcome() is being called
    c) Check lib/bridge_cycle.py integration
""")
                elif "Advisory Packet Store" in check["check"]:
                    print("""
  - Advisory packet store is not healthy. Recommended checks:
    a) Confirm advisory packets are being saved (`build_packet`/`save_packet` flow runs)
    b) Verify packet TTL is not too short for your workflow
    c) Trim invalidation rules if too many packets become invalidated
    d) Inspect ~/.spark/advice_packets/index.json for unexpected corruption
""")
                elif "Codex Sync Outputs" in check["check"] and not check["ok"]:
                    if "Codex sync not configured" in check["message"]:
                        print("""
  - Codex sync is disabled in this run context. Enable if you want this check:
    a) Launch with `spark-codex` wrapper, or
    b) Set SPARK_SYNC_TARGETS=codex
    c) Or set SPARK_CODEX_CMD / CODEX_CMD
""")
                    else:
                        print("""
  - Codex sync artifacts missing or stale. Recommended checks:
    a) Run `python -m spark.cli sync-context` in this directory
    b) Ensure SPARK_SYNC_TARGETS includes `codex`
    c) Verify `SPARK_CONTEXT_FOR_CODEX.md` and `SPARK_ADVISORY_PAYLOAD.json` exist
    d) Confirm payload parses and includes `schema_version`
""")

    print("=" * 60 + "\n")
    return status


if __name__ == "__main__":
    print_status()
