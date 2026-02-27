"""Offline tuneables replay / suggestion harness.

This script is intentionally *safe by default*:
- It does NOT apply any changes unless you pass --apply.
- It produces a markdown report with current KPIs + tuning recommendations.

Why this exists
---------------
We want Carmack-style iteration: cheap measurement + small bounded knobs.
This harness pulls together:
- Carmack KPI scorecard (recent window)
- AutoTuner health + recommendations (suggest-only unless apply)
- Outcome predictor snapshot (risk keys)

Usage
-----
python scripts/tune_replay.py
python scripts/tune_replay.py --out reports/tune_replay_latest.md
python scripts/tune_replay.py --apply --mode moderate
python scripts/tune_replay.py --apply --mode moderate --apply-boosts

"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _format_pct(x: float) -> str:
    try:
        return f"{100.0 * float(x):.1f}%"
    except Exception:
        return "0.0%"


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _top_outcome_risks(limit: int = 10, min_samples: int = 5) -> List[Dict[str, Any]]:
    """Return top risky keys from outcome predictor store (if present)."""
    try:
        from lib.outcome_predictor import STORE_PATH, PRIOR_FAIL, PRIOR_SUCC

        store = _read_json(Path(STORE_PATH))
        keys = store.get("keys")
        if not isinstance(keys, dict):
            return []

        rows: List[Tuple[float, int, str, int, int]] = []
        for k, row in keys.items():
            if not isinstance(row, dict):
                continue
            succ = _safe_int(row.get("succ"), 0)
            fail = _safe_int(row.get("fail"), 0)
            n = succ + fail
            if n < int(min_samples):
                continue
            p_fail = (fail + float(PRIOR_FAIL)) / (n + float(PRIOR_FAIL) + float(PRIOR_SUCC))
            rows.append((float(p_fail), int(n), str(k), succ, fail))

        rows.sort(key=lambda t: (t[0], t[1]), reverse=True)
        out: List[Dict[str, Any]] = []
        for p_fail, n, k, succ, fail in rows[: max(0, int(limit))]:
            out.append({
                "key": k,
                "p_fail": round(float(p_fail), 4),
                "samples": int(n),
                "succ": int(succ),
                "fail": int(fail),
            })
        return out
    except Exception:
        return []


def run(*, apply: bool, apply_boosts: bool, mode: str, out_path: Path | None) -> Dict[str, Any]:
    from lib.auto_tuner import AutoTuner
    from lib.carmack_kpi import build_scorecard

    stamp = _utc_stamp()

    # --- KPI scorecard ---
    scorecard = {}
    try:
        scorecard = build_scorecard()
    except Exception as e:
        scorecard = {"error": str(e)}

    # --- Auto-tuner reports ---
    tuner = AutoTuner()
    health = None
    recs = []
    applied_recs = []
    boost_report = None
    try:
        health = tuner.measure_system_health()
        recs = tuner.compute_recommendations(health)
        applied_recs = tuner.apply_recommendations(recs, mode=mode if apply else "suggest")
    except Exception as e:
        recs = [{"error": str(e)}]

    try:
        # Safety: even when --apply is set, do NOT apply boost tuning unless
        # explicitly requested (boost tuning may touch many sources).
        boost_report = tuner.run(dry_run=not (apply and apply_boosts), force=True)
    except Exception as e:
        boost_report = {"error": str(e)}

    # --- Outcome predictor snapshot ---
    outcome_stats = {}
    top_risks: List[Dict[str, Any]] = []
    try:
        from lib.outcome_predictor import get_stats

        outcome_stats = get_stats()
        top_risks = _top_outcome_risks(limit=12, min_samples=5)
    except Exception as e:
        outcome_stats = {"error": str(e)}

    payload: Dict[str, Any] = {
        "generated_at": stamp,
        "apply": bool(apply),
        "apply_boosts": bool(apply_boosts),
        "mode": str(mode),
        "scorecard": scorecard,
        "auto_tuner": {
            "enabled": bool(getattr(tuner, "enabled", False)),
            "health": asdict(health) if health is not None else None,
            "recommendations": [asdict(r) for r in recs] if recs and hasattr(recs[0], "__dataclass_fields__") else recs,
            "applied_recommendations": [asdict(r) for r in applied_recs] if applied_recs and hasattr(applied_recs[0], "__dataclass_fields__") else applied_recs,
            "source_boost_report": getattr(boost_report, "summary", None) if boost_report is not None else None,
        },
        "outcome_predictor": {
            "stats": outcome_stats,
            "top_risks": top_risks,
        },
    }

    report_md = render_markdown(payload)
    if out_path:
        _write_text(out_path, report_md)

    return payload


def _md_json(obj: Any) -> str:
    return "```json\n" + json.dumps(obj, indent=2, ensure_ascii=False) + "\n```"


def render_markdown(payload: Dict[str, Any]) -> str:
    generated_at = payload.get("generated_at", "")
    apply = bool(payload.get("apply"))
    mode = payload.get("mode", "suggest")

    sc = payload.get("scorecard") or {}
    cur = (sc.get("current") or {}) if isinstance(sc, dict) else {}
    evt = cur.get("event_counts") or {}

    at = payload.get("auto_tuner") or {}
    health = at.get("health") or {}

    op = payload.get("outcome_predictor") or {}

    lines: List[str] = []
    lines.append(f"# Tune Replay Report\n\nGenerated: `{generated_at}`\n")
    lines.append(f"Mode: `{'APPLY' if apply else 'SUGGEST'}` (mode={mode}, apply_boosts={bool(payload.get('apply_boosts'))})\n")

    lines.append("## Carmack KPI (current window)\n")
    if "error" in sc:
        lines.append(f"- Error building scorecard: `{sc.get('error')}`\n")
    else:
        lines.append(f"- total_events: **{cur.get('total_events', 0)}**\n")
        lines.append(f"- emitted: **{cur.get('emitted', 0)}**\n")
        lines.append(f"- no_emit: **{cur.get('no_emit', 0)}**\n")
        lines.append(f"- noise_burden: **{cur.get('noise_burden', 0)}**\n")
        if evt:
            lines.append("\nEvent counts:\n")
            for k in sorted(evt.keys()):
                lines.append(f"- {k}: {evt[k]}")
            lines.append("")

    lines.append("## Auto-tuner health snapshot\n")
    if health:
        lines.append(f"- advice_action_rate: **{_format_pct(health.get('advice_action_rate', 0.0))}**")
        lines.append(f"- total_advice_given: **{health.get('total_advice_given', 0)}**")
        lines.append(f"- total_followed: **{health.get('total_followed', 0)}**")
        lines.append(f"- total_helpful: **{health.get('total_helpful', 0)}**")
        lines.append(f"- feedback_loop_closure: **{_format_pct(health.get('feedback_loop_closure', 0.0))}**")
        lines.append(f"- promotion_throughput (24h): **{health.get('promotion_throughput', 0)}**")
        lines.append(f"- top_sources: {', '.join(health.get('top_sources') or [])}")
        lines.append(f"- weak_sources: {', '.join(health.get('weak_sources') or [])}\n")
    else:
        lines.append("- (no health available)\n")

    recs = (at.get("recommendations") or [])
    lines.append("## Recommendations\n")
    if recs and isinstance(recs, list) and isinstance(recs[0], dict) and "error" in recs[0]:
        lines.append(f"- Error computing recommendations: `{recs[0].get('error')}`\n")
    elif not recs:
        lines.append("- No recommendations.\n")
    else:
        for r in recs:
            lines.append(
                f"- `{r.get('section')}.{r.get('key')}`: {r.get('current_value')} → {r.get('recommended_value')}"
                f" (conf={r.get('confidence')}, impact={r.get('impact')}) — {r.get('reason')}"
            )
        lines.append("")

    applied = (at.get("applied_recommendations") or [])
    lines.append("## Applied (if any)\n")
    if not apply:
        lines.append("- Not applied (suggest-only run).\n")
    elif not applied:
        lines.append("- No changes applied.\n")
    else:
        for r in applied:
            lines.append(
                f"- `{r.get('section')}.{r.get('key')}`: {r.get('current_value')} → {r.get('recommended_value')} — {r.get('reason')}"
            )
        lines.append("")

    lines.append("## Outcome predictor snapshot\n")
    lines.append(_md_json(op.get("stats") or {}))
    top_risks = op.get("top_risks") or []
    if top_risks:
        lines.append("\nTop risky keys (min_samples>=5):\n")
        for row in top_risks:
            lines.append(f"- {row.get('key')} | p_fail={row.get('p_fail')} n={row.get('samples')} (succ={row.get('succ')}, fail={row.get('fail')})")
        lines.append("")

    lines.append("\n---\n\nRaw payload:\n")
    lines.append(_md_json(payload))

    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="Spark offline tune replay / suggestion harness")
    p.add_argument("--out", default="", help="Write markdown report to this path")
    p.add_argument("--apply", action="store_true", help="Apply selected recommendations to tuneables.json")
    p.add_argument(
        "--apply-boosts",
        action="store_true",
        help="Also apply auto-tuner boost changes (may touch many sources). Off by default.",
    )
    p.add_argument(
        "--mode",
        default="conservative",
        choices=["suggest", "conservative", "moderate", "aggressive"],
        help="Apply mode for recommendations (ignored unless --apply). Default conservative.",
    )
    args = p.parse_args()

    out_path = Path(args.out) if args.out else None
    mode = str(args.mode or "conservative")

    payload = run(apply=bool(args.apply), apply_boosts=bool(args.apply_boosts), mode=mode, out_path=out_path)

    # Print a concise console summary.
    print(f"Generated: {payload.get('generated_at')}")
    print(f"Mode: {'APPLY' if args.apply else 'SUGGEST'} ({mode})")
    sc = payload.get("scorecard") or {}
    cur = (sc.get("current") or {}) if isinstance(sc, dict) else {}
    print(f"KPI total_events={cur.get('total_events', 0)} emitted={cur.get('emitted', 0)} noise_burden={cur.get('noise_burden', 0)}")

    recs = (payload.get("auto_tuner") or {}).get("recommendations") or []
    if isinstance(recs, list):
        print(f"Recommendations: {len(recs)}")

    if out_path:
        print(f"Wrote report: {out_path}")


if __name__ == "__main__":
    main()
