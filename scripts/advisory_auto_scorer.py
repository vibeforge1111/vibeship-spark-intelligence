#!/usr/bin/env python3
"""Advice-to-Action Auto-Scorer.

Builds per-advisory action/effect scores and session KPIs from existing Spark logs.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Dict, List

from lib.action_matcher import match_actions
from lib.advisory_parser import load_advisories
from lib.effect_evaluator import evaluate_effect
from lib.score_reporter import build_report, render_terminal_summary, write_report


def _dedupe_strs(values: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for v in values:
        s = str(v or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def run_autoscore(
    *,
    include_engine_fallback: bool,
    limit_requests: int,
    max_match_window_s: float,
    use_minimax: bool,
) -> Dict[str, Any]:
    del include_engine_fallback  # legacy parser fallback lane removed
    advisories = load_advisories(
        limit_requests=limit_requests,
    )
    matches = match_actions(
        advisories,
        max_match_window_s=max_match_window_s,
    )
    by_instance = {str(m.get("advisory_instance_id") or ""): m for m in matches}

    scored_items: List[Dict[str, Any]] = []
    for adv in advisories:
        instance_id = str(adv.get("advisory_instance_id") or "")
        match = by_instance.get(instance_id, {})
        eval_out = evaluate_effect(adv, match, use_minimax=use_minimax)
        confidence = float(eval_out.get("confidence") or match.get("confidence_hint") or 0.35)
        confidence = max(0.0, min(1.0, confidence))
        evidence_refs = _dedupe_strs(
            list(adv.get("evidence_refs") or []) + list(match.get("evidence_refs") or [])
        )
        scored_items.append(
            {
                "advisory_instance_id": instance_id,
                "advisory_id": str(adv.get("advisory_id") or ""),
                "recommendation": str(adv.get("recommendation") or ""),
                "status": str(match.get("status") or "unresolved"),
                "latency_s": match.get("latency_s"),
                "effect": str(eval_out.get("effect") or "neutral"),
                "confidence": round(confidence, 3),
                "evidence_refs": evidence_refs,
                "match_type": str(match.get("match_type") or "none"),
                "effect_reason": str(eval_out.get("reason") or ""),
                "created_at": float(adv.get("created_at") or 0.0),
                "session_id": str(adv.get("session_id") or ""),
                "tool": str(adv.get("tool") or ""),
                "route": str(adv.get("route") or ""),
                "source_kind": str(adv.get("source_kind") or ""),
                "source_file": str(adv.get("source_file") or ""),
            }
        )

    scored_items.sort(key=lambda x: float(x.get("created_at") or 0.0))
    return build_report(scored_items)


def main() -> int:
    ap = argparse.ArgumentParser(description="Score advisory->action conversion automatically.")
    ap.add_argument(
        "--include-engine-fallback",
        action="store_true",
        help="Deprecated no-op (legacy parser fallback path removed).",
    )
    ap.add_argument("--limit-requests", type=int, default=2000, help="Max request rows to parse.")
    ap.add_argument("--max-match-window-s", type=float, default=6 * 3600, help="Max seconds after advisory to consider action matches.")
    ap.add_argument("--use-minimax", action="store_true", help="Use MiniMax for ambiguous effect inference.")
    ap.add_argument("--output", type=Path, default=None, help="Output JSON path.")
    args = ap.parse_args()

    report = run_autoscore(
        include_engine_fallback=bool(args.include_engine_fallback),
        limit_requests=max(1, int(args.limit_requests)),
        max_match_window_s=max(0.0, float(args.max_match_window_s)),
        use_minimax=bool(args.use_minimax),
    )

    if args.output is None:
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        output = Path("reports") / f"advisory_auto_score_{ts}.json"
    else:
        output = Path(args.output)
    write_report(report, output)
    print(render_terminal_summary(report))
    print(f"report_path={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
