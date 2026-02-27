"""
EIDOS Validation: Every Step Must Be Verifiable

A step without validation is not a learning unit.

Validation Methods:
- test:passed/failed - Automated test result
- build:success/failed - Compile/build result
- lint:clean/errors - Linter result
- output:expected/unexpected - Output matched prediction
- error:resolved/persists - Error state change
- manual:checked/approved - Human verification
- deferred:reason - Validation postponed

Deferred Validation Reasons:
- deferred:needs_deploy (24h max)
- deferred:needs_data (48h max)
- deferred:needs_human (72h max)
- deferred:async_process (4h max)
"""

import os
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import Step, Evaluation


class ValidationMethod(Enum):
    """Standard validation method codes."""
    # Test results
    TEST_PASSED = "test:passed"
    TEST_FAILED = "test:failed"

    # Build results
    BUILD_SUCCESS = "build:success"
    BUILD_FAILED = "build:failed"

    # Lint results
    LINT_CLEAN = "lint:clean"
    LINT_ERRORS = "lint:errors"

    # Output comparison
    OUTPUT_EXPECTED = "output:expected"
    OUTPUT_UNEXPECTED = "output:unexpected"

    # Error state
    ERROR_RESOLVED = "error:resolved"
    ERROR_PERSISTS = "error:persists"

    # Manual verification
    MANUAL_CHECKED = "manual:checked"
    MANUAL_APPROVED = "manual:approved"

    # Deferred (with reason)
    DEFERRED = "deferred"


# Maximum deferral times in seconds
DEFERRAL_LIMITS = {
    "needs_deploy": 24 * 3600,      # 24 hours
    "needs_data": 48 * 3600,        # 48 hours
    "needs_human": 72 * 3600,       # 72 hours
    "async_process": 4 * 3600,      # 4 hours
}

# Default max deferral
DEFAULT_MAX_DEFERRAL = 24 * 3600  # 24 hours


def _sqlite_timeout_s() -> float:
    try:
        return max(0.5, float(os.getenv("SPARK_SQLITE_TIMEOUT_S", "5.0") or 5.0))
    except Exception:
        return 5.0


@dataclass
class ValidationResult:
    """Result of validating a step."""
    valid: bool
    method: str = ""
    deferred: bool = False
    error: str = ""
    deferral_reason: str = ""
    max_wait_seconds: int = 0


@dataclass
class DeferredValidation:
    """A validation that was deferred for later."""
    step_id: str
    reason: str
    deferred_at: float
    max_wait_seconds: int
    reminder_sent: bool = False
    resolved: bool = False
    resolved_at: Optional[float] = None
    resolution_method: str = ""


def validate_step(step: Step) -> ValidationResult:
    """
    Validate that a step has proper validation.

    Every step MUST have validation to count as a learning unit.
    """
    # Case 1: Explicit validation
    if step.validated and step.validation_method:
        return ValidationResult(
            valid=True,
            method=step.validation_method
        )

    # Case 2: Deferred with reason
    if step.validation_method and step.validation_method.startswith('deferred:'):
        reason = step.validation_method.split(':', 1)[1] if ':' in step.validation_method else ""
        if reason.strip():
            max_wait = DEFERRAL_LIMITS.get(reason.strip(), DEFAULT_MAX_DEFERRAL)
            return ValidationResult(
                valid=True,
                method=step.validation_method,
                deferred=True,
                deferral_reason=reason.strip(),
                max_wait_seconds=max_wait
            )
        else:
            return ValidationResult(
                valid=False,
                error="Deferred validation requires reason"
            )

    # Case 3: No validation = invalid step
    return ValidationResult(
        valid=False,
        error="Step must be validated or explicitly deferred with reason"
    )


def parse_validation_method(method: str) -> Tuple[str, str]:
    """Parse validation method into (code, detail)."""
    if ':' in method:
        parts = method.split(':', 1)
        return parts[0], parts[1]
    return method, ""


def is_positive_validation(method: str) -> bool:
    """Check if validation method indicates success."""
    positive_codes = {
        'test:passed', 'build:success', 'lint:clean',
        'output:expected', 'error:resolved',
        'manual:checked', 'manual:approved'
    }
    return method.lower() in positive_codes


def is_negative_validation(method: str) -> bool:
    """Check if validation method indicates failure."""
    negative_codes = {
        'test:failed', 'build:failed', 'lint:errors',
        'output:unexpected', 'error:persists'
    }
    return method.lower() in negative_codes


