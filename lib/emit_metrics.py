"""Shared advisory telemetry helpers for emit/suppression metrics."""

from __future__ import annotations

from typing import Any, Dict, Iterable


SUPPRESSION_EVENTS = {
    "no_emit",
    "gate_no_emit",
    "context_repeat_blocked",
    "dedupe_empty",
    "no_advice",
    "emit_suppressed",
}


def advisory_engine_emit_metrics(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    emitted = 0
    suppressed = 0
    for row in rows:
        event = str((row or {}).get("event") or "").strip()
        if event == "emitted":
            emitted += 1
            continue
        if event in SUPPRESSION_EVENTS:
            suppressed += 1

    denom = emitted + suppressed
    emit_rate = (float(emitted) / float(denom)) if denom > 0 else 0.0
    return {
        "emitted": int(emitted),
        "suppressed": int(suppressed),
        "denom": int(denom),
        "emit_rate": round(float(emit_rate), 3),
    }


def advisory_decision_emit_metrics(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    emitted = 0
    blocked = 0
    for row in rows:
        outcome = str((row or {}).get("outcome") or "").strip()
        if outcome == "emitted":
            emitted += 1
            continue
        if outcome == "blocked":
            blocked += 1
    denom = emitted + blocked
    emit_rate = (float(emitted) / float(denom)) if denom > 0 else 0.0
    return {
        "emitted": int(emitted),
        "blocked": int(blocked),
        "denom": int(denom),
        "emit_rate": round(float(emit_rate), 3),
    }
