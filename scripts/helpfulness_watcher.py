#!/usr/bin/env python3
"""Run the advisory helpfulness watcher.

Examples:
  python scripts/helpfulness_watcher.py --once
  python scripts/helpfulness_watcher.py --loop --interval-s 120
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Ensure local repo root is importable when running as `python scripts/...`.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib.helpfulness_watcher import run_helpfulness_watcher_default


def _print_summary(result: dict) -> None:
    summary = result.get("summary") or {}
    labels = summary.get("labels") or {}
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "events": summary.get("total_events", 0),
                "helpful_rate_pct": summary.get("helpful_rate_pct", 0.0),
                "unknown_rate_pct": summary.get("unknown_rate_pct", 0.0),
                "conflict_rate_pct": summary.get("conflict_rate_pct", 0.0),
                "llm_review_queue_count": summary.get("llm_review_queue_count", 0),
                "labels": labels,
                "paths": result.get("paths", {}),
            },
            ensure_ascii=False,
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Build canonical advisory helpfulness events.")
    ap.add_argument("--spark-dir", default="", help="Override ~/.spark root directory")
    ap.add_argument("--once", action="store_true", help="Run once and exit (default behavior)")
    ap.add_argument("--loop", action="store_true", help="Run continuously")
    ap.add_argument("--interval-s", type=int, default=120, help="Loop interval in seconds")
    ap.add_argument("--window-hours", type=float, default=72.0, help="Only process requests from this many recent hours")
    ap.add_argument("--max-request-rows", type=int, default=6000, help="Tail size for advice_feedback_requests.jsonl")
    ap.add_argument("--max-explicit-rows", type=int, default=10000, help="Tail size for advice_feedback.jsonl")
    ap.add_argument("--max-implicit-rows", type=int, default=16000, help="Tail size for implicit_feedback.jsonl")
    ap.add_argument("--max-review-rows", type=int, default=20000, help="Tail size for helpfulness_llm_reviews.jsonl")
    ap.add_argument("--explicit-window-s", type=int, default=21600, help="Max delay for matching explicit feedback")
    ap.add_argument("--implicit-window-s", type=int, default=5400, help="Max delay for matching implicit signals")
    ap.add_argument("--llm-review-threshold", type=float, default=0.75, help="Confidence below this goes to LLM review queue")
    ap.add_argument("--min-applied-review-confidence", type=float, default=0.65, help="Min confidence required to apply an LLM review override")
    ap.add_argument("--dry-run", action="store_true", help="Do not write files")
    args = ap.parse_args()

    spark_dir = Path(args.spark_dir).expanduser() if args.spark_dir else None
    min_created_at = time.time() - max(0.0, float(args.window_hours)) * 3600.0

    def _run_once() -> dict:
        return run_helpfulness_watcher_default(
            spark_dir=spark_dir,
            max_request_rows=max(1, int(args.max_request_rows)),
            max_explicit_rows=max(1, int(args.max_explicit_rows)),
            max_implicit_rows=max(1, int(args.max_implicit_rows)),
            explicit_window_s=max(60, int(args.explicit_window_s)),
            implicit_window_s=max(60, int(args.implicit_window_s)),
            min_created_at=min_created_at,
            llm_review_confidence_threshold=max(0.0, min(1.0, float(args.llm_review_threshold))),
            min_applied_review_confidence=max(0.0, min(1.0, float(args.min_applied_review_confidence))),
            max_review_rows=max(1, int(args.max_review_rows)),
            write_files=not bool(args.dry_run),
        )

    if args.loop:
        while True:
            res = _run_once()
            _print_summary(res)
            time.sleep(max(10, int(args.interval_s)))
    else:
        # Default one-shot behavior, even when --once is omitted.
        res = _run_once()
        _print_summary(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
