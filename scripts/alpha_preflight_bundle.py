#!/usr/bin/env python3
"""Single-command alpha preflight across services, hooks, integration, and gates."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

from lib.integration_status import get_full_status
from lib.production_gates import evaluate_gates, load_live_metrics
from lib.service_control import service_status


ROOT = Path(__file__).resolve().parents[1]


def _run_json_command(args: list[str]) -> Tuple[bool, Dict[str, Any] | None, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return False, None, f"command failed: {exc}"

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        detail = stderr or stdout or f"exit={proc.returncode}"
        return False, None, detail
    if not stdout:
        return False, None, "empty output"
    try:
        payload = json.loads(stdout)
    except Exception as exc:
        return False, None, f"invalid json: {exc}"
    if not isinstance(payload, dict):
        return False, None, "json payload is not an object"
    return True, payload, ""


def evaluate_alpha_preflight(*, bridge_stale_s: int = 90) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()

    integration = get_full_status()
    services = service_status(bridge_stale_s=bridge_stale_s)

    metrics = load_live_metrics()
    production = evaluate_gates(metrics)

    codex_ok, codex_obs, codex_err = _run_json_command(
        [sys.executable, str(ROOT / "scripts" / "codex_hooks_observatory.py"), "--json-only"]
    )

    core_services = ("sparkd", "bridge_worker", "scheduler", "watchdog")
    core_services_running = all(bool((services.get(name) or {}).get("running")) for name in core_services)
    codex_bridge_running = bool((services.get("codex_bridge") or {}).get("running"))

    codex_summary = codex_obs.get("summary", {}) if isinstance(codex_obs, dict) else {}
    codex_gates = codex_obs.get("gates", {}) if isinstance(codex_obs, dict) else {}
    codex_alert = codex_obs.get("alert", {}) if isinstance(codex_obs, dict) else {}
    codex_derived = codex_summary.get("derived", {}) if isinstance(codex_summary, dict) else {}
    codex_window_activity = int(codex_derived.get("window_activity_rows") or 0)
    codex_gate_strict_ok = bool(codex_gates.get("passing"))
    codex_gate_ok = codex_gate_strict_ok or codex_window_activity == 0

    checks = [
        {"name": "integration.all_ok", "ok": bool(integration.get("all_ok")), "value": integration.get("status")},
        {"name": "services.core_running", "ok": core_services_running, "value": {k: (services.get(k) or {}).get("running") for k in core_services}},
        {"name": "services.codex_bridge_running", "ok": codex_bridge_running, "value": (services.get("codex_bridge") or {})},
        {"name": "codex_hooks.observable", "ok": codex_ok and bool(codex_summary.get("available")), "value": codex_summary if codex_ok else codex_err},
        {"name": "codex_hooks.observe_mode", "ok": codex_ok and str(codex_summary.get("mode")) == "observe", "value": codex_summary.get("mode") if codex_ok else codex_err},
        {
            "name": "codex_hooks.gates_passing",
            "ok": codex_ok and codex_gate_ok,
            "value": {
                "strict_pass": codex_gate_strict_ok,
                "window_activity_rows": codex_window_activity,
                "reason": "no_window_activity" if (not codex_gate_strict_ok and codex_window_activity == 0) else "normal",
                "gates": codex_gates if codex_ok else codex_err,
            },
        },
        {"name": "codex_hooks.alert_not_critical", "ok": codex_ok and str(codex_alert.get("level") or "unknown") != "critical", "value": codex_alert if codex_ok else codex_err},
        {"name": "production_gates.ready", "ok": bool(production.get("ready")), "value": {"passed": production.get("passed"), "total": production.get("total")}},
    ]

    ready = all(bool(c.get("ok")) for c in checks)
    return {
        "timestamp": now,
        "ready": ready,
        "checks": checks,
        "integration": integration,
        "services": services,
        "production_gates": production,
        "codex_hooks": codex_obs if codex_ok else {"ok": False, "error": codex_err},
    }


def _print_human(payload: Dict[str, Any]) -> None:
    print("=" * 66)
    print(" SPARK ALPHA PREFLIGHT BUNDLE")
    print("=" * 66)
    print(f"Ready: {'YES' if payload.get('ready') else 'NO'}")
    print(f"Generated: {payload.get('timestamp')}")
    print("")
    print("Checks:")
    for check in payload.get("checks", []):
        status = "PASS" if check.get("ok") else "FAIL"
        print(f"  [{status}] {check.get('name')}")
    print("=" * 66)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a bundled alpha preflight gate.")
    ap.add_argument("--bridge-stale-s", type=int, default=90, help="bridge stale threshold in seconds")
    ap.add_argument("--json-only", action="store_true", help="Emit JSON only")
    args = ap.parse_args()

    payload = evaluate_alpha_preflight(bridge_stale_s=int(args.bridge_stale_s))
    if args.json_only:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        _print_human(payload)
    return 0 if payload.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
