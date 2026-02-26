"""Memory compaction planning helpers.

Provides an ACT-R style activation score and Mem0-like action labels
(`update`, `delete`, `noop`) so compaction decisions are explicit.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_HALF_LIFE_BY_CATEGORY: Dict[str, float] = {
    "user_understanding": 90.0,
    "communication": 90.0,
    "wisdom": 180.0,
    "meta_learning": 120.0,
    "self_awareness": 60.0,
    "reasoning": 60.0,
    "context": 45.0,
    "creativity": 60.0,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _parse_iso(raw: Any) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def normalize_insight_text(text: Any) -> str:
    body = str(text or "").strip().lower()
    body = re.sub(r"[^a-z0-9\s]+", " ", body)
    body = re.sub(r"\s+", " ", body)
    return body.strip()


def age_days(*, created_at: Any = "", last_validated_at: Any = "", now: Optional[datetime] = None) -> float:
    baseline = _parse_iso(last_validated_at) or _parse_iso(created_at)
    if baseline is None:
        return 0.0
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    return max(0.0, float((now_dt - baseline).total_seconds()) / 86400.0)


def activation_score(*, reliability: float, age_days_value: float, half_life_days: float) -> float:
    rel = max(0.0, min(1.0, _safe_float(reliability, 0.0)))
    age = max(0.0, _safe_float(age_days_value, 0.0))
    half_life = max(1.0, _safe_float(half_life_days, 60.0))
    decay = 0.5 ** (age / half_life)
    return max(0.0, min(1.0, rel * decay))


def build_duplicate_groups(
    rows: Iterable[Dict[str, Any]],
    *,
    min_chars: int = 24,
) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for row in rows:
        key = str((row or {}).get("key", "")).strip()
        norm = normalize_insight_text((row or {}).get("insight"))
        if not key or len(norm) < int(min_chars):
            continue
        grouped.setdefault(norm, []).append(key)
    return {sig: keys for sig, keys in grouped.items() if len(keys) > 1}


def build_compaction_plan(
    rows: Iterable[Dict[str, Any]],
    *,
    max_age_days: float = 180.0,
    min_activation: float = 0.20,
    half_life_by_category: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    items = [dict(row or {}) for row in rows if isinstance(row, dict)]
    half_life = dict(DEFAULT_HALF_LIFE_BY_CATEGORY)
    if isinstance(half_life_by_category, dict):
        for key, value in half_life_by_category.items():
            half_life[str(key).strip().lower()] = max(1.0, _safe_float(value, 60.0))

    duplicate_groups = build_duplicate_groups(items)
    duplicate_size_by_key: Dict[str, int] = {}
    for keys in duplicate_groups.values():
        size = len(keys)
        for key in keys:
            duplicate_size_by_key[str(key)] = size

    candidates: List[Dict[str, Any]] = []
    for row in items:
        key = str(row.get("key", "")).strip()
        if not key:
            continue
        category = str(row.get("category", "general")).strip().lower() or "general"
        rel = _safe_float(row.get("reliability"), 0.0)
        row_age = row.get("age_days")
        age = _safe_float(row_age, -1.0)
        if age < 0.0:
            age = age_days(
                created_at=row.get("created_at"),
                last_validated_at=row.get("last_validated_at"),
            )
        half = _safe_float(half_life.get(category, 60.0), 60.0)
        activation = activation_score(
            reliability=rel,
            age_days_value=age,
            half_life_days=half,
        )
        duplicate_group_size = int(duplicate_size_by_key.get(key, 1))
        if age >= float(max_age_days) and activation < float(min_activation):
            action = "delete"
            reason = "stale_low_activation"
        elif duplicate_group_size > 1:
            action = "update"
            reason = "duplicate_merge"
        else:
            action = "noop"
            reason = "keep"
        candidates.append(
            {
                "key": key,
                "category": category,
                "age_days": round(age, 3),
                "reliability": round(rel, 4),
                "activation": round(activation, 4),
                "duplicate_group_size": duplicate_group_size,
                "action": action,
                "reason": reason,
            }
        )

    rank = {"delete": 0, "update": 1, "noop": 2}
    candidates.sort(
        key=lambda row: (
            rank.get(str(row.get("action")), 9),
            -_safe_float(row.get("age_days"), 0.0),
            _safe_float(row.get("activation"), 0.0),
        )
    )

    by_action = {"delete": 0, "update": 0, "noop": 0}
    for row in candidates:
        action = str(row.get("action"))
        by_action[action] = int(by_action.get(action, 0) + 1)

    return {
        "summary": {
            "total": len(candidates),
            "by_action": by_action,
            "duplicate_groups": len(duplicate_groups),
            "delete_ratio": round(float(by_action.get("delete", 0)) / max(len(candidates), 1), 4),
            "max_age_days": float(max_age_days),
            "min_activation": float(min_activation),
        },
        "candidates": candidates,
    }

