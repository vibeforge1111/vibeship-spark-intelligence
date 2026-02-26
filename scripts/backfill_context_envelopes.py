#!/usr/bin/env python3
"""Backfill contextual memory envelopes for cognitive insights."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from lib.context_envelope import DEFAULT_MIN_CONTEXT_CHARS, build_context_envelope

SPARK_DIR = Path.home() / ".spark"
COGNITIVE_FILE = SPARK_DIR / "cognitive_insights.json"


def _iter_items(obj: Any) -> Iterable[Tuple[str, Dict[str, Any]]]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, dict):
                yield str(key), value
        return
    if isinstance(obj, list):
        for idx, value in enumerate(obj):
            if isinstance(value, dict):
                key = str(value.get("key") or f"idx:{idx}")
                yield key, value


def _median_length(rows: Iterable[str]) -> int:
    vals = [len(str(x or "")) for x in rows]
    if not vals:
        return 0
    return int(statistics.median(vals))


def plan_backfill(path: Path = COGNITIVE_FILE) -> Dict[str, Any]:
    if not path.exists():
        return {
            "ok": False,
            "path": str(path),
            "reason": "missing_file",
            "items_total": 0,
            "items_updated": 0,
        }

    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {
            "ok": False,
            "path": str(path),
            "reason": f"read_error:{type(exc).__name__}",
            "items_total": 0,
            "items_updated": 0,
        }

    before_contexts: List[str] = []
    updates: List[Dict[str, Any]] = []

    for key, row in _iter_items(raw):
        before = str(row.get("context") or "")
        before_contexts.append(before)

        enriched = build_context_envelope(
            context=before,
            insight=str(row.get("insight") or ""),
            category=str(row.get("category") or ""),
            source=str(row.get("source") or ""),
            advisory_quality=row.get("advisory_quality") if isinstance(row.get("advisory_quality"), dict) else {},
            min_chars=DEFAULT_MIN_CONTEXT_CHARS,
        )

        if enriched and enriched != before:
            updates.append({"key": key, "context": enriched, "before": before, "after": enriched})

    after_contexts = list(before_contexts)
    if updates:
        by_key = {u["key"]: u["after"] for u in updates}
        after_contexts = [by_key.get(k, v) for (k, _), v in zip(_iter_items(raw), before_contexts)]

    return {
        "ok": True,
        "path": str(path),
        "items_total": len(before_contexts),
        "items_updated": len(updates),
        "context_p50_before": _median_length(before_contexts),
        "context_p50_after": _median_length(after_contexts),
        "min_target": DEFAULT_MIN_CONTEXT_CHARS,
        "updates": updates,
        "raw": raw,
    }


def apply_backfill(plan: Dict[str, Any]) -> Dict[str, Any]:
    if not plan.get("ok"):
        return {"applied": False, "reason": plan.get("reason") or "plan_failed"}
    path = Path(str(plan.get("path") or COGNITIVE_FILE))
    updates = list(plan.get("updates") or [])
    raw = plan.get("raw")

    if not updates:
        return {"applied": False, "reason": "no_updates", "updated": 0}

    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_suffix(path.suffix + f".bak-{int(time.time())}")
    backup.write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

    by_key = {str(u.get("key") or ""): str(u.get("after") or "") for u in updates}
    if isinstance(raw, dict):
        for key, row in raw.items():
            if not isinstance(row, dict):
                continue
            if str(key) in by_key:
                row["context"] = by_key[str(key)]
    elif isinstance(raw, list):
        for idx, row in enumerate(raw):
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or f"idx:{idx}")
            if key in by_key:
                row["context"] = by_key[key]

    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "applied": True,
        "updated": len(updates),
        "backup": str(backup),
        "path": str(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=str(COGNITIVE_FILE), help="Path to cognitive_insights.json")
    parser.add_argument("--apply", action="store_true", help="Write back enriched contexts")
    parser.add_argument("--show", type=int, default=5, help="Preview first N updates")
    args = parser.parse_args()

    plan = plan_backfill(Path(args.path))
    if not plan.get("ok"):
        print(json.dumps(plan, indent=2))
        return 1

    preview = [
        {
            "key": u.get("key"),
            "before_len": len(str(u.get("before") or "")),
            "after_len": len(str(u.get("after") or "")),
        }
        for u in list(plan.get("updates") or [])[: max(0, int(args.show or 0))]
    ]

    summary = {
        "path": plan.get("path"),
        "items_total": plan.get("items_total"),
        "items_updated": plan.get("items_updated"),
        "context_p50_before": plan.get("context_p50_before"),
        "context_p50_after": plan.get("context_p50_after"),
        "min_target": plan.get("min_target"),
        "preview": preview,
    }

    if args.apply:
        result = apply_backfill(plan)
        summary["apply"] = result

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
