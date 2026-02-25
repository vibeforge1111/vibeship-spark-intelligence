"""Semantic retrieval for cognitive insights (hybrid: triggers + semantic + outcomes).

Designed to be low-risk:
- Disabled by default unless enabled in ~/.spark/tuneables.json or SPARK_SEMANTIC_ENABLED=1
- Falls back gracefully if embeddings are unavailable
- Uses lightweight SQLite index for vectors
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .config_authority import env_bool, resolve_section
from .embeddings import embed_text, embed_texts
from .diagnostics import log_debug


DEFAULT_CONFIG = {
    "enabled": True,  # Enabled by default — falls back gracefully if fastembed unavailable
    "embedding_provider": "local",
    "embedding_model": "BAAI/bge-small-en-v1.5",
    "min_similarity": 0.55,
    "min_fusion_score": 0.50,
    # Avoid total empty collapse when strict gates over-filter all candidates.
    "empty_result_rescue_enabled": True,
    "rescue_min_similarity": 0.30,
    "rescue_min_fusion_score": 0.20,
    "weight_recency": 0.2,
    "weight_outcome": 0.3,
    "mmr_lambda": 0.5,
    "dedupe_similarity": 0.92,
    "max_results": 8,
    "index_on_write": True,
    "index_on_read": True,
    "index_backfill_limit": 500,
    "index_cache_ttl_seconds": 120,
    "exclude_categories": [],
    "trigger_rules_file": "~/.spark/trigger_rules.yaml",
    "category_caps": {
        "cognitive": 3,
        "trigger": 2,
        "default": 2,
    },
    "category_exclude": [],
    "triggers_enabled": False,
    "log_retrievals": True,
    # Log file safety (prevent unbounded growth)
    "log_max_bytes": 5 * 1024 * 1024,  # 5MB
    "log_backups": 3,
    # Optional sampling to reduce disk I/O on hot path.
    # 1.0 = log every retrieval, 0.1 = log ~10%, 0.0 = log none.
    "log_sample_rate": 1.0,
}


def _rotate_log_if_needed(path: Path, max_bytes: int, backups: int = 3) -> None:
    """Rotate a JSONL log if it exceeds max_bytes.

    Keeps up to `backups` rotated files: <name>.jsonl.1, .2, ...
    """
    try:
        if max_bytes <= 0 or not path.exists():
            return
        size = path.stat().st_size
        if size <= max_bytes:
            return
        backups = max(0, int(backups or 0))

        # Shift existing rotations
        for i in range(backups, 0, -1):
            src = path.with_suffix(path.suffix + f".{i}")
            dst = path.with_suffix(path.suffix + f".{i + 1}")
            if src.exists():
                if i == backups:
                    src.unlink(missing_ok=True)
                else:
                    src.replace(dst)

        # Rotate current log to .1
        rotated = path.with_suffix(path.suffix + ".1")
        path.replace(rotated)
    except Exception:
        return



DEFAULT_TRIGGER_RULES = {
    "version": 1,
    "rules": [
        {
            "name": "auth_security",
            "pattern": r"auth|login|password|token|session|jwt|oauth",
            "priority": "high",
            "surface_text": [
                "Validate authentication inputs server-side and avoid trusting client checks.",
                "Never log secrets or tokens; redact sensitive data in logs.",
            ],
        },
        {
            "name": "destructive_commands",
            "pattern": r"rm -rf|delete.*prod|drop table|truncate",
            "priority": "critical",
            "interrupt": True,
            "surface_text": [
                "Double-check destructive commands and confirm targets before executing.",
                "Run a dry-run or backup before irreversible operations.",
            ],
        },
        {
            "name": "deployment",
            "pattern": r"deploy|release|push.*main|merge.*master|prod",
            "priority": "high",
            "surface_text": [
                "Before deploy: run tests, verify migrations, and confirm env vars.",
            ],
        },
    ],
    "learned": [],
}


@dataclass
class TriggerMatch:
    rule_name: str
    priority: str
    surface: List[str]
    surface_text: List[str]
    interrupt: bool = False


@dataclass
class SemanticResult:
    insight_key: str
    insight_text: str
    semantic_sim: float = 0.0
    trigger_conf: float = 0.0
    recency_score: float = 0.0
    outcome_score: float = 0.5
    fusion_score: float = 0.0
    source_type: str = "semantic"  # semantic | trigger | both
    category: str = "cognitive"
    priority: str = "normal"
    why: str = ""


class TriggerMatcher:
    def __init__(self, rules_file: Optional[str] = None):
        self.rules_file = rules_file
        self.rules = self._load_rules()

    def _load_rules(self) -> Dict[str, Any]:
        rules = DEFAULT_TRIGGER_RULES
        path = Path(os.path.expanduser(self.rules_file or ""))
        if path and path.exists():
            try:
                import yaml
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("rules"):
                    rules = data
            except Exception:
                pass
        return rules

    def match(self, context: str) -> List[TriggerMatch]:
        if not context:
            return []
        matches: List[TriggerMatch] = []
        ctx = context.lower()
        for rule in self.rules.get("rules", []) or []:
            pattern = rule.get("pattern") or ""
            if not pattern:
                continue
            try:
                if not re.search(pattern, ctx, re.IGNORECASE):
                    continue
            except re.error:
                continue
            context_pattern = rule.get("context_pattern")
            if context_pattern:
                try:
                    if not re.search(context_pattern, ctx, re.IGNORECASE):
                        continue
                except re.error:
                    continue
            matches.append(
                TriggerMatch(
                    rule_name=str(rule.get("name") or "rule"),
                    priority=str(rule.get("priority") or "normal"),
                    surface=list(rule.get("surface") or []),
                    surface_text=list(rule.get("surface_text") or []),
                    interrupt=bool(rule.get("interrupt") or False),
                )
            )
        return matches


class SemanticIndex:
    def __init__(self, path: Optional[Path] = None, cache_ttl_s: int = 120):
        self.path = path or (Path.home() / ".spark" / "semantic" / "insights_vec.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_ttl_s = cache_ttl_s
        self._cache_ts = 0.0
        self._cache: Optional[List[Tuple[str, List[float], float]]] = None
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS insights_vec (
                    insight_key TEXT PRIMARY KEY,
                    content_hash TEXT,
                    dim INTEGER,
                    vector BLOB,
                    updated_at REAL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _vector_to_blob(self, vec: List[float]) -> bytes:
        import array
        arr = array.array("f", vec)
        return arr.tobytes()

    def _blob_to_vector(self, blob: bytes) -> List[float]:
        import array
        arr = array.array("f")
        arr.frombytes(blob)
        return list(arr)

    def _hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    def _invalidate_cache(self) -> None:
        self._cache = None
        self._cache_ts = 0.0

    def _load_cache(self) -> List[Tuple[str, List[float], float]]:
        now = time.time()
        if self._cache is not None and now - self._cache_ts < self.cache_ttl_s:
            return self._cache
        items: List[Tuple[str, List[float], float]] = []
        with self._connect() as conn:
            rows = conn.execute("SELECT insight_key, vector FROM insights_vec").fetchall()
        for row in rows:
            vec = self._blob_to_vector(row["vector"])
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            items.append((row["insight_key"], vec, norm))
        self._cache = items
        self._cache_ts = now
        return items

    def existing_hashes(self) -> Dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT insight_key, content_hash FROM insights_vec").fetchall()
        return {r["insight_key"]: r["content_hash"] for r in rows}

    def add_many(self, items: List[Tuple[str, str]]) -> int:
        if not items:
            return 0
        hashes = self.existing_hashes()
        to_embed: List[Tuple[str, str, str]] = []
        for key, text in items:
            if not text:
                continue
            content_hash = self._hash_text(text)
            if hashes.get(key) == content_hash:
                continue
            to_embed.append((key, text, content_hash))
        if not to_embed:
            return 0

        vectors = embed_texts([t for _, t, _ in to_embed])
        if not vectors:
            return 0

        now = time.time()
        with self._connect() as conn:
            for (key, _, content_hash), vec in zip(to_embed, vectors):
                conn.execute(
                    "INSERT OR REPLACE INTO insights_vec (insight_key, content_hash, dim, vector, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (key, content_hash, len(vec), self._vector_to_blob(vec), now),
                )
            conn.commit()

        self._invalidate_cache()
        return len(to_embed)

    def add(self, key: str, text: str) -> bool:
        return self.add_many([(key, text)]) > 0

    def upsert(self, key: str, vector: List[float]) -> bool:
        """Upsert a precomputed vector directly (no embedding)."""
        if not key or not vector:
            return False
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO insights_vec (insight_key, content_hash, dim, vector, updated_at) VALUES (?, ?, ?, ?, ?)",
                (key, None, len(vector), self._vector_to_blob(vector), now),
            )
            conn.commit()
        self._invalidate_cache()
        return True

    def get(self, key: str) -> Optional[List[float]]:
        """Return a vector for a given insight_key if present."""
        if not key:
            return None
        items = self._load_cache()
        for k, vec, _ in items:
            if k == key:
                return vec
        return None

    def ensure_index(
        self,
        insights: Dict[str, Any],
        max_items: int = 300,
        noise_filter: Any = None,
    ) -> int:
        """Index missing or stale insights, filtering noise.

        Args:
            insights: dict of insight_key -> insight object
            max_items: max items to embed in a single call (batch limit)
            noise_filter: optional callable(text) -> bool that returns True for noise
        """
        if not insights:
            return 0
        hashes = self.existing_hashes()

        def _score(item: Tuple[str, Any]) -> float:
            _, insight = item
            rel = getattr(insight, "reliability", 0.5)
            return rel

        items = sorted(insights.items(), key=_score, reverse=True)
        missing: List[Tuple[str, str]] = []
        for key, insight in items:
            text = f"{getattr(insight, 'insight', '')} {getattr(insight, 'context', '')}".strip()
            if not text:
                continue
            # Skip noise insights
            if noise_filter and noise_filter(text):
                continue
            content_hash = self._hash_text(text)
            if hashes.get(key) == content_hash:
                continue
            missing.append((key, text))
            if len(missing) >= max_items:
                break
        return self.add_many(missing)

    def prune_stale(self, valid_keys: set) -> int:
        """Remove entries from the index that are no longer in the insights dict.

        Returns count of pruned entries.
        """
        if not valid_keys:
            return 0
        pruned = 0
        with self._connect() as conn:
            rows = conn.execute("SELECT insight_key FROM insights_vec").fetchall()
            for row in rows:
                if row["insight_key"] not in valid_keys:
                    conn.execute("DELETE FROM insights_vec WHERE insight_key = ?", (row["insight_key"],))
                    pruned += 1
            if pruned:
                conn.commit()
        if pruned:
            self._invalidate_cache()
        return pruned

    def count(self) -> int:
        """Return the number of indexed entries."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM insights_vec").fetchone()
            return row[0] if row else 0

    def search(self, query_vec: List[float], limit: int = 10) -> List[Tuple[str, float]]:
        if not query_vec:
            return []
        qnorm = math.sqrt(sum(x * x for x in query_vec)) or 1.0
        items = self._load_cache()
        scores: List[Tuple[str, float]] = []
        for key, vec, vnorm in items:
            dot = 0.0
            for a, b in zip(query_vec, vec):
                dot += a * b
            sim = dot / (qnorm * vnorm)
            scores.append((key, sim))
        scores.sort(key=lambda t: t[1], reverse=True)
        return scores[:limit]


