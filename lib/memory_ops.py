"""Memory Operations Engine: ADD / UPDATE / DELETE / NOOP.

Replaces binary keep/discard with a four-way decision informed by:
- Semantic similarity to existing insights
- Contradiction detection (reuses lib/contradiction_detector.py)
- ACT-R activation scores (from lib/activation.py)

Design: fail-open.  If similarity search or activation is unavailable,
falls back to ADD (current behavior).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("spark.memory_ops")

# ---------------------------------------------------------------------------
# In-memory decision log for dashboard visibility
# ---------------------------------------------------------------------------
_OPS_LOG_MAX = 200
_ops_decision_log: list = []


def _log_ops_decision(decision: "MemoryDecision", text: str) -> None:
    """Append to bounded in-memory decision log."""
    _ops_decision_log.append({
        "ts": time.time(),
        "op": decision.op.value,
        "reason": decision.reason,
        "text": text[:120],
        "similarity": round(decision.similarity, 3),
        "target_key": decision.target_key or "",
        "contradiction": round(decision.contradiction_confidence, 2),
    })
    while len(_ops_decision_log) > _OPS_LOG_MAX:
        _ops_decision_log.pop(0)


def get_memory_ops_log() -> list:
    """Return recent memory ops decisions for dashboard display."""
    return list(_ops_decision_log)


def get_memory_ops_stats() -> dict:
    """Return aggregate memory ops stats."""
    from collections import Counter
    ops = Counter(d["op"] for d in _ops_decision_log)
    return {
        "total_decisions": len(_ops_decision_log),
        "add": ops.get("add", 0),
        "update": ops.get("update", 0),
        "delete": ops.get("delete", 0),
        "noop": ops.get("noop", 0),
    }


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class MemoryOp(Enum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    NOOP = "noop"


@dataclass
class MemoryDecision:
    """Result of the decide() call."""
    op: MemoryOp
    reason: str
    target_key: Optional[str] = None       # existing insight key (UPDATE/DELETE)
    target_text: Optional[str] = None      # existing insight text
    similarity: float = 0.0                # cosine sim to target
    activation: float = 0.0                # target's ACT-R activation
    contradiction_confidence: float = 0.0  # how contradictory (for DELETE)
    merged_text: Optional[str] = None      # refined text for UPDATE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "op": self.op.value,
            "reason": self.reason,
            "target_key": self.target_key,
            "similarity": round(self.similarity, 4),
            "activation": round(self.activation, 4),
            "contradiction_confidence": round(self.contradiction_confidence, 4),
        }


# ---------------------------------------------------------------------------
# Thresholds (configurable via tuneables.json -> memory_ops)
# ---------------------------------------------------------------------------

SIMILARITY_NEAR_DUPE = 0.92    # above = NOOP (duplicate)
SIMILARITY_UPDATE = 0.75       # above = UPDATE candidate
SIMILARITY_CONTRADICTION = 0.60  # above = DELETE if contradicted
ACTIVATION_HIGH_THRESHOLD = 0.0   # above = "high activation" insight


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class MemoryOpsEngine:
    """Determine ADD/UPDATE/DELETE/NOOP for incoming insights."""

    def __init__(
        self,
        sim_near_dupe: float = SIMILARITY_NEAR_DUPE,
        sim_update: float = SIMILARITY_UPDATE,
        sim_contradiction: float = SIMILARITY_CONTRADICTION,
        activation_high: float = ACTIVATION_HIGH_THRESHOLD,
    ):
        self.sim_near_dupe = sim_near_dupe
        self.sim_update = sim_update
        self.sim_contradiction = sim_contradiction
        self.activation_high = activation_high

    def decide(
        self,
        new_text: str,
        new_category: str,
        existing_insights: Dict[str, Any],
        activation_store: Optional[Any] = None,
    ) -> MemoryDecision:
        """Determine the memory operation for a new insight candidate.

        Decision matrix:
        | sim > 0.92              | NOOP (duplicate)                  |
        | sim 0.75-0.92, no contr | UPDATE (merge)                    |
        | sim 0.75-0.92, contr,
        |   high activation       | UPDATE (supersede, keep history)  |
        | sim 0.75-0.92, contr,
        |   low activation        | DELETE + ADD                      |
        | sim 0.60-0.75, contr    | DELETE                            |
        | sim < 0.60              | ADD                               |
        """
        if not new_text or not new_text.strip():
            return MemoryDecision(op=MemoryOp.NOOP, reason="empty_text")

        # Find most similar existing insight.
        best_key, best_sim, best_text = self._find_most_similar(
            new_text, existing_insights
        )

        # No similar insight found → ADD.
        if best_key is None or best_sim < self.sim_contradiction:
            return MemoryDecision(op=MemoryOp.ADD, reason="no_similar_existing")

        # Get activation for the target insight.
        target_activation = 0.0
        if activation_store is not None and best_key:
            try:
                act = activation_store.compute_activation(best_key)
                target_activation = act if act is not None else 0.0
            except Exception:
                pass

        # Near-duplicate → NOOP.
        if best_sim >= self.sim_near_dupe:
            return MemoryDecision(
                op=MemoryOp.NOOP,
                reason="near_duplicate",
                target_key=best_key,
                target_text=best_text,
                similarity=best_sim,
                activation=target_activation,
            )

        # Check for contradiction.
        is_contradiction, contr_confidence = self._detect_contradiction(
            new_text, best_text or ""
        )

        # Similar but NOT contradicting → UPDATE (merge).
        if best_sim >= self.sim_update and not is_contradiction:
            merged = self._merge_texts(new_text, best_text or "", best_sim)
            return MemoryDecision(
                op=MemoryOp.UPDATE,
                reason="similar_merge",
                target_key=best_key,
                target_text=best_text,
                similarity=best_sim,
                activation=target_activation,
                merged_text=merged,
            )

        # Similar AND contradicting.
        if is_contradiction:
            if best_sim >= self.sim_update:
                # High similarity + contradiction.
                if target_activation > self.activation_high:
                    # High activation → UPDATE (supersede, preserve history).
                    return MemoryDecision(
                        op=MemoryOp.UPDATE,
                        reason="contradiction_supersede_high_activation",
                        target_key=best_key,
                        target_text=best_text,
                        similarity=best_sim,
                        activation=target_activation,
                        contradiction_confidence=contr_confidence,
                        merged_text=new_text,  # new text wins
                    )
                else:
                    # Low activation → DELETE old + ADD new.
                    return MemoryDecision(
                        op=MemoryOp.DELETE,
                        reason="contradiction_low_activation",
                        target_key=best_key,
                        target_text=best_text,
                        similarity=best_sim,
                        activation=target_activation,
                        contradiction_confidence=contr_confidence,
                    )
            elif best_sim >= self.sim_contradiction:
                # Medium similarity + contradiction → DELETE.
                return MemoryDecision(
                    op=MemoryOp.DELETE,
                    reason="medium_sim_contradiction",
                    target_key=best_key,
                    target_text=best_text,
                    similarity=best_sim,
                    activation=target_activation,
                    contradiction_confidence=contr_confidence,
                )

        # Fallback: ADD.
        return MemoryDecision(op=MemoryOp.ADD, reason="below_thresholds")

    # -- Similarity ---------------------------------------------------------

    def _find_most_similar(
        self,
        text: str,
        existing_insights: Dict[str, Any],
    ) -> Tuple[Optional[str], float, Optional[str]]:
        """Find the most similar existing insight.

        Uses embeddings if available, falls back to word overlap.
        Returns (key, similarity, text) or (None, 0.0, None).
        """
        if not existing_insights:
            return None, 0.0, None

        best_key: Optional[str] = None
        best_sim = 0.0
        best_text: Optional[str] = None

        # Try embedding-based similarity.
        new_embedding = None
        try:
            from lib.embeddings import embed_text
            new_embedding = embed_text(text)
        except Exception:
            pass

        new_words = set(text.lower().split())

        for key, insight in existing_insights.items():
            insight_text = ""
            if hasattr(insight, "insight"):
                insight_text = insight.insight
            elif isinstance(insight, dict):
                insight_text = insight.get("insight", "")
            if not insight_text:
                continue

            sim = 0.0

            # Embedding similarity.
            if new_embedding is not None:
                try:
                    from lib.embeddings import embed_text
                    existing_embedding = embed_text(insight_text)
                    if existing_embedding:
                        sim = self._cosine_sim(new_embedding, existing_embedding)
                except Exception:
                    pass

            # Word overlap fallback (Jaccard).
            existing_words = set(insight_text.lower().split())
            if new_words and existing_words:
                jaccard = len(new_words & existing_words) / len(new_words | existing_words)
                sim = max(sim, jaccard)

            if sim > best_sim:
                best_sim = sim
                best_key = key
                best_text = insight_text

        return best_key, best_sim, best_text

    @staticmethod
    def _cosine_sim(a: List[float], b: List[float]) -> float:
        """Cosine similarity between two vectors."""
        import math
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # -- Contradiction detection --------------------------------------------

    @staticmethod
    def _detect_contradiction(
        new_text: str,
        existing_text: str,
    ) -> Tuple[bool, float]:
        """Detect contradiction using existing patterns.  No LLM."""
        try:
            from lib.contradiction_detector import _has_opposition
            return _has_opposition(new_text, existing_text)
        except ImportError:
            pass

        # Inline fallback: basic negation asymmetry check.
        import re
        neg_patterns = [r"\bnot\b", r"\bnever\b", r"\bdon'?t\b", r"\bavoid\b"]
        new_lower = new_text.lower()
        exist_lower = existing_text.lower()
        new_neg = any(re.search(p, new_lower) for p in neg_patterns)
        exist_neg = any(re.search(p, exist_lower) for p in neg_patterns)
        if new_neg != exist_neg:
            return True, 0.5
        return False, 0.0

    # -- Merge logic --------------------------------------------------------

    @staticmethod
    def _merge_texts(
        new_text: str,
        existing_text: str,
        similarity: float,
    ) -> str:
        """Merge new evidence into existing insight text.

        Rules:
        - If new text is more specific (more words, action verbs), use new.
        - If very similar (>0.85), keep existing (it's established).
        - Cap at 500 chars.
        """
        # Very high similarity → keep existing, it's already good.
        if similarity > 0.85:
            return existing_text[:500]

        # Count action verb density as proxy for specificity.
        from lib.keepability_gate import _ACTION_VERBS, _WORD_RE
        new_words = _WORD_RE.findall(new_text)
        exist_words = _WORD_RE.findall(existing_text)
        new_actions = sum(1 for w in new_words if w.lower() in _ACTION_VERBS)
        exist_actions = sum(1 for w in exist_words if w.lower() in _ACTION_VERBS)

        # More specific text wins.
        if new_actions > exist_actions or (new_actions == exist_actions and len(new_text) > len(existing_text)):
            return new_text[:500]

        return existing_text[:500]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def execute_decision(
    decision: MemoryDecision,
    learner: Any,  # CognitiveLearner
    new_text: str,
    new_category: Any,  # CognitiveCategory
    new_context: str,
    new_confidence: float,
    source: str,
    activation_store: Optional[Any] = None,
) -> Optional[Any]:
    """Execute the memory operation.

    Returns the CognitiveInsight if stored (ADD/UPDATE), None otherwise.
    """
    try:
        from lib.intelligence_observability import log_intelligence_flow_event
    except ImportError:
        def log_intelligence_flow_event(**kw: Any) -> None: pass

    _log_ops_decision(decision, new_text)

    if decision.op == MemoryOp.NOOP:
        log_intelligence_flow_event(
            stage="memory_ops",
            action="noop",
            text=new_text[:200],
            reason=decision.reason,
            extra=decision.to_dict(),
        )
        return None

    if decision.op == MemoryOp.ADD:
        log_intelligence_flow_event(
            stage="memory_ops",
            action="add",
            text=new_text[:200],
            reason=decision.reason,
        )
        result = learner.add_insight(
            category=new_category,
            insight=new_text,
            context=new_context,
            confidence=new_confidence,
            source=source,
        )
        if result and activation_store:
            try:
                # Derive key the same way cognitive learner does.
                key = _insight_key(new_category, new_text)
                activation_store.record_access(key, "storage")
            except Exception:
                pass
        return result

    if decision.op == MemoryOp.UPDATE:
        log_intelligence_flow_event(
            stage="memory_ops",
            action="update",
            text=new_text[:200],
            reason=decision.reason,
            extra={"target_key": decision.target_key, "similarity": decision.similarity},
        )
        target_key = decision.target_key
        if target_key and target_key in learner.insights:
            insight = learner.insights[target_key]
            # Update text if merged version is better.
            if decision.merged_text and decision.merged_text != insight.insight:
                insight.insight = decision.merged_text[:500]
            # Boost confidence.
            insight.confidence = min(1.0, max(insight.confidence, new_confidence))
            # Increment validation (new evidence = validation of the concept).
            insight.times_validated += 1
            import datetime
            insight.last_validated_at = datetime.datetime.now().isoformat()
            # Add evidence.
            if hasattr(insight, "evidence") and isinstance(insight.evidence, list):
                if len(insight.evidence) < 10:
                    insight.evidence.append(new_text[:200])
            # Save.
            try:
                learner._save_insights()
            except Exception:
                pass
            # Record access.
            if activation_store:
                try:
                    activation_store.record_access(target_key, "validation")
                except Exception:
                    pass
            return insight
        else:
            # Target key gone — fall back to ADD.
            return learner.add_insight(
                category=new_category,
                insight=decision.merged_text or new_text,
                context=new_context,
                confidence=new_confidence,
                source=source,
            )

    if decision.op == MemoryOp.DELETE:
        log_intelligence_flow_event(
            stage="memory_ops",
            action="delete",
            text=new_text[:200],
            reason=decision.reason,
            extra={
                "target_key": decision.target_key,
                "contradiction_confidence": decision.contradiction_confidence,
            },
        )
        target_key = decision.target_key
        if target_key and target_key in learner.insights:
            insight = learner.insights[target_key]
            # Soft delete: boost contradictions to drop reliability.
            insight.times_contradicted += 5
            # Add counter_example.
            if hasattr(insight, "counter_examples") and isinstance(insight.counter_examples, list):
                if len(insight.counter_examples) < 10:
                    insight.counter_examples.append(new_text[:200])
            # Set invalidated_at marker.
            import datetime
            if hasattr(insight, "invalidated_at"):
                insight.invalidated_at = datetime.datetime.now().isoformat()
            try:
                learner._save_insights()
            except Exception:
                pass

        # After DELETE, ADD the new insight (superseding).
        result = learner.add_insight(
            category=new_category,
            insight=new_text,
            context=new_context,
            confidence=new_confidence,
            source=source,
        )
        if result and activation_store:
            try:
                key = _insight_key(new_category, new_text)
                activation_store.record_access(key, "storage")
            except Exception:
                pass
        return result

    return None


def _insight_key(category: Any, text: str) -> str:
    """Derive an insight key matching cognitive_learner's convention."""
    cat_val = category.value if hasattr(category, "value") else str(category)
    identifier = text[:40].lower().replace(" ", "_")
    return f"{cat_val}:{identifier}"


# ---------------------------------------------------------------------------
# Singleton / convenience
# ---------------------------------------------------------------------------

_engine: Optional[MemoryOpsEngine] = None


def get_memory_ops_engine() -> MemoryOpsEngine:
    """Get or create singleton MemoryOpsEngine."""
    global _engine
    if _engine is None:
        _engine = MemoryOpsEngine()
    return _engine
