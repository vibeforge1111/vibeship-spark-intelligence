#!/usr/bin/env python3
"""Generate emission-native advisory quality metrics.

Creates:
- ~/.spark/advisor/advisory_quality_events.jsonl
- ~/.spark/advisor/advisory_quality_summary.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.advisory_quality_spine import run_advisory_quality_spine_default


def main() -> int:
    ap = argparse.ArgumentParser(description="Build advisory quality spine from emitted advisories.")
    ap.add_argument("--spark-dir", default=str(Path.home() / ".spark"))
    ap.add_argument("--max-recent-rows", type=int, default=10000)
    ap.add_argument("--max-alpha-rows", type=int, default=24000)
    ap.add_argument("--max-observe-rows", type=int, default=24000)
    ap.add_argument("--max-implicit-rows", type=int, default=24000)
    ap.add_argument("--max-explicit-rows", type=int, default=24000)
    ap.add_argument("--explicit-window-s", type=int, default=6 * 3600)
    ap.add_argument("--implicit-window-s", type=int, default=90 * 60)
    ap.add_argument("--provider-window-s", type=int, default=180)
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    result = run_advisory_quality_spine_default(
        spark_dir=Path(args.spark_dir).expanduser(),
        max_recent_rows=max(1, int(args.max_recent_rows)),
        max_alpha_rows=max(1, int(args.max_alpha_rows)),
        max_observe_rows=max(1, int(args.max_observe_rows)),
        max_implicit_rows=max(1, int(args.max_implicit_rows)),
        max_explicit_rows=max(1, int(args.max_explicit_rows)),
        explicit_window_s=max(60, int(args.explicit_window_s)),
        implicit_window_s=max(60, int(args.implicit_window_s)),
        provider_window_s=max(10, int(args.provider_window_s)),
        write_files=(not bool(args.dry_run)),
    )

    payload = {
        "ok": result.get("ok", False),
        "paths": result.get("paths", {}),
        "inputs": result.get("inputs", {}),
        "summary": result.get("summary", {}),
    }

    if args.json_only:
        print(json.dumps(payload, indent=2))
        return 0

    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    print("Advisory Quality Spine")
    print(f"total_events={summary.get('total_events', 0)}")
    print(
        "avg_impact_score="
        + str(summary.get("avg_impact_score", 0.0))
        + " helpful_rate_pct="
        + str(summary.get("helpful_rate_pct", 0.0))
        + " right_on_time_rate_pct="
        + str(summary.get("right_on_time_rate_pct", 0.0))
    )
    print("paths=" + json.dumps(payload.get("paths", {})))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
