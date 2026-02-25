"""Local hybrid memory store (SQLite + optional embeddings).

Goal: cross-project sink with lightweight hybrid retrieval:
- SQLite FTS5 (BM25-ish lexical ranking)
- Optional embeddings for semantic matching

No server required. Falls back gracefully if embeddings or FTS5 are unavailable.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import hashlib
import difflib
import sys
import time
from array import array
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lib.config_authority import env_bool, env_float, resolve_section
from lib.embeddings import embed_texts

DB_PATH = Path.home() / ".spark" / "memory_store.sqlite"
_FTS_AVAILABLE: Optional[bool] = None
TUNEABLES_FILE = Path.home() / ".spark" / "tuneables.json"

# Phase 2: patchified (chunked) memory storage
PATCHIFIED_ENABLED = os.getenv("SPARK_MEMORY_PATCHIFIED", "0") == "1"

# Phase 2: delta memory compaction (store updates as deltas when near-duplicate)
DELTAS_ENABLED = os.getenv("SPARK_MEMORY_DELTAS", "0") == "1"
try:
    DELTA_MIN_SIMILARITY = float(os.getenv("SPARK_MEMORY_DELTA_MIN_SIM", "0.86"))
except Exception:
    DELTA_MIN_SIMILARITY = 0.86
DELTAS_WINDOW_DAYS = 30

try:
    PATCH_MAX_CHARS = max(120, min(2000, int(os.getenv("SPARK_MEMORY_PATCH_MAX_CHARS", "600") or 600)))
except Exception:
    PATCH_MAX_CHARS = 600
try:
    PATCH_MIN_CHARS = max(40, min(400, int(os.getenv("SPARK_MEMORY_PATCH_MIN_CHARS", "120") or 120)))
except Exception:
    PATCH_MIN_CHARS = 120

MEMORY_EMOTION_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "retrieval_state_match_weight": 0.22,
    "retrieval_min_state_similarity": 0.30,
}
_MEMORY_EMOTION_CFG_CACHE: Dict[str, Any] = dict(MEMORY_EMOTION_DEFAULTS)
_MEMORY_EMOTION_CFG_MTIME: Optional[float] = None

MEMORY_LEARNING_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "retrieval_learning_weight": 0.18,
    "retrieval_min_learning_signal": 0.20,
    "calm_mode_bonus": 0.08,
}
_MEMORY_LEARNING_CFG_CACHE: Dict[str, Any] = dict(MEMORY_LEARNING_DEFAULTS)
_MEMORY_LEARNING_CFG_MTIME: Optional[float] = None

MEMORY_RETRIEVAL_GUARD_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "base_score_floor": 0.22,
    "max_total_boost": 1.0,
}
_MEMORY_RETRIEVAL_GUARD_CFG_CACHE: Dict[str, Any] = dict(MEMORY_RETRIEVAL_GUARD_DEFAULTS)
_MEMORY_RETRIEVAL_GUARD_CFG_MTIME: Optional[float] = None


def _tuneables_read_allowed() -> bool:
    if "pytest" not in sys.modules:
        return True
    if str(os.environ.get("SPARK_TEST_ALLOW_HOME_TUNEABLES", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return True
    try:
        return TUNEABLES_FILE.resolve() != (Path.home() / ".spark" / "tuneables.json").resolve()
    except Exception:
        return False


def _safe_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "off", "no"}


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _load_memory_emotion_config(*, force: bool = False) -> Dict[str, Any]:
    global _MEMORY_EMOTION_CFG_MTIME
    global _MEMORY_EMOTION_CFG_CACHE

    current_mtime: Optional[float] = None
    try:
        if TUNEABLES_FILE.exists() and _tuneables_read_allowed():
            current_mtime = float(TUNEABLES_FILE.stat().st_mtime)
    except Exception:
        current_mtime = None

    if not force and _MEMORY_EMOTION_CFG_MTIME == current_mtime:
        return dict(_MEMORY_EMOTION_CFG_CACHE)

    cfg = dict(MEMORY_EMOTION_DEFAULTS)
    runtime_path = (
        TUNEABLES_FILE
        if _tuneables_read_allowed()
        else (Path.home() / ".spark" / "__disabled_tuneables_runtime__.json")
    )
    resolved = resolve_section(
        "memory_emotion",
        runtime_path=runtime_path,
        env_overrides={
            "enabled": env_bool("SPARK_MEMORY_EMOTION_ENABLED"),
            "retrieval_state_match_weight": env_float("SPARK_MEMORY_EMOTION_WEIGHT", lo=0.0, hi=1.0),
            "retrieval_min_state_similarity": env_float("SPARK_MEMORY_EMOTION_MIN_SIM", lo=0.0, hi=1.0),
        },
    ).data
    cfg["enabled"] = _safe_bool(resolved.get("enabled"), cfg["enabled"])
    cfg["retrieval_state_match_weight"] = _safe_float(
        resolved.get("retrieval_state_match_weight"),
        cfg["retrieval_state_match_weight"],
    )
    cfg["retrieval_min_state_similarity"] = _safe_float(
        resolved.get("retrieval_min_state_similarity"),
        cfg["retrieval_min_state_similarity"],
    )

    cfg["retrieval_state_match_weight"] = max(0.0, float(cfg["retrieval_state_match_weight"]))
    cfg["retrieval_min_state_similarity"] = _clamp01(cfg["retrieval_min_state_similarity"])

    _MEMORY_EMOTION_CFG_CACHE = dict(cfg)
    _MEMORY_EMOTION_CFG_MTIME = current_mtime
    return dict(cfg)


def _load_memory_learning_config(*, force: bool = False) -> Dict[str, Any]:
    global _MEMORY_LEARNING_CFG_MTIME
    global _MEMORY_LEARNING_CFG_CACHE

    current_mtime: Optional[float] = None
    try:
        if TUNEABLES_FILE.exists() and _tuneables_read_allowed():
            current_mtime = float(TUNEABLES_FILE.stat().st_mtime)
    except Exception:
        current_mtime = None

    if not force and _MEMORY_LEARNING_CFG_MTIME == current_mtime:
        return dict(_MEMORY_LEARNING_CFG_CACHE)

    cfg = dict(MEMORY_LEARNING_DEFAULTS)
    runtime_path = (
        TUNEABLES_FILE
        if _tuneables_read_allowed()
        else (Path.home() / ".spark" / "__disabled_tuneables_runtime__.json")
    )
    resolved = resolve_section(
        "memory_learning",
        runtime_path=runtime_path,
        env_overrides={
            "enabled": env_bool("SPARK_MEMORY_LEARNING_ENABLED"),
            "retrieval_learning_weight": env_float("SPARK_MEMORY_LEARNING_WEIGHT", lo=0.0, hi=1.0),
        },
    ).data
    cfg["enabled"] = _safe_bool(resolved.get("enabled"), cfg["enabled"])
    cfg["retrieval_learning_weight"] = _safe_float(
        resolved.get("retrieval_learning_weight"),
        cfg["retrieval_learning_weight"],
    )
    cfg["retrieval_min_learning_signal"] = _safe_float(
        resolved.get("retrieval_min_learning_signal"),
        cfg["retrieval_min_learning_signal"],
    )
    cfg["calm_mode_bonus"] = _safe_float(
        resolved.get("calm_mode_bonus"),
        cfg["calm_mode_bonus"],
    )

    cfg["retrieval_learning_weight"] = max(0.0, float(cfg["retrieval_learning_weight"]))
    cfg["retrieval_min_learning_signal"] = _clamp01(cfg["retrieval_min_learning_signal"])
    cfg["calm_mode_bonus"] = _clamp01(cfg["calm_mode_bonus"])

    _MEMORY_LEARNING_CFG_CACHE = dict(cfg)
    _MEMORY_LEARNING_CFG_MTIME = current_mtime
    return dict(cfg)


def _load_memory_retrieval_guard_config(*, force: bool = False) -> Dict[str, Any]:
    global _MEMORY_RETRIEVAL_GUARD_CFG_MTIME
    global _MEMORY_RETRIEVAL_GUARD_CFG_CACHE

    current_mtime: Optional[float] = None
    try:
        if TUNEABLES_FILE.exists() and _tuneables_read_allowed():
            current_mtime = float(TUNEABLES_FILE.stat().st_mtime)
    except Exception:
        current_mtime = None

    if not force and _MEMORY_RETRIEVAL_GUARD_CFG_MTIME == current_mtime:
        return dict(_MEMORY_RETRIEVAL_GUARD_CFG_CACHE)

    cfg = dict(MEMORY_RETRIEVAL_GUARD_DEFAULTS)
    runtime_path = (
        TUNEABLES_FILE
        if _tuneables_read_allowed()
        else (Path.home() / ".spark" / "__disabled_tuneables_runtime__.json")
    )
    resolved = resolve_section(
        "memory_retrieval_guard",
        runtime_path=runtime_path,
        env_overrides={
            "enabled": env_bool("SPARK_MEMORY_RETRIEVAL_GUARD_ENABLED"),
        },
    ).data
    cfg["enabled"] = _safe_bool(resolved.get("enabled"), cfg["enabled"])
    cfg["base_score_floor"] = _safe_float(
        resolved.get("base_score_floor"),
        cfg["base_score_floor"],
    )
    cfg["max_total_boost"] = _safe_float(
        resolved.get("max_total_boost"),
        cfg["max_total_boost"],
    )

    cfg["base_score_floor"] = _clamp01(cfg["base_score_floor"])
    cfg["max_total_boost"] = max(0.0, float(cfg["max_total_boost"]))

    _MEMORY_RETRIEVAL_GUARD_CFG_CACHE = dict(cfg)
    _MEMORY_RETRIEVAL_GUARD_CFG_MTIME = current_mtime
    return dict(cfg)


def _current_retrieval_emotion_state() -> Optional[Dict[str, Any]]:
    try:
        from lib.spark_emotions import SparkEmotions

        state = (SparkEmotions().status() or {}).get("state") or {}
        if not isinstance(state, dict):
            return None
        return {
            "primary_emotion": str(state.get("primary_emotion") or "steady"),
            "mode": str(state.get("mode") or "real_talk"),
            "warmth": _clamp01(_safe_float(state.get("warmth"), 0.0)),
            "energy": _clamp01(_safe_float(state.get("energy"), 0.0)),
            "confidence": _clamp01(_safe_float(state.get("confidence"), 0.0)),
            "calm": _clamp01(_safe_float(state.get("calm"), 0.0)),
            "playfulness": _clamp01(_safe_float(state.get("playfulness"), 0.0)),
            "strain": _clamp01(_safe_float(state.get("strain"), 0.0)),
        }
    except Exception:
        return None


def _with_memory_emotion_meta(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(meta or {})
    cfg = _load_memory_emotion_config()
    if not bool(cfg.get("enabled", True)):
        return merged
    if isinstance(merged.get("emotion"), dict) and merged.get("emotion"):
        return merged

    state = _current_retrieval_emotion_state()
    if not state:
        return merged

    state_copy = dict(state)
    state_copy["captured_at"] = time.time()
    merged["emotion"] = state_copy
    return merged


def _with_memory_learning_meta(
    meta: Optional[Dict[str, Any]],
    *,
    category: str,
    content: str,
) -> Dict[str, Any]:
    merged = dict(meta or {})
    cfg = _load_memory_learning_config()
    if not bool(cfg.get("enabled", True)):
        return merged

    if isinstance(merged.get("learning"), dict) and merged.get("learning"):
        return merged

    cat = (category or "").strip().lower()
    base_priority = {
        "reasoning": 0.78,
        "meta_learning": 0.75,
        "self_awareness": 0.68,
        "workflow": 0.62,
        "advisory": 0.60,
    }.get(cat, 0.52)

    text = (content or "").lower()
    keyword_bonus = 0.0
    if any(k in text for k in ("learn", "lesson", "pattern", "insight", "approach", "fix", "decision")):
        keyword_bonus += 0.08
    if any(k in text for k in ("always", "never", "rule", "gate", "must")):
        keyword_bonus += 0.06

    outcome_quality = _clamp01(_safe_float(merged.get("outcome_quality"), 0.60))
    priority = _clamp01(base_priority + keyword_bonus)

    merged["learning"] = {
        "priority": round(priority, 4),
        "outcome_quality": round(outcome_quality, 4),
        "calm_important": bool(priority >= 0.62),
        "captured_at": time.time(),
    }
    return merged


def _emotion_state_similarity(
    active_state: Optional[Dict[str, Any]],
    stored_state: Optional[Dict[str, Any]],
) -> float:
    if not isinstance(active_state, dict) or not isinstance(stored_state, dict):
        return 0.0

    emotion_match = 1.0 if (
        str(active_state.get("primary_emotion") or "").strip()
        and str(active_state.get("primary_emotion") or "").strip()
        == str(stored_state.get("primary_emotion") or "").strip()
    ) else 0.0
    mode_match = 1.0 if (
        str(active_state.get("mode") or "").strip()
        and str(active_state.get("mode") or "").strip()
        == str(stored_state.get("mode") or "").strip()
    ) else 0.0

    axis_scores: List[float] = []
    for axis in ("strain", "calm", "energy", "confidence", "warmth", "playfulness"):
        if axis not in active_state or axis not in stored_state:
            continue
        a = _clamp01(_safe_float(active_state.get(axis), 0.0))
        b = _clamp01(_safe_float(stored_state.get(axis), 0.0))
        axis_scores.append(max(0.0, 1.0 - abs(a - b)))

    axis_similarity = sum(axis_scores) / len(axis_scores) if axis_scores else 0.0
    return _clamp01((0.50 * axis_similarity) + (0.35 * emotion_match) + (0.15 * mode_match))

def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
          memory_id TEXT PRIMARY KEY,
          content TEXT NOT NULL,
          scope TEXT,
          project_key TEXT,
          category TEXT,
          created_at REAL,
          source TEXT,
          meta TEXT
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_key);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope);")
    _ensure_fts(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories_vec (
          memory_id TEXT PRIMARY KEY,
          dim INTEGER,
          vector BLOB
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_edges (
          source_id TEXT NOT NULL,
          target_id TEXT NOT NULL,
          weight REAL,
          reason TEXT,
          created_at REAL,
          PRIMARY KEY (source_id, target_id)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON memory_edges(source_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON memory_edges(target_id);")
    conn.commit()


def _ensure_fts(conn: sqlite3.Connection) -> bool:
    global _FTS_AVAILABLE
    if _FTS_AVAILABLE is True:
        return True
    if _FTS_AVAILABLE is False:
        return False
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(
              content,
              memory_id UNINDEXED,
              scope UNINDEXED,
              project_key UNINDEXED,
              category UNINDEXED
            );
            """
        )
        _FTS_AVAILABLE = True
    except sqlite3.OperationalError:
        _FTS_AVAILABLE = False
    return bool(_FTS_AVAILABLE)