class DeferredValidationTracker:
    """
    Track and manage deferred validations.

    Stores deferred validations and alerts when they become overdue.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            spark_dir = Path.home() / ".spark"
            spark_dir.mkdir(exist_ok=True)
            db_path = str(spark_dir / "eidos.db")

        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize deferred validations table."""
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS deferred_validations (
                    step_id TEXT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    deferred_at REAL NOT NULL,
                    max_wait_seconds INTEGER NOT NULL,
                    reminder_sent INTEGER DEFAULT 0,
                    resolved INTEGER DEFAULT 0,
                    resolved_at REAL,
                    resolution_method TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_deferred_unresolved
                    ON deferred_validations(resolved) WHERE resolved = 0;

                -- View for overdue validations
                CREATE VIEW IF NOT EXISTS overdue_validations AS
                SELECT
                    step_id,
                    reason,
                    deferred_at,
                    (strftime('%s', 'now') - deferred_at) as seconds_waiting,
                    max_wait_seconds
                FROM deferred_validations
                WHERE resolved = 0
                AND (strftime('%s', 'now') - deferred_at) > max_wait_seconds;
            """)
            conn.commit()

    def defer(self, step: Step, reason: str) -> DeferredValidation:
        """Record a deferred validation."""
        max_wait = DEFERRAL_LIMITS.get(reason, DEFAULT_MAX_DEFERRAL)
        now = time.time()

        deferred = DeferredValidation(
            step_id=step.step_id,
            reason=reason,
            deferred_at=now,
            max_wait_seconds=max_wait
        )

        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO deferred_validations
                (step_id, reason, deferred_at, max_wait_seconds)
                VALUES (?, ?, ?, ?)
            """, (step.step_id, reason, now, max_wait))
            conn.commit()

        return deferred

    def resolve(
        self,
        step_id: str,
        resolution_method: str
    ) -> bool:
        """Mark a deferred validation as resolved."""
        now = time.time()
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            cursor = conn.execute("""
                UPDATE deferred_validations
                SET resolved = 1,
                    resolved_at = ?,
                    resolution_method = ?
                WHERE step_id = ?
            """, (now, resolution_method, step_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_overdue(self) -> List[DeferredValidation]:
        """Get all overdue deferred validations."""
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM deferred_validations
                WHERE resolved = 0
                AND (strftime('%s', 'now') - deferred_at) > max_wait_seconds
            """).fetchall()

            return [self._row_to_deferred(row) for row in rows]

    def get_pending(self) -> List[DeferredValidation]:
        """Get all pending (not yet overdue) deferred validations."""
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM deferred_validations
                WHERE resolved = 0
                AND (strftime('%s', 'now') - deferred_at) <= max_wait_seconds
            """).fetchall()

            return [self._row_to_deferred(row) for row in rows]

    def mark_reminder_sent(self, step_id: str):
        """Mark that a reminder was sent for this deferral."""
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            conn.execute("""
                UPDATE deferred_validations
                SET reminder_sent = 1
                WHERE step_id = ?
            """, (step_id,))
            conn.commit()

    def _row_to_deferred(self, row: sqlite3.Row) -> DeferredValidation:
        """Convert database row to DeferredValidation."""
        return DeferredValidation(
            step_id=row["step_id"],
            reason=row["reason"],
            deferred_at=row["deferred_at"],
            max_wait_seconds=row["max_wait_seconds"],
            reminder_sent=bool(row["reminder_sent"]),
            resolved=bool(row["resolved"]),
            resolved_at=row["resolved_at"],
            resolution_method=row["resolution_method"] or ""
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get deferred validation statistics."""
        with sqlite3.connect(self.db_path, timeout=_sqlite_timeout_s()) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM deferred_validations"
            ).fetchone()[0]

            resolved = conn.execute(
                "SELECT COUNT(*) FROM deferred_validations WHERE resolved = 1"
            ).fetchone()[0]

            pending = conn.execute("""
                SELECT COUNT(*) FROM deferred_validations
                WHERE resolved = 0
                AND (strftime('%s', 'now') - deferred_at) <= max_wait_seconds
            """).fetchone()[0]

            overdue = conn.execute("""
                SELECT COUNT(*) FROM deferred_validations
                WHERE resolved = 0
                AND (strftime('%s', 'now') - deferred_at) > max_wait_seconds
            """).fetchone()[0]

            by_reason = {}
            for row in conn.execute("""
                SELECT reason, COUNT(*), SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END)
                FROM deferred_validations
                GROUP BY reason
            """):
                by_reason[row[0]] = {"total": row[1], "resolved": row[2]}

            return {
                "total": total,
                "resolved": resolved,
                "pending": pending,
                "overdue": overdue,
                "by_reason": by_reason
            }


# Singleton instance
_tracker: Optional[DeferredValidationTracker] = None


def get_deferred_tracker(db_path: Optional[str] = None) -> DeferredValidationTracker:
    """Get the singleton deferred validation tracker."""
    global _tracker
    if _tracker is None or (db_path and _tracker.db_path != db_path):
        _tracker = DeferredValidationTracker(db_path)
    return _tracker

