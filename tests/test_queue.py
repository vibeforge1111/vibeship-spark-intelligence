import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import lib.queue as queue


def _patch_queue_paths(tmp_path: Path, monkeypatch) -> None:
    queue_dir = tmp_path / "queue"
    monkeypatch.setattr(queue, "QUEUE_DIR", queue_dir)
    monkeypatch.setattr(queue, "EVENTS_FILE", queue_dir / "events.jsonl")
    monkeypatch.setattr(queue, "LOCK_FILE", queue_dir / ".queue.lock")
    monkeypatch.setattr(queue, "QUEUE_STATE_FILE", queue_dir / "state.json")


def test_quick_capture_and_read_recent_events(tmp_path, monkeypatch):
    _patch_queue_paths(tmp_path, monkeypatch)

    ok = queue.quick_capture(
        event_type=queue.EventType.USER_PROMPT,
        session_id="s1",
        data={"payload": {"text": "hello"}},
    )
    assert ok is True

    events = queue.read_recent_events(1)
    assert len(events) == 1
    assert events[0].event_type == queue.EventType.USER_PROMPT
    assert events[0].session_id == "s1"


def test_rotate_if_needed(tmp_path, monkeypatch):
    _patch_queue_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(queue, "MAX_EVENTS", 4)
    # Reset the rotation throttle so count_events() runs immediately
    monkeypatch.setattr(queue, "_last_count_check", 0.0)

    queue.QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    with queue.EVENTS_FILE.open("w", encoding="utf-8") as f:
        for i in range(6):
            event = queue.SparkEvent(
                event_type=queue.EventType.USER_PROMPT,
                session_id="s1",
                timestamp=time.time(),
                data={"i": i},
            )
            f.write(json.dumps(event.to_dict()) + "\n")

    rotated = queue.rotate_if_needed()
    assert rotated is True
    assert queue.count_events() == queue.MAX_EVENTS // 2


def test_lock_release_after_fd_close_failure(tmp_path, monkeypatch):
    """Lock file must be removed even when os.close() raises OSError.

    Regression test for the deadlock bug where a single try/except block
    around both os.close() and LOCK_FILE.unlink() caused the lock to stay
    on disk permanently if closing the fd failed.
    """
    _patch_queue_paths(tmp_path, monkeypatch)
    queue.QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    original_close = os.close

    def close_raises(fd):
        original_close(fd)
        raise OSError("simulated close failure")

    with patch("lib.queue.os.close", side_effect=close_raises):
        with queue._queue_lock() as lock:
            assert lock.acquired is True
        # After __exit__, the lock file must be gone regardless of the close error.
        assert not queue.LOCK_FILE.exists(), (
            "Lock file was not removed after os.close() failure — future "
            "lock attempts would deadlock permanently."
        )


def test_load_queue_config_corrupt_json_logs(tmp_path, monkeypatch, capfd):
    """Corrupted tuneables.json should log a debug message, not silently pass."""
    queue_dir = tmp_path / "queue"
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text("{this is not valid json", encoding="utf-8")

    monkeypatch.setattr(queue, "QUEUE_DIR", queue_dir)
    monkeypatch.setattr(queue, "TUNEABLES_FILE", tuneables)

    logged = []

    def fake_log(module, msg, exc=None):
        logged.append((module, msg))

    with patch("lib.queue.log_debug", side_effect=fake_log):
        result = queue._load_queue_config()

    assert result == {}, "Should return empty dict on parse failure"
    assert any("queue" in m[0] and "queue config" in m[1] for m in logged), (
        "Expected a log_debug call indicating the config load failure, got none. "
        "Silent failures make tuneables.json misconfiguration invisible."
    )


def test_load_queue_state_corrupt_json_logs(tmp_path, monkeypatch):
    """Corrupted state.json should log and return {}, not silently reset head."""
    _patch_queue_paths(tmp_path, monkeypatch)
    queue.QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    queue.QUEUE_STATE_FILE.write_text("{broken json", encoding="utf-8")

    logged = []

    def fake_log(module, msg, exc=None):
        logged.append((module, msg))

    with patch("lib.queue.log_debug", side_effect=fake_log):
        result = queue._load_queue_state()

    assert result == {}, "Should return empty dict on corrupt state"
    assert any("queue" in m[0] and "corrupt" in m[1] for m in logged), (
        "Expected a log_debug call when state.json is corrupted so that "
        "operators know head_bytes was reset (potentially causing event re-processing)."
    )
