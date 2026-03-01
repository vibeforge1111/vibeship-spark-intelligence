"""ACT-R activation model for Spark Intelligence.

Implements base-level activation (BLA) from ACT-R cognitive architecture:

    B_i = ln(sum over j: t_j^(-d))

Where:
- t_j = time in seconds since the j-th access of insight i
- d   = decay parameter (default 0.5, power-law)

Power-law decay means old-but-frequently-accessed knowledge persists far
longer than exponential decay would allow.  An insight accessed 100 times
over 6 months retains significant activation even after a week of silence.

Storage: separate SQLite database at ~/.spark/activation/access_log.sqlite.
Does NOT modify the CognitiveInsight dataclass or cognitive_insights.json.

Design: fail-open.  If the DB is locked or corrupted, all operations return
safe defaults (activation=0.0, all insights pass threshold).
"""

from __future__ import annotations

import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration (overridden by tuneables.json -> activation section)
# ---------------------------------------------------------------------------

DEFAULT_DECAY = 0.5
DEFAULT_TAU = -1.0           # retrieval threshold (below = effectively forgotten)
MAX_ACCESS_LOG_SIZE = 200    # per insight, prune oldest beyond this
ACTIVATION_CACHE_TTL_S = 30  # recompute at most every 30s per insight
MIN_TIME_DELTA = 1.0         # minimum seconds since access (avoid log(0))

ACTIVATION_DIR = Path.home() / ".spark" / "activation"
ACTIVATION_DB = ACTIVATION_DIR / "access_log.sqlite"

# ---------------------------------------------------------------------------
# Thread-safe singleton
# ---------------------------------------------------------------------------

_instance: Optional["ActivationStore"] = None
_instance_lock = threading.Lock()


def get_activation_store(db_path: Optional[Path] = None) -> "ActivationStore":
    """Get or create the singleton ActivationStore."""
    global _instance
    if _instance is not None and (db_path is None or _instance.db_path == db_path):
        return _instance
    with _instance_lock:
        if _instance is None or (db_path is not None and _instance.db_path != db_path):
            _instance = ActivationStore(db_path or ACTIVATION_DB)
    return _instance


# ---------------------------------------------------------------------------
# ActivationStore
# ---------------------------------------------------------------------------

