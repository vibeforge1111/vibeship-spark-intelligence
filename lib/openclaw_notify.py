"""OpenClaw notification bridge: push Spark findings into the agent session."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Optional

from .diagnostics import log_debug
from .openclaw_paths import discover_openclaw_workspaces, read_openclaw_config


def _safe_gateway_port(raw_port: object, default: int = 18789) -> int:
    try:
        port = int(str(raw_port).strip())
    except Exception:
        return default
    if 1 <= port <= 65535:
        return port
    return default


def _read_openclaw_config() -> dict:
    """Read OpenClaw config from ~/.openclaw/openclaw.json."""
    return read_openclaw_config()


def _get_gateway_url() -> str:
    cfg = _read_openclaw_config()
    port = _safe_gateway_port(cfg.get("gateway", {}).get("port", 18789))
    return f"http://127.0.0.1:{port}"


def _get_gateway_token() -> Optional[str]:
    cfg = _read_openclaw_config()
    return cfg.get("gateway", {}).get("auth", {}).get("token")


def _workspace_paths() -> List[Path]:
    explicit = os.environ.get("SPARK_OPENCLAW_WORKSPACE") or os.environ.get("OPENCLAW_WORKSPACE")
    if explicit:
        return [Path(explicit).expanduser()]
    return discover_openclaw_workspaces(include_nonexistent=True)


def notify_agent(message: str, priority: str = "normal") -> bool:
    """Write a notification file and update SPARK_NOTIFICATIONS.md.

    This is the passive channel — files are visible even without wake events.
    Returns True if notification was written successfully.
    """
    try:
        ts = time.time()
        ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        filename = f"notif_{int(ts * 1000)}.json"

        payload = {
            "timestamp": ts_str,
            "epoch": ts,
            "message": message,
            "priority": priority,
            "source": "spark_bridge",
        }
        wrote_any = False
        for workspace in _workspace_paths():
            notif_dir = workspace / "spark_notifications"
            notif_dir.mkdir(parents=True, exist_ok=True)
            (notif_dir / filename).write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
            _update_notifications_md(workspace / "SPARK_NOTIFICATIONS.md", ts_str, message)
            _cleanup_notification_files(notif_dir, keep=20)
            wrote_any = True

        return wrote_any
    except Exception as e:
        log_debug("openclaw_notify", "notify_agent failed", e)
        return False


def _update_notifications_md(md_path: Path, ts_str: str, message: str) -> None:
    """Append to SPARK_NOTIFICATIONS.md, keeping only last 5 entries."""
    header = "# Spark Notifications\n\nLatest findings pushed by Spark Intelligence.\n\n"

    entries: list[str] = []
    if md_path.exists():
        try:
            content = md_path.read_text(encoding="utf-8")
            # Parse existing entries (lines starting with "- **")
            for line in content.splitlines():
                if line.startswith("- **"):
                    entries.append(line)
        except Exception:
            pass

    entries.append(f"- **{ts_str}** — {message}")
    entries = entries[-5:]  # keep last 5

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(
        header + "\n".join(entries) + "\n", encoding="utf-8"
    )


def _cleanup_notification_files(notif_dir: Path, keep: int = 20) -> None:
    """Remove old notification JSON files, keeping the most recent ones."""
    try:
        files = sorted(notif_dir.glob("notif_*.json"))
        for f in files[:-keep]:
            f.unlink(missing_ok=True)
    except Exception:
        pass


def wake_agent(text: str) -> bool:
    """Call OpenClaw's cron wake API to inject a message into the agent session.

    POST /api/cron/wake with Bearer token auth.
    Returns True if the wake call succeeded.
    """
    token = _get_gateway_token()
    if not token:
        log_debug("openclaw_notify", "no gateway token found, skipping wake", None)
        return False

    url = f"{_get_gateway_url()}/api/cron/wake"

    try:
        import urllib.request
        import urllib.error

        body = json.dumps({"text": text, "mode": "now"}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception as e:
        log_debug("openclaw_notify", f"wake_agent failed: {e}", None)
        return False
