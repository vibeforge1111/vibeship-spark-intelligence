from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ALPHA_SUPPRESSION_EVENTS = {
    "gate_no_emit",
    "emit_suppressed",
    "global_dedupe_suppressed",
    "context_repeat_blocked",
    "dedupe_empty",
    "dedupe_gate_empty",
}


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _row_ts(row: Dict[str, Any]) -> float:
    # Different Spark logs use different timestamp keys.
    # - advisory_engine_alpha.jsonl: typically "ts"
    # - advice_feedback_requests.jsonl: typically "created_at"
    for key in ("ts", "created_at", "timestamp"):
        if key in row:
            ts = _safe_float(row.get(key), 0.0)
            if ts:
                return ts
    return 0.0


def _collect_rows_since(path: Path, start_ts: float) -> List[Dict[str, Any]]:
    out = []
    for row in _read_jsonl(path):
        ts = _row_ts(row)
        if ts >= start_ts:
            out.append(row)
    return out


def _summarize_repeats(advice_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    texts: List[str] = []
    trace_rows = 0
    for row in advice_rows:
        if row.get("trace_id"):
            trace_rows += 1
        for t in (row.get("advice_texts") or []):
            text = str(t or "").strip()
            if text:
                texts.append(text)
    total_items = len(texts)
    if total_items <= 0:
        return {
            "rows": len(advice_rows),
            "trace_rows": trace_rows,
            "trace_coverage_pct": 0.0,
            "item_total": 0,
            "top_repeats": [],
            "top_repeat_share_pct": 0.0,
            "unique_ratio_pct": 0.0,
        }
    counter = Counter(texts)
    top = [
        {"text": text[:180], "count": int(count)}
        for text, count in counter.most_common(5)
    ]
    top_share = (top[0]["count"] / total_items * 100.0) if top else 0.0
    unique_ratio = len(counter) / total_items * 100.0
    return {
        "rows": len(advice_rows),
        "trace_rows": trace_rows,
        "trace_coverage_pct": round((trace_rows / max(1, len(advice_rows))) * 100.0, 2),
        "item_total": total_items,
        "top_repeats": top,
        "top_repeat_share_pct": round(top_share, 2),
        "unique_ratio_pct": round(unique_ratio, 2),
    }


def _summarize_engine(engine_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    events = Counter()
    routes = Counter()
    error_codes = Counter()
    synth_policy_counts = Counter()
    emitted_synth_policy_counts = Counter()
    selective_ai_eligibility = Counter()
    emitted_authority_counts = Counter()
    trace_rows = 0
    suppression_events = 0
    delivered = 0
    elapsed_ms: List[float] = []
    for row in engine_rows:
        ev = str(row.get("event") or "")
        rt = str(row.get("route") or "")
        if ev:
            events[ev] += 1
        if rt:
            routes[rt] += 1
        error_code = str(row.get("error_code") or "").strip()
        if error_code:
            error_codes[error_code] += 1
        synth_policy = str(row.get("synth_policy") or "").strip() or "__missing__"
        if ev in {"emitted", "synth_empty"}:
            synth_policy_counts[synth_policy] += 1
            selective_ai_eligibility["eligible" if bool(row.get("selective_ai_eligible")) else "not_eligible"] += 1
            for auth in list(row.get("emitted_authorities") or [])[:4]:
                name = str(auth or "").strip().lower()
                if name:
                    emitted_authority_counts[name] += 1
        if ev == "emitted":
            emitted_synth_policy_counts[synth_policy] += 1
        if row.get("trace_id"):
            trace_rows += 1
        if ev in ALPHA_SUPPRESSION_EVENTS:
            suppression_events += 1
        if ev == "emitted":
            delivered += 1
            ems = _safe_float(row.get("elapsed_ms"), 0.0)
            if ems > 0:
                elapsed_ms.append(ems)

    elapsed_ms.sort()
    def _pct(p: float) -> float:
        if not elapsed_ms:
            return 0.0
        idx = int(round((p / 100.0) * (len(elapsed_ms) - 1)))
        idx = max(0, min(len(elapsed_ms) - 1, idx))
        return float(elapsed_ms[idx])

    return {
        "rows": len(engine_rows),
        "trace_rows": trace_rows,
        "trace_coverage_pct": round((trace_rows / max(1, len(engine_rows))) * 100.0, 2),
        "events": dict(events),
        "routes": dict(routes),
        "error_codes": dict(error_codes),
        "synth_policy_counts": dict(synth_policy_counts),
        "emitted_synth_policy_counts": dict(emitted_synth_policy_counts),
        "selective_ai_eligibility": dict(selective_ai_eligibility),
        "emitted_authority_counts": dict(emitted_authority_counts),
        "suppression_share_pct": round((suppression_events / max(1, len(engine_rows))) * 100.0, 2),
        "latency": {
            "n": len(elapsed_ms),
            "p50_ms": round(_pct(50), 2),
            "p90_ms": round(_pct(90), 2),
            "p95_ms": round(_pct(95), 2),
            "p99_ms": round(_pct(99), 2),
            "max_ms": round(float(elapsed_ms[-1]), 2) if elapsed_ms else 0.0,
        },
    }


def run_workload(
    rounds: int,
    session_prefix: str,
    trace_prefix: str,
    *,
    force_live: bool = False,
    reset_feedback_state: bool = True,
    prompt_mode: str = "constant",
    tool_input_mode: str = "synthetic",
) -> Dict[str, Any]:
    from lib import advisory_engine_alpha as advisory_runtime
    from lib import advisory_gate
    from lib import advisor as advisor_mod
    from lib import advisory_packet_store as packet_store

    repo_root = Path(__file__).resolve().parents[1]
    spark_dir = Path.home() / ".spark"
    engine_log = spark_dir / "advisory_engine_alpha.jsonl"
    feedback_requests = spark_dir / "advice_feedback_requests.jsonl"
    feedback_state = spark_dir / "advice_feedback_state.json"

    if reset_feedback_state and feedback_state.exists():
        try:
            feedback_state.unlink()
        except Exception:
            pass

    start_ts = time.time()
    end_ts: float | None = None
    emitted_count = 0
    tools = ["Read", "Edit", "Task", "WebFetch", "Read", "Task", "Edit", "WebFetch"]
    orig_lookup_exact = packet_store.lookup_exact
    orig_lookup_relaxed = packet_store.lookup_relaxed
    if force_live:
        packet_store.lookup_exact = lambda **_kwargs: None  # type: ignore[assignment]
        packet_store.lookup_relaxed = lambda **_kwargs: None  # type: ignore[assignment]

    try:
        for i in range(max(1, rounds)):
            tool_name = tools[i % len(tools)]
            session_id = f"{session_prefix}-{i % 6}"
            trace_id = f"{trace_prefix}-{i:04d}"

            if tool_input_mode == "repo":
                # Prefer real files so the advisor has a chance to match on concrete context.
                candidates = [
                    "AGENTS.md",
                    "CLAUDE.md",
                    "README.md",
                    "docs/reports/2026-02-15_233443_prompt_run_10_2_6.md",
                    "lib/advisor.py",
                    "lib/advisory_engine_alpha.py",
                    "lib/advisory_engine_alpha.py",
                    "scripts/advisory_controlled_delta.py",
                ]
                rel = candidates[i % len(candidates)]
                file_path = str((repo_root / rel).resolve())
            else:
                file_path = f"synthetic/{tool_name.lower()}_{i}.txt"

            if prompt_mode == "vary":
                prompt = (
                    "Evaluate advisory quality under repeated tool execution.\n"
                    f"Round: {i}\n"
                    f"Tool: {tool_name}\n"
                    f"Target: {file_path}\n"
                    "Requirements: be precise, non-repetitive, actionable, and bind advice to the trace."
                )
            else:
                prompt = (
                    "Evaluate advisory quality under repeated tool execution. "
                    "Focus on precise, non-repetitive, actionable guidance with trace binding."
                )
            advisory_runtime.on_user_prompt(session_id, prompt, trace_id=trace_id)
            tool_input = {"file_path": file_path, "attempt": i}
            text = advisory_runtime.on_pre_tool(
                session_id=session_id,
                tool_name=tool_name,
                tool_input=tool_input,
                trace_id=trace_id,
            )
            if text:
                emitted_count += 1
            success = not (tool_name in {"Task", "WebFetch"} and (i % 3 == 0))
            advisory_runtime.on_post_tool(
                session_id=session_id,
                tool_name=tool_name,
                success=success,
                tool_input=tool_input,
                trace_id=trace_id,
                error=(None if success else "synthetic_failure"),
            )
    finally:
        end_ts = time.time()
        if force_live:
            packet_store.lookup_exact = orig_lookup_exact  # type: ignore[assignment]
            packet_store.lookup_relaxed = orig_lookup_relaxed  # type: ignore[assignment]

    # Small flush window for file writes.
    time.sleep(0.25)

    engine_rows = _collect_rows_since(engine_log, start_ts)
    advice_rows = _collect_rows_since(feedback_requests, start_ts)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_ts": start_ts,
        "end_ts": end_ts,
        "rounds": rounds,
        "emitted_returns": emitted_count,
        "engine": _summarize_engine(engine_rows),
        "feedback_requests": _summarize_repeats(advice_rows),
        "modes": {
            "prompt_mode": str(prompt_mode),
            "tool_input_mode": str(tool_input_mode),
        },
        "config": {
            "advisory_route": {
                "mode": "alpha",
                "decision_log": str(engine_log),
            },
            "advisory_gate": advisory_gate.get_gate_config(),
            "advisor": {
                "max_items": int(getattr(advisor_mod, "MAX_ADVICE_ITEMS", 0)),
                "min_rank_score": float(getattr(advisor_mod, "MIN_RANK_SCORE", 0.0)),
            },
        },
        "force_live": bool(force_live),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run controlled advisory workload and summarize KPIs")
    ap.add_argument("--rounds", type=int, default=40, help="Number of synthetic pre/post tool rounds")
    ap.add_argument("--label", default="run", help="Label used in output metadata")
    ap.add_argument("--out", default="", help="Optional output JSON path")
    ap.add_argument("--session-prefix", default="", help="Optional session prefix override")
    ap.add_argument("--trace-prefix", default="", help="Optional trace prefix override")
    ap.add_argument("--force-live", action="store_true", help="Bypass packet lookup to exercise live advisory path")
    ap.add_argument(
        "--prompt-mode",
        choices=("constant", "vary"),
        default="constant",
        help="constant: stable prompt for routing comparisons; vary: include tool/target/round to reduce dedupe.",
    )
    ap.add_argument(
        "--tool-input-mode",
        choices=("synthetic", "repo"),
        default="synthetic",
        help="synthetic: fake file paths; repo: rotate through real repo files to improve match odds.",
    )
    ap.add_argument(
        "--no-reset-feedback-state",
        action="store_true",
        help="Keep existing advice feedback state (default resets for clean comparisons)",
    )
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    trace_prefix = str(args.trace_prefix or "").strip() or f"delta-{args.label}-{ts}"
    # Default bench sessions bypass global/low-auth dedupe guards so controlled runs can measure emissions.
    session_prefix = str(args.session_prefix or "").strip() or f"advisory-bench-{args.label}"
    summary = run_workload(
        rounds=max(1, int(args.rounds)),
        session_prefix=session_prefix,
        trace_prefix=trace_prefix,
        force_live=bool(args.force_live),
        reset_feedback_state=not bool(args.no_reset_feedback_state),
        prompt_mode=str(args.prompt_mode),
        tool_input_mode=str(args.tool_input_mode),
    )
    summary["label"] = str(args.label)
    summary["trace_prefix"] = trace_prefix
    summary["session_prefix"] = session_prefix

    out_path = Path(args.out) if args.out else None
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Wrote: {out_path}")
    else:
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

