"""Parse advisories into atomic recommendations for auto-scoring."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .openclaw_paths import discover_openclaw_advisory_files

REQUESTS_FILE = Path.home() / ".spark" / "advice_feedback_requests.jsonl"
SPARK_ADVISORY_FILE = Path.home() / ".openclaw" / "workspace" / "SPARK_ADVISORY.md"
SPARK_ADVISORY_FALLBACK_FILE = Path.home() / ".spark" / "llm_advisory.md"
ENGINE_FILE = Path.home() / ".spark" / "advisory_engine.jsonl"
LEGACY_PATHS_ENABLED = (
    str(os.getenv("SPARK_ADVISORY_PARSER_INCLUDE_LEGACY", "0")).strip().lower()
    in {"1", "true", "yes", "on"}
)

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
    # Fallback: include non-empty prose line when no bullets exist.
    if not out:
        compact = normalize_recommendation(str(text or ""))
        if compact:
            out.append(compact)
    return out


def _read_jsonl(path: Path, limit: Optional[int] = None) -> List[tuple[int, Dict[str, Any]]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if limit and limit > 0:
        lines = lines[-int(limit) :]
    rows: List[tuple[int, Dict[str, Any]]] = []
    start_line = max(1, len(path.read_text(encoding="utf-8", errors="replace").splitlines()) - len(lines) + 1)
    for idx, line in enumerate(lines):
        try:
            row = json.loads(line)
        except Exception:
            continue
        rows.append((start_line + idx, row))
    return rows


def parse_feedback_requests(
    path: Path = REQUESTS_FILE,
    limit: Optional[int] = 2000,
) -> List[Dict[str, Any]]:
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


def parse_advisory_markdown(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    created_at = float(path.stat().st_mtime)
    recs = split_atomic_recommendations(text)
    out: List[Dict[str, Any]] = []
    for idx, recommendation in enumerate(recs):
        advisory_id = _hash_id(recommendation, str(idx), path.name)
        out.append(
            {
                "advisory_instance_id": _hash_id(advisory_id, str(created_at), str(idx)),
                "advisory_id": advisory_id,
                "recommendation": recommendation,
                "created_at": created_at,
                "session_id": "",
                "tool": "",
                "trace_id": "",
                "packet_id": "",
                "route": "",
                "source_kind": "advisory_markdown",
                "source_file": str(path),
                "evidence_refs": [str(path)],
            }
        )
    return out


def parse_engine_previews(
    path: Path = ENGINE_FILE,
    limit: Optional[int] = 800,
) -> List[Dict[str, Any]]:
    """Fallback parser when feedback request logs are missing."""
    out: List[Dict[str, Any]] = []
    for line_no, row in _read_jsonl(path, limit=limit):
        if str(row.get("event") or "") != "emitted":
            continue
        preview = normalize_recommendation(str(row.get("emitted_text_preview") or ""))
        if not preview:
            continue
        created_at = float(row.get("ts") or 0.0)
        session_id = str(row.get("session_id") or "")
        tool = str(row.get("tool") or "")
        trace_id = str(row.get("trace_id") or "")
        packet_id = str(row.get("packet_id") or "")
        advisory_id = packet_id or _hash_id(preview, str(created_at), session_id)
        out.append(
            {
                "advisory_instance_id": _hash_id(advisory_id, str(created_at), str(line_no)),
                "advisory_id": advisory_id,
                "recommendation": preview,
                "created_at": created_at,
                "session_id": session_id,
                "tool": tool,
                "trace_id": trace_id,
                "packet_id": packet_id,
                "route": str(row.get("route") or ""),
                "source_kind": "engine_preview",
                "source_file": str(path),
                "evidence_refs": [f"{path}:{line_no}"],
            }
        )
    return out


def load_advisories(
    *,
    request_file: Path = REQUESTS_FILE,
    advisory_paths: Optional[Iterable[Path]] = None,
    engine_file: Path = ENGINE_FILE,
    limit_requests: int = 2000,
    include_engine_fallback: bool = True,
) -> List[Dict[str, Any]]:
    advisories = parse_feedback_requests(request_file, limit=limit_requests)
    if LEGACY_PATHS_ENABLED:
        if advisory_paths is None:
            discovered = discover_openclaw_advisory_files()
            advisory_paths = discovered or [SPARK_ADVISORY_FILE]
            advisory_paths = [*advisory_paths, SPARK_ADVISORY_FALLBACK_FILE]
        for p in advisory_paths:
            advisories.extend(parse_advisory_markdown(Path(p)))
        if include_engine_fallback and not advisories:
            advisories.extend(parse_engine_previews(engine_file))
    advisories.sort(key=lambda x: float(x.get("created_at") or 0.0))
    return advisories
