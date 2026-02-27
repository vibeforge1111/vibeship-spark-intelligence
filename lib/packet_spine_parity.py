"""Parity helpers for advisory packet index vs SQLite packet spine metadata."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List


_CANONICAL_KEYS = (
    "project_key",
    "session_context_key",
    "tool_name",
    "intent_family",
    "task_plane",
    "invalidated",
    "fresh_until_ts",
    "updated_ts",
    "effectiveness_score",
    "read_count",
    "usage_count",
    "emit_count",
    "deliver_count",
    "source_summary",
    "category_summary",
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_list(value: Any, *, max_items: int = 40) -> List[str]:
    out: List[str] = []
    if isinstance(value, (list, tuple, set)):
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            out.append(text)
            if len(out) >= max_items:
                break
    return out


def _canonical_row(packet_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(row or {})
    return {
        "packet_id": str(packet_id or "").strip(),
        "project_key": str(payload.get("project_key") or "").strip(),
        "session_context_key": str(payload.get("session_context_key") or "").strip(),
        "tool_name": str(payload.get("tool_name") or "").strip(),
        "intent_family": str(payload.get("intent_family") or "").strip(),
        "task_plane": str(payload.get("task_plane") or "").strip(),
        "invalidated": bool(payload.get("invalidated")),
        "fresh_until_ts": round(_safe_float(payload.get("fresh_until_ts"), 0.0), 6),
        "updated_ts": round(_safe_float(payload.get("updated_ts"), 0.0), 6),
        "effectiveness_score": round(_safe_float(payload.get("effectiveness_score"), 0.5), 6),
        "read_count": max(0, _safe_int(payload.get("read_count"), 0)),
        "usage_count": max(0, _safe_int(payload.get("usage_count"), 0)),
        "emit_count": max(0, _safe_int(payload.get("emit_count"), 0)),
        "deliver_count": max(0, _safe_int(payload.get("deliver_count"), 0)),
        "source_summary": _safe_list(payload.get("source_summary"), max_items=20),
        "category_summary": _safe_list(payload.get("category_summary"), max_items=20),
    }


def _coerce_rows(raw: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for packet_id, row in raw.items():
        pid = str(packet_id or "").strip()
        if not pid:
            continue
        out[pid] = _canonical_row(pid, row if isinstance(row, dict) else {})
    return out


def _payload_digest(payload: Dict[str, Any]) -> str:
    subset = {k: payload.get(k) for k in _CANONICAL_KEYS}
    blob = json.dumps(subset, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8", errors="ignore")).hexdigest()


def compare_snapshots(
    index_meta: Any,
    spine_meta: Any,
    *,
    list_limit: int = 25,
) -> Dict[str, Any]:
    base = _coerce_rows(index_meta)
    spine = _coerce_rows(spine_meta)

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
        "index_count": base_count,
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
    rows = int(parity.get("index_count", 0) or 0)
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
