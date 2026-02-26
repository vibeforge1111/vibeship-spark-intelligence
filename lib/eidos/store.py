"""
EIDOS Store: SQLite Persistence Layer

The canonical memory - simple, inspectable, debuggable.

Tables:
- episodes: Bounded learning units
- steps: Decision packets (the core intelligence unit)
- distillations: Extracted rules (where intelligence lives)
- policies: Operating constraints

This is NOT where tool logs go. Tool logs are ephemeral evidence.
"""

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..distillation_transformer import transform_for_advisory
from .models import (
    Episode, Step, Distillation, Policy,
    Budget, Phase, Outcome, Evaluation, DistillationType, ActionType
)

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _normalize_distillation_statement(text: str) -> str:
    """Normalize statements so semantically identical distillations collapse."""
    s = (text or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    # Canonicalize budget percentage variants of the same heuristic.
    s = re.sub(
        r"when budget is \d+% used without progress",
        "when budget is <pct> used without progress",
        s,
    )
    return s


def _merge_unique_str(items_a: List[str], items_b: List[str]) -> List[str]:
    out: List[str] = []
    for item in (items_a or []) + (items_b or []):
        v = str(item or "").strip()
        if not v:
            continue
        if v not in out:
            out.append(v)
    return out


def _safe_sql_identifier(name: str) -> Optional[str]:
    ident = str(name or "").strip()
    if not ident or _SQL_IDENTIFIER_RE.fullmatch(ident) is None:
        return None
    return ident


class EidosStore:
    """
    SQLite-based persistence for EIDOS intelligence primitives.

    Design principles:
    - Source of truth for all durable memory
    - Human-inspectable (just open the SQLite file)
    - Simple schema that maps directly to models
    - Indexes optimized for retrieval patterns
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the store.

        Args:
            db_path: Path to SQLite database. Defaults to ~/.spark/eidos.db
        """
        if db_path is None:
            spark_dir = Path.home() / ".spark"
            spark_dir.mkdir(exist_ok=True)
            db_path = str(spark_dir / "eidos.db")

        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                -- Episodes
                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    success_criteria TEXT,
                    constraints TEXT,  -- JSON
                    budget_max_steps INTEGER DEFAULT 25,
                    budget_max_time_seconds INTEGER DEFAULT 720,
                    budget_max_retries INTEGER DEFAULT 3,
                    phase TEXT DEFAULT 'explore',
                    outcome TEXT DEFAULT 'in_progress',
                    final_evaluation TEXT,
                    start_ts REAL,
                    end_ts REAL,
                    step_count INTEGER DEFAULT 0,
                    error_counts TEXT  -- JSON
                );

                -- Steps (the core intelligence unit)
                CREATE TABLE IF NOT EXISTS steps (
                    step_id TEXT PRIMARY KEY,
                    episode_id TEXT REFERENCES episodes(episode_id),
                    trace_id TEXT,

                    -- Before action
                    intent TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    alternatives TEXT,  -- JSON
                    assumptions TEXT,   -- JSON
                    prediction TEXT,
                    confidence_before REAL DEFAULT 0.5,

                    -- Action
                    action_type TEXT DEFAULT 'reasoning',
                    action_details TEXT,  -- JSON

                    -- After action
                    result TEXT,
                    evaluation TEXT DEFAULT 'unknown',
                    surprise_level REAL DEFAULT 0.0,
                    lesson TEXT,
                    confidence_after REAL DEFAULT 0.5,

                    -- Memory binding
                    retrieved_memories TEXT,  -- JSON
                    memory_cited INTEGER DEFAULT 0,
                    memory_useful INTEGER,

                    -- Validation
                    validated INTEGER DEFAULT 0,
                    validation_method TEXT,

                    created_at REAL DEFAULT (strftime('%s', 'now'))
                );

                -- Distillations (where intelligence lives)
                CREATE TABLE IF NOT EXISTS distillations (
                    distillation_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    domains TEXT,       -- JSON
                    triggers TEXT,      -- JSON
                    anti_triggers TEXT, -- JSON

                    source_steps TEXT,  -- JSON
                    validation_count INTEGER DEFAULT 0,
                    contradiction_count INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 0.5,

                    times_retrieved INTEGER DEFAULT 0,
                    times_used INTEGER DEFAULT 0,
                    times_helped INTEGER DEFAULT 0,

                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    revalidate_by REAL,
                    refined_statement TEXT,
                    advisory_quality TEXT
                );

                -- Archived distillations (reversible purge history)
                CREATE TABLE IF NOT EXISTS distillations_archive (
                    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    distillation_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    domains TEXT,
                    triggers TEXT,
                    anti_triggers TEXT,
                    source_steps TEXT,
                    validation_count INTEGER DEFAULT 0,
                    contradiction_count INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 0.5,
                    times_retrieved INTEGER DEFAULT 0,
                    times_used INTEGER DEFAULT 0,
                    times_helped INTEGER DEFAULT 0,
                    created_at REAL,
                    revalidate_by REAL,
                    refined_statement TEXT,
                    archive_reason TEXT NOT NULL,
                    advisory_quality TEXT,
                    archived_at REAL DEFAULT (strftime('%s', 'now'))
                );

                -- Policies (operating constraints)
                CREATE TABLE IF NOT EXISTS policies (
                    policy_id TEXT PRIMARY KEY,
                    statement TEXT NOT NULL,
                    scope TEXT DEFAULT 'GLOBAL',
                    priority INTEGER DEFAULT 50,
                    source TEXT DEFAULT 'INFERRED',
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                );

                -- Indexes for efficient retrieval
                CREATE INDEX IF NOT EXISTS idx_steps_episode ON steps(episode_id);
                CREATE INDEX IF NOT EXISTS idx_steps_created ON steps(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_steps_trace ON steps(trace_id);
                CREATE INDEX IF NOT EXISTS idx_distillations_type ON distillations(type);
                CREATE INDEX IF NOT EXISTS idx_distillations_confidence ON distillations(confidence DESC);
                CREATE INDEX IF NOT EXISTS idx_distillations_archive_dist_id ON distillations_archive(distillation_id);
                CREATE INDEX IF NOT EXISTS idx_policies_scope ON policies(scope);
                CREATE INDEX IF NOT EXISTS idx_policies_priority ON policies(priority DESC);
            """)
            # Lightweight migration for existing databases.
            try:
                if not self._column_exists(conn, "steps", "trace_id"):
                    conn.execute("ALTER TABLE steps ADD COLUMN trace_id TEXT")
                if not self._column_exists(conn, "distillations", "refined_statement"):
                    conn.execute("ALTER TABLE distillations ADD COLUMN refined_statement TEXT")
                if not self._column_exists(conn, "distillations", "advisory_quality"):
                    conn.execute("ALTER TABLE distillations ADD COLUMN advisory_quality TEXT")
                if not self._column_exists(conn, "distillations_archive", "refined_statement"):
                    conn.execute("ALTER TABLE distillations_archive ADD COLUMN refined_statement TEXT")
                if not self._column_exists(conn, "distillations_archive", "advisory_quality"):
                    conn.execute("ALTER TABLE distillations_archive ADD COLUMN advisory_quality TEXT")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_steps_trace ON steps(trace_id)")
            except Exception:
                pass
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

    def _fallback_trace_id(self, step: Step) -> str:
        raw = f"{step.step_id}|{step.episode_id}|{step.created_at}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _fallback_trace_id_fields(self, step_id: str, episode_id: str, created_at: float) -> str:
        raw = f"{step_id}|{episode_id}|{created_at}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    # ==================== Episode Operations ====================

    def save_episode(self, episode: Episode) -> str:
        """Save an episode to the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO episodes (
                    episode_id, goal, success_criteria, constraints,
                    budget_max_steps, budget_max_time_seconds, budget_max_retries,
                    phase, outcome, final_evaluation, start_ts, end_ts,
                    step_count, error_counts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                episode.episode_id,
                episode.goal,
                episode.success_criteria,
                json.dumps(episode.constraints),
                episode.budget.max_steps,
                episode.budget.max_time_seconds,
                episode.budget.max_retries_per_error,
                episode.phase.value,
                episode.outcome.value,
                episode.final_evaluation,
                episode.start_ts,
                episode.end_ts,
                episode.step_count,
                json.dumps(episode.error_counts)
            ))
            conn.commit()
        return episode.episode_id

    def get_episode(self, episode_id: str) -> Optional[Episode]:
        """Get an episode by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM episodes WHERE episode_id = ?",
                (episode_id,)
            ).fetchone()

            if not row:
                return None

            return Episode(
                episode_id=row["episode_id"],
                goal=row["goal"],
                success_criteria=row["success_criteria"] or "",
                constraints=json.loads(row["constraints"] or "[]"),
                budget=Budget(
                    max_steps=row["budget_max_steps"],
                    max_time_seconds=row["budget_max_time_seconds"],
                    max_retries_per_error=row["budget_max_retries"]
                ),
                phase=Phase(row["phase"]),
                outcome=Outcome(row["outcome"]),
                final_evaluation=row["final_evaluation"] or "",
                start_ts=row["start_ts"],
                end_ts=row["end_ts"],
                step_count=row["step_count"],
                error_counts=json.loads(row["error_counts"] or "{}")
            )

    def get_recent_episodes(self, limit: int = 10) -> List[Episode]:
        """Get most recent episodes."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM episodes ORDER BY start_ts DESC LIMIT ?",
                (limit,)
            ).fetchall()

            return [self._row_to_episode(row) for row in rows]

    def _row_to_episode(self, row: sqlite3.Row) -> Episode:
        """Convert a database row to Episode object."""
        return Episode(
            episode_id=row["episode_id"],
            goal=row["goal"],
            success_criteria=row["success_criteria"] or "",
            constraints=json.loads(row["constraints"] or "[]"),
            budget=Budget(
                max_steps=row["budget_max_steps"],
                max_time_seconds=row["budget_max_time_seconds"],
                max_retries_per_error=row["budget_max_retries"]
            ),
            phase=Phase(row["phase"]),
            outcome=Outcome(row["outcome"]),
            final_evaluation=row["final_evaluation"] or "",
            start_ts=row["start_ts"],
            end_ts=row["end_ts"],
            step_count=row["step_count"],
            error_counts=json.loads(row["error_counts"] or "{}")
        )

    # ==================== Step Operations ====================

    def save_step(self, step: Step) -> str:
        """Save a step to the database."""
        if not step.trace_id:
            step.trace_id = self._fallback_trace_id(step)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO steps (
                    step_id, episode_id, trace_id, intent, decision, alternatives, assumptions,
                    prediction, confidence_before, action_type, action_details,
                    result, evaluation, surprise_level, lesson, confidence_after,
                    retrieved_memories, memory_cited, memory_useful,
                    validated, validation_method, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                step.step_id,
                step.episode_id,
                step.trace_id,
                step.intent,
                step.decision,
                json.dumps(step.alternatives),
                json.dumps(step.assumptions),
                step.prediction,
                step.confidence_before,
                step.action_type.value,
                json.dumps(step.action_details),
                step.result,
                step.evaluation.value,
                step.surprise_level,
                step.lesson,
                step.confidence_after,
                json.dumps(step.retrieved_memories),
                1 if step.memory_cited else 0,
                1 if step.memory_useful else (0 if step.memory_useful is False else None),
                1 if step.validated else 0,
                step.validation_method,
                step.created_at
            ))
            conn.commit()
        return step.step_id

    def backfill_trace_ids(self, evidence_db_path: Optional[str] = None) -> Dict[str, int]:
        """
        Backfill missing trace_id values on steps using evidence where possible.

        Returns counts for observability.
        """
        evidence_map: Dict[str, str] = {}
        if evidence_db_path:
            try:
                with sqlite3.connect(evidence_db_path) as conn:
                    for row in conn.execute(
                        "SELECT step_id, trace_id FROM evidence WHERE trace_id IS NOT NULL AND trace_id != ''"
                    ):
                        step_id, trace_id = row[0], row[1]
                        if step_id and trace_id and step_id not in evidence_map:
                            evidence_map[step_id] = trace_id
            except Exception:
                pass

        updated = 0
        missing = 0
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT step_id, episode_id, created_at FROM steps WHERE trace_id IS NULL OR trace_id = ''"
            ).fetchall()
            missing = len(rows)
            for step_id, episode_id, created_at in rows:
                trace_id = evidence_map.get(step_id)
                if not trace_id:
                    trace_id = self._fallback_trace_id_fields(
                        step_id, episode_id or "", created_at or 0.0
                    )
                conn.execute(
                    "UPDATE steps SET trace_id = ? WHERE step_id = ?",
                    (trace_id, step_id),
                )
                updated += 1
            conn.commit()

        return {
            "steps_missing": missing,
            "steps_updated": updated,
        }

    def get_step(self, step_id: str) -> Optional[Step]:
        """Get a step by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM steps WHERE step_id = ?",
                (step_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_step(row)

    def get_episode_steps(self, episode_id: str) -> List[Step]:
        """Get all steps for an episode."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM steps WHERE episode_id = ? ORDER BY created_at",
                (episode_id,)
            ).fetchall()

            return [self._row_to_step(row) for row in rows]

    def get_recent_steps(self, limit: int = 50) -> List[Step]:
        """Get most recent steps across all episodes."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM steps ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()

            return [self._row_to_step(row) for row in rows]

    def _row_to_step(self, row: sqlite3.Row) -> Step:
        """Convert a database row to Step object."""
        memory_useful = row["memory_useful"]
        if memory_useful is not None:
            memory_useful = bool(memory_useful)

        trace_id = row["trace_id"] if "trace_id" in row.keys() else None

        return Step(
            step_id=row["step_id"],
            episode_id=row["episode_id"],
            trace_id=trace_id,
            intent=row["intent"],
            decision=row["decision"],
            alternatives=json.loads(row["alternatives"] or "[]"),
            assumptions=json.loads(row["assumptions"] or "[]"),
            prediction=row["prediction"] or "",
            confidence_before=row["confidence_before"],
            action_type=ActionType(row["action_type"]),
            action_details=json.loads(row["action_details"] or "{}"),
            result=row["result"] or "",
            evaluation=Evaluation(row["evaluation"]),
            surprise_level=row["surprise_level"],
            lesson=row["lesson"] or "",
            confidence_after=row["confidence_after"],
            retrieved_memories=json.loads(row["retrieved_memories"] or "[]"),
            memory_cited=bool(row["memory_cited"]),
            memory_useful=memory_useful,
            validated=bool(row["validated"]),
            validation_method=row["validation_method"] or "",
            created_at=row["created_at"]
        )

    # ==================== Distillation Operations ====================

    def save_distillation(self, distillation: Distillation) -> str:
        """Save a distillation to the database with duplicate-statement collapsing."""
        def _quality_score(payload: Any) -> float:
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            if isinstance(payload, dict):
                return float(payload.get("unified_score", 0.0) or 0.0)
            return 0.0

        def _quality_dict(payload: Any) -> Dict[str, Any]:
            if isinstance(payload, dict):
                return payload
            if isinstance(payload, str):
                raw = payload.strip()
                if not raw:
                    return {}
                try:
                    parsed = json.loads(raw)
                except Exception:
                    return {}
                return parsed if isinstance(parsed, dict) else {}
            return {}

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            target_norm = _normalize_distillation_statement(distillation.statement)
            existing = None
            candidates = conn.execute(
                """SELECT * FROM distillations
                   WHERE type = ?""",
                (distillation.type.value,),
            ).fetchall()
            for row in candidates:
                if _normalize_distillation_statement(row["statement"] or "") == target_norm:
                    existing = row
                    break

            if existing:
                merged_domains = _merge_unique_str(
                    json.loads(existing["domains"] or "[]"),
                    distillation.domains,
                )
                merged_triggers = _merge_unique_str(
                    json.loads(existing["triggers"] or "[]"),
                    distillation.triggers,
                )
                merged_anti_triggers = _merge_unique_str(
                    json.loads(existing["anti_triggers"] or "[]"),
                    distillation.anti_triggers,
                )
                merged_source_steps = _merge_unique_str(
                    json.loads(existing["source_steps"] or "[]"),
                    distillation.source_steps,
                )

                merged_validation = int(existing["validation_count"] or 0) + int(distillation.validation_count or 0)
                merged_contradiction = int(existing["contradiction_count"] or 0) + int(distillation.contradiction_count or 0)
                merged_retrieved = int(existing["times_retrieved"] or 0) + int(distillation.times_retrieved or 0)
                merged_used = int(existing["times_used"] or 0) + int(distillation.times_used or 0)
                merged_helped = int(existing["times_helped"] or 0) + int(distillation.times_helped or 0)
                merged_confidence = max(float(existing["confidence"] or 0.0), float(distillation.confidence or 0.0))
                merged_created = min(float(existing["created_at"] or time.time()), float(distillation.created_at or time.time()))

                existing_revalidate = existing["revalidate_by"]
                if existing_revalidate is None:
                    merged_revalidate = distillation.revalidate_by
                elif distillation.revalidate_by is None:
                    merged_revalidate = existing_revalidate
                else:
                    merged_revalidate = max(float(existing_revalidate), float(distillation.revalidate_by))

                existing_q = existing["advisory_quality"] if "advisory_quality" in existing.keys() else None
                incoming_q = distillation.advisory_quality or {}
                incoming_better_or_equal = _quality_score(incoming_q) >= _quality_score(existing_q)
                merged_quality = (
                    incoming_q if incoming_better_or_equal else _quality_dict(existing_q)
                )
                merged_statement = str(
                    distillation.statement
                    if incoming_better_or_equal and (distillation.statement or "").strip()
                    else (existing["statement"] or distillation.statement)
                )
                merged_refined = str(
                    distillation.refined_statement
                    or (existing["refined_statement"] if "refined_statement" in existing.keys() else "")
                    or ""
                )

                conn.execute(
                    """UPDATE distillations
                       SET statement = ?, domains = ?, triggers = ?, anti_triggers = ?,
                           source_steps = ?, validation_count = ?, contradiction_count = ?,
                           confidence = ?, times_retrieved = ?, times_used = ?, times_helped = ?,
                           created_at = ?, revalidate_by = ?, refined_statement = ?, advisory_quality = ?
                       WHERE distillation_id = ?""",
                    (
                        merged_statement,
                        json.dumps(merged_domains),
                        json.dumps(merged_triggers),
                        json.dumps(merged_anti_triggers),
                        json.dumps(merged_source_steps),
                        merged_validation,
                        merged_contradiction,
                        merged_confidence,
                        merged_retrieved,
                        merged_used,
                        merged_helped,
                        merged_created,
                        merged_revalidate,
                        merged_refined,
                        json.dumps(merged_quality),
                        str(existing["distillation_id"]),
                    ),
                )
                conn.commit()
                return str(existing["distillation_id"])

            conn.execute(
                """
                INSERT OR REPLACE INTO distillations (
                    distillation_id, type, statement, domains, triggers, anti_triggers,
                    source_steps, validation_count, contradiction_count, confidence,
                    times_retrieved, times_used, times_helped, created_at, revalidate_by,
                    refined_statement, advisory_quality
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    distillation.distillation_id,
                    distillation.type.value,
                    distillation.statement,
                    json.dumps(distillation.domains),
                    json.dumps(distillation.triggers),
                    json.dumps(distillation.anti_triggers),
                    json.dumps(distillation.source_steps),
                    distillation.validation_count,
                    distillation.contradiction_count,
                    distillation.confidence,
                    distillation.times_retrieved,
                    distillation.times_used,
                    distillation.times_helped,
                    distillation.created_at,
                    distillation.revalidate_by,
                    distillation.refined_statement,
                    json.dumps(distillation.advisory_quality or {}),
                ),
            )
            conn.commit()
        return distillation.distillation_id

    def get_distillation(self, distillation_id: str) -> Optional[Distillation]:
        """Get a distillation by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM distillations WHERE distillation_id = ?",
                (distillation_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_distillation(row)

    def get_distillations_by_type(
        self,
        dtype: DistillationType,
        limit: int = 20
    ) -> List[Distillation]:
        """Get distillations of a specific type."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM distillations
                   WHERE type = ?
                   ORDER BY confidence DESC LIMIT ?""",
                (dtype.value, limit)
            ).fetchall()

            return [self._row_to_distillation(row) for row in rows]

    def get_high_confidence_distillations(
        self,
        min_confidence: float = 0.7,
        limit: int = 20
    ) -> List[Distillation]:
        """Get distillations above confidence threshold."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM distillations
                   WHERE confidence >= ?
                   ORDER BY confidence DESC LIMIT ?""",
                (min_confidence, limit)
            ).fetchall()

            return [self._row_to_distillation(row) for row in rows]

    def get_distillations_for_revalidation(self) -> List[Distillation]:
        """Get distillations due for revalidation."""
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM distillations
                   WHERE revalidate_by IS NOT NULL AND revalidate_by <= ?""",
                (now,)
            ).fetchall()

            return [self._row_to_distillation(row) for row in rows]

    def get_distillations_by_trigger(
        self,
        trigger: str,
        limit: int = 20
    ) -> List[Distillation]:
        """Get distillations that match a trigger pattern."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Search in JSON triggers array
            rows = conn.execute(
                """SELECT * FROM distillations
                   WHERE triggers LIKE ?
                   ORDER BY confidence DESC, times_used DESC LIMIT ?""",
                (f'%{trigger}%', limit)
            ).fetchall()

            return [self._row_to_distillation(row) for row in rows]

    def get_distillations_by_domain(
        self,
        domain: str,
        limit: int = 20
    ) -> List[Distillation]:
        """Get distillations for a specific domain."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM distillations
                   WHERE domains LIKE ?
                   ORDER BY confidence DESC, times_used DESC LIMIT ?""",
                (f'%{domain}%', limit)
            ).fetchall()

            return [self._row_to_distillation(row) for row in rows]

    def get_all_distillations(self, limit: int = 100) -> List[Distillation]:
        """Get all distillations ordered by confidence."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM distillations
                   ORDER BY confidence DESC, times_used DESC LIMIT ?""",
                (limit,)
            ).fetchall()

            return [self._row_to_distillation(row) for row in rows]

    def record_distillation_retrieval(self, distillation_id: str):
        """Record that a distillation was retrieved."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE distillations
                   SET times_retrieved = times_retrieved + 1
                   WHERE distillation_id = ?""",
                (distillation_id,)
            )
            conn.commit()

    def find_distillation_by_prefix(self, id_prefix: str) -> Optional[str]:
        """Find a distillation ID by its prefix (used for outcome routing).

        The advisor stores truncated IDs (8 chars) in insight_keys.
        This resolves the full ID for usage tracking.
        """
        if not id_prefix or len(id_prefix) < 6:
            return None
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT distillation_id FROM distillations WHERE distillation_id LIKE ?",
                    (id_prefix + "%",)
                ).fetchone()
                return row[0] if row else None
        except Exception:
            return None

    def record_distillation_usage(self, distillation_id: str, helped: bool):
        """Record that a distillation was used and whether it helped.

        Confidence evolves based on outcomes:
        - Positive: confidence grows toward 1.0 (diminishing returns)
        - Negative: confidence decays (accelerates with high contradiction rate)
        - Below 0.1 after 10+ uses: effectively dead, prunable
        """
        with sqlite3.connect(self.db_path) as conn:
            if helped:
                conn.execute(
                    """UPDATE distillations
                       SET times_used = times_used + 1,
                           times_helped = times_helped + 1,
                           validation_count = validation_count + 1
                       WHERE distillation_id = ?""",
                    (distillation_id,)
                )
            else:
                conn.execute(
                    """UPDATE distillations
                       SET times_used = times_used + 1,
                           contradiction_count = contradiction_count + 1
                       WHERE distillation_id = ?""",
                    (distillation_id,)
                )

            # Evolve confidence based on track record
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT times_used, times_helped, contradiction_count, confidence "
                "FROM distillations WHERE distillation_id = ?",
                (distillation_id,)
            ).fetchone()

            if row and row["times_used"] >= 3:
                total = row["times_used"]
                helped_count = row["times_helped"]
                contra = row["contradiction_count"]
                current_conf = row["confidence"]
                success_ratio = helped_count / max(total, 1)

                if helped:
                    # Boost confidence toward 1.0 with diminishing returns
                    # Step size decreases as confidence grows (harder to reach 1.0)
                    headroom = 1.0 - current_conf
                    boost = min(0.05, headroom * 0.15)
                    new_conf = min(1.0, current_conf + boost)
                else:
                    # Decay confidence — faster when contradiction rate is high
                    contra_rate = contra / max(total, 1)
                    if contra_rate > 0.8 and total >= 10:
                        new_conf = max(0.05, current_conf - 0.05)
                    elif contra_rate > 0.5:
                        new_conf = max(0.05, current_conf - 0.03)
                    else:
                        new_conf = max(0.05, current_conf - 0.01)

                if abs(new_conf - current_conf) > 0.001:
                    conn.execute(
                        "UPDATE distillations SET confidence = ? WHERE distillation_id = ?",
                        (round(new_conf, 4), distillation_id)
                    )

            conn.commit()

    def _row_to_distillation(self, row: sqlite3.Row) -> Distillation:
        """Convert a database row to Distillation object."""
        advisory_quality = {}
        if "advisory_quality" in row.keys():
            raw_quality = row["advisory_quality"]
            if isinstance(raw_quality, str) and raw_quality:
                try:
                    advisory_quality = json.loads(raw_quality)
                except Exception:
                    advisory_quality = {}
            elif isinstance(raw_quality, dict):
                advisory_quality = raw_quality

        refined_statement = ""
        if "refined_statement" in row.keys():
            refined_statement = row["refined_statement"] or ""

        return Distillation(
            distillation_id=row["distillation_id"],
            type=DistillationType(row["type"]),
            statement=row["statement"],
            domains=json.loads(row["domains"] or "[]"),
            triggers=json.loads(row["triggers"] or "[]"),
            anti_triggers=json.loads(row["anti_triggers"] or "[]"),
            source_steps=json.loads(row["source_steps"] or "[]"),
            validation_count=row["validation_count"],
            contradiction_count=row["contradiction_count"],
            confidence=row["confidence"],
            times_retrieved=row["times_retrieved"],
            times_used=row["times_used"],
            times_helped=row["times_helped"],
            created_at=row["created_at"],
            revalidate_by=row["revalidate_by"],
            refined_statement=refined_statement,
            advisory_quality=advisory_quality,
        )

    def prune_distillations(self) -> dict:
        """Prune low-performing and dead distillations.

        Removes:
        1. Dead playbooks (0 retrievals, older than 1 day)
        2. Low success ratio (<0.15) after 10+ uses
        3. Corrupted records (impossible counter values)

        Returns dict with counts of pruned records by reason.
        """
        pruned = {"dead_playbooks": 0, "low_success": 0, "corrupted": 0}
        one_day_ago = time.time() - 86400

        with sqlite3.connect(self.db_path) as conn:
            # 1. Dead playbooks
            cur = conn.execute(
                "DELETE FROM distillations WHERE times_retrieved = 0 "
                "AND type = 'playbook' AND created_at < ?",
                (one_day_ago,)
            )
            pruned["dead_playbooks"] = cur.rowcount

            # 2. Low success ratio after 10+ uses
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT distillation_id, times_used, times_helped "
                "FROM distillations WHERE times_used >= 10"
            ).fetchall()
            low_ids = []
            for row in rows:
                ratio = row["times_helped"] / max(row["times_used"], 1)
                if ratio < 0.15:
                    low_ids.append(row["distillation_id"])
            if low_ids:
                conn.executemany(
                    "DELETE FROM distillations WHERE distillation_id = ?",
                    [(dist_id,) for dist_id in low_ids],
                )
                pruned["low_success"] = len(low_ids)

            # 3. Corrupted records (impossible counts) - repair instead of deleting.
            cur = conn.execute(
                """
                UPDATE distillations
                SET times_retrieved = CASE WHEN times_retrieved > 1000000 OR times_retrieved < 0 THEN 0 ELSE times_retrieved END,
                    times_used = CASE WHEN times_used > 1000000 OR times_used < 0 THEN 0 ELSE times_used END,
                    times_helped = CASE WHEN times_helped > 1000000 OR times_helped < 0 THEN 0 ELSE times_helped END,
                    validation_count = CASE WHEN validation_count > 1000000 OR validation_count < 0 THEN 0 ELSE validation_count END,
                    contradiction_count = CASE WHEN contradiction_count > 1000000 OR contradiction_count < 0 THEN 0 ELSE contradiction_count END
                WHERE times_retrieved > 1000000 OR times_used > 1000000 OR times_helped > 1000000
                   OR validation_count > 1000000 OR contradiction_count > 1000000
                   OR times_retrieved < 0 OR times_used < 0 OR times_helped < 0
                   OR validation_count < 0 OR contradiction_count < 0
                """
            )
            pruned["corrupted"] = cur.rowcount

            conn.commit()

        return pruned

    def archive_and_purge_low_quality_distillations(
        self,
        unified_floor: float = 0.35,
        dry_run: bool = False,
        max_preview: int = 20,
    ) -> Dict[str, Any]:
        """Archive and purge distillations that fail advisory quality gates."""
        def _parse_quality(raw: Any) -> Dict[str, Any]:
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str):
                text = raw.strip()
                if not text:
                    return {}
                try:
                    parsed = json.loads(text)
                except Exception:
                    return {}
                return parsed if isinstance(parsed, dict) else {}
            return {}

        preview: List[Dict[str, Any]] = []
        purge_ids: List[str] = []
        archive_rows: List[Dict[str, Any]] = []

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM distillations").fetchall()
            scanned = len(rows)
            for row in rows:
                statement = (row["statement"] or "").strip()
                refined_statement = ""
                if "refined_statement" in row.keys():
                    refined_statement = (row["refined_statement"] or "").strip()
                candidate_text = refined_statement or statement

                aq_data = _parse_quality(
                    row["advisory_quality"] if "advisory_quality" in row.keys() else None
                )
                if not aq_data or "unified_score" not in aq_data or "suppressed" not in aq_data:
                    computed = transform_for_advisory(candidate_text, source="eidos").to_dict()
                    aq_data = {**computed, **(aq_data or {})}

                reason = ""
                suppressed = bool(aq_data.get("suppressed", False))
                unified = float(aq_data.get("unified_score", 0.0) or 0.0)
                if suppressed:
                    detail = str(aq_data.get("suppression_reason") or "suppressed")
                    reason = f"suppressed:{detail}"
                elif unified < unified_floor:
                    reason = f"unified_score_below_floor:{unified:.3f}"

                if not reason:
                    continue

                purge_ids.append(row["distillation_id"])
                archive_row = dict(row)
                archive_row["archive_reason"] = reason
                archive_row["advisory_quality"] = json.dumps(aq_data)
                archive_rows.append(archive_row)

                if len(preview) < max_preview:
                    preview.append(
                        {
                            "distillation_id": row["distillation_id"],
                            "reason": reason,
                            "statement": candidate_text[:200],
                        }
                    )

            if not dry_run and archive_rows:
                for row in archive_rows:
                    conn.execute(
                        """
                        INSERT INTO distillations_archive (
                            distillation_id, type, statement, domains, triggers, anti_triggers,
                            source_steps, validation_count, contradiction_count, confidence,
                            times_retrieved, times_used, times_helped, created_at, revalidate_by,
                            refined_statement, archive_reason, advisory_quality
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["distillation_id"],
                            row["type"],
                            row["statement"],
                            row["domains"],
                            row["triggers"],
                            row["anti_triggers"],
                            row["source_steps"],
                            row["validation_count"],
                            row["contradiction_count"],
                            row["confidence"],
                            row["times_retrieved"],
                            row["times_used"],
                            row["times_helped"],
                            row["created_at"],
                            row["revalidate_by"],
                            row.get("refined_statement", ""),
                            row["archive_reason"],
                            row["advisory_quality"],
                        ),
                    )
                conn.executemany(
                    "DELETE FROM distillations WHERE distillation_id = ?",
                    [(did,) for did in purge_ids],
                )
                conn.commit()

        return {
            "scanned": scanned,
            "archived": len(purge_ids),
            "dry_run": dry_run,
            "unified_floor": unified_floor,
            "preview": preview,
        }

    def backfill_advisory_quality(self, min_unified_score: float = 0.60) -> Dict[str, Any]:
        """Backfill advisory_quality + refined_statement on distillations that lack them.

        Runs the refinement loop on every active distillation missing advisory_quality,
        then persists the best refined text and quality scores.

        Returns summary dict with counts.
        """
        try:
            from ..distillation_refiner import refine_distillation
        except Exception:
            return {"error": "Could not import refine_distillation"}

        updated = 0
        skipped = 0
        already_has = 0
        errors = 0
        details: List[Dict[str, Any]] = []

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM distillations").fetchall()

            for row in rows:
                did = row["distillation_id"]
                raw_aq = row["advisory_quality"] if "advisory_quality" in row.keys() else None

                # Check if already has valid advisory_quality
                has_quality = False
                if isinstance(raw_aq, str) and raw_aq.strip():
                    try:
                        parsed = json.loads(raw_aq)
                        if isinstance(parsed, dict) and "unified_score" in parsed:
                            has_quality = True
                    except Exception:
                        pass

                if has_quality:
                    already_has += 1
                    continue

                statement = (row["statement"] or "").strip()
                if not statement:
                    skipped += 1
                    continue

                try:
                    refined_text, quality = refine_distillation(
                        statement,
                        source="eidos",
                        context={"type": row["type"], "confidence": row["confidence"]},
                        min_unified_score=min_unified_score,
                    )

                    conn.execute(
                        """UPDATE distillations
                           SET refined_statement = ?, advisory_quality = ?
                           WHERE distillation_id = ?""",
                        (
                            refined_text if refined_text != statement else "",
                            json.dumps(quality),
                            did,
                        ),
                    )
                    updated += 1
                    details.append({
                        "id": did,
                        "type": row["type"],
                        "unified_score": quality.get("unified_score", 0),
                        "suppressed": quality.get("suppressed", False),
                        "refined": bool(refined_text and refined_text != statement),
                    })
                except Exception as exc:
                    errors += 1
                    details.append({"id": did, "error": str(exc)[:200]})

            conn.commit()

        return {
            "total": len(rows),
            "updated": updated,
            "already_has": already_has,
            "skipped": skipped,
            "errors": errors,
            "details": details,
        }

    # ==================== Policy Operations ====================

    def save_policy(self, policy: Policy) -> str:
        """Save a policy to the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO policies (
                    policy_id, statement, scope, priority, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                policy.policy_id,
                policy.statement,
                policy.scope,
                policy.priority,
                policy.source,
                policy.created_at
            ))
            conn.commit()
        return policy.policy_id

    def get_policy(self, policy_id: str) -> Optional[Policy]:
        """Get a policy by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM policies WHERE policy_id = ?",
                (policy_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_policy(row)

    def get_policies_by_scope(
        self,
        scope: str = "GLOBAL",
        limit: int = 50
    ) -> List[Policy]:
        """Get policies by scope."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM policies
                   WHERE scope = ?
                   ORDER BY priority DESC LIMIT ?""",
                (scope, limit)
            ).fetchall()

            return [self._row_to_policy(row) for row in rows]

    def get_all_policies(self) -> List[Policy]:
        """Get all policies ordered by priority."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM policies ORDER BY priority DESC"
            ).fetchall()

            return [self._row_to_policy(row) for row in rows]

    def _row_to_policy(self, row: sqlite3.Row) -> Policy:
        """Convert a database row to Policy object."""
        return Policy(
            policy_id=row["policy_id"],
            statement=row["statement"],
            scope=row["scope"],
            priority=row["priority"],
            source=row["source"],
            created_at=row["created_at"]
        )

    # ==================== Statistics ====================

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with sqlite3.connect(self.db_path) as conn:
            episode_count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            step_count = conn.execute("SELECT COUNT(*) FROM steps").fetchone()[0]
            distillation_count = conn.execute("SELECT COUNT(*) FROM distillations").fetchone()[0]
            policy_count = conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0]

            # Success rate
            success_episodes = conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE outcome = 'success'"
            ).fetchone()[0]

            # High confidence distillations
            high_conf_distillations = conn.execute(
                "SELECT COUNT(*) FROM distillations WHERE confidence >= 0.7"
            ).fetchone()[0]

            return {
                "episodes": episode_count,
                "steps": step_count,
                "distillations": distillation_count,
                "policies": policy_count,
                "success_rate": success_episodes / episode_count if episode_count > 0 else 0,
                "high_confidence_distillations": high_conf_distillations,
                "db_path": self.db_path
            }

    def purge_telemetry_distillations(self, dry_run: bool = False, max_preview: int = 20) -> Dict[str, Any]:
        """Remove telemetry/primitive distillations from the EIDOS store."""
        from ..primitive_filter import is_primitive_text
        from ..promoter import is_operational_insight

        def _is_telemetry_distillation(text: str) -> bool:
            t = (text or "").strip()
            if not t:
                return False
            if is_primitive_text(t) or is_operational_insight(t):
                return True
            tl = t.lower()
            if "success rate" in tl:
                return True
            if re.search(r"over\s+\d+\s+uses", tl):
                return True
            if "sequence" in tl and "->" in t:
                return True
            return False

        removed_ids: List[str] = []
        preview: List[str] = []

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT distillation_id, statement FROM distillations"
            ).fetchall()
            for row in rows:
                dist_id = row[0]
                statement = row[1] or ""
                if _is_telemetry_distillation(statement):
                    removed_ids.append(dist_id)
                    if len(preview) < max_preview:
                        preview.append(statement[:200])

            if not dry_run and removed_ids:
                conn.executemany(
                    "DELETE FROM distillations WHERE distillation_id = ?",
                    [(rid,) for rid in removed_ids]
                )

        return {
            "scanned": len(rows),
            "removed": len(removed_ids),
            "preview": preview,
            "dry_run": dry_run,
        }


# Singleton instance
_store: Optional[EidosStore] = None


def get_store(db_path: Optional[str] = None) -> EidosStore:
    """Get the singleton store instance."""
    global _store
    if _store is None or (db_path and _store.db_path != db_path):
        _store = EidosStore(db_path)
    return _store


def purge_telemetry_distillations(dry_run: bool = False, max_preview: int = 20) -> Dict[str, Any]:
    """Purge telemetry/primitive distillations from the EIDOS store."""
    store = get_store()
    return store.purge_telemetry_distillations(dry_run=dry_run, max_preview=max_preview)
