"""SQLite spine for advisory packet metadata and lookup paths."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


_SPINE_DB_RAW = str(
    os.getenv("SPARK_ADVISORY_PACKET_SPINE_DB")
    or os.getenv("SPARK_PACKET_SPINE_DB")
    or (Path.home() / ".spark" / "advisory_packet_spine.db")
).strip()
SPINE_DB = Path(_SPINE_DB_RAW)
_SPINE_LOCK = threading.RLock()


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _connect() -> sqlite3.Connection:
    SPINE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SPINE_DB), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS packet_meta (
            packet_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            session_context_key TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            intent_family TEXT NOT NULL,
            task_plane TEXT NOT NULL,
            invalidated INTEGER NOT NULL DEFAULT 0,
            fresh_until_ts REAL NOT NULL DEFAULT 0,
            updated_ts REAL NOT NULL DEFAULT 0,
            effectiveness_score REAL NOT NULL DEFAULT 0.5,
            read_count INTEGER NOT NULL DEFAULT 0,
            usage_count INTEGER NOT NULL DEFAULT 0,
            emit_count INTEGER NOT NULL DEFAULT 0,
            deliver_count INTEGER NOT NULL DEFAULT 0,
            source_summary_json TEXT NOT NULL DEFAULT '[]',
            category_summary_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS exact_alias (
            exact_key TEXT PRIMARY KEY,
            packet_id TEXT NOT NULL,
            updated_ts REAL NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_packet_meta_relaxed ON packet_meta(project_key, tool_name, intent_family, task_plane, invalidated, fresh_until_ts, updated_ts)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_packet_meta_project ON packet_meta(project_key, invalidated, fresh_until_ts)"
    )
    conn.commit()


def upsert_packet(packet: Dict[str, Any]) -> None:
    if not isinstance(packet, dict):
        return
    packet_id = str(packet.get("packet_id") or "").strip()
    if not packet_id:
        return
    row = {
        "packet_id": packet_id,
        "project_key": str(packet.get("project_key") or "").strip(),
        "session_context_key": str(packet.get("session_context_key") or "").strip(),
        "tool_name": str(packet.get("tool_name") or "").strip(),
        "intent_family": str(packet.get("intent_family") or "").strip(),
        "task_plane": str(packet.get("task_plane") or "").strip(),
        "invalidated": 1 if bool(packet.get("invalidated")) else 0,
        "fresh_until_ts": _to_float(packet.get("fresh_until_ts"), 0.0),
        "updated_ts": _to_float(packet.get("updated_ts"), time.time()),
        "effectiveness_score": max(0.0, min(1.0, _to_float(packet.get("effectiveness_score"), 0.5))),
        "read_count": max(0, _to_int(packet.get("read_count"), 0)),
        "usage_count": max(0, _to_int(packet.get("usage_count"), 0)),
        "emit_count": max(0, _to_int(packet.get("emit_count"), 0)),
        "deliver_count": max(0, _to_int(packet.get("deliver_count"), 0)),
        "source_summary_json": json.dumps(list(packet.get("source_summary") or []), ensure_ascii=True),
        "category_summary_json": json.dumps(list(packet.get("category_summary") or []), ensure_ascii=True),
    }
    with _SPINE_LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO packet_meta (
                    packet_id, project_key, session_context_key, tool_name, intent_family, task_plane,
                    invalidated, fresh_until_ts, updated_ts, effectiveness_score, read_count, usage_count,
                    emit_count, deliver_count, source_summary_json, category_summary_json
                ) VALUES (
                    :packet_id, :project_key, :session_context_key, :tool_name, :intent_family, :task_plane,
                    :invalidated, :fresh_until_ts, :updated_ts, :effectiveness_score, :read_count, :usage_count,
                    :emit_count, :deliver_count, :source_summary_json, :category_summary_json
                )
                ON CONFLICT(packet_id) DO UPDATE SET
                    project_key=excluded.project_key,
                    session_context_key=excluded.session_context_key,
                    tool_name=excluded.tool_name,
                    intent_family=excluded.intent_family,
                    task_plane=excluded.task_plane,
                    invalidated=excluded.invalidated,
                    fresh_until_ts=excluded.fresh_until_ts,
                    updated_ts=excluded.updated_ts,
                    effectiveness_score=excluded.effectiveness_score,
                    read_count=excluded.read_count,
                    usage_count=excluded.usage_count,
                    emit_count=excluded.emit_count,
                    deliver_count=excluded.deliver_count,
                    source_summary_json=excluded.source_summary_json,
                    category_summary_json=excluded.category_summary_json
                """,
                row,
            )
            conn.commit()
        finally:
            conn.close()


