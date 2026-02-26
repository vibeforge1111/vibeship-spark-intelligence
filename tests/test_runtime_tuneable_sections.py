from __future__ import annotations

import json

import lib.memory_capture as memory_capture
import lib.queue as queue_module
import lib.pattern_detection.request_tracker as request_tracker


def test_request_tracker_apply_updates_singleton(monkeypatch):
    monkeypatch.setattr(request_tracker, "_tracker", None)
    tracker = request_tracker.get_request_tracker()

    result = request_tracker.apply_request_tracker_config(
        {
            "max_pending": 80,
            "max_completed": 300,
            "max_age_seconds": 7200,
        }
    )

    assert "max_pending" in result.get("applied", [])
    assert "max_completed" in result.get("applied", [])
    assert "max_age_seconds" in result.get("applied", [])
    assert tracker.max_pending == 80
    assert tracker.max_completed == 300
    assert request_tracker.REQUEST_TRACKER_MAX_AGE_SECONDS == 7200.0


def test_memory_capture_apply_clamps_and_orders_thresholds(monkeypatch):
    monkeypatch.setattr(memory_capture, "AUTO_SAVE_THRESHOLD", 0.82)
    monkeypatch.setattr(memory_capture, "SUGGEST_THRESHOLD", 0.55)
    monkeypatch.setattr(memory_capture, "MAX_CAPTURE_CHARS", 2000)
    monkeypatch.setattr(memory_capture, "CONTEXT_CAPTURE_CHARS", 320)

    result = memory_capture.apply_memory_capture_config(
        {
            "auto_save_threshold": 0.7,
            "suggest_threshold": 0.9,
            "max_capture_chars": 4096,
            "context_capture_chars": 360,
        }
    )

    assert "auto_save_threshold" in result.get("applied", [])
    assert "suggest_threshold" in result.get("applied", [])
    assert "max_capture_chars" in result.get("applied", [])
    assert "context_capture_chars" in result.get("applied", [])
    assert memory_capture.AUTO_SAVE_THRESHOLD == 0.7
    assert memory_capture.SUGGEST_THRESHOLD <= memory_capture.AUTO_SAVE_THRESHOLD
    assert memory_capture.MAX_CAPTURE_CHARS == 4096
    assert memory_capture.CONTEXT_CAPTURE_CHARS == 360


def test_queue_apply_updates_limits(monkeypatch):
    monkeypatch.setattr(queue_module, "MAX_EVENTS", 10000)
    monkeypatch.setattr(queue_module, "TAIL_CHUNK_BYTES", 64 * 1024)

    result = queue_module.apply_queue_config(
        {
            "max_events": 15000,
            "tail_chunk_bytes": 131072,
        }
    )

    assert "max_events" in result.get("applied", [])
    assert "tail_chunk_bytes" in result.get("applied", [])
    assert queue_module.MAX_EVENTS == 15000
    assert queue_module.TAIL_CHUNK_BYTES == 131072


def test_queue_load_config_uses_runtime_and_env(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "queue": {
                    "max_events": 11111,
                    "tail_chunk_bytes": 32768,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(queue_module, "TUNEABLES_FILE", tuneables)
    monkeypatch.setenv("SPARK_QUEUE_MAX_EVENTS", "22222")

    cfg = queue_module._load_queue_config()

    assert cfg["max_events"] == 22222
    assert cfg["tail_chunk_bytes"] == 32768
