#!/usr/bin/env python3
"""Analyze Observatory reports with Claude and refresh Report Center links."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Run Claude analysis over Observatory report sources."
    )
    ap.add_argument(
        "--obs-dir",
        default="",
        help="Override observatory directory. Defaults to <vault>/_observatory.",
    )
    ap.add_argument(
        "--max-reports",
        type=int,
        default=20,
        help="Maximum number of reports to analyze when --report is not specified.",
    )
    ap.add_argument(
        "--report",
        action="append",
        default=[],
        help="Specific report path (relative to repo or absolute). Repeat for multiple.",
    )
    ap.add_argument(
        "--timeout-s",
        type=int,
        default=180,
        help="Per-report Claude timeout in seconds.",
    )
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-run analysis even when a report already has an analysis page.",
    )
    ap.add_argument(
        "--no-refresh-center",
        action="store_true",
        help="Skip regenerating report_center.md after analysis.",
    )
    return ap


def main() -> int:
    args = _build_parser().parse_args()

    from lib.observatory.config import load_config
    from lib.observatory.report_center import (
        analyze_reports_with_claude,
        generate_report_center,
    )

    cfg = load_config()
    if args.obs_dir:
        obs_dir = Path(args.obs_dir).expanduser()
    else:
        obs_dir = Path(cfg.vault_dir).expanduser() / "_observatory"

    result = analyze_reports_with_claude(
        obs_dir=obs_dir,
        max_reports=max(1, int(args.max_reports)),
        timeout_s=max(30, int(args.timeout_s)),
        overwrite=bool(args.overwrite),
        report_paths=[str(x) for x in (args.report or [])] or None,
    )

    report_center = {}
    if not bool(args.no_refresh_center):
        report_center = generate_report_center(obs_dir=obs_dir)

    payload = {
        "analysis": result,
        "report_center": report_center,
        "observatory_dir": str(obs_dir),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if bool(result.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
