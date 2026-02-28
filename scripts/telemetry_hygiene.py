#!/usr/bin/env python3
"""Cap high-volume telemetry JSONL files to bounded line counts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

from lib.jsonl_utils import cap_jsonl_file


def _default_targets() -> List[Tuple[Path, int]]:
    sd = Path.home() / ".spark"
    return [
        (sd / "noise_classifier_shadow.jsonl", 10000),
        (sd / "logs" / "codex_hook_bridge_telemetry.jsonl", 10000),
        (sd / "advisory_engine_alpha.jsonl", 20000),
        (sd / "advisory_emit.jsonl", 20000),
    ]


def run_hygiene(targets: List[Tuple[Path, int]]) -> Dict[str, object]:
    rows: List[Dict[str, object]] = []
    total_dropped = 0
    for path, cap in targets:
        existed = path.exists()
        before_size = int(path.stat().st_size) if existed else 0
        dropped = cap_jsonl_file(path, int(cap))
        after_exists = path.exists()
        after_size = int(path.stat().st_size) if after_exists else 0
        rows.append(
            {
                "path": str(path),
                "cap_lines": int(cap),
                "existed": bool(existed),
                "dropped_lines": int(dropped),
                "before_size_bytes": int(before_size),
                "after_size_bytes": int(after_size),
            }
        )
        total_dropped += int(dropped)
    return {
        "ok": True,
        "total_dropped_lines": int(total_dropped),
        "targets": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Cap Spark telemetry JSONL files.")
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    payload = run_hygiene(_default_targets())
    if args.json_only:
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
