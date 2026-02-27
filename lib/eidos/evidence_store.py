"""
EIDOS Evidence Store: Layer 0 - Ephemeral Evidence

Tool logs are NOT memory. They are temporary proof artifacts.

Purpose:
- Provide audit trail for recent actions
- Enable debugging of "what exactly happened"
- Support validation of steps
- Auto-expire to prevent bloat

Retention Policy:
- Standard tool output: 72 hours
- Build/test results: 7 days
- Deploy artifacts: 30 days
- Security-related: 90 days
- User-flagged: Permanent
"""

import hashlib
import json
import os
import re
import sqlite3
import time
import zlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class EvidenceType(Enum):
    """Types of evidence that can be stored."""
    TOOL_OUTPUT = "tool_output"       # stdout/stderr from tool (72h)
    DIFF = "diff"                     # File changes made (7d)
    TEST_RESULT = "test_result"       # Test pass/fail details (7d)
    BUILD_LOG = "build_log"           # Compile/build output (7d)
    ERROR_TRACE = "error_trace"       # Stack traces, errors (7d)
    DEPLOY_ARTIFACT = "deploy_artifact"  # Deployment logs (30d)
    SECURITY_EVENT = "security_event"    # Auth, access, secrets (90d)
    USER_FLAGGED = "user_flagged"     # Explicit importance (permanent)


# Default retention in seconds
RETENTION_POLICY = {
    EvidenceType.TOOL_OUTPUT: 72 * 3600,      # 72 hours
    EvidenceType.DIFF: 7 * 24 * 3600,         # 7 days
    EvidenceType.TEST_RESULT: 7 * 24 * 3600,  # 7 days
    EvidenceType.BUILD_LOG: 7 * 24 * 3600,    # 7 days
    EvidenceType.ERROR_TRACE: 7 * 24 * 3600,  # 7 days
    EvidenceType.DEPLOY_ARTIFACT: 30 * 24 * 3600,  # 30 days
    EvidenceType.SECURITY_EVENT: 90 * 24 * 3600,   # 90 days
    EvidenceType.USER_FLAGGED: None,          # Permanent
}


def _safe_sql_identifier(name: str) -> Optional[str]:
    ident = str(name or "").strip()
    if not ident or _SQL_IDENTIFIER_RE.fullmatch(ident) is None:
        return None
    return ident


def _sqlite_timeout_s() -> float:
    try:
        return max(0.5, float(os.getenv("SPARK_SQLITE_TIMEOUT_S", "5.0") or 5.0))
    except Exception:
        return 5.0


@dataclass
class Evidence:
    """Evidence artifact linked to a step."""
    evidence_id: str
    step_id: str
    type: EvidenceType
    trace_id: Optional[str] = None
    tool_name: str = ""

    # Content
    content: str = ""
    content_hash: str = ""
    byte_size: int = 0
    compressed: bool = False

    # Metadata
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None

    # Lifecycle
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    retention_reason: str = ""

    def __post_init__(self):
        if not self.evidence_id:
            self.evidence_id = self._generate_id()
        if not self.content_hash and self.content:
            self.content_hash = hashlib.md5(self.content.encode()).hexdigest()
        if self.expires_at is None:
            retention = RETENTION_POLICY.get(self.type)
            if retention:
                self.expires_at = self.created_at + retention

    def _generate_id(self) -> str:
        key = f"{self.step_id}:{self.type.value}:{self.created_at}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "step_id": self.step_id,
            "trace_id": self.trace_id,
            "type": self.type.value,
            "tool_name": self.tool_name,
            "content": self.content,
            "content_hash": self.content_hash,
            "byte_size": self.byte_size,
            "compressed": self.compressed,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "retention_reason": self.retention_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Evidence":
        return cls(
            evidence_id=data["evidence_id"],
            step_id=data["step_id"],
            type=EvidenceType(data["type"]),
            trace_id=data.get("trace_id"),
            tool_name=data.get("tool_name", ""),
            content=data.get("content", ""),
            content_hash=data.get("content_hash", ""),
            byte_size=data.get("byte_size", 0),
            compressed=data.get("compressed", False),
            exit_code=data.get("exit_code"),
            duration_ms=data.get("duration_ms"),
            created_at=data.get("created_at", time.time()),
            expires_at=data.get("expires_at"),
            retention_reason=data.get("retention_reason", ""),
        )