def set_exact_alias(exact_key: str, packet_id: str) -> None:
    key = str(exact_key or "").strip()
    pid = str(packet_id or "").strip()
    if not key or not pid:
        return
    with _SPINE_LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO exact_alias (exact_key, packet_id, updated_ts)
                VALUES (?, ?, ?)
                ON CONFLICT(exact_key) DO UPDATE SET
                    packet_id=excluded.packet_id,
                    updated_ts=excluded.updated_ts
                """,
                (key, pid, time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def resolve_exact_packet_id(exact_key: str, *, now_ts: Optional[float] = None) -> str:
    key = str(exact_key or "").strip()
    if not key:
        return ""
    now_value = _to_float(now_ts, time.time())
    with _SPINE_LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT pm.packet_id
                FROM exact_alias ea
                JOIN packet_meta pm ON pm.packet_id = ea.packet_id
                WHERE ea.exact_key = ?
                  AND pm.invalidated = 0
                  AND pm.fresh_until_ts >= ?
                LIMIT 1
                """,
                (key, now_value),
            ).fetchone()
            return str(row["packet_id"]) if row else ""
        finally:
            conn.close()


def relaxed_candidates(
    *,
    project_key: str,
    tool_name: str = "",
    intent_family: str = "",
    task_plane: str = "",
    now_ts: Optional[float] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    project = str(project_key or "").strip()
    if not project:
        return []
    now_value = _to_float(now_ts, time.time())
    row_limit = max(1, min(60, _to_int(limit, 10)))
    with _SPINE_LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT packet_id, tool_name, intent_family, task_plane, updated_ts, fresh_until_ts,
                       effectiveness_score, read_count, usage_count, emit_count, deliver_count,
                       project_key, invalidated,
                       source_summary_json, category_summary_json
                FROM packet_meta
                WHERE project_key = ?
                  AND invalidated = 0
                  AND fresh_until_ts >= ?
                ORDER BY updated_ts DESC
                LIMIT ?
                """,
                (project, now_value, row_limit),
            ).fetchall()
        finally:
            conn.close()

    out: List[Dict[str, Any]] = []
    req_tool = str(tool_name or "").strip()
    req_intent = str(intent_family or "").strip()
    req_plane = str(task_plane or "").strip()
    for row in rows:
        row_tool = str(row["tool_name"] or "")
        row_intent = str(row["intent_family"] or "")
        row_plane = str(row["task_plane"] or "")
        if req_tool and row_tool not in {req_tool, "*"}:
            continue
        if req_intent and row_intent and row_intent != req_intent:
            continue
        if req_plane and row_plane and row_plane != req_plane:
            continue
        try:
            source_summary = json.loads(str(row["source_summary_json"] or "[]"))
        except Exception:
            source_summary = []
        try:
            category_summary = json.loads(str(row["category_summary_json"] or "[]"))
        except Exception:
            category_summary = []
        out.append(
            {
                "packet_id": str(row["packet_id"] or ""),
                "project_key": str(row["project_key"] or ""),
                "invalidated": bool(_to_int(row["invalidated"], 0)),
                "tool_name": row_tool,
                "intent_family": row_intent,
                "task_plane": row_plane,
                "updated_ts": _to_float(row["updated_ts"], 0.0),
                "fresh_until_ts": _to_float(row["fresh_until_ts"], 0.0),
                "effectiveness_score": max(0.0, min(1.0, _to_float(row["effectiveness_score"], 0.5))),
                "read_count": max(0, _to_int(row["read_count"], 0)),
                "usage_count": max(0, _to_int(row["usage_count"], 0)),
                "emit_count": max(0, _to_int(row["emit_count"], 0)),
                "deliver_count": max(0, _to_int(row["deliver_count"], 0)),
                "source_summary": [str(x) for x in list(source_summary or [])][:20],
                "category_summary": [str(x) for x in list(category_summary or [])][:20],
            }
        )
    return out
