#!/usr/bin/env python3
"""Run Spark Alpha start readiness checks as one reproducible command."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "benchmarks" / "out" / "alpha_start"
PRODUCTION_REPORT_SCRIPT = ROOT / "scripts" / "production_loop_report.py"
REPLAY_EVIDENCE_SCRIPT = ROOT / "scripts" / "run_alpha_replay_evidence.py"
DELTA_SCRIPT = ROOT / "scripts" / "advisory_controlled_delta.py"
GAP_AUDIT_SCRIPT = ROOT / "scripts" / "alpha_gap_audit.py"

DEFAULT_PYTEST_TARGETS = [
    "tests/test_spark_alpha_replay_arena.py",
    "tests/test_run_alpha_replay_evidence_helpers.py",
    "tests/test_advisory_engine_alpha.py",
    "tests/test_advisory_orchestrator.py",
    "tests/test_advisory_packet_store.py",
    "tests/test_advisor.py",
    "tests/test_advisor_retrieval_routing.py",
    "tests/test_tuneables_alignment.py",
    "tests/test_pr1_config_authority.py",
    "tests/test_context_sync_policy.py",
    "tests/test_memory_compaction.py",
    "tests/test_memory_spine_sqlite.py",
    "tests/test_advisory_preferences.py",
    "tests/test_advisory_self_review.py",
    "tests/test_cross_surface_drift_checker.py",
    "tests/test_memory_quality_observatory.py",
    "tests/test_carmack_kpi.py",
    "tests/test_advisory_day_trial.py",
    "tests/test_intelligence_llm_preferences.py",
    "tests/test_llm_dispatch.py",
    "tests/test_production_loop_gates.py",
]


@dataclass
class StageResult:
    name: str
    ok: bool
    returncode: int
    duration_s: float
    command: List[str]
    stdout: str
    stderr: str
    details: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ok": bool(self.ok),
            "returncode": int(self.returncode),
            "duration_s": round(float(self.duration_s), 3),
            "command": list(self.command),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "details": dict(self.details),
        }


def _parse_json_payload(text: str) -> Dict[str, Any]:
    body = str(text or "").strip()
    if not body:
        raise ValueError("empty json payload")
    try:
        payload = json.loads(body)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    end = body.rfind("}")
    if end < 0:
        raise ValueError("no json object found in payload")
    for start in range(end, -1, -1):
        if body[start] != "{":
            continue
        candidate = body[start : end + 1]
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("unable to parse json object from payload")


def _parse_csv(raw: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for part in str(raw or "").split(","):
        value = str(part or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _run_command(command: List[str], *, timeout_s: int) -> Dict[str, Any]:
    start = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=int(timeout_s),
    )
    elapsed = time.perf_counter() - start
    return {
        "returncode": int(proc.returncode),
        "stdout": str(proc.stdout or ""),
        "stderr": str(proc.stderr or ""),
        "duration_s": float(elapsed),
    }


def _render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Spark Alpha Start Readiness",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- run_id: `{report.get('run_id')}`",
        f"- strict: `{report.get('strict')}`",
        f"- ready: `{report.get('ready')}`",
        "",
        "## Stage Summary",
        "",
        "| stage | ok | returncode | duration_s | key details |",
        "|---|---:|---:|---:|---|",
    ]
    for stage in report.get("stages") or []:
        details = stage.get("details") or {}
        key_fields = []
        for key in (
            "gate_status",
            "promotion_pass_rate",
            "alpha_win_rate",
            "winner",
            "advisory_files",
            "tuneable_keys",
            "distillation_files",
            "lib_jsonl_runtime_ext_refs",
            "report_json",
            "delta_out",
            "pytest_tail",
        ):
            if key in details:
                key_fields.append(f"{key}={details.get(key)}")
        lines.append(
            "| {name} | {ok} | {returncode} | {duration_s} | {details} |".format(
                name=stage.get("name"),
                ok=stage.get("ok"),
                returncode=stage.get("returncode"),
                duration_s=stage.get("duration_s"),
                details="; ".join(key_fields) if key_fields else "-",
            )
        )
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    for key, value in (report.get("artifacts") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    return "\n".join(lines)


def _production_stage(*, strict: bool, timeout_s: int) -> StageResult:
    cmd = [sys.executable, str(PRODUCTION_REPORT_SCRIPT)]
    res = _run_command(cmd, timeout_s=timeout_s)
    stdout = str(res["stdout"])
    gate_status = "unknown"
    for line in stdout.splitlines():
        if "Gate status:" in line:
            gate_status = line.split("Gate status:", 1)[1].strip()
            break
    ok = res["returncode"] == 0
    if strict:
        ok = ok and ("Gate status: READY" in stdout)
    return StageResult(
        name="production_gates",
        ok=ok,
        returncode=int(res["returncode"]),
        duration_s=float(res["duration_s"]),
        command=cmd,
        stdout=stdout,
        stderr=str(res["stderr"]),
        details={"gate_status": gate_status},
    )


def _replay_stage(
    *,
    strict: bool,
    timeout_s: int,
    seeds: str,
    episodes: str,
    out_dir: Path,
    min_promotion_pass_rate: float,
    min_alpha_win_rate: float,
) -> StageResult:
    cmd = [
        sys.executable,
        str(REPLAY_EVIDENCE_SCRIPT),
        "--seeds",
        str(seeds),
        "--episodes",
        str(episodes),
        "--out-dir",
        str(out_dir),
        "--require-promotion-pass-rate",
        str(float(min_promotion_pass_rate)),
    ]
    res = _run_command(cmd, timeout_s=timeout_s)
    details: Dict[str, Any] = {}
    ok = res["returncode"] == 0
    try:
        payload = _parse_json_payload(str(res["stdout"]))
        details.update(
            {
                "alpha_win_rate": float(payload.get("alpha_win_rate", 0.0) or 0.0),
                "promotion_pass_rate": float(payload.get("promotion_pass_rate", 0.0) or 0.0),
                "runs": int(payload.get("runs", 0) or 0),
                "report_json": str(payload.get("report_json") or ""),
                "report_md": str(payload.get("report_md") or ""),
            }
        )
    except Exception as exc:
        details["parse_error"] = str(exc)
        payload = {}

    if strict:
        ok = ok and float(details.get("promotion_pass_rate", 0.0)) >= float(min_promotion_pass_rate)
        ok = ok and float(details.get("alpha_win_rate", 0.0)) >= float(min_alpha_win_rate)
        ok = ok and int(details.get("runs", 0)) > 0

    return StageResult(
        name="replay_evidence",
        ok=ok,
        returncode=int(res["returncode"]),
        duration_s=float(res["duration_s"]),
        command=cmd,
        stdout=str(res["stdout"]),
        stderr=str(res["stderr"]),
        details=details,
    )


def _delta_stage(*, strict: bool, timeout_s: int, out_path: Path, rounds: int, label: str) -> StageResult:
    cmd = [
        sys.executable,
        str(DELTA_SCRIPT),
        "--rounds",
        str(int(rounds)),
        "--label",
        str(label),
        "--out",
        str(out_path),
    ]
    res = _run_command(cmd, timeout_s=timeout_s)
    ok = res["returncode"] == 0
    if strict:
        ok = ok and out_path.exists()
    return StageResult(
        name="controlled_delta",
        ok=ok,
        returncode=int(res["returncode"]),
        duration_s=float(res["duration_s"]),
        command=cmd,
        stdout=str(res["stdout"]),
        stderr=str(res["stderr"]),
        details={"delta_out": str(out_path)},
    )


def _gap_stage(
    *,
    strict: bool,
    timeout_s: int,
    max_advisory_files: int,
    max_tuneable_keys: int,
    max_distillation_files: int,
    max_lib_jsonl_runtime_ext_refs: int,
) -> StageResult:
    cmd = [sys.executable, str(GAP_AUDIT_SCRIPT)]
    res = _run_command(cmd, timeout_s=timeout_s)
    details: Dict[str, Any] = {}
    ok = res["returncode"] == 0
    try:
        payload = _parse_json_payload(str(res["stdout"]))
        counts = payload.get("counts") or {}
        details.update(
            {
                "advisory_files": int(counts.get("advisory_files", 0) or 0),
                "tuneable_keys": int(counts.get("tuneable_keys", 0) or 0),
                "distillation_files": int(counts.get("distillation_files", 0) or 0),
                "lib_jsonl_runtime_ext_refs": int(counts.get("lib_jsonl_runtime_ext_refs", 0) or 0),
                "report_json": str(payload.get("report_json") or ""),
                "report_md": str(payload.get("report_md") or ""),
            }
        )
    except Exception as exc:
        details["parse_error"] = str(exc)

    if strict:
        ok = ok and int(details.get("advisory_files", 10**9)) <= int(max_advisory_files)
        ok = ok and int(details.get("tuneable_keys", 10**9)) <= int(max_tuneable_keys)
        ok = ok and int(details.get("distillation_files", 10**9)) <= int(max_distillation_files)
        ok = ok and int(details.get("lib_jsonl_runtime_ext_refs", 10**9)) <= int(max_lib_jsonl_runtime_ext_refs)

    return StageResult(
        name="alpha_gap_audit",
        ok=ok,
        returncode=int(res["returncode"]),
        duration_s=float(res["duration_s"]),
        command=cmd,
        stdout=str(res["stdout"]),
        stderr=str(res["stderr"]),
        details=details,
    )


def _pytest_stage(*, strict: bool, timeout_s: int, targets: List[str]) -> StageResult:
    cmd = [sys.executable, "-m", "pytest", *targets, "-q"]
    res = _run_command(cmd, timeout_s=timeout_s)
    ok = res["returncode"] == 0
    stdout = str(res["stdout"])
    tail = ""
    lines = [line for line in stdout.splitlines() if line.strip()]
    if lines:
        tail = lines[-1].strip()
    if strict:
        ok = ok and ("passed" in stdout.lower())
    return StageResult(
        name="pytest_alpha_core",
        ok=ok,
        returncode=int(res["returncode"]),
        duration_s=float(res["duration_s"]),
        command=cmd,
        stdout=stdout,
        stderr=str(res["stderr"]),
        details={"targets": list(targets), "pytest_tail": tail},
    )


def _write_report(report: Dict[str, Any], *, out_dir: Path, run_id: str) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"alpha_start_readiness_{run_id}.json"
    md_path = out_dir / f"alpha_start_readiness_{run_id}.md"
    latest_json = out_dir / "alpha_start_readiness_latest.json"
    latest_md = out_dir / "alpha_start_readiness_latest.md"
    payload = json.dumps(report, indent=2, ensure_ascii=True)
    json_path.write_text(payload, encoding="utf-8")
    latest_json.write_text(payload, encoding="utf-8")
    rendered_md = _render_markdown(report)
    md_path.write_text(rendered_md, encoding="utf-8")
    latest_md.write_text(rendered_md, encoding="utf-8")
    return {
        "report_json": str(json_path),
        "report_md": str(md_path),
        "report_latest_json": str(latest_json),
        "report_latest_md": str(latest_md),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Spark Alpha start readiness checks.")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Directory for readiness artifacts.")
    ap.add_argument("--seeds", default="42,77", help="Replay evidence seeds CSV.")
    ap.add_argument("--episodes", default="8,20", help="Replay evidence episodes CSV.")
    ap.add_argument("--delta-rounds", type=int, default=2, help="Controlled-delta rounds.")
    ap.add_argument("--delta-label", default="alpha_start_smoke", help="Controlled-delta label prefix.")
    ap.add_argument(
        "--pytest-targets",
        default=",".join(DEFAULT_PYTEST_TARGETS),
        help="Comma-separated pytest targets for the alpha core regression slice.",
    )
    ap.add_argument("--timeout-s", type=int, default=1800, help="Per-stage timeout in seconds.")
    ap.add_argument("--strict", action="store_true", help="Enforce strict success thresholds for stage checks.")
    ap.add_argument("--emit-report", action="store_true", help="Write JSON/Markdown readiness report artifacts.")
    ap.add_argument(
        "--min-promotion-pass-rate",
        type=float,
        default=1.0,
        help="Strict replay minimum promotion pass rate [0..1].",
    )
    ap.add_argument(
        "--min-alpha-win-rate",
        type=float,
        default=1.0,
        help="Strict replay minimum alpha win rate [0..1].",
    )
    ap.add_argument(
        "--max-advisory-files",
        type=int,
        default=5,
        help="Strict alpha-gap max advisory module files.",
    )
    ap.add_argument(
        "--max-tuneable-keys",
        type=int,
        default=300,
        help="Strict alpha-gap max tuneable keys.",
    )
    ap.add_argument(
        "--max-distillation-files",
        type=int,
        default=3,
        help="Strict alpha-gap max distillation file count.",
    )
    ap.add_argument(
        "--max-lib-jsonl-runtime-ext-refs",
        type=int,
        default=200,
        help="Strict alpha-gap max runtime lib external .jsonl references.",
    )
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    replay_out_dir = out_dir / "replay_evidence"
    run_id = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    delta_out = out_dir / f"advisory_delta_{run_id}.json"
    pytest_targets = _parse_csv(args.pytest_targets)
    if not pytest_targets:
        pytest_targets = list(DEFAULT_PYTEST_TARGETS)

    stages: List[StageResult] = []
    stages.append(_production_stage(strict=bool(args.strict), timeout_s=int(args.timeout_s)))
    stages.append(
        _replay_stage(
            strict=bool(args.strict),
            timeout_s=int(args.timeout_s),
            seeds=str(args.seeds),
            episodes=str(args.episodes),
            out_dir=replay_out_dir,
            min_promotion_pass_rate=float(args.min_promotion_pass_rate),
            min_alpha_win_rate=float(args.min_alpha_win_rate),
        )
    )
    stages.append(
        _delta_stage(
            strict=bool(args.strict),
            timeout_s=int(args.timeout_s),
            out_path=delta_out,
            rounds=int(args.delta_rounds),
            label=f"{args.delta_label}_{run_id}",
        )
    )
    stages.append(
        _gap_stage(
            strict=bool(args.strict),
            timeout_s=int(args.timeout_s),
            max_advisory_files=int(args.max_advisory_files),
            max_tuneable_keys=int(args.max_tuneable_keys),
            max_distillation_files=int(args.max_distillation_files),
            max_lib_jsonl_runtime_ext_refs=int(args.max_lib_jsonl_runtime_ext_refs),
        )
    )
    stages.append(_pytest_stage(strict=bool(args.strict), timeout_s=int(args.timeout_s), targets=pytest_targets))

    stage_dicts = [stage.as_dict() for stage in stages]
    ready = all(bool(stage.get("ok")) for stage in stage_dicts)

    artifacts: Dict[str, str] = {
        "replay_out_dir": str(replay_out_dir),
        "delta_out": str(delta_out),
    }
    gap_details = (stage_dicts[3].get("details") or {}) if len(stage_dicts) > 3 else {}
    if gap_details.get("report_json"):
        artifacts["alpha_gap_report_json"] = str(gap_details.get("report_json"))
    if gap_details.get("report_md"):
        artifacts["alpha_gap_report_md"] = str(gap_details.get("report_md"))
    replay_details = (stage_dicts[1].get("details") or {}) if len(stage_dicts) > 1 else {}
    if replay_details.get("report_json"):
        artifacts["replay_report_json"] = str(replay_details.get("report_json"))
    if replay_details.get("report_md"):
        artifacts["replay_report_md"] = str(replay_details.get("report_md"))

    report: Dict[str, Any] = {
        "ok": True,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": run_id,
        "strict": bool(args.strict),
        "ready": bool(ready),
        "stages": stage_dicts,
        "artifacts": artifacts,
        "config": {
            "seeds": _parse_csv(str(args.seeds)),
            "episodes": _parse_csv(str(args.episodes)),
            "delta_rounds": int(args.delta_rounds),
            "min_promotion_pass_rate": float(args.min_promotion_pass_rate),
            "min_alpha_win_rate": float(args.min_alpha_win_rate),
            "max_advisory_files": int(args.max_advisory_files),
            "max_tuneable_keys": int(args.max_tuneable_keys),
            "max_distillation_files": int(args.max_distillation_files),
            "max_lib_jsonl_runtime_ext_refs": int(args.max_lib_jsonl_runtime_ext_refs),
            "pytest_targets_count": int(len(pytest_targets)),
        },
    }

    if args.emit_report:
        artifacts.update(_write_report(report, out_dir=out_dir, run_id=run_id))
        report["artifacts"] = artifacts

    print(
        json.dumps(
            {
                "ok": True,
                "ready": bool(ready),
                "run_id": run_id,
                "strict": bool(args.strict),
                "stages": [{k: v for k, v in s.items() if k in {"name", "ok", "returncode", "details"}} for s in stage_dicts],
                "report_json": artifacts.get("report_json", ""),
                "report_md": artifacts.get("report_md", ""),
            },
            indent=2,
        )
    )
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
