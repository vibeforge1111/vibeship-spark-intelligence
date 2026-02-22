"""
Spark Event Queue: Ultra-fast event capture

Events are captured in < 10ms and written to a local queue file.
Background processing handles the heavy lifting (learning, syncing).

This ensures:
1. Hooks never slow down the AI agent
2. No events are lost
3. Processing happens asynchronously
"""

import json
import os
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass, asdict

from lib.diagnostics import log_debug

# ============= Configuration =============
QUEUE_DIR = Path.home() / ".spark" / "queue"
EVENTS_FILE = QUEUE_DIR / "events.jsonl"
MAX_EVENTS = int(os.environ.get("SPARK_QUEUE_MAX_EVENTS", "10000"))  # Rotate after this many events
MAX_QUEUE_BYTES = int(os.environ.get("SPARK_QUEUE_MAX_BYTES", "10485760"))  # 10 MB
LOCK_FILE = QUEUE_DIR / ".queue.lock"
OVERFLOW_FILE = QUEUE_DIR / "events.overflow.jsonl"
QUEUE_STATE_FILE = QUEUE_DIR / "state.json"
QUEUE_COMPACT_HEAD_BYTES = int(os.environ.get("SPARK_QUEUE_COMPACT_HEAD_BYTES", str(5 * 1024 * 1024)))
TUNEABLES_FILE = Path.home() / ".spark" / "tuneables.json"

# Read the tail in chunks to avoid loading large files into memory.
TAIL_CHUNK_BYTES = 64 * 1024

# Throttle the O(n) count_events() call inside rotate_if_needed.
_last_count_check: float = 0.0
_COUNT_CHECK_INTERVAL: float = 60.0
_last_count_value: Optional[int] = None
_last_count_value_ts: float = 0.0
_COUNT_CACHE_TTL_S: float = 1.0


