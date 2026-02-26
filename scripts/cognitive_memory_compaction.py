#!/usr/bin/env python3
"""Run a compact cognitive-memory compaction pass with explicit artifacts."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from lib.cognitive_learner import get_cognitive_learner
from lib.memory_compaction import build_compaction_plan


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "benchmarks" / "out" / "memory_compaction"


def _rows_from_learner() -> List[Dict[str, Any]]:
    learner = get_cognitive_learner()
    rows: List[Dict[str, Any]] = []
    for key, insight in learner.insights.items():
        category = getattr(getattr(insight, "category", None), "value", "")
        rows.append(
            {
                "key": str(key),
                "insight": str(getattr(insight, "insight", "") or ""),
                "category": str(category or "general"),
                "reliability": float(getattr(insight, "reliability", 0.0) or 0.0),
                "created_at": str(getattr(insight, "created_at", "") or ""),
                "last_validated_at": str(getattr(insight, "last_validated_at", "") or ""),
            }
        )
    return rows


def _apply_compaction(*, max_age_days: float, min_activation: float) -> Dict[str, Any]:
    learner = get_cognitive_learner()
    signal_merged = learner.dedupe_signals()
    struggle_merged = learner.dedupe_struggles()
    pruned = int(learner.prune_stale(max_age_days=max_age_days, min_effective=min_activation))
    wisdom = learner.promote_to_wisdom()

    signal_removed = int(sum(max(0, int(count) - 1) for count in signal_merged.values()))
    struggle_removed = int(sum(max(0, int(count) - 1) for count in struggle_merged.values()))
    wisdom_promoted = int((wisdom or {}).get("promoted", 0) or 0)

    return {
        "signal_merge_groups": int(len(signal_merged)),
        "struggle_merge_groups": int(len(struggle_merged)),
        "signal_removed": signal_removed,
        "struggle_removed": struggle_removed,
        "pruned": pruned,
        "wisdom_promoted": wisdom_promoted,
        "mem0_actions": {
            "add": 0,
            "update": int(signal_removed + struggle_removed + wisdom_promoted),
            "delete": int(pruned),
            "noop": 0,
        },
    }


def _render_markdown(report: Dict[str, Any], *, candidate_limit: int) -> str:
    summary = dict((report.get("plan") or {}).get("summary") or {})
    candidates = list((report.get("plan") or {}).get("candidates") or [])
    applied = report.get("applied")

    lines = [
        "# Cognitive Memory Compaction",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- mode: `{'apply' if bool(applied) else 'preview'}`",
        f"- total_candidates: `{summary.get('total', 0)}`",
        f"- delete_candidates: `{(summary.get('by_action') or {}).get('delete', 0)}`",
        f"- update_candidates: `{(summary.get('by_action') or {}).get('update', 0)}`",
        f"- noop_candidates: `{(summary.get('by_action') or {}).get('noop', 0)}`",
        "",
        "## Plan Summary",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    for field in ("total", "duplicate_groups", "delete_ratio", "max_age_days", "min_activation"):
        lines.append(f"| {field} | {summary.get(field, 0)} |")

    by_action = dict(summary.get("by_action") or {})
    lines.extend(
        [
            "",
            "## Actions (Preview)",
            "",
            "| Action | Count |",
            "|---|---:|",
            f"| delete | {by_action.get('delete', 0)} |",
            f"| update | {by_action.get('update', 0)} |",
            f"| noop | {by_action.get('noop', 0)} |",
        ]
    )
    if isinstance(applied, dict):
        lines.extend(
            [
                "",
                "## Apply Result",
                "",
                f"- signal_merge_groups: `{applied.get('signal_merge_groups', 0)}`",
                f"- struggle_merge_groups: `{applied.get('struggle_merge_groups', 0)}`",
                f"- signal_removed: `{applied.get('signal_removed', 0)}`",
                f"- struggle_removed: `{applied.get('struggle_removed', 0)}`",
                f"- pruned: `{applied.get('pruned', 0)}`",
                f"- wisdom_promoted: `{applied.get('wisdom_promoted', 0)}`",
                "",
            ]
        )

    lines.extend(
        [
            "## Top Candidates",
            "",
            "| Key | Action | Reason | Age (days) | Activation |",
            "|---|---|---|---:|---:|",
        ]
    )
    for row in candidates[: max(1, int(candidate_limit))]:
        lines.append(
            f"| `{row.get('key')}` | {row.get('action')} | {row.get('reason')} | "
            f"{row.get('age_days')} | {row.get('activation')} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run cognitive memory compaction preview/apply pass.")
    ap.add_argument("--max-age-days", type=float, default=180.0, help="Stale age threshold for delete candidates.")
    ap.add_argument("--min-activation", type=float, default=0.20, help="Minimum ACT-R style activation for stale rows.")
    ap.add_argument("--apply", action="store_true", help="Apply compaction actions (dedupe/prune/promote).")
    ap.add_argument("--candidate-limit", type=int, default=80, help="Max candidate rows rendered in Markdown.")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory for reports.")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = _rows_from_learner()
    plan = build_compaction_plan(
        rows,
        max_age_days=float(args.max_age_days),
        min_activation=float(args.min_activation),
    )
    applied = None
    if bool(args.apply):
        applied = _apply_compaction(
            max_age_days=float(args.max_age_days),
            min_activation=float(args.min_activation),
        )
        if isinstance(applied, dict) and "mem0_actions" in applied:
            by_action = dict((plan.get("summary") or {}).get("by_action") or {})
            mem0 = dict(applied.get("mem0_actions") or {})
            known = int(mem0.get("update", 0) + mem0.get("delete", 0))
            mem0["noop"] = max(0, int((plan.get("summary") or {}).get("total", 0) - known)
            )
            applied["mem0_actions"] = mem0

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "apply" if bool(args.apply) else "preview",
        "plan": plan,
        "applied": applied,
    }

    run_id = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    json_path = out_dir / f"cognitive_memory_compaction_{run_id}.json"
    md_path = out_dir / f"cognitive_memory_compaction_{run_id}.md"
    latest_json = out_dir / "cognitive_memory_compaction_latest.json"
    latest_md = out_dir / "cognitive_memory_compaction_latest.md"

    payload = json.dumps(report, indent=2, ensure_ascii=True)
    json_path.write_text(payload, encoding="utf-8")
    latest_json.write_text(payload, encoding="utf-8")
    rendered_md = _render_markdown(report, candidate_limit=int(args.candidate_limit))
    md_path.write_text(rendered_md, encoding="utf-8")
    latest_md.write_text(rendered_md, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "mode": report["mode"],
                "total": int((plan.get("summary") or {}).get("total", 0)),
                "delete_candidates": int(((plan.get("summary") or {}).get("by_action") or {}).get("delete", 0)),
                "update_candidates": int(((plan.get("summary") or {}).get("by_action") or {}).get("update", 0)),
                "report_json": str(json_path),
                "report_md": str(md_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

