"""Canonical metrics contract for Spark Alpha runtime and observability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

METRIC_CONTRACT_VERSION = "2026-02-26.alpha.v1"


RETRIEVAL_GUARDRAIL_THRESHOLDS: Dict[str, float] = {
    "semantic_sim_avg_min": 0.22,
    "semantic_sim_low_ratio_max": 0.20,
    "semantic_dominant_key_ratio_max": 0.35,
    "advisory_emit_rate_min": 0.15,
    "advisory_global_dedupe_ratio_max": 0.55,
    "capture_noise_ratio_max": 0.15,
    "context_p50_min": 120.0,
}


@dataclass(frozen=True)
class DriftMetricSpec:
    metric_id: str
    canonical_metric: str
    tolerance_abs: float
    unit: str
    formula: str
    canonical_source: str


DRIFT_METRICS: Dict[str, DriftMetricSpec] = {
    "memory_noise_ratio": DriftMetricSpec(
        metric_id="memory_noise_ratio",
        canonical_metric="capture.noise_like_ratio",
        tolerance_abs=0.03,
        unit="ratio",
        formula="capture_noise_like_count / capture_count over the drift window",
        canonical_source="_observatory/memory_quality_snapshot.json:capture.noise_like_ratio",
    ),
    "context_p50_chars": DriftMetricSpec(
        metric_id="context_p50_chars",
        canonical_metric="context.p50",
        tolerance_abs=12.0,
        unit="chars",
        formula="median(len(context)) over cognitive insights in drift window",
        canonical_source="_observatory/memory_quality_snapshot.json:context.p50",
    ),
    "advisory_emit_rate": DriftMetricSpec(
        metric_id="advisory_emit_rate",
        canonical_metric="advisory_engine.emit_rate",
        tolerance_abs=0.02,
        unit="ratio",
        formula="emitted / (emitted + no_emit_or_blocked) over the drift window",
        canonical_source="_observatory/memory_quality_snapshot.json:advisory_engine.emit_rate",
    ),
}


def metric_contract_payload() -> Dict[str, object]:
    return {
        "version": METRIC_CONTRACT_VERSION,
        "retrieval_guardrail_thresholds": dict(RETRIEVAL_GUARDRAIL_THRESHOLDS),
        "drift_metrics": {
            metric_id: {
                "canonical_metric": spec.canonical_metric,
                "tolerance_abs": spec.tolerance_abs,
                "unit": spec.unit,
                "formula": spec.formula,
                "canonical_source": spec.canonical_source,
            }
            for metric_id, spec in DRIFT_METRICS.items()
        },
    }
