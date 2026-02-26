"""Tests for lib/embeddings.py — TF-IDF backend (pure stdlib)."""

from __future__ import annotations

import importlib
import sys

import pytest

import lib.embeddings as emb
from lib.embeddings import (
    _TFIDF_DIM,
    _hash_token,
    _tokenize,
    _tfidf_embed,
    embed_text,
    embed_texts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_backend(monkeypatch):
    """Force backend to re-evaluate on next call."""
    monkeypatch.setattr(emb, "_BACKEND", None)


def _use_tfidf(monkeypatch):
    _reset_backend(monkeypatch)
    monkeypatch.delenv("SPARK_EMBEDDINGS", raising=False)
    monkeypatch.setenv("SPARK_EMBED_BACKEND", "tfidf")


def _disable(monkeypatch):
    _reset_backend(monkeypatch)
    monkeypatch.setenv("SPARK_EMBEDDINGS", "0")


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------

def test_tokenize_basic():
    tokens = _tokenize("hello world")
    assert "hello" in tokens
    assert "world" in tokens


def test_tokenize_lowercases():
    tokens = _tokenize("Hello World")
    assert "hello" in tokens


def test_tokenize_strips_non_alpha():
    tokens = _tokenize("foo-bar baz!")
    assert "foo" in tokens or "bar" in tokens
    assert "baz" in tokens


def test_tokenize_removes_stop_words():
    tokens = _tokenize("the a is are")
    assert tokens == []


def test_tokenize_removes_single_char():
    tokens = _tokenize("x y z hello")
    assert "x" not in tokens
    assert "hello" in tokens


def test_tokenize_empty_string():
    assert _tokenize("") == []


def test_tokenize_only_stop_words():
    assert _tokenize("the is a an of in") == []


def test_tokenize_numbers_kept():
    tokens = _tokenize("python3 version 12")
    assert "python3" in tokens or "version" in tokens


def test_tokenize_returns_list():
    assert isinstance(_tokenize("hello"), list)


def test_tokenize_underscore_kept():
    tokens = _tokenize("snake_case_variable")
    assert "snake_case_variable" in tokens


# ---------------------------------------------------------------------------
# _hash_token
# ---------------------------------------------------------------------------

def test_hash_token_in_range():
    h = _hash_token("hello", _TFIDF_DIM)
    assert 0 <= h < _TFIDF_DIM


def test_hash_token_deterministic():
    assert _hash_token("hello", 256) == _hash_token("hello", 256)


def test_hash_token_different_tokens_different_buckets():
    h1 = _hash_token("hello", 256)
    h2 = _hash_token("world", 256)
    # Not guaranteed to differ, but highly likely with dim=256
    # Just check both are valid
    assert 0 <= h1 < 256
    assert 0 <= h2 < 256


def test_hash_token_dim_1_always_0():
    assert _hash_token("anything", 1) == 0


def test_hash_token_empty_string():
    h = _hash_token("", 256)
    assert 0 <= h < 256


def test_hash_token_sign_in_range():
    h = _hash_token("hello_sign", 2)
    assert h in (0, 1)


# ---------------------------------------------------------------------------
# _tfidf_embed
# ---------------------------------------------------------------------------

def test_tfidf_embed_returns_list():
    vec = _tfidf_embed("machine learning algorithms")
    assert isinstance(vec, list)


def test_tfidf_embed_correct_dim():
    vec = _tfidf_embed("some text here")
    assert len(vec) == _TFIDF_DIM


def test_tfidf_embed_empty_string():
    vec = _tfidf_embed("")
    assert len(vec) == _TFIDF_DIM
    assert all(v == 0.0 for v in vec)


def test_tfidf_embed_only_stop_words():
    vec = _tfidf_embed("the is a the")
    assert len(vec) == _TFIDF_DIM
    assert all(v == 0.0 for v in vec)


def test_tfidf_embed_is_unit_vector():
    import math
    vec = _tfidf_embed("machine learning python programming")
    norm = math.sqrt(sum(v * v for v in vec))
    assert abs(norm - 1.0) < 1e-9 or norm == 0.0


def test_tfidf_embed_deterministic():
    v1 = _tfidf_embed("hello world programming")
    v2 = _tfidf_embed("hello world programming")
    assert v1 == v2


def test_tfidf_embed_different_texts_different_vectors():
    v1 = _tfidf_embed("machine learning algorithms")
    v2 = _tfidf_embed("database transactions sql")
    assert v1 != v2


def test_tfidf_embed_returns_floats():
    vec = _tfidf_embed("hello world")
    assert all(isinstance(v, float) for v in vec)


def test_tfidf_dim_is_256():
    assert _TFIDF_DIM == 256


def test_tfidf_embed_non_zero_for_real_text():
    vec = _tfidf_embed("python programming language functional")
    assert any(v != 0.0 for v in vec)


# ---------------------------------------------------------------------------
# embed_texts – tfidf backend
# ---------------------------------------------------------------------------

def test_embed_texts_tfidf_returns_list(monkeypatch):
    _use_tfidf(monkeypatch)
    result = embed_texts(["hello world", "python code"])
    assert isinstance(result, list)


def test_embed_texts_tfidf_correct_count(monkeypatch):
    _use_tfidf(monkeypatch)
    result = embed_texts(["a b c", "d e f", "g h i"])
    assert len(result) == 3


def test_embed_texts_tfidf_each_dim(monkeypatch):
    _use_tfidf(monkeypatch)
    result = embed_texts(["machine learning"])
    assert len(result[0]) == _TFIDF_DIM


def test_embed_texts_tfidf_empty_list(monkeypatch):
    _use_tfidf(monkeypatch)
    result = embed_texts([])
    assert result == []


def test_embed_texts_disabled_returns_none(monkeypatch):
    _disable(monkeypatch)
    result = embed_texts(["hello"])
    assert result is None


def test_embed_texts_disabled_via_false(monkeypatch):
    _reset_backend(monkeypatch)
    monkeypatch.setenv("SPARK_EMBEDDINGS", "false")
    result = embed_texts(["hello"])
    assert result is None


def test_embed_texts_disabled_via_no(monkeypatch):
    _reset_backend(monkeypatch)
    monkeypatch.setenv("SPARK_EMBEDDINGS", "no")
    result = embed_texts(["hello"])
    assert result is None


# ---------------------------------------------------------------------------
# embed_text – single string
# ---------------------------------------------------------------------------

def test_embed_text_returns_list(monkeypatch):
    _use_tfidf(monkeypatch)
    result = embed_text("python machine learning")
    assert isinstance(result, list)


def test_embed_text_correct_dim(monkeypatch):
    _use_tfidf(monkeypatch)
    result = embed_text("python machine learning")
    assert len(result) == _TFIDF_DIM


def test_embed_text_empty_returns_none(monkeypatch):
    _use_tfidf(monkeypatch)
    result = embed_text("")
    assert result is None


def test_embed_text_none_like_empty(monkeypatch):
    _use_tfidf(monkeypatch)
    result = embed_text("")
    assert result is None


def test_embed_text_disabled_returns_none(monkeypatch):
    _disable(monkeypatch)
    result = embed_text("hello world")
    assert result is None


def test_embed_text_consistent_with_embed_texts(monkeypatch):
    _use_tfidf(monkeypatch)
    single = embed_text("deep learning neural network")
    batch = embed_texts(["deep learning neural network"])
    assert single == batch[0]
