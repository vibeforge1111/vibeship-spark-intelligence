"""Advice feedback requests and logging."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.diagnostics import log_debug
from lib.file_lock import file_lock_for


REQUESTS_FILE = Path.home() / ".spark" / "advice_feedback_requests.jsonl"
FEEDBACK_FILE = Path.home() / ".spark" / "advice_feedback.jsonl"
SUMMARY_FILE = Path.home() / ".spark" / "advice_feedback_summary.json"
STATE_FILE = Path.home() / ".spark" / "advice_feedback_state.json"

REQUESTS_FILE_MAX = 2000
FEEDBACK_FILE_MAX = 2000

CORRELATION_SCHEMA_VERSION = 2


def _rotate_jsonl(path: Path, max_lines: int) -> None:
    """Trim a JSONL file to its last *max_lines* lines.

    Uses atomic temp-write + os.replace to avoid partial-write corruption.
    Callers should hold the per-file lock across append+rotate.
    """
    try:
        if not path.exists():
            return
        # Cheap heuristic: average ~250 bytes per JSON line.
        estimated_lines = path.stat().st_size // 250
        if estimated_lines <= max_lines:
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= max_lines:
            return
        keep = "\n".join(lines[-max_lines:]) + "\n"
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
        tmp.write_text(keep, encoding="utf-8")
        os.replace(str(tmp), str(path))
    except Exception:
        pass


def _append_jsonl_row(path: Path, row: Dict[str, Any], max_lines: int) -> None:
    """Append one JSON row and rotate under a shared lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with file_lock_for(path, fail_open=False):
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
        _rotate_jsonl(path, max_lines)


def _session_lineage(session_id: Optional[str]) -> Dict[str, Any]:
    """Best-effort session lineage metadata for parent/child attribution."""
    sid = str(session_id or "").strip()
    if not sid:
        return {
            "session_kind": "unknown",
            "is_subagent": False,
            "depth_hint": 0,
            "session_tree_key": "",
            "root_session_hint": "",
            "parent_session_hint": "",
        }

    if ":subagent:" in sid:
        head = sid.split(":subagent:", 1)[0]
        return {
            "session_kind": "subagent",
            "is_subagent": True,
            "depth_hint": 2,
            "session_tree_key": head,
            "root_session_hint": f"{head}:main",
            "parent_session_hint": f"{head}:main",
        }
    if ":cron:" in sid:
        head = sid.split(":cron:", 1)[0]
        return {
            "session_kind": "cron",
            "is_subagent": False,
            "depth_hint": 1,
            "session_tree_key": head,
            "root_session_hint": sid,
            "parent_session_hint": "",
        }
    if sid.endswith(":main"):
        return {
            "session_kind": "main",
            "is_subagent": False,
            "depth_hint": 1,
            "session_tree_key": sid.rsplit(":main", 1)[0],
            "root_session_hint": sid,
            "parent_session_hint": "",
        }

    return {
        "session_kind": "other",
        "is_subagent": False,
        "depth_hint": 1,
        "session_tree_key": sid,
        "root_session_hint": sid,
        "parent_session_hint": "",
    }


