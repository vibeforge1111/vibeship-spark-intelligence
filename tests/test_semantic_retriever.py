from __future__ import annotations

from types import SimpleNamespace

import lib.semantic_retriever as semantic_retriever_module


def _make_retriever(*, rescue_enabled: bool):
    cfg = dict(semantic_retriever_module.DEFAULT_CONFIG)
    cfg.update(
        {
            "triggers_enabled": False,
            "index_on_read": False,
            "min_similarity": 0.9,
            "min_fusion_score": 0.9,
            "empty_result_rescue_enabled": rescue_enabled,
            "rescue_min_similarity": 0.2,
            "rescue_min_fusion_score": 0.0,
        }
    )
    return semantic_retriever_module.SemanticRetriever(config=cfg)


def _make_insights():
    return {
        "k1": SimpleNamespace(insight="auth token rotation and session repair", reliability=0.6),
        "k2": SimpleNamespace(insight="memory retrieval diagnostics and provider checks", reliability=0.55),
    }


def test_empty_result_rescue_returns_candidates(monkeypatch):
    retriever = _make_retriever(rescue_enabled=True)
    monkeypatch.setattr(semantic_retriever_module, "embed_text", lambda _q: [1.0])
    monkeypatch.setattr(
        retriever.index,
        "search",
        lambda _vec, limit=10: [("k1", 0.4), ("k2", 0.35)][:limit],
    )

    results = retriever.retrieve("auth token memory issue", _make_insights(), limit=3)

    assert results
    assert any("rescue_fallback" in (r.why or "") for r in results)


def test_empty_result_rescue_can_be_disabled(monkeypatch):
    retriever = _make_retriever(rescue_enabled=False)
    monkeypatch.setattr(semantic_retriever_module, "embed_text", lambda _q: [1.0])
    monkeypatch.setattr(
        retriever.index,
        "search",
        lambda _vec, limit=10: [("k1", 0.4), ("k2", 0.35)][:limit],
    )

    results = retriever.retrieve("auth token memory issue", _make_insights(), limit=3)
    assert results == []


def test_tfidf_runtime_recalibrates_default_thresholds(monkeypatch):
    monkeypatch.setenv("SPARK_EMBED_BACKEND", "tfidf")
    monkeypatch.setattr(
        semantic_retriever_module,
        "_load_config",
        lambda: {
            **semantic_retriever_module.DEFAULT_CONFIG,
            "min_similarity": 0.56,
            "min_fusion_score": 0.50,
            "rescue_min_similarity": 0.30,
            "rescue_min_fusion_score": 0.20,
        },
    )

    retriever = semantic_retriever_module.SemanticRetriever(config=None)

    assert retriever.config["min_similarity"] <= 0.15
    assert retriever.config["min_fusion_score"] <= 0.10
    assert retriever.config["rescue_min_similarity"] <= 0.10
    assert retriever.config["rescue_min_fusion_score"] <= 0.05
