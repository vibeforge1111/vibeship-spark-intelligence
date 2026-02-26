#!/usr/bin/env python3
"""Run memory spine parity report and track consecutive pass streak."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict

from lib.jsonl_utils import append_jsonl_capped

from lib.memory_spine_parity import compare_snapshots, evaluate_parity_gate


LEDGER_PATH = Path.home() / ".spark" / "memory_spine_parity_ledger.jsonl"
LEDGER_MAX = 2000


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


def _latest_streak(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        return 0
    streak = 0
    for row in reversed(rows):
        if bool((row or {}).get("pass")):
            streak += 1
        else:
            break
    return int(streak)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-path", type=Path, default=_default_json_path())
    parser.add_argument("--db-path", type=Path, default=_default_db_path())
    parser.add_argument("--fail-under", type=float, default=0.995)
    parser.add_argument("--min-rows", type=int, default=10)
    parser.add_argument("--required-streak", type=int, default=3)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()

    json_snapshot = _load_json_snapshot(args.json_path)
    spine_snapshot = _load_spine_snapshot(args.db_path)
    parity = compare_snapshots(json_snapshot, spine_snapshot)
    gate = evaluate_parity_gate(
        parity,
        min_payload_parity=float(args.fail_under),
        min_rows=max(0, int(args.min_rows)),
    )

    row: Dict[str, Any] = {
        "ts": time.time(),
        "json_path": str(args.json_path),
        "db_path": str(args.db_path),
        "pass": bool(gate.get("pass")),
        "payload_parity_ratio": float(gate.get("payload_parity_ratio", 0.0) or 0.0),
        "rows": int(gate.get("rows", 0) or 0),
        "min_payload_parity": float(gate.get("min_payload_parity", args.fail_under)),
        "min_rows": int(gate.get("min_rows", args.min_rows)),
    }
    append_jsonl_capped(args.ledger, row, LEDGER_MAX, ensure_ascii=True)
    streak = _latest_streak(args.ledger)
    ready = streak >= max(1, int(args.required_streak))

    out = {
        "ok": True,
        "gate": gate,
        "streak": streak,
        "required_streak": int(args.required_streak),
        "ready_for_json_retirement": bool(ready),
        "ledger": str(args.ledger),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    if args.enforce and not ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
