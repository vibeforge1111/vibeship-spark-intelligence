from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "alpha_start_readiness.py"
    name = "alpha_start_readiness_script"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_parse_json_payload_direct_object():
    mod = _load_module()
    payload = mod._parse_json_payload('{"ok": true, "runs": 3}')
    assert payload["ok"] is True
    assert payload["runs"] == 3


def test_parse_json_payload_with_noise_prefix():
    mod = _load_module()
    text = "log line before\n{\n  \"ok\": true,\n  \"promotion_pass_rate\": 1.0\n}\n"
    payload = mod._parse_json_payload(text)
    assert payload["ok"] is True
    assert abs(float(payload["promotion_pass_rate"]) - 1.0) < 1e-9


def test_parse_csv_dedupes_and_skips_empty():
    mod = _load_module()
    values = mod._parse_csv("a,b,a,,b,c")
    assert values == ["a", "b", "c"]

