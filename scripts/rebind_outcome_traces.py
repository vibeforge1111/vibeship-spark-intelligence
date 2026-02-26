#!/usr/bin/env python3
"""Repair strict trace binding for historical outcome records.

Targets records where retrieval trace exists, outcome trace differs, and the
retrieval->outcome latency is within the strict attribution window.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

SPARK_DIR = Path.home() / ".spark"
OUTCOME_FILE = SPARK_DIR / "meta_ralph" / "outcome_tracking.json"


def _parse_iso_ts(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return None


def _latency_s(row: Dict[str, Any]) -> Optional[float]:
    start = _parse_iso_ts(row.get("retrieved_at"))
    end = _parse_iso_ts(row.get("outcome_at"))
    if start is None or end is None:
        return None
    delta = end - start
    if delta < 0:
        return None
    return float(delta)


def _synthetic_trace_id(row: Dict[str, Any], *, idx: int) -> str:
    seed = "|".join(
        [
            str(row.get("learning_id") or ""),
            str(row.get("insight_key") or ""),
            str(row.get("retrieved_at") or ""),
            str(row.get("outcome_at") or ""),
            str(idx),
        ]
    )
    return f"trace-recovered-{hashlib.sha1(seed.encode('utf-8', errors='ignore')).hexdigest()[:16]}"


def plan_rebind(path: Path = OUTCOME_FILE, *, window_s: int = 1800) -> Dict[str, Any]:
    if not path.exists():
        return {
            "ok": False,
            "reason": "missing_file",
            "path": str(path),
            "total": 0,
            "candidates": 0,
        }

    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"read_error:{type(exc).__name__}",
            "path": str(path),
            "total": 0,
            "candidates": 0,
        }

    rows = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        rows = []

    candidates: List[Dict[str, Any]] = []
    mismatched = 0
    missing_trace = 0
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if not bool(row.get("acted_on")):
            continue
        retrieve_trace = str(row.get("trace_id") or "").strip()
        outcome_trace = str(row.get("outcome_trace_id") or "").strip()
        latency = _latency_s(row)

        if not retrieve_trace and not outcome_trace:
            missing_trace += 1
            if latency is None or latency > float(max(0, int(window_s))):
                continue
            synthetic = _synthetic_trace_id(row, idx=idx)
            candidates.append(
                {
                    "index": idx,
                    "learning_id": str(row.get("learning_id") or ""),
                    "source": str(row.get("source") or ""),
                    "trace_id": synthetic,
                    "outcome_trace_id": synthetic,
                    "latency_s": round(latency, 2),
                    "mode": "recovered_missing_trace",
                }
            )
            continue

        if not (retrieve_trace and outcome_trace):
            continue
        if retrieve_trace == outcome_trace:
            continue
        mismatched += 1

        if latency is None or latency > float(max(0, int(window_s))):
            continue

        candidates.append(
            {
                "index": idx,
                "learning_id": str(row.get("learning_id") or ""),
                "source": str(row.get("source") or ""),
                "trace_id": retrieve_trace,
                "outcome_trace_id": outcome_trace,
                "latency_s": round(latency, 2),
                "mode": "rebind_mismatch",
            }
        )

    return {
        "ok": True,
        "path": str(path),
        "window_s": int(window_s),
        "total": len(rows),
        "mismatched": mismatched,
        "missing_trace": missing_trace,
        "candidates": len(candidates),
        "updates": candidates,
        "payload": payload,
    }


def apply_rebind(plan: Dict[str, Any]) -> Dict[str, Any]:
    if not plan.get("ok"):
        return {"applied": False, "reason": plan.get("reason") or "plan_failed"}
    updates = list(plan.get("updates") or [])
    if not updates:
        return {"applied": False, "reason": "no_updates", "updated": 0}

    path = Path(str(plan.get("path") or OUTCOME_FILE))
    payload = plan.get("payload") if isinstance(plan.get("payload"), dict) else {}
    rows = payload.get("records") if isinstance(payload.get("records"), list) else []

    backup = path.with_suffix(path.suffix + f".bak-{int(time.time())}")
    backup.write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

    updated = 0
    for item in updates:
        raw_idx = item.get("index")
        idx = int(raw_idx) if raw_idx is not None else -1
        if idx < 0 or idx >= len(rows):
            continue
        row = rows[idx]
        if not isinstance(row, dict):
            continue
        old_retrieve_trace = str(row.get("trace_id") or "").strip()
        old_outcome_trace = str(row.get("outcome_trace_id") or "").strip()
        target_trace = str(item.get("trace_id") or "").strip()
        if not target_trace:
            continue
        if not old_retrieve_trace:
            row["trace_id"] = target_trace
        row["outcome_trace_id"] = target_trace
        if (
            old_outcome_trace
            and old_outcome_trace != target_trace
            and not str(row.get("reported_outcome_trace_id") or "").strip()
        ):
            row["reported_outcome_trace_id"] = old_outcome_trace
        updated += 1

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "applied": True,
        "updated": updated,
        "backup": str(backup),
        "path": str(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=str(OUTCOME_FILE), help="Path to outcome_tracking.json")
    parser.add_argument("--window-s", type=int, default=1800, help="Strict attribution window in seconds")
    parser.add_argument("--apply", action="store_true", help="Apply changes in-place")
    parser.add_argument("--show", type=int, default=8, help="Preview first N candidate rows")
    args = parser.parse_args()

    plan = plan_rebind(Path(args.path), window_s=int(args.window_s))
    if not plan.get("ok"):
        print(json.dumps(plan, indent=2))
        return 1

    summary = {
        "path": plan.get("path"),
        "window_s": plan.get("window_s"),
        "total": plan.get("total"),
        "mismatched": plan.get("mismatched"),
        "missing_trace": plan.get("missing_trace"),
        "candidates": plan.get("candidates"),
        "preview": list(plan.get("updates") or [])[: max(0, int(args.show or 0))],
    }

    if args.apply:
        summary["apply"] = apply_rebind(plan)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
