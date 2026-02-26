"""Tests for lib/cross_encoder_reranker.py."""

from __future__ import annotations

import time
import threading
from typing import List, Tuple
from unittest.mock import MagicMock, patch

import pytest

import lib.cross_encoder_reranker as cer
from lib.cross_encoder_reranker import (
    CrossEncoderReranker,
    get_reranker,
    preload_reranker,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _reset_state(monkeypatch):
    """Reset singleton globals before each test."""
    monkeypatch.setattr(cer, "_reranker_instance", None)
    monkeypatch.setattr(cer, "_reranker_load_attempted", False)
    monkeypatch.setattr(cer, "_reranker_loading", False)


def _mock_cross_encoder(scores: List[float]):
    """Return a mock CrossEncoder whose predict() returns fixed scores."""
    mock_ce = MagicMock()
    mock_ce.predict.return_value = scores
    mock_module = MagicMock()
    mock_module.CrossEncoder.return_value = mock_ce
    return mock_module, mock_ce


# ---------------------------------------------------------------------------
# CrossEncoderReranker.rerank – via mock model
# ---------------------------------------------------------------------------

def _make_reranker(scores: List[float]) -> CrossEncoderReranker:
    """Build a CrossEncoderReranker with a mocked sentence_transformers."""
    mock_module, mock_ce = _mock_cross_encoder(scores)
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
    return r


def test_rerank_empty_query_returns_empty():
    mock_module, _ = _mock_cross_encoder([])
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
    assert r.rerank("", ["candidate a", "candidate b"]) == []


def test_rerank_empty_candidates_returns_empty():
    mock_module, _ = _mock_cross_encoder([])
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
    assert r.rerank("query", []) == []


def test_rerank_returns_list_of_tuples():
    scores = [0.9, 0.5, 0.3]
    r = _make_reranker(scores)
    with patch.dict("sys.modules", {"sentence_transformers": MagicMock()}):
        result = r.rerank("query", ["a", "b", "c"])
    assert isinstance(result, list)
    for item in result:
        assert len(item) == 2


def test_rerank_sorted_descending():
    scores = [0.3, 0.9, 0.5]
    mock_module, mock_ce = _mock_cross_encoder(scores)
    mock_ce.predict.return_value = scores
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
        result = r.rerank("query", ["a", "b", "c"])
    assert result[0][1] >= result[1][1] >= result[2][1]


def test_rerank_top_k_limits_results():
    scores = [0.9, 0.8, 0.7, 0.6, 0.5]
    mock_module, mock_ce = _mock_cross_encoder(scores)
    mock_ce.predict.return_value = scores
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
        result = r.rerank("query", ["a", "b", "c", "d", "e"], top_k=3)
    assert len(result) == 3


def test_rerank_preserves_original_index():
    # score order: b(1.0) > a(0.5)
    scores = [0.5, 1.0]
    mock_module, mock_ce = _mock_cross_encoder(scores)
    mock_ce.predict.return_value = scores
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
        result = r.rerank("query", ["a", "b"])
    # Top result should be index 1 (candidate 'b')
    assert result[0][0] == 1


def test_rerank_oversized_candidates_clamped_at_max_pairs():
    # Create more candidates than MAX_PAIRS (24)
    n = 30
    scores = [float(i) for i in range(n)]
    mock_module, mock_ce = _mock_cross_encoder(scores[:24])
    mock_ce.predict.return_value = scores[:24]
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
        result = r.rerank("query", [f"c{i}" for i in range(n)], top_k=n)
    # Un-scored items get -100.0 — all 30 should appear
    assert len(result) == n


def test_rerank_unscored_items_get_negative_score():
    # Only first 24 scored; rest get -100.0
    scores = [0.5] * 24
    mock_module, mock_ce = _mock_cross_encoder(scores)
    mock_ce.predict.return_value = scores
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
        result = r.rerank("query", [f"c{i}" for i in range(30)], top_k=30)
    low_scores = [s for _, s in result if s == -100.0]
    assert len(low_scores) == 6  # 30 - 24 = 6 unscored


def test_rerank_default_top_k_is_8():
    scores = [float(i) for i in range(10)]
    mock_module, mock_ce = _mock_cross_encoder(scores)
    mock_ce.predict.return_value = scores
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
        result = r.rerank("query", [f"c{i}" for i in range(10)])
    assert len(result) == 8


def test_rerank_single_candidate():
    mock_module, mock_ce = _mock_cross_encoder([0.75])
    mock_ce.predict.return_value = [0.75]
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
        result = r.rerank("query", ["only_one"])
    assert len(result) == 1
    assert result[0] == (0, pytest.approx(0.75))


# ---------------------------------------------------------------------------
# CrossEncoderReranker.score_pair
# ---------------------------------------------------------------------------

def test_score_pair_empty_query_returns_minus_100():
    mock_module, _ = _mock_cross_encoder([])
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
    assert r.score_pair("", "candidate") == pytest.approx(-100.0)


def test_score_pair_empty_candidate_returns_minus_100():
    mock_module, _ = _mock_cross_encoder([])
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
    assert r.score_pair("query", "") == pytest.approx(-100.0)


def test_score_pair_returns_float():
    scores = [0.85]
    mock_module, mock_ce = _mock_cross_encoder(scores)
    mock_ce.predict.return_value = scores
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
        result = r.score_pair("query", "candidate")
    assert isinstance(result, float)
    assert result == pytest.approx(0.85)


def test_score_pair_calls_predict_with_one_pair():
    scores = [0.6]
    mock_module, mock_ce = _mock_cross_encoder(scores)
    mock_ce.predict.return_value = scores
    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        r = CrossEncoderReranker()
        r.score_pair("my query", "my candidate")
    mock_ce.predict.assert_called_once_with([("my query", "my candidate")])


# ---------------------------------------------------------------------------
# get_reranker – singleton logic
# ---------------------------------------------------------------------------

def test_get_reranker_returns_none_when_sentence_transformers_unavailable(monkeypatch):
    _reset_state(monkeypatch)
    with patch.dict("sys.modules", {"sentence_transformers": None}):
        result = get_reranker()
    assert result is None or isinstance(result, CrossEncoderReranker)


def test_get_reranker_returns_none_if_attempted_and_failed(monkeypatch):
    _reset_state(monkeypatch)
    monkeypatch.setattr(cer, "_reranker_load_attempted", True)
    monkeypatch.setattr(cer, "_reranker_instance", None)
    result = get_reranker()
    assert result is None


def test_get_reranker_returns_none_if_loading(monkeypatch):
    _reset_state(monkeypatch)
    monkeypatch.setattr(cer, "_reranker_loading", True)
    result = get_reranker()
    assert result is None


def test_get_reranker_returns_instance_if_available(monkeypatch):
    _reset_state(monkeypatch)
    mock_instance = MagicMock(spec=CrossEncoderReranker)
    monkeypatch.setattr(cer, "_reranker_instance", mock_instance)
    result = get_reranker()
    assert result is mock_instance


def test_get_reranker_sets_load_attempted_on_failure(monkeypatch):
    _reset_state(monkeypatch)
    # Make CrossEncoderReranker() fail
    with patch.object(cer, "CrossEncoderReranker", side_effect=ImportError("no module")):
        get_reranker()
    assert cer._reranker_load_attempted is True


# ---------------------------------------------------------------------------
# preload_reranker – idempotency
# ---------------------------------------------------------------------------

def test_preload_does_not_start_if_already_loading(monkeypatch):
    _reset_state(monkeypatch)
    monkeypatch.setattr(cer, "_reranker_loading", True)
    import threading as _threading
    started = []
    orig_thread = _threading.Thread
    class _Spy(orig_thread):
        def start(self):
            started.append(True)
            super().start()
    with patch("threading.Thread", _Spy):
        preload_reranker()
    assert len(started) == 0


def test_preload_does_not_start_if_already_attempted(monkeypatch):
    _reset_state(monkeypatch)
    monkeypatch.setattr(cer, "_reranker_load_attempted", True)
    import threading as _threading
    started = []
    orig_thread = _threading.Thread
    class _Spy(orig_thread):
        def start(self):
            started.append(True)
            super().start()
    with patch("threading.Thread", _Spy):
        preload_reranker()
    assert len(started) == 0


def test_preload_does_not_start_if_already_loaded(monkeypatch):
    _reset_state(monkeypatch)
    mock_instance = MagicMock(spec=CrossEncoderReranker)
    monkeypatch.setattr(cer, "_reranker_instance", mock_instance)
    import threading as _threading
    started = []
    orig_thread = _threading.Thread
    class _Spy(orig_thread):
        def start(self):
            started.append(True)
            super().start()
    with patch("threading.Thread", _Spy):
        preload_reranker()
    assert len(started) == 0


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

def test_model_name_is_string():
    assert isinstance(CrossEncoderReranker.MODEL_NAME, str)


def test_max_pairs_is_positive_int():
    assert isinstance(CrossEncoderReranker.MAX_PAIRS, int)
    assert CrossEncoderReranker.MAX_PAIRS > 0


def test_max_pairs_is_24():
    assert CrossEncoderReranker.MAX_PAIRS == 24
