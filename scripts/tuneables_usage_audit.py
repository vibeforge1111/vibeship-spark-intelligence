#!/usr/bin/env python3
"""Generate schema-key usage signals for safe tuneables reduction."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "benchmarks" / "out" / "alpha_start"
SEARCH_DIRS = ["lib", "scripts", "hooks", "tests"]
SCHEMA_PATH = "lib/tuneables_schema.py"


def _iter_source_files() -> List[Path]:
    out: List[Path] = []
    for name in SEARCH_DIRS:
        base = ROOT / name
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path.is_file():
                out.append(path)
    return sorted(out)


def _load_text_map(paths: Iterable[Path]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for path in paths:
        key = str(path.relative_to(ROOT)).replace("\\", "/")
        try:
            out[key] = path.read_text(encoding="utf-8")
        except Exception:
            out[key] = ""
    return out


def _key_usage_count(text_map: Dict[str, str], key: str) -> Tuple[int, List[str]]:
    safe = re.escape(str(key))
    patterns = [
        re.compile(rf'["\']{safe}["\']'),
        re.compile(rf"\.get\(\s*['\"]{safe}['\"]"),
        re.compile(rf"\[\s*['\"]{safe}['\"]\s*\]"),
    ]
    total = 0
    files: List[str] = []
    for path, text in text_map.items():
        hits = 0
        for rx in patterns:
            hits += len(rx.findall(text))
        if hits > 0:
            total += hits
            files.append(path)
    return int(total), sorted(files)


def _load_schema() -> Dict[str, Dict[str, Any]]:
    from lib.tuneables_schema import SCHEMA

    return {str(section): dict(keys) for section, keys in SCHEMA.items()}


def _audit() -> Dict[str, Any]:
    schema = _load_schema()
    files = _iter_source_files()
    text_map = _load_text_map(files)
    external_text_map = {k: v for k, v in text_map.items() if k != SCHEMA_PATH}

    section_rows: List[Dict[str, Any]] = []
    orphan_rows: List[Dict[str, Any]] = []
    orphan_external_rows: List[Dict[str, Any]] = []
    total_keys = 0
    total_hits = 0
    total_external_hits = 0

    for section_name, section_spec in sorted(schema.items()):
        keys = sorted(section_spec.keys())
        section_keys = len(keys)
        section_hits = 0
        section_external_hits = 0
        used_keys = 0
        orphans = 0
        external_used_keys = 0
        external_orphans = 0
        for key in keys:
            key_hits, key_files = _key_usage_count(text_map, key)
            external_hits, external_files = _key_usage_count(external_text_map, key)
            total_keys += 1
            total_hits += key_hits
            total_external_hits += external_hits
            section_hits += key_hits
            section_external_hits += external_hits
            if key_hits > 0:
                used_keys += 1
            else:
                orphans += 1
                orphan_rows.append(
                    {
                        "section": section_name,
                        "key": key,
                        "hits": 0,
                        "files": [],
                    }
                )
            if external_hits > 0:
                external_used_keys += 1
            else:
                external_orphans += 1
                orphan_external_rows.append(
                    {
                        "section": section_name,
                        "key": key,
                        "hits": 0,
                        "files": [],
                    }
                )
        section_rows.append(
            {
                "section": section_name,
                "keys": int(section_keys),
                "used_keys": int(used_keys),
                "orphan_keys": int(orphans),
                "hits": int(section_hits),
                "external_used_keys": int(external_used_keys),
                "external_orphan_keys": int(external_orphans),
                "external_hits": int(section_external_hits),
            }
        )

    section_rows.sort(
        key=lambda row: (
            -int(row.get("external_orphan_keys", 0)),
            -int(row.get("orphan_keys", 0)),
            str(row.get("section", "")),
        )
    )
    orphan_rows.sort(key=lambda row: (str(row.get("section", "")), str(row.get("key", ""))))
    orphan_external_rows.sort(key=lambda row: (str(row.get("section", "")), str(row.get("key", ""))))

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "totals": {
            "sections": int(len(schema)),
            "keys": int(total_keys),
            "hits": int(total_hits),
            "orphan_keys": int(len(orphan_rows)),
            "external_hits": int(total_external_hits),
            "external_orphan_keys": int(len(orphan_external_rows)),
        },
        "section_summary": section_rows,
        "orphan_keys": orphan_rows,
        "external_orphan_keys": orphan_external_rows,
        "scanned_files": int(len(text_map)),
        "external_scanned_files": int(len(external_text_map)),
    }


def _render_markdown(payload: Dict[str, Any]) -> str:
    totals = payload.get("totals") or {}
    lines = [
        "# Tuneables Usage Audit",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- scanned_files: `{payload.get('scanned_files', 0)}`",
        f"- external_scanned_files: `{payload.get('external_scanned_files', 0)}`",
        f"- sections: `{totals.get('sections', 0)}`",
        f"- keys: `{totals.get('keys', 0)}`",
        f"- orphan_keys: `{totals.get('orphan_keys', 0)}`",
        f"- external_orphan_keys: `{totals.get('external_orphan_keys', 0)}`",
        "",
        "## Top Sections By Orphan Keys",
        "",
        "| section | keys | used_keys | orphan_keys | hits | external_used | external_orphan | external_hits |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in (payload.get("section_summary") or [])[:20]:
        lines.append(
            "| {section} | {keys} | {used_keys} | {orphan_keys} | {hits} | {external_used_keys} | {external_orphan_keys} | {external_hits} |".format(
                section=row.get("section"),
                keys=row.get("keys"),
                used_keys=row.get("used_keys"),
                orphan_keys=row.get("orphan_keys"),
                hits=row.get("hits"),
                external_used_keys=row.get("external_used_keys"),
                external_orphan_keys=row.get("external_orphan_keys"),
                external_hits=row.get("external_hits"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _write_reports(payload: Dict[str, Any], *, out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    json_path = out_dir / f"tuneables_usage_audit_{run_id}.json"
    md_path = out_dir / f"tuneables_usage_audit_{run_id}.md"
    latest_json = out_dir / "tuneables_usage_audit_latest.json"
    latest_md = out_dir / "tuneables_usage_audit_latest.md"
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
    ap = argparse.ArgumentParser(description="Generate tuneables usage audit report.")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory for artifacts.")
    args = ap.parse_args()

    payload = _audit()
    artifacts = _write_reports(payload, out_dir=Path(args.out_dir))
    print(
        json.dumps(
            {
                "ok": True,
                "totals": payload.get("totals"),
                "scanned_files": payload.get("scanned_files"),
                **artifacts,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
