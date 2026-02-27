from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


def _load_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "advisory_spine_parity_gate.py"
    name = "advisory_spine_parity_gate_script"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_latest_streak_counts_trailing_passes(tmp_path):
    mod = _load_module()
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(
            [
                json.dumps({"pass": False}),
                json.dumps({"pass": True}),
                json.dumps({"pass": True}),
                json.dumps({"pass": True}),
            ]
        ),
        encoding="utf-8",
    )
    assert mod._latest_streak(ledger) == 3
