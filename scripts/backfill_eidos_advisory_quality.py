#!/usr/bin/env python3
"""Backfill advisory_quality on existing EIDOS distillations.

Runs the refinement loop (elevate → rewrite → re-score) on every active
distillation missing advisory_quality, then persists the best refined text
and quality scores so they can rank properly in advisory emissions.

Usage:
    python scripts/backfill_eidos_advisory_quality.py [--dry-run] [--min-score 0.60]
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill EIDOS advisory quality scores")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without writing")
    parser.add_argument("--min-score", type=float, default=0.60, help="Min unified_score target for refinement (default: 0.60)")
    args = parser.parse_args()

    from lib.eidos.store import EidosStore

    store = EidosStore()

    if args.dry_run:
        # Just show current state
        import sqlite3
        with sqlite3.connect(store.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM distillations").fetchall()
            total = len(rows)
            missing = 0
            for row in rows:
                raw = row["advisory_quality"] if "advisory_quality" in row.keys() else None
                has = False
                if isinstance(raw, str) and raw.strip():
                    try:
                        parsed = json.loads(raw)
                        has = isinstance(parsed, dict) and "unified_score" in parsed
                    except Exception:
                        pass
                if not has:
                    missing += 1
                    stmt = (row["statement"] or "")[:80]
                    print(f"  MISSING: [{row['type']}] {stmt}...")

        print(f"\nDry run: {missing}/{total} distillations need backfill")
        return

    print("Running advisory quality backfill...")
    result = store.backfill_advisory_quality(min_unified_score=args.min_score)

    print(f"\nResults:")
    print(f"  Total distillations: {result['total']}")
    print(f"  Updated:            {result['updated']}")
    print(f"  Already had quality: {result['already_has']}")
    print(f"  Skipped (empty):    {result['skipped']}")
    print(f"  Errors:             {result['errors']}")

    # Show details
    if result.get("details"):
        print(f"\nDetails:")
        suppressed_count = 0
        refined_count = 0
        scores = []
        for d in result["details"]:
            if "error" in d:
                print(f"  ERROR {d['id']}: {d['error']}")
                continue
            score = d.get("unified_score", 0)
            scores.append(score)
            if d.get("suppressed"):
                suppressed_count += 1
            if d.get("refined"):
                refined_count += 1
            status = "SUPPRESSED" if d.get("suppressed") else f"score={score:.3f}"
            refined_tag = " [REFINED]" if d.get("refined") else ""
            print(f"  {d['id'][:12]}... [{d['type']}] {status}{refined_tag}")

        if scores:
            avg = sum(scores) / len(scores)
            print(f"\n  Avg unified_score: {avg:.3f}")
            print(f"  Refined (improved): {refined_count}/{len(scores)}")
            print(f"  Suppressed: {suppressed_count}/{len(scores)}")


if __name__ == "__main__":
    main()
