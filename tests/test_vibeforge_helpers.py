from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


def _load_vibeforge_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "vibeforge.py"
    name = "vibeforge_script"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_goal_reached_respects_optimize_direction():
    vibeforge = _load_vibeforge_module()
    assert vibeforge._goal_reached(0.9, 0.85, "maximize") is True
    assert vibeforge._goal_reached(0.8, 0.85, "maximize") is False
    assert vibeforge._goal_reached(4.0, 5.0, "minimize") is True
    assert vibeforge._goal_reached(6.0, 5.0, "minimize") is False


def test_compare_operators():
    vibeforge = _load_vibeforge_module()
    assert vibeforge._compare(1.0, ">=", 1.0) is True
    assert vibeforge._compare(1.0, ">", 2.0) is False
    assert vibeforge._compare(1.0, "<=", 2.0) is True
    assert vibeforge._compare(2.0, "<", 2.0) is False
    assert vibeforge._compare(2.0, "==", 2.0) is True


def test_regret_rate_stays_low_when_reward_zero():
    vibeforge = _load_vibeforge_module()
    cycle_regret, cumulative, rate = vibeforge._update_regret([], reward=0.0, gap_before=999.0)
    assert cycle_regret >= 0.0
    assert cumulative >= 0.0
    assert rate <= 1.0


def test_rank_candidates_prefers_winning_signature():
    vibeforge = _load_vibeforge_module()
    candidates = [
        {"section": "advisor", "key": "min_rank_score", "op": "add", "delta": -0.02},
        {"section": "advisor", "key": "max_advice_items", "op": "add", "delta": 1},
    ]
    ledger = [
        {
            "outcome": "promoted",
            "delta": 0.03,
            "proposal": {"type": "tuneable", "section": "advisor", "key": "max_advice_items", "from": 2, "to": 3},
        },
        {
            "outcome": "rolled_back",
            "delta": -0.01,
            "proposal": {"type": "tuneable", "section": "advisor", "key": "min_rank_score", "from": 0.3, "to": 0.28},
        },
    ]
    ranked = vibeforge._rank_candidates(candidates, ledger)
    assert ranked[0]["key"] == "max_advice_items"


def test_find_last_promoted_with_existing_backup(tmp_path):
    vibeforge = _load_vibeforge_module()
    backup = tmp_path / "backup.json"
    backup.write_text("{}", encoding="utf-8")
    ledger = [
        {"cycle": 1, "outcome": "promoted", "proposal": {"type": "tuneable", "section": "a", "key": "x"}, "backup_path": str(backup)},
        {"cycle": 2, "outcome": "rolled_back"},
    ]
    row = vibeforge._find_last_promoted_with_backup(ledger)
    assert row is not None
    assert int(row.get("cycle", 0)) == 1


def test_momentum_candidates_follow_previous_wins():
    vibeforge = _load_vibeforge_module()
    ledger = [
        {
            "outcome": "promoted",
            "proposal": {
                "type": "tuneable",
                "section": "advisor",
                "key": "max_advice_items",
                "from": 2,
                "to": 3,
            },
        }
    ]
    tuneables = {"advisor": {"max_advice_items": 3}}
    momentum = vibeforge._momentum_candidates(ledger, tuneables)
    assert momentum
    assert momentum[0]["section"] == "advisor"
    assert momentum[0]["key"] == "max_advice_items"
    assert float(momentum[0]["delta"]) > 0.0


def test_resolve_metric_supports_benchmark_json_file(tmp_path):
    vibeforge = _load_vibeforge_module()
    benchmark = tmp_path / "bench.json"
    benchmark.write_text(json.dumps({"retrieval_precision_p5": 0.41}), encoding="utf-8")
    spec = {
        "source": "benchmark",
        "field": "retrieval_precision_p5",
        "path": str(benchmark),
    }
    value = vibeforge._resolve_metric(spec, {"production_gates": {}, "carmack_kpi": {}}, benchmark_cache={})
    assert abs(value - 0.41) < 1e-9


def test_resolve_metric_supports_benchmark_command_stdout_json():
    vibeforge = _load_vibeforge_module()
    spec = {
        "source": "benchmark",
        "field": "metric",
        "command": [sys.executable, "-c", "import json; print(json.dumps({'metric': 0.73}))"],
        "json_from_stdout": True,
    }
    value = vibeforge._resolve_metric(spec, {"production_gates": {}, "carmack_kpi": {}}, benchmark_cache={})
    assert abs(value - 0.73) < 1e-9


def test_evaluate_benchmark_checks_supports_blocking_field(tmp_path):
    vibeforge = _load_vibeforge_module()
    benchmark = tmp_path / "bench.json"
    benchmark.write_text(json.dumps({"precision": 0.42}), encoding="utf-8")
    goal = {
        "benchmark_checks": [
            {
                "name": "precision_guard",
                "source": "benchmark",
                "field": "precision",
                "operator": ">=",
                "threshold": 0.40,
                "path": str(benchmark),
                "blocking": True,
            }
        ]
    }
    checks = vibeforge._evaluate_benchmark_checks(goal, sources={"production_gates": {}, "carmack_kpi": {}}, benchmark_cache={})
    assert len(checks) == 1
    assert checks[0]["ok"] is True
    assert checks[0]["blocking"] is True


def test_blocking_checks_ok_ignores_non_blocking_failures():
    vibeforge = _load_vibeforge_module()
    checks = [
        {"name": "main_guard", "ok": True, "blocking": True},
        {"name": "info_only", "ok": False, "blocking": False},
    ]
    assert vibeforge._blocking_checks_ok(checks) is True
