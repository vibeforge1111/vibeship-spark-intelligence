from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "alpha_cutover_evidence_pack.py"
    name = "alpha_cutover_evidence_pack_script"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_parse_int_csv_dedupes_and_preserves_order():
    mod = _load_module()
    values = mod._parse_int_csv("42,77,42,101")
    assert values == [42, 77, 101]


def test_build_summary_includes_canary_check_when_enabled():
    mod = _load_module()
    payload = mod._build_summary(
        production={"ready": True, "gate_status": "READY"},
        replay={"ok": True, "promotion_pass_rate": 1.0},
        canary={"ok": False, "status": "rolled_back"},
        run_canary=True,
    )
    checks = payload.get("checks") or {}
    assert checks.get("production_ready") is True
    assert checks.get("replay_pass") is True
    assert checks.get("canary_pass") is False
    assert payload.get("ready_for_cutover") is False


def test_build_summary_skips_canary_when_disabled():
    mod = _load_module()
    payload = mod._build_summary(
        production={"ready": True},
        replay={"ok": True},
        canary={"ok": False},
        run_canary=False,
    )
    checks = payload.get("checks") or {}
    assert "canary_pass" not in checks
    assert payload.get("ready_for_cutover") is True


def test_run_canary_short_circuits_when_inputs_missing(tmp_path):
    mod = _load_module()
    out = mod._run_canary(
        timeout_s=30,
        retrieval_level="2",
        mrr_min=0.35,
        gate_pass_rate_min=0.6,
        advisory_score_min=0.7,
        memory_cases=tmp_path / "missing_memory_cases.json",
        memory_gates=tmp_path / "missing_memory_gates.json",
        advisory_cases=tmp_path / "missing_advisory_cases.json",
    )
    assert out.get("ok") is False
    assert out.get("status") == "input_missing"
