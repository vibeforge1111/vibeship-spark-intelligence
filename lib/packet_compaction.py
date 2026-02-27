"""Advisory packet compaction planning helpers.

Provides a compact action contract (`update`, `delete`, `noop`) for
packet metadata so advisory-store compaction can run in preview/apply
modes with bounded risk.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional


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


def build_packet_compaction_plan(
    packet_meta: Iterable[Dict[str, Any]],
    *,
    now_ts: Optional[float] = None,
    stale_age_days: float = 7.0,
    low_effectiveness: float = 0.25,
    review_age_days: float = 2.0,
) -> Dict[str, Any]:
    now_value = _safe_float(now_ts, time.time())
    stale_age_s = max(0.0, _safe_float(stale_age_days, 7.0) * 86400.0)
    review_age_s = max(0.0, _safe_float(review_age_days, 2.0) * 86400.0)
    low_eff = max(0.0, min(1.0, _safe_float(low_effectiveness, 0.25)))

    rows: List[Dict[str, Any]] = []
    for raw in packet_meta:
        if not isinstance(raw, dict):
            continue
        packet_id = str(raw.get("packet_id") or "").strip()
        if not packet_id:
            continue
        invalidated = bool(raw.get("invalidated"))
        updated_ts = _safe_float(raw.get("updated_ts"), 0.0)
        fresh_until_ts = _safe_float(raw.get("fresh_until_ts"), 0.0)
        age_s = max(0.0, now_value - updated_ts) if updated_ts > 0.0 else 0.0
        stale = fresh_until_ts > 0.0 and fresh_until_ts < now_value
        usage_count = _safe_int(raw.get("usage_count", raw.get("read_count", 0)), 0)
        feedback_count = _safe_int(raw.get("feedback_count"), 0)
        effectiveness = _safe_float(raw.get("effectiveness_score"), 0.5)

        action = "noop"
        reason = "keep"
        if invalidated:
            action = "noop"
            reason = "already_invalidated"
        elif stale and usage_count <= 0 and age_s >= stale_age_s:
            action = "delete"
            reason = "stale_never_used"
        elif stale and effectiveness < low_eff and age_s >= stale_age_s:
            action = "delete"
            reason = "stale_low_effectiveness"
        elif (not stale) and usage_count <= 0 and feedback_count <= 0 and age_s >= review_age_s:
            action = "update"
            reason = "cold_packet_review"

        rows.append(
            {
                "packet_id": packet_id,
                "action": action,
                "reason": reason,
                "invalidated": invalidated,
                "stale": stale,
                "age_days": round(age_s / 86400.0, 3),
                "usage_count": usage_count,
                "feedback_count": feedback_count,
                "effectiveness_score": round(effectiveness, 4),
            }
        )

    rank = {"delete": 0, "update": 1, "noop": 2}
    rows.sort(
        key=lambda row: (
            rank.get(str(row.get("action")), 9),
            -_safe_float(row.get("age_days"), 0.0),
            _safe_float(row.get("effectiveness_score"), 1.0),
        )
    )

    by_action = {"delete": 0, "update": 0, "noop": 0}
    for row in rows:
        action = str(row.get("action"))
        by_action[action] = int(by_action.get(action, 0) + 1)

    return {
        "summary": {
            "total": int(len(rows)),
            "by_action": by_action,
            "stale_age_days": float(stale_age_days),
            "low_effectiveness": float(low_eff),
            "review_age_days": float(review_age_days),
        },
        "candidates": rows,
    }

