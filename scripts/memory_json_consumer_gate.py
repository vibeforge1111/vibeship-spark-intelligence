#!/usr/bin/env python3
"""Gate retirement of JSON memory consumers using audit streak evidence."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

from lib.jsonl_utils import append_jsonl_capped


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_PATH = ROOT / "benchmarks" / "out" / "memory_spine_audit" / "memory_json_consumer_audit_latest.json"
DEFAULT_LEDGER_PATH = Path.home() / ".spark" / "memory_json_consumer_gate_ledger.jsonl"
LEDGER_MAX = 2000


def _load_audit_report(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


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


def _evaluate_gate(
    report: Dict[str, Any],
    *,
    max_runtime_hits: int,
    max_total_hits: int,
) -> Dict[str, Any]:
    totals = dict(report.get("totals") or {})
    runtime_hits = int(totals.get("runtime_hits", 0) or 0)
    total_hits = int(totals.get("hits", 0) or 0)
    pass_runtime = runtime_hits <= int(max_runtime_hits)
    pass_total = total_hits <= int(max_total_hits)
    return {
        "pass": bool(pass_runtime and pass_total),
        "runtime_hits": runtime_hits,
        "total_hits": total_hits,
        "max_runtime_hits": int(max_runtime_hits),
        "max_total_hits": int(max_total_hits),
        "pass_runtime": bool(pass_runtime),
        "pass_total": bool(pass_total),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT_PATH, help="Path to audit JSON report.")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH, help="Gate ledger path.")
    parser.add_argument("--max-runtime-hits", type=int, default=0, help="Max allowed runtime JSON consumer hits.")
    parser.add_argument("--max-total-hits", type=int, default=200, help="Max allowed total JSON consumer hits.")
    parser.add_argument("--required-streak", type=int, default=3, help="Required consecutive pass streak.")
    parser.add_argument("--out", type=Path, default=None, help="Optional output JSON path.")
    parser.add_argument("--enforce", action="store_true", help="Exit non-zero when streak is below requirement.")
    args = parser.parse_args()

    report = _load_audit_report(args.audit)
    gate = _evaluate_gate(
        report,
        max_runtime_hits=max(0, int(args.max_runtime_hits)),
        max_total_hits=max(0, int(args.max_total_hits)),
    )

    ledger_row = {
        "ts": time.time(),
        "audit_path": str(args.audit),
        "pass": bool(gate.get("pass")),
        "runtime_hits": int(gate.get("runtime_hits", 0) or 0),
        "total_hits": int(gate.get("total_hits", 0) or 0),
        "max_runtime_hits": int(gate.get("max_runtime_hits", 0) or 0),
        "max_total_hits": int(gate.get("max_total_hits", 0) or 0),
    }
    append_jsonl_capped(args.ledger, ledger_row, LEDGER_MAX, ensure_ascii=True)
    streak = _latest_streak(args.ledger)
    ready = streak >= max(1, int(args.required_streak))

    out = {
        "ok": True,
        "gate": gate,
        "streak": streak,
        "required_streak": int(args.required_streak),
        "ready_for_runtime_json_retirement": bool(ready),
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

