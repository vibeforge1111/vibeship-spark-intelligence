"""Central intake observability for intelligence flow.

This module logs item-level lifecycle events so every candidate can be
reverse engineered from intake to final storage/drop decisions.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .jsonl_utils import append_jsonl_capped

FLOW_EVENTS_FILE = Path.home() / ".spark" / "intelligence_flow_events.jsonl"
FLOW_EVENTS_MAX_LINES = 200000


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _derive_item_id(*, text: str, source: str, trace_id: str) -> str:
    seed = f"{source}|{trace_id}|{text[:240]}".encode("utf-8", errors="ignore")
    return hashlib.sha1(seed).hexdigest()[:16]


def log_intelligence_flow_event(
    *,
    stage: str,
    action: str,
    text: str = "",
    source: str = "",
    category: str = "",
    context: str = "",
    trace_id: Optional[str] = None,
    item_id: Optional[str] = None,
    verdict: Optional[str] = None,
    stored: Optional[bool] = None,
    reason: Optional[str] = None,
    insight_key: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """Append one intake lifecycle event and return stable item_id."""
    trace = _norm_text(trace_id)
    body = _norm_text(text)
    src = _norm_text(source) or "unknown"
    iid = _norm_text(item_id) or _derive_item_id(text=body, source=src, trace_id=trace)
    row: Dict[str, Any] = {
        "ts": float(time.time()),
        "item_id": iid,
        "trace_id": trace,
        "stage": _norm_text(stage) or "unknown",
        "action": _norm_text(action) or "unknown",
        "source": src,
        "category": _norm_text(category),
        "text_excerpt": body[:360],
        "context_excerpt": _norm_text(context)[:240],
    }
    if verdict is not None:
        row["verdict"] = _norm_text(verdict)
    if stored is not None:
        row["stored"] = bool(stored)
    if reason is not None:
        row["reason"] = _norm_text(reason)
    if insight_key is not None:
        row["insight_key"] = _norm_text(insight_key)
    if isinstance(extra, dict) and extra:
        safe_extra: Dict[str, Any] = {}
        for key, value in extra.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe_extra[str(key)] = value
            else:
                safe_extra[str(key)] = _norm_text(value)[:240]
        row["extra"] = safe_extra

    append_jsonl_capped(
        FLOW_EVENTS_FILE,
        row,
        FLOW_EVENTS_MAX_LINES,
        ensure_ascii=True,
    )
    return iid

