"""Shared JSONL helpers for bounded append and tail reads."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List


def tail_jsonl_objects(path: Path, count: int) -> List[Dict[str, Any]]:
    """Return up to ``count`` parsed JSON-object rows from the end of a JSONL file."""
    if count <= 0 or not path.exists():
        return []
    chunk_size = 64 * 1024
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            buffer = b""
            lines: List[bytes] = []
            while pos > 0 and len(lines) <= count:
                read_size = min(chunk_size, pos)
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
        out: List[Dict[str, Any]] = []
        for ln in lines[-count:]:
            ln = ln.strip()
            if not ln:
                continue
            try:
                row = json.loads(ln.decode("utf-8", errors="ignore"))
            except Exception:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out
    except Exception:
        return []


def append_jsonl_capped(
    path: Path,
    entry: Dict[str, Any],
    max_lines: int,
    *,
    ensure_ascii: bool = True,
) -> None:
    """Append one JSONL row and keep only the most recent ``max_lines`` rows."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=bool(ensure_ascii)) + "\n")
        if max_lines <= 0:
            return
        probe = tail_jsonl_objects(path, max_lines + 1)
        if len(probe) <= max_lines:
            return
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=bool(ensure_ascii)) for r in probe[-max_lines:]) + "\n",
            encoding="utf-8",
        )
    except Exception:
        return
