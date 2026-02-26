from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "memory_json_consumer_gate.py"
    name = "memory_json_consumer_gate_script"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_evaluate_gate_passes_when_under_thresholds():
    mod = _load_module()
    report = {"totals": {"hits": 20, "runtime_hits": 0}}
    gate = mod._evaluate_gate(report, max_runtime_hits=0, max_total_hits=50)
    assert gate["pass"] is True
    assert gate["pass_runtime"] is True
    assert gate["pass_total"] is True


def test_evaluate_gate_fails_when_runtime_exceeds_limit():
    mod = _load_module()
    report = {"totals": {"hits": 10, "runtime_hits": 3}}
    gate = mod._evaluate_gate(report, max_runtime_hits=0, max_total_hits=50)
    assert gate["pass"] is False
    assert gate["pass_runtime"] is False
    assert gate["pass_total"] is True

