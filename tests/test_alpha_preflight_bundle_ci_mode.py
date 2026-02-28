from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "alpha_preflight_bundle.py"
    name = "alpha_preflight_bundle_script"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _inject_env_contract(monkeypatch, mod, status: str) -> None:
    def _fake_check(probe):
        check = type("Check", (), {})()
        check.id = "alpha_env_contract"
        check.status = status
        check.message = "env contract"
        check.details = ""
        probe.checks.append(check)

    monkeypatch.setattr(mod, "_check_alpha_env_contract", _fake_check)


def _base_patches(monkeypatch, *, production_ready: bool) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "load_live_metrics", lambda: {"stub": True})
    monkeypatch.setattr(
        mod,
        "evaluate_gates",
        lambda metrics: {"ready": bool(production_ready), "passed": 19 if production_ready else 18, "total": 19},
    )
    monkeypatch.setattr(mod, "get_full_status", lambda: {"all_ok": False, "status": "BROKEN"})
    monkeypatch.setattr(mod, "service_status", lambda bridge_stale_s=90: {"sparkd": {"running": False}})
    monkeypatch.setattr(mod, "_run_json_command", lambda args: (False, None, "not_used_in_ci_mode"))
    monkeypatch.setattr(
        mod,
        "_collect_runtime_hygiene",
        lambda: {
            "shadow": {"ok": True, "lines": 0, "soft_cap_lines": 10500},
            "wal": {"ok": True, "size_bytes": 0, "max_bytes": 1048576},
        },
    )
    return mod


def _runtime_patches(
    monkeypatch,
    *,
    codex_obs,
    fidelity_obs,
    canary_obs=None,
    production_ready: bool = True,
    runtime_hygiene=None,
    advisory_quality=None,
):
    mod = _load_module()
    monkeypatch.setattr(mod, "load_live_metrics", lambda: {"stub": True})
    monkeypatch.setattr(
        mod,
        "evaluate_gates",
        lambda metrics: {"ready": bool(production_ready), "passed": 19 if production_ready else 18, "total": 19},
    )
    monkeypatch.setattr(mod, "get_full_status", lambda: {"all_ok": True, "status": "OK"})
    monkeypatch.setattr(
        mod,
        "service_status",
        lambda bridge_stale_s=90: {
            "sparkd": {"running": True},
            "bridge_worker": {"running": True},
            "scheduler": {"running": True},
            "watchdog": {"running": True},
            "codex_bridge": {"running": True},
        },
    )
    if runtime_hygiene is None:
        runtime_hygiene = {
            "shadow": {"ok": True, "lines": 0, "soft_cap_lines": 10500},
            "wal": {"ok": True, "size_bytes": 0, "max_bytes": 1048576},
        }
    monkeypatch.setattr(mod, "_collect_runtime_hygiene", lambda: runtime_hygiene)
    if advisory_quality is None:
        advisory_quality = {
            "path": "mock",
            "available": True,
            "total_events": 200,
            "known_helpfulness_total": 50,
            "known_helpfulness_coverage": 0.25,
        }
    monkeypatch.setattr(mod, "_collect_advisory_quality_summary", lambda: advisory_quality)
    if canary_obs is None:
        canary_obs = {
            "providers": {},
            "active_providers": [],
            "failing_active": [],
            "ready": True,
        }

    def _run(args):
        cmd = " ".join(args)
        if "codex_hooks_observatory.py" in cmd:
            return True, codex_obs, ""
        if "workflow_fidelity_observatory.py" in cmd:
            return True, fidelity_obs, ""
        if "run_advisory_provider_canary.py" in cmd:
            return True, canary_obs, ""
        return False, None, "unexpected_command"

    monkeypatch.setattr(mod, "_run_json_command", _run)
    return mod


