#!/usr/bin/env python3
"""Single-command alpha preflight across services, hooks, integration, and gates."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

from lib.doctor import DoctorResult, _check_alpha_env_contract
from lib.integration_status import get_full_status
from lib.production_gates import evaluate_gates, load_live_metrics
from lib.service_control import service_status


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_PROVIDER_BREACH_WINDOWS = 2
NOISE_SHADOW_CAP_TOLERANCE = 1.05
DEFAULT_KNOWN_HELPFULNESS_MIN_COUNT = 25
DEFAULT_KNOWN_HELPFULNESS_MIN_COVERAGE = 0.02


def _read_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        value = int(default)
    return max(1, int(value))


def _read_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except Exception:
        value = float(default)
    return float(value)


def _count_nonempty_lines(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                if raw.strip():
                    total += 1
    except Exception:
        return 0
    return int(total)


def _collect_runtime_hygiene() -> Dict[str, Any]:
    spark_dir = Path.home() / ".spark"
    shadow_path = spark_dir / "noise_classifier_shadow.jsonl"
    shadow_cap_lines = _read_int_env("SPARK_NOISE_SHADOW_MAX_LINES", 10000)
    shadow_soft_cap_lines = max(shadow_cap_lines, int(round(shadow_cap_lines * NOISE_SHADOW_CAP_TOLERANCE)))
    shadow_lines = _count_nonempty_lines(shadow_path)

    wal_path = spark_dir / "spark_memory_spine.db-wal"
    wal_max_bytes = _read_int_env("SPARK_MEMORY_WAL_MAX_BYTES", 1_048_576)
    wal_size_bytes = int(wal_path.stat().st_size) if wal_path.exists() else 0

    return {
        "shadow": {
            "path": str(shadow_path),
            "lines": int(shadow_lines),
            "cap_lines": int(shadow_cap_lines),
            "soft_cap_lines": int(shadow_soft_cap_lines),
            "ok": bool(shadow_lines <= shadow_soft_cap_lines),
        },
        "wal": {
            "path": str(wal_path),
            "size_bytes": int(wal_size_bytes),
            "max_bytes": int(wal_max_bytes),
            "ok": bool(wal_size_bytes <= wal_max_bytes),
        },
    }


def _collect_advisory_quality_summary() -> Dict[str, Any]:
    path = Path.home() / ".spark" / "advisor" / "advisory_quality_summary.json"
    if not path.exists():
        return {
            "path": str(path),
            "available": False,
            "total_events": 0,
            "known_helpfulness_total": 0,
            "known_helpfulness_coverage": 0.0,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    total = int(payload.get("total_events", 0) or 0)
    known = int(payload.get("known_helpfulness_total", 0) or 0)
    coverage = (float(known) / float(total)) if total > 0 else 0.0
    return {
        "path": str(path),
        "available": True,
        "total_events": total,
        "known_helpfulness_total": known,
        "known_helpfulness_coverage": coverage,
        "summary": payload,
    }


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
    if not stdout:
        detail = stderr or f"exit={proc.returncode}"
        return False, None, f"empty output: {detail}"
    try:
        payload = json.loads(stdout)
    except Exception as exc:
        detail = stderr or f"exit={proc.returncode}"
        return False, None, f"invalid json: {exc}; {detail}"
    if not isinstance(payload, dict):
        detail = stderr or f"exit={proc.returncode}"
        return False, None, f"json payload is not an object; {detail}"

    # Some probe scripts intentionally return non-zero when a gate is red but still emit
    # structured JSON. Treat that as a successful read so downstream checks can evaluate it.
    return True, payload, (stderr or "")


def evaluate_alpha_preflight(*, bridge_stale_s: int = 90, ci_mode: bool = False) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    known_helpfulness_min_count = _read_int_env(
        "SPARK_ADVISORY_KNOWN_HELPFULNESS_MIN_COUNT",
        DEFAULT_KNOWN_HELPFULNESS_MIN_COUNT,
    )
    known_helpfulness_min_coverage = _read_float_env(
        "SPARK_ADVISORY_KNOWN_HELPFULNESS_MIN_COVERAGE",
        DEFAULT_KNOWN_HELPFULNESS_MIN_COVERAGE,
    )

    if ci_mode:
        integration = {"status": "CI_MODE", "all_ok": True, "checks": []}
        services = {}
    else:
        integration = get_full_status()
        services = service_status(bridge_stale_s=bridge_stale_s)

    metrics = load_live_metrics()
    production = evaluate_gates(metrics)
    runtime_hygiene = _collect_runtime_hygiene()
    advisory_quality = _collect_advisory_quality_summary()

    if ci_mode:
        codex_ok, codex_obs, codex_err = True, {"summary": {"available": False, "mode": "ci_skip"}, "gates": {}, "alert": {"level": "ok"}}, ""
        fidelity_ok, fidelity_obs, fidelity_err = True, {"providers": {}, "alerts": {"providers": {}}, "window_minutes": 60}, ""
        canary_ok, canary_obs, canary_err = True, {"providers": {}, "active_providers": [], "failing_active": [], "ready": True}, ""
    else:
        codex_ok, codex_obs, codex_err = _run_json_command(
            [sys.executable, str(ROOT / "scripts" / "codex_hooks_observatory.py"), "--json-only"]
        )
        fidelity_ok, fidelity_obs, fidelity_err = _run_json_command(
            [sys.executable, str(ROOT / "scripts" / "workflow_fidelity_observatory.py"), "--json-only"]
        )
        canary_ok, canary_obs, canary_err = _run_json_command(
            [sys.executable, str(ROOT / "scripts" / "run_advisory_provider_canary.py"), "--json-only"]
        )

    core_services = ("sparkd", "bridge_worker", "scheduler", "watchdog")
    core_services_running = True if ci_mode else all(bool((services.get(name) or {}).get("running")) for name in core_services)
    codex_bridge_running = True if ci_mode else bool((services.get("codex_bridge") or {}).get("running"))

    codex_summary = codex_obs.get("summary", {}) if isinstance(codex_obs, dict) else {}
    codex_gates = codex_obs.get("gates", {}) if isinstance(codex_obs, dict) else {}
    codex_alert = codex_obs.get("alert", {}) if isinstance(codex_obs, dict) else {}
    codex_derived = codex_summary.get("derived", {}) if isinstance(codex_summary, dict) else {}
    codex_window_activity = int(codex_derived.get("window_activity_rows") or 0)
    codex_gate_strict_ok = bool(codex_gates.get("passing"))
    codex_gate_ok = codex_gate_strict_ok or codex_window_activity == 0

    fidelity_providers = fidelity_obs.get("providers", {}) if isinstance(fidelity_obs, dict) else {}
    fidelity_alerts = (
        (fidelity_obs.get("alerts") or {}).get("providers", {})
        if isinstance(fidelity_obs, dict)
        else {}
    )
    fidelity_critical_active: list[Dict[str, Any]] = []
    fidelity_degraded_active: list[Dict[str, Any]] = []
    fidelity_unavailable_providers: list[str] = []
    for provider, summary in (fidelity_providers.items() if isinstance(fidelity_providers, dict) else []):
        if not isinstance(summary, dict):
            continue
        if not bool(summary.get("available")):
            fidelity_unavailable_providers.append(str(provider))
            continue
        window_activity_rows = int(summary.get("window_activity_rows") or 0)
        if window_activity_rows <= 0:
            continue
        alert = fidelity_alerts.get(provider) if isinstance(fidelity_alerts, dict) else {}
        level = str((alert or {}).get("level") or "unknown")
        consecutive = int((alert or {}).get("consecutive_breach_windows") or 0)
        breaches = (alert or {}).get("breaches")
        has_breach = isinstance(breaches, list) and bool(breaches)
        if level == "critical":
            fidelity_critical_active.append(
                {
                    "provider": provider,
                    "window_activity_rows": window_activity_rows,
                    "alert": alert,
                }
            )
        if level == "critical" or (has_breach and consecutive >= ACTIVE_PROVIDER_BREACH_WINDOWS):
            fidelity_degraded_active.append(
                {
                    "provider": provider,
                    "window_activity_rows": window_activity_rows,
                    "consecutive_breach_windows": consecutive,
                    "alert_level": level,
                    "breaches": breaches if isinstance(breaches, list) else [],
                }
            )

    env_contract_probe = DoctorResult()
    _check_alpha_env_contract(env_contract_probe)
    env_contract_check = next((c for c in env_contract_probe.checks if c.id == "alpha_env_contract"), None)
    env_contract_status = str(getattr(env_contract_check, "status", "skip"))
    env_contract_ok = env_contract_status != "fail"
    known_helpfulness_total = int(advisory_quality.get("known_helpfulness_total", 0) or 0)
    total_quality_events = int(advisory_quality.get("total_events", 0) or 0)
    known_helpfulness_coverage = float(advisory_quality.get("known_helpfulness_coverage", 0.0) or 0.0)
    known_helpfulness_ok = (
        advisory_quality.get("available") is True
        and known_helpfulness_total >= int(known_helpfulness_min_count)
        and known_helpfulness_coverage >= float(known_helpfulness_min_coverage)
    )

    checks = [
        {"name": "integration.all_ok", "ok": bool(integration.get("all_ok")), "value": integration.get("status")},
        {
            "name": "services.core_running",
            "ok": core_services_running,
            "value": ({k: (services.get(k) or {}).get("running") for k in core_services} if not ci_mode else {"skipped": True, "reason": "ci_mode"}),
        },
        {
            "name": "services.codex_bridge_running",
            "ok": codex_bridge_running,
            "value": ((services.get("codex_bridge") or {}) if not ci_mode else {"skipped": True, "reason": "ci_mode"}),
        },
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
        {
            "name": "workflow_fidelity.observable",
            "ok": fidelity_ok and bool(isinstance(fidelity_providers, dict)),
            "value": fidelity_obs if fidelity_ok else fidelity_err,
        },
        {
            "name": "workflow_fidelity.alert_not_critical_active",
            "ok": fidelity_ok and not fidelity_critical_active,
            "value": {
                "critical_active": fidelity_critical_active,
                "alerts": fidelity_alerts if isinstance(fidelity_alerts, dict) else {},
            }
            if fidelity_ok
            else fidelity_err,
        },
        {
            "name": "workflow_fidelity.active_provider_breach_budget",
            "ok": fidelity_ok and not fidelity_degraded_active,
            "value": {
                "max_consecutive_breach_windows": ACTIVE_PROVIDER_BREACH_WINDOWS,
                "degraded_active": fidelity_degraded_active,
            }
            if fidelity_ok
            else fidelity_err,
        },
        {
            "name": "workflow_fidelity.unavailable_providers_reported",
            "ok": fidelity_ok,
            "value": {
                "unavailable_providers": fidelity_unavailable_providers,
            }
            if fidelity_ok
            else fidelity_err,
        },
        {
            "name": "runtime_hygiene.shadow_log_within_cap",
            "ok": bool((runtime_hygiene.get("shadow") or {}).get("ok")),
            "value": runtime_hygiene.get("shadow", {}),
        },
        {
            "name": "runtime_hygiene.memory_wal_within_budget",
            "ok": bool((runtime_hygiene.get("wal") or {}).get("ok")),
            "value": runtime_hygiene.get("wal", {}),
        },
        {
            "name": "advisory_quality.observable",
            "ok": bool(advisory_quality.get("available")),
            "value": advisory_quality,
        },
        {
            "name": "advisory_quality.known_helpfulness_coverage",
            "ok": bool(known_helpfulness_ok),
            "value": {
                "known_helpfulness_total": int(known_helpfulness_total),
                "total_events": int(total_quality_events),
                "known_helpfulness_coverage": float(known_helpfulness_coverage),
                "min_known_helpfulness_total": int(known_helpfulness_min_count),
                "min_known_helpfulness_coverage": float(known_helpfulness_min_coverage),
            },
        },
        {
            "name": "advisory_quality.provider_canary_active_pass",
            "ok": canary_ok and bool((canary_obs or {}).get("ready")),
            "value": canary_obs if canary_ok else {"error": canary_err},
        },
        {
            "name": "config.alpha_env_contract",
            "ok": env_contract_ok,
            "value": {
                "status": env_contract_status,
                "message": getattr(env_contract_check, "message", ""),
                "details": getattr(env_contract_check, "details", ""),
            },
        },
        {"name": "production_gates.ready", "ok": bool(production.get("ready")), "value": {"passed": production.get("passed"), "total": production.get("total")}},
    ]

    if ci_mode:
        # CI has no long-running services or hook telemetry; enforce contract + gate checks only.
        for row in checks:
            if (
                str(row.get("name")).startswith("codex_hooks.")
                or str(row.get("name")).startswith("workflow_fidelity.")
                or str(row.get("name")).startswith("runtime_hygiene.")
                or str(row.get("name")).startswith("advisory_quality.")
            ):
                row["ok"] = True
                row["value"] = {"skipped": True, "reason": "ci_mode"}
        ready = all(
            bool(c.get("ok"))
            for c in checks
            if str(c.get("name")) in {"integration.all_ok", "config.alpha_env_contract", "production_gates.ready"}
        )
    else:
        ready = all(bool(c.get("ok")) for c in checks)
    return {
        "timestamp": now,
        "ci_mode": bool(ci_mode),
        "ready": ready,
        "checks": checks,
        "integration": integration,
        "services": services,
        "production_gates": production,
        "codex_hooks": codex_obs if codex_ok else {"ok": False, "error": codex_err},
        "workflow_fidelity": fidelity_obs if fidelity_ok else {"ok": False, "error": fidelity_err},
        "runtime_hygiene": runtime_hygiene,
        "advisory_quality": advisory_quality,
        "advisory_provider_canary": canary_obs if canary_ok else {"ok": False, "error": canary_err},
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
    ap.add_argument("--ci-mode", action="store_true", help="CI-safe mode (skip live service/hook checks)")
    ap.add_argument("--json-only", action="store_true", help="Emit JSON only")
    args = ap.parse_args()

    payload = evaluate_alpha_preflight(bridge_stale_s=int(args.bridge_stale_s), ci_mode=bool(args.ci_mode))
    if args.json_only:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        _print_human(payload)
    return 0 if payload.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
