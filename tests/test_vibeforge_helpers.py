from __future__ import annotations

import importlib.util
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