def test_ci_mode_ready_when_env_contract_and_gates_pass(monkeypatch):
    mod = _base_patches(monkeypatch, production_ready=True)
    _inject_env_contract(monkeypatch, mod, "pass")
    payload = mod.evaluate_alpha_preflight(ci_mode=True)
    assert payload["ci_mode"] is True
    assert payload["ready"] is True
    check_by_name = {c["name"]: c for c in payload.get("checks", [])}
    assert check_by_name["production_gates.ready"]["ok"] is True
    assert check_by_name["config.alpha_env_contract"]["ok"] is True
    assert check_by_name["codex_hooks.observable"]["ok"] is True
    assert check_by_name["codex_hooks.observable"]["value"]["reason"] == "ci_mode"


def test_ci_mode_not_ready_when_production_gates_fail(monkeypatch):
    mod = _base_patches(monkeypatch, production_ready=False)
    _inject_env_contract(monkeypatch, mod, "pass")
    payload = mod.evaluate_alpha_preflight(ci_mode=True)
    assert payload["ready"] is False
    check_by_name = {c["name"]: c for c in payload.get("checks", [])}
    assert check_by_name["production_gates.ready"]["ok"] is False


def test_ci_mode_not_ready_when_env_contract_fails(monkeypatch):
    mod = _base_patches(monkeypatch, production_ready=True)
    _inject_env_contract(monkeypatch, mod, "fail")
    payload = mod.evaluate_alpha_preflight(ci_mode=True)
    assert payload["ready"] is False
    check_by_name = {c["name"]: c for c in payload.get("checks", [])}
    assert check_by_name["config.alpha_env_contract"]["ok"] is False


def test_runtime_mode_not_ready_on_repeated_active_provider_breach(monkeypatch):
    codex_obs = {
        "summary": {"available": True, "mode": "observe", "derived": {"window_activity_rows": 12}},
        "gates": {"passing": True},
        "alert": {"level": "ok"},
    }
    fidelity_obs = {
        "providers": {
            "claude": {"available": True, "window_activity_rows": 31},
            "openclaw": {"available": False},
            "codex": {"available": True, "window_activity_rows": 8},
        },
        "alerts": {
            "providers": {
                "claude": {
                    "level": "warning",
                    "consecutive_breach_windows": 2,
                    "breaches": [{"name": "tool_result_capture_rate", "actual": 0.3}],
                },
                "openclaw": {"level": "unknown", "consecutive_breach_windows": 0, "breaches": []},
                "codex": {"level": "ok", "consecutive_breach_windows": 0, "breaches": []},
            }
        },
    }
    mod = _runtime_patches(monkeypatch, codex_obs=codex_obs, fidelity_obs=fidelity_obs, production_ready=True)
    _inject_env_contract(monkeypatch, mod, "pass")

    payload = mod.evaluate_alpha_preflight(ci_mode=False)
    check_by_name = {c["name"]: c for c in payload.get("checks", [])}
    assert payload["ready"] is False
    assert check_by_name["workflow_fidelity.active_provider_breach_budget"]["ok"] is False
    degraded = check_by_name["workflow_fidelity.active_provider_breach_budget"]["value"]["degraded_active"]
    assert degraded[0]["provider"] == "claude"
    assert degraded[0]["consecutive_breach_windows"] == 2


def test_runtime_mode_ready_when_only_provider_unavailable(monkeypatch):
    codex_obs = {
        "summary": {"available": True, "mode": "observe", "derived": {"window_activity_rows": 0}},
        "gates": {"passing": True},
        "alert": {"level": "ok"},
    }
    fidelity_obs = {
        "providers": {
            "openclaw": {"available": False},
        },
        "alerts": {
            "providers": {
                "openclaw": {"level": "unknown", "consecutive_breach_windows": 0, "breaches": []},
            }
        },
    }
    mod = _runtime_patches(monkeypatch, codex_obs=codex_obs, fidelity_obs=fidelity_obs, production_ready=True)
    _inject_env_contract(monkeypatch, mod, "pass")

    payload = mod.evaluate_alpha_preflight(ci_mode=False)
    check_by_name = {c["name"]: c for c in payload.get("checks", [])}
    assert payload["ready"] is True
    assert check_by_name["workflow_fidelity.unavailable_providers_reported"]["ok"] is True
    unavailable = check_by_name["workflow_fidelity.unavailable_providers_reported"]["value"]["unavailable_providers"]
    assert unavailable == ["openclaw"]


