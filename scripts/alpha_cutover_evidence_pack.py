#!/usr/bin/env python3
"""Build a deterministic Spark Alpha cutover evidence pack.

Runs three evidence lanes and emits one decision artifact:
1) Live production gates
2) Replay evidence matrix
3) Advisory retrieval canary
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.production_gates import evaluate_gates, load_live_metrics


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "benchmarks" / "out" / "alpha_cutover"
REPLAY_SCRIPT = ROOT / "scripts" / "run_alpha_replay_evidence.py"
CANARY_SCRIPT = ROOT / "scripts" / "run_advisory_retrieval_canary.py"
CANARY_REPORT_DIR = ROOT / "docs" / "reports"
DEFAULT_MEMORY_CASES = ROOT / "benchmarks" / "data" / "memory_retrieval_eval_multidomain_real_user_2026_02_16.json"
DEFAULT_MEMORY_GATES = ROOT / "benchmarks" / "data" / "memory_retrieval_domain_gates_multidomain_v1.json"
DEFAULT_ADVISORY_CASES = ROOT / "benchmarks" / "data" / "advisory_quality_eval_seed.json"


def _parse_int_csv(raw: str, *, minimum: int = 1) -> List[int]:
    out: List[int] = []
    for part in str(raw or "").split(","):
        text = str(part or "").strip()
        if not text:
            continue
        value = int(text)
        if value < minimum:
            raise ValueError(f"value must be >= {minimum}: {value}")
        out.append(value)
    if not out:
        raise ValueError("expected at least one integer value")
    deduped: List[int] = []
    seen = set()
    for value in out:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _run_json_cmd(cmd: List[str], *, timeout_s: int = 1200) -> Dict[str, Any]:
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=max(30, int(timeout_s)),
    )
    stdout = str(proc.stdout or "").strip()
    stderr = str(proc.stderr or "").strip()
    payload: Dict[str, Any] = {}
    if stdout:
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            payload = {}
    return {
        "returncode": int(proc.returncode),
        "stdout": stdout,
        "stderr": stderr,
        "payload": payload,
    }


def _latest_report(pattern: str) -> Optional[Path]:
    if not CANARY_REPORT_DIR.exists():
        return None
    matches = sorted(
        CANARY_REPORT_DIR.glob(pattern),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    return matches[0] if matches else None


def _count_cases(path: Path) -> int:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    rows = raw.get("cases") if isinstance(raw, dict) else []
    if not isinstance(rows, list):
        return 0
    return int(len(rows))


def _run_replay(*, seeds: List[int], episodes: List[int], out_dir: Path, min_pass_rate: float, timeout_s: int) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(REPLAY_SCRIPT),
        "--seeds",
        ",".join(str(v) for v in seeds),
        "--episodes",
        ",".join(str(v) for v in episodes),
        "--out-dir",
        str(out_dir),
        "--require-promotion-pass-rate",
        str(float(min_pass_rate)),
    ]
    run = _run_json_cmd(cmd, timeout_s=timeout_s)
    payload = dict(run.get("payload") or {})
    return {
        "command": cmd,
        "returncode": int(run.get("returncode", 1)),
        "ok": int(run.get("returncode", 1)) == 0,
        "alpha_win_rate": float(payload.get("alpha_win_rate", 0.0) or 0.0),
        "promotion_pass_rate": float(payload.get("promotion_pass_rate", 0.0) or 0.0),
        "report_json": str(payload.get("report_json") or ""),
        "report_md": str(payload.get("report_md") or ""),
        "stderr": str(run.get("stderr") or "")[:500],
    }


def _run_canary(
    *,
    timeout_s: int,
    retrieval_level: str,
    mrr_min: float,
    gate_pass_rate_min: float,
    advisory_score_min: float,
    memory_cases: Path,
    memory_gates: Path,
    advisory_cases: Path,
) -> Dict[str, Any]:
    missing = [str(p) for p in (memory_cases, memory_gates, advisory_cases) if not p.exists()]
    if missing:
        return {
            "command": [],
            "returncode": 2,
            "ok": False,
            "status": "input_missing",
            "reason": f"missing_inputs:{','.join(missing)}",
            "evaluation": {},
            "metrics": {},
            "report_json": "",
            "stderr": "",
            "inputs": {
                "memory_cases": str(memory_cases),
                "memory_gates": str(memory_gates),
                "advisory_cases": str(advisory_cases),
            },
        }
    if _count_cases(memory_cases) <= 0:
        return {
            "command": [],
            "returncode": 2,
            "ok": False,
            "status": "input_empty",
            "reason": f"empty_cases:{memory_cases}",
            "evaluation": {},
            "metrics": {},
            "report_json": "",
            "stderr": "",
            "inputs": {
                "memory_cases": str(memory_cases),
                "memory_gates": str(memory_gates),
                "advisory_cases": str(advisory_cases),
            },
        }

    before = _latest_report("*_advisory_retrieval_canary_*.json")
    cmd = [
        sys.executable,
        str(CANARY_SCRIPT),
        "--timeout-s",
        str(int(timeout_s)),
        "--memory-cases",
        str(memory_cases),
        "--memory-gates",
        str(memory_gates),
        "--advisory-cases",
        str(advisory_cases),
        "--retrieval-level",
        str(retrieval_level),
        "--memory-mrr-min",
        str(float(mrr_min)),
        "--memory-gate-pass-rate-min",
        str(float(gate_pass_rate_min)),
        "--advisory-score-min",
        str(float(advisory_score_min)),
    ]
    run = _run_json_cmd(cmd, timeout_s=max(int(timeout_s), 120))
    after = _latest_report("*_advisory_retrieval_canary_*.json")

    report_path: Optional[Path] = None
    if after is not None and (before is None or after != before):
        report_path = after
    elif after is not None:
        report_path = after

    report: Dict[str, Any] = {}
    if report_path is not None and report_path.exists():
        try:
            loaded = json.loads(report_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                report = loaded
        except Exception:
            report = {}

    status = str(report.get("status") or "")
    evaluation = dict(report.get("evaluation") or {})
    metrics = dict(evaluation.get("metrics") or {})
    all_pass = bool(evaluation.get("all_pass"))
    promoted = status == "promoted"
    ok = int(run.get("returncode", 1)) == 0 and promoted and all_pass

    return {
        "command": cmd,
        "returncode": int(run.get("returncode", 1)),
        "ok": bool(ok),
        "status": status or ("command_failed" if int(run.get("returncode", 1)) != 0 else "unknown"),
        "evaluation": evaluation,
        "metrics": metrics,
        "report_json": str(report_path) if report_path is not None else "",
        "stderr": str(run.get("stderr") or "")[:500],
        "inputs": {
            "memory_cases": str(memory_cases),
            "memory_gates": str(memory_gates),
            "advisory_cases": str(advisory_cases),
        },
    }


def _build_summary(*, production: Dict[str, Any], replay: Dict[str, Any], canary: Dict[str, Any], run_canary: bool) -> Dict[str, Any]:
    checks = {
        "production_ready": bool(production.get("ready")),
        "replay_pass": bool(replay.get("ok")),
    }
    if run_canary:
        checks["canary_pass"] = bool(canary.get("ok"))
    ready = all(bool(v) for v in checks.values())
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ready_for_cutover": bool(ready),
        "checks": checks,
        "production": production,
        "replay": replay,
        "canary": canary if run_canary else {"skipped": True},
    }


def _render_markdown(payload: Dict[str, Any]) -> str:
    checks = payload.get("checks") or {}
    production = payload.get("production") or {}
    replay = payload.get("replay") or {}
    canary = payload.get("canary") or {}

    lines = [
        "# Spark Alpha Cutover Evidence Pack",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- ready_for_cutover: `{payload.get('ready_for_cutover')}`",
        "",
        "## Checks",
        "",
    ]
    for key, value in checks.items():
        lines.append(f"- {key}: `{'PASS' if value else 'FAIL'}`")

    lines.extend(
        [
            "",
            "## Production Gates",
            "",
            f"- ready: `{production.get('ready')}`",
            f"- gate_status: `{production.get('gate_status')}`",
            "",
            "## Replay Evidence",
            "",
            f"- ok: `{replay.get('ok')}`",
            f"- alpha_win_rate: `{replay.get('alpha_win_rate')}`",
            f"- promotion_pass_rate: `{replay.get('promotion_pass_rate')}`",
            f"- report_json: `{replay.get('report_json')}`",
            "",
            "## Canary",
            "",
            f"- ok: `{canary.get('ok')}`",
            f"- status: `{canary.get('status', 'skipped')}`",
            f"- report_json: `{canary.get('report_json', '')}`",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Spark Alpha cutover evidence pack (gates + replay + canary).")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--replay-seeds", default="42,77,101")
    ap.add_argument("--replay-episodes", default="20,60,120")
    ap.add_argument("--replay-min-promotion-pass-rate", type=float, default=1.0)
    ap.add_argument("--replay-timeout-s", type=int, default=2400)
    ap.add_argument("--run-canary", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--canary-timeout-s", type=int, default=1200)
    ap.add_argument("--canary-retrieval-level", default="2")
    ap.add_argument("--canary-memory-cases", default=str(DEFAULT_MEMORY_CASES))
    ap.add_argument("--canary-memory-gates", default=str(DEFAULT_MEMORY_GATES))
    ap.add_argument("--canary-advisory-cases", default=str(DEFAULT_ADVISORY_CASES))
    ap.add_argument("--canary-memory-mrr-min", type=float, default=0.35)
    ap.add_argument("--canary-gate-pass-rate-min", type=float, default=0.60)
    ap.add_argument("--canary-advisory-score-min", type=float, default=0.70)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics = load_live_metrics()
    gate_eval = evaluate_gates(metrics)
    checks = list(gate_eval.get("checks") or [])
    passed = sum(1 for row in checks if bool((row or {}).get("ok")))
    total = len(checks)
    ready_flag = bool(gate_eval.get("ready"))
    production = {
        "ready": ready_flag,
        "gate_status": f"{'READY' if ready_flag else 'NOT READY'} ({passed}/{total} passed)",
        "failed": list(gate_eval.get("failed_checks") or []),
    }

    seeds = _parse_int_csv(args.replay_seeds, minimum=1)
    episodes = _parse_int_csv(args.replay_episodes, minimum=1)
    replay = _run_replay(
        seeds=seeds,
        episodes=episodes,
        out_dir=ROOT / "benchmarks" / "out" / "replay_arena",
        min_pass_rate=float(args.replay_min_promotion_pass_rate),
        timeout_s=int(args.replay_timeout_s),
    )

    if bool(args.run_canary):
        canary = _run_canary(
            timeout_s=int(args.canary_timeout_s),
            retrieval_level=str(args.canary_retrieval_level),
            mrr_min=float(args.canary_memory_mrr_min),
            gate_pass_rate_min=float(args.canary_gate_pass_rate_min),
            advisory_score_min=float(args.canary_advisory_score_min),
            memory_cases=Path(str(args.canary_memory_cases)),
            memory_gates=Path(str(args.canary_memory_gates)),
            advisory_cases=Path(str(args.canary_advisory_cases)),
        )
    else:
        canary = {"skipped": True, "ok": True, "status": "skipped"}

    payload = _build_summary(
        production=production,
        replay=replay,
        canary=canary,
        run_canary=bool(args.run_canary),
    )

    run_id = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    json_path = out_dir / f"alpha_cutover_evidence_{run_id}.json"
    md_path = out_dir / f"alpha_cutover_evidence_{run_id}.md"
    latest_json = out_dir / "alpha_cutover_evidence_latest.json"
    latest_md = out_dir / "alpha_cutover_evidence_latest.md"

    body = json.dumps(payload, indent=2, ensure_ascii=True)
    json_path.write_text(body, encoding="utf-8")
    latest_json.write_text(body, encoding="utf-8")
    md = _render_markdown(payload)
    md_path.write_text(md, encoding="utf-8")
    latest_md.write_text(md, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "ready_for_cutover": bool(payload.get("ready_for_cutover")),
                "checks": payload.get("checks"),
                "report_json": str(json_path),
                "report_md": str(md_path),
            },
            indent=2,
        )
    )
    return 0 if bool(payload.get("ready_for_cutover")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
