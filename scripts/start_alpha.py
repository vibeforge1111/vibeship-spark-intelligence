#!/usr/bin/env python3
"""Archive all legacy ~/.spark/ data and start a fresh pre-alpha era.

Moves all data files into ~/.spark/archive/legacy_YYYYMMDD/.
Preserves config (tuneables.json, *.yaml chip definitions).
Recreates empty directory structure for clean boot.
Writes ~/.spark/era.json as the pre-alpha era marker.

Usage:
    python scripts/start_alpha.py          # interactive (confirms before archiving)
    python scripts/start_alpha.py --yes    # skip confirmation
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

SPARK_DIR = Path.home() / ".spark"

# Files to KEEP in place (config, not data)
KEEP_FILES = {"tuneables.json"}

# File extensions that are config (not data) — keep .yaml chip definitions
KEEP_EXTENSIONS = {".yaml", ".yml"}

# Directories that are purely data and should be moved wholesale
DATA_DIRS = [
    "queue", "advisor", "meta_ralph", "chip_insights", "logs",
    "advisory_state", "advisory_quarantine", "advice_packets",
    "orchestration", "banks", "convo_iq", "engagement_pulse",
    "niche_intel", "opportunity_scanner", "projects", "semantic",
    "taste", "x_voice",
]

# Directories to recreate empty after archiving
RECREATE_DIRS = [
    "queue", "advisor", "meta_ralph", "chip_insights", "logs",
]


def main() -> None:
    if not SPARK_DIR.exists():
        print(f"No {SPARK_DIR} directory found. Nothing to archive.")
        return

    today = datetime.now().strftime("%Y%m%d")
    archive_dir = SPARK_DIR / "archive" / f"legacy_{today}"

    if archive_dir.exists():
        print(f"Archive already exists: {archive_dir}")
        print("Delete it first or pick a different name.")
        sys.exit(1)

    # Dry-run: count what we'll move
    files_to_move: list[Path] = []
    dirs_to_move: list[Path] = []
    total_bytes = 0

    # Collect data directories
    for dirname in DATA_DIRS:
        d = SPARK_DIR / dirname
        if d.exists() and d.is_dir():
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            dirs_to_move.append(d)
            total_bytes += size

    # Collect data files in root ~/.spark/
    for p in SPARK_DIR.iterdir():
        if p.is_dir():
            continue  # handled above or skip unknown dirs
        if p.name in KEEP_FILES:
            continue
        if p.name == "era.json":
            continue  # don't archive previous era marker
        if p.suffix in KEEP_EXTENSIONS:
            continue
        files_to_move.append(p)
        total_bytes += p.stat().st_size

    mb = total_bytes / (1024 * 1024)
    print(f"=== Pre-Alpha Era Archive ===")
    print(f"Archive target:  {archive_dir}")
    print(f"Directories:     {len(dirs_to_move)}")
    print(f"Root files:      {len(files_to_move)}")
    print(f"Total size:      {mb:.1f} MB")
    print()

    if "--yes" not in sys.argv:
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    # Create archive directory
    archive_dir.mkdir(parents=True, exist_ok=True)

    moved_count = 0
    moved_bytes = 0

    # Move data directories
    for d in dirs_to_move:
        dest = archive_dir / d.name
        try:
            shutil.move(str(d), str(dest))
            moved_count += 1
            print(f"  moved dir:  {d.name}/")
        except Exception as e:
            print(f"  WARN: could not move {d.name}/: {e}")
            # Fallback: copy then delete
            try:
                shutil.copytree(str(d), str(dest))
                shutil.rmtree(str(d))
                moved_count += 1
                print(f"  copied+deleted dir: {d.name}/")
            except Exception as e2:
                print(f"  ERROR: failed to archive {d.name}/: {e2}")

    # Move root data files
    for f in files_to_move:
        dest = archive_dir / f.name
        try:
            size = f.stat().st_size
            shutil.move(str(f), str(dest))
            moved_count += 1
            moved_bytes += size
            print(f"  moved file: {f.name} ({size:,} bytes)")
        except Exception as e:
            print(f"  WARN: could not move {f.name}: {e}")

    # Recreate empty directories
    for dirname in RECREATE_DIRS:
        d = SPARK_DIR / dirname
        d.mkdir(parents=True, exist_ok=True)

    # Write era marker
    era = {
        "current": "pre-alpha",
        "started_at": datetime.now().isoformat(),
        "started_ts": datetime.now().timestamp(),
        "legacy_archive": str(archive_dir.relative_to(SPARK_DIR)),
        "description": "Pre-alpha fresh start after Intelligence Flow Evolution (PR #95)",
    }
    era_path = SPARK_DIR / "era.json"
    era_path.write_text(json.dumps(era, indent=2), encoding="utf-8")

    print()
    print(f"=== Pre-Alpha Era Started ===")
    print(f"Archived:     {moved_count} items -> {archive_dir}")
    print(f"Era marker:   {era_path}")
    print(f"Config kept:  {', '.join(KEEP_FILES)}")
    print(f"Dirs created: {', '.join(RECREATE_DIRS)}")
    print()
    print("Pre-alpha is live. New data will accumulate in ~/.spark/ from here.")


if __name__ == "__main__":
    main()
