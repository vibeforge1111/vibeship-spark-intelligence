#!/usr/bin/env python3
"""Audit direct JSON memory consumers during SQLite migration.

Focuses on identifying code paths that still reference legacy JSON memory files
so PR-04 retirement work can be sequenced with explicit deletion targets.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "benchmarks" / "out" / "memory_spine_audit"
TOKENS = (
    "cognitive_insights.json",
    "advisory_packet_store.json",
    "mind_advisory_state.json",
)


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    token: str
    line_text: str


def _iter_repo_files(root: Path) -> Iterable[Path]:
    include_roots = ("lib", "scripts", "hooks", "tests", "docs")
    for rel in include_roots:
        base = root / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".db", ".sqlite"}:
                continue
            yield path


def _scan_hits(root: Path, tokens: Iterable[str]) -> List[Hit]:
    patterns = [(token, re.compile(re.escape(token), re.IGNORECASE)) for token in tokens]
    hits: List[Hit] = []
    for path in _iter_repo_files(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for idx, line in enumerate(lines, start=1):
            for token, pattern in patterns:
                if pattern.search(line):
                    hits.append(
                        Hit(
                            path=str(path.relative_to(root)).replace("\\", "/"),
                            line=idx,
                            token=token,
                            line_text=line.strip()[:240],
                        )
                    )
    return hits


def _surface_group(path: str) -> str:
    if path.startswith("lib/"):
        return "runtime_lib"
    if path.startswith("hooks/"):
        return "runtime_hooks"
    if path.startswith("scripts/"):
        return "tooling_scripts"
    if path.startswith("tests/"):
        return "tests"
    if path.startswith("docs/"):
        return "docs"
    return "other"


def _build_report(hits: List[Hit]) -> Dict[str, object]:
    by_group: Dict[str, int] = {}
    by_token: Dict[str, int] = {}
    for hit in hits:
        group = _surface_group(hit.path)
        by_group[group] = int(by_group.get(group, 0) + 1)
        by_token[hit.token] = int(by_token.get(hit.token, 0) + 1)
    details = [
        {
            "path": hit.path,
            "line": hit.line,
            "token": hit.token,
            "surface": _surface_group(hit.path),
            "line_text": hit.line_text,
        }
        for hit in sorted(hits, key=lambda h: (h.path, h.line, h.token))
    ]
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "totals": {
            "hits": len(hits),
            "runtime_hits": sum(1 for hit in hits if _surface_group(hit.path) in {"runtime_lib", "runtime_hooks"}),
            "docs_hits": sum(1 for hit in hits if _surface_group(hit.path) == "docs"),
            "tests_hits": sum(1 for hit in hits if _surface_group(hit.path) == "tests"),
        },
        "by_surface": dict(sorted(by_group.items(), key=lambda kv: kv[0])),
        "by_token": dict(sorted(by_token.items(), key=lambda kv: kv[0])),
        "details": details,
    }


def _render_markdown(report: Dict[str, object]) -> str:
    totals = report.get("totals") or {}
    details = list(report.get("details") or [])
    lines = [
        "# Memory JSON Consumer Audit",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- total_hits: `{totals.get('hits', 0)}`",
        f"- runtime_hits: `{totals.get('runtime_hits', 0)}`",
        f"- docs_hits: `{totals.get('docs_hits', 0)}`",
        f"- tests_hits: `{totals.get('tests_hits', 0)}`",
        "",
        "## By Surface",
        "",
        "| Surface | Hits |",
        "|---|---:|",
    ]
    for surface, count in dict(report.get("by_surface") or {}).items():
        lines.append(f"| {surface} | {count} |")
    lines.extend(
        [
            "",
            "## By Token",
            "",
            "| Token | Hits |",
            "|---|---:|",
        ]
    )
    for token, count in dict(report.get("by_token") or {}).items():
        lines.append(f"| `{token}` | {count} |")
    lines.extend(
        [
            "",
            "## Detailed Hits",
            "",
            "| Path | Line | Token | Surface |",
            "|---|---:|---|---|",
        ]
    )
    for row in details[:400]:
        lines.append(
            f"| `{row.get('path')}` | {row.get('line')} | `{row.get('token')}` | {row.get('surface')} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit direct JSON memory consumers.")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Directory for JSON/Markdown report.")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    hits = _scan_hits(ROOT, TOKENS)
    report = _build_report(hits)
    run_id = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    json_path = out_dir / f"memory_json_consumer_audit_{run_id}.json"
    md_path = out_dir / f"memory_json_consumer_audit_{run_id}.md"
    latest_json = out_dir / "memory_json_consumer_audit_latest.json"
    latest_md = out_dir / "memory_json_consumer_audit_latest.md"

    payload = json.dumps(report, indent=2, ensure_ascii=True)
    json_path.write_text(payload, encoding="utf-8")
    latest_json.write_text(payload, encoding="utf-8")
    rendered_md = _render_markdown(report)
    md_path.write_text(rendered_md, encoding="utf-8")
    latest_md.write_text(rendered_md, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "hits": int((report.get("totals") or {}).get("hits", 0)),
                "runtime_hits": int((report.get("totals") or {}).get("runtime_hits", 0)),
                "report_json": str(json_path),
                "report_md": str(md_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

