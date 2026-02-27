#!/usr/bin/env python3
"""Fast CI guardrails for Spark Alpha migration integrity."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
DOCS_SWEEP = ROOT / "scripts" / "alpha_docs_legacy_ref_sweep.py"
GAP_AUDIT = ROOT / "scripts" / "alpha_gap_audit.py"

CANONICAL_DOCS = {
    "README.md",
    "docs/CONFIG_AUTHORITY.md",
    "docs/PROGRAM_STATUS.md",
    "docs/DOCS_INDEX.md",
    "docs/SPARK_ALPHA_RUNTIME_CONTRACT.md",
    "docs/SPARK_ALPHA_ARCHITECTURE_NOW.md",
    "docs/SPARK_ALPHA_TRANSFORMATION_REPORT.md",
}


def _parse_json_payload(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        pass
    start = raw.rfind("\n{")
    if start >= 0:
        try:
            payload = json.loads(raw[start + 1 :])
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    return {}


def _run(cmd: List[str]) -> Tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _docs_guardrail() -> Dict[str, Any]:
    code, out, err = _run([sys.executable, str(DOCS_SWEEP), "--scope", "canonical"])
    payload = _parse_json_payload(out)
    report_json = payload.get("report_json")
    canonical_hits: List[Dict[str, Any]] = []
    if isinstance(report_json, str) and report_json:
        try:
            report = json.loads(Path(report_json).read_text(encoding="utf-8"))
            rows = report.get("rows") if isinstance(report.get("rows"), list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                rel = str(row.get("file") or "")
                if rel in CANONICAL_DOCS and int(row.get("legacy_ref_count", 0) or 0) > 0:
                    canonical_hits.append(
                        {
                            "file": rel,
                            "legacy_ref_count": int(row.get("legacy_ref_count", 0) or 0),
                        }
                    )
        except Exception:
            canonical_hits.append({"file": "unreadable_docs_sweep_report", "legacy_ref_count": 1})
    ok = code == 0 and len(canonical_hits) == 0
    return {
        "name": "docs_legacy_refs",
        "ok": bool(ok),
        "returncode": int(code),
        "details": {
            "canonical_hits": canonical_hits,
            "report_json": report_json,
            "stdout_tail": (out or "")[-500:],
            "stderr_tail": (err or "")[-500:],
        },
    }


def _gap_guardrail(
    *,
    max_advisory_files: int,
    max_tuneable_keys: int,
    max_distillation_files: int,
    max_lib_jsonl_runtime_ext_refs: int,
) -> Dict[str, Any]:
    code, out, err = _run([sys.executable, str(GAP_AUDIT)])
    payload = _parse_json_payload(out)
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    advisory_files = int(counts.get("advisory_files", 0) or 0)
    tuneable_keys = int(counts.get("tuneable_keys", 0) or 0)
    distillation_files = int(counts.get("distillation_files", 0) or 0)
    jsonl_runtime_ext_refs = int(counts.get("lib_jsonl_runtime_ext_refs", 0) or 0)
    orchestrator_present = bool(status.get("orchestrator_module_present", False))

    checks = {
        "advisory_files_ok": advisory_files <= int(max_advisory_files),
        "tuneable_keys_ok": tuneable_keys <= int(max_tuneable_keys),
        "distillation_files_ok": distillation_files <= int(max_distillation_files),
        "runtime_ext_jsonl_refs_ok": jsonl_runtime_ext_refs <= int(max_lib_jsonl_runtime_ext_refs),
        "orchestrator_removed_ok": not orchestrator_present,
    }
    ok = code == 0 and all(bool(v) for v in checks.values())
    return {
        "name": "alpha_gap_shape",
        "ok": bool(ok),
        "returncode": int(code),
        "details": {
            "counts": {
                "advisory_files": advisory_files,
                "tuneable_keys": tuneable_keys,
                "distillation_files": distillation_files,
                "lib_jsonl_runtime_ext_refs": jsonl_runtime_ext_refs,
            },
            "checks": checks,
            "thresholds": {
                "max_advisory_files": int(max_advisory_files),
                "max_tuneable_keys": int(max_tuneable_keys),
                "max_distillation_files": int(max_distillation_files),
                "max_lib_jsonl_runtime_ext_refs": int(max_lib_jsonl_runtime_ext_refs),
            },
            "report_json": payload.get("report_json"),
            "stderr_tail": (err or "")[-500:],
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run fast Spark Alpha CI guardrails.")
    ap.add_argument("--max-advisory-files", type=int, default=4)
    ap.add_argument("--max-tuneable-keys", type=int, default=320)
    ap.add_argument("--max-distillation-files", type=int, default=3)
    ap.add_argument("--max-lib-jsonl-runtime-ext-refs", type=int, default=140)
    args = ap.parse_args()

    stages = [
        _docs_guardrail(),
        _gap_guardrail(
            max_advisory_files=int(args.max_advisory_files),
            max_tuneable_keys=int(args.max_tuneable_keys),
            max_distillation_files=int(args.max_distillation_files),
            max_lib_jsonl_runtime_ext_refs=int(args.max_lib_jsonl_runtime_ext_refs),
        ),
    ]
    ok = all(bool(stage.get("ok")) for stage in stages)
    report = {
        "ok": bool(ok),
        "stages": stages,
        "thresholds": {
            "max_advisory_files": int(args.max_advisory_files),
            "max_tuneable_keys": int(args.max_tuneable_keys),
            "max_distillation_files": int(args.max_distillation_files),
            "max_lib_jsonl_runtime_ext_refs": int(args.max_lib_jsonl_runtime_ext_refs),
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

