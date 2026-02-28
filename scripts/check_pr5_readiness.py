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
    for row in rows:
        route_counter[str(row.get("route") or "unknown")] += 1
        reason_counter[str(row.get("reason") or "unknown")] += 1
    return {
        "rows": len(rows),
        "route_mix": dict(route_counter),
        "reason_mix": dict(reason_counter),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run PR-05 readiness gate checks.")
    ap.add_argument("--precision-floor", type=float, default=0.30, help="Minimum acceptable overall P@5.")
    ap.add_argument("--latency-p95-max-ms", type=float, default=2000.0, help="Maximum acceptable p95 latency (ms).")
    ap.add_argument("--noise-rate-max", type=float, default=0.05, help="Maximum acceptable overall noise rate.")
    ap.add_argument("--route-log-lines", type=int, default=1200, help="How many recent route rows to summarize.")
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
    routes = _route_mix_summary(route_rows)

    gates = {
        "precision_gate": precision >= float(args.precision_floor),
        "latency_gate": latency_p95 <= float(args.latency_p95_max_ms),
        "noise_gate": noise <= float(args.noise_rate_max),
    }

    replay_payload: Dict[str, Any] = {}
    if bool(args.run_replay):
        replay_payload = _run_replay_arena(
            seed=int(args.replay_seed),
            episodes=int(args.replay_episodes),
            out_dir=OUT_DIR,
        )
        promotion = replay_payload.get("promotion") or {}
        gates["replay_promotion_gate"] = bool(promotion.get("promotion_gate_pass"))

    report = {
        "run_id": run_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "inputs": {
            "precision_floor": float(args.precision_floor),
            "latency_p95_max_ms": float(args.latency_p95_max_ms),
            "noise_rate_max": float(args.noise_rate_max),
            "route_log_lines": int(args.route_log_lines),
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
        "replay": replay_payload,
        "gates": gates,
        "pass": all(bool(v) for v in gates.values()),
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
