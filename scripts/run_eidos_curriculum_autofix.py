#!/usr/bin/env python3
"""Run curriculum-driven EIDOS distillation auto-refinement."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.eidos_curriculum_autofix import run_curriculum_autofix


def main() -> int:
    parser = argparse.ArgumentParser(description="Run EIDOS curriculum auto-refinement worker.")
    parser.add_argument("--db", default="", help="Path to eidos.db (default: ~/.spark/eidos.db)")
    parser.add_argument("--max-cards", type=int, default=5, help="Max top curriculum cards to attempt")
    parser.add_argument("--min-gain", type=float, default=0.03, help="Min unified-score gain required")
    parser.add_argument("--apply", action="store_true", help="Write updates to eidos.db (default: dry-run)")
    parser.add_argument("--include-archive", action="store_true", help="Include archive cards from distillations_archive")
    parser.add_argument("--promote-on-success", action="store_true", help="Promote improved archive rows into distillations")
    parser.add_argument(
        "--promote-min-unified",
        type=float,
        default=0.60,
        help="Minimum unified score required for archive promotion",
    )
    parser.add_argument(
        "--archive-fallback-llm",
        dest="archive_fallback_llm",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable second-pass fallback refinement for archive rows",
    )
    parser.add_argument(
        "--soft-promote-on-success",
        action="store_true",
        help="Tag improved archive rows as soft-promoted when they pass the soft gate",
    )
    parser.add_argument(
        "--soft-promote-min-unified",
        type=float,
        default=0.35,
        help="Minimum unified score for soft promotion",
    )
    parser.add_argument("--json-out", default="", help="Optional path to write full JSON report")
    args = parser.parse_args()

    report = run_curriculum_autofix(
        db_path=Path(args.db) if args.db else None,
        max_cards=max(1, int(args.max_cards)),
        min_gain=float(args.min_gain),
        apply=bool(args.apply),
        include_archive=bool(args.include_archive),
        promote_on_success=bool(args.promote_on_success),
        promote_min_unified=float(args.promote_min_unified),
        archive_fallback_llm=bool(args.archive_fallback_llm),
        soft_promote_on_success=bool(args.soft_promote_on_success),
        soft_promote_min_unified=float(args.soft_promote_min_unified),
    )

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
