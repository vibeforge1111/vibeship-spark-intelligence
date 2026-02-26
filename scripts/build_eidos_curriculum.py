"""Generate an EIDOS distillation learning curriculum from eidos.db."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.eidos_distillation_curriculum import build_curriculum, render_curriculum_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="Build EIDOS distillation curriculum cards.")
    parser.add_argument("--db", type=str, default="", help="Path to eidos.db (default: ~/.spark/eidos.db)")
    parser.add_argument("--max-rows", type=int, default=300, help="Max rows to scan from distillations")
    parser.add_argument("--max-cards", type=int, default=200, help="Max output cards")
    parser.add_argument("--no-archive", action="store_true", help="Do not include distillations_archive")
    parser.add_argument("--json-out", type=str, default="", help="Write JSON report to this path")
    parser.add_argument("--md-out", type=str, default="", help="Write markdown report to this path")
    args = parser.parse_args()

    report = build_curriculum(
        db_path=Path(args.db) if args.db else None,
        max_rows=max(1, int(args.max_rows)),
        max_cards=max(1, int(args.max_cards)),
        include_archive=not bool(args.no_archive),
    )

    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    markdown = render_curriculum_markdown(report, max_cards=min(40, max(1, int(args.max_cards))))
    if args.md_out:
        path = Path(args.md_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")

    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

