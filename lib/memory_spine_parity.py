"""Parity helpers for JSON cognitive insights vs SQLite memory spine snapshot."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List


def _coerce_snapshot(raw: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for key, value in raw.items():
        row = value if isinstance(value, dict) else {}
        out[str(key)] = row
    return out


def _payload_digest(payload: Dict[str, Any]) -> str:
    blob = json.dumps(payload or {}, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8", errors="ignore")).hexdigest()


def compare_snapshots(
    json_snapshot: Any,
    spine_snapshot: Any,
    *,
    list_limit: int = 25,
) -> Dict[str, Any]:
    base = _coerce_snapshot(json_snapshot)
    spine = _coerce_snapshot(spine_snapshot)

    base_keys = set(base.keys())
    spine_keys = set(spine.keys())
    common = base_keys.intersection(spine_keys)
    missing_in_spine = sorted(base_keys - spine_keys)
    extra_in_spine = sorted(spine_keys - base_keys)

    payload_match_keys: List[str] = []
    payload_mismatch_keys: List[str] = []
    for key in sorted(common):
        if _payload_digest(base.get(key) or {}) == _payload_digest(spine.get(key) or {}):
            payload_match_keys.append(key)
        else:
            payload_mismatch_keys.append(key)

    base_count = int(len(base_keys))
    spine_count = int(len(spine_keys))
    key_overlap = int(len(common))
    payload_match_count = int(len(payload_match_keys))

    key_parity_ratio = float(key_overlap) / float(max(base_count, 1))
    payload_parity_ratio = float(payload_match_count) / float(max(base_count, 1))

    return {
        "json_count": base_count,
        "spine_count": spine_count,
        "key_overlap_count": key_overlap,
        "payload_match_count": payload_match_count,
        "key_parity_ratio": round(key_parity_ratio, 4),
        "payload_parity_ratio": round(payload_parity_ratio, 4),
        "missing_in_spine_count": int(len(missing_in_spine)),
        "extra_in_spine_count": int(len(extra_in_spine)),
        "payload_mismatch_count": int(len(payload_mismatch_keys)),
        "missing_in_spine": missing_in_spine[: max(0, int(list_limit))],
        "extra_in_spine": extra_in_spine[: max(0, int(list_limit))],
        "payload_mismatch_keys": payload_mismatch_keys[: max(0, int(list_limit))],
    }


def evaluate_parity_gate(
    parity: Dict[str, Any],
    *,
    min_payload_parity: float = 0.995,
    min_rows: int = 10,
) -> Dict[str, Any]:
    payload_ratio = float(parity.get("payload_parity_ratio", 0.0) or 0.0)
    rows = int(parity.get("json_count", 0) or 0)
    pass_rows = rows >= int(min_rows)
    pass_ratio = payload_ratio >= float(min_payload_parity)
    return {
        "pass": bool(pass_rows and pass_ratio),
        "rows": rows,
        "payload_parity_ratio": round(payload_ratio, 4),
        "min_rows": int(min_rows),
        "min_payload_parity": float(min_payload_parity),
        "pass_rows": bool(pass_rows),
        "pass_ratio": bool(pass_ratio),
    }
