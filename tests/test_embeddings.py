from __future__ import annotations

import importlib

import lib.embeddings as embeddings


def _reload_embeddings(monkeypatch, backend: str):
    monkeypatch.setenv("SPARK_EMBED_BACKEND", backend)
    monkeypatch.delenv("SPARK_EMBEDDINGS", raising=False)
    mod = importlib.reload(embeddings)
    return mod


def test_auto_backend_falls_back_to_tfidf(monkeypatch):
    mod = _reload_embeddings(monkeypatch, "auto")
    monkeypatch.setattr(mod, "_get_fastembed", lambda: None)
    vec = mod.embed_text("token refresh retry policy")
    assert vec is not None
    assert len(vec) == 256


def test_invalid_backend_defaults_to_auto(monkeypatch):
    mod = _reload_embeddings(monkeypatch, "invalid_backend_name")
    monkeypatch.setattr(mod, "_get_fastembed", lambda: None)
    vec = mod.embed_text("cache invalidation strategy")
    assert vec is not None
    assert len(vec) == 256


def test_fastembed_mode_returns_none_if_unavailable(monkeypatch):
    mod = _reload_embeddings(monkeypatch, "fastembed")
    monkeypatch.setattr(mod, "_get_fastembed", lambda: None)
    assert mod.embed_text("anything") is None
