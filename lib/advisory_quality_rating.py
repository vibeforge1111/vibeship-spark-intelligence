"""Strict rating flow for emitted advisory quality events."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


RATINGS_FILE = Path.home() / ".spark" / "advisor" / "advisory_quality_ratings.jsonl"


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _tail_jsonl(path: Path, max_rows: int) -> List[Dict[str, Any]]:
    if not path.exists() or max_rows <= 0:
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-max_rows:]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
    existing = []
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            existing = []
    existing.append(json.dumps(row, ensure_ascii=False))
    tmp.write_text("\n".join(existing) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def _label_to_feedback(label: str) -> Tuple[Optional[bool], bool, str, str]:
    key = _norm_text(label).lower()
    if key == "helpful":
        return True, True, "acted", "good"
    if key == "unhelpful":
        return False, True, "blocked", "bad"
    if key == "harmful":
        return False, True, "harmful", "bad"
    if key == "not_followed":
        return None, False, "ignored", "neutral"
    return None, False, "ignored", "neutral"


def _record_feedback(**kwargs: Any) -> bool:
    from .advice_feedback import record_feedback

    return bool(record_feedback(**kwargs))


def _record_packet_outcome_for_advice(
    advice_id: str,
    *,
    status: str,
    source: str,
    tool_name: Optional[str],
    trace_id: Optional[str],
    notes: str,
    count_effectiveness: bool,
) -> Dict[str, Any]:
    from .advisory_packet_store import record_packet_outcome_for_advice

    return record_packet_outcome_for_advice(
        advice_id,
        status=status,
        source=source,
        tool_name=tool_name,
        trace_id=trace_id,
        notes=notes,
        count_effectiveness=count_effectiveness,
    )


def _refresh_quality_spine(spark_dir: Path) -> Dict[str, Any]:
    from .advisory_quality_spine import run_advisory_quality_spine_default

    out = run_advisory_quality_spine_default(spark_dir=spark_dir, write_files=True)
    return out.get("summary", {}) if isinstance(out, dict) else {}


def list_events(
    *,
    spark_dir: Path,
    limit: int = 20,
    provider: str = "",
    tool: str = "",
) -> List[Dict[str, Any]]:
    events_file = spark_dir / "advisor" / "advisory_quality_events.jsonl"
    rows = _tail_jsonl(events_file, max(1, int(limit) * 10))
    want_provider = _norm_text(provider).lower()
    want_tool = _norm_text(tool).lower()
    filtered: List[Dict[str, Any]] = []
    for row in reversed(rows):
        if want_provider and _norm_text(row.get("provider")).lower() != want_provider:
            continue
        if want_tool and _norm_text(row.get("tool")).lower() != want_tool:
            continue
        filtered.append(row)
        if len(filtered) >= max(1, int(limit)):
            break
    return filtered


def rate_latest(
    *,
    spark_dir: Path,
    label: str,
    notes: str = "",
    source: str = "quality_rate_cli",
    count_effectiveness: bool = True,
    refresh_spine: bool = True,
    trace_id: str = "",
    advice_id: str = "",
    tool: str = "",
    provider: str = "",
    max_scan: int = 2000,
) -> Dict[str, Any]:
    if refresh_spine:
        _refresh_quality_spine(spark_dir)

    rows = list_events(
        spark_dir=spark_dir,
        limit=max(1, int(max_scan)),
        provider=str(provider or ""),
        tool=str(tool or ""),
    )
    want_trace = _norm_text(trace_id)
    want_advice = _norm_text(advice_id)
    chosen: Optional[Dict[str, Any]] = None
    for row in rows:
        if want_trace and _norm_text(row.get("trace_id")) != want_trace:
            continue
        if want_advice and _norm_text(row.get("advice_id")) != want_advice:
            continue
        chosen = row
        break
    if not isinstance(chosen, dict):
        return {
            "ok": False,
            "reason": "event_not_found_for_filters",
            "filters": {
                "trace_id": want_trace,
                "advice_id": want_advice,
                "tool": _norm_text(tool),
                "provider": _norm_text(provider),
            },
        }

    result = rate_event(
        spark_dir=spark_dir,
        event_id=_norm_text(chosen.get("event_id")),
        label=label,
        notes=notes,
        source=source,
        count_effectiveness=count_effectiveness,
        refresh_spine=False,
    )
    if refresh_spine and bool(result.get("ok")):
        result["refreshed_summary"] = _refresh_quality_spine(spark_dir)
    return result


def rate_event(
    *,
    spark_dir: Path,
    event_id: str,
    label: str,
    notes: str = "",
    source: str = "quality_rate_cli",
    count_effectiveness: bool = True,
    refresh_spine: bool = True,
) -> Dict[str, Any]:
    events_file = spark_dir / "advisor" / "advisory_quality_events.jsonl"
    rows = _tail_jsonl(events_file, 50000)
    want = _norm_text(event_id)
    if not want:
        return {"ok": False, "reason": "missing_event_id"}
    row = next((r for r in rows if _norm_text(r.get("event_id")) == want), None)
    if not isinstance(row, dict):
        return {"ok": False, "reason": "event_not_found", "event_id": want}

    trace_id = _norm_text(row.get("trace_id"))
    if not trace_id:
        return {"ok": False, "reason": "missing_trace_id", "event_id": want}
    advice_id = _norm_text(row.get("advice_id"))
    if not advice_id:
        return {"ok": False, "reason": "missing_advice_id", "event_id": want}

    helpful, followed, status, outcome = _label_to_feedback(label)
    tool = _norm_text(row.get("tool")) or None
    run_id = _norm_text(row.get("run_id")) or None
    session_id = _norm_text(row.get("session_id")) or None
    route = _norm_text(row.get("route")) or None

    feedback_ok = _record_feedback(
        advice_ids=[advice_id],
        tool=tool,
        helpful=helpful,
        followed=followed,
        status=status,
        outcome=outcome,
        trace_id=trace_id,
        run_id=run_id,
        session_id=session_id,
        route=route,
        notes=str(notes or "")[:200],
        source=str(source or "quality_rate_cli")[:40],
    )

    packet_result = _record_packet_outcome_for_advice(
        advice_id,
        status=status,
        source=str(source or "quality_rate_cli")[:40],
        tool_name=tool,
        trace_id=trace_id,
        notes=str(notes or "")[:200],
        count_effectiveness=bool(count_effectiveness),
    )

    rating_row = {
        "ts": time.time(),
        "event_id": want,
        "trace_id": trace_id,
        "run_id": run_id,
        "session_id": session_id,
        "tool": tool,
        "provider": _norm_text(row.get("provider")) or "unknown",
        "advice_id": advice_id,
        "label": _norm_text(label).lower() or "unknown",
        "status": status,
        "helpful": helpful,
        "followed": followed,
        "notes": str(notes or "")[:200],
        "source": str(source or "quality_rate_cli")[:40],
    }
    _append_jsonl(RATINGS_FILE, rating_row)

    refreshed_summary = {}
    if refresh_spine:
        refreshed_summary = _refresh_quality_spine(spark_dir)

    return {
        "ok": bool(feedback_ok),
        "event_id": want,
        "feedback_ok": bool(feedback_ok),
        "packet_result": packet_result,
        "rating_row": rating_row,
        "refreshed_summary": refreshed_summary,
    }
