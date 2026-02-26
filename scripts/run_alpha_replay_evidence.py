#!/usr/bin/env python3
"""Batch runner for Spark alpha replay evidence.

Runs deterministic replay arena across multiple seeds/episode windows and writes
an aggregated evidence summary for PR-07 cutover decisions.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "benchmarks" / "out" / "replay_arena"
ARENA_SCRIPT = ROOT / "scripts" / "spark_alpha_replay_arena.py"


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
    deduped = []
    seen = set()
    for value in out:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _run_arena(*, seed: int, episodes: int, out_dir: Path) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(ARENA_SCRIPT),
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
            f"replay arena failed (seed={seed}, episodes={episodes}, rc={proc.returncode}): "
            f"{(proc.stderr or '').strip() or 'no stderr'}"
        )
    body = str(proc.stdout or "").strip()
    if not body:
        raise RuntimeError(f"replay arena returned empty stdout (seed={seed}, episodes={episodes})")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise RuntimeError(f"replay arena stdout is not an object (seed={seed}, episodes={episodes})")
    payload["seed"] = int(seed)
    payload["episodes"] = int(episodes)
    return payload


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(float(count) / float(total), 4)


def _render_markdown(summary: Dict[str, Any]) -> str:
    totals = summary.get("totals") or {}
    combos = summary.get("combinations") or []
    lines = [
        "# Spark Alpha Replay Evidence Batch",
        "",
        f"- generated_at: `{summary.get('generated_at')}`",
        f"- runs: `{totals.get('runs', 0)}`",
        f"- alpha_win_rate: `{totals.get('alpha_win_rate', 0.0)}`",
        f"- promotion_pass_rate: `{totals.get('promotion_pass_rate', 0.0)}`",
        f"- cutover_eligible_runs: `{totals.get('eligible_runs', 0)}`",
        "",
        "## Run Matrix",
        "",
        "| seed | episodes | winner | promotion_gate_pass | streak | eligible_for_cutover | report |",
        "|---:|---:|---|---:|---:|---:|---|",
    ]
    for row in combos:
        lines.append(
            "| {seed} | {episodes} | {winner} | {promotion_gate_pass} | {streak} | {eligible_for_cutover} | `{report_json}` |".format(
                seed=row.get("seed"),
                episodes=row.get("episodes"),
                winner=row.get("winner"),
                promotion_gate_pass=row.get("promotion_gate_pass"),
                streak=row.get("consecutive_pass_streak"),
                eligible_for_cutover=row.get("eligible_for_cutover"),
                report_json=row.get("report_json"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _build_summary(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    combos = list(rows)
    runs = len(combos)
    alpha_wins = sum(1 for row in combos if str(row.get("winner") or "") == "alpha")
    promotion_passes = sum(1 for row in combos if bool(row.get("promotion_gate_pass")))
    eligible_runs = sum(1 for row in combos if bool(row.get("eligible_for_cutover")))
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "totals": {
            "runs": runs,
            "alpha_wins": alpha_wins,
            "promotion_passes": promotion_passes,
            "eligible_runs": eligible_runs,
            "alpha_win_rate": _rate(alpha_wins, runs),
            "promotion_pass_rate": _rate(promotion_passes, runs),
        },
        "combinations": combos,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run replay arena across seed/episode combinations.")
    ap.add_argument("--seeds", default="42,77,101", help="Comma-separated deterministic seeds.")
    ap.add_argument("--episodes", default="60,120,180", help="Comma-separated episode counts.")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Replay output directory.")
    ap.add_argument(
        "--require-promotion-pass-rate",
        type=float,
        default=0.0,
        help="Fail if aggregated promotion_pass_rate is below this [0..1] threshold.",
    )
    args = ap.parse_args()

    seeds = _parse_int_csv(args.seeds, minimum=1)
    episode_counts = _parse_int_csv(args.episodes, minimum=1)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    for seed in seeds:
        for episodes in episode_counts:
            rows.append(_run_arena(seed=seed, episodes=episodes, out_dir=out_dir))

    summary = _build_summary(rows)
    run_id = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    json_path = out_dir / f"spark_alpha_replay_evidence_{run_id}.json"
    md_path = out_dir / f"spark_alpha_replay_evidence_{run_id}.md"
    latest_json = out_dir / "spark_alpha_replay_evidence_latest.json"
    latest_md = out_dir / "spark_alpha_replay_evidence_latest.md"

    payload = json.dumps(summary, indent=2, ensure_ascii=True)
    json_path.write_text(payload, encoding="utf-8")
    latest_json.write_text(payload, encoding="utf-8")
    rendered_md = _render_markdown(summary)
    md_path.write_text(rendered_md, encoding="utf-8")
    latest_md.write_text(rendered_md, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "runs": int((summary.get("totals") or {}).get("runs", 0)),
                "alpha_win_rate": float((summary.get("totals") or {}).get("alpha_win_rate", 0.0)),
                "promotion_pass_rate": float((summary.get("totals") or {}).get("promotion_pass_rate", 0.0)),
                "report_json": str(json_path),
                "report_md": str(md_path),
            },
            indent=2,
        )
    )

    required = max(0.0, min(1.0, float(args.require_promotion_pass_rate or 0.0)))
    actual = float((summary.get("totals") or {}).get("promotion_pass_rate", 0.0))
    if actual < required:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

