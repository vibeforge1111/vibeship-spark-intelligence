#!/usr/bin/env python3
"""PR-05 readiness gate for retrieval fusion + contextual advisory routing.

Evaluates:
- Retrieval quality harness metrics (P@5, noise, latency p95)
- Optional replay-arena promotion signal
- Recent retrieval route telemetry mix
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "benchmarks" / "out" / "pr5_gate"
RETRIEVAL_ROUTE_LOG = Path.home() / ".spark" / "advisor" / "retrieval_router.jsonl"
SEMANTIC_LOG = Path.home() / ".spark" / "logs" / "semantic_retrieval.jsonl"
REPLAY_SCRIPT = ROOT / "scripts" / "spark_alpha_replay_arena.py"


def _tail_jsonl(path: Path, max_lines: int = 2000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    if max_lines > 0 and len(lines) > max_lines:
        lines = lines[-max_lines:]
    rows: List[Dict[str, Any]] = []
    for line in lines:
        row = (line or "").strip()
        if not row:
            continue
        try:
            parsed = json.loads(row)
        except Exception:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _run_retrieval_quality() -> Dict[str, Any]:
    from tests.test_retrieval_quality import _get_advisor, run_all_scenarios

    advisor = _get_advisor()
    return run_all_scenarios(advisor)


def _run_replay_arena(seed: int, episodes: int, out_dir: Path) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(REPLAY_SCRIPT),
        "--seed",
        str(int(seed)),
        "--episodes",
        str(int(episodes)),
        "--out-dir",
        str(out_dir),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"replay arena failed (rc={proc.returncode}): {(proc.stderr or '').strip() or 'no stderr'}"
        )
    body = str(proc.stdout or "").strip()
    if not body:
        raise RuntimeError("replay arena returned empty stdout")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise RuntimeError("replay arena stdout was not JSON object")
    return parsed


def _route_mix_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    route_counter: Counter[str] = Counter()
    reason_counter: Counter[str] = Counter()
    missing_route_fields = 0
    missing_reason_fields = 0
    empty_route_count = 0
    unknown_reason_count = 0
    actionable_denominator = 0
    actionable_empty_count = 0

    for row in rows:
        route_raw = str(row.get("route") or "").strip()
        route = route_raw or "unknown"
        complexity = int(row.get("complexity_score") or 0)
        primary_count = int(row.get("primary_count") or 0)
        is_actionable = complexity >= 2 or primary_count > 0
        if is_actionable:
            actionable_denominator += 1
        if not route_raw:
            missing_route_fields += 1
        if route == "empty":
            empty_route_count += 1
            if is_actionable:
                actionable_empty_count += 1
        route_counter[route] += 1

        reason_raw = str(row.get("reason") or "").strip()
        reason = reason_raw
        if not reason:
            reasons = row.get("reasons")
            if isinstance(reasons, list):
                for candidate in reasons:
                    token = str(candidate or "").strip()
                    if token:
                        reason = token
                        break
        if not reason:
            missing_reason_fields += 1
            reason = "unknown"
        if reason == "unknown":
            unknown_reason_count += 1
        reason_counter[reason] += 1

    row_count = len(rows)
    return {
        "rows": row_count,
        "route_mix": dict(route_counter),
        "reason_mix": dict(reason_counter),
        "missing_route_fields": missing_route_fields,
        "missing_reason_fields": missing_reason_fields,
        "empty_route_count": empty_route_count,
        "unknown_reason_count": unknown_reason_count,
        "missing_route_rate": (missing_route_fields / row_count) if row_count else 0.0,
        "missing_reason_rate": (missing_reason_fields / row_count) if row_count else 0.0,
        "empty_route_rate": (empty_route_count / row_count) if row_count else 0.0,
        "actionable_rows": actionable_denominator,
        "actionable_empty_count": actionable_empty_count,
        "actionable_empty_rate": (
            actionable_empty_count / actionable_denominator
        )
        if actionable_denominator
        else 0.0,
        "unknown_reason_rate": (unknown_reason_count / row_count) if row_count else 0.0,
    }


def _semantic_context_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    bucket_counter: Counter[str] = Counter()
    rescue_used = 0
    for row in rows:
        final_results = row.get("final_results")
        final_count = len(final_results) if isinstance(final_results, list) else 0
        candidates = int(row.get("semantic_candidates_count") or 0)
        embedding = bool(row.get("embedding_available"))
        if bool(row.get("rescue_used")):
            rescue_used += 1
        if final_count > 0:
            bucket = "non_empty"
        elif embedding and candidates <= 0:
            bucket = "embed_enabled_no_candidates"
        elif (not embedding) and candidates <= 0:
            bucket = "no_embeddings_no_keyword_overlap"
        elif candidates > 0 and final_count <= 0:
            bucket = "gated_or_filtered_after_candidates"
        else:
            bucket = "other_empty"
        bucket_counter[bucket] += 1
    total = max(1, len(rows))
    return {
        "rows": len(rows),
        "empty_context_buckets": dict(bucket_counter),
        "empty_share": 1.0 - (float(bucket_counter.get("non_empty", 0)) / float(total)),
        "rescue_used_count": rescue_used,
        "rescue_used_rate": float(rescue_used) / float(total),
    }


def _production_noise_gate_summary(
    report: Dict[str, Any],
    *,
    min_expected_noise_rows: int,
    min_recall: float,
    max_fp_rate: float,
) -> Dict[str, Any]:
    expected_noise = int(report.get("expected_noise_rows") or 0)
    recall = float(report.get("recall") or 0.0)
    fp_rate = float(report.get("false_positive_rate") or 0.0)
    coverage_ok = expected_noise >= max(1, int(min_expected_noise_rows))
    return {
        "expected_noise_coverage_gate": bool(coverage_ok),
        "production_noise_recall_gate": bool(coverage_ok and recall >= float(min_recall)),
        "production_noise_fp_gate": bool(fp_rate <= float(max_fp_rate)),
        "expected_noise_rows": expected_noise,
        "recall": recall,
        "false_positive_rate": fp_rate,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run PR-05 readiness gate checks.")
    ap.add_argument("--precision-floor", type=float, default=0.30, help="Minimum acceptable overall P@5.")
    ap.add_argument("--latency-p95-max-ms", type=float, default=2000.0, help="Maximum acceptable p95 latency (ms).")
    ap.add_argument("--noise-rate-max", type=float, default=0.05, help="Maximum acceptable overall noise rate.")
    ap.add_argument("--route-log-lines", type=int, default=1200, help="How many recent route rows to summarize.")
    ap.add_argument("--route-min-rows", type=int, default=200, help="Minimum route telemetry rows required for gate validity.")
    ap.add_argument("--route-empty-max", type=float, default=0.05, help="Maximum acceptable empty-route share.")
    ap.add_argument(
        "--route-actionable-empty-max",
        type=float,
        default=0.05,
        help="Maximum acceptable empty-route share for actionable rows (complexity>=2 or primary_count>0).",
    )
    ap.add_argument("--reason-unknown-max", type=float, default=0.05, help="Maximum acceptable unknown-reason share.")
    ap.add_argument(
        "--production-noise-min-expected",
        type=int,
        default=20,
        help="Minimum expected-noise rows required for production noise recall validity.",
    )
    ap.add_argument(
        "--production-noise-min-recall",
        type=float,
        default=0.90,
        help="Minimum acceptable production hard-noise recall.",
    )
    ap.add_argument(
        "--production-noise-max-fp-rate",
        type=float,
        default=0.15,
        help="Maximum acceptable production signal false-positive rate.",
    )
    ap.add_argument("--run-replay", action="store_true", help="Run replay arena and include promotion signal.")
    ap.add_argument("--replay-seed", type=int, default=42, help="Replay seed when --run-replay is enabled.")
    ap.add_argument("--replay-episodes", type=int, default=24, help="Replay episode count when --run-replay is enabled.")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d_%H%M%S", time.localtime())

    quality = _run_retrieval_quality()
    precision = float(quality.get("overall_precision_at_5") or 0.0)
    noise = float(quality.get("noise_rate") or 0.0)
    latency_p95 = float(quality.get("p95_latency_ms") or 0.0)

    route_rows = _tail_jsonl(RETRIEVAL_ROUTE_LOG, max_lines=max(100, int(args.route_log_lines)))
    semantic_rows = _tail_jsonl(SEMANTIC_LOG, max_lines=max(100, int(args.route_log_lines)))
    routes = _route_mix_summary(route_rows)
    semantic_context = _semantic_context_summary(semantic_rows)
    from lib.advisory_content_quality import build_production_noise_report

    production_noise = build_production_noise_report(
        spark_dir=Path.home() / ".spark",
        max_rows_per_source=max(250, int(args.route_log_lines)),
        detail_rows=240,
    )
    production_noise_gates = _production_noise_gate_summary(
        production_noise,
        min_expected_noise_rows=max(1, int(args.production_noise_min_expected)),
        min_recall=float(args.production_noise_min_recall),
        max_fp_rate=float(args.production_noise_max_fp_rate),
    )
    route_row_count = int(routes.get("rows") or 0)
    empty_route_rate = float(routes.get("empty_route_rate") or 0.0)
    actionable_empty_rate = float(routes.get("actionable_empty_rate") or 0.0)
    unknown_reason_rate = float(routes.get("unknown_reason_rate") or 0.0)

    gates = {
        "precision_gate": precision >= float(args.precision_floor),
        "latency_gate": latency_p95 <= float(args.latency_p95_max_ms),
        "noise_gate": noise <= float(args.noise_rate_max),
        "route_coverage_gate": route_row_count >= max(1, int(args.route_min_rows)),
        "route_empty_gate": actionable_empty_rate <= float(args.route_actionable_empty_max),
        "route_empty_raw_monitor_gate": empty_route_rate <= float(args.route_empty_max),
        "reason_unknown_gate": unknown_reason_rate <= float(args.reason_unknown_max),
        "production_noise_coverage_gate": bool(production_noise_gates.get("expected_noise_coverage_gate")),
        "production_noise_recall_gate": bool(production_noise_gates.get("production_noise_recall_gate")),
        "production_noise_fp_gate": bool(production_noise_gates.get("production_noise_fp_gate")),
    }

    replay_payload: Dict[str, Any] = {}
    if bool(args.run_replay):
        replay_payload = _run_replay_arena(
            seed=int(args.replay_seed),
            episodes=int(args.replay_episodes),
            out_dir=OUT_DIR,
        )
        # Replay stdout currently exposes gate fields at top-level.
        # Keep a nested fallback for backward compatibility.
        promotion = replay_payload.get("promotion") or {}
        gate_value = replay_payload.get("promotion_gate_pass")
        if gate_value is None:
            gate_value = promotion.get("promotion_gate_pass")
        gates["replay_promotion_gate"] = bool(gate_value)

    blocking_gates = {
        key: value
        for key, value in gates.items()
        if key not in {"route_empty_raw_monitor_gate"}
    }

    report = {
        "run_id": run_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "inputs": {
            "precision_floor": float(args.precision_floor),
            "latency_p95_max_ms": float(args.latency_p95_max_ms),
            "noise_rate_max": float(args.noise_rate_max),
            "route_log_lines": int(args.route_log_lines),
            "route_min_rows": int(args.route_min_rows),
            "route_empty_max": float(args.route_empty_max),
            "route_actionable_empty_max": float(args.route_actionable_empty_max),
            "reason_unknown_max": float(args.reason_unknown_max),
            "production_noise_min_expected": int(args.production_noise_min_expected),
            "production_noise_min_recall": float(args.production_noise_min_recall),
            "production_noise_max_fp_rate": float(args.production_noise_max_fp_rate),
            "run_replay": bool(args.run_replay),
            "replay_seed": int(args.replay_seed),
            "replay_episodes": int(args.replay_episodes),
        },
        "retrieval_quality": {
            "overall_precision_at_5": precision,
            "noise_rate": noise,
            "p95_latency_ms": latency_p95,
            "avg_latency_ms": float(quality.get("avg_latency_ms") or 0.0),
            "by_category": quality.get("by_category") or {},
        },
        "route_telemetry": routes,
        "semantic_context": semantic_context,
        "production_noise_regression": production_noise,
        "production_noise_gate_summary": production_noise_gates,
        "replay": replay_payload,
        "gates": gates,
        "blocking_gates": blocking_gates,
        "pass": all(bool(v) for v in blocking_gates.values()),
    }

    out_json = OUT_DIR / f"pr5_readiness_{run_id}.json"
    latest_json = OUT_DIR / "pr5_readiness_latest.json"
    payload = json.dumps(report, indent=2, ensure_ascii=True)
    out_json.write_text(payload, encoding="utf-8")
    latest_json.write_text(payload, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "pass": bool(report.get("pass")),
                "gates": gates,
                "report_json": str(out_json),
                "latest_json": str(latest_json),
            },
            indent=2,
        )
    )
    return 0 if bool(report.get("pass")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
