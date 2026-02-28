"""Shared JSONL helpers for bounded append and tail reads."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any, Dict, List


def tail_jsonl_objects(path: Path, count: int) -> List[Dict[str, Any]]:
    """Return up to ``count`` parsed JSON-object rows from the end of a JSONL file."""
    if count <= 0 or not path.exists():
        return []
    try:
        rows: deque[str] = deque(maxlen=int(count))
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(line)
        out: List[Dict[str, Any]] = []
        for ln in rows:
            try:
                row = json.loads(ln)
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


def cap_jsonl_file(
    path: Path,
    max_lines: int,
    *,
    ensure_trailing_newline: bool = True,
) -> int:
    """Rewrite ``path`` to keep only the last ``max_lines`` raw lines.

    Returns the number of dropped lines. Returns 0 on no-op or failure.
    """
    if max_lines <= 0 or not path.exists():
        return 0
    try:
        rows: deque[str] = deque(maxlen=int(max_lines))
        total = 0
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line.strip():
                    continue
                rows.append(line)
                total += 1
        if total <= max_lines:
            return 0
        dropped = int(total - max_lines)
        body = "\n".join(rows)
        if ensure_trailing_newline and body:
            body += "\n"
        path.write_text(body, encoding="utf-8")
        return dropped
    except Exception:
        return 0
