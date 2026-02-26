import json
from pathlib import Path

from lib.tuneables_schema import SCHEMA


def _config_tuneables() -> dict:
    return json.loads(Path("config/tuneables.json").read_text(encoding="utf-8-sig"))


def test_critical_defaults_align_schema_and_config():
    cfg = _config_tuneables()
    keys = [
        ("bridge_worker", "mind_sync_limit"),
        ("bridge_worker", "mind_sync_queue_budget"),
        ("auto_tuner", "min_boost"),
        ("auto_tuner", "max_boost"),
        ("queue", "max_events"),
        ("queue", "max_queue_bytes"),
        ("queue", "compact_head_bytes"),
        ("queue", "tail_chunk_bytes"),
        ("pipeline", "importance_sampling_enabled"),
        ("pipeline", "low_priority_keep_rate"),
        ("pipeline", "macros_enabled"),
        ("memory_capture", "auto_save_threshold"),
        ("memory_capture", "suggest_threshold"),
        ("memory_capture", "context_capture_chars"),
        ("synthesizer", "mode"),
        ("semantic", "enabled"),
        ("triggers", "enabled"),
        ("promotion", "auto_interval_s"),
        ("eidos", "max_time_seconds"),
        ("memory_emotion", "enabled"),
        ("memory_learning", "enabled"),
        ("memory_retrieval_guard", "enabled"),
        ("advisory_gate", "agreement_gate_enabled"),
        ("advisory_gate", "agreement_min_sources"),
        ("advisory_packet_store", "packet_ttl_s"),
        ("advisory_prefetch", "worker_enabled"),
        ("sync", "mind_limit"),
        ("production_gates", "min_quality_samples"),
        ("request_tracker", "max_pending"),
    ]
    for section, key in keys:
        assert section in cfg, f"missing config section: {section}"
        assert section in SCHEMA, f"missing schema section: {section}"
        assert key in cfg[section], f"missing config key: {section}.{key}"
        assert key in SCHEMA[section], f"missing schema key: {section}.{key}"
        assert cfg[section][key] == SCHEMA[section][key].default
