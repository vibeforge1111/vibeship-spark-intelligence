from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[1]
    module_path = root / "scripts" / "spark_alpha_replay_arena.py"
    spec = importlib.util.spec_from_file_location("spark_alpha_replay_arena", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load spark_alpha_replay_arena module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_weights_normalizes_sum_to_one():
    mod = _load_module()
    weights = mod.parse_weights("0.5,0.2,0.2,0.1")
    assert round(sum(weights.values()), 6) == 1.0
    assert weights["utility"] > weights["latency"]


def test_compute_weighted_score_prefers_stronger_metrics():
    mod = _load_module()
    weights = mod.parse_weights("0.45,0.20,0.20,0.15")
    weak = mod.compute_weighted_score(
        utility=0.2,
        safety=0.9,
        trace=0.9,
        latency=0.9,
        weights=weights,
    )
    strong = mod.compute_weighted_score(
        utility=0.9,
        safety=0.9,
        trace=0.9,
        latency=0.9,
        weights=weights,
    )
    assert strong > weak


def test_consecutive_promotion_wins_counts_only_tail_streak():
    mod = _load_module()
    rows = [
        {"promotion_gate_pass": True},
        {"promotion_gate_pass": True},
        {"promotion_gate_pass": False},
        {"promotion_gate_pass": True},
        {"promotion_gate_pass": True},
    ]
    assert mod.consecutive_promotion_wins(rows) == 2


def test_build_diff_reports_weighted_and_rate_deltas():
    mod = _load_module()
    previous = {
        "winner": {"route": "legacy"},
        "scorecards": {
            "legacy": {"weighted_score": 0.6},
            "alpha": {
                "weighted_score": 0.55,
                "emit_rate": 0.20,
                "safety_rate": 1.0,
                "question_like_emit_rate": 0.10,
                "trace_integrity_rate": 0.95,
                "latency_p95_ms": 900.0,
            },
        },
    }
    current = {
        "winner": {"route": "alpha"},
        "scorecards": {
            "legacy": {"weighted_score": 0.58},
            "alpha": {
                "weighted_score": 0.62,
                "emit_rate": 0.30,
                "safety_rate": 1.0,
                "question_like_emit_rate": 0.0,
                "trace_integrity_rate": 0.97,
                "latency_p95_ms": 850.0,
            },
        },
    }
    diff = mod.build_diff(current, previous)
    assert diff["winner_changed"] is True
    assert diff["challenger_weighted_delta"] > 0
    assert diff["challenger_emit_rate_delta"] > 0
    assert diff["challenger_question_like_emit_delta"] < 0
    assert diff["challenger_latency_p95_delta_ms"] < 0


def test_question_like_emit_detects_conversational_patterns():
    mod = _load_module()
    assert mod._question_like_emit("What should we do next?") is True
    assert mod._question_like_emit("Can you re-check the wiring before promoting?") is True
    assert mod._question_like_emit("Verify contracts before changing payload shapes.") is False


def _card(mod, *, weighted: float, safety: float, trace: float, question_like: float):
    return mod.Scorecard(
        route="alpha",
        episodes=10,
        emitted=10,
        emit_rate=1.0,
        utility_actionability_avg=0.8,
        utility_score=0.9,
        safety_rate=safety,
        question_like_emit_rate=question_like,
        trace_integrity_rate=trace,
        latency_avg_ms=100.0,
        latency_p95_ms=120.0,
        latency_score=1.0,
        weighted_score=weighted,
    )


def test_evaluate_promotion_gate_blocks_question_like_rate():
    mod = _load_module()
    orchestrator = _card(mod, weighted=0.6, safety=1.0, trace=1.0, question_like=0.0)
    alpha = _card(mod, weighted=0.9, safety=1.0, trace=1.0, question_like=0.2)
    gate = mod.evaluate_promotion_gate(
        alpha_card=alpha,
        orchestrator_card=orchestrator,
        require_safety_floor=0.98,
        require_trace_floor=0.95,
        max_question_like_rate=0.0,
    )
    assert gate["alpha_win_weighted"] is True
    assert gate["question_gate"] is False
    assert gate["promotion_gate_pass"] is False


def test_question_like_examples_collects_preview_rows():
    mod = _load_module()
    rows = [
        mod.EpisodeResult(
            episode_id="ep-1",
            trace_id="arena:t:1",
            emitted=True,
            text_preview="What should we do now?",
            latency_ms=10.0,
            utility_actionability=0.2,
            harmful_emit=False,
            question_like_emit=True,
            trace_ok=True,
            trace_event="emitted",
        ),
        mod.EpisodeResult(
            episode_id="ep-2",
            trace_id="arena:t:2",
            emitted=True,
            text_preview="Verify contracts before changing payload shapes.",
            latency_ms=12.0,
            utility_actionability=0.8,
            harmful_emit=False,
            question_like_emit=False,
            trace_ok=True,
            trace_event="emitted",
        ),
    ]
    out = mod._question_like_examples(rows, limit=3)
    assert len(out) == 1
    assert out[0]["episode_id"] == "ep-1"
