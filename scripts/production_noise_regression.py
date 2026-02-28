#!/usr/bin/env python3
"""Run production-noise regression against live advisory content artifacts."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.advisory_content_quality import build_production_noise_report


def _fmt_pct(value: float) -> str:
    return f"{float(value) * 100.0:.1f}%"


def _build_markdown(report: Dict[str, Any], gates: Dict[str, Any], detail_limit: int) -> str:
    lines = [
        "# Production Noise Regression",
        "",
        f"- Generated at (epoch): `{report.get('generated_at', 0)}`",
        f"- Spark dir: `{report.get('spark_dir', '')}`",
        f"- Rows analyzed: `{report.get('rows_analyzed', 0)}`",
        "",
        "## Gate Summary",
        "",
        "| Gate | Value | Target | Pass |",
        "|------|-------|--------|------|",
    ]
    for gate in ("expected_noise_coverage_gate", "noise_recall_gate", "signal_fp_gate"):
        item = gates.get(gate) if isinstance(gates.get(gate), dict) else {}
        lines.append(
            f"| {gate} | {item.get('value', '-')} | {item.get('target', '-')} | {'yes' if item.get('ok') else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Core Metrics",
            "",
            f"- expected_noise_rows: `{report.get('expected_noise_rows', 0)}`",
            f"- expected_signal_rows: `{report.get('expected_signal_rows', 0)}`",
            f"- true_positive: `{report.get('true_positive', 0)}`",
            f"- false_negative: `{report.get('false_negative', 0)}`",
            f"- false_positive: `{report.get('false_positive', 0)}`",
            f"- recall: `{_fmt_pct(report.get('recall', 0.0))}`",
            f"- false_positive_rate: `{_fmt_pct(report.get('false_positive_rate', 0.0))}`",
            "",
            "## Hard Noise Signature Counts",
            "",
            "| Signature | Count |",
            "|-----------|------:|",
        ]
    )
    sig_counts = report.get("hard_noise_signature_counts") if isinstance(report.get("hard_noise_signature_counts"), dict) else {}
    if sig_counts:
        for key, value in sorted(sig_counts.items(), key=lambda item: int(item[1]), reverse=True):
            lines.append(f"| {key} | {int(value)} |")
    else:
        lines.append("| _none_ | 0 |")

    lines.extend(
        [
            "",
            f"## Detailed Rows (Latest {min(int(detail_limit), len(report.get('detailed_rows') or []))})",
            "",
            "| source | id | classifier | rule | hard_noise | hard_reason | expected_signal | snippet |",
            "|--------|----|------------|------|------------|-------------|-----------------|---------|",
        ]
    )
    detail_rows = report.get("detailed_rows") if isinstance(report.get("detailed_rows"), list) else []
    for row in detail_rows[: max(1, int(detail_limit))]:
        snippet = str(row.get("snippet") or "").replace("|", "\\|")
        lines.append(
            f"| {row.get('source', '?')} | {row.get('id', '?')} | "
            f"{'noise' if row.get('classifier_is_noise') else 'signal'} | {row.get('classifier_rule', 'none')} | "
            f"{'yes' if row.get('hard_noise') else 'no'} | {row.get('hard_noise_reason', '-')} | "
            f"{'yes' if row.get('expected_signal') else 'no'} | {snippet} |"
        )
    lines.append("")
    return "\n".join(lines)


def _gate_eval(
    *,
    report: Dict[str, Any],
    min_expected_noise_rows: int,
    min_recall: float,
    max_fp_rate: float,
) -> Dict[str, Any]:
    expected_noise = int(report.get("expected_noise_rows") or 0)
    recall = float(report.get("recall") or 0.0)
    fp_rate = float(report.get("false_positive_rate") or 0.0)
    coverage_ok = expected_noise >= max(1, int(min_expected_noise_rows))
    return {
        "expected_noise_coverage_gate": {
            "ok": bool(coverage_ok),
            "value": int(expected_noise),
            "target": f">={int(min_expected_noise_rows)}",
        },
        "noise_recall_gate": {
            "ok": bool(coverage_ok and (recall >= float(min_recall))),
            "value": round(recall, 4),
            "target": f">={float(min_recall):.2f}",
        },
        "signal_fp_gate": {
            "ok": bool(fp_rate <= float(max_fp_rate)),
            "value": round(fp_rate, 4),
            "target": f"<={float(max_fp_rate):.2f}",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run production noise regression against live advisory data.")
    ap.add_argument("--spark-dir", default=str(Path.home() / ".spark"), help="Spark runtime directory")
    ap.add_argument("--out-dir", default=str(ROOT / "reports" / "runtime"), help="Output directory")
    ap.add_argument("--max-rows-per-source", type=int, default=1200, help="Rows to load per source")
    ap.add_argument("--detail-rows", type=int, default=600, help="Detailed row count in output payload")
    ap.add_argument("--md-detail-rows", type=int, default=260, help="Detailed markdown rows to render")
    ap.add_argument("--min-expected-noise-rows", type=int, default=20, help="Minimum expected-noise rows for valid recall gate")
    ap.add_argument("--min-recall", type=float, default=0.90, help="Minimum acceptable hard-noise recall")
    ap.add_argument("--max-fp-rate", type=float, default=0.15, help="Maximum acceptable signal false-positive rate")
    args = ap.parse_args()

    spark_dir = Path(str(args.spark_dir)).expanduser()
    out_dir = Path(str(args.out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)

    report = build_production_noise_report(
        spark_dir=spark_dir,
        max_rows_per_source=max(50, int(args.max_rows_per_source)),
        detail_rows=max(80, int(args.detail_rows)),
    )
    gates = _gate_eval(
        report=report,
        min_expected_noise_rows=max(1, int(args.min_expected_noise_rows)),
        min_recall=float(args.min_recall),
        max_fp_rate=float(args.max_fp_rate),
    )
    passed = all(bool((gates.get(key) or {}).get("ok")) for key in gates)

    payload: Dict[str, Any] = {
        "generated_at": time.time(),
        "pass": bool(passed),
        "inputs": {
            "spark_dir": str(spark_dir),
            "max_rows_per_source": int(args.max_rows_per_source),
            "detail_rows": int(args.detail_rows),
            "md_detail_rows": int(args.md_detail_rows),
            "min_expected_noise_rows": int(args.min_expected_noise_rows),
            "min_recall": float(args.min_recall),
            "max_fp_rate": float(args.max_fp_rate),
        },
        "report": report,
        "gates": gates,
    }

    stamp = time.strftime("%Y-%m-%d_%H%M%S", time.gmtime())
    out_json = out_dir / f"{stamp}_production_noise_regression.json"
    out_md = out_dir / f"{stamp}_production_noise_regression.md"
    latest_json = out_dir / "production_noise_regression_latest.json"
    latest_md = out_dir / "production_noise_regression_latest.md"

    payload_text = json.dumps(payload, indent=2, ensure_ascii=False)
    out_json.write_text(payload_text, encoding="utf-8")
    latest_json.write_text(payload_text, encoding="utf-8")
    md_text = _build_markdown(payload["report"], gates, detail_limit=max(40, int(args.md_detail_rows)))
    out_md.write_text(md_text, encoding="utf-8")
    latest_md.write_text(md_text, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "pass": bool(passed),
                "gates": gates,
                "out_json": str(out_json),
                "latest_json": str(latest_json),
                "out_md": str(out_md),
                "latest_md": str(latest_md),
            },
            indent=2,
        )
    )
    return 0 if bool(passed) else 2


if __name__ == "__main__":
    raise SystemExit(main())
