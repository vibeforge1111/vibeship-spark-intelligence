from __future__ import annotations

import json
from pathlib import Path

from lib.production_gates import (
    LoopMetrics,
    LoopThresholds,
    _load_loop_thresholds_from_tuneables,
    evaluate_gates,
    load_live_metrics,
)


def _check(result, name: str):
    for check in result["checks"]:
        if check["name"] == name:
            return check
    raise AssertionError(f"missing check: {name}")


def test_evaluate_gates_flags_counter_integrity_failure():
    metrics = LoopMetrics(
        total_stored=100,
        total_retrieved=20,
        retrieval_rate=0.2,
        acted_on=12,
        acted_on_rate=0.6,
        effectiveness_rate=0.7,
        strict_acted_on=10,
        strict_with_outcome=8,
        strict_acted_on_rate=0.5,
        strict_trace_coverage=0.83,
        strict_effectiveness_rate=0.75,
        strict_require_trace=True,
        strict_window_s=1200,
        quality_rate=0.45,
        distillations=10,
        queue_depth=100,
        advice_total=5,
        advice_followed=9,
        advice_helpful=2,
        chip_insights=500,
        chip_to_cognitive_ratio=5.0,
    )
    result = evaluate_gates(metrics)
    assert result["ready"] is False
    assert _check(result, "effectiveness_counter_integrity")["ok"] is False


def test_evaluate_gates_passes_for_healthy_profile():
    metrics = LoopMetrics(
        total_stored=200,
        total_retrieved=80,
        retrieval_rate=0.4,
        acted_on=40,
        acted_on_rate=0.5,
        effectiveness_rate=0.65,
        strict_acted_on=30,
        strict_with_outcome=24,
        strict_acted_on_rate=0.375,
        strict_trace_coverage=0.75,
        strict_effectiveness_rate=0.66,
        strict_require_trace=True,
        strict_window_s=1200,
        quality_rate=0.42,
        distillations=9,
        queue_depth=120,
        advice_total=100,
        advice_followed=70,
        advice_helpful=55,
        chip_insights=8000,
        chip_to_cognitive_ratio=40.0,
    )
    result = evaluate_gates(metrics)
    assert result["ready"] is True
    assert result["passed"] == result["total"]


