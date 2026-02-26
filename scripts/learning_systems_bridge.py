"""CLI bridge for spark-learning-systems to integrate with Spark safely."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

from lib.learning_systems_bridge import (
    list_tuneable_proposals,
    propose_tuneable_change,
    store_external_insight,
)


def _parse_json_maybe(value: str) -> Any:
    text = str(value or "").strip()
    if not text:
        return text
    try:
        return json.loads(text)
    except Exception:
        return text


def _print(payload: Dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok", True) else 1


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Spark Learning Systems bridge CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("store-insight", help="Store an insight through validate_and_store")
    s1.add_argument("--text", required=True)
    s1.add_argument("--category", required=True)
    s1.add_argument("--source", required=True)
    s1.add_argument("--context", default="")
    s1.add_argument("--confidence", type=float, default=0.7)

    s2 = sub.add_parser("propose-tuneable", help="Queue a tuneable proposal")
    s2.add_argument("--system-id", required=True)
    s2.add_argument("--section", required=True)
    s2.add_argument("--key", required=True)
    s2.add_argument("--new-value", required=True, help="JSON literal or raw string")
    s2.add_argument("--reasoning", required=True)
    s2.add_argument("--confidence", type=float, default=0.5)
    s2.add_argument("--metadata", default="{}", help="JSON object")

    s3 = sub.add_parser("list-proposals", help="List recent proposals")
    s3.add_argument("--limit", type=int, default=50)
    s3.add_argument("--status", default="")

    args = p.parse_args(argv)
    if args.cmd == "store-insight":
        out = store_external_insight(
            text=args.text,
            category=args.category,
            source=args.source,
            context=args.context,
            confidence=args.confidence,
        )
        out["ok"] = bool(out.get("stored"))
        return _print(out)

    if args.cmd == "propose-tuneable":
        metadata = _parse_json_maybe(args.metadata)
        if not isinstance(metadata, dict):
            metadata = {"raw_metadata": str(args.metadata)}
        out = propose_tuneable_change(
            system_id=args.system_id,
            section=args.section,
            key=args.key,
            new_value=_parse_json_maybe(args.new_value),
            reasoning=args.reasoning,
            confidence=args.confidence,
            metadata=metadata,
        )
        out["ok"] = bool(out.get("queued"))
        return _print(out)

    out = {
        "ok": True,
        "items": list_tuneable_proposals(limit=args.limit, status=(args.status or None)),
    }
    return _print(out)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

