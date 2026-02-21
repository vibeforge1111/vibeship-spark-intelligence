"""Test queue concurrency: no events lost under concurrent access."""

import json
import threading
import time
from pathlib import Path

import lib.queue as queue


def _patch_queue_paths(tmp_path: Path, monkeypatch) -> None:
    queue_dir = tmp_path / "queue"
    monkeypatch.setattr(queue, "QUEUE_DIR", queue_dir)
    monkeypatch.setattr(queue, "EVENTS_FILE", queue_dir / "events.jsonl")
    monkeypatch.setattr(queue, "LOCK_FILE", queue_dir / ".queue.lock")
    monkeypatch.setattr(queue, "OVERFLOW_FILE", queue_dir / "events.overflow.jsonl")
    # Isolate the queue state file so tests don't read/write the real
    # ~/.spark/queue/state.json (head_bytes stored there would cause
    # consume_processed to start at a wrong offset in the temp file).
    monkeypatch.setattr(queue, "QUEUE_STATE_FILE", queue_dir / "state.json")


def _merge_overflow(queue_mod):
    """Merge any overflow events into the main queue file."""
    overflow = queue_mod.OVERFLOW_FILE
    if overflow.exists():
        data = overflow.read_text(encoding="utf-8")
        if data.strip():
            with open(queue_mod.EVENTS_FILE, "a", encoding="utf-8") as f:
                f.write(data)
        overflow.unlink()


def test_concurrent_writes_no_loss(tmp_path, monkeypatch):
    """Multiple threads writing simultaneously should lose zero events."""
    _patch_queue_paths(tmp_path, monkeypatch)
    # Disable rotation to isolate the write test
    monkeypatch.setattr(queue, "MAX_EVENTS", 0)
    monkeypatch.setattr(queue, "MAX_QUEUE_BYTES", 0)

    n_threads = 5
    n_events_per_thread = 20
    total_expected = n_threads * n_events_per_thread

    def writer(thread_id):
        for i in range(n_events_per_thread):
            queue.quick_capture(
                event_type=queue.EventType.USER_PROMPT,
                session_id=f"t{thread_id}",
                data={"thread": thread_id, "i": i},
            )

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Merge overflow before counting
    _merge_overflow(queue)

    count = queue.count_events()
    assert count == total_expected, f"Expected {total_expected}, got {count}"


def test_concurrent_write_and_consume(tmp_path, monkeypatch):
    """Writer + consumer running concurrently should not lose events."""
    _patch_queue_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(queue, "MAX_EVENTS", 0)
    monkeypatch.setattr(queue, "MAX_QUEUE_BYTES", 0)

    # Pre-populate with 50 events
    queue.QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(50):
        queue.quick_capture(
            event_type=queue.EventType.POST_TOOL,
            session_id="pre",
            data={"i": i},
        )

    assert queue.count_events() == 50

    consumed = []
    written_ok = []

    def consumer():
        c = queue.consume_processed(25)
        consumed.append(c)

    def writer():
        for i in range(10):
            ok = queue.quick_capture(
                event_type=queue.EventType.USER_PROMPT,
                session_id="concurrent",
                data={"i": i},
            )
            written_ok.append(ok)
            time.sleep(0.002)

    t1 = threading.Thread(target=consumer)
    t2 = threading.Thread(target=writer)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Merge overflow (consumer already merges, but writer may have produced more)
    _merge_overflow(queue)

    final_count = queue.count_events()
    n_consumed = consumed[0] if consumed else 0
    n_written = sum(1 for ok in written_ok if ok)
    expected = 50 - n_consumed + n_written
    assert final_count == expected, (
        f"Expected {expected} (50 - {n_consumed} + {n_written}), got {final_count}"
    )


def test_lock_exit_does_not_delete_others_lock(tmp_path, monkeypatch):
    """If lock acquisition times out, __exit__ must NOT delete the lock file."""
    _patch_queue_paths(tmp_path, monkeypatch)
    queue.QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    # Simulate another holder by creating the lock file externally
    queue.LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(queue.LOCK_FILE, "w") as f:
        f.write("held-by-other")

    # Try to acquire with very short timeout -- should fail
    lock = queue._queue_lock(timeout_s=0.02)
    with lock:
        assert not lock.acquired
        assert lock.fd is None

    # Lock file must still exist (not deleted by our failed acquisition)
    assert queue.LOCK_FILE.exists()


def test_lock_acquired_flag(tmp_path, monkeypatch):
    """Successful lock acquisition sets acquired=True."""
    _patch_queue_paths(tmp_path, monkeypatch)
    queue.QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    lock = queue._queue_lock(timeout_s=0.5)
    with lock:
        assert lock.acquired is True
        assert lock.fd is not None

    # After exiting, lock file should be cleaned up
    assert not queue.LOCK_FILE.exists()


def test_overflow_sidecar_created_on_contention(tmp_path, monkeypatch):
    """When lock is held, quick_capture writes to overflow file."""
    _patch_queue_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(queue, "MAX_EVENTS", 0)
    monkeypatch.setattr(queue, "MAX_QUEUE_BYTES", 0)
    queue.QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    # Hold the lock so quick_capture can't acquire it
    lock_fd = None
    try:
        lock_fd = queue.os.open(
            str(queue.LOCK_FILE), queue.os.O_CREAT | queue.os.O_EXCL | queue.os.O_RDWR
        )

        ok = queue.quick_capture(
            event_type=queue.EventType.USER_PROMPT,
            session_id="overflow_test",
            data={"text": "should go to overflow"},
        )
        assert ok is True

        # Event should be in overflow, not main file
        assert queue.OVERFLOW_FILE.exists()
        overflow_lines = queue.OVERFLOW_FILE.read_text().strip().split("\n")
        assert len(overflow_lines) == 1
    finally:
        if lock_fd is not None:
            queue.os.close(lock_fd)
            if queue.LOCK_FILE.exists():
                queue.LOCK_FILE.unlink()


def test_consume_merges_overflow(tmp_path, monkeypatch):
    """consume_processed merges overflow events before consuming."""
    _patch_queue_paths(tmp_path, monkeypatch)
    queue.QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    # Write 3 events to main file
    for i in range(3):
        ev = queue.SparkEvent(
            event_type=queue.EventType.POST_TOOL,
            session_id="main",
            timestamp=time.time(),
            data={"i": i},
        )
        with open(queue.EVENTS_FILE, "a") as f:
            f.write(json.dumps(ev.to_dict()) + "\n")

    # Write 2 events to overflow
    for i in range(2):
        ev = queue.SparkEvent(
            event_type=queue.EventType.USER_PROMPT,
            session_id="overflow",
            timestamp=time.time(),
            data={"i": i},
        )
        with open(queue.OVERFLOW_FILE, "a") as f:
            f.write(json.dumps(ev.to_dict()) + "\n")

    # Consume first 2 events -- should merge overflow first
    removed = queue.consume_processed(2)
    assert removed == 2

    # 3 original - 2 consumed + 2 overflow = 3 remaining
    remaining = queue.count_events()
    assert remaining == 3

    # Overflow file should be gone
    assert not queue.OVERFLOW_FILE.exists()
