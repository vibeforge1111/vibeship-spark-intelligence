#!/usr/bin/env python3
"""Compare legacy advisory-engine vs advisory-alpha quality telemetry."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from lib.advisory_log_paths import advisory_engine_log_compat


def _read_jsonl(path: Path, limit: int = 5000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    if limit > 0:
        lines = lines[-limit:]
    out: List[Dict[str, Any]] = []
    for line in lines:
        row = (line or "").strip()
        if not row:
            continue
        try:
            parsed = json.loads(row)
        except Exception:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def _window(rows: List[Dict[str, Any]], window_s: int) -> List[Dict[str, Any]]:
    if window_s <= 0:
        return rows
    cutoff = time.time() - float(window_s)
    out: List[Dict[str, Any]] = []
    for row in rows:
        try:
            ts = float(row.get("ts") or 0.0)
        except Exception:
            ts = 0.0
        if ts >= cutoff:
            out.append(row)
    return out


def _summarize_engine(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    emitted = 0
    fallback_emitted = 0
    trace_bound = 0
    elapsed: List[float] = []
    for row in rows:
        event = str(row.get("event") or "").strip().lower()
        if event == "emitted":
            emitted += 1
        if event == "fallback_emit":
            fallback_emitted += 1
        trace_id = str((row.get("extra") or {}).get("trace_id") or row.get("trace_id") or "").strip()
        if trace_id:
            trace_bound += 1
        try:
            elapsed.append(float(row.get("elapsed_ms") or 0.0))
        except Exception:
            pass
    avg_elapsed = sum(elapsed) / max(len(elapsed), 1) if elapsed else 0.0
    return {
        "rows": total,
        "emitted": emitted,
        "fallback_emitted": fallback_emitted,
        "emit_rate": round(emitted / max(total, 1), 4),
        "trace_coverage": round(trace_bound / max(total, 1), 4),
        "avg_elapsed_ms": round(avg_elapsed, 2),
    }


def _summarize_alpha(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    emitted = 0
    no_emit = 0
    trace_bound = 0
    elapsed: List[float] = []
    for row in rows:
        event = str(row.get("event") or "").strip().lower()
        if event == "emitted":
            emitted += 1
        if event in {"no_advice", "gate_no_emit", "emit_suppressed", "context_repeat_blocked", "dedupe_empty", "dedupe_gate_empty"}:
            no_emit += 1
        trace_id = str(row.get("trace_id") or "").strip()
        if trace_id:
            trace_bound += 1
        try:
            elapsed.append(float(row.get("elapsed_ms") or 0.0))
        except Exception:
            pass
    avg_elapsed = sum(elapsed) / max(len(elapsed), 1) if elapsed else 0.0
    return {
        "rows": total,
        "emitted": emitted,
        "no_emit_events": no_emit,
        "emit_rate": round(emitted / max(total, 1), 4),
        "trace_coverage": round(trace_bound / max(total, 1), 4),
        "avg_elapsed_ms": round(avg_elapsed, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare advisory engine and advisory alpha telemetry.")
    ap.add_argument("--window-s", type=int, default=86400, help="Time window in seconds (0=all rows).")
    ap.add_argument("--limit", type=int, default=8000, help="Tail rows to read per log.")
    ap.add_argument("--engine-log", type=str, default=str(advisory_engine_log_compat()))
    ap.add_argument("--alpha-log", type=str, default=str(Path.home() / ".spark" / "advisory_engine_alpha.jsonl"))
    args = ap.parse_args()

    engine_rows = _window(_read_jsonl(Path(args.engine_log), limit=max(0, int(args.limit))), int(args.window_s))
    alpha_rows = _window(_read_jsonl(Path(args.alpha_log), limit=max(0, int(args.limit))), int(args.window_s))

    engine = _summarize_engine(engine_rows)
    alpha = _summarize_alpha(alpha_rows)

    out = {
        "ok": True,
        "window_s": int(args.window_s),
        "engine_log": str(Path(args.engine_log)),
        "alpha_log": str(Path(args.alpha_log)),
        "engine": engine,
        "alpha": alpha,
        "delta": {
            "emit_rate": round(float(alpha.get("emit_rate", 0.0)) - float(engine.get("emit_rate", 0.0)), 4),
            "trace_coverage": round(float(alpha.get("trace_coverage", 0.0)) - float(engine.get("trace_coverage", 0.0)), 4),
            "avg_elapsed_ms": round(float(alpha.get("avg_elapsed_ms", 0.0)) - float(engine.get("avg_elapsed_ms", 0.0)), 2),
        },
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