class EvidenceStore:
    """
    SQLite-based ephemeral evidence storage.

    Evidence is linked to steps but stored separately to keep
    the steps table lean while maintaining full audit trail.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            spark_dir = Path.home() / ".spark"
            spark_dir.mkdir(exist_ok=True)
            db_path = str(spark_dir / "evidence.db")

        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            # First, create table WITHOUT trace_id index (for compatibility with old DBs)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    step_id TEXT,
                    trace_id TEXT,

                    type TEXT NOT NULL,
                    tool_name TEXT,

                    content TEXT,
                    content_hash TEXT,
                    byte_size INTEGER,
                    compressed INTEGER DEFAULT 0,

                    exit_code INTEGER,
                    duration_ms INTEGER,

                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    expires_at REAL,
                    retention_reason TEXT
                )
            """)

            # Migration: add trace_id column if missing (for old databases)
            try:
                if not self._column_exists(conn, "evidence", "trace_id"):
                    conn.execute("ALTER TABLE evidence ADD COLUMN trace_id TEXT")
            except Exception:
                pass

            # Now create all indexes (trace_id column guaranteed to exist)
            conn.executescript("""
                CREATE INDEX IF NOT EXISTS idx_evidence_step ON evidence(step_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_trace ON evidence(trace_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_expires ON evidence(expires_at)
                    WHERE expires_at IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(type);
                CREATE INDEX IF NOT EXISTS idx_evidence_hash ON evidence(content_hash);
            """)
            conn.commit()

    def _column_exists(self, conn: sqlite3.Connection, table: str, column: str) -> bool:
        try:
            safe_table = _safe_sql_identifier(table)
            safe_column = _safe_sql_identifier(column)
            if not safe_table or not safe_column:
                return False
            rows = conn.execute(f'PRAGMA table_info("{safe_table}")').fetchall()
            return any(r[1] == safe_column for r in rows)
        except Exception:
            return False

    def _infer_trace_id_from_step(self, step_id: str) -> Optional[str]:
        if not step_id:
            return None
        try:
            from .store import get_store
            store = get_store()
            with sqlite3.connect(store.db_path, timeout=_sqlite_timeout_s()) as conn:
                row = conn.execute(
                    "SELECT trace_id FROM steps WHERE step_id = ?",
                    (step_id,),
                ).fetchone()
                if row and row[0]:
                    return str(row[0])
        except Exception:
            return None
        return None

    def save(self, evidence: Evidence, compress_threshold: int = 10000) -> str:
        """
        Save evidence to the store.

        Args:
            evidence: Evidence object to save
            compress_threshold: Compress content if larger than this (bytes)
        """
        if not evidence.trace_id and evidence.step_id:
            evidence.trace_id = self._infer_trace_id_from_step(evidence.step_id)

        content = evidence.content
        compressed = False
        byte_size = len(content.encode('utf-8')) if content else 0

        # Compress large content
        if byte_size > compress_threshold:
            compressed_bytes = zlib.compress(content.encode('utf-8'))
            content = compressed_bytes.hex()
            compressed = True
            byte_size = len(compressed_bytes)

        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO evidence (
                    evidence_id, step_id, trace_id, type, tool_name,
                    content, content_hash, byte_size, compressed,
                    exit_code, duration_ms,
                    created_at, expires_at, retention_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                evidence.evidence_id,
                evidence.step_id,
                evidence.trace_id,
                evidence.type.value,
                evidence.tool_name,
                content,
                evidence.content_hash,
                byte_size,
                1 if compressed else 0,
                evidence.exit_code,
                evidence.duration_ms,
                evidence.created_at,
                evidence.expires_at,
                evidence.retention_reason,
            ))
            conn.commit()

        return evidence.evidence_id

    def backfill_trace_ids(self, steps_db_path: Optional[str] = None) -> Dict[str, int]:
        """
        Backfill missing trace_id values on evidence using step trace_ids.

        Returns counts for observability.
        """
        step_map: Dict[str, str] = {}
        if steps_db_path:
            try:
                with sqlite3.connect(steps_db_path, timeout=_sqlite_timeout_s()) as conn:
                    for row in conn.execute(
                        "SELECT step_id, trace_id FROM steps WHERE trace_id IS NOT NULL AND trace_id != ''"
                    ):
                        step_id, trace_id = row[0], row[1]
                        if step_id and trace_id and step_id not in step_map:
                            step_map[step_id] = trace_id
            except Exception:
                pass

        updated = 0
        missing = 0
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            rows = conn.execute(
                "SELECT evidence_id, step_id FROM evidence WHERE trace_id IS NULL OR trace_id = ''"
            ).fetchall()
            missing = len(rows)
            for evidence_id, step_id in rows:
                trace_id = step_map.get(step_id) if step_id else None
                if not trace_id:
                    key = f"{evidence_id}|{step_id or ''}"
                    trace_id = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
                conn.execute(
                    "UPDATE evidence SET trace_id = ? WHERE evidence_id = ?",
                    (trace_id, evidence_id),
                )
                updated += 1
            conn.commit()

        return {
            "evidence_missing": missing,
            "evidence_updated": updated,
        }

    def get(self, evidence_id: str) -> Optional[Evidence]:
        """Get evidence by ID."""
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?",
                (evidence_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_evidence(row)

    def get_for_step(self, step_id: str) -> List[Evidence]:
        """Get all evidence for a step."""
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM evidence WHERE step_id = ? ORDER BY created_at",
                (step_id,)
            ).fetchall()

            return [self._row_to_evidence(row) for row in rows]

    def get_by_type(
        self,
        etype: EvidenceType,
        limit: int = 50
    ) -> List[Evidence]:
        """Get recent evidence of a specific type."""
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM evidence
                   WHERE type = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (etype.value, limit)
            ).fetchall()

            return [self._row_to_evidence(row) for row in rows]

    def _row_to_evidence(self, row: sqlite3.Row) -> Evidence:
        """Convert database row to Evidence object."""
        content = row["content"] or ""
        compressed = bool(row["compressed"])

        # Decompress if needed
        if compressed and content:
            try:
                compressed_bytes = bytes.fromhex(content)
                content = zlib.decompress(compressed_bytes).decode('utf-8')
            except Exception:
                pass  # Keep as-is if decompression fails

        return Evidence(
            evidence_id=row["evidence_id"],
            step_id=row["step_id"],
            type=EvidenceType(row["type"]),
            trace_id=row["trace_id"] if "trace_id" in row.keys() else None,
            tool_name=row["tool_name"] or "",
            content=content,
            content_hash=row["content_hash"] or "",
            byte_size=row["byte_size"] or 0,
            compressed=compressed,
            exit_code=row["exit_code"],
            duration_ms=row["duration_ms"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            retention_reason=row["retention_reason"] or "",
        )

    def flag_permanent(self, evidence_id: str, reason: str = "user_flagged"):
        """Mark evidence as permanent (no expiry)."""
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            conn.execute("""
                UPDATE evidence
                SET expires_at = NULL,
                    retention_reason = ?
                WHERE evidence_id = ?
            """, (reason, evidence_id))
            conn.commit()

    def extend_retention(
        self,
        evidence_id: str,
        additional_seconds: int,
        reason: str = ""
    ):
        """Extend retention period for evidence."""
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            conn.execute("""
                UPDATE evidence
                SET expires_at = COALESCE(expires_at, strftime('%s', 'now')) + ?,
                    retention_reason = COALESCE(retention_reason || '; ', '') || ?
                WHERE evidence_id = ?
            """, (additional_seconds, reason, evidence_id))
            conn.commit()

    def cleanup_expired(self) -> int:
        """Remove expired evidence. Returns count of deleted items."""
        now = time.time()
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            cursor = conn.execute("""
                DELETE FROM evidence
                WHERE expires_at IS NOT NULL
                AND expires_at < ?
            """, (now,))
            conn.commit()
            return cursor.rowcount

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            total = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
            total_bytes = conn.execute(
                "SELECT COALESCE(SUM(byte_size), 0) FROM evidence"
            ).fetchone()[0]

            by_type = {}
            for row in conn.execute(
                "SELECT type, COUNT(*), SUM(byte_size) FROM evidence GROUP BY type"
            ):
                by_type[row[0]] = {"count": row[1], "bytes": row[2] or 0}

            expiring_soon = conn.execute("""
                SELECT COUNT(*) FROM evidence
                WHERE expires_at IS NOT NULL
                AND expires_at < ?
            """, (time.time() + 24 * 3600,)).fetchone()[0]

            permanent = conn.execute(
                "SELECT COUNT(*) FROM evidence WHERE expires_at IS NULL"
            ).fetchone()[0]

            return {
                "total_items": total,
                "total_bytes": total_bytes,
                "by_type": by_type,
                "expiring_in_24h": expiring_soon,
                "permanent": permanent,
                "db_path": self.db_path,
            }


# Convenience function to create evidence from tool output
def create_evidence_from_tool(
    step_id: str,
    tool_name: str,
    output: str,
    exit_code: Optional[int] = None,
    duration_ms: Optional[int] = None,
    evidence_type: Optional[EvidenceType] = None,
    trace_id: Optional[str] = None,
) -> Evidence:
    """
    Create evidence from tool output.

    Automatically determines evidence type based on tool name if not specified.
    """
    # Auto-detect type
    if evidence_type is None:
        tool_lower = tool_name.lower()
        if 'test' in tool_lower:
            evidence_type = EvidenceType.TEST_RESULT
        elif 'build' in tool_lower or 'compile' in tool_lower:
            evidence_type = EvidenceType.BUILD_LOG
        elif 'deploy' in tool_lower:
            evidence_type = EvidenceType.DEPLOY_ARTIFACT
        elif 'security' in tool_lower or 'auth' in tool_lower:
            evidence_type = EvidenceType.SECURITY_EVENT
        elif tool_name in ('Edit', 'Write'):
            evidence_type = EvidenceType.DIFF
        elif 'error' in output.lower() or 'traceback' in output.lower():
            evidence_type = EvidenceType.ERROR_TRACE
        else:
            evidence_type = EvidenceType.TOOL_OUTPUT

    return Evidence(
        evidence_id="",
        step_id=step_id,
        trace_id=trace_id,
        type=evidence_type,
        tool_name=tool_name,
        content=output,
        exit_code=exit_code,
        duration_ms=duration_ms,
    )


# Singleton instance
_evidence_store: Optional[EvidenceStore] = None


def get_evidence_store(db_path: Optional[str] = None) -> EvidenceStore:
    """Get the singleton evidence store instance."""
    global _evidence_store
    if _evidence_store is None or (db_path and _evidence_store.db_path != db_path):
        _evidence_store = EvidenceStore(db_path)
    return _evidence_store

