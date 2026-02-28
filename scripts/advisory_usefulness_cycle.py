#!/usr/bin/env python3
"""Run 4-hour advisory usefulness cycle with context-first rating."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.advisory_usefulness_cycle import run_usefulness_cycle


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Run advisory usefulness review/rating cycle.")
    ap.add_argument("--spark-dir", default=str(Path.home() / ".spark"))
    ap.add_argument("--window-hours", type=float, default=4.0)
    ap.add_argument("--max-candidates", type=int, default=80)
    ap.add_argument("--providers", default="auto")
    ap.add_argument("--llm-timeout-s", type=float, default=180.0)
    ap.add_argument("--min-confidence", type=float, default=0.72)
    ap.add_argument("--apply-limit", type=int, default=40)
    ap.add_argument("--source", default="usefulness_cycle")
    ap.add_argument("--no-run-llm", action="store_true")
    return ap


def main() -> int:
    args = _build_parser().parse_args()
    out = run_usefulness_cycle(
        spark_dir=Path(args.spark_dir).expanduser(),
        window_hours=max(0.25, float(args.window_hours)),
        max_candidates=max(1, int(args.max_candidates)),
        run_llm=(not bool(args.no_run_llm)),
        providers=str(args.providers or "auto"),
        llm_timeout_s=max(30.0, float(args.llm_timeout_s)),
        min_confidence=max(0.0, min(1.0, float(args.min_confidence))),
        apply_limit=max(1, int(args.apply_limit)),
        source=str(args.source or "usefulness_cycle"),
    )
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if bool(out.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())

