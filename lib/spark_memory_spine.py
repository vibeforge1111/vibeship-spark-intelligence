"""SQLite memory spine (shadow/dual-write lane).

Current scope:
- Dual-write cognitive insights into SQLite while JSON remains canonical.
- Optional read fallback from SQLite when JSON is unavailable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict


def _db_path() -> Path:
    raw = str(os.getenv("SPARK_MEMORY_SPINE_DB", "")).strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".spark" / "spark_memory_spine.db"


def dual_write_enabled() -> bool:
    raw = os.getenv("SPARK_MEMORY_SPINE_DUAL_WRITE")
    if raw is None and os.getenv("PYTEST_CURRENT_TEST"):
        return False
    val = str(raw if raw is not None else "1").strip().lower()
    return val in {"1", "true", "yes", "on"}


def read_fallback_enabled() -> bool:
    raw = str(os.getenv("SPARK_MEMORY_SPINE_READ_FALLBACK", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cognitive_insights (
            insight_key TEXT PRIMARY KEY,
            category TEXT,
            insight TEXT,
            confidence REAL,
            reliability REAL,
            source TEXT,
            action_domain TEXT,
            updated_at REAL NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cognitive_insights_meta (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            updated_at REAL NOT NULL,
            insight_count INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )


def dual_write_cognitive_insights(snapshot: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Persist full cognitive insight snapshot into SQLite spine."""
    if not dual_write_enabled():
        return {"ok": False, "skipped": True, "reason": "dual_write_disabled"}

    rows = snapshot if isinstance(snapshot, dict) else {}
    now = float(time.time())
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute("BEGIN")
        conn.execute("DELETE FROM cognitive_insights")
        for key, payload in rows.items():
            row = payload if isinstance(payload, dict) else {}
            conn.execute(
                """
                INSERT INTO cognitive_insights (
                    insight_key, category, insight, confidence, reliability, source,
                    action_domain, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(key),
                    str(row.get("category") or ""),
                    str(row.get("insight") or ""),
                    float(row.get("confidence") or 0.0),
                    float(row.get("reliability") or 0.0),
                    str(row.get("source") or ""),
                    str(row.get("action_domain") or ""),
                    now,
                    json.dumps(row, ensure_ascii=True),
                ),
            )
        conn.execute(
            """
            INSERT INTO cognitive_insights_meta (id, updated_at, insight_count, payload_json)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                updated_at = excluded.updated_at,
                insight_count = excluded.insight_count,
                payload_json = excluded.payload_json
            """,
            (now, int(len(rows)), json.dumps(rows, ensure_ascii=True)),
        )
        conn.commit()

    return {"ok": True, "written": int(len(rows)), "db_path": str(_db_path())}


def load_cognitive_insights_snapshot() -> Dict[str, Dict[str, Any]]:
    """Load latest full cognitive snapshot from SQLite spine metadata."""
    if not read_fallback_enabled():
        return {}
    path = _db_path()
    if not path.exists():
        return {}

    try:
        with _connect() as conn:
            _ensure_schema(conn)
            row = conn.execute(
                "SELECT payload_json FROM cognitive_insights_meta WHERE id = 1"
            ).fetchone()
            if not row:
                return {}
            payload = row[0]
    except Exception:
        return {}

    try:
        data = json.loads(str(payload or "{}"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
