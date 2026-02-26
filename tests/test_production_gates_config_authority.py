from __future__ import annotations

import json

from lib import production_gates


def test_load_loop_thresholds_resolves_baseline_and_runtime(tmp_path):
    baseline = tmp_path / "baseline.json"
    runtime = tmp_path / "runtime.json"
    baseline.write_text(
        json.dumps(
            {
                "production_gates": {
                    "min_quality_samples": 80,
                    "max_advisory_store_queue_depth": 900,
                }
            }
        ),
        encoding="utf-8",
    )
    runtime.write_text(
        json.dumps(
            {
                "production_gates": {
                    "min_quality_samples": 120,
                }
            }
        ),
        encoding="utf-8",
    )

    thresholds = production_gates._load_loop_thresholds_from_tuneables(
        runtime,
        baseline_path=baseline,
    )

    assert thresholds.min_quality_samples == 120
    assert thresholds.max_advisory_store_queue_depth == 900
    assert thresholds.min_retrieval_rate == 0.10
