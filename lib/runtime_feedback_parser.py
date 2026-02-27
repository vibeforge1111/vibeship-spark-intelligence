"""Parse advisory feedback-request logs into atomic recommendation rows."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

REQUESTS_FILE = Path.home() / ".spark" / "advice_feedback_requests.jsonl"

_BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")
_CHECKBOX_RE = re.compile(r"^\s*-\s*\[[ xX]\]\s+(.+?)\s*$")
_WS_RE = re.compile(r"\s+")


def _hash_id(*parts: str) -> str:
    payload = "|".join(parts)
    return hashlib.sha1(payload.encode("utf-8", errors="replace")).hexdigest()[:12]


def normalize_recommendation(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"^\[SPARK(?: ADVISORY)?\]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\(spark:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\)\s*$", "", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def split_atomic_recommendations(text: str) -> List[str]:
    out: List[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _CHECKBOX_RE.match(line) or _BULLET_RE.match(line)
        if m:
            item = normalize_recommendation(m.group(1))
            if item:
                out.append(item)
    if not out:
        compact = normalize_recommendation(str(text or ""))
        if compact:
            out.append(compact)
    return out


def _read_jsonl(path: Path, limit: Optional[int] = None) -> List[tuple[int, Dict[str, Any]]]:
    if not path.exists():
        return []
    all_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lines = all_lines
    if limit and limit > 0:
        lines = all_lines[-int(limit) :]
    rows: List[tuple[int, Dict[str, Any]]] = []
    start_line = max(1, len(all_lines) - len(lines) + 1)
    for idx, line in enumerate(lines):
        try:
            row = json.loads(line)
        except Exception:
            continue
        rows.append((start_line + idx, row))
    return rows


def parse_feedback_requests(path: Path = REQUESTS_FILE, limit: Optional[int] = 2000) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for line_no, row in _read_jsonl(path, limit=limit):
        created_at = float(row.get("created_at") or 0.0)
        advice_texts = list(row.get("advice_texts") or [])
        advice_ids = list(row.get("advice_ids") or [])
        session_id = str(row.get("session_id") or "")
        tool = str(row.get("tool") or "")
        trace_id = str(row.get("trace_id") or "")
        packet_id = str(row.get("packet_id") or "")
        route = str(row.get("route") or "")

        for i, raw_text in enumerate(advice_texts):
            recommendation = normalize_recommendation(str(raw_text or ""))
            if not recommendation:
                continue
            advice_id = str(advice_ids[i] if i < len(advice_ids) else "") or _hash_id(recommendation)
            instance_id = _hash_id(advice_id, str(created_at), session_id, trace_id, str(i))
            items.append(
                {
                    "advisory_instance_id": instance_id,
                    "advisory_id": advice_id,
                    "recommendation": recommendation,
                    "created_at": created_at,
                    "session_id": session_id,
                    "tool": tool,
                    "trace_id": trace_id,
                    "packet_id": packet_id,
                    "route": route,
                    "source_kind": "feedback_request",
                    "source_file": str(path),
                    "evidence_refs": [f"{path}:{line_no}"],
                }
            )
    return items


def load_advisories(*, request_file: Path = REQUESTS_FILE, limit_requests: int = 2000) -> List[Dict[str, Any]]:
    advisories = parse_feedback_requests(request_file, limit=limit_requests)
    advisories.sort(key=lambda x: float(x.get("created_at") or 0.0))
    return advisories

