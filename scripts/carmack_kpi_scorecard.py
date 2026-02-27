#!/usr/bin/env python3
"""Print aligned Carmack KPI scorecard for recent Spark windows."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from lib.carmack_kpi import build_scorecard, build_health_alert


def _fmt_ratio(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def _fmt_delta(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:+.1f}pp"


def _parse_threshold_overrides(raw_items: list[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for raw in raw_items:
        token = str(raw or "").strip()
        if not token or "=" not in token:
            continue
        key, value = token.split("=", 1)
        key = key.strip()
        if not key:
            continue
        try:
            out[key] = float(value.strip())
        except Exception:
            continue
    return out


def _render_text(score: Dict[str, Any]) -> str:
    generated = datetime.fromtimestamp(float(score["generated_at"]), tz=timezone.utc).isoformat()
    rows = []
    rows.append(f"Carmack KPI Scorecard (generated {generated})")
    rows.append(f"Window: {score.get('window_hours')}h current vs previous")
    rows.append("")
    rows.append("KPI | Current | Previous | Delta | Trend")
    rows.append("--- | --- | --- | --- | ---")

    metrics = score.get("metrics") or {}
    gaur = metrics.get("gaur") or {}
    rows.append(
        "GAUR (schema_v2) | "
        f"{_fmt_ratio(gaur.get('current'))} | {_fmt_ratio(gaur.get('previous'))} | "
        f"{_fmt_delta(gaur.get('delta'))} | {gaur.get('trend', 'unknown')}"
    )

    gaur_all = metrics.get("gaur_all") or {}
    rows.append(
        "GAUR (all) | "
        f"{_fmt_ratio(gaur_all.get('current'))} | {_fmt_ratio(gaur_all.get('previous'))} | "
        f"{_fmt_delta(gaur_all.get('delta'))} | {gaur_all.get('trend', 'unknown')}"
    )

    nb = metrics.get("noise_burden") or {}
    rows.append(
        "Noise Burden | "
        f"{_fmt_ratio(nb.get('current'))} | {_fmt_ratio(nb.get('previous'))} | "
        f"{_fmt_delta(nb.get('delta'))} | {nb.get('trend', 'unknown')}"
    )

    cr = metrics.get("core_reliability") or {}
    rows.append(
        "Core Reliability | "
        f"{_fmt_ratio(cr.get('current'))} | {_fmt_ratio(cr.get('previous'))} | "
        f"{_fmt_delta(cr.get('delta'))} | {cr.get('trend', 'unknown')}"
    )

    fsv2 = metrics.get("feedback_schema_v2_ratio") or {}
    rows.append(
        "Feedback schema_v2 ratio | "
        f"{_fmt_ratio(fsv2.get('current'))} | {_fmt_ratio(fsv2.get('previous'))} | "
        f"{_fmt_delta(fsv2.get('delta'))} | {fsv2.get('trend', 'unknown')}"
    )

    current = score.get("current") or {}
    rows.append("")
    rows.append(
        "Current window raw: "
        f"events={current.get('total_events', 0)}, delivered_calls={current.get('delivered', 0)}, "
        f"emitted_items={current.get('emitted_advice_items', 0)}, "
        f"emitted_items_schema_v2={current.get('emitted_advice_items_schema_v2', 0)}, "
        f"good_used={current.get('good_advice_used', 0)}, "
        f"good_used_schema_v2={current.get('good_advice_used_schema_v2', 0)}"
    )
    rows.append(
        "Feedback rows: "
        f"total={current.get('feedback_rows_total', 0)}, "
        f"schema_v2={current.get('feedback_rows_schema_v2', 0)}, "
        f"legacy={current.get('feedback_rows_legacy', 0)}, "
        f"quality_gate_ready={bool(current.get('quality_gate_ready', False))}"
    )
    core = score.get("core") or {}
    rows.append(
        f"Core services running: {core.get('core_running', 0)}/{core.get('core_total', 0)}"
    )
    return "\n".join(rows)


def _has_breach_kind(alert: Dict[str, Any], kinds: set[str]) -> bool:
    for row in list(alert.get("breaches") or []):
        if str(row.get("kind") or "") in kinds:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute aligned Carmack KPI scorecard.")
    ap.add_argument("--window-hours", type=float, default=4.0, help="Window size in hours.")
    ap.add_argument("--json", action="store_true", help="Print scorecard JSON only.")
    ap.add_argument("--alert-json", action="store_true", help="Print health-alert summary JSON.")
    ap.add_argument(
        "--threshold",
        action="append",
        default=[],
        help="Override alert threshold as key=value (repeatable)",
    )
    ap.add_argument(
        "--fail-on-breach",
        action="store_true",
        help="Exit non-zero when alert status is breach (for cron/webhook gating).",
    )
    ap.add_argument(
        "--confirm-seconds",
        type=int,
        default=0,
        help="If breached, recheck after N seconds before declaring final breach.",
    )
    ap.add_argument(
        "--auto-remediate-core",
        action="store_true",
        help="If still breached after confirm, run service ensure/recheck for core-flow breaches.",
    )
    ap.add_argument(
        "--remediate-on",
        default="core_reliability_low,bridge_heartbeat_stale",
        help="Comma-separated breach kinds eligible for auto-remediation.",
    )
    args = ap.parse_args()

    score = build_scorecard(window_hours=args.window_hours)
    threshold_overrides = _parse_threshold_overrides(args.threshold or [])

    if args.alert_json:
        alert = build_health_alert(score, thresholds=threshold_overrides)
        # False-breach guard: confirm once after a short delay.
        if str(alert.get("status")) == "breach" and int(args.confirm_seconds or 0) > 0:
            time.sleep(max(0, int(args.confirm_seconds)))
            score_confirm = build_scorecard(window_hours=args.window_hours)
            alert_confirm = build_health_alert(score_confirm, thresholds=threshold_overrides)
            alert = {
                **alert_confirm,
                "precheck": {
                    "status": str(alert.get("status") or ""),
                    "breach_count": int(alert.get("breach_count") or 0),
                },
                "confirmed": True,
            }

        # Optional auto-remediation for persistent core-flow breaches.
        if str(alert.get("status")) == "breach" and args.auto_remediate_core:
            requested = {
                x.strip()
                for x in str(args.remediate_on or "").split(",")
                if x.strip()
            }
            if _has_breach_kind(alert, requested):
                from lib.service_control import ensure_services

                remediation = ensure_services()
                time.sleep(8)
                score_post = build_scorecard(window_hours=args.window_hours)
                alert_post = build_health_alert(score_post, thresholds=threshold_overrides)
                alert = {
                    **alert_post,
                    "auto_remediation": {
                        "applied": True,
                        "requested_kinds": sorted(requested),
                        "service_actions": remediation,
                    },
                }

        print(json.dumps(alert, indent=2))
        if args.fail_on_breach and str(alert.get("status")) == "breach":
            return 2
        return 0

    if args.json:
        print(json.dumps(score, indent=2))
        return 0

    print(_render_text(score))
    if args.fail_on_breach:
        alert = build_health_alert(score, thresholds=threshold_overrides)
        if str(alert.get("status")) == "breach":
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