def _sanitize_token(token: str) -> str:
    return "".join(ch for ch in token if ch.isalnum())


def _build_fts_query(text: str) -> str:
    tokens = [_sanitize_token(t) for t in (text or "").lower().split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return ""
    return " OR ".join(tokens)


def _embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    return embed_texts(texts)


def _vector_to_blob(vec: List[float]) -> bytes:
    buf = array("f", vec)
    return buf.tobytes()


def _blob_to_vector(blob: bytes) -> List[float]:
    buf = array("f")
    buf.frombytes(blob or b"")
    return list(buf)


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / ((na ** 0.5) * (nb ** 0.5))))


def _upsert_edge(
    conn: sqlite3.Connection,
    source_id: str,
    target_id: str,
    weight: float,
    reason: str,
    created_at: float,
) -> None:
    if not source_id or not target_id or source_id == target_id:
        return
    row = conn.execute(
        "SELECT weight FROM memory_edges WHERE source_id = ? AND target_id = ?",
        (source_id, target_id),
    ).fetchone()
    if row:
        new_weight = min(1.0, float(row["weight"] or 0.0) + 0.05)
        conn.execute(
            "UPDATE memory_edges SET weight = ?, reason = ?, created_at = ? WHERE source_id = ? AND target_id = ?",
            (new_weight, reason, created_at, source_id, target_id),
        )
    else:
        conn.execute(
            "INSERT OR REPLACE INTO memory_edges (source_id, target_id, weight, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (source_id, target_id, weight, reason, created_at),
        )


