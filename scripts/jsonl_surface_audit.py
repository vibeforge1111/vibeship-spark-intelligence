#!/usr/bin/env python3
"""Audit JSONL surface usage in code to guide store-consolidation waves."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "benchmarks" / "out" / "alpha_start"
SCAN_DIRS = ("lib", "scripts", "hooks", "tests")
JSONL_RE = re.compile(r"jsonl|\.jsonl")


def _iter_py_files() -> List[Path]:
    files: List[Path] = []
    for name in SCAN_DIRS:
        base = ROOT / name
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path.is_file():
                files.append(path)
    return sorted(files)


def _count_hits(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return 0
    return int(len(JSONL_RE.findall(text)))


def _audit() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    total_hits = 0
    dir_hits: Dict[str, int] = {}
    for path in _iter_py_files():
        hits = _count_hits(path)
        if hits <= 0:
            continue
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        top = rel.split("/", 1)[0] if "/" in rel else rel
        total_hits += hits
        dir_hits[top] = int(dir_hits.get(top, 0)) + int(hits)
        rows.append({"file": rel, "hits": int(hits)})

    rows.sort(key=lambda r: (-int(r["hits"]), str(r["file"])))
    dir_rows = [{"scope": k, "hits": int(v)} for k, v in sorted(dir_hits.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "totals": {
            "jsonl_hits": int(total_hits),
            "files_with_jsonl_hits": int(len(rows)),
            "scopes_with_hits": int(len(dir_rows)),
        },
        "scope_summary": dir_rows,
        "file_summary": rows,
    }


def _render_markdown(payload: Dict[str, Any]) -> str:
    totals = payload.get("totals") or {}
    lines = [
        "# JSONL Surface Audit",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- jsonl_hits: `{totals.get('jsonl_hits', 0)}`",
        f"- files_with_jsonl_hits: `{totals.get('files_with_jsonl_hits', 0)}`",
        "",
        "## Scope Summary",
        "",
        "| scope | hits |",
        "|---|---:|",
    ]
    for row in payload.get("scope_summary") or []:
        lines.append(f"| {row.get('scope')} | {row.get('hits')} |")
    lines.extend(
        [
            "",
            "## Top Files",
            "",
            "| file | hits |",
            "|---|---:|",
        ]
    )
    for row in (payload.get("file_summary") or [])[:60]:
        lines.append(f"| {row.get('file')} | {row.get('hits')} |")
    lines.append("")
    return "\n".join(lines)


def _write_reports(payload: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    json_path = out_dir / f"jsonl_surface_audit_{run_id}.json"
    md_path = out_dir / f"jsonl_surface_audit_{run_id}.md"
    latest_json = out_dir / "jsonl_surface_audit_latest.json"
    latest_md = out_dir / "jsonl_surface_audit_latest.md"
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
    ap = argparse.ArgumentParser(description="Audit JSONL references across code.")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory for audit artifacts.")
    args = ap.parse_args()

    payload = _audit()
    artifacts = _write_reports(payload, Path(args.out_dir))
    print(json.dumps({"ok": True, "totals": payload.get("totals"), **artifacts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

