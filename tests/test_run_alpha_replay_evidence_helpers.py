from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "run_alpha_replay_evidence.py"
    name = "run_alpha_replay_evidence_script"
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


def test_build_summary_rates():
    mod = _load_module()
    rows = [
        {"winner": "alpha", "promotion_gate_pass": True, "eligible_for_cutover": True},
        {"winner": "orchestrator", "promotion_gate_pass": False, "eligible_for_cutover": False},
    ]
    summary = mod._build_summary(rows)
    totals = summary.get("totals") or {}
    assert totals.get("runs") == 2
    assert totals.get("alpha_wins") == 1
    assert totals.get("promotion_passes") == 1
    assert abs(float(totals.get("alpha_win_rate", 0.0)) - 0.5) < 1e-9
    assert abs(float(totals.get("promotion_pass_rate", 0.0)) - 0.5) < 1e-9
