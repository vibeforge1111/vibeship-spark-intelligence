"""
Lightweight quarantine sink for advisory rows that are dropped by quality gates.

The quarantine path is intentionally compact and bounded:
- keep one short text snippet and text length
- preserve suppression reasons and stage/source
- persist advisory meta/reason fields for later audits
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .jsonl_utils import append_jsonl_capped as _append_jsonl_capped

QUARANTINE_DIR = Path.home() / ".spark" / "advisory_quarantine"
QUARANTINE_FILE = QUARANTINE_DIR / "advisory_quarantine.jsonl"


def _max_lines() -> int:
    try:
        return max(1, int(os.environ.get("SPARK_ADVISORY_QUARANTINE_MAX_LINES", "1200")))
    except Exception:
        return 1200


def _coerce_float01(value: Any) -> float | None:
    try:
        value_f = float(value)
    except Exception:
        return None
    if value_f != value_f:
        return None
    if value_f < 0.0:
        return 0.0
    if value_f > 1.0:
        return 1.0
    return round(value_f, 4)


def _safe_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _sanitize_text(text: str, limit: int = 420) -> str:
    snippet = str(text or "").strip()
    if len(snippet) <= limit:
        return snippet
    return snippet[: max(1, limit - 3)] + "..."


def record_quarantine_item(
    *,
    source: str,
    stage: str,
    reason: str,
    text: str | None = None,
    advisory_quality: Dict[str, Any] | None = None,
    advisory_readiness: float | None = None,
    meta: Dict[str, Any] | None = None,
    extras: Dict[str, Any] | None = None,
) -> None:
    """Append a compact diagnostic row to quarantine sink.

    This intentionally avoids raising exceptions to protect live advisory flow.
    """
    try:
        source_name = str(source or "").strip() or "unknown"
        stage_name = str(stage or "").strip() or "unknown"
        reason_text = str(reason or "").strip() or "unspecified"
        full_text = str(text or "")
        payload: Dict[str, Any] = {
            "ts": round(time.time(), 4),
            "recorded_at": datetime.now().isoformat(),
            "source": source_name,
            "stage": stage_name,
            "reason": reason_text[:120],
            "text_len": len(full_text),
            "text_snippet": _sanitize_text(full_text),
            "advisory_quality": _safe_dict(advisory_quality),
        }
        readiness = _coerce_float01(advisory_readiness)
        if readiness is not None:
            payload["advisory_readiness"] = readiness
        if isinstance(meta, dict):
            payload["source_meta"] = _safe_dict(meta)
        if isinstance(extras, dict):
            payload["extras"] = _safe_dict(extras)
        _append_jsonl_capped(QUARANTINE_FILE, payload, _max_lines())
    except Exception:
        return
