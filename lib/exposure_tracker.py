"""Track which insights were surfaced to the user."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .primitive_filter import is_primitive_text


EXPOSURES_FILE = Path.home() / ".spark" / "exposures.jsonl"
LAST_EXPOSURE_FILE = Path.home() / ".spark" / "last_exposure.json"

# Chunk size for tail reads (64KB)
_TAIL_CHUNK_BYTES = 65536

# Write-volume policies for high-frequency exposure sources.
_SOURCE_WRITE_POLICIES = {
    "sync_context": {"max_items": 6, "dedupe_window_s": 600.0},
    "sync_context:project": {"max_items": 4, "dedupe_window_s": 1800.0},
    "chip_merge": {"max_items": 8, "dedupe_window_s": 900.0},
}
_POLICY_RECENT_SCAN_LIMIT = 300

# Secret-redaction patterns for ingestion boundaries.
_REDACT_PATTERNS = [
    # Authorization/Bearer headers
    (re.compile(r"(?i)\b(authorization\s*[:=]\s*bearer\s+)([A-Za-z0-9._\-]+)"), r"\1[REDACTED]"),
    # Generic API key assignments (api_key=..., token: ...)
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*([A-Za-z0-9_\-]{8,})"), r"\1=[REDACTED]"),
    # OpenAI-style keys
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"), "[REDACTED_SK]"),
    # Telegram bot token-ish pattern
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_\-]{20,}\b"), "[REDACTED_TELEGRAM_TOKEN]"),
]


def _sanitize_text(value: Optional[str], max_len: int = 2000) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    for pattern, repl in _REDACT_PATTERNS:
        try:
            text = pattern.sub(repl, text)
        except Exception:
            continue
    text = text.strip()
    if max_len > 0:
        text = text[:max_len]
    return text or None


def _normalize_signature(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _exposure_signature(row: Dict[str, Any]) -> str:
    """Stable signature for dedupe across repeated emissions."""
    key = row.get("insight_key")
    if isinstance(key, str) and key.strip():
        return f"k:{_normalize_signature(key)}"
    text = row.get("text")
    if isinstance(text, str) and text.strip():
        category = row.get("category") or ""
        return f"t:{_normalize_signature(str(category))}|{_normalize_signature(text)[:240]}"
    return ""


def _recent_signatures_for_source(source: str, now_ts: float, max_age_s: float) -> set[str]:
    if not source or max_age_s <= 0:
        return set()
    recent = read_exposures_within(max_age_s=max_age_s, now=now_ts, limit=_POLICY_RECENT_SCAN_LIMIT)
    signatures: set[str] = set()
    for row in recent:
        if (row.get("source") or "") != source:
            continue
        sig = _exposure_signature(row)
        if sig:
            signatures.add(sig)
    return signatures


def _tail_lines(path: Path, count: int) -> List[str]:
    """Read the last N lines of a file without loading the whole file into memory."""
    if count <= 0 or not path.exists():
        return []

    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            buffer = b""
            lines: List[bytes] = []

            while pos > 0 and len(lines) <= count:
                read_size = min(_TAIL_CHUNK_BYTES, pos)
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

            # Normalize and decode
            return [
                ln.decode("utf-8", errors="replace").rstrip("\r")
                for ln in lines[-count:]
                if ln
            ]
    except Exception:
        return []


def _maybe_rotate_exposures() -> None:
    """Rotate exposures.jsonl when it exceeds 5MB."""
    if not EXPOSURES_FILE.exists():
        return
    try:
        if EXPOSURES_FILE.stat().st_size > 5 * 1024 * 1024:  # 5MB
            rotated = EXPOSURES_FILE.with_suffix('.1.jsonl')
            if rotated.exists():
                rotated.unlink()
            EXPOSURES_FILE.rename(rotated)
    except Exception:
        pass


def record_exposures(
    source: str,
    items: Iterable[Dict],
    *,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None
) -> int:
    """Append exposure entries. Returns count written."""
    _maybe_rotate_exposures()
    rows: List[Dict] = []
    now = time.time()
    for item in items:
        if not item:
            continue
        text = _sanitize_text(item.get("text"))
        if isinstance(text, str) and is_primitive_text(text):
            continue
        # Ingestion boundary allowlist: persist only safe, minimal fields.
        rows.append({
            "ts": now,
            "source": str(source or "")[:80],
            "insight_key": _sanitize_text(item.get("insight_key"), max_len=200),
            "category": _sanitize_text(item.get("category"), max_len=80),
            "text": text,
            "session_id": (str(session_id)[:160] if session_id else None),
            "trace_id": (str(trace_id)[:160] if trace_id else None),
        })

    if not rows:
        return 0

    policy = _SOURCE_WRITE_POLICIES.get(source, {})
    if policy:
        max_items = int(policy.get("max_items") or 0)
        dedupe_window_s = float(policy.get("dedupe_window_s") or 0.0)
        recent_sigs = _recent_signatures_for_source(source, now, dedupe_window_s)
        seen_batch: set[str] = set()
        filtered: List[Dict] = []
        for row in rows:
            sig = _exposure_signature(row)
            if sig:
                if sig in seen_batch or sig in recent_sigs:
                    continue
                seen_batch.add(sig)
            filtered.append(row)
        if max_items > 0 and len(filtered) > max_items:
            filtered = filtered[:max_items]
        rows = filtered
        if not rows:
            return 0

    EXPOSURES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with EXPOSURES_FILE.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    try:
        # Persist the most recent exposure for quick linking.
        LAST_EXPOSURE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAST_EXPOSURE_FILE.write_text(json.dumps(rows[-1], ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return len(rows)


def read_recent_exposures(limit: int = 200, max_age_s: float = 6 * 3600) -> List[Dict]:
    """Read recent exposures using streaming tail read (memory efficient)."""
    if not EXPOSURES_FILE.exists():
        return []

    # Use tail read to avoid loading entire file into memory
    lines = _tail_lines(EXPOSURES_FILE, limit)
    if not lines:
        return []

    now = time.time()
    out: List[Dict] = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except Exception:
            continue
        ts = float(row.get("ts") or 0.0)
        if max_age_s and ts and (now - ts) > max_age_s:
            continue
        out.append(row)
    return out


def read_exposures_within(*, max_age_s: float, now: Optional[float] = None, limit: int = 200) -> List[Dict]:
    """Read exposures within max_age_s relative to now (memory efficient)."""
    if not EXPOSURES_FILE.exists():
        return []

    # Use tail read to avoid loading entire file into memory
    lines = _tail_lines(EXPOSURES_FILE, limit)
    if not lines:
        return []

    now_ts = float(now or time.time())
    out: List[Dict] = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except Exception:
            continue
        ts = float(row.get("ts") or 0.0)
        if max_age_s and ts and (now_ts - ts) > max_age_s:
            continue
        out.append(row)
    return out


def read_last_exposure() -> Optional[Dict]:
    """Return the most recent exposure record if available."""
    if not LAST_EXPOSURE_FILE.exists():
        return None
    try:
        return json.loads(LAST_EXPOSURE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def infer_latest_session_id() -> Optional[str]:
    """Best-effort latest session id from last exposure or recent queue events."""
    last = read_last_exposure()
    if last:
        sid = last.get("session_id")
        if isinstance(sid, str) and sid.strip():
            return sid
    try:
        from lib.queue import read_recent_events
        events = read_recent_events(1)
        if events:
            return events[-1].session_id
    except Exception:
        return None
    return None


def infer_latest_trace_id(session_id: Optional[str] = None, limit: int = 50) -> Optional[str]:
    """Best-effort trace_id from recent queue events (optionally scoped to session)."""
    try:
        from lib.queue import read_recent_events
        events = read_recent_events(limit)
        for ev in reversed(events):
            if session_id and ev.session_id != session_id:
                continue
            trace_id = (ev.data or {}).get("trace_id")
            if trace_id:
                return str(trace_id)
    except Exception:
        return None
    return None
