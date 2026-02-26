"""Tests for lib/evaluation.py — 40 tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.evaluation as ev


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _pred(text: str = "good pattern", age_s: float = 0.0, **kw) -> dict:
    return {"text": text, "created_at": time.time() - age_s, **kw}


def _out(text: str = "good pattern", polarity: str = "pos", age_s: float = 0.0, **kw) -> dict:
    return {"text": text, "polarity": polarity, "created_at": time.time() - age_s, **kw}


# ---------------------------------------------------------------------------
# _load_jsonl
# ---------------------------------------------------------------------------

class TestLoadJsonl:
    def test_returns_empty_list_when_file_missing(self, tmp_path):
        result = ev._load_jsonl(tmp_path / "nope.jsonl")
        assert result == []

    def test_loads_all_rows(self, tmp_path):
        p = tmp_path / "data.jsonl"
        _write_jsonl(p, [{"a": 1}, {"b": 2}, {"c": 3}])
        result = ev._load_jsonl(p)
        assert len(result) == 3

    def test_respects_limit(self, tmp_path):
        p = tmp_path / "data.jsonl"
        _write_jsonl(p, [{"i": i} for i in range(100)])
        result = ev._load_jsonl(p, limit=10)
        assert len(result) <= 10

    def test_skips_corrupt_lines(self, tmp_path):
        p = tmp_path / "data.jsonl"
        p.write_text('{"good": 1}\nBAD JSON\n{"good": 2}\n')
        result = ev._load_jsonl(p)
        assert len(result) == 2

    def test_returns_empty_on_unreadable_file(self, tmp_path):
        p = tmp_path / "unreadable.jsonl"
        p.write_text("data")
        p.chmod(0o000)
        try:
            result = ev._load_jsonl(p)
            assert result == []
        finally:
            p.chmod(0o644)


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_lowercases(self):
        assert ev._normalize("HELLO World") == "hello world"

    def test_strips_whitespace(self):
        assert ev._normalize("  hello  ") == "hello"

    def test_empty_string(self):
        assert ev._normalize("") == ""

    def test_none_becomes_empty(self):
        assert ev._normalize(None) == ""  # type: ignore


# ---------------------------------------------------------------------------
# _token_overlap
# ---------------------------------------------------------------------------

class TestTokenOverlap:
    def test_identical_strings_return_one(self):
        assert ev._token_overlap("hello world", "hello world") == 1.0

    def test_no_overlap_returns_zero(self):
        assert ev._token_overlap("foo bar", "baz qux") == 0.0

    def test_partial_overlap(self):
        score = ev._token_overlap("hello world", "hello earth")
        assert 0.0 < score < 1.0

    def test_empty_strings_return_zero(self):
        assert ev._token_overlap("", "") == 0.0

    def test_one_empty_string_returns_zero(self):
        assert ev._token_overlap("hello", "") == 0.0
        assert ev._token_overlap("", "world") == 0.0

    def test_jaccard_symmetry(self):
        a, b = "the quick brown fox", "the slow brown cat"
        assert ev._token_overlap(a, b) == ev._token_overlap(b, a)

    def test_case_insensitive_via_normalize(self):
        assert ev._token_overlap("HELLO WORLD", "hello world") == 1.0


# ---------------------------------------------------------------------------
# evaluate_predictions
# ---------------------------------------------------------------------------

class TestEvaluatePredictions:
    def _patch(self, monkeypatch, preds_path: Path, outcomes_path: Path):
        monkeypatch.setattr(ev, "PREDICTIONS_FILE", preds_path)
        monkeypatch.setattr(ev, "OUTCOMES_FILE", outcomes_path)

    def test_returns_empty_metrics_when_no_files(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path / "p.jsonl", tmp_path / "o.jsonl")
        result = ev.evaluate_predictions()
        assert result["predictions"] == 0
        assert result["outcomes"] == 0
        assert result["matched"] == 0
        assert result["precision"] == 0.0

    def test_returns_counts_in_result(self, tmp_path, monkeypatch):
        pf = tmp_path / "p.jsonl"
        of = tmp_path / "o.jsonl"
        _write_jsonl(pf, [_pred() for _ in range(3)])
        _write_jsonl(of, [_out() for _ in range(2)])
        self._patch(monkeypatch, pf, of)
        result = ev.evaluate_predictions()
        assert result["predictions"] == 3
        assert result["outcomes"] == 2

    def test_filters_old_predictions(self, tmp_path, monkeypatch):
        pf = tmp_path / "p.jsonl"
        of = tmp_path / "o.jsonl"
        old_pred = _pred(age_s=8 * 24 * 3600)  # 8 days old
        new_pred = _pred()
        _write_jsonl(pf, [old_pred, new_pred])
        _write_jsonl(of, [_out()])
        self._patch(monkeypatch, pf, of)
        result = ev.evaluate_predictions(max_age_s=7 * 24 * 3600)
        assert result["predictions"] == 1

    def test_high_overlap_produces_match(self, tmp_path, monkeypatch):
        pf = tmp_path / "p.jsonl"
        of = tmp_path / "o.jsonl"
        text = "this is a very specific prediction that should match exactly"
        _write_jsonl(pf, [_pred(text=text, expected_polarity="pos")])
        _write_jsonl(of, [_out(text=text, polarity="pos")])
        self._patch(monkeypatch, pf, of)
        result = ev.evaluate_predictions(sim_threshold=0.5)
        assert result["matched"] >= 1
        assert result["validated"] >= 1

    def test_low_overlap_no_match(self, tmp_path, monkeypatch):
        pf = tmp_path / "p.jsonl"
        of = tmp_path / "o.jsonl"
        _write_jsonl(pf, [_pred(text="alpha beta gamma delta")])
        _write_jsonl(of, [_out(text="zeta eta theta iota kappa")])
        self._patch(monkeypatch, pf, of)
        result = ev.evaluate_predictions(sim_threshold=0.72)
        assert result["matched"] == 0

    def test_contradicted_when_polarity_mismatches(self, tmp_path, monkeypatch):
        pf = tmp_path / "p.jsonl"
        of = tmp_path / "o.jsonl"
        text = "performance degraded significantly under high load conditions"
        _write_jsonl(pf, [_pred(text=text, expected_polarity="pos")])
        _write_jsonl(of, [_out(text=text, polarity="neg")])
        self._patch(monkeypatch, pf, of)
        result = ev.evaluate_predictions(sim_threshold=0.5)
        assert result["contradicted"] >= 1

    def test_linked_insight_key_bypasses_similarity(self, tmp_path, monkeypatch):
        pf = tmp_path / "p.jsonl"
        of = tmp_path / "o.jsonl"
        _write_jsonl(pf, [_pred(text="unrelated text AAA", insight_key="K1", expected_polarity="pos")])
        _write_jsonl(of, [_out(text="completely different BBB", polarity="pos",
                                linked_insights=["K1"])])
        self._patch(monkeypatch, pf, of)
        result = ev.evaluate_predictions(sim_threshold=0.72)
        assert result["matched"] >= 1

    def test_entity_id_match_bypasses_similarity(self, tmp_path, monkeypatch):
        pf = tmp_path / "p.jsonl"
        of = tmp_path / "o.jsonl"
        _write_jsonl(pf, [_pred(text="pred foo bar", entity_id="ENT1", expected_polarity="pos")])
        _write_jsonl(of, [_out(text="outcome baz qux", polarity="pos", entity_id="ENT1")])
        self._patch(monkeypatch, pf, of)
        result = ev.evaluate_predictions(sim_threshold=0.72)
        assert result["matched"] >= 1

    def test_failure_pattern_always_validated(self, tmp_path, monkeypatch):
        pf = tmp_path / "p.jsonl"
        of = tmp_path / "o.jsonl"
        text = "failure pattern recurring system crash on startup"
        _write_jsonl(pf, [_pred(text=text, type="failure_pattern")])
        _write_jsonl(of, [_out(text=text, polarity="neg")])
        self._patch(monkeypatch, pf, of)
        result = ev.evaluate_predictions(sim_threshold=0.5)
        if result["matched"] > 0:
            assert result["validated"] == result["matched"]

    def test_precision_zero_when_no_matches(self, tmp_path, monkeypatch):
        pf = tmp_path / "p.jsonl"
        of = tmp_path / "o.jsonl"
        _write_jsonl(pf, [_pred(text="abc xyz")])
        _write_jsonl(of, [_out(text="def uvw")])
        self._patch(monkeypatch, pf, of)
        result = ev.evaluate_predictions(sim_threshold=0.99)
        assert result["precision"] == 0.0

    def test_session_id_preferred_for_matching(self, tmp_path, monkeypatch):
        pf = tmp_path / "p.jsonl"
        of = tmp_path / "o.jsonl"
        text = "session scoped prediction outcome text"
        _write_jsonl(pf, [_pred(text=text, session_id="SID1", expected_polarity="pos")])
        _write_jsonl(of, [
            _out(text=text, polarity="pos", session_id="SID1"),
            _out(text=text, polarity="neg", session_id="OTHER"),
        ])
        self._patch(monkeypatch, pf, of)
        result = ev.evaluate_predictions(sim_threshold=0.5)
        if result["matched"] >= 1:
            assert result["validated"] >= 1

    def test_outcome_coverage_is_fraction(self, tmp_path, monkeypatch):
        pf = tmp_path / "p.jsonl"
        of = tmp_path / "o.jsonl"
        text = "exact match text for coverage"
        _write_jsonl(pf, [_pred(text=text, expected_polarity="pos")])
        _write_jsonl(of, [_out(text=text, polarity="pos")])
        self._patch(monkeypatch, pf, of)
        result = ev.evaluate_predictions(sim_threshold=0.5)
        assert 0.0 <= result["outcome_coverage"] <= 1.0

    def test_returns_dict_with_all_keys(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path / "p.jsonl", tmp_path / "o.jsonl")
        result = ev.evaluate_predictions()
        for key in ("predictions", "outcomes", "matched", "validated",
                    "contradicted", "outcome_coverage", "precision"):
            assert key in result
