"""Clean noise promotions from CLAUDE.md files.

Runs the keepability gate on each promoted item in CLAUDE.md.
Items that fail the gate are removed from the markdown.
Creates backup before modifying.

Usage:
    python scripts/cleanup_claude_md_promotions.py          # dry run
    python scripts/cleanup_claude_md_promotions.py --apply  # actually clean
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

_repo = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo))

from lib.keepability_gate import evaluate_structural_keepability

# CLAUDE.md files to clean
CLAUDE_MD_FILES = [
    _repo / "CLAUDE.md",
    Path.home() / "CLAUDE.md",
]
BACKUP_DIR = Path.home() / ".spark" / "backups"


def _is_section_header(line: str) -> bool:
    return line.startswith("## ") or line.startswith("# ")


def _clean_file(path: Path, dry_run: bool = True) -> dict:
    """Clean a single CLAUDE.md file."""
    if not path.exists():
        print(f"  Skipping {path} (not found)")
        return {"skipped": True}

    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")

    keep_lines: list[str] = []
    removed: list[str] = []
    kept: list[str] = []
    in_spark_section = False

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Track Spark sections (where promoted items live)
        if stripped in (
            "## Spark Learnings",
            "## Spark Bootstrap",
            "## Promoted Learnings (Docs)",
            "## Mind Memory",
            "## Outcome Check-in",
        ):
            in_spark_section = True
            keep_lines.append(line)
            i += 1
            continue

        if _is_section_header(stripped) and in_spark_section:
            in_spark_section = False

        # Only filter bullet items in Spark sections
        if in_spark_section and stripped.startswith("- "):
            item_text = stripped[2:]
            # Gather continuation lines (indented, non-bullet)
            j = i + 1
            while j < len(lines):
                next_s = lines[j].strip()
                if next_s.startswith("- ") or _is_section_header(next_s) or next_s == "":
                    break
                item_text += " " + next_s
                j += 1

            gate = evaluate_structural_keepability(item_text[:400])
            if gate["passed"]:
                # Add back the original lines
                for k in range(i, j):
                    keep_lines.append(lines[k])
                kept.append(item_text[:120])
            else:
                removed.append(
                    f"{item_text[:100]} -> {', '.join(gate.get('reasons', []))}"
                )
                # Skip all lines of this item (don't add to keep_lines)

            i = j
            continue

        keep_lines.append(line)
        i += 1

    stats = {
        "file": str(path),
        "total_bullets": len(kept) + len(removed),
        "kept": len(kept),
        "removed": len(removed),
        "removed_items": removed,
        "kept_items": kept,
    }

    if dry_run:
        print(f"\n  DRY RUN for {path.name}:")
        print(f"    Bullets: {len(kept) + len(removed)}")
        print(f"    Keep:    {len(kept)}")
        print(f"    Remove:  {len(removed)}")
        for r in removed:
            print(f"      DROP: {r}")
        for k in kept:
            print(f"      KEEP: {k}")
        return stats

    # Backup
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"{path.name}_{int(time.time())}.md"
    backup.write_text(text, encoding="utf-8")
    print(f"  Backup: {backup}")

    # Write cleaned
    new_text = "\n".join(keep_lines)
    path.write_text(new_text, encoding="utf-8")
    print(f"  Cleaned: {path}")
    print(f"    {len(kept) + len(removed)} -> {len(kept)} items ({len(removed)} removed)")
    return stats


def cleanup(dry_run: bool = True) -> list[dict]:
    results = []
    for path in CLAUDE_MD_FILES:
        print(f"\nProcessing: {path}")
        results.append(_clean_file(path, dry_run=dry_run))

    if dry_run:
        print("\nRe-run with --apply to execute.")
    return results


if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    cleanup(dry_run=dry_run)
