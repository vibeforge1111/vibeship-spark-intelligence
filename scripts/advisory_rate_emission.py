#!/usr/bin/env python3
"""Strictly rate emitted advisory events by event_id."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.advisory_quality_rating import list_events, rate_event, rate_latest


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Rate emitted advisory quality events.")
    ap.add_argument("--spark-dir", default=str(Path.home() / ".spark"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List recent advisory quality events.")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--provider", default="")
    p_list.add_argument("--tool", default="")

    p_rate = sub.add_parser("rate", help="Rate one advisory emission by event_id.")
    p_rate.add_argument("--event-id", required=True)
    p_rate.add_argument(
        "--label",
        required=True,
        choices=["helpful", "unhelpful", "harmful", "not_followed", "unknown"],
    )
    p_rate.add_argument("--notes", default="")
    p_rate.add_argument("--source", default="quality_rate_cli")
    p_rate.add_argument("--no-count-effectiveness", action="store_true")
    p_rate.add_argument("--no-refresh-spine", action="store_true")

    p_rate_latest = sub.add_parser("rate-latest", help="Rate latest event matching trace/tool/advice filters.")
    p_rate_latest.add_argument("--trace-id", default="")
    p_rate_latest.add_argument("--advice-id", default="")
    p_rate_latest.add_argument("--tool", default="")
    p_rate_latest.add_argument("--provider", default="")
    p_rate_latest.add_argument("--max-scan", type=int, default=2000)
    p_rate_latest.add_argument(
        "--label",
        required=True,
        choices=["helpful", "unhelpful", "harmful", "not_followed", "unknown"],
    )
    p_rate_latest.add_argument("--notes", default="")
    p_rate_latest.add_argument("--source", default="quality_rate_cli")
    p_rate_latest.add_argument("--no-count-effectiveness", action="store_true")
    p_rate_latest.add_argument("--no-refresh-spine", action="store_true")
    return ap


def main() -> int:
    ap = _build_parser()
    args = ap.parse_args()
    spark_dir = Path(args.spark_dir).expanduser()

    if args.cmd == "list":
        rows = list_events(
            spark_dir=spark_dir,
            limit=max(1, int(args.limit)),
            provider=str(args.provider or ""),
            tool=str(args.tool or ""),
        )
        print(json.dumps({"count": len(rows), "events": rows}, indent=2))
        return 0

    if args.cmd == "rate-latest":
        result = rate_latest(
            spark_dir=spark_dir,
            label=str(args.label or "").strip().lower(),
            notes=str(args.notes or ""),
            source=str(args.source or "quality_rate_cli"),
            count_effectiveness=not bool(args.no_count_effectiveness),
            refresh_spine=not bool(args.no_refresh_spine),
            trace_id=str(args.trace_id or ""),
            advice_id=str(args.advice_id or ""),
            tool=str(args.tool or ""),
            provider=str(args.provider or ""),
            max_scan=max(1, int(args.max_scan)),
        )
    else:
        result = rate_event(
            spark_dir=spark_dir,
            event_id=str(args.event_id or "").strip(),
            label=str(args.label or "").strip().lower(),
            notes=str(args.notes or ""),
            source=str(args.source or "quality_rate_cli"),
            count_effectiveness=not bool(args.no_count_effectiveness),
            refresh_spine=not bool(args.no_refresh_spine),
        )
    print(json.dumps(result, indent=2))
    return 0 if bool(result.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