def _correlation_ids(
    *,
    session_id: Optional[str],
    tool: Optional[str],
    trace_id: Optional[str],
    advice_ids: Optional[List[str]],
    run_id: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Build deterministic correlation ids for advisory telemetry joins."""
    sid = str(session_id or "").strip()
    tname = str(tool or "").strip()
    tid = str(trace_id or "").strip()
    ids = [str(x).strip() for x in (advice_ids or []) if str(x).strip()]
    primary_advisory_id = ids[0] if ids else None
    # Deterministic group key so request/feedback records can be joined even
    # when emitted by different code paths.
    group_blob = "|".join([sid, tname, tid, ",".join(sorted(ids))])
    advisory_group_key = hashlib.sha1(group_blob.encode("utf-8", errors="ignore")).hexdigest()[:24]

    rid = str(run_id or "").strip()
    if not rid:
        rid_blob = "|".join([sid, tid, tname, advisory_group_key])
        rid = hashlib.sha1(rid_blob.encode("utf-8", errors="ignore")).hexdigest()[:20]

    return {
        "trace_id": tid or None,
        "run_id": rid,
        "primary_advisory_id": primary_advisory_id,
        "advisory_group_key": advisory_group_key,
    }


def _load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        log_debug("advice_feedback", "save_state failed", e)


def record_advice_request(
    *,
    session_id: str,
    tool: str,
    advice_ids: List[str],
    advice_texts: Optional[List[str]] = None,
    sources: Optional[List[str]] = None,
    trace_id: Optional[str] = None,
    run_id: Optional[str] = None,
    route: Optional[str] = None,
    packet_id: Optional[str] = None,
    min_interval_s: int = 600,
) -> bool:
    """Record a feedback request when advice was shown."""
    try:
        now = time.time()
        state = _load_state()
        last_by_tool = state.get("last_by_tool") or {}
        last = float(last_by_tool.get(tool) or 0.0)
        if now - last < min_interval_s:
            return False

        REQUESTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        corr = _correlation_ids(
            session_id=session_id,
            tool=tool,
            trace_id=trace_id,
            advice_ids=advice_ids,
            run_id=run_id,
        )
        lineage = _session_lineage(session_id)
        # Deterministic joins require trace_id for high-confidence attribution.
        if not corr.get("trace_id"):
            log_debug("advice_feedback", "record_advice_request skipped: missing trace_id", None)
            return False

        row = {
            "schema_version": CORRELATION_SCHEMA_VERSION,
            "session_id": session_id,
            "tool": tool,
            "advice_ids": advice_ids[:20],
            "advice_texts": [str(x)[:240] for x in (advice_texts or [])[:20]],
            "sources": [str(x)[:80] for x in (sources or [])[:20]],
            "trace_id": corr.get("trace_id"),
            "run_id": corr.get("run_id"),
            "primary_advisory_id": corr.get("primary_advisory_id"),
            "advisory_group_key": corr.get("advisory_group_key"),
            "session_kind": lineage.get("session_kind"),
            "is_subagent": bool(lineage.get("is_subagent")),
            "depth_hint": int(lineage.get("depth_hint") or 0),
            "session_tree_key": str(lineage.get("session_tree_key") or ""),
            "root_session_hint": str(lineage.get("root_session_hint") or ""),
            "parent_session_hint": str(lineage.get("parent_session_hint") or ""),
            "route": (str(route)[:80] if route else None),
            "packet_id": (str(packet_id)[:120] if packet_id else None),
            "created_at": now,
        }
        _append_jsonl_row(REQUESTS_FILE, row, REQUESTS_FILE_MAX)

        last_by_tool[tool] = now
        state["last_by_tool"] = last_by_tool
        _save_state(state)
        return True
    except Exception as e:
        log_debug("advice_feedback", "record_advice_request failed", e)
        return False


def list_requests(limit: int = 10, max_age_s: Optional[int] = None) -> List[Dict[str, Any]]:
    if not REQUESTS_FILE.exists():
        return []
    lines = REQUESTS_FILE.read_text(encoding="utf-8").splitlines()[-max(1, int(limit or 1)) :]
    out: List[Dict[str, Any]] = []
    now = time.time()
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except Exception:
            continue
        if max_age_s is not None:
            created_at = float(row.get("created_at") or 0.0)
            if created_at and now - created_at > max_age_s:
                continue
        out.append(row)
    return out


def has_recent_requests(max_age_s: int = 1800) -> bool:
    return bool(list_requests(limit=5, max_age_s=max_age_s))


def record_feedback(
    *,
    advice_ids: List[str],
    tool: Optional[str],
    helpful: Optional[bool],
    followed: bool,
    insight_keys: Optional[List[str]] = None,
    sources: Optional[List[str]] = None,
    status: Optional[str] = None,
    outcome: Optional[str] = None,
    trace_id: Optional[str] = None,
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    packet_id: Optional[str] = None,
    route: Optional[str] = None,
    notes: str = "",
    source: str = "cli",
) -> bool:
    """Record explicit feedback on advice helpfulness."""
    try:
        st = str(status or "").strip().lower() if status else ""
        if st and st not in {"acted", "blocked", "harmful", "ignored", "skipped"}:
            st = ""
        oc = str(outcome or "").strip().lower() if outcome else ""
        if oc and oc not in {"good", "bad", "neutral"}:
            oc = ""
        corr = _correlation_ids(
            session_id=session_id,
            tool=tool,
            trace_id=trace_id,
            advice_ids=advice_ids,
            run_id=run_id,
        )
        lineage = _session_lineage(session_id)
        row = {
            "schema_version": CORRELATION_SCHEMA_VERSION,
            "advice_ids": advice_ids[:20],
            "tool": tool,
            "helpful": helpful,
            "followed": followed,
            "status": st or None,
            "outcome": oc or None,
            "insight_keys": (insight_keys or [])[:20],
            "sources": (sources or [])[:20],
            "trace_id": corr.get("trace_id"),
            "run_id": corr.get("run_id"),
            "primary_advisory_id": corr.get("primary_advisory_id"),
            "advisory_group_key": corr.get("advisory_group_key"),
            "session_id": (str(session_id)[:160] if session_id else None),
            "session_kind": lineage.get("session_kind"),
            "is_subagent": bool(lineage.get("is_subagent")),
            "depth_hint": int(lineage.get("depth_hint") or 0),
            "session_tree_key": str(lineage.get("session_tree_key") or ""),
            "root_session_hint": str(lineage.get("root_session_hint") or ""),
            "parent_session_hint": str(lineage.get("parent_session_hint") or ""),
            "packet_id": (str(packet_id)[:120] if packet_id else None),
            "route": (str(route)[:80] if route else None),
            "notes": notes[:200] if notes else "",
            "source": source,
            "created_at": time.time(),
        }
        _append_jsonl_row(FEEDBACK_FILE, row, FEEDBACK_FILE_MAX)
        return True
    except Exception as e:
        log_debug("advice_feedback", "record_feedback failed", e)
        return False


def analyze_feedback(
    *,
    min_samples: int = 3,
    max_entries: int = 2000,
    write_summary: bool = True,
) -> Dict[str, Any]:
    """Analyze advice feedback backlog and suggest improvements."""
    if not FEEDBACK_FILE.exists():
        return {"total": 0, "message": "No advice feedback yet"}

    lines = FEEDBACK_FILE.read_text(encoding="utf-8").splitlines()[-max(1, int(max_entries)) :]
    total = 0
    helpful_known = 0
    helpful_true = 0
    by_tool: Dict[str, Dict[str, int]] = {}
    by_source: Dict[str, Dict[str, int]] = {}
    by_insight: Dict[str, Dict[str, int]] = {}

    def _accum(bucket: Dict[str, Dict[str, int]], key: str, helpful: Optional[bool]) -> None:
        if key not in bucket:
            bucket[key] = {"total": 0, "helpful_known": 0, "helpful_true": 0}
        bucket[key]["total"] += 1
        if helpful is True or helpful is False:
            bucket[key]["helpful_known"] += 1
            if helpful is True:
                bucket[key]["helpful_true"] += 1

    for line in lines:
        try:
            row = json.loads(line)
        except Exception:
            continue
        helpful = row.get("helpful")
        tool = row.get("tool") or "unknown"
        sources = row.get("sources") or []
        insight_keys = row.get("insight_keys") or []

        total += 1
        if helpful is True or helpful is False:
            helpful_known += 1
            if helpful is True:
                helpful_true += 1

        _accum(by_tool, tool, helpful)
        for src in sources:
            if src:
                _accum(by_source, src, helpful)
        for key in insight_keys:
            if key:
                _accum(by_insight, key, helpful)

    helpful_rate = helpful_true / max(1, helpful_known)

    def _rank(bucket: Dict[str, Dict[str, int]]) -> List[Dict[str, Any]]:
        out = []
        for k, v in bucket.items():
            rate = v["helpful_true"] / max(1, v["helpful_known"])
            out.append({
                "key": k,
                "total": v["total"],
                "helpful_rate": round(rate, 3),
                "helpful_known": v["helpful_known"],
            })
        out.sort(key=lambda x: (-x["helpful_known"], -x["helpful_rate"]))
        return out

    tool_rank = _rank(by_tool)
    source_rank = _rank(by_source)
    insight_rank = _rank(by_insight)

    recommendations = []
    for item in tool_rank:
        if item["helpful_known"] >= min_samples and item["helpful_rate"] < 0.4:
            recommendations.append(
                f"Review advice quality for tool '{item['key']}' (helpful_rate={item['helpful_rate']:.0%})"
            )
    for item in source_rank:
        if item["helpful_known"] >= min_samples and item["helpful_rate"] < 0.4:
            recommendations.append(
                f"Review advice source '{item['key']}' (helpful_rate={item['helpful_rate']:.0%})"
            )

    summary = {
        "total_feedback": total,
        "helpful_rate": round(helpful_rate, 3),
        "helpful_known": helpful_known,
        "by_tool": tool_rank[:10],
        "by_source": source_rank[:10],
        "top_insights": insight_rank[:10],
        "recommendations": recommendations,
        "last_updated": time.time(),
    }

    if write_summary:
        try:
            SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
            SUMMARY_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        except Exception as e:
            log_debug("advice_feedback", "write_summary failed", e)

    return summary
