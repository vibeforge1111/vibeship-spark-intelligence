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
