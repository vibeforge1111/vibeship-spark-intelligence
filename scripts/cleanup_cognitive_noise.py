"""Clean noise items from cognitive insights store.

Removes items that fail the keepability gate.
Creates backup before modifying.

Usage:
    python scripts/cleanup_cognitive_noise.py          # dry run
    python scripts/cleanup_cognitive_noise.py --apply  # actually clean
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_repo = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo))

from lib.keepability_gate import evaluate_structural_keepability

SPARK_HOME = Path.home() / ".spark"
INSIGHTS_FILE = SPARK_HOME / "cognitive_insights.json"
BACKUP_DIR = SPARK_HOME / "backups"


def _extract_text(key: str, entry: dict) -> str:
    for field in ("text", "insight", "content", "summary"):
        val = entry.get(field)
        if val and isinstance(val, str) and len(val) > 5:
            return val
    if len(key) > 10 and not key.startswith("_"):
        return key
    return ""


def cleanup(dry_run: bool = True) -> dict:
    if not INSIGHTS_FILE.exists():
        print(f"No insights file at {INSIGHTS_FILE}")
        return {}

    data = json.loads(INSIGHTS_FILE.read_text(encoding="utf-8-sig"))
    original_count = len(data)

    remove_keys: list[str] = []
    keep_count = 0
    reason_counts: dict[str, int] = {}
    false_wisdom_count = 0

    for key, entry in data.items():
        if not isinstance(entry, dict):
            remove_keys.append(key)
            continue
        text = _extract_text(key, entry)
        if not text:
            remove_keys.append(key)
            reason_counts["empty_text"] = reason_counts.get("empty_text", 0) + 1
            continue

        gate = evaluate_structural_keepability(text)
        if gate["passed"]:
            keep_count += 1
        else:
            remove_keys.append(key)
            validations = entry.get("times_validated", 0)
            reliability = entry.get("reliability", 0.0)
            for r in gate["reasons"]:
                reason_counts[r] = reason_counts.get(r, 0) + 1
            if validations >= 10 or reliability >= 0.8:
                false_wisdom_count += 1
                print(f"  FALSE WISDOM: [{validations:3d}v {reliability:.0%}] {text[:100]}")

    stats = {
        "original": original_count,
        "removing": len(remove_keys),
        "keeping": keep_count,
        "false_wisdom": false_wisdom_count,
        "reasons": dict(sorted(reason_counts.items(), key=lambda x: -x[1])),
    }

    if dry_run:
        print(f"\nDRY RUN — would remove {len(remove_keys)}/{original_count}, keep {keep_count}")
        print(f"  False wisdom purged: {false_wisdom_count}")
        for r, c in stats["reasons"].items():
            print(f"  {r}: {c}")
        print("\nRe-run with --apply to execute.")
        return stats

    # Backup
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"cognitive_insights_{int(time.time())}.json"
    backup.write_text(INSIGHTS_FILE.read_text(encoding="utf-8-sig"), encoding="utf-8")
    print(f"\nBackup: {backup}")

    # Use CognitiveLearner's drop_keys to ensure running processes
    # don't merge the deleted items back from their in-memory state.
    try:
        from lib.cognitive_learner import CognitiveLearner

        cl = CognitiveLearner()
        # Remove from in-memory store
        for key in remove_keys:
            cl.insights.pop(key, None)
        # Save with drop_keys — this does an atomic read-merge-write
        # that also removes the keys from disk data before merging.
        cl._save_insights(drop_keys=set(remove_keys))
        remaining = len(json.loads(INSIGHTS_FILE.read_text(encoding="utf-8")))
        print(f"Cleaned via CognitiveLearner.drop_keys: {INSIGHTS_FILE}")
        print(f"  {original_count} -> {remaining} items ({len(remove_keys)} targeted)")
    except Exception as exc:
        # Fallback: direct file write (may be overwritten by running processes)
        print(f"  CognitiveLearner unavailable ({exc}), using direct write...")
        for key in remove_keys:
            del data[key]
        INSIGHTS_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Cleaned: {INSIGHTS_FILE}")
        print(f"  {original_count} -> {len(data)} items ({len(remove_keys)} removed)")
    return stats


if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    cleanup(dry_run=dry_run)
