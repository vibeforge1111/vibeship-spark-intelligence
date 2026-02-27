"""SQLite memory spine for cognitive insights.

Modes:
- Shadow lane (legacy): JSON canonical + optional SQLite dual-write.
- Alpha lane: SQLite canonical + optional JSON mirror for compatibility.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional


def _db_path() -> Path:
    raw = str(os.getenv("SPARK_MEMORY_SPINE_DB", "")).strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".spark" / "spark_memory_spine.db"


def db_path() -> Path:
    """Public helper for read-only tools that need the spine file location."""
    return _db_path()


def dual_write_enabled() -> bool:
    raw = os.getenv("SPARK_MEMORY_SPINE_DUAL_WRITE")
    if raw is None and os.getenv("PYTEST_CURRENT_TEST"):
        return False
    val = str(raw if raw is not None else "1").strip().lower()
    return val in {"1", "true", "yes", "on"}


def canonical_enabled() -> bool:
    raw = os.getenv("SPARK_MEMORY_SPINE_CANONICAL")
    if raw is None and os.getenv("PYTEST_CURRENT_TEST"):
        return False
    val = str(raw if raw is not None else "1").strip().lower()
    return val in {"1", "true", "yes", "on"}


def read_fallback_enabled() -> bool:
    raw = str(os.getenv("SPARK_MEMORY_SPINE_READ_FALLBACK", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def json_mirror_enabled() -> bool:
    raw = os.getenv("SPARK_MEMORY_SPINE_JSON_MIRROR")
    val = str(raw if raw is not None else "1").strip().lower()
    return val in {"1", "true", "yes", "on"}


def runtime_json_fallback_enabled() -> bool:
    # Runtime fallback is retired: SQLite is the only runtime source.
    return False


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


def _write_json_mirror(path: Optional[Path], snapshot: Dict[str, Dict[str, Any]]) -> Optional[str]:
    if path is None:
        return None
    target = path.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(f".json.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    for _ in range(5):
        try:
            tmp.replace(target)
            break
        except Exception:
            time.sleep(0.05)
    try:
        if tmp.exists():
            tmp.unlink()
    except Exception:
        pass
    return str(target)


def write_cognitive_insights_snapshot(
    snapshot: Dict[str, Dict[str, Any]],
    *,
    force: bool = False,
    mirror_json_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Persist full cognitive insight snapshot into SQLite with optional JSON mirror."""
    if not force and not dual_write_enabled() and not canonical_enabled():
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

    out = {"ok": True, "written": int(len(rows)), "db_path": str(_db_path())}
    if json_mirror_enabled():
        try:
            mirrored = _write_json_mirror(mirror_json_path, rows)
            if mirrored:
                out["json_mirror_path"] = mirrored
        except Exception:
            # Mirror is compatibility-only; canonical SQLite write should still succeed.
            out["json_mirror_error"] = "write_failed"
    return out


def dual_write_cognitive_insights(snapshot: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Legacy wrapper used by shadow lane code."""
    return write_cognitive_insights_snapshot(snapshot, force=False)


def load_cognitive_insights_snapshot(*, force: bool = False) -> Dict[str, Dict[str, Any]]:
    """Load latest full cognitive snapshot from SQLite spine metadata."""
    if not force and not read_fallback_enabled() and not canonical_enabled():
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


def load_cognitive_insights_snapshot_canonical() -> Dict[str, Dict[str, Any]]:
    """Canonical read path for SQLite-first mode."""
    return load_cognitive_insights_snapshot(force=True)


def load_cognitive_insights_runtime_snapshot(
    *,
    json_fallback_path: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    """Read cognitive snapshot for runtime consumers (SQLite-only)."""
    del json_fallback_path
    try:
        snap = load_cognitive_insights_snapshot(force=True)
        if isinstance(snap, dict) and snap:
            return snap
    except Exception:
        pass
    try:
        snap = load_cognitive_insights_snapshot(force=False)
        if isinstance(snap, dict) and snap:
            return snap
    except Exception:
        pass
    return {}


def runtime_snapshot_mtime(
    *,
    json_fallback_path: Optional[Path] = None,
) -> Optional[float]:
    """Best-effort mtime for active runtime cognitive snapshot source."""
    del json_fallback_path
    db = _db_path()
    if db.exists():
        try:
            return float(db.stat().st_mtime)
        except Exception:
            pass
    return None