class SemanticRetriever:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or _load_config()
        self.trigger_matcher = TriggerMatcher(self.config.get("trigger_rules_file"))
        self.index = SemanticIndex(cache_ttl_s=int(self.config.get("index_cache_ttl_seconds", 120)))
        self._index_warmed = False

    def retrieve(self, context: str, insights: Dict[str, Any], limit: int = 8) -> List[SemanticResult]:
        if not context:
            return []

        start_ts = time.time()
        query = self._extract_intent(context)
        results: List[SemanticResult] = []
        seen: set[str] = set()
        trigger_matches: List[TriggerMatch] = []
        semantic_candidates: List[Tuple[str, float]] = []
        embedding_available = False

        # Trigger rules (optional)
        if self.config.get("triggers_enabled", False):
            trigger_matches = self.trigger_matcher.match(context)
            for match in trigger_matches:
                for text in match.surface_text or []:
                    key = f"trigger:{match.rule_name}:{hashlib.sha1(text.encode()).hexdigest()[:8]}"
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append(
                        SemanticResult(
                            insight_key=key,
                            insight_text=text,
                            trigger_conf=1.0,
                            source_type="trigger",
                            category="trigger",
                            priority=match.priority,
                            why=f"Trigger: {match.rule_name}",
                        )
                    )
                for surface in match.surface or []:
                    # Exact key match
                    if surface in insights and surface not in seen:
                        seen.add(surface)
                        ins = insights[surface]
                        results.append(
                            SemanticResult(
                                insight_key=surface,
                                insight_text=getattr(ins, "insight", ""),
                                trigger_conf=1.0,
                                source_type="trigger",
                                category=self._infer_category(ins),
                                priority=match.priority,
                                why=f"Trigger: {match.rule_name}",
                            )
                        )
                        continue
                    # Fallback: find insights containing surface token
                    surface_lower = surface.lower()
                    for key, ins in insights.items():
                        if key in seen:
                            continue
                        text = getattr(ins, "insight", "") or ""
                        if surface_lower and surface_lower in text.lower():
                            seen.add(key)
                            results.append(
                                SemanticResult(
                                    insight_key=key,
                                    insight_text=text,
                                    trigger_conf=1.0,
                                    source_type="trigger",
                                    category=self._infer_category(ins),
                                    priority=match.priority,
                                    why=f"Trigger: {match.rule_name}",
                                )
                            )

        # Ensure index warmed (with noise filtering)
        if self.config.get("index_on_read", True) and not self._index_warmed:
            try:
                noise_fn = self._get_noise_filter()
                self.index.ensure_index(
                    insights,
                    max_items=int(self.config.get("index_backfill_limit", 300)),
                    noise_filter=noise_fn,
                )
            finally:
                self._index_warmed = True

        # Semantic search
        qvec = embed_text(query)
        if qvec:
            embedding_available = True
            semantic_candidates = self.index.search(qvec, limit=limit * 3)
            for key, sim in semantic_candidates:
                if key in seen:
                    continue
                insight = insights.get(key)
                if not insight:
                    continue
                seen.add(key)
                results.append(
                    SemanticResult(
                        insight_key=key,
                        insight_text=getattr(insight, "insight", ""),
                        semantic_sim=sim,
                        source_type="semantic",
                        category=self._infer_category(insight),
                        priority=self._infer_priority(sim),
                        why=f"Semantic: {sim:.2f} similar",
                    )
                )
        else:
            # Keyword fallback when embeddings unavailable (graceful degradation)
            query_lower = query.lower()
            query_words = set(re.findall(r"[a-z0-9]+", query_lower))
            if query_words:
                scored: List[Tuple[float, str, Any]] = []
                for key, insight in insights.items():
                    if key in seen:
                        continue
                    text = getattr(insight, "insight", "") or ""
                    ctx = getattr(insight, "context", "") or ""
                    combined = f"{text} {ctx}".lower()
                    combined_words = set(re.findall(r"[a-z0-9]+", combined))
                    if not combined_words:
                        continue
                    overlap = len(query_words & combined_words)
                    if overlap == 0:
                        continue
                    jaccard = overlap / len(query_words | combined_words)
                    scored.append((jaccard, key, insight))
                scored.sort(key=lambda t: t[0], reverse=True)
                for jaccard, key, insight in scored[:limit * 2]:
                    if key in seen:
                        continue
                    seen.add(key)
                    # Map jaccard to a pseudo-similarity score
                    pseudo_sim = min(1.0, 0.5 + jaccard)
                    results.append(
                        SemanticResult(
                            insight_key=key,
                            insight_text=getattr(insight, "insight", ""),
                            semantic_sim=pseudo_sim,
                            source_type="semantic",
                            category=self._infer_category(insight),
                            priority=self._infer_priority(pseudo_sim),
                            why=f"Keyword: {jaccard:.2f} overlap (no embeddings)",
                        )
                    )

        # Enrich scores
        for r in results:
            insight = insights.get(r.insight_key)
            if insight:
                r.recency_score = self._compute_recency(insight)
                r.outcome_score = self._get_outcome_effectiveness(r.insight_key, insight)

        # Filter noise insights from results (semantic only, triggers are pre-curated)
        noise_fn = self._get_noise_filter()
        if noise_fn:
            results = [
                r for r in results
                if r.source_type == "trigger" or not noise_fn(r.insight_text)
            ]

        # Category exclusions (semantic results only)
        exclude = set(self.config.get("category_exclude") or [])
        if exclude:
            results = [
                r for r in results
                if r.source_type == "trigger" or (r.category not in exclude)
            ]
        pre_gate_results = list(results)

        # Gate: semantic similarity (triggers bypass)
        min_sim = float(self.config.get("min_similarity", 0.55))
        results = [
            r for r in results
            if r.source_type == "trigger" or r.semantic_sim >= min_sim
        ]

        # Exclude noisy categories if configured
        exclude = {str(c).lower() for c in (self.config.get("exclude_categories") or []) if c}
        if exclude:
            results = [
                r for r in results
                if (r.category or "").lower() not in exclude
            ]

        # Fusion score (RRF: rank-based combination of semantic + outcome signals)
        self._compute_fusion_scores_rrf(results)

        # Filter by fusion score
        min_fusion = float(self.config.get("min_fusion_score", 0.5))
        results = [r for r in results if r.fusion_score >= min_fusion]
        if not results and self.config.get("empty_result_rescue_enabled", True):
            results = self._rescue_empty_results(
                candidates=pre_gate_results,
                limit=limit,
                min_similarity=min_sim,
                min_fusion_score=min_fusion,
            )

        # Sort by fusion score
        results.sort(key=lambda r: r.fusion_score, reverse=True)

        # Dedupe by embedding similarity (cheap, prevents near-duplicates)
        dedupe_sim = float(self.config.get("dedupe_similarity", 0.0) or 0.0)
        if dedupe_sim > 0:
            results = self._dedupe_by_embedding(results, dedupe_sim)

        # Diversity
        results = self._diversify_mmr(results, lambda_=float(self.config.get("mmr_lambda", 0.5)))
        results = self._cap_by_category(results)

        final_results = results[:limit]

        self._log_retrieval(
            context=context,
            intent=query,
            semantic_candidates_count=len(semantic_candidates),
            trigger_hits=len(trigger_matches),
            results=final_results,
            embedding_available=embedding_available,
            elapsed_ms=int((time.time() - start_ts) * 1000),
        )

        return final_results

    def _rescue_empty_results(
        self,
        *,
        candidates: List[SemanticResult],
        limit: int,
        min_similarity: float,
        min_fusion_score: float,
    ) -> List[SemanticResult]:
        if not candidates:
            return []

        rescue_min_sim = float(
            self.config.get("rescue_min_similarity", min(0.30, min_similarity))
        )
        rescue_min_fusion = float(
            self.config.get("rescue_min_fusion_score", min(0.20, min_fusion_score))
        )
        rescued: List[SemanticResult] = []

        for item in candidates:
            if item.source_type != "trigger" and item.semantic_sim < rescue_min_sim:
                continue
            item.fusion_score = self._compute_fusion(item)
            if item.fusion_score < rescue_min_fusion:
                continue
            if "rescue_fallback" not in item.why:
                item.why = f"{item.why} [rescue_fallback]".strip()
            rescued.append(item)

        if not rescued:
            best = sorted(
                candidates,
                key=lambda r: (self._compute_fusion(r), r.semantic_sim),
                reverse=True,
            )[: max(1, limit)]
            for item in best:
                item.fusion_score = self._compute_fusion(item)
                if "rescue_fallback" not in item.why:
                    item.why = f"{item.why} [rescue_fallback]".strip()
            rescued = best

        log_debug(
            "semantic",
            (
                "SR_EMPTY_RESCUE_USED "
                f"candidates={len(candidates)} "
                f"rescued={len(rescued)} "
                f"rescue_min_sim={rescue_min_sim:.2f} "
                f"rescue_min_fusion={rescue_min_fusion:.2f}"
            ),
        )
        return rescued

    def _compute_fusion(self, r: SemanticResult) -> float:
        w_out = float(self.config.get("weight_outcome", 0.3))
        w_rec = float(self.config.get("weight_recency", 0.2))

        if r.source_type == "trigger":
            base = 0.9 + (r.outcome_score - 0.5) * w_out
        else:
            boosters = (r.outcome_score - 0.5) * w_out + r.recency_score * w_rec
            base = r.semantic_sim * (1 + boosters)

        priority_bonus = {"critical": 0.2, "high": 0.1, "normal": 0.0, "background": -0.1}
        base += priority_bonus.get(r.priority, 0.0)
        return max(0.0, min(1.0, base))

    def _compute_fusion_scores_rrf(self, results: List[SemanticResult]) -> None:
        """Compute fusion scores using Reciprocal Rank Fusion (RRF).

        Combines semantic similarity rank and outcome effectiveness rank:
            score = 1/(k + rank_semantic) + 1/(k + rank_outcome)

        Triggers bypass RRF and use the per-item formula.
        Recency and priority are additive bonuses after RRF normalisation.
        """
        k = float(self.config.get("rrf_k", 30))
        w_rec = float(self.config.get("weight_recency", 0.2))

        semantic: List[SemanticResult] = []
        for r in results:
            if r.source_type == "trigger":
                r.fusion_score = self._compute_fusion(r)
            else:
                semantic.append(r)

        if not semantic:
            return

        n = len(semantic)

        # Rank by semantic similarity (descending, 1-based)
        sim_order = sorted(range(n), key=lambda i: semantic[i].semantic_sim, reverse=True)
        sim_rank = [0] * n
        for rank, idx in enumerate(sim_order):
            sim_rank[idx] = rank + 1

        # Rank by outcome effectiveness (descending, 1-based)
        out_order = sorted(range(n), key=lambda i: semantic[i].outcome_score, reverse=True)
        out_rank = [0] * n
        for rank, idx in enumerate(out_order):
            out_rank[idx] = rank + 1

        # RRF + additive bonuses
        max_rrf = 2.0 / (k + 1)  # Theoretical max (rank 1 in both signals)
        priority_bonus = {"critical": 0.15, "high": 0.08, "normal": 0.0, "background": -0.05}

        for i, r in enumerate(semantic):
            rrf_raw = 1.0 / (k + sim_rank[i]) + 1.0 / (k + out_rank[i])
            normalized = rrf_raw / max_rrf if max_rrf > 0 else 0.0

            normalized += r.recency_score * w_rec * 0.15
            normalized += priority_bonus.get(r.priority, 0.0)

            r.fusion_score = max(0.0, min(1.0, normalized))

    def _compute_recency(self, insight: Any) -> float:
        ts = getattr(insight, "last_validated_at", None) or getattr(insight, "created_at", None)
        if not ts:
            return 0.5
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            age_days = max(0.0, (datetime.now(dt.tzinfo) - dt).total_seconds() / 86400.0)
        except Exception:
            return 0.5
        half_life = float(self.config.get("recency_half_life_days", 60))
        return float(2 ** (-age_days / max(1.0, half_life)))

    def _get_outcome_effectiveness(self, insight_key: str, insight: Any) -> float:
        try:
            from .meta_ralph import get_meta_ralph
            ralph = get_meta_ralph()
            eff = ralph.get_insight_effectiveness(insight_key)
            if eff is not None:
                return float(eff)
        except Exception:
            pass
        return float(getattr(insight, "reliability", 0.5) or 0.5)

    def _get_noise_filter(self):
        """Return a noise filter callable, or None if unavailable."""
        try:
            from .cognitive_learner import get_cognitive_learner
            learner = get_cognitive_learner()
            if hasattr(learner, "is_noise_insight"):
                return learner.is_noise_insight
        except Exception:
            pass
        return None

    def _infer_priority(self, sim: float) -> str:
        if sim >= 0.9:
            return "high"
        if sim >= 0.75:
            return "normal"
        return "background"

    def _infer_category(self, insight: Any) -> str:
        cat = getattr(insight, "category", None)
        if hasattr(cat, "value"):
            return str(cat.value)
        if isinstance(cat, str):
            return cat
        return "cognitive"

    def _extract_intent(self, context: str) -> str:
        """Extract semantic intent from context, stripping tool metadata noise.

        Goal: produce a clean query string that captures WHAT the user is doing,
        not HOW (tool names, file paths, JSON blobs are noise for embedding search).
        """
        # Remove JSON blobs (tool_input serializations)
        intent = re.sub(r"\{[^}]*\}", "", context)
        # Remove file_path=... key-value metadata
        intent = re.sub(r"file_path=\S*", "", intent)
        # Remove common tool input keys that leak into context
        intent = re.sub(r"(old_string|new_string|command|pattern|query)=\S*", "", intent)
        # Collapse whitespace
        intent = re.sub(r"\s+", " ", intent).strip()

        # Strip leading tool name if it's a bare tool name (Edit, Bash, Read, etc.)
        # but keep it if there's meaningful context after it
        tool_names = {"edit", "bash", "read", "write", "grep", "glob", "task",
                      "webfetch", "websearch", "todowrite", "notebookedit"}
        words = intent.split()
        if len(words) >= 2 and words[0].lower() in tool_names:
            # Drop bare tool name prefix, keep the rest as intent
            remaining = " ".join(words[1:])
            # If remaining is meaningful (>10 chars), use it
            if len(remaining) > 10:
                intent = remaining

        # Extract action-focused phrases (keep FULL remaining text, not just the match)
        action_patterns = [
            r"(?:fix(?:ing)?|implement(?:ing)?|add(?:ing)?|updat(?:e|ing)|remov(?:e|ing)|chang(?:e|ing)|creat(?:e|ing)|delet(?:e|ing)|debug(?:ging)?|refactor(?:ing)?)\s+.+",
            r"working on\s+.+",
        ]
        for pattern in action_patterns:
            match = re.search(pattern, intent, re.IGNORECASE)
            if match:
                return match.group(0).strip()

        # Fallback: return cleaned context (up to 30 words for richer embedding)
        return " ".join(intent.split()[:30])

    def _text_similarity(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        aw = set(re.findall(r"[a-z0-9]+", a.lower()))
        bw = set(re.findall(r"[a-z0-9]+", b.lower()))
        if not aw or not bw:
            return 0.0
        return len(aw & bw) / max(1, len(aw | bw))

    def _cosine_sim(self, a: List[float], b: List[float]) -> float:
        if not a or not b:
            return 0.0
        dot = 0.0
        an = 0.0
        bn = 0.0
        for x, y in zip(a, b):
            dot += x * y
            an += x * x
            bn += y * y
        denom = math.sqrt(an) * math.sqrt(bn) or 1.0
        return dot / denom

    def _dedupe_by_embedding(self, results: List[SemanticResult], threshold: float) -> List[SemanticResult]:
        if not results or threshold <= 0:
            return results
        kept: List[SemanticResult] = []
        kept_vecs: Dict[str, List[float]] = {}
        seen_text: set[str] = set()
        for r in results:
            text_key = (r.insight_text or "").strip().lower()
            if text_key and text_key in seen_text:
                continue
            rvec = self.index.get(r.insight_key)
            too_similar = False
            for s in kept:
                if not rvec:
                    sim = self._text_similarity(r.insight_text, s.insight_text)
                else:
                    svec = kept_vecs.get(s.insight_key)
                    if not svec:
                        svec = self.index.get(s.insight_key)
                        if svec:
                            kept_vecs[s.insight_key] = svec
                    sim = self._cosine_sim(rvec, svec) if svec else self._text_similarity(r.insight_text, s.insight_text)
                if sim >= threshold:
                    too_similar = True
                    break
            if too_similar:
                continue
            kept.append(r)
            if rvec:
                kept_vecs[r.insight_key] = rvec
            if text_key:
                seen_text.add(text_key)
        return kept

    def _diversify_mmr(self, results: List[SemanticResult], lambda_: float = 0.5) -> List[SemanticResult]:
        selected: List[SemanticResult] = []
        remaining = list(results)
        while remaining and len(selected) < int(self.config.get("max_results", 8)):
            if not selected:
                best = max(remaining, key=lambda r: r.fusion_score)
            else:
                def mmr_score(r: SemanticResult) -> float:
                    relevance = r.fusion_score
                    max_sim = max(self._text_similarity(r.insight_text, s.insight_text) for s in selected)
                    return lambda_ * relevance - (1 - lambda_) * max_sim
                best = max(remaining, key=mmr_score)
            selected.append(best)
            remaining.remove(best)
        return selected

    def _cap_by_category(self, results: List[SemanticResult]) -> List[SemanticResult]:
        caps = self.config.get("category_caps", DEFAULT_CONFIG["category_caps"])
        counts: Dict[str, int] = {}
        capped: List[SemanticResult] = []
        for r in results:
            cat = r.category or "default"
            counts[cat] = counts.get(cat, 0) + 1
            if counts[cat] <= caps.get(cat, caps.get("default", 2)):
                capped.append(r)
        return capped

    def _log_retrieval(
        self,
        *,
        context: str,
        intent: str,
        semantic_candidates_count: int,
        trigger_hits: int,
        results: List[SemanticResult],
        embedding_available: bool,
        elapsed_ms: int,
    ) -> None:
        if not self.config.get("log_retrievals", True):
            return
        try:
            rate = float(self.config.get("log_sample_rate", 1.0) or 1.0)
        except Exception:
            rate = 1.0
        if rate <= 0.0:
            return
        if rate < 1.0:
            import random
            if random.random() > rate:
                return
        try:
            log_dir = Path.home() / ".spark" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / "semantic_retrieval.jsonl"

            # Keep log bounded so the hot path doesn't create unbounded disk I/O.
            max_bytes = int(self.config.get("log_max_bytes", 0) or 0)
            backups = int(self.config.get("log_backups", 3) or 3)
            _rotate_log_if_needed(path, max_bytes=max_bytes, backups=backups)

            payload = {
                "ts": time.time(),
                "intent": intent[:200],
                "context_preview": (context or "")[:200],
                "semantic_candidates_count": int(semantic_candidates_count),
                "trigger_hits": int(trigger_hits),
                "embedding_available": bool(embedding_available),
                "elapsed_ms": int(elapsed_ms),
                "final_results": [
                    {
                        "key": r.insight_key,
                        "fusion": round(float(r.fusion_score or 0.0), 4),
                        "sim": round(float(r.semantic_sim or 0.0), 4),
                        "outcome": round(float(r.outcome_score or 0.0), 4),
                        "recency": round(float(r.recency_score or 0.0), 4),
                        "why": r.why,
                        "source": r.source_type,
                        "category": r.category,
                    }
                    for r in results
                ],
            }
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            log_debug(
                "semantic",
                f"intent='{intent[:80]}' candidates={semantic_candidates_count} triggers={trigger_hits} final={len(results)}",
            )
        except Exception as e:
            log_debug("semantic", "log_retrieval failed", e)


def _load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    tuneables = path or (Path.home() / ".spark" / "tuneables.json")
    semantic = resolve_section(
        "semantic",
        runtime_path=tuneables,
        env_overrides={"enabled": env_bool("SPARK_SEMANTIC_ENABLED")},
    ).data
    triggers = resolve_section(
        "triggers",
        runtime_path=tuneables,
        env_overrides={"enabled": env_bool("SPARK_TRIGGERS_ENABLED")},
    ).data
    config.update(semantic if isinstance(semantic, dict) else {})
    if isinstance(triggers, dict):
        if "enabled" in triggers:
            config["triggers_enabled"] = bool(triggers.get("enabled"))
        if "rules_file" in triggers:
            config["trigger_rules_file"] = triggers.get("rules_file")

    return config


_RETRIEVER: Optional[SemanticRetriever] = None


def get_semantic_retriever() -> Optional[SemanticRetriever]:
    global _RETRIEVER
    config = _load_config()
    if not config.get("enabled", False):
        return None
    if _RETRIEVER is None or _RETRIEVER.config != config:
        _RETRIEVER = SemanticRetriever(config=config)
    return _RETRIEVER


def index_insight(insight_key: str, text: str, context: str = "") -> bool:
    retriever = get_semantic_retriever()
    if not retriever:
        return False
    if not retriever.config.get("index_on_write", True):
        return False
    combined = f"{text} {context}".strip()
    if not combined:
        return False
    # Skip noise insights at write time
    try:
        from .cognitive_learner import get_cognitive_learner
        learner = get_cognitive_learner()
        if hasattr(learner, "is_noise_insight") and learner.is_noise_insight(combined):
            return False
    except Exception:
        pass
    return retriever.index.add(insight_key, combined)


def backfill_index(force: bool = False) -> Dict[str, Any]:
    """Backfill the semantic index with all cognitive insights.

    This is the manual/CLI entry point for ensuring the index is complete.
    Can be called from scripts or the CLI.

    Args:
        force: if True, re-index even if hashes match (full rebuild)

    Returns:
        dict with backfill stats (indexed, pruned, skipped, total)
    """
    from .cognitive_learner import get_cognitive_learner

    config = _load_config()
    # Force-enable for backfill even if disabled in config
    config["enabled"] = True

    retriever = SemanticRetriever(config=config)
    learner = get_cognitive_learner()
    insights = learner.insights

    noise_fn = None
    if hasattr(learner, "is_noise_insight"):
        noise_fn = learner.is_noise_insight

    if force:
        # Clear the index for full rebuild
        with retriever.index._connect() as conn:
            conn.execute("DELETE FROM insights_vec")
            conn.commit()
        retriever.index._invalidate_cache()

    # Index all insights (no batch limit for backfill)
    indexed = retriever.index.ensure_index(
        insights,
        max_items=len(insights) + 100,
        noise_filter=noise_fn,
    )

    # Prune stale entries (insights that were deleted from cognitive store)
    valid_keys = set(insights.keys())
    pruned = retriever.index.prune_stale(valid_keys)

    total = retriever.index.count()
    skipped = len(insights) - total

    return {
        "indexed": indexed,
        "pruned": pruned,
        "skipped_noise": skipped,
        "total_in_index": total,
        "total_insights": len(insights),
    }


def _reload_semantic_from(_cfg):
    """Hot-reload callback — invalidates cached retriever so next call re-creates with fresh config."""
    global _RETRIEVER
    _RETRIEVER = None


try:
    from .tuneables_reload import register_reload as _sem_register

    _sem_register("semantic", _reload_semantic_from, label="semantic_retriever.reload")
    _sem_register("triggers", _reload_semantic_from, label="semantic_retriever.reload.triggers")
except Exception:
    pass
