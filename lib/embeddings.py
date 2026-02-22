"""Embeddings helper for Spark Intelligence.

Supports three backends (chosen via SPARK_EMBED_BACKEND env var):
  - "tfidf"     : Lightweight TF-IDF hashing (default). ~0MB RAM, no model download.
  - "fastembed"  : Neural embeddings via fastembed/ONNX. High quality but 8GB+ RAM.
  - "none"       : Disabled entirely. All functions return None.

Set SPARK_EMBEDDINGS=0 to force "none" (backwards compatible).
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from typing import Any, List, Optional

# --- Backend selection ---
_BACKEND = None


def _get_backend() -> str:
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND

    if os.environ.get("SPARK_EMBEDDINGS", "1").lower() in ("0", "false", "no"):
        _BACKEND = "none"
        return _BACKEND

    _BACKEND = os.environ.get("SPARK_EMBED_BACKEND", "tfidf").lower()
    return _BACKEND


# ============================================================
# TF-IDF hashing embedder — zero dependencies, ~0MB overhead
# ============================================================
_TFIDF_DIM = 256  # hash vector dimension (power of 2 for speed)
_STOP_WORDS = frozenset(
    "the a an is are was were be been being have has had do does did "
    "will would shall should may might can could of in to for on with "
    "at by from as into through during before after above below between "
    "and or but not no nor so yet both either neither each every all "
    "any few more most other some such than too very this that these those "
    "it its i me my we our you your he him his she her they them their "
    "what which who whom how when where why".split()
)


def _tokenize(text: str) -> List[str]:
    """Simple tokenizer: lowercase, split on non-alphanumeric, remove stop words."""
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


def _hash_token(token: str, dim: int) -> int:
    """Deterministic hash to bucket index."""
    # Use Python's built-in hash with a fixed seed approach
    h = 0
    for ch in token:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h % dim


def _tfidf_embed(text: str) -> List[float]:
    """Produce a TF-IDF-style hash vector for a text string.

    Uses hashing trick (feature hashing) — no vocabulary needed.
    Includes bigrams for better semantic capture.
    """
    tokens = _tokenize(text)
    if not tokens:
        return [0.0] * _TFIDF_DIM

    # Add bigrams
    bigrams = [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)]
    all_terms = tokens + bigrams

    # Term frequency
    tf = Counter(all_terms)
    total = len(all_terms)

    # Build hash vector with TF weighting
    vec = [0.0] * _TFIDF_DIM
    for term, count in tf.items():
        idx = _hash_token(term, _TFIDF_DIM)
        # Sign hash to reduce collisions
        sign = 1.0 if (_hash_token(term + "_sign", 2) == 0) else -1.0
        weight = (count / total) * math.log(1 + 1.0 / (1 + count))
        vec[idx] += sign * weight

    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]

    return vec


# ============================================================
# fastembed backend (original — kept for opt-in high quality)
# ============================================================
_FASTEMBED = None
_FASTEMBED_ERROR = None


def _get_fastembed() -> Optional[Any]:
    global _FASTEMBED, _FASTEMBED_ERROR
    if _FASTEMBED is not None:
        return _FASTEMBED
    if _FASTEMBED_ERROR is not None:
        return None
    try:
        from fastembed import TextEmbedding
    except Exception as e:
        _FASTEMBED_ERROR = e
        return None
    model = os.environ.get("SPARK_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    try:
        _FASTEMBED = TextEmbedding(model_name=model)
    except Exception as e:
        _FASTEMBED_ERROR = e
        return None
    return _FASTEMBED


# ============================================================
# Public API (unchanged interface)
# ============================================================


def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    """Embed a list of texts. Returns None if embeddings are disabled."""
    backend = _get_backend()

    if backend == "none":
        return None

    if backend == "fastembed":
        embedder = _get_fastembed()
        if embedder is None:
            return None
        try:
            vectors = list(embedder.embed(texts))
            return [list(v) for v in vectors]
        except Exception:
            return None

    # Default: tfidf
    try:
        return [_tfidf_embed(t) for t in texts]
    except Exception:
        return None


def embed_text(text: str) -> Optional[List[float]]:
    """Embed a single text string."""
    if not text:
        return None
    vectors = embed_texts([text])
    if not vectors:
        return None
    return vectors[0]
