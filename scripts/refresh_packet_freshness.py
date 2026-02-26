#!/usr/bin/env python3
"""Refresh advisory packet freshness windows after TTL/config changes."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from lib.advisory_packet_store import INDEX_FILE, PACKET_DIR, get_packet_store_config


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def plan_refresh(
    *,
    index_path: Path = INDEX_FILE,
    packet_dir: Path = PACKET_DIR,
    ttl_s: float | None = None,
    max_age_s: float = 6 * 3600,
) -> Dict[str, Any]:
    index = _load_json(index_path)
    meta = index.get("packet_meta") if isinstance(index.get("packet_meta"), dict) else {}
    if not meta:
        return {
            "ok": False,
            "reason": "empty_meta",
            "index_path": str(index_path),
            "packet_dir": str(packet_dir),
            "ttl_s": float(ttl_s or 0.0),
            "candidates": [],
            "total": 0,
        }

    cfg = get_packet_store_config() if ttl_s is None else {}
    resolved_ttl = float(ttl_s if ttl_s is not None else cfg.get("packet_ttl_s", 900.0) or 900.0)
    now = time.time()

    candidates: List[Dict[str, Any]] = []
    for packet_id, row in meta.items():
        if not isinstance(row, dict):
            continue
        if bool(row.get("invalidated")):
            continue
        updated_ts = float(row.get("updated_ts", 0.0) or 0.0)
        if updated_ts <= 0.0:
            continue
        age_s = max(0.0, now - updated_ts)
        if age_s > float(max(0.0, max_age_s)):
            continue

        current_fresh_until = float(row.get("fresh_until_ts", 0.0) or 0.0)
        target_fresh_until = max(current_fresh_until, updated_ts + resolved_ttl)
        if target_fresh_until <= current_fresh_until:
            continue

        packet_path = packet_dir / f"{packet_id}.json"
        candidates.append(
            {
                "packet_id": str(packet_id),
                "packet_path": str(packet_path),
                "current_fresh_until_ts": current_fresh_until,
                "target_fresh_until_ts": target_fresh_until,
                "updated_ts": updated_ts,
                "age_s": round(age_s, 2),
            }
        )

    return {
        "ok": True,
        "index_path": str(index_path),
        "packet_dir": str(packet_dir),
        "ttl_s": resolved_ttl,
        "max_age_s": float(max_age_s),
        "total": len(meta),
        "candidates": candidates,
        "index": index,
    }


def apply_refresh(plan: Dict[str, Any]) -> Dict[str, Any]:
    if not plan.get("ok"):
        return {"applied": False, "reason": plan.get("reason") or "plan_failed"}
    candidates = list(plan.get("candidates") or [])
    if not candidates:
        return {"applied": False, "reason": "no_updates", "updated": 0}

    index_path = Path(str(plan.get("index_path") or INDEX_FILE))
    packet_dir = Path(str(plan.get("packet_dir") or PACKET_DIR))
    index = plan.get("index") if isinstance(plan.get("index"), dict) else _load_json(index_path)
    meta = index.get("packet_meta") if isinstance(index.get("packet_meta"), dict) else {}

    backup = index_path.with_suffix(index_path.suffix + f".bak-{int(time.time())}")
    if index_path.exists():
        backup.write_text(index_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

    updated = 0
    updated_packets = 0
    for item in candidates:
        packet_id = str(item.get("packet_id") or "")
        target = float(item.get("target_fresh_until_ts") or 0.0)
        if not packet_id or target <= 0.0:
            continue

        row = meta.get(packet_id)
        if isinstance(row, dict):
            row["fresh_until_ts"] = target
            ttl_s = max(30.0, target - float(row.get("updated_ts", 0.0) or 0.0))
            row["ttl_s"] = ttl_s
            updated += 1

        packet_path = packet_dir / f"{packet_id}.json"
        packet = _load_json(packet_path)
        if packet:
            packet["fresh_until_ts"] = target
            ttl_s = max(30.0, target - float(packet.get("updated_ts", 0.0) or 0.0))
            packet["ttl_s"] = ttl_s
            packet_path.write_text(json.dumps(packet, indent=2, ensure_ascii=False), encoding="utf-8")
            updated_packets += 1

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "applied": True,
        "updated_meta_rows": updated,
        "updated_packet_files": updated_packets,
        "backup": str(backup),
        "index_path": str(index_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default=str(INDEX_FILE), help="Path to packet index.json")
    parser.add_argument("--packet-dir", default=str(PACKET_DIR), help="Path to packet directory")
    parser.add_argument("--ttl-s", type=float, default=None, help="TTL seconds override (default from config)")
    parser.add_argument("--max-age-s", type=float, default=6 * 3600, help="Only refresh packets updated within this age")
    parser.add_argument("--apply", action="store_true", help="Write changes")
    parser.add_argument("--show", type=int, default=8, help="Preview first N candidate rows")
    args = parser.parse_args()

    plan = plan_refresh(
        index_path=Path(args.index),
        packet_dir=Path(args.packet_dir),
        ttl_s=args.ttl_s,
        max_age_s=float(args.max_age_s),
    )
    summary = {
        "ok": bool(plan.get("ok")),
        "index_path": plan.get("index_path"),
        "packet_dir": plan.get("packet_dir"),
        "ttl_s": plan.get("ttl_s"),
        "max_age_s": plan.get("max_age_s"),
        "total": plan.get("total"),
        "candidates": len(plan.get("candidates") or []),
        "preview": list(plan.get("candidates") or [])[: max(0, int(args.show or 0))],
    }

    if args.apply and plan.get("ok"):
        summary["apply"] = apply_refresh(plan)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
