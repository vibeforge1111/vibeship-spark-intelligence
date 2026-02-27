#!/usr/bin/env python3
"""Audit and optionally migrate legacy advisory module references in docs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
OBS_DIR = ROOT / "_observatory"

LEGACY_MAP: Dict[str, str] = {
    "lib/advisory_engine.py": "lib/advisory_engine_alpha.py",
    "lib/advisory_orchestrator.py": "lib/advisory_engine_alpha.py",
}

CANONICAL_DOCS = {
    "README.md",
    "docs/CONFIG_AUTHORITY.md",
    "docs/PROGRAM_STATUS.md",
    "docs/DOCS_INDEX.md",
    "docs/SPARK_ALPHA_RUNTIME_CONTRACT.md",
    "docs/SPARK_ALPHA_ARCHITECTURE_NOW.md",
    "docs/SPARK_ALPHA_TRANSFORMATION_REPORT.md",
}


def _iter_docs() -> List[Path]:
    out: List[Path] = []
    for p in ROOT.rglob("*.md"):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel.startswith(".venv/") or rel.startswith("node_modules/"):
            continue
        out.append(p)
    return sorted(out)


def _scan(path: Path) -> List[Tuple[str, int]]:
    found: List[Tuple[str, int]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return found
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        for legacy in LEGACY_MAP:
            if legacy in line:
                found.append((legacy, idx))
    return found


def _replace(text: str) -> str:
    out = text
    for legacy, repl in LEGACY_MAP.items():
        out = out.replace(legacy, repl)
    return out


def _render_md(payload: Dict[str, object]) -> str:
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    lines: List[str] = []
    lines.append("# Docs Legacy Ref Sweep")
    lines.append("")
    lines.append(f"- generated_at_utc: `{payload.get('generated_at_utc')}`")
    lines.append(f"- apply_mode: `{payload.get('applied')}`")
    lines.append(f"- scope: `{payload.get('scope')}`")
    lines.append(f"- files_scanned: `{payload.get('files_scanned')}`")
    lines.append(f"- files_with_legacy_refs: `{payload.get('files_with_legacy_refs')}`")
    lines.append(f"- replacements_applied: `{payload.get('replacements_applied')}`")
    lines.append("")
    lines.append("| file | legacy_refs | changed |")
    lines.append("|---|---:|---:|")
    for row in rows:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"| `{row.get('file')}` | {int(row.get('legacy_ref_count', 0) or 0)} | {bool(row.get('changed'))} |"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Apply replacements in selected scope.")
    ap.add_argument(
        "--scope",
        choices=("canonical", "all"),
        default="canonical",
        help="Document scope for apply mode.",
    )
    args = ap.parse_args()

    docs = _iter_docs()
    changed = 0
    rows = []
    with_refs = 0

    for p in docs:
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        hits = _scan(p)
        if hits:
            with_refs += 1
        should_apply = bool(args.apply) and (
            args.scope == "all" or rel in CANONICAL_DOCS
        )
        row = {
            "file": rel,
            "legacy_ref_count": len(hits),
            "legacy_refs": [{"legacy": legacy, "line": ln} for legacy, ln in hits],
            "changed": False,
        }
        if should_apply and hits:
            before = p.read_text(encoding="utf-8", errors="replace")
            after = _replace(before)
            if after != before:
                p.write_text(after, encoding="utf-8")
                row["changed"] = True
                changed += 1
        rows.append(row)

    payload = {
        "ok": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "applied": bool(args.apply),
        "scope": str(args.scope),
        "files_scanned": len(docs),
        "files_with_legacy_refs": with_refs,
        "replacements_applied": changed,
        "rows": rows,
    }

    OBS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OBS_DIR / "docs_legacy_ref_sweep.json"
    md_path = OBS_DIR / "docs_legacy_ref_sweep.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_md(payload) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "applied": bool(args.apply),
                "scope": str(args.scope),
                "files_scanned": len(docs),
                "files_with_legacy_refs": with_refs,
                "replacements_applied": changed,
                "report_json": str(json_path),
                "report_md": str(md_path),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
