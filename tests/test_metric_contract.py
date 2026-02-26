from __future__ import annotations

from lib.metric_contract import (
    DRIFT_METRICS,
    METRIC_CONTRACT_VERSION,
    RETRIEVAL_GUARDRAIL_THRESHOLDS,
    metric_contract_payload,
)


def test_metric_contract_payload_has_expected_keys():
    payload = metric_contract_payload()
    assert payload["version"] == METRIC_CONTRACT_VERSION
    assert "retrieval_guardrail_thresholds" in payload
    assert "drift_metrics" in payload


def test_retrieval_guardrails_include_core_thresholds():
    assert RETRIEVAL_GUARDRAIL_THRESHOLDS["semantic_sim_avg_min"] >= 0.2
    assert RETRIEVAL_GUARDRAIL_THRESHOLDS["capture_noise_ratio_max"] <= 0.2
    assert RETRIEVAL_GUARDRAIL_THRESHOLDS["context_p50_min"] >= 80


def test_drift_metric_specs_cover_core_metrics():
    assert "memory_noise_ratio" in DRIFT_METRICS
    assert "context_p50_chars" in DRIFT_METRICS
    assert "advisory_emit_rate" in DRIFT_METRICS
