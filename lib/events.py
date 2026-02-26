#!/usr/bin/env python3
"""Spark event schema (v1)

Goal: make Spark ingestion platform-agnostic.

Adapters (Clawdbot, Claude Code, webhooks, etc.) emit SparkEventV1 objects.
Spark core stores them, then distills into insights/surprises/voice.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class SparkEventKind(str, Enum):
    MESSAGE = "message"
    TOOL = "tool"
    COMMAND = "command"
    SYSTEM = "system"


@dataclass
class SparkEventV1:
    """Normalized event payload."""

    v: int
    source: str                 # e.g., "clawdbot", "claude_code", "webhook"
    kind: SparkEventKind        # message/tool/command/system
    ts: float                   # unix seconds
    session_id: str
    payload: Dict[str, Any]
    trace_id: Optional[str] = None  # de-dupe across adapters

    def to_dict(self) -> Dict[str, Any]:
        return {
            "v": self.v,
            "source": self.source,
            "kind": self.kind.value,
            "ts": self.ts,
            "session_id": self.session_id,
            "payload": self.payload,
            "trace_id": self.trace_id,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SparkEventV1":
        if int(d.get("v", 0)) != 1:
            raise ValueError("Unsupported event version")
        return SparkEventV1(
            v=1,
            source=str(d.get("source") or "unknown"),
            kind=SparkEventKind(str(d.get("kind") or "system")),
            ts=float(d.get("ts") or 0),
            session_id=str(d.get("session_id") or "unknown"),
            payload=dict(d.get("payload") or {}),
            trace_id=(str(d["trace_id"]) if d.get("trace_id") else None),
        )


def validate_event_dict(d: Dict[str, Any], *, strict: bool = True) -> Tuple[bool, str]:
    """Validate a raw SparkEventV1 dict before ingestion."""
    if not isinstance(d, dict):
        return False, "not_object"
    required = ("v", "source", "kind", "ts", "session_id", "payload")
    for key in required:
        if key not in d:
            return False, f"missing_{key}"
    try:
        if int(d.get("v", 0)) != 1:
            return False, "unsupported_version"
    except Exception:
        return False, "invalid_version"
    source = d.get("source")
    if not isinstance(source, str) or not source.strip():
        return False, "invalid_source"
    if len(source) > 256:
        return False, "source_too_long"
    kind = str(d.get("kind") or "")
    allowed = {k.value for k in SparkEventKind}
    if kind not in allowed:
        return False, "invalid_kind"
    session_id = d.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return False, "invalid_session_id"
    if len(session_id) > 256:
        return False, "session_id_too_long"
    try:
        ts = float(d.get("ts") or 0)
        if ts <= 0:
            return False, "invalid_ts"
    except Exception:
        return False, "invalid_ts"
    payload = d.get("payload")
    if payload is None and strict:
        return False, "missing_payload"
    if payload is not None and not isinstance(payload, dict):
        return False, "invalid_payload"
    if payload is not None:
        try:
            import json as _json
            if len(_json.dumps(payload)) > 65536:
                return False, "payload_too_large"
        except (RecursionError, ValueError):
            return False, "payload_too_deep"
    return True, ""