def test_runtime_mode_not_ready_when_runtime_hygiene_exceeds_budget(monkeypatch):
    codex_obs = {
        "summary": {"available": True, "mode": "observe", "derived": {"window_activity_rows": 4}},
        "gates": {"passing": True},
        "alert": {"level": "ok"},
    }
    fidelity_obs = {
        "providers": {"codex": {"available": True, "window_activity_rows": 4}},
        "alerts": {"providers": {"codex": {"level": "ok", "consecutive_breach_windows": 0, "breaches": []}}},
    }
    runtime_hygiene = {
        "shadow": {"ok": False, "lines": 26000, "soft_cap_lines": 21000},
        "wal": {"ok": True, "size_bytes": 200000, "max_bytes": 1048576},
    }
    mod = _runtime_patches(
        monkeypatch,
        codex_obs=codex_obs,
        fidelity_obs=fidelity_obs,
        production_ready=True,
        runtime_hygiene=runtime_hygiene,
    )
    _inject_env_contract(monkeypatch, mod, "pass")

    payload = mod.evaluate_alpha_preflight(ci_mode=False)
    check_by_name = {c["name"]: c for c in payload.get("checks", [])}
    assert payload["ready"] is False
    assert check_by_name["runtime_hygiene.shadow_log_within_cap"]["ok"] is False


def test_runtime_mode_not_ready_when_known_helpfulness_coverage_low(monkeypatch):
    codex_obs = {
        "summary": {"available": True, "mode": "observe", "derived": {"window_activity_rows": 4}},
        "gates": {"passing": True},
        "alert": {"level": "ok"},
    }
    fidelity_obs = {
        "providers": {"codex": {"available": True, "window_activity_rows": 4}},
        "alerts": {"providers": {"codex": {"level": "ok", "consecutive_breach_windows": 0, "breaches": []}}},
    }
    advisory_quality = {
        "path": "mock",
        "available": True,
        "total_events": 500,
        "known_helpfulness_total": 5,
        "known_helpfulness_coverage": 0.01,
    }
    mod = _runtime_patches(
        monkeypatch,
        codex_obs=codex_obs,
        fidelity_obs=fidelity_obs,
        production_ready=True,
        advisory_quality=advisory_quality,
    )
    _inject_env_contract(monkeypatch, mod, "pass")

    payload = mod.evaluate_alpha_preflight(ci_mode=False)
    check_by_name = {c["name"]: c for c in payload.get("checks", [])}
    assert payload["ready"] is False
    assert check_by_name["advisory_quality.known_helpfulness_coverage"]["ok"] is False


def test_runtime_mode_not_ready_when_provider_canary_fails(monkeypatch):
    codex_obs = {
        "summary": {"available": True, "mode": "observe", "derived": {"window_activity_rows": 4}},
        "gates": {"passing": True},
        "alert": {"level": "ok"},
    }
    fidelity_obs = {
        "providers": {"codex": {"available": True, "window_activity_rows": 4}},
        "alerts": {"providers": {"codex": {"level": "ok", "consecutive_breach_windows": 0, "breaches": []}}},
    }
    canary_obs = {
        "providers": {
            "codex": {"active": True, "passed": False, "reasons": ["unknown_rate>90.0%"]},
        },
        "active_providers": ["codex"],
        "failing_active": ["codex"],
        "ready": False,
    }
    mod = _runtime_patches(
        monkeypatch,
        codex_obs=codex_obs,
        fidelity_obs=fidelity_obs,
        canary_obs=canary_obs,
        production_ready=True,
    )
    _inject_env_contract(monkeypatch, mod, "pass")

    payload = mod.evaluate_alpha_preflight(ci_mode=False)
    check_by_name = {c["name"]: c for c in payload.get("checks", [])}
    assert payload["ready"] is False
    assert check_by_name["advisory_quality.provider_canary_active_pass"]["ok"] is False
