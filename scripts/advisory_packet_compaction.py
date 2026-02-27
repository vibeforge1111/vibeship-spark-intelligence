#!/usr/bin/env python3
"""Run advisory packet compaction preview/apply with explicit artifacts."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from lib import advisory_packet_store as packet_store
from lib.packet_compaction import build_packet_compaction_plan


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "benchmarks" / "out" / "packet_compaction"


def _meta_rows() -> List[Dict[str, Any]]:
    index = packet_store._load_index()  # noqa: SLF001 - script-level maintenance operation
    meta = index.get("packet_meta") or {}
    rows: List[Dict[str, Any]] = []
    if isinstance(meta, dict):
        for packet_id, raw in meta.items():
            row = dict(raw or {}) if isinstance(raw, dict) else {}
            row["packet_id"] = str(packet_id)
            rows.append(row)
    return rows


def _apply_plan(
    plan: Dict[str, Any],
    *,
    apply_limit: int,
    apply_updates: bool,
) -> Dict[str, Any]:
    candidates = list(plan.get("candidates") or [])
    remaining = max(0, int(apply_limit))
    deleted = 0
    updated = 0

    index = packet_store._load_index()  # noqa: SLF001
    meta = index.get("packet_meta") or {}
    touched_meta = False

    for row in candidates:
        if remaining <= 0:
            break
        action = str(row.get("action") or "").strip().lower()
        packet_id = str(row.get("packet_id") or "").strip()
        reason = str(row.get("reason") or "compaction").strip() or "compaction"
        if not packet_id:
            continue
        if action == "delete":
            ok = bool(packet_store.invalidate_packet(packet_id, reason=f"compaction:{reason}"))
            if ok:
                deleted += 1
                remaining -= 1
            continue
        if action == "update" and apply_updates:
            meta_row = meta.get(packet_id)
            if not isinstance(meta_row, dict):
                continue
            meta_row["compaction_flag"] = "review"
            meta_row["compaction_reason"] = reason
            meta_row["compaction_ts"] = float(time.time())
            updated += 1
            remaining -= 1
            touched_meta = True

    if touched_meta:
        packet_store._save_index(index)  # noqa: SLF001

    return {
        "applied_limit": int(apply_limit),
        "remaining_budget": int(remaining),
        "deleted": int(deleted),
        "updated": int(updated),
        "apply_updates": bool(apply_updates),
    }


def _render_markdown(report: Dict[str, Any], *, candidate_limit: int) -> str:
    plan = dict(report.get("plan") or {})
    summary = dict(plan.get("summary") or {})
    by_action = dict(summary.get("by_action") or {})
    candidates = list(plan.get("candidates") or [])
    applied = report.get("applied")

    lines = [
        "# Advisory Packet Compaction",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- mode: `{report.get('mode')}`",
        f"- total_candidates: `{summary.get('total', 0)}`",
        f"- delete_candidates: `{by_action.get('delete', 0)}`",
        f"- update_candidates: `{by_action.get('update', 0)}`",
        f"- noop_candidates: `{by_action.get('noop', 0)}`",
        "",
        "## Config",
        "",
        f"- stale_age_days: `{summary.get('stale_age_days', 0)}`",
        f"- low_effectiveness: `{summary.get('low_effectiveness', 0)}`",
        f"- review_age_days: `{summary.get('review_age_days', 0)}`",
        "",
    ]
    if isinstance(applied, dict):
        lines.extend(
            [
                "## Apply Result",
                "",
                f"- deleted: `{applied.get('deleted', 0)}`",
                f"- updated: `{applied.get('updated', 0)}`",
                f"- applied_limit: `{applied.get('applied_limit', 0)}`",
                f"- remaining_budget: `{applied.get('remaining_budget', 0)}`",
                f"- apply_updates: `{applied.get('apply_updates')}`",
                "",
            ]
        )

    lines.extend(
        [
            "## Top Candidates",
            "",
            "| packet_id | action | reason | stale | age_days | usage | effectiveness |",
            "|---|---|---|---|---:|---:|---:|",
        ]
    )
    for row in candidates[: max(1, int(candidate_limit))]:
        lines.append(
            f"| `{row.get('packet_id')}` | {row.get('action')} | {row.get('reason')} | "
            f"{row.get('stale')} | {row.get('age_days')} | {row.get('usage_count')} | {row.get('effectiveness_score')} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run advisory packet compaction preview/apply pass.")
    ap.add_argument("--stale-age-days", type=float, default=7.0, help="Min age in days for stale delete candidates.")
    ap.add_argument("--low-effectiveness", type=float, default=0.25, help="Effectiveness threshold for stale delete candidates.")
    ap.add_argument("--review-age-days", type=float, default=2.0, help="Min age for cold-packet review updates.")
    ap.add_argument("--apply", action="store_true", help="Apply compaction actions.")
    ap.add_argument("--apply-limit", type=int, default=40, help="Max number of apply actions in one run.")
    ap.add_argument("--apply-updates", action="store_true", help="Apply update actions (default apply only deletes).")
    ap.add_argument("--candidate-limit", type=int, default=80, help="Max candidate rows rendered in Markdown.")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory for report artifacts.")
    args = ap.parse_args()

    rows = _meta_rows()
    plan = build_packet_compaction_plan(
        rows,
        stale_age_days=float(args.stale_age_days),
        low_effectiveness=float(args.low_effectiveness),
        review_age_days=float(args.review_age_days),
    )

    applied = None
    mode = "preview"
    if bool(args.apply):
        mode = "apply"
        applied = _apply_plan(
            plan,
            apply_limit=int(args.apply_limit),
            apply_updates=bool(args.apply_updates),
        )

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": mode,
        "plan": plan,
        "applied": applied,
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    json_path = out_dir / f"advisory_packet_compaction_{run_id}.json"
    md_path = out_dir / f"advisory_packet_compaction_{run_id}.md"
    latest_json = out_dir / "advisory_packet_compaction_latest.json"
    latest_md = out_dir / "advisory_packet_compaction_latest.md"

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
                "mode": mode,
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