def test_load_live_metrics_reads_local_files(monkeypatch, tmp_path: Path):
    spark_dir = tmp_path / ".spark"
    (spark_dir / "advisor").mkdir(parents=True)
    (spark_dir / "chip_insights").mkdir(parents=True)

    (spark_dir / "cognitive_insights.json").write_text(
        json.dumps({"k1": {"insight": "a"}, "k2": {"insight": "b"}}),
        encoding="utf-8",
    )
    (spark_dir / "advisor" / "effectiveness.json").write_text(
        json.dumps(
            {
                "total_advice_given": 10,
                "total_followed": 7,
                "total_helpful": 5,
            }
        ),
        encoding="utf-8",
    )
    (spark_dir / "chip_insights" / "demo.jsonl").write_text(
        '{"a":1}\n{"a":2}\n{"a":3}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr("lib.production_gates.SPARK_DIR", spark_dir)
    monkeypatch.setattr("lib.production_gates.EFFECTIVENESS_FILE", spark_dir / "advisor" / "effectiveness.json")
    monkeypatch.setattr("lib.production_gates.CHIP_INSIGHTS_DIR", spark_dir / "chip_insights")
    monkeypatch.setattr("lib.production_gates._count_chip_insights", lambda _p: 3)
    monkeypatch.setattr("lib.production_gates._count_stored_learnings", lambda _p: 2)

    # Make live data deterministic for this test.
    monkeypatch.setattr("lib.production_gates._read_meta_metrics", lambda: {})
    monkeypatch.setattr("lib.production_gates._read_distillation_count", lambda: 0)
    monkeypatch.setattr("lib.production_gates._read_queue_depth", lambda: 0)

    metrics = load_live_metrics()
    assert metrics.total_stored == 2
    assert metrics.advice_total == 10
    assert metrics.advice_followed == 7
    assert metrics.advice_helpful == 5
    assert metrics.chip_insights == 3
    assert metrics.retrieval_rate == 0.0


def test_evaluate_gates_uses_custom_thresholds():
    metrics = LoopMetrics(
        total_stored=100,
        total_retrieved=10,
        retrieval_rate=0.1,
        acted_on=2,
        acted_on_rate=0.2,
        effectiveness_rate=0.2,
        strict_acted_on=1,
        strict_with_outcome=1,
        strict_acted_on_rate=0.1,
        strict_trace_coverage=0.5,
        strict_effectiveness_rate=1.0,
        strict_require_trace=True,
        strict_window_s=900,
        quality_rate=0.2,
        distillations=1,
        queue_depth=5000,
        advice_total=10,
        advice_followed=8,
        advice_helpful=3,
        chip_insights=2000,
        chip_to_cognitive_ratio=20.0,
    )
    thresholds = LoopThresholds(
        min_retrieval_rate=0.05,
        min_acted_on_rate=0.1,
        min_effectiveness_rate=0.1,
        min_strict_acted_on_rate=0.05,
        min_strict_trace_coverage=0.40,
        min_strict_effectiveness_rate=0.8,
        min_strict_with_outcome=1,
        require_strict_trace_binding=True,
        max_strict_window_s=1200,
        min_distillations=1,
        min_quality_rate=0.15,
        max_quality_rate=0.80,
        max_queue_depth=6000,
        max_chip_to_cognitive_ratio=25.0,
    )
    result = evaluate_gates(metrics, thresholds=thresholds)
    assert result["ready"] is True


def test_load_live_metrics_uses_actionable_denominator(monkeypatch):
    monkeypatch.setattr("lib.production_gates._count_stored_learnings", lambda _p: 100)
    monkeypatch.setattr("lib.production_gates._count_chip_insights", lambda _p: 0)
    monkeypatch.setattr(
        "lib.production_gates._read_meta_metrics",
        lambda: {
            "total_retrieved": 80,
            "actionable_retrieved": 20,
            "ignored_non_actionable": 60,
            "acted_on": 10,
            "effectiveness_rate": 0.8,
            "strict_acted_on": 8,
            "strict_with_outcome": 6,
            "strict_effectiveness_rate": 2 / 3,
            "strict_require_trace": True,
            "strict_window_s": 1200,
            "quality_rate": 0.45,
        },
    )
    monkeypatch.setattr("lib.production_gates._read_distillation_count", lambda: 0)
    monkeypatch.setattr("lib.production_gates._read_queue_depth", lambda: 0)
    monkeypatch.setattr(
        "lib.production_gates._read_effectiveness_metrics",
        lambda: {
            "total_advice_given": 0,
            "total_followed": 0,
            "total_helpful": 0,
        },
    )

    metrics = load_live_metrics()
    assert metrics.total_retrieved == 80
    assert metrics.actionable_retrieved == 20
    assert metrics.ignored_non_actionable == 60
    assert metrics.acted_on == 10
    assert metrics.retrieval_rate == 0.8
    assert metrics.acted_on_rate == 0.5
    assert metrics.strict_acted_on_rate == 0.4
    assert metrics.strict_trace_coverage == 0.8
    assert round(metrics.strict_effectiveness_rate, 3) == round(2 / 3, 3)
    assert metrics.strict_require_trace is True
    assert metrics.strict_window_s == 1200


def test_load_live_metrics_honors_zero_actionable(monkeypatch):
    monkeypatch.setattr("lib.production_gates._count_stored_learnings", lambda _p: 50)
    monkeypatch.setattr("lib.production_gates._count_chip_insights", lambda _p: 0)
    monkeypatch.setattr(
        "lib.production_gates._read_meta_metrics",
        lambda: {
            "total_retrieved": 40,
            "actionable_retrieved": 0,
            "ignored_non_actionable": 40,
            "acted_on": 0,
            "effectiveness_rate": 0.0,
            "strict_acted_on": 0,
            "strict_with_outcome": 0,
            "strict_effectiveness_rate": 0.0,
            "strict_require_trace": True,
            "strict_window_s": 1200,
            "quality_rate": 0.45,
        },
    )
    monkeypatch.setattr("lib.production_gates._read_distillation_count", lambda: 0)
    monkeypatch.setattr("lib.production_gates._read_queue_depth", lambda: 0)
    monkeypatch.setattr(
        "lib.production_gates._read_effectiveness_metrics",
        lambda: {
            "total_advice_given": 0,
            "total_followed": 0,
            "total_helpful": 0,
        },
    )

    metrics = load_live_metrics()
    assert metrics.total_retrieved == 40
    assert metrics.actionable_retrieved == 0
    assert metrics.ignored_non_actionable == 40
    assert metrics.acted_on == 0
    assert metrics.acted_on_rate == 0.0
    assert metrics.strict_acted_on_rate == 0.0
    assert metrics.strict_trace_coverage == 0.0


def test_evaluate_gates_flags_strict_policy_and_coverage_failures():
    metrics = LoopMetrics(
        total_stored=200,
        total_retrieved=100,
        retrieval_rate=0.5,
        acted_on=60,
        acted_on_rate=0.6,
        effectiveness_rate=0.7,
        strict_acted_on=10,
        strict_with_outcome=10,
        strict_acted_on_rate=0.10,
        strict_trace_coverage=10 / 60,
        strict_effectiveness_rate=0.9,
        strict_require_trace=False,
        strict_window_s=7200,
        quality_rate=0.4,
        distillations=12,
        queue_depth=100,
        advice_total=100,
        advice_followed=80,
        advice_helpful=70,
        chip_insights=2000,
        chip_to_cognitive_ratio=10.0,
    )

    result = evaluate_gates(metrics)
    assert result["ready"] is False
    assert _check(result, "strict_attribution_policy")["ok"] is False
    assert _check(result, "strict_acted_on_rate")["ok"] is False
    assert _check(result, "strict_trace_coverage")["ok"] is False


def test_threshold_loader_disables_meta_quality_enforcement_without_env(tmp_path, monkeypatch):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps({"production_gates": {"enforce_meta_ralph_quality_band": True}}),
        encoding="utf-8",
    )
    monkeypatch.delenv("SPARK_ENFORCE_META_RALPH_QUALITY_BAND", raising=False)

    thresholds = _load_loop_thresholds_from_tuneables(path=tuneables)

    assert thresholds.enforce_meta_ralph_quality_band is False


def test_threshold_loader_allows_meta_quality_enforcement_with_env(tmp_path, monkeypatch):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps({"production_gates": {"enforce_meta_ralph_quality_band": True}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SPARK_ENFORCE_META_RALPH_QUALITY_BAND", "1")

    thresholds = _load_loop_thresholds_from_tuneables(path=tuneables)

    assert thresholds.enforce_meta_ralph_quality_band is True
