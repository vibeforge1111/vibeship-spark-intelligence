#!/usr/bin/env python3
"""Compact chip insight JSONL files to reduce telemetry bloat.

Supports:
- line-based compaction
- optional age window filtering
- optional active-chip-only filtering
- optional schema-preserving retention
- optional archival backup before rewrite
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_registry_active(project_path: str) -> List[str]:
    registry = Path.home() / ".spark" / "chip_registry.json"
    if not registry.exists():
        return []
    try:
        raw = json.loads(registry.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    active = raw.get("active") or {}
    if not isinstance(active, dict):
        return []
    rows = active.get(project_path) or []
    if not isinstance(rows, list):
        return []
    return sorted({str(r).strip() for r in rows if str(r).strip()})


def _is_schema_row(row: Dict[str, Any]) -> bool:
    captured = row.get("captured_data") or {}
    if not isinstance(captured, dict):
        return False
    payload = captured.get("learning_payload")
    return isinstance(payload, dict) and bool(payload)


def _read_jsonl_rows(path: Path) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    raw_total = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        raw_total += 1
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows, raw_total


def _filter_rows(rows: List[Dict[str, Any]], max_age_days: int) -> List[Dict[str, Any]]:
    if max_age_days <= 0:
        return rows
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    kept: List[Dict[str, Any]] = []
    for row in rows:
        ts = _parse_timestamp(row.get("timestamp"))
        if ts is None:
            # No parseable timestamp — preserve the row rather than silently
            # dropping data whose age we cannot determine.
            kept.append(row)
            continue
        if ts >= cutoff:
            kept.append(row)
    return kept


def _retain_rows(rows: List[Dict[str, Any]], keep_lines: int, prefer_schema: bool) -> List[Dict[str, Any]]:
    if keep_lines <= 0:
        return []
    if len(rows) <= keep_lines:
        return rows
    if not prefer_schema:
        return rows[-keep_lines:]

    schema_rows = [r for r in rows if _is_schema_row(r)]
    non_schema_rows = [r for r in rows if not _is_schema_row(r)]

    kept: List[Dict[str, Any]] = []
    if schema_rows:
        kept.extend(schema_rows[-keep_lines:])
    remaining = keep_lines - len(kept)
    if remaining > 0 and non_schema_rows:
        kept = non_schema_rows[-remaining:] + kept
    return kept[-keep_lines:]


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]):
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = ""
    for row in rows:
        payload += json.dumps(row, ensure_ascii=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def _compact_file(
    path: Path,
    *,
    keep_lines: int,
    max_age_days: int,
    prefer_schema: bool,
    apply: bool,
    archive_dir: Path | None,
) -> Dict[str, int]:
    if keep_lines <= 0 or not path.exists():
        return {"before": 0, "after": 0, "schema_before": 0, "schema_after": 0}

    rows, before = _read_jsonl_rows(path)
    filtered = _filter_rows(rows, max_age_days=max_age_days)
    retained = _retain_rows(filtered, keep_lines=keep_lines, prefer_schema=prefer_schema)
    after = len(retained)
    schema_before = sum(1 for r in rows if _is_schema_row(r))
    schema_after = sum(1 for r in retained if _is_schema_row(r))

    if apply and before != after:
        if archive_dir is not None:
            archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, archive_dir / path.name)
        _write_jsonl(path, retained)

    return {
        "before": before,
        "after": after,
        "schema_before": schema_before,
        "schema_after": schema_after,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compact ~/.spark/chip_insights/*.jsonl")
    parser.add_argument("--keep-lines", type=int, default=2000, help="lines to keep per chip file")
    parser.add_argument("--max-age-days", type=int, default=0, help="keep only rows newer than N days (0 disables)")
    parser.add_argument("--prefer-schema", action="store_true", help="keep schema rows preferentially within keep-lines cap")
    parser.add_argument("--active-only", action="store_true", help="compact only project active chip files")
    parser.add_argument(
        "--project-path",
        default=".",
        help="project path key used in ~/.spark/chip_registry.json when --active-only is set",
    )
    parser.add_argument("--archive", action="store_true", help="backup original files to ~/.spark/archive/chip_insights/<timestamp>")
    parser.add_argument("--apply", action="store_true", help="write changes (default is dry-run)")
    args = parser.parse_args()

    chip_dir = Path.home() / ".spark" / "chip_insights"
    files = sorted(chip_dir.glob("*.jsonl"))
    active_ids = _load_registry_active(str(args.project_path)) if bool(args.active_only) else []
    if active_ids:
        wanted = {f"{cid}.jsonl" for cid in active_ids}
        files = [f for f in files if f.name in wanted]

    archive_dir: Path | None = None
    if bool(args.archive):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_dir = Path.home() / ".spark" / "archive" / "chip_insights" / stamp

    print(f"chip_dir={chip_dir}")
    print(
        f"files={len(files)} keep_lines={args.keep_lines} "
        f"max_age_days={args.max_age_days} prefer_schema={bool(args.prefer_schema)} "
        f"active_only={bool(args.active_only)} apply={args.apply}"
    )
    if active_ids:
        print(f"active_ids={','.join(active_ids)}")
    if archive_dir is not None:
        print(f"archive_dir={archive_dir}")

    total_before = 0
    total_after = 0
    total_schema_before = 0
    total_schema_after = 0
    for path in files:
        res = _compact_file(
            path,
            keep_lines=int(args.keep_lines),
            max_age_days=int(args.max_age_days),
            prefer_schema=bool(args.prefer_schema),
            apply=bool(args.apply),
            archive_dir=archive_dir,
        )
        total_before += res["before"]
        total_after += res["after"]
        total_schema_before += res["schema_before"]
        total_schema_after += res["schema_after"]
        if res["before"] != res["after"]:
            print(
                f"{path.name}: {res['before']} -> {res['after']} "
                f"(schema {res['schema_before']} -> {res['schema_after']})"
            )
        else:
            print(f"{path.name}: {res['before']} (unchanged, schema={res['schema_before']})")

    print(f"TOTAL: {total_before} -> {total_after} (schema {total_schema_before} -> {total_schema_after})")
    if not args.apply:
        print("Dry-run only. Re-run with --apply to write compacted files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


