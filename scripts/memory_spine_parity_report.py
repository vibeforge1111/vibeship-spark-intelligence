#!/usr/bin/env python3
"""Report parity between cognitive_insights.json and SQLite memory spine snapshot."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict

from lib.memory_spine_parity import compare_snapshots, evaluate_parity_gate


def _default_json_path() -> Path:
    return Path.home() / ".spark" / "cognitive_insights.json"


def _default_db_path() -> Path:
    raw = str(os.getenv("SPARK_MEMORY_SPINE_DB", "")).strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".spark" / "spark_memory_spine.db"


def _load_json_snapshot(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_spine_snapshot(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM cognitive_insights_meta WHERE id = 1"
            ).fetchone()
    except Exception:
        return {}

    if not row:
        return {}

    try:
        data = json.loads(str(row[0] or "{}"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report parity between JSON cognitive insights and SQLite memory spine."
    )
    parser.add_argument("--json-path", type=Path, default=_default_json_path())
    parser.add_argument("--db-path", type=Path, default=_default_db_path())
    parser.add_argument("--fail-under", type=float, default=0.995)
    parser.add_argument("--min-rows", type=int, default=10)
    parser.add_argument("--list-limit", type=int, default=25)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Exit non-zero when parity gate fails.",
    )
    args = parser.parse_args()

    json_snapshot = _load_json_snapshot(args.json_path)
    spine_snapshot = _load_spine_snapshot(args.db_path)

    parity = compare_snapshots(
        json_snapshot,
        spine_snapshot,
        list_limit=max(0, int(args.list_limit)),
    )
    gate = evaluate_parity_gate(
        parity,
        min_payload_parity=float(args.fail_under),
        min_rows=max(0, int(args.min_rows)),
    )

    report = {
        "ok": True,
        "ts": time.time(),
        "json_path": str(args.json_path),
        "db_path": str(args.db_path),
        "parity": parity,
        "gate": gate,
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    if args.enforce and not bool(gate.get("pass")):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
