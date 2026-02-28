from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "production_noise_regression.py"
    spec = importlib.util.spec_from_file_location("production_noise_regression", script)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_gate_eval_passes_expected_thresholds():
    mod = _load_module()
    gates = mod._gate_eval(
        report={
            "expected_noise_rows": 42,
            "recall": 0.91,
            "false_positive_rate": 0.11,
        },
        min_expected_noise_rows=20,
        min_recall=0.9,
        max_fp_rate=0.15,
    )
    assert gates["expected_noise_coverage_gate"]["ok"] is True
    assert gates["noise_recall_gate"]["ok"] is True
    assert gates["signal_fp_gate"]["ok"] is True


def test_gate_eval_fails_when_recall_below_floor():
    mod = _load_module()
    gates = mod._gate_eval(
        report={
            "expected_noise_rows": 42,
            "recall": 0.5,
            "false_positive_rate": 0.11,
        },
        min_expected_noise_rows=20,
        min_recall=0.9,
        max_fp_rate=0.15,
    )
    assert gates["noise_recall_gate"]["ok"] is False

