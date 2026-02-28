#!/usr/bin/env python3
"""Run provider-specific advisory canary checks from quality spine events."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.advisory_provider_canary import run_provider_canary_default


def _split_csv(text: str) -> list[str]:
    return [x.strip() for x in str(text or "").split(",") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Provider advisory canary checks.")
    ap.add_argument("--spark-dir", default=str(Path.home() / ".spark"))
    ap.add_argument("--providers", default="codex,claude,openclaw")
    ap.add_argument("--window-s", type=int, default=6 * 3600)
    ap.add_argument("--min-events-per-provider", type=int, default=10)
    ap.add_argument("--min-known-helpfulness", type=int, default=3)
    ap.add_argument("--min-helpful-rate-pct", type=float, default=40.0)
    ap.add_argument("--min-right-on-time-rate-pct", type=float, default=35.0)
    ap.add_argument("--max-unknown-rate-pct", type=float, default=90.0)
    ap.add_argument("--no-refresh-spine", action="store_true")
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    payload = run_provider_canary_default(
        spark_dir=Path(args.spark_dir).expanduser(),
        providers=_split_csv(args.providers),
        window_s=max(60, int(args.window_s)),
        min_events_per_provider=max(1, int(args.min_events_per_provider)),
        min_known_helpfulness=max(1, int(args.min_known_helpfulness)),
        min_helpful_rate_pct=max(0.0, float(args.min_helpful_rate_pct)),
        min_right_on_time_rate_pct=max(0.0, float(args.min_right_on_time_rate_pct)),
        max_unknown_rate_pct=max(0.0, min(100.0, float(args.max_unknown_rate_pct))),
        refresh_spine=not bool(args.no_refresh_spine),
    )

    if args.json_only:
        print(json.dumps(payload, indent=2))
        return 0 if bool(payload.get("ready")) else 1

    print("Advisory Provider Canary")
    print(f"ready={bool(payload.get('ready'))}")
    for provider, row in (payload.get("providers") or {}).items():
        status = "PASS" if bool((row or {}).get("passed")) else ("SKIP" if not bool((row or {}).get("active")) else "FAIL")
        print(
            f"{provider}: {status} events={int((row or {}).get('events', 0))} "
            f"known={int((row or {}).get('known_helpfulness', 0))} "
            f"helpful_rate={float((row or {}).get('helpful_rate_pct', 0.0)):.1f}% "
            f"right_on_time={float((row or {}).get('right_on_time_rate_pct', 0.0)):.1f}% "
            f"unknown={float((row or {}).get('unknown_rate_pct', 0.0)):.1f}%"
        )
        reasons = list((row or {}).get("reasons") or [])
        if reasons:
            print("  reasons=" + ", ".join(reasons))
    return 0 if bool(payload.get("ready")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
