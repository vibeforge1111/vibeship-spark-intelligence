#!/usr/bin/env python3
"""Reconcile advisory packet SQLite spine from index metadata and packet files."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from lib.advisory_packet_store import INDEX_FILE, PACKET_DIR
from lib.packet_spine import set_exact_alias, upsert_packet


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _packet_from_meta(packet_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(row or {})
    return {
        "packet_id": str(packet_id or "").strip(),
        "project_key": str(payload.get("project_key") or "").strip(),
        "session_context_key": str(payload.get("session_context_key") or "").strip(),
        "tool_name": str(payload.get("tool_name") or "").strip(),
        "intent_family": str(payload.get("intent_family") or "").strip(),
        "task_plane": str(payload.get("task_plane") or "").strip(),
        "invalidated": bool(payload.get("invalidated")),
        "fresh_until_ts": float(payload.get("fresh_until_ts", 0.0) or 0.0),
        "updated_ts": float(payload.get("updated_ts", 0.0) or 0.0),
        "effectiveness_score": float(payload.get("effectiveness_score", 0.5) or 0.5),
        "read_count": int(payload.get("read_count", 0) or 0),
        "usage_count": int(payload.get("usage_count", 0) or 0),
        "emit_count": int(payload.get("emit_count", 0) or 0),
        "deliver_count": int(payload.get("deliver_count", 0) or 0),
        "source_summary": list(payload.get("source_summary") or []),
        "category_summary": list(payload.get("category_summary") or []),
    }


def build_reconcile_plan(
    *,
    index_path: Path = INDEX_FILE,
    packet_dir: Path = PACKET_DIR,
) -> Dict[str, Any]:
    index = _load_json(index_path)
    meta = index.get("packet_meta") if isinstance(index.get("packet_meta"), dict) else {}
    by_exact = index.get("by_exact") if isinstance(index.get("by_exact"), dict) else {}

    packets: List[Dict[str, Any]] = []
    packet_file_rows = 0
    packet_meta_rows = 0
    packet_missing = 0

    for packet_id, raw in meta.items():
        pid = str(packet_id or "").strip()
        if not pid:
            continue
        packet_path = packet_dir / f"{pid}.json"
        packet = _load_json(packet_path)
        source = "packet_file"
        if not packet:
            packet_missing += 1
            source = "packet_meta"
            packet = _packet_from_meta(pid, raw if isinstance(raw, dict) else {})
            packet_meta_rows += 1
        else:
            packet_file_rows += 1
            packet.setdefault("packet_id", pid)
        packets.append(
            {
                "packet_id": pid,
                "source": source,
                "packet_exists": bool(packet_path.exists()),
                "packet": packet,
            }
        )

    aliases: List[Dict[str, str]] = []
    for exact_key, packet_id in by_exact.items():
        key = str(exact_key or "").strip()
        pid = str(packet_id or "").strip()
        if not key or not pid:
            continue
        aliases.append({"exact_key": key, "packet_id": pid})

    return {
        "ok": True,
        "index_path": str(index_path),
        "packet_dir": str(packet_dir),
        "packets": packets,
        "aliases": aliases,
        "summary": {
            "index_packet_meta_rows": int(len(meta)),
            "by_exact_rows": int(len(by_exact)),
            "packet_file_rows": int(packet_file_rows),
            "packet_meta_rows": int(packet_meta_rows),
            "packet_missing_files": int(packet_missing),
            "planned_packet_upserts": int(len(packets)),
            "planned_alias_upserts": int(len(aliases)),
        },
    }


def apply_reconcile(
    plan: Dict[str, Any],
    *,
    max_packets: int = 0,
    max_aliases: int = 0,
) -> Dict[str, Any]:
    if not bool((plan or {}).get("ok")):
        return {"applied": False, "reason": "plan_not_ok"}

    packet_rows = list(plan.get("packets") or [])
    alias_rows = list(plan.get("aliases") or [])
    packet_limit = max(0, int(max_packets or 0))
    alias_limit = max(0, int(max_aliases or 0))
    if packet_limit > 0:
        packet_rows = packet_rows[:packet_limit]
    if alias_limit > 0:
        alias_rows = alias_rows[:alias_limit]

    packet_upserts = 0
    alias_upserts = 0
    packet_errors = 0
    alias_errors = 0
    for row in packet_rows:
        payload = row.get("packet")
        if not isinstance(payload, dict):
            packet_errors += 1
            continue
        try:
            upsert_packet(payload)
            packet_upserts += 1
        except Exception:
            packet_errors += 1

    for row in alias_rows:
        exact_key = str((row or {}).get("exact_key") or "").strip()
        packet_id = str((row or {}).get("packet_id") or "").strip()
        if not exact_key or not packet_id:
            alias_errors += 1
            continue
        try:
            set_exact_alias(exact_key, packet_id)
            alias_upserts += 1
        except Exception:
            alias_errors += 1

    return {
        "applied": True,
        "packet_upserts": int(packet_upserts),
        "packet_errors": int(packet_errors),
        "alias_upserts": int(alias_upserts),
        "alias_errors": int(alias_errors),
        "max_packets": int(packet_limit),
        "max_aliases": int(alias_limit),
    }


def _preview_packets(plan: Dict[str, Any], *, show: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in list(plan.get("packets") or [])[: max(0, int(show))]:
        out.append(
            {
                "packet_id": str((row or {}).get("packet_id") or ""),
                "source": str((row or {}).get("source") or ""),
                "packet_exists": bool((row or {}).get("packet_exists")),
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=INDEX_FILE, help="Path to packet index.json")
    parser.add_argument("--packet-dir", type=Path, default=PACKET_DIR, help="Path to packet JSON directory")
    parser.add_argument("--show", type=int, default=10, help="Number of packet rows to preview in output")
    parser.add_argument("--apply", action="store_true", help="Apply upserts to SQLite spine")
    parser.add_argument("--max-packets", type=int, default=0, help="Apply at most N packet rows (0 = all)")
    parser.add_argument("--max-aliases", type=int, default=0, help="Apply at most N alias rows (0 = all)")
    parser.add_argument("--out", type=Path, default=None, help="Optional JSON report path")
    args = parser.parse_args()

    plan = build_reconcile_plan(index_path=Path(args.index), packet_dir=Path(args.packet_dir))
    out: Dict[str, Any] = {
        "ok": bool(plan.get("ok")),
        "ts": time.time(),
        "index_path": str(args.index),
        "packet_dir": str(args.packet_dir),
        "summary": dict(plan.get("summary") or {}),
        "preview_packets": _preview_packets(plan, show=int(args.show)),
        "preview_aliases": list(plan.get("aliases") or [])[: max(0, int(args.show))],
    }
    if args.apply:
        out["apply"] = apply_reconcile(
            plan,
            max_packets=int(args.max_packets),
            max_aliases=int(args.max_aliases),
        )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
