#!/usr/bin/env python3
"""Weekly strict-quality rollup for Spark x OpenClaw advisory telemetry."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

SPARK_DIR = Path.home() / ".spark"
REQUESTS_FILE = SPARK_DIR / "advice_feedback_requests.jsonl"
FEEDBACK_FILE = SPARK_DIR / "advice_feedback.jsonl"


def _tail_jsonl(path: Path, max_lines: int = 20000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines[-max(1, int(max_lines)) :]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _is_strict_row(row: Dict[str, Any]) -> bool:
    schema = int(row.get("schema_version") or 0)
    if schema < 2:
        return False
    return bool(
        str(row.get("trace_id") or "").strip()
        and str(row.get("run_id") or "").strip()
        and str(row.get("advisory_group_key") or "").strip()
    )


def _in_window(ts: float, now_ts: float, window_s: float) -> bool:
    return ts > 0 and (now_ts - ts) <= window_s


def build_rollup(
    *,
    now_ts: float,
    window_days: int,
    requests_file: Path,
    feedback_file: Path,
) -> Dict[str, Any]:
    window_s = max(1, int(window_days)) * 86400
    req_rows = _tail_jsonl(requests_file)
    fb_rows = _tail_jsonl(feedback_file)

    req_recent = [r for r in req_rows if _in_window(_safe_float(r.get("created_at")), now_ts, window_s)]
    fb_recent = [r for r in fb_rows if _in_window(_safe_float(r.get("created_at")), now_ts, window_s)]

    strict_req = [r for r in req_recent if _is_strict_row(r)]
    strict_fb = [r for r in fb_recent if _is_strict_row(r)]

    req_ratio = (len(strict_req) / len(req_recent)) if req_recent else 0.0
    fb_ratio = (len(strict_fb) / len(fb_recent)) if fb_recent else 0.0

    helpful = sum(1 for r in strict_fb if r.get("helpful") is True)
    followed = sum(1 for r in strict_fb if bool(r.get("followed")))
    acted = sum(1 for r in strict_fb if str(r.get("status") or "").strip().lower() == "acted")

    by_tool = Counter(str(r.get("tool") or "unknown") for r in strict_fb)
    by_session = Counter(str(r.get("session_kind") or "unknown") for r in strict_fb)
    by_source: Counter[str] = Counter()
    for r in strict_fb:
        sources = r.get("sources") or []
        if isinstance(sources, list) and sources:
            for src in sources:
                text = str(src or "").strip() or "unknown"
                by_source[text] += 1
        else:
            by_source["unknown"] += 1

    run_ids = {str(r.get("run_id")) for r in strict_req + strict_fb if str(r.get("run_id") or "").strip()}
    trace_ids = {str(r.get("trace_id")) for r in strict_req + strict_fb if str(r.get("trace_id") or "").strip()}
    group_keys = {
        str(r.get("advisory_group_key"))
        for r in strict_req + strict_fb
        if str(r.get("advisory_group_key") or "").strip()
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": int(window_days),
        "paths": {"requests_file": str(requests_file), "feedback_file": str(feedback_file)},
        "totals": {
            "requests_window": len(req_recent),
            "feedback_window": len(fb_recent),
            "strict_requests_window": len(strict_req),
            "strict_feedback_window": len(strict_fb),
            "strict_request_ratio": round(req_ratio, 4),
            "strict_feedback_ratio": round(fb_ratio, 4),
            "distinct_run_ids": len(run_ids),
            "distinct_trace_ids": len(trace_ids),
            "distinct_group_keys": len(group_keys),
        },
        "quality": {
            "helpful_rate": round((helpful / len(strict_fb)), 4) if strict_fb else 0.0,
            "followed_rate": round((followed / len(strict_fb)), 4) if strict_fb else 0.0,
            "acted_rate": round((acted / len(strict_fb)), 4) if strict_fb else 0.0,
        },
        "lineage_slices": {
            "by_source": dict(sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0]))),
            "by_tool": dict(sorted(by_tool.items(), key=lambda kv: (-kv[1], kv[0]))),
            "by_session_kind": dict(sorted(by_session.items(), key=lambda kv: (-kv[1], kv[0]))),
        },
    }


def render_markdown(report: Dict[str, Any]) -> str:
    totals = report.get("totals") or {}
    quality = report.get("quality") or {}
    slices = report.get("lineage_slices") or {}

    lines = [
        "# OpenClaw Strict Quality Rollup",
        "",
        f"- Generated: `{report.get('generated_at')}`",
        f"- Window: `{report.get('window_days')} days`",
        "",
        "## Coverage",
        "",
        f"- Requests in window: `{totals.get('requests_window', 0)}`",
        f"- Feedback in window: `{totals.get('feedback_window', 0)}`",
        f"- Strict request ratio: `{float(totals.get('strict_request_ratio', 0.0)):.2%}`",
        f"- Strict feedback ratio: `{float(totals.get('strict_feedback_ratio', 0.0)):.2%}`",
        "",
        "## Quality (strict rows)",
        "",
        f"- Helpful rate: `{float(quality.get('helpful_rate', 0.0)):.2%}`",
        f"- Followed rate: `{float(quality.get('followed_rate', 0.0)):.2%}`",
        f"- Acted rate: `{float(quality.get('acted_rate', 0.0)):.2%}`",
        "",
        "## Lineage Slices",
        "",
        "### By Source",
    ]
    for key, value in (slices.get("by_source") or {}).items():
        lines.append(f"- `{key}`: `{int(value)}`")
    lines.extend(["", "### By Tool"])
    for key, value in (slices.get("by_tool") or {}).items():
        lines.append(f"- `{key}`: `{int(value)}`")
    lines.extend(["", "### By Session Kind"])
    for key, value in (slices.get("by_session_kind") or {}).items():
        lines.append(f"- `{key}`: `{int(value)}`")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Strict rows require schema_version>=2 and non-empty trace_id/run_id/advisory_group_key.",
            "- Use this weekly report to monitor attribution integrity and lineage balance.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate weekly strict-quality lineage rollup.")
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--requests-file", type=Path, default=REQUESTS_FILE)
    ap.add_argument("--feedback-file", type=Path, default=FEEDBACK_FILE)
    ap.add_argument("--out-dir", type=Path, default=Path("docs") / "reports" / "openclaw")
    args = ap.parse_args()

    now_ts = time.time()
    report = build_rollup(
        now_ts=now_ts,
        window_days=int(args.window_days),
        requests_file=args.requests_file,
        feedback_file=args.feedback_file,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_path = args.out_dir / f"{stamp}_openclaw_strict_quality_rollup.json"
    md_path = args.out_dir / f"{stamp}_openclaw_strict_quality_rollup.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    print(f"[ok] wrote {json_path}")
    print(f"[ok] wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