class ActivationStore:
    """SQLite-backed access log and activation cache for ACT-R model."""

    def __init__(self, db_path: Path = ACTIVATION_DB):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._cache: Dict[str, Tuple[float, float]] = {}  # key -> (activation, computed_at)
        self._init_db()

    # -- Connection management (per-thread) ---------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=5.0,
                isolation_level="DEFERRED",
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        try:
            conn = self._get_conn()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS access_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    insight_key TEXT NOT NULL,
                    access_ts REAL NOT NULL,
                    access_type TEXT DEFAULT 'retrieval'
                );
                CREATE INDEX IF NOT EXISTS idx_access_key
                    ON access_log(insight_key);
                CREATE INDEX IF NOT EXISTS idx_access_ts
                    ON access_log(access_ts);

                CREATE TABLE IF NOT EXISTS activation_cache (
                    insight_key TEXT PRIMARY KEY,
                    activation REAL NOT NULL,
                    computed_at REAL NOT NULL,
                    access_count INTEGER DEFAULT 0
                );
            """)
            conn.commit()
        except Exception:
            pass  # fail-open: DB issues should not block the system

    # -- Recording accesses -------------------------------------------------

    def record_access(
        self,
        insight_key: str,
        access_type: str = "retrieval",
    ) -> None:
        """Record an access event.

        Types: retrieval, validation, advisory, promotion, storage.
        """
        if not insight_key:
            return
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO access_log (insight_key, access_ts, access_type) VALUES (?, ?, ?)",
                (insight_key, time.time(), access_type),
            )
            conn.commit()
            # Invalidate cache for this key.
            self._cache.pop(insight_key, None)
        except Exception:
            pass  # fail-open

    def record_access_batch(
        self,
        entries: List[Tuple[str, str]],  # [(insight_key, access_type), ...]
    ) -> None:
        """Record multiple access events efficiently."""
        if not entries:
            return
        try:
            now = time.time()
            conn = self._get_conn()
            conn.executemany(
                "INSERT INTO access_log (insight_key, access_ts, access_type) VALUES (?, ?, ?)",
                [(key, now, atype) for key, atype in entries],
            )
            conn.commit()
            for key, _ in entries:
                self._cache.pop(key, None)
        except Exception:
            pass

    # -- Computing activation -----------------------------------------------

    def compute_activation(
        self,
        insight_key: str,
        decay: float = DEFAULT_DECAY,
    ) -> float:
        """Compute ACT-R base-level activation B_i = ln(sum(t_j^(-d))).

        Uses cached value if fresh (< ACTIVATION_CACHE_TTL_S old).
        Returns 0.0 for insights with no access history.
        """
        if not insight_key:
            return 0.0

        # Check in-memory cache first.
        cached = self._cache.get(insight_key)
        now = time.time()
        if cached is not None:
            activation, computed_at = cached
            if (now - computed_at) < ACTIVATION_CACHE_TTL_S:
                return activation

        try:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT access_ts FROM access_log WHERE insight_key = ? ORDER BY access_ts DESC LIMIT ?",
                (insight_key, MAX_ACCESS_LOG_SIZE),
            ).fetchall()
        except Exception:
            return 0.0

        if not rows:
            return 0.0

        activation = self._compute_bla(rows, now, decay)

        # Cache it.
        self._cache[insight_key] = (activation, now)

        # Persist to DB cache for cross-process visibility.
        try:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO activation_cache (insight_key, activation, computed_at, access_count)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(insight_key) DO UPDATE SET
                       activation=excluded.activation,
                       computed_at=excluded.computed_at,
                       access_count=excluded.access_count""",
                (insight_key, activation, now, len(rows)),
            )
            conn.commit()
        except Exception:
            pass

        return activation

    def batch_compute_activations(
        self,
        insight_keys: List[str],
        decay: float = DEFAULT_DECAY,
    ) -> Dict[str, float]:
        """Compute activations for multiple keys efficiently."""
        if not insight_keys:
            return {}

        now = time.time()
        result: Dict[str, float] = {}
        keys_to_compute: List[str] = []

        # Check cache first.
        for key in insight_keys:
            cached = self._cache.get(key)
            if cached is not None:
                activation, computed_at = cached
                if (now - computed_at) < ACTIVATION_CACHE_TTL_S:
                    result[key] = activation
                    continue
            keys_to_compute.append(key)

        if not keys_to_compute:
            return result

        # Batch fetch from DB.
        try:
            conn = self._get_conn()
            placeholders = ",".join("?" for _ in keys_to_compute)
            rows = conn.execute(
                f"SELECT insight_key, access_ts FROM access_log "
                f"WHERE insight_key IN ({placeholders}) "
                f"ORDER BY insight_key, access_ts DESC",
                keys_to_compute,
            ).fetchall()
        except Exception:
            # Return defaults for uncached keys.
            for key in keys_to_compute:
                result[key] = 0.0
            return result

        # Group by key.
        key_accesses: Dict[str, List[Tuple[float,]]] = {}
        for key, ts in rows:
            key_accesses.setdefault(key, []).append((ts,))

        for key in keys_to_compute:
            accesses = key_accesses.get(key, [])
            if not accesses:
                result[key] = 0.0
            else:
                # Only keep MAX_ACCESS_LOG_SIZE most recent.
                accesses = accesses[:MAX_ACCESS_LOG_SIZE]
                activation = self._compute_bla(accesses, now, decay)
                result[key] = activation
                self._cache[key] = (activation, now)

        return result

    def get_activation_cached(self, insight_key: str) -> Optional[float]:
        """Return cached activation if fresh, else None."""
        cached = self._cache.get(insight_key)
        if cached is not None:
            activation, computed_at = cached
            if (time.time() - computed_at) < ACTIVATION_CACHE_TTL_S:
                return activation

        # Try DB cache.
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT activation, computed_at FROM activation_cache WHERE insight_key = ?",
                (insight_key,),
            ).fetchone()
            if row:
                activation, computed_at = row
                if (time.time() - computed_at) < ACTIVATION_CACHE_TTL_S:
                    self._cache[insight_key] = (activation, computed_at)
                    return activation
        except Exception:
            pass

        return None

    # -- Threshold queries --------------------------------------------------

    def get_above_threshold(
        self,
        tau: float = DEFAULT_TAU,
        limit: int = 500,
    ) -> List[Tuple[str, float]]:
        """Return insight keys with activation >= tau, sorted descending."""
        try:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT insight_key, activation FROM activation_cache "
                "WHERE activation >= ? ORDER BY activation DESC LIMIT ?",
                (tau, limit),
            ).fetchall()
            return [(key, act) for key, act in rows]
        except Exception:
            return []

    def get_below_threshold(
        self,
        tau: float = DEFAULT_TAU,
        limit: int = 200,
    ) -> List[Tuple[str, float]]:
        """Return insights below threshold (candidates for archival)."""
        try:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT insight_key, activation FROM activation_cache "
                "WHERE activation < ? ORDER BY activation ASC LIMIT ?",
                (tau, limit),
            ).fetchall()
            return [(key, act) for key, act in rows]
        except Exception:
            return []

    # -- Maintenance --------------------------------------------------------

    def prune_old_accesses(
        self,
        max_per_key: int = MAX_ACCESS_LOG_SIZE,
    ) -> int:
        """Remove oldest access entries beyond max_per_key per insight.

        Returns count of rows deleted.
        """
        try:
            conn = self._get_conn()
            # Find keys with more than max_per_key entries.
            heavy_keys = conn.execute(
                "SELECT insight_key, COUNT(*) as cnt FROM access_log "
                "GROUP BY insight_key HAVING cnt > ?",
                (max_per_key,),
            ).fetchall()

            total_deleted = 0
            for key, cnt in heavy_keys:
                excess = cnt - max_per_key
                # Delete the oldest excess rows for this key.
                conn.execute(
                    "DELETE FROM access_log WHERE id IN ("
                    "  SELECT id FROM access_log WHERE insight_key = ? "
                    "  ORDER BY access_ts ASC LIMIT ?"
                    ")",
                    (key, excess),
                )
                total_deleted += excess

            conn.commit()
            return total_deleted
        except Exception:
            return 0

    def batch_recompute_stale(self, max_items: int = 100) -> int:
        """Recompute activations for keys with stale cache entries.

        Returns count of keys recomputed.
        """
        try:
            cutoff = time.time() - ACTIVATION_CACHE_TTL_S
            conn = self._get_conn()
            stale_keys = conn.execute(
                "SELECT insight_key FROM activation_cache "
                "WHERE computed_at < ? LIMIT ?",
                (cutoff, max_items),
            ).fetchall()

            if not stale_keys:
                return 0

            keys = [row[0] for row in stale_keys]
            self.batch_compute_activations(keys)
            return len(keys)
        except Exception:
            return 0

    def get_stats(self) -> Dict[str, int]:
        """Return basic statistics about the activation store."""
        try:
            conn = self._get_conn()
            total_accesses = conn.execute(
                "SELECT COUNT(*) FROM access_log"
            ).fetchone()[0]
            unique_keys = conn.execute(
                "SELECT COUNT(DISTINCT insight_key) FROM access_log"
            ).fetchone()[0]
            cached_keys = conn.execute(
                "SELECT COUNT(*) FROM activation_cache"
            ).fetchone()[0]
            return {
                "total_accesses": total_accesses,
                "unique_keys": unique_keys,
                "cached_activations": cached_keys,
            }
        except Exception:
            return {"total_accesses": 0, "unique_keys": 0, "cached_activations": 0}

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _compute_bla(
        rows: List[Tuple[float, ...]],
        now: float,
        decay: float,
    ) -> float:
        """Core ACT-R base-level activation formula.

        B_i = ln(sum(t_j^(-d)))

        *rows* is a list of tuples where the first element is access_ts.
        """
        total = 0.0
        for row in rows:
            ts = row[0]
            delta = max(now - ts, MIN_TIME_DELTA)
            total += delta ** (-decay)

        if total <= 0:
            return -10.0  # effectively no activation

        return math.log(total)

    @staticmethod
    def activation_to_probability(activation: float) -> float:
        """Convert ACT-R activation to a [0, 1] probability via sigmoid.

        Useful for blending with existing fusion/rank scores that use [0,1].
        """
        return 1.0 / (1.0 + math.exp(-activation))

    def close(self) -> None:
        """Close the DB connection for the current thread."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None
