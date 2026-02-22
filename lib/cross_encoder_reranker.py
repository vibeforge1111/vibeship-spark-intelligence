"""Cross-encoder reranker for advisory retrieval (Phase 2).

Uses ms-marco-MiniLM-L-6-v2 (22M params) to rerank retrieval candidates
by computing full query-document relevance scores. This is a second-pass
filter after the initial bi-encoder retrieval.

The cross-encoder is lazy-loaded on first use and cached as a singleton.
If the model is unavailable, reranking is silently skipped.

Performance: ~80-160ms for 16 pairs on CPU (well within 500ms budget).
"""

from __future__ import annotations

import time
from typing import Any, List, Optional, Tuple

from .diagnostics import log_debug

_reranker_instance: Optional["CrossEncoderReranker"] = None
_reranker_load_attempted: bool = False
_reranker_loading: bool = False


def preload_reranker() -> None:
    """Start loading the cross-encoder model in a background thread.

    Call this early (e.g., at advisor init) so the model is warm
    by the time the first rerank request comes in. If the model
    isn't ready yet, get_reranker() returns None and reranking is
    silently skipped (no 10s cold-start block).
    """
    global _reranker_loading, _reranker_load_attempted
    if _reranker_instance is not None or _reranker_load_attempted or _reranker_loading:
        return
    _reranker_loading = True

    import threading

    def _load() -> None:
        global _reranker_instance, _reranker_load_attempted, _reranker_loading
        try:
            _reranker_instance = CrossEncoderReranker()
            log_debug("cross_encoder", "Background preload complete")
        except Exception as e:
            log_debug("cross_encoder", f"Background preload failed: {e}")
        finally:
            _reranker_load_attempted = True
            _reranker_loading = False

    t = threading.Thread(target=_load, daemon=True)
    t.start()


def get_reranker() -> Optional["CrossEncoderReranker"]:
    """Get the singleton reranker. Returns None if unavailable or still loading."""
    global _reranker_instance, _reranker_load_attempted
    if _reranker_instance is not None:
        return _reranker_instance
    if _reranker_load_attempted:
        return None  # Tried and failed
    if _reranker_loading:
        return None  # Still loading in background — skip this time
    # No background preload was started; attempt synchronous load
    _reranker_load_attempted = True
    try:
        _reranker_instance = CrossEncoderReranker()
        return _reranker_instance
    except Exception as e:
        log_debug("cross_encoder", f"Failed to load: {e}")
        return None


class CrossEncoderReranker:
    """Reranks candidates using a cross-encoder model for precise relevance scoring."""

    MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    # Maximum pairs to score in one batch (latency guard)
    MAX_PAIRS = 24

    def __init__(self, model_name: Optional[str] = None) -> None:
        from sentence_transformers import CrossEncoder
        self._model = CrossEncoder(model_name or self.MODEL_NAME)

    def rerank(
        self,
        query: str,
        candidates: List[str],
        top_k: int = 8,
    ) -> List[Tuple[int, float]]:
        """Rerank candidates by cross-encoder relevance score.

        Args:
            query: The retrieval query (tool context string).
            candidates: List of candidate advice texts.
            top_k: Number of top results to return.

        Returns:
            List of (original_index, score) tuples, sorted by score descending.
            Only top_k items are returned.
        """
        if not query or not candidates:
            return []

        # Limit to MAX_PAIRS to control latency
        n = min(len(candidates), self.MAX_PAIRS)
        pairs = [(query, candidates[i]) for i in range(n)]

        start = time.perf_counter()
        scores = self._model.predict(pairs)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Build ranked list: (original_index, score)
        indexed_scores = [(i, float(scores[i])) for i in range(n)]
        # Add un-scored items at the bottom with a very low score
        for i in range(n, len(candidates)):
            indexed_scores.append((i, -100.0))

        indexed_scores.sort(key=lambda x: x[1], reverse=True)

        log_debug(
            "cross_encoder",
            f"Reranked {n} candidates in {elapsed_ms:.0f}ms, "
            f"top score: {indexed_scores[0][1]:.2f}, "
            f"bottom score: {indexed_scores[min(top_k, len(indexed_scores)) - 1][1]:.2f}",
        )

        return indexed_scores[:top_k]

    def score_pair(self, query: str, candidate: str) -> float:
        """Score a single query-candidate pair. Returns relevance score."""
        if not query or not candidate:
            return -100.0
        scores = self._model.predict([(query, candidate)])
        return float(scores[0])
