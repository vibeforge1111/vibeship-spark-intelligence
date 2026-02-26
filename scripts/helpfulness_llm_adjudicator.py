#!/usr/bin/env python3
"""Adjudicate ambiguous helpfulness events with an LLM.

Consumes: ~/.spark/advisor/helpfulness_llm_queue.jsonl
Writes:   ~/.spark/advisor/helpfulness_llm_reviews.jsonl
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

from lib.helpfulness_llm_adjudicator import run_helpfulness_llm_adjudicator_default


def _print_result(result: dict) -> None:
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "queue_rows": result.get("queue_rows", 0),
                "processed": result.get("processed", 0),
                "reviewed_now": result.get("reviewed_now", 0),
                "skipped_existing": result.get("skipped_existing", 0),
                "skipped_scope": result.get("skipped_scope", 0),
                "total_reviews": result.get("total_reviews", 0),
                "by_status": result.get("by_status", {}),
                "by_label": result.get("by_label", {}),
                "paths": result.get("paths", {}),
            },
            ensure_ascii=False,
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Run LLM adjudication for advisory helpfulness queue.")
    ap.add_argument("--spark-dir", default="", help="Override ~/.spark root directory")
    ap.add_argument("--provider", default="auto", help="auto|minimax|kimi|qwen")
    ap.add_argument("--scope", default="all", help="all|architecture")
    ap.add_argument("--max-events", type=int, default=120, help="Max queue rows to adjudicate this run")
    ap.add_argument("--max-queue-rows", type=int, default=2000, help="Tail size for LLM queue file")
    ap.add_argument("--max-reviews-rows", type=int, default=20000, help="Tail size for existing reviews")
    ap.add_argument("--timeout-s", type=float, default=16.0, help="Per-request timeout seconds")
    ap.add_argument("--temperature", type=float, default=0.0, help="LLM temperature")
    ap.add_argument("--max-output-tokens", type=int, default=220, help="Max response tokens")
    ap.add_argument("--min-review-confidence", type=float, default=0.65, help="Persisted confidence threshold hint")
    ap.add_argument("--force", action="store_true", help="Re-review even if event already has an ok/abstain review")
    ap.add_argument("--dry-run", action="store_true", help="Do not write review file")
    ap.add_argument("--loop", action="store_true", help="Run continuously")
    ap.add_argument("--interval-s", type=int, default=120, help="Loop interval in seconds")
    args = ap.parse_args()

    spark_dir = Path(args.spark_dir).expanduser() if args.spark_dir else None

    def _run_once() -> dict:
        return run_helpfulness_llm_adjudicator_default(
            spark_dir=spark_dir,
            provider=str(args.provider or "auto").strip().lower(),
            scope=str(args.scope or "all").strip().lower(),
            timeout_s=max(3.0, float(args.timeout_s)),
            temperature=max(0.0, min(1.0, float(args.temperature))),
            max_output_tokens=max(80, int(args.max_output_tokens)),
            min_review_confidence=max(0.0, min(1.0, float(args.min_review_confidence))),
            max_queue_rows=max(1, int(args.max_queue_rows)),
            max_reviews_rows=max(1, int(args.max_reviews_rows)),
            max_events=max(1, int(args.max_events)),
            force=bool(args.force),
            write_files=not bool(args.dry_run),
        )

    if args.loop:
        while True:
            out = _run_once()
            _print_result(out)
            time.sleep(max(10, int(args.interval_s)))
    else:
        out = _run_once()
        _print_result(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

