from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.memory_quality_observatory import _retrieval_guardrails


def test_retrieval_guardrails_pass_when_metrics_meet_thresholds():
    snapshot = {
        "semantic_retrieval": {
            "sim_avg": 0.31,
            "sim_lt_0_1_ratio": 0.08,
            "dominant_key_ratio": 0.2,
        },
        "advisory_engine": {
            "emit_rate": 0.24,
            "global_dedupe_ratio": 0.3,
        },
        "capture": {"noise_like_ratio": 0.06},
        "context": {"p50": 180},
    }

    guardrails = _retrieval_guardrails(snapshot)

    assert guardrails["passing"] is True
    assert guardrails["failed_count"] == 0
    assert guardrails["failed_names"] == []
    assert all(check["pass"] for check in guardrails["checks"])


def test_retrieval_guardrails_fail_when_metrics_regress():
    snapshot = {
        "semantic_retrieval": {
            "sim_avg": 0.11,
            "sim_lt_0_1_ratio": 0.42,
            "dominant_key_ratio": 0.72,
        },
        "advisory_engine": {
            "emit_rate": 0.05,
            "global_dedupe_ratio": 0.8,
        },
        "capture": {"noise_like_ratio": 0.31},
        "context": {"p50": 44},
    }

    guardrails = _retrieval_guardrails(snapshot)

    assert guardrails["passing"] is False
    assert guardrails["failed_count"] >= 5
    assert "semantic.sim_avg" in guardrails["failed_names"]
    assert "advisory.emit_rate" in guardrails["failed_names"]