def _link_edges(
    conn: sqlite3.Connection,
    memory_id: str,
    project_key: Optional[str],
    scope: str,
    created_at: float,
    max_project_links: int = 5,
    max_global_links: int = 3,
) -> None:
    targets: List[sqlite3.Row] = []
    if project_key:
        targets.extend(
            conn.execute(
                """
                SELECT memory_id, project_key, scope
                FROM memories
                WHERE memory_id != ? AND project_key = ?
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (memory_id, project_key, max_project_links),
            ).fetchall()
        )

    targets.extend(
        conn.execute(
            """
            SELECT memory_id, project_key, scope
            FROM memories
            WHERE memory_id != ? AND scope = 'global'
            ORDER BY created_at DESC
            LIMIT ?;
            """,
            (memory_id, max_global_links),
        ).fetchall()
    )

    seen = set()
    for row in targets:
        tid = row["memory_id"]
        if not tid or tid in seen:
            continue
        seen.add(tid)
        reason = "cooccurrence:project" if row["project_key"] == project_key and project_key else "cooccurrence:global"
        weight = 0.6 if reason.endswith("project") else 0.4
        _upsert_edge(conn, memory_id, tid, weight, reason, created_at)
        _upsert_edge(conn, tid, memory_id, weight, reason, created_at)


def _normalize_for_similarity(text: str) -> str:
    t = str(text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t[:5000]  # bound work


def _best_delta(old_text: str, new_text: str) -> str:
    """Extract a human-readable delta from new_text relative to old_text.

    Conservative: if we can't find a meaningful delta, return empty string.
    """
    old_n = _normalize_for_similarity(old_text)
    new_n = _normalize_for_similarity(new_text)
    if not old_n or not new_n:
        return ""

    # Easiest case: old is contained in new.
    if old_n in new_n and len(new_n) > len(old_n):
        # attempt to take suffix/prefix around the match for readability
        idx = new_n.find(old_n)
        prefix = new_n[:idx].strip()
        suffix = new_n[idx + len(old_n):].strip()
        delta = " ".join([p for p in (prefix, suffix) if p])
        return delta.strip()

    sm = difflib.SequenceMatcher(a=old_n, b=new_n)
    match = sm.find_longest_match(0, len(old_n), 0, len(new_n))
    if match.size < 120:
        return ""

    prefix = new_n[: match.b].strip()
    suffix = new_n[match.b + match.size :].strip()
    parts = [p for p in (prefix, suffix) if p]
    delta = " / ".join(parts).strip()
    return delta


def _find_recent_similar(
    conn: sqlite3.Connection,
    *,
    content: str,
    scope: str,
    project_key: Optional[str],
    category: str,
) -> Optional[Tuple[str, str, float]]:
    """Return (memory_id, content, similarity) for the best recent match."""
    if not content:
        return None
    cutoff = time.time() - (max(1, int(DELTAS_WINDOW_DAYS)) * 86400.0)
    rows = conn.execute(
        """
        SELECT memory_id, content
        FROM memories
        WHERE created_at >= ?
          AND scope = ?
          AND category = ?
          AND (? IS NULL OR project_key = ?)
        ORDER BY created_at DESC
        LIMIT 25;
        """,
        (cutoff, scope, category, project_key, project_key),
    ).fetchall()

    best: Optional[Tuple[str, str, float]] = None
    target = _normalize_for_similarity(content)
    if not target:
        return None
    for r in rows:
        old = r["content"] or ""
        if not old:
            continue
        old_n = _normalize_for_similarity(old)
        if not old_n:
            continue
        sim = difflib.SequenceMatcher(a=old_n, b=target).ratio()
        if best is None or sim > best[2]:
            best = (str(r["memory_id"]), old, float(sim))
    return best


def _split_patches(text: str) -> List[str]:
    """Split a memory into chunk-sized patches.

    Heuristics:
    - Prefer paragraph/bullet boundaries
    - Keep each patch <= PATCH_MAX_CHARS
    - Drop tiny fragments (< PATCH_MIN_CHARS) by merging forward
    """
    raw = str(text or "").strip()
    if not raw:
        return []

    # Normalize line endings
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    # Split into logical blocks: paragraphs + bullet runs
    blocks: List[str] = []
    for part in re.split(r"\n\s*\n+", raw):
        part = part.strip()
        if not part:
            continue
        # If it's a multi-line bullet list, keep bullets separate-ish
        lines = [ln.strip() for ln in part.split("\n") if ln.strip()]
        if sum(1 for ln in lines if ln.startswith(("- ", "* ", "• "))) >= 2:
            # group bullets into blocks but keep max size bound
            buf = ""
            for ln in lines:
                candidate = (buf + "\n" + ln).strip() if buf else ln
                if len(candidate) > PATCH_MAX_CHARS and buf:
                    blocks.append(buf)
                    buf = ln
                else:
                    buf = candidate
            if buf:
                blocks.append(buf)
        else:
            blocks.append(part)

    # Now pack blocks into patches under PATCH_MAX_CHARS
    patches: List[str] = []
    buf = ""
    for blk in blocks:
        candidate = (buf + "\n\n" + blk).strip() if buf else blk
        if len(candidate) > PATCH_MAX_CHARS and buf:
            patches.append(buf)
            buf = blk
        else:
            buf = candidate
    if buf:
        patches.append(buf)

    # Merge small tail fragments
    merged: List[str] = []
    i = 0
    while i < len(patches):
        p = patches[i].strip()
        if not p:
            i += 1
            continue
        if len(p) < PATCH_MIN_CHARS and merged:
            prev = merged[-1]
            candidate = (prev + "\n\n" + p).strip()
            if len(candidate) <= int(PATCH_MAX_CHARS * 1.2):
                merged[-1] = candidate
            else:
                merged.append(p)
        else:
            merged.append(p)
        i += 1

    return merged


def _apply_reconsolidation_meta(
    previous_meta: Optional[Dict[str, Any]],
    new_meta: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    prev = dict(previous_meta or {})
    nxt = dict(new_meta or {})

    prev_outcome = _safe_float(prev.get("outcome_quality"), 0.50)
    next_outcome = _safe_float(nxt.get("outcome_quality"), prev_outcome)

    recon_prev = prev.get("reconsolidation") if isinstance(prev.get("reconsolidation"), dict) else {}
    updates = int(recon_prev.get("updates") or 0) + 1

    prev_ema = _safe_float(recon_prev.get("outcome_quality_ema"), prev_outcome)
    outcome_ema = _clamp01((0.70 * prev_ema) + (0.30 * next_outcome))

    history = recon_prev.get("outcome_history") if isinstance(recon_prev.get("outcome_history"), list) else []
    history = [h for h in history if isinstance(h, (int, float))]
    history.append(round(next_outcome, 4))
    history = history[-6:]

    nxt["reconsolidation"] = {
        "updates": updates,
        "last_outcome_delta": round(next_outcome - prev_outcome, 4),
        "outcome_quality_ema": round(outcome_ema, 4),
        "outcome_history": history,
        "last_updated_at": time.time(),
    }
    return nxt


def _upsert_entry_raw(
    conn: sqlite3.Connection,
    *,
    memory_id: str,
    content: str,
    scope: str,
    project_key: Optional[str],
    category: str,
    created_at: float,
    source: str,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    existing_row = conn.execute(
        "SELECT meta FROM memories WHERE memory_id = ?",
        (memory_id,),
    ).fetchone()
    if existing_row is not None:
        try:
            prev_meta = _parse_meta(existing_row["meta"])
            meta = _apply_reconsolidation_meta(prev_meta, meta)
        except Exception:
            pass

    conn.execute(
        """
        INSERT OR REPLACE INTO memories
        (memory_id, content, scope, project_key, category, created_at, source, meta)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            memory_id,
            content,
            scope,
            project_key,
            category,
            created_at,
            source,
            json.dumps(meta or {}),
        ),
    )

    if _ensure_fts(conn):
        conn.execute("DELETE FROM memories_fts WHERE memory_id = ?", (memory_id,))
        conn.execute(
            "INSERT INTO memories_fts (content, memory_id, scope, project_key, category) VALUES (?, ?, ?, ?, ?)",
            (content, memory_id, scope, project_key or "", category),
        )

    vectors = _embed_texts([content])
    if vectors:
        vec = vectors[0]
        conn.execute(
            "INSERT OR REPLACE INTO memories_vec (memory_id, dim, vector) VALUES (?, ?, ?)",
            (memory_id, len(vec), _vector_to_blob(vec)),
        )

    _link_edges(conn, memory_id, project_key, scope, created_at)


