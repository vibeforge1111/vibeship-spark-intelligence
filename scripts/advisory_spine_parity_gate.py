#!/usr/bin/env python3
"""Run advisory spine parity report and track consecutive pass streak."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict

from lib.jsonl_utils import append_jsonl_capped

from lib.advisory_spine_parity import compare_snapshots, evaluate_parity_gate


LEDGER_PATH = Path.home() / ".spark" / "advisory_spine_parity_ledger.jsonl"
LEDGER_MAX = 2000


def _default_index_path() -> Path:
    return Path.home() / ".spark" / "advice_packets" / "index.json"


def _default_db_path() -> Path:
    return Path.home() / ".spark" / "advisory_packet_spine.db"


def _load_index_meta(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    meta = data.get("packet_meta")
    return dict(meta) if isinstance(meta, dict) else {}


def _load_spine_meta(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT packet_id, project_key, session_context_key, tool_name, intent_family, task_plane,
                       invalidated, fresh_until_ts, updated_ts, effectiveness_score,
                       read_count, usage_count, emit_count, deliver_count,
                       source_summary_json, category_summary_json
                FROM packet_meta
                """
            ).fetchall()
    except Exception:
        return {}

    out: Dict[str, Any] = {}
    for row in rows:
        packet_id = str(row["packet_id"] or "").strip()
        if not packet_id:
            continue
        try:
            source_summary = json.loads(str(row["source_summary_json"] or "[]"))
        except Exception:
            source_summary = []
        try:
            category_summary = json.loads(str(row["category_summary_json"] or "[]"))
        except Exception:
            category_summary = []
        out[packet_id] = {
            "project_key": str(row["project_key"] or ""),
            "session_context_key": str(row["session_context_key"] or ""),
            "tool_name": str(row["tool_name"] or ""),
            "intent_family": str(row["intent_family"] or ""),
            "task_plane": str(row["task_plane"] or ""),
            "invalidated": bool(int(row["invalidated"] or 0)),
            "fresh_until_ts": float(row["fresh_until_ts"] or 0.0),
            "updated_ts": float(row["updated_ts"] or 0.0),
            "effectiveness_score": float(row["effectiveness_score"] or 0.5),
            "read_count": int(row["read_count"] or 0),
            "usage_count": int(row["usage_count"] or 0),
            "emit_count": int(row["emit_count"] or 0),
            "deliver_count": int(row["deliver_count"] or 0),
            "source_summary": [str(x) for x in list(source_summary or [])][:20],
            "category_summary": [str(x) for x in list(category_summary or [])][:20],
        }
    return out


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
    parser.add_argument("--index-path", type=Path, default=_default_index_path())
    parser.add_argument("--db-path", type=Path, default=_default_db_path())
    parser.add_argument("--fail-under", type=float, default=0.995)
    parser.add_argument("--min-rows", type=int, default=10)
    parser.add_argument("--required-streak", type=int, default=3)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()

    index_meta = _load_index_meta(args.index_path)
    spine_meta = _load_spine_meta(args.db_path)
    parity = compare_snapshots(index_meta, spine_meta)
    gate = evaluate_parity_gate(
        parity,
        min_payload_parity=float(args.fail_under),
        min_rows=max(0, int(args.min_rows)),
    )

    row: Dict[str, Any] = {
        "ts": time.time(),
        "index_path": str(args.index_path),
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
        "ready_for_index_meta_retirement": bool(ready),
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
