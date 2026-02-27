#!/usr/bin/env python3
"""Emit current Spark Alpha gap metrics (done/not-done baseline counters)."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "benchmarks" / "out" / "alpha_start"


def _all_files(paths: Iterable[Path], *, suffixes: Tuple[str, ...] = (".py",)) -> List[Path]:
    out: List[Path] = []
    for base in paths:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in suffixes:
                out.append(path)
    return sorted(out)


def _count_regex_hits(files: Iterable[Path], pattern: str) -> int:
    rx = re.compile(pattern)
    total = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        total += len(rx.findall(text))
    return int(total)


def _load_tuneable_shape() -> Dict[str, int]:
    sections = 0
    keys = 0
    try:
        from lib.tuneables_schema import SCHEMA

        sections = int(len(SCHEMA))
        keys = int(sum(len(v) for v in SCHEMA.values()))
    except Exception:
        pass
    return {"sections": sections, "keys": keys}


def _audit() -> Dict[str, Any]:
    lib_dir = ROOT / "lib"
    scripts_dir = ROOT / "scripts"

    advisory_files = sorted(lib_dir.glob("*advisory*.py"))
    distillation_files = sorted(path for path in _all_files([lib_dir]) if "distill" in path.as_posix().lower())
    lib_py_files = _all_files([lib_dir])
    jsonl_refs = _count_regex_hits(lib_py_files, r"jsonl|\.jsonl")

    tuneables = _load_tuneable_shape()

    vibeforge_path = scripts_dir / "vibeforge.py"
    vibeforge_text = ""
    if vibeforge_path.exists():
        try:
            vibeforge_text = vibeforge_path.read_text(encoding="utf-8")
        except Exception:
            vibeforge_text = ""

    has_evolve_blocks = "evolve_blocks" in vibeforge_text
    has_code_evolve_lane = any(token in vibeforge_text for token in ("apply_patch", "git apply", "patch_text"))

    compaction_files = {
        "lib/memory_compaction.py": (ROOT / "lib" / "memory_compaction.py").exists(),
        "lib/context_sync.py": (ROOT / "lib" / "context_sync.py").exists(),
        "scripts/cognitive_memory_compaction.py": (ROOT / "scripts" / "cognitive_memory_compaction.py").exists(),
    }

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "counts": {
            "advisory_files": int(len(advisory_files)),
            "tuneable_sections": int(tuneables.get("sections", 0)),
            "tuneable_keys": int(tuneables.get("keys", 0)),
            "lib_jsonl_refs": int(jsonl_refs),
            "distillation_files": int(len(distillation_files)),
        },
        "status": {
            "orchestrator_module_present": (ROOT / "lib" / "advisory_orchestrator.py").exists(),
            "compaction_stack_present": all(bool(v) for v in compaction_files.values()),
            "vibeforge_has_evolve_blocks": bool(has_evolve_blocks),
            "vibeforge_has_code_evolve_lane": bool(has_code_evolve_lane),
        },
        "files": {
            "advisory": [str(path.relative_to(ROOT)) for path in advisory_files],
            "distillation": [str(path.relative_to(ROOT)) for path in distillation_files],
            "compaction_components": compaction_files,
            "vibeforge": str(vibeforge_path.relative_to(ROOT)),
        },
    }


def _render_markdown(payload: Dict[str, Any]) -> str:
    counts = payload.get("counts") or {}
    status = payload.get("status") or {}
    lines = [
        "# Spark Alpha Gap Audit",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        "",
        "## Counts",
        "",
        f"- advisory_files: `{counts.get('advisory_files', 0)}`",
        f"- tuneable_sections: `{counts.get('tuneable_sections', 0)}`",
        f"- tuneable_keys: `{counts.get('tuneable_keys', 0)}`",
        f"- lib_jsonl_refs: `{counts.get('lib_jsonl_refs', 0)}`",
        f"- distillation_files: `{counts.get('distillation_files', 0)}`",
        "",
        "## Status",
        "",
        f"- orchestrator_module_present: `{status.get('orchestrator_module_present')}`",
        f"- compaction_stack_present: `{status.get('compaction_stack_present')}`",
        f"- vibeforge_has_evolve_blocks: `{status.get('vibeforge_has_evolve_blocks')}`",
        f"- vibeforge_has_code_evolve_lane: `{status.get('vibeforge_has_code_evolve_lane')}`",
        "",
    ]
    return "\n".join(lines)


def _write_reports(payload: Dict[str, Any], *, out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    json_path = out_dir / f"alpha_gap_audit_{run_id}.json"
    md_path = out_dir / f"alpha_gap_audit_{run_id}.md"
    latest_json = out_dir / "alpha_gap_audit_latest.json"
    latest_md = out_dir / "alpha_gap_audit_latest.md"
    body = json.dumps(payload, indent=2, ensure_ascii=True)
    json_path.write_text(body, encoding="utf-8")
    latest_json.write_text(body, encoding="utf-8")
    md = _render_markdown(payload)
    md_path.write_text(md, encoding="utf-8")
    latest_md.write_text(md, encoding="utf-8")
    return {
        "report_json": str(json_path),
        "report_md": str(md_path),
        "report_latest_json": str(latest_json),
        "report_latest_md": str(latest_md),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate Spark Alpha gap-audit counters.")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory for artifacts.")
    args = ap.parse_args()

    payload = _audit()
    artifacts = _write_reports(payload, out_dir=Path(args.out_dir))
    print(
        json.dumps(
            {
                "ok": True,
                "counts": payload.get("counts"),
                "status": payload.get("status"),
                **artifacts,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

