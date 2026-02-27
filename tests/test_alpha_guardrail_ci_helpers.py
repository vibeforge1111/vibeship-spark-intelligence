from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


def _load_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "alpha_guardrail_ci.py"
    name = "alpha_guardrail_ci_script"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_parse_json_payload_with_noise_prefix():
    mod = _load_module()
    text = "log line\n{\n  \"ok\": true,\n  \"counts\": {}\n}\n"
    payload = mod._parse_json_payload(text)
    assert payload["ok"] is True


def test_docs_guardrail_detects_canonical_legacy_refs(tmp_path, monkeypatch):
    mod = _load_module()
    report = {
        "rows": [
            {"file": "docs/SPARK_ALPHA_RUNTIME_CONTRACT.md", "legacy_ref_count": 1},
            {"file": "docs/other.md", "legacy_ref_count": 2},
        ]
    }
    report_path = tmp_path / "docs_sweep.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    def _fake_run(_cmd):
        payload = {"report_json": str(report_path)}
        return 0, json.dumps(payload), ""

    monkeypatch.setattr(mod, "_run", _fake_run)
    stage = mod._docs_guardrail()
    assert stage["ok"] is False
    assert len(stage["details"]["canonical_hits"]) == 1


def test_gap_guardrail_passes_when_within_thresholds(monkeypatch):
    mod = _load_module()

    def _fake_run(_cmd):
        payload = {
            "counts": {
                "advisory_files": 4,
                "tuneable_keys": 300,
                "distillation_files": 3,
                "lib_jsonl_runtime_ext_refs": 120,
            },
            "status": {"orchestrator_module_present": False},
        }
        return 0, json.dumps(payload), ""

    monkeypatch.setattr(mod, "_run", _fake_run)
    stage = mod._gap_guardrail(
        max_advisory_files=4,
        max_tuneable_keys=320,
        max_distillation_files=3,
        max_lib_jsonl_runtime_ext_refs=140,
    )
    assert stage["ok"] is True


def test_gap_guardrail_fails_on_threshold_regression(monkeypatch):
    mod = _load_module()

    def _fake_run(_cmd):
        payload = {
            "counts": {
                "advisory_files": 6,
                "tuneable_keys": 450,
                "distillation_files": 5,
                "lib_jsonl_runtime_ext_refs": 210,
            },
            "status": {"orchestrator_module_present": True},
        }
        return 0, json.dumps(payload), ""

    monkeypatch.setattr(mod, "_run", _fake_run)
    stage = mod._gap_guardrail(
        max_advisory_files=4,
        max_tuneable_keys=320,
        max_distillation_files=3,
        max_lib_jsonl_runtime_ext_refs=140,
    )
    assert stage["ok"] is False
    checks = stage["details"]["checks"]
    assert checks["advisory_files_ok"] is False
    assert checks["orchestrator_removed_ok"] is False


def test_runtime_cycle_guardrail_pass(monkeypatch):
    mod = _load_module()
    monkeypatch.setattr(mod, "_collect_runtime_cycles", lambda: [])
    stage = mod._runtime_cycle_guardrail(max_runtime_cycles=0)
    assert stage["ok"] is True
    assert stage["details"]["runtime_cycle_count"] == 0


def test_runtime_cycle_guardrail_fail(monkeypatch):
    mod = _load_module()
    monkeypatch.setattr(mod, "_collect_runtime_cycles", lambda: [["lib.a", "lib.b"]])
    stage = mod._runtime_cycle_guardrail(max_runtime_cycles=0)
    assert stage["ok"] is False
    assert stage["details"]["runtime_cycle_count"] == 1
