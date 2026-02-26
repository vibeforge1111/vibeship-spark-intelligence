"""Safe integration bridge for spark-learning-systems.

This module provides two controlled ingress paths:
1) Store external insights through validate_and_store_insight().
2) Queue tuneable change proposals for review/approval.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .file_lock import file_lock_for
except Exception:  # pragma: no cover - fallback for older branches
    from contextlib import contextmanager

    @contextmanager
    def file_lock_for(_path: Path, **_kwargs):
        yield

BRIDGE_DIR = Path.home() / ".spark" / "learning_systems"
INSIGHT_AUDIT_FILE = BRIDGE_DIR / "insight_ingest_audit.jsonl"
TUNEABLE_PROPOSALS_FILE = BRIDGE_DIR / "tuneable_proposals.jsonl"

MAX_AUDIT_LINES = 3000
MAX_PROPOSAL_LINES = 3000


def _bridge_enabled() -> bool:
    try:
        from .config_authority import resolve_section, env_bool
        cfg = resolve_section(
            "feature_gates",
            env_overrides={"learning_bridge": env_bool("SPARK_LEARNING_BRIDGE_ENABLED")},
        ).data
        return bool(cfg.get("learning_bridge", True))
    except Exception:
        raw = str(os.getenv("SPARK_LEARNING_BRIDGE_ENABLED", "1")).strip().lower()
        return raw not in {"0", "false", "no", "off"}


def _append_jsonl_capped(path: Path, row: Dict[str, Any], *, max_lines: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with file_lock_for(path):
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
        try:
            if not path.exists():
                return
            if path.stat().st_size // 260 <= max_lines:
                return
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) <= max_lines:
                return
            keep = "\n".join(lines[-max_lines:]) + "\n"
            tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
            tmp.write_text(keep, encoding="utf-8")
            os.replace(str(tmp), str(path))
        except Exception:
            return


def _parse_category(category: Any):
    from .cognitive_learner import CognitiveCategory

    if isinstance(category, CognitiveCategory):
        return category
    text = str(category or "").strip().lower()
    if not text:
        return None
    try:
        return CognitiveCategory(text)
    except Exception:
        return None


def store_external_insight(
    *,
    text: Any,
    category: Any,
    source: str,
    context: str = "",
    confidence: float = 0.7,
) -> Dict[str, Any]:
    """Store an external learning-system insight through Spark's safe write path."""
    ts = time.time()
    text_s = str(text or "")
    cat = _parse_category(category)
    result: Dict[str, Any]

    if not _bridge_enabled():
        result = {"stored": False, "reason": "bridge_disabled"}
    elif not text_s.strip():
        result = {"stored": False, "reason": "empty_text"}
    elif cat is None:
        result = {"stored": False, "reason": "invalid_category"}
    else:
        from .validate_and_store import validate_and_store_insight

        try:
            out = validate_and_store_insight(
                text=text_s,
                category=cat,
                context=context,
                confidence=float(confidence),
                source=str(source or "learning_system"),
                return_details=True,
            )
        except TypeError as exc:
            # Compatibility with older validate_and_store versions that only return bool.
            if "return_details" not in str(exc):
                raise
            out = validate_and_store_insight(
                text=text_s,
                category=cat,
                context=context,
                confidence=float(confidence),
                source=str(source or "learning_system"),
            )
        if isinstance(out, dict):
            result = out
        else:
            result = {
                "stored": bool(out),
                "insight_key": "",
                "stored_text": text_s,
                "reason": "" if bool(out) else "rejected_or_filtered",
            }

    audit_row = {
        "ts": ts,
        "source": str(source or ""),
        "category": str(getattr(cat, "value", category) or ""),
        "stored": bool(result.get("stored")),
        "reason": str(result.get("reason") or ""),
        "insight_key": str(result.get("insight_key") or ""),
        "text_len": len(text_s),
        "text_hash": hashlib.sha1(text_s.encode("utf-8", errors="ignore")).hexdigest()[:16],
    }
    _append_jsonl_capped(INSIGHT_AUDIT_FILE, audit_row, max_lines=MAX_AUDIT_LINES)
    return result


def propose_tuneable_change(
    *,
    system_id: str,
    section: str,
    key: str,
    new_value: Any,
    reasoning: str,
    confidence: float = 0.5,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Queue a tuneable proposal for manual/automated review."""
    sid = str(system_id or "").strip()
    sec = str(section or "").strip()
    k = str(key or "").strip()
    why = str(reasoning or "").strip()
    if not sid or not sec or not k or not why:
        return {"queued": False, "reason": "missing_required_fields"}
    if not _bridge_enabled():
        return {"queued": False, "reason": "bridge_disabled"}

    ts = time.time()
    proposal_id = hashlib.sha1(
        f"{sid}|{sec}|{k}|{json.dumps(new_value, sort_keys=True, default=str)}|{ts}".encode("utf-8")
    ).hexdigest()[:16]
    row = {
        "proposal_id": proposal_id,
        "ts": ts,
        "status": "pending",
        "system_id": sid,
        "section": sec,
        "key": k,
        "new_value": new_value,
        "reasoning": why[:1000],
        "confidence": max(0.0, min(1.0, float(confidence))),
        "metadata": metadata or {},
    }
    _append_jsonl_capped(TUNEABLE_PROPOSALS_FILE, row, max_lines=MAX_PROPOSAL_LINES)
    return {"queued": True, "proposal_id": proposal_id}


def list_tuneable_proposals(limit: int = 50, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List recent tuneable proposals (tail read)."""
    path = TUNEABLE_PROPOSALS_FILE
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-max(1, int(limit or 1)) :]
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    wanted = str(status or "").strip().lower()
    for raw in reversed(lines):
        try:
            row = json.loads(raw)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        if wanted and str(row.get("status") or "").strip().lower() != wanted:
            continue
        out.append(row)
    return out