def _load_queue_config() -> Dict[str, Any]:
    try:
        if TUNEABLES_FILE.exists():
            # Accept UTF-8 with BOM (common on Windows).
            data = json.loads(TUNEABLES_FILE.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                cfg = data.get("queue") or {}
                if isinstance(cfg, dict):
                    return cfg
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        log_debug("queue", "failed to load queue config from tuneables.json", e)
    return {}


def _apply_queue_config(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    global MAX_EVENTS
    global TAIL_CHUNK_BYTES

    applied: List[str] = []
    warnings: List[str] = []
    if not isinstance(cfg, dict):
        return {"applied": applied, "warnings": warnings}

    if "max_events" in cfg:
        try:
            MAX_EVENTS = max(100, min(1_000_000, int(cfg.get("max_events") or 100)))
            applied.append("max_events")
        except (ValueError, TypeError):
            warnings.append("invalid_max_events")

    if "tail_chunk_bytes" in cfg:
        try:
            TAIL_CHUNK_BYTES = max(4096, min(4 * 1024 * 1024, int(cfg.get("tail_chunk_bytes") or 4096)))
            applied.append("tail_chunk_bytes")
        except (ValueError, TypeError):
            warnings.append("invalid_tail_chunk_bytes")

    return {"applied": applied, "warnings": warnings}


def apply_queue_config(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    return _apply_queue_config(cfg)


def get_queue_config() -> Dict[str, Any]:
    return {
        "max_events": int(MAX_EVENTS),
        "tail_chunk_bytes": int(TAIL_CHUNK_BYTES),
    }


_apply_queue_config(_load_queue_config())

try:
    from lib.tuneables_reload import register_reload as _queue_register
    _queue_register("queue", apply_queue_config, label="queue.apply_config")
except ImportError:
    pass


def _load_queue_state() -> Dict[str, Any]:
    if not QUEUE_STATE_FILE.exists():
        return {}
    try:
        return json.loads(QUEUE_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_queue_state(state: Dict[str, Any]) -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        QUEUE_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        log_debug("queue", "save state failed", e)


def _queue_head_bytes() -> int:
    state = _load_queue_state()
    head = int(state.get("head_bytes") or 0)
    if not EVENTS_FILE.exists():
        if head != 0:
            state["head_bytes"] = 0
            _save_queue_state(state)
        return 0
    try:
        size = EVENTS_FILE.stat().st_size
    except Exception:
        size = 0
    if head < 0:
        head = 0
    if head > size:
        head = 0
        state["head_bytes"] = 0
        _save_queue_state(state)
    return head


def _set_queue_head_bytes(head_bytes: int) -> None:
    state = _load_queue_state()
    state["head_bytes"] = max(0, int(head_bytes or 0))
    _save_queue_state(state)


def _invalidate_count_cache() -> None:
    global _last_count_value, _last_count_value_ts
    _last_count_value = None
    _last_count_value_ts = 0.0


def _active_file_bytes() -> int:
    if not EVENTS_FILE.exists():
        return 0
    try:
        size = EVENTS_FILE.stat().st_size
    except Exception:
        return 0
    head = _queue_head_bytes()
    return max(0, size - head)


def _iter_active_lines_iter(path: Path):
    """Yield decoded active lines from queue head to end (streaming).

    This avoids materializing the entire queue into memory.
    """
    if not path.exists():
        return
    head = _queue_head_bytes()
    try:
        with path.open("rb") as f:
            f.seek(head)
            for raw in f:
                if not raw:
                    continue
                yield raw.decode("utf-8", errors="replace").rstrip("\r\n")
    except Exception as e:
        log_debug("queue", "_iter_active_lines failed", e)
        return


def _iter_active_lines(path: Path) -> List[str]:
    """Return decoded active lines from queue head to end.

    Prefer _iter_active_lines_iter() in hot paths.
    """
    return list(_iter_active_lines_iter(path) or [])


def _merge_overflow_locked() -> None:
    """Merge overflow sidecar into main queue (requires queue lock held)."""
    if not OVERFLOW_FILE.exists():
        return
    try:
        overflow_data = OVERFLOW_FILE.read_text(encoding="utf-8")
        if overflow_data.strip():
            with open(EVENTS_FILE, "a", encoding="utf-8") as f:
                f.write(overflow_data)
        OVERFLOW_FILE.unlink()
        _invalidate_count_cache()
    except Exception as e:
        log_debug("queue", "overflow merge failed", e)


class EventType(Enum):
    """Types of events Spark captures."""
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_PROMPT = "user_prompt"
    PRE_TOOL = "pre_tool"
    POST_TOOL = "post_tool"
    POST_TOOL_FAILURE = "post_tool_failure"
    STOP = "stop"
    LEARNING = "learning"
    ERROR = "error"


@dataclass
class SparkEvent:
    """A captured event."""
    event_type: EventType
    session_id: str
    timestamp: float
    data: Dict[str, Any]
    tool_name: Optional[str] = None
    tool_input: Optional[Dict] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d
    
    @classmethod
    def from_dict(cls, data: Dict) -> "SparkEvent":
        """Create from dictionary."""
        data["event_type"] = EventType(data["event_type"])
        return cls(**data)


def quick_capture(event_type: EventType, session_id: str, data: Dict[str, Any],
                  tool_name: Optional[str] = None, tool_input: Optional[Dict] = None,
                  error: Optional[str] = None, trace_id: Optional[str] = None) -> bool:
    """
    Capture an event as fast as possible.
    
    Target: < 10ms
    Method: Append-only file write with short lock, overflow sidecar on contention.
    """
    try:
        if not isinstance(event_type, EventType):
            raise ValueError("invalid_event_type")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("invalid_session_id")
        if not isinstance(data, dict):
            raise ValueError("invalid_data")

        QUEUE_DIR.mkdir(parents=True, exist_ok=True)

        event_ts = time.time()
        data_out = dict(data)
        trace_hint = ""
        if trace_id:
            data_out["trace_id"] = trace_id
        if not data_out.get("trace_id"):
            payload = data_out.get("payload")
            if isinstance(payload, dict):
                trace_hint = str(payload.get("text") or payload.get("intent") or payload.get("command") or "")[:80]
            raw = f"{session_id}|{event_type.value}|{event_ts}|{tool_name or ''}|{trace_hint}"
            data_out["trace_id"] = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

        event = SparkEvent(
            event_type=event_type,
            session_id=session_id,
            timestamp=event_ts,
            data=data_out,
            tool_name=tool_name,
            tool_input=tool_input,
            error=error
        )

        line = json.dumps(event.to_dict()) + "\n"
        lock = _queue_lock(timeout_s=0.05)
        with lock:
            if lock.acquired:
                with open(EVENTS_FILE, "a") as f:
                    f.write(line)
                _invalidate_count_cache()
            else:
                # Lock busy (consumer/rotator active) -- write to overflow
                # sidecar so no events are lost. Merged on next consume.
                with open(OVERFLOW_FILE, "a") as f:
                    f.write(line)

        # Best-effort rotation so the queue doesn't grow unbounded.
        rotate_if_needed()

        return True

    except Exception as e:
        # Never fail - just drop the event silently
        log_debug("queue", "quick_capture failed", e)
        return False


def read_events(limit: int = 100, offset: int = 0) -> List[SparkEvent]:
    """Read events from the queue."""
    events = []
    
    if not EVENTS_FILE.exists():
        return events
    
    try:
        idx = 0
        for line in (_iter_active_lines_iter(EVENTS_FILE) or []):
            if idx < offset:
                idx += 1
                continue
            if len(events) >= limit:
                break
            idx += 1
            try:
                data = json.loads(line.strip())
                events.append(SparkEvent.from_dict(data))
            except Exception:
                continue

    except Exception as e:
        log_debug("queue", "read_events failed", e)
        pass
    
    return events


def read_recent_events(count: int = 50) -> List[SparkEvent]:
    """Read the most recent events."""
    if not EVENTS_FILE.exists():
        return []
    
    try:
        lines = _tail_lines(EVENTS_FILE, count, start_offset_bytes=_queue_head_bytes())
        events = []
        for line in lines:
            try:
                data = json.loads(line.strip())
                events.append(SparkEvent.from_dict(data))
            except Exception:
                continue
        return events
        
    except Exception as e:
        log_debug("queue", "read_recent_events failed", e)
        return []


def read_recent_events_raw(count: int = 50) -> List[SparkEvent]:
    """Read the most recent events, ignoring queue head_bytes.

    This is a fallback for downstream consumers (e.g., opportunity scanner)
    when the pipeline advanced head_bytes but didn't surface processed_events.
    """
    if not EVENTS_FILE.exists():
        return []
    try:
        lines = _tail_lines(EVENTS_FILE, count, start_offset_bytes=0)
        events: List[SparkEvent] = []
        for line in lines:
            try:
                data = json.loads(line.strip())
                events.append(SparkEvent.from_dict(data))
            except Exception:
                continue
        return events
    except Exception as e:
        log_debug("queue", "read_recent_events_raw failed", e)
        return []


def count_events(use_cache: bool = True) -> int:
    """Count total events in queue."""
    if not EVENTS_FILE.exists():
        return 0
    now = time.time()
    global _last_count_value, _last_count_value_ts
    if use_cache and _last_count_value is not None and (now - _last_count_value_ts) < _COUNT_CACHE_TTL_S:
        return _last_count_value
    
    try:
        count = 0
        head = _queue_head_bytes()
        with open(EVENTS_FILE, "rb") as f:
            f.seek(head)
            for _ in f:
                count += 1
        _last_count_value = count
        _last_count_value_ts = now
        return count
    except Exception as e:
        log_debug("queue", "count_events failed", e)
        return 0


def clear_events() -> int:
    """Clear all events from queue. Returns count cleared."""
    count = count_events()
    
    if EVENTS_FILE.exists():
        with _queue_lock():
            if EVENTS_FILE.exists():
                EVENTS_FILE.unlink()
            if OVERFLOW_FILE.exists():
                OVERFLOW_FILE.unlink()
            _set_queue_head_bytes(0)
            _invalidate_count_cache()
    
    return count


def _estimate_event_count(size_bytes: int) -> int:
    """Estimate event count from file size without reading the file.

    Average JSONL event line is ~500 bytes.  This is used in the hot
    path (quick_capture) to avoid O(n) line counting on every write.
    """
    if size_bytes <= 0:
        return 0
    return max(1, size_bytes // 500)


def rotate_if_needed() -> bool:
    """Rotate queue if it's too large."""
    global _last_count_check

    size_bytes = _active_file_bytes()

    over_size = MAX_QUEUE_BYTES > 0 and size_bytes > MAX_QUEUE_BYTES

    # Use file-size estimation for the hot path instead of O(n) line count.
    # Only do the expensive count_events() call every 60s or when size-based
    # estimate already shows we're over.
    now = time.time()
    count = 0
    over_count = False
    if MAX_EVENTS > 0:
        estimated = _estimate_event_count(size_bytes)
        if over_size or estimated > MAX_EVENTS:
            # Likely over limit -- do the real count
            count = count_events(use_cache=False)
            _last_count_check = now
            over_count = count > MAX_EVENTS
        elif now - _last_count_check >= _COUNT_CHECK_INTERVAL:
            count = count_events(use_cache=False)
            _last_count_check = now
            over_count = count > MAX_EVENTS

    if not over_size and not over_count:
        return False
    
    try:
        with _queue_lock():
            _merge_overflow_locked()
            active_head = _queue_head_bytes()
            # Keep only the last half to evict oldest events.
            if MAX_EVENTS > 0:
                keep_count = max(1, MAX_EVENTS // 2)
            else:
                keep_count = max(1, count // 2) if count else 5000
            lines = _tail_lines(EVENTS_FILE, keep_count, start_offset_bytes=active_head)
            tmp = EVENTS_FILE.with_suffix(".jsonl.rotate.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                for line in lines:
                    if line:
                        f.write(line.rstrip("\r\n") + "\n")
            tmp.replace(EVENTS_FILE)
            _set_queue_head_bytes(0)
            _invalidate_count_cache()
            print(f"[SPARK] Rotated queue: {count} -> {keep_count} events")
            return True
        
    except Exception as e:
        log_debug("queue", "rotate_if_needed failed", e)
        return False


def consume_processed(up_to_offset: int) -> int:
    """Remove events that have been processed (up to offset line number).

    This is the key mechanism that keeps the queue from growing forever.
    After the bridge worker processes events 0..N, it calls
    ``consume_processed(N)`` to strip those lines from the file.

    Uses atomic temp-file + rename to avoid race conditions with
    concurrent writers (the observe hook appends events while we consume).

    Returns the number of events removed.
    """
    if up_to_offset <= 0 or not EVENTS_FILE.exists():
        return 0

    try:
        with _queue_lock():
            _merge_overflow_locked()
            head = _queue_head_bytes()
            removed = 0
            advance_bytes = 0
            with open(EVENTS_FILE, "rb") as f:
                f.seek(head)
                while removed < up_to_offset:
                    line = f.readline()
                    if not line:
                        break
                    advance_bytes += len(line)
                    removed += 1
            if removed == 0:
                return 0
            new_head = head + advance_bytes
            _set_queue_head_bytes(new_head)

            # Compact periodically to reclaim space while keeping consume O(1)
            # in the steady state.
            try:
                size = EVENTS_FILE.stat().st_size
            except Exception:
                size = 0
            active = max(0, size - new_head)
            should_compact = (
                new_head >= QUEUE_COMPACT_HEAD_BYTES
                and (new_head >= (size // 2) or active <= QUEUE_COMPACT_HEAD_BYTES)
            )
            if should_compact:
                tmp = EVENTS_FILE.with_suffix(".jsonl.tmp")
                with open(EVENTS_FILE, "rb") as src, open(tmp, "wb") as dst:
                    src.seek(new_head)
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
                tmp.replace(EVENTS_FILE)
                _set_queue_head_bytes(0)

            _invalidate_count_cache()
            log_debug("queue", f"consumed {removed} events", None)
            return removed
    except Exception as e:
        log_debug("queue", "consume_processed failed", e)
        return 0


# ============= Event Priority Classification =============

class EventPriority:
    """Priority tiers for event processing.

    HIGH  - Events most likely to yield valuable learnings (user prompts,
            failures, session boundaries).  Always processed first.
    MEDIUM - Events that occasionally yield insights (Edit, Write, Bash
             with interesting commands).
    LOW   - Routine events (Read, Glob, Grep success) that rarely produce
            novel learnings.  Processed only when backlog is small.
    """
    HIGH = 3
    MEDIUM = 2
    LOW = 1


def classify_event_priority(event: "SparkEvent") -> int:
    """Classify an event's processing priority.

    Returns an ``EventPriority`` int (higher = more important).
    """
    et = event.event_type

    # High-value: user prompts, failures, session boundaries, errors
    if et in (EventType.USER_PROMPT, EventType.POST_TOOL_FAILURE,
              EventType.SESSION_START, EventType.SESSION_END,
              EventType.STOP, EventType.ERROR):
        return EventPriority.HIGH

    # Learnings are always interesting
    if et == EventType.LEARNING:
        return EventPriority.HIGH

    # Medium: post_tool for mutation tools (Edit, Write, Bash)
    if et == EventType.POST_TOOL:
        tool = (event.tool_name or "").strip()
        if tool in ("Edit", "Write", "Bash", "NotebookEdit"):
            return EventPriority.MEDIUM

    # Everything else (Read, Glob, Grep successes, pre_tool) is low priority
    return EventPriority.LOW


def get_queue_stats() -> Dict:
    """Get queue statistics."""
    count = count_events()
    size_bytes = _active_file_bytes()
    file_bytes = 0
    if EVENTS_FILE.exists():
        try:
            file_bytes = EVENTS_FILE.stat().st_size
        except Exception:
            file_bytes = 0

    return {
        "event_count": count,
        "size_bytes": size_bytes,
        "file_bytes": file_bytes,
        "size_mb": round(size_bytes / (1024 * 1024), 2),
        "queue_file": str(EVENTS_FILE),
        "max_events": MAX_EVENTS,
        "tail_chunk_bytes": TAIL_CHUNK_BYTES,
        "max_bytes": MAX_QUEUE_BYTES,
        "needs_rotation": (MAX_EVENTS > 0 and count > MAX_EVENTS) or (MAX_QUEUE_BYTES > 0 and size_bytes > MAX_QUEUE_BYTES)
    }


def _tail_lines(path: Path, count: int, start_offset_bytes: int = 0) -> List[str]:
    """Read the last N lines of a file without loading the whole file.

    Args:
        path: File path.
        count: Number of lines to return from the tail.
        start_offset_bytes: Optional byte offset that defines the logical
            start of the file (used by queue head compaction state).
    """
    if count <= 0:
        return []
    if not path.exists():
        return []
    if start_offset_bytes < 0:
        start_offset_bytes = 0

    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            if start_offset_bytes > pos:
                start_offset_bytes = pos
            buffer = b""
            lines: List[bytes] = []

            while pos > start_offset_bytes and len(lines) <= count:
                read_size = min(TAIL_CHUNK_BYTES, pos - start_offset_bytes)
                pos -= read_size
                f.seek(pos)
                data = f.read(read_size)
                buffer = data + buffer

                if b"\n" in buffer:
                    parts = buffer.split(b"\n")
                    buffer = parts[0]
                    lines = parts[1:] + lines

            if buffer:
                lines = [buffer] + lines

            # Drop possible trailing empty line
            # Normalize Windows CRLF to avoid double-CR issues on rewrite.
            out = [
                ln.decode("utf-8", errors="replace").rstrip("\r")
                for ln in lines
                if ln != b""
            ]
            return out[-count:]
    except Exception as e:
        log_debug("queue", "_tail_lines failed", e)
        return []


class _queue_lock:
    """Best-effort lock using an exclusive lock file."""

    def __init__(self, timeout_s: float = 0.5):
        self.timeout_s = timeout_s
        self.fd = None
        self.acquired = False

    def __enter__(self):
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        start = time.time()
        while True:
            try:
                self.fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                self.acquired = True
                return self
            except FileExistsError:
                if time.time() - start >= self.timeout_s:
                    return self  # self.acquired stays False
                time.sleep(0.01)
            except Exception as e:
                log_debug("queue", "lock acquire failed", e)
                return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            # Only delete the lock file if WE acquired it.
            if self.acquired and LOCK_FILE.exists():
                LOCK_FILE.unlink()
        except Exception as e:
            log_debug("queue", "lock release failed", e)
        self.acquired = False
