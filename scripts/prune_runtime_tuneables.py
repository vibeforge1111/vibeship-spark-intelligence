#!/usr/bin/env python3
"""Prune unknown/retired keys from runtime tuneables.

Defaults to ~/.spark/tuneables.json, writes a timestamped backup, then writes
the cleaned payload when --write is provided.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from lib.tuneables_schema import SCHEMA


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def _prune_payload(
    payload: Dict[str, Any],
    *,
    drop_unknown_sections: bool,
) -> Tuple[Dict[str, Any], List[str]]:
    cleaned: Dict[str, Any] = {}
    removed: List[str] = []

    for section, section_payload in payload.items():
        if section == "updated_at":
            cleaned[section] = section_payload
            continue

        if section not in SCHEMA:
            if drop_unknown_sections:
                removed.append(f"section:{section}")
                continue
            cleaned[section] = section_payload
            continue

        if not isinstance(section_payload, dict):
            cleaned[section] = section_payload
            continue

        section_schema = SCHEMA.get(section, {})
        is_dynamic = section in {"llm_areas", "observatory", "openclaw_tailer", "opportunity_scanner"}
        allow_doc_key = section in {"source_roles", "scheduler"}

        out_section: Dict[str, Any] = {}
        for key, value in section_payload.items():
            if key in section_schema:
                out_section[key] = value
                continue
            if is_dynamic:
                out_section[key] = value
                continue
            if key.startswith("_") or (allow_doc_key and key == "_doc"):
                out_section[key] = value
                continue
            removed.append(f"{section}.{key}")
        cleaned[section] = out_section

    return cleaned, removed


def main() -> int:
    ap = argparse.ArgumentParser(description="Prune unknown keys from runtime tuneables.")
    ap.add_argument(
        "--path",
        default=str(Path.home() / ".spark" / "tuneables.json"),
        help="Runtime tuneables path",
    )
    ap.add_argument(
        "--write",
        action="store_true",
        help="Write cleaned payload back to path (otherwise dry-run)",
    )
    ap.add_argument(
        "--drop-unknown-sections",
        action="store_true",
        help="Also remove top-level unknown sections",
    )
    args = ap.parse_args()

    path = Path(args.path).expanduser()
    payload = _load_json(path)
    if not payload:
        print(json.dumps({"ok": False, "path": str(path), "error": "missing_or_invalid_payload"}, indent=2))
        return 1

    cleaned, removed = _prune_payload(
        payload,
        drop_unknown_sections=bool(args.drop_unknown_sections),
    )
    result = {
        "ok": True,
        "path": str(path),
        "removed_count": len(removed),
        "removed": removed,
        "write": bool(args.write),
    }

    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"tuneables.backup_prune_{stamp}.json")
        if path.exists():
            backup.write_text(path.read_text(encoding="utf-8-sig"), encoding="utf-8")
            result["backup"] = str(backup)
        cleaned["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path.write_text(json.dumps(cleaned, indent=2, ensure_ascii=True), encoding="utf-8")

    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

