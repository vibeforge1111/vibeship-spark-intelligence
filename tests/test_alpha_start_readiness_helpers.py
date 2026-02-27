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


def test_gap_stage_strict_thresholds_pass(monkeypatch):
    mod = _load_module()

    def _fake_run(_cmd, *, timeout_s):
        _ = timeout_s
        return {
            "returncode": 0,
            "stdout": '{"counts":{"advisory_files":4,"tuneable_keys":286,"distillation_files":3,"lib_jsonl_runtime_ext_refs":146},"report_json":"gap.json","report_md":"gap.md"}',
            "stderr": "",
            "duration_s": 0.01,
        }

    monkeypatch.setattr(mod, "_run_command", _fake_run)
    stage = mod._gap_stage(
        strict=True,
        timeout_s=10,
        max_advisory_files=4,
        max_tuneable_keys=300,
        max_distillation_files=3,
        max_lib_jsonl_runtime_ext_refs=200,
    )
    assert stage.ok is True
    assert stage.details["advisory_files"] == 4


def test_gap_stage_strict_thresholds_fail(monkeypatch):
    mod = _load_module()

    def _fake_run(_cmd, *, timeout_s):
        _ = timeout_s
        return {
            "returncode": 0,
            "stdout": '{"counts":{"advisory_files":8,"tuneable_keys":400,"distillation_files":5,"lib_jsonl_runtime_ext_refs":350}}',
            "stderr": "",
            "duration_s": 0.01,
        }

    monkeypatch.setattr(mod, "_run_command", _fake_run)
    stage = mod._gap_stage(
        strict=True,
        timeout_s=10,
        max_advisory_files=4,
        max_tuneable_keys=300,
        max_distillation_files=3,
        max_lib_jsonl_runtime_ext_refs=200,
    )
    assert stage.ok is False
