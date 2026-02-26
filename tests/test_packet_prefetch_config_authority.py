from __future__ import annotations

import json

import lib.advisory_packet_store as packet_store
import lib.advisory_prefetch_worker as prefetch_worker


def test_packet_store_load_config_resolves_precedence(tmp_path):
    baseline = tmp_path / "baseline.json"
    runtime = tmp_path / "runtime.json"
    baseline.write_text(
        json.dumps(
            {
                "advisory_packet_store": {
                    "packet_ttl_s": 700,
                    "max_index_packets": 3100,
                }
            }
        ),
        encoding="utf-8",
    )
    runtime.write_text(
        json.dumps(
            {
                "advisory_packet_store": {
                    "packet_ttl_s": 900,
                }
            }
        ),
        encoding="utf-8",
    )

    cfg = packet_store._load_packet_store_config(runtime, baseline_path=baseline)

    assert cfg["packet_ttl_s"] == 900
    assert cfg["max_index_packets"] == 3100
    assert cfg["packet_lookup_candidates"] == 6


def test_prefetch_load_config_supports_env_override(monkeypatch, tmp_path):
    baseline = tmp_path / "baseline.json"
    runtime = tmp_path / "runtime.json"
    baseline.write_text(
        json.dumps(
            {
                "advisory_prefetch": {
                    "worker_enabled": False,
                    "max_tools_per_job": 2,
                }
            }
        ),
        encoding="utf-8",
    )
    runtime.write_text(
        json.dumps(
            {
                "advisory_prefetch": {
                    "max_jobs_per_run": 7,
                    "min_probability": 0.4,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SPARK_ADVISORY_PREFETCH_WORKER", "1")

    cfg = prefetch_worker._load_prefetch_config(runtime, baseline_path=baseline)

    assert cfg["worker_enabled"] is True
    assert cfg["max_jobs_per_run"] == 7
    assert cfg["max_tools_per_job"] == 2
    assert cfg["min_probability"] == 0.4