def upsert_entry(
    *,
    memory_id: str,
    content: str,
    scope: str,
    project_key: Optional[str],
    category: str,
    created_at: float,
    source: str,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    if _is_telemetry_memory(content):
        return

    meta = _with_memory_emotion_meta(meta)
    meta = _with_memory_learning_meta(meta, category=category, content=content)

    # Delta compaction: if this is near-duplicate of a recent memory, store only the delta.
    if DELTAS_ENABLED and content and len(content) >= 240:
        conn = _connect()
        try:
            best = _find_recent_similar(
                conn,
                content=content,
                scope=scope,
                project_key=project_key,
                category=category,
            )
        finally:
            conn.close()

        if best:
            base_id, base_text, sim = best
            if sim >= float(DELTA_MIN_SIMILARITY):
                delta = _best_delta(base_text, content)
                # Only accept meaningful deltas.
                if delta and len(delta) >= 80:
                    meta = dict(meta or {})
                    meta.update({
                        "delta": True,
                        "delta_from": base_id,
                        "delta_similarity": round(float(sim), 4),
                    })
                    content = f"Update (delta from {base_id}): {delta}".strip()

    # Patchified mode: store a compact root + chunk entries for better retrieval precision.
    if PATCHIFIED_ENABLED and content and len(content) > PATCH_MAX_CHARS:
        patches = _split_patches(content)
        if len(patches) >= 2:
            conn = _connect()
            try:
                root_meta = dict(meta or {})
                root_meta.update({
                    "patchified": True,
                    "patch_count": len(patches),
                    "patch_max_chars": PATCH_MAX_CHARS,
                    "patch_min_chars": PATCH_MIN_CHARS,
                })
                # Root stores first patch (not the full content) to keep DB light.
                _upsert_entry_raw(
                    conn,
                    memory_id=memory_id,
                    content=patches[0],
                    scope=scope,
                    project_key=project_key,
                    category=category,
                    created_at=created_at,
                    source=source,
                    meta=root_meta,
                )

                for idx, patch in enumerate(patches[1:], start=1):
                    pid = f"{memory_id}#p{idx}"
                    pmeta = dict(meta or {})
                    pmeta.update({
                        "parent_id": memory_id,
                        "patch_index": idx,
                        "patch_count": len(patches),
                        "patchified": True,
                    })
                    _upsert_entry_raw(
                        conn,
                        memory_id=pid,
                        content=patch,
                        scope=scope,
                        project_key=project_key,
                        category=category,
                        created_at=created_at,
                        source=source,
                        meta=pmeta,
                    )

                conn.commit()
                return
            finally:
                conn.close()

    conn = _connect()
    try:
        _upsert_entry_raw(
            conn,
            memory_id=memory_id,
            content=content,
            scope=scope,
            project_key=project_key,
            category=category,
            created_at=created_at,
            source=source,
            meta=meta,
        )
        conn.commit()
    finally:
        conn.close()


def _fetch_vectors(conn: sqlite3.Connection, ids: Iterable[str]) -> Dict[str, List[float]]:
    id_list = [i for i in ids if i]
    if not id_list:
        return {}
    conn.execute("DROP TABLE IF EXISTS _tmp_memory_ids")
    conn.execute("CREATE TEMP TABLE _tmp_memory_ids (memory_id TEXT PRIMARY KEY)")
    conn.executemany(
        "INSERT OR IGNORE INTO _tmp_memory_ids(memory_id) VALUES (?)",
        [(memory_id,) for memory_id in id_list],
    )
    rows = conn.execute(
        """
        SELECT v.memory_id, v.vector
        FROM memories_vec v
        JOIN _tmp_memory_ids t ON t.memory_id = v.memory_id
        """,
    ).fetchall()
    out: Dict[str, List[float]] = {}
    for r in rows:
        out[r["memory_id"]] = _blob_to_vector(r["vector"])
    return out


def _is_telemetry_memory(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    tl = t.lower()
    if t.startswith("Sequence '") or t.startswith('Sequence "'):
        return True
    if "sequence" in tl and ("worked" in tl or "pattern" in tl):
        return True
    if t.startswith("Pattern '") and "->" in t and "risky" not in tl:
        return True
    if "->" in t and any(s in tl for s in ["sequence", "pattern", "worked well", "works well"]):
        return True
    if "heavy " in tl and " usage" in tl:
        return True
    if "usage count" in tl or "usage (" in tl:
        return True
    if t.startswith("User was satisfied after:") or t.startswith("User frustrated after:"):
        return True
    return False


def _chunked(items: List[str], size: int = 200) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def purge_telemetry_memories(
    *,
    dry_run: bool = True,
    max_preview: int = 20,
) -> Dict[str, Any]:
    """Purge telemetry/sequence noise from memory_store."""
    conn = _connect()
    try:
        rows = conn.execute("SELECT memory_id, content FROM memories").fetchall()
        to_delete: List[str] = []
        preview: List[str] = []
        for r in rows:
            content = r["content"] or ""
            if _is_telemetry_memory(content):
                to_delete.append(r["memory_id"])
                if len(preview) < max(0, int(max_preview or 0)):
                    preview.append(content[:120])

        if not to_delete or dry_run:
            return {"removed": len(to_delete), "preview": preview, "dry_run": dry_run}

        conn.execute("DROP TABLE IF EXISTS _tmp_memory_ids")
        conn.execute("CREATE TEMP TABLE _tmp_memory_ids (memory_id TEXT PRIMARY KEY)")
        for chunk in _chunked(to_delete, 200):
            conn.execute("DELETE FROM _tmp_memory_ids")
            conn.executemany(
                "INSERT OR IGNORE INTO _tmp_memory_ids(memory_id) VALUES (?)",
                [(memory_id,) for memory_id in chunk],
            )
            conn.execute("DELETE FROM memories WHERE memory_id IN (SELECT memory_id FROM _tmp_memory_ids)")
            if _ensure_fts(conn):
                conn.execute("DELETE FROM memories_fts WHERE memory_id IN (SELECT memory_id FROM _tmp_memory_ids)")
            conn.execute("DELETE FROM memories_vec WHERE memory_id IN (SELECT memory_id FROM _tmp_memory_ids)")
            conn.execute(
                """
                DELETE FROM memory_edges
                WHERE source_id IN (SELECT memory_id FROM _tmp_memory_ids)
                   OR target_id IN (SELECT memory_id FROM _tmp_memory_ids)
                """,
            )
        conn.commit()
        return {"removed": len(to_delete), "preview": preview, "dry_run": dry_run}
    finally:
        conn.close()


def _parse_meta(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def retrieve(
    query: str,
    *,
    project_key: Optional[str] = None,
    limit: int = 6,
    candidate_limit: int = 50,
) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []

    conn = _connect()
    try:
        items: List[Dict[str, Any]] = []

        if _ensure_fts(conn):
            fts_query = _build_fts_query(q)
            if not fts_query:
                return []
            if project_key:
                rows = conn.execute(
                    """
                    SELECT m.memory_id, m.content, m.scope, m.project_key, m.category, m.meta,
                           bm25(memories_fts) AS bm25
                    FROM memories_fts
                    JOIN memories m ON m.memory_id = memories_fts.memory_id
                    WHERE memories_fts MATCH ? AND (m.scope = 'global' OR m.project_key = ?)
                    ORDER BY bm25
                    LIMIT ?;
                    """,
                    [fts_query, project_key, max(10, int(candidate_limit))],
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT m.memory_id, m.content, m.scope, m.project_key, m.category, m.meta,
                           bm25(memories_fts) AS bm25
                    FROM memories_fts
                    JOIN memories m ON m.memory_id = memories_fts.memory_id
                    WHERE memories_fts MATCH ?
                    ORDER BY bm25
                    LIMIT ?;
                    """,
                    [fts_query, max(10, int(candidate_limit))],
                ).fetchall()

            for r in rows:
                content = r["content"] or ""
                if _is_telemetry_memory(content):
                    continue
                bm25 = float(r["bm25"]) if r["bm25"] is not None else 0.0
                bm25 = max(0.0, bm25)
                lex = 1.0 / (1.0 + bm25)
                meta = _parse_meta(r["meta"])
                parent_id = str(meta.get("parent_id") or "").strip() or None
                items.append({
                    "entry_id": r["memory_id"],
                    "text": content,
                    "scope": r["scope"],
                    "project_key": r["project_key"],
                    "category": r["category"],
                    "bm25": bm25,
                    "score": lex,
                    "meta": meta,
                    "parent_id": parent_id,
                    "patch_index": meta.get("patch_index"),
                })
        else:
            # FTS not available; fallback to simple scan
            rows = conn.execute(
                """
                SELECT memory_id, content, scope, project_key, category, meta
                FROM memories
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (max(200, int(candidate_limit)),),
            ).fetchall()
            q_lower = q.lower()
            q_words = [w for w in q_lower.split() if len(w) > 2]
            for r in rows:
                content = r["content"] or ""
                if _is_telemetry_memory(content):
                    continue
                text = content.lower()
                score = 0.0
                if q_lower in text:
                    score += 2.0
                for w in q_words[:8]:
                    if w in text:
                        score += 0.25
                if project_key and r["project_key"] == project_key:
                    score += 0.4
                if score <= 0.25:
                    continue
                meta = _parse_meta(r["meta"])
                parent_id = str(meta.get("parent_id") or "").strip() or None
                items.append({
                    "entry_id": r["memory_id"],
                    "text": content,
                    "scope": r["scope"],
                    "project_key": r["project_key"],
                    "category": r["category"],
                    "bm25": None,
                    "score": score,
                    "meta": meta,
                    "parent_id": parent_id,
                    "patch_index": meta.get("patch_index"),
                })

        if not items:
            return []

        vectors = _embed_texts([q])
        if vectors:
            qvec = vectors[0]
            vecs = _fetch_vectors(conn, [i["entry_id"] for i in items])
            for it in items:
                vec = vecs.get(it["entry_id"])
                if vec:
                    cos = _cosine(qvec, vec)
                    it["score"] = (0.6 * it["score"]) + (0.4 * cos)

        guard_cfg = _load_memory_retrieval_guard_config()
        guard_enabled = bool(guard_cfg.get("enabled", True))
        base_floor = float(guard_cfg.get("base_score_floor") or 0.0)
        max_total_boost = float(guard_cfg.get("max_total_boost") or 0.0)

        for it in items:
            it["base_score"] = float(it.get("score") or 0.0)
            it["total_context_boost"] = 0.0

        emotion_cfg = _load_memory_emotion_config()
        active_state = _current_retrieval_emotion_state() if emotion_cfg.get("enabled") else None
        if emotion_cfg.get("enabled") and active_state:
            state_weight = float(emotion_cfg.get("retrieval_state_match_weight") or 0.0)
            min_state_sim = float(emotion_cfg.get("retrieval_min_state_similarity") or 0.0)
            if state_weight > 0.0:
                for it in items:
                    meta = it.get("meta") if isinstance(it, dict) else None
                    mem_state = meta.get("emotion") if isinstance(meta, dict) else None
                    state_match = _emotion_state_similarity(active_state, mem_state)
                    if state_match < min_state_sim:
                        state_match = 0.0
                    state_boost = state_weight * state_match

                    eligible = True
                    if guard_enabled and (float(it.get("total_context_boost") or 0.0) + state_boost) > max_total_boost:
                        remaining = max(0.0, max_total_boost - float(it.get("total_context_boost") or 0.0))
                        state_boost = min(state_boost, remaining * max(0.0, state_match))

                    if state_boost > 0.0 and eligible:
                        it["score"] += state_boost
                        it["total_context_boost"] = float(it.get("total_context_boost") or 0.0) + state_boost
                    it["emotion_state_match"] = round(state_match, 4)
                    it["emotion_score_boost"] = round(state_boost if eligible else 0.0, 4)

        # Learning lane: calm but important learnings should still rank strongly.
        learning_cfg = _load_memory_learning_config()
        if learning_cfg.get("enabled"):
            learning_weight = float(learning_cfg.get("retrieval_learning_weight") or 0.0)
            min_signal = float(learning_cfg.get("retrieval_min_learning_signal") or 0.0)
            calm_bonus = float(learning_cfg.get("calm_mode_bonus") or 0.0)
            is_calm_mode = bool(
                active_state and str(active_state.get("primary_emotion") or "steady") in {"steady", "calm", "reflective"}
            )
            if learning_weight > 0.0:
                for it in items:
                    meta = it.get("meta") if isinstance(it, dict) else None
                    learn = meta.get("learning") if isinstance(meta, dict) else None
                    if not isinstance(learn, dict):
                        continue
                    priority = _clamp01(_safe_float(learn.get("priority"), 0.0))
                    outcome_quality = _clamp01(
                        _safe_float(learn.get("outcome_quality"), _safe_float(meta.get("outcome_quality"), 0.5) if isinstance(meta, dict) else 0.5)
                    )
                    learning_signal = _clamp01((0.65 * priority) + (0.35 * outcome_quality))
                    if learning_signal < min_signal:
                        learning_signal = 0.0
                    learning_boost = learning_weight * learning_signal
                    if is_calm_mode and bool(learn.get("calm_important")):
                        learning_boost += calm_bonus * learning_signal

                    eligible = True
                    if guard_enabled and float(it.get("base_score") or 0.0) < base_floor:
                        eligible = False
                    if guard_enabled and (float(it.get("total_context_boost") or 0.0) + learning_boost) > max_total_boost:
                        learning_boost = max(0.0, max_total_boost - float(it.get("total_context_boost") or 0.0))

                    if learning_boost > 0.0 and eligible:
                        it["score"] += learning_boost
                        it["total_context_boost"] = float(it.get("total_context_boost") or 0.0) + learning_boost
                    it["learning_signal"] = round(learning_signal, 4)
                    it["learning_score_boost"] = round(learning_boost if eligible else 0.0, 4)

        items.sort(key=lambda i: i.get("score", 0.0), reverse=True)

        def _dedupe_parent(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            deduped: List[Dict[str, Any]] = []
            seen_parent: set[str] = set()
            for it in rows or []:
                parent_key = str(it.get("parent_id") or it.get("entry_id") or "").strip()
                if parent_key and parent_key in seen_parent:
                    continue
                if parent_key:
                    seen_parent.add(parent_key)
                deduped.append(it)
            return deduped

        # Patchified dedupe: keep at most one hit per parent group to reduce noise.
        items = _dedupe_parent(items)

        # Edge expansion (graph-lite): add related items with small score boost.
        want = max(0, int(limit or 0))
        if want <= 0:
            return []
        if len(items) >= want:
            return items[:want]

        seed_ids = [i["entry_id"] for i in items[: min(5, len(items))] if i.get("entry_id")]
        if not seed_ids:
            return items[:want]

        conn.execute("DROP TABLE IF EXISTS _tmp_seed_ids")
        conn.execute("CREATE TEMP TABLE _tmp_seed_ids (memory_id TEXT PRIMARY KEY)")
        conn.executemany(
            "INSERT OR IGNORE INTO _tmp_seed_ids(memory_id) VALUES (?)",
            [(memory_id,) for memory_id in seed_ids],
        )
        edge_rows = conn.execute(
            """
            SELECT source_id, target_id, weight, reason
            FROM memory_edges
            WHERE source_id IN (SELECT memory_id FROM _tmp_seed_ids)
            ORDER BY weight DESC
            LIMIT 25;
            """,
        ).fetchall()

        edge_targets = []
        for r in edge_rows:
            edge_targets.append((r["target_id"], float(r["weight"] or 0.0), r["reason"]))

        if not edge_targets:
            return items[:want]

        existing = {i["entry_id"] for i in items}
        target_ids = [t[0] for t in edge_targets if t[0] and t[0] not in existing]
        if not target_ids:
            return items[:want]

        conn.execute("DROP TABLE IF EXISTS _tmp_target_ids")
        conn.execute("CREATE TEMP TABLE _tmp_target_ids (memory_id TEXT PRIMARY KEY)")
        conn.executemany(
            "INSERT OR IGNORE INTO _tmp_target_ids(memory_id) VALUES (?)",
            [(memory_id,) for memory_id in target_ids],
        )
        rows = conn.execute(
            """
            SELECT memory_id, content, scope, project_key, category, meta
            FROM memories
            WHERE memory_id IN (SELECT memory_id FROM _tmp_target_ids);
            """,
        ).fetchall()
        row_map = {r["memory_id"]: r for r in rows}

        for tid, weight, reason in edge_targets:
            if len(items) >= want:
                break
            if tid in existing:
                continue
            r = row_map.get(tid)
            if not r:
                continue
            if _is_telemetry_memory(r["content"] or ""):
                continue
            if project_key and r["project_key"] not in (project_key, None, "") and r["scope"] != "global":
                continue
            meta = _parse_meta(r["meta"])
            parent_id = str(meta.get("parent_id") or "").strip() or None
            # Skip patch chunks if we already have the parent in results.
            if parent_id and parent_id in existing:
                continue
            items.append({
                "entry_id": r["memory_id"],
                "text": r["content"],
                "scope": r["scope"],
                "project_key": r["project_key"],
                "category": r["category"],
                "bm25": None,
                "score": 0.15 * weight,
                "edge_reason": reason,
                "meta": meta,
                "parent_id": parent_id,
                "patch_index": meta.get("patch_index"),
            })
            existing.add(tid)
            if parent_id:
                existing.add(parent_id)

        items.sort(key=lambda i: i.get("score", 0.0), reverse=True)
        items = _dedupe_parent(items)
        return items[:want]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Hot-reload registration
# ---------------------------------------------------------------------------

def _reload_memory_store_from(_cfg) -> None:
    """Hot-reload callback — force-refresh all 3 config caches."""
    _load_memory_emotion_config(force=True)
    _load_memory_learning_config(force=True)
    _load_memory_retrieval_guard_config(force=True)


try:
    from .tuneables_reload import register_reload as _ms_register
    _ms_register("memory_emotion", _reload_memory_store_from, label="memory_store.reload.emotion")
    _ms_register("memory_learning", _reload_memory_store_from, label="memory_store.reload.learning")
    _ms_register("memory_retrieval_guard", _reload_memory_store_from, label="memory_store.reload.guard")
except Exception:
    pass
