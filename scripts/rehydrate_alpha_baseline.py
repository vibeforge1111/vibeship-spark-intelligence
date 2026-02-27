#!/usr/bin/env python3
"""Rehydrate core Spark baseline data from archived ~/.spark snapshots.

Default mode is dry-run. Use --apply to perform copies.
Only missing/empty targets are restored unless --force is set.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

SPARK_DIR = Path.home() / ".spark"
ARCHIVE_DIR = SPARK_DIR / "archive"
REPORTS_DIR = Path("docs") / "reports"


@dataclass(frozen=True)
class TargetSpec:
    relpath: str
    kind: str


TARGET_SPECS: List[TargetSpec] = [
    TargetSpec("memory_store.sqlite", "sqlite_memory_db"),
    TargetSpec("cognitive_insights.json", "json_container"),
    TargetSpec("advisory_decision_ledger.jsonl", "jsonl"),
    TargetSpec("advisory_engine_alpha.jsonl", "jsonl"),
    TargetSpec("advisory_engine.jsonl", "jsonl"),
    TargetSpec("advisor/effectiveness.json", "effectiveness"),
    TargetSpec("logs/semantic_retrieval.jsonl", "jsonl"),
]


def _count_jsonl_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
    except Exception:
        return 0


def _is_nonempty_sqlite_memory_db(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with sqlite3.connect(path) as con:
            rows = con.execute(
                "select count(*) from sqlite_master where type='table' and name='memories'"
            ).fetchone()
            if not rows or int(rows[0]) <= 0:
                return False
            count = con.execute("select count(*) from memories").fetchone()
            return bool(count and int(count[0]) > 0)
    except Exception:
        return False


def _is_nonempty_json_container(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return False
    if isinstance(obj, dict):
        return len(obj) > 0
    if isinstance(obj, list):
        return len(obj) > 0
    return False


def _is_nonempty_effectiveness(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    try:
        total = int(obj.get("total_advice_given", 0) or 0)
    except Exception:
        total = 0
    return total > 0


def is_nonempty(path: Path, kind: str) -> bool:
    if kind == "sqlite_memory_db":
        return _is_nonempty_sqlite_memory_db(path)
    if kind == "json_container":
        return _is_nonempty_json_container(path)
    if kind == "effectiveness":
        return _is_nonempty_effectiveness(path)
    if kind == "jsonl":
        return _count_jsonl_rows(path) > 0
    return path.exists() and path.stat().st_size > 0


def discover_archive_candidates(archive_root: Path, max_candidates: int = 12) -> List[Path]:
    if not archive_root.exists():
        return []
    candidates = [p for p in archive_root.iterdir() if p.is_dir()]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[: max(1, int(max_candidates))]


def plan_rehydrate(
    *,
    spark_dir: Path,
    archive_root: Path,
    force: bool = False,
    max_candidates: int = 12,
) -> Dict[str, Any]:
    candidates = discover_archive_candidates(archive_root, max_candidates=max_candidates)
    actions: List[Dict[str, Any]] = []

    for spec in TARGET_SPECS:
        target_path = spark_dir / spec.relpath
        target_nonempty = is_nonempty(target_path, spec.kind)
        if target_nonempty and not force:
            continue

        source_path: Path | None = None
        for candidate in candidates:
            probe = candidate / spec.relpath
            if is_nonempty(probe, spec.kind):
                source_path = probe
                break

        if source_path is None:
            continue

        actions.append(
            {
                "relpath": spec.relpath,
                "kind": spec.kind,
                "target": str(target_path),
                "source": str(source_path),
                "target_nonempty": target_nonempty,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spark_dir": str(spark_dir),
        "archive_root": str(archive_root),
        "candidate_count": len(candidates),
        "actions": actions,
    }


def apply_rehydrate_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    applied: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for action in plan.get("actions", []):
        source = Path(str(action.get("source")))
        target = Path(str(action.get("target")))
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            applied.append(action)
        except Exception as exc:
            skipped.append({**action, "error": f"{exc.__class__.__name__}: {exc}"})

    return {"applied": applied, "skipped": skipped}


def write_report(plan: Dict[str, Any], result: Dict[str, Any], *, applied_mode: bool) -> Dict[str, str]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    stem = f"{day}_baseline_rehydrate"
    json_path = REPORTS_DIR / f"{stem}.json"
    md_path = REPORTS_DIR / f"{stem}.md"

    payload = dict(plan)
    payload["mode"] = "apply" if applied_mode else "dry_run"
    payload["result"] = result
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Baseline Rehydrate Report",
        "",
        f"- Generated: {plan.get('generated_at')}",
        f"- Mode: {'APPLY' if applied_mode else 'DRY-RUN'}",
        f"- Archive candidates scanned: {plan.get('candidate_count', 0)}",
        f"- Planned actions: {len(plan.get('actions', []))}",
        f"- Applied: {len(result.get('applied', []))}",
        f"- Skipped/errors: {len(result.get('skipped', []))}",
        "",
        "## Planned Restores",
    ]

    actions = plan.get("actions", [])
    if not actions:
        lines.append("- None")
    else:
        for action in actions:
            lines.append(
                f"- `{action.get('relpath')}` <= `{action.get('source')}`"
            )

    if result.get("skipped"):
        lines.extend(["", "## Errors"])
        for item in result.get("skipped", []):
            lines.append(
                f"- `{item.get('relpath')}`: {item.get('error', 'unknown error')}"
            )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Rehydrate core baseline data from ~/.spark/archive.")
    parser.add_argument("--apply", action="store_true", help="Apply planned restores (default is dry-run).")
    parser.add_argument("--force", action="store_true", help="Allow overwrite even when target is non-empty.")
    parser.add_argument("--archive-root", default=str(ARCHIVE_DIR))
    parser.add_argument("--max-candidates", type=int, default=12)
    args = parser.parse_args()

    archive_root = Path(args.archive_root).expanduser()
    plan = plan_rehydrate(
        spark_dir=SPARK_DIR,
        archive_root=archive_root,
        force=bool(args.force),
        max_candidates=int(args.max_candidates),
    )

    if args.apply:
        result = apply_rehydrate_plan(plan)
    else:
        result = {"applied": [], "skipped": []}

    paths = write_report(plan, result, applied_mode=bool(args.apply))
    out = {
        "mode": "apply" if args.apply else "dry_run",
        "planned_actions": len(plan.get("actions", [])),
        "applied": len(result.get("applied", [])),
        "skipped": len(result.get("skipped", [])),
        "report_paths": paths,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
