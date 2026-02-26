#!/usr/bin/env python3
"""Codex hook bridge observability report.

Reads codex_hook_bridge telemetry, evaluates rollout gates, and publishes:
- _observatory/codex_hooks_snapshot.json
- _observatory/codex_hooks.md
- docs/reports/<date>_codex_hooks.md
- <ObsidianVault>/_observatory/codex_hooks.md
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from lib.observatory.config import load_config


SPARK_DIR = Path.home() / ".spark"
TELEMETRY_FILE = SPARK_DIR / "logs" / "codex_hook_bridge_telemetry.jsonl"
LOCAL_OBSERVATORY_DIR = Path("_observatory")
REPORTS_DIR = Path("docs") / "reports"

GATE_THRESHOLDS = {
    "coverage_ratio_min": 0.90,
    "pairing_ratio_min": 0.90,
    "unknown_exit_ratio_max": 0.15,
    "json_decode_errors_delta_max": 0,
    "post_unmatched_delta_max": 0,
    "observe_success_ratio_min": 0.98,
    "observe_latency_p95_ms_max": 2500.0,
}

COUNTER_KEYS = (
    "rows_seen",
    "json_decode_errors",
    "relevant_rows",
    "mapped_events",
    "pre_events",
    "post_events",
    "post_success",
    "post_failure",
    "post_unknown_exit",
    "post_unmatched_call_id",
    "observe_calls",
    "observe_success",
    "observe_failures",
    "pre_input_truncated",
    "post_output_truncated",
)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_ratio(numer: float, denom: float) -> float:
    if denom <= 0:
        return 0.0
    return float(numer) / float(denom)


def _metric_delta(first: Dict[str, Any], last: Dict[str, Any], key: str) -> int:
    start = _to_int(first.get(key), 0)
    end = _to_int(last.get(key), 0)
    if end >= start:
        return end - start
    # Counter reset/restart case.
    return end


def summarize_telemetry(
    rows: List[Dict[str, Any]],
    *,
    window_minutes: int = 60,
    now_ts: float | None = None,
) -> Dict[str, Any]:
    if not rows:
        return {
            "available": False,
            "reason": "no_rows",
            "window_minutes": int(window_minutes),
        }

    rows_sorted = sorted(rows, key=lambda r: _to_float(r.get("ts"), 0.0))
    if now_ts is None:
        now_ts = _to_float(rows_sorted[-1].get("ts"), time.time())
    cutoff = now_ts - max(1, int(window_minutes)) * 60.0
    window_rows = [r for r in rows_sorted if _to_float(r.get("ts"), 0.0) >= cutoff]
    if not window_rows:
        window_rows = [rows_sorted[-1]]

    first = window_rows[0]
    last = window_rows[-1]
    first_metrics = first.get("metrics") if isinstance(first.get("metrics"), dict) else {}
    last_metrics = last.get("metrics") if isinstance(last.get("metrics"), dict) else {}

    deltas = {k: _metric_delta(first_metrics, last_metrics, k) for k in COUNTER_KEYS}
    post_events = max(0, deltas.get("post_events", 0))
    unknown_exit = max(0, deltas.get("post_unknown_exit", 0))
    unmatched = max(0, deltas.get("post_unmatched_call_id", 0))
    observe_calls = max(0, deltas.get("observe_calls", 0))
    observe_success = max(0, deltas.get("observe_success", 0))
    latest_post_events = max(0, _to_int(last_metrics.get("post_events"), 0))
    latest_unknown_exit = max(0, _to_int(last_metrics.get("post_unknown_exit"), 0))
    latest_unmatched = max(0, _to_int(last_metrics.get("post_unmatched_call_id"), 0))
    latest_observe_calls = max(0, _to_int(last_metrics.get("observe_calls"), 0))
    latest_observe_success = max(0, _to_int(last_metrics.get("observe_success"), 0))
    latest_pre_events = max(0, _to_int(last_metrics.get("pre_events"), 0))
    latest_mapped_events = max(0, _to_int(last_metrics.get("mapped_events"), 0))
    latest_post_output_truncated = max(0, _to_int(last_metrics.get("post_output_truncated"), 0))

    delta_pre_events = max(0, deltas.get("pre_events", 0))
    delta_mapped_events = max(0, deltas.get("mapped_events", 0))
    delta_post_output_truncated = max(0, deltas.get("post_output_truncated", 0))

    coverage_ratio = _to_float(last_metrics.get("coverage_ratio"), 0.0)
    pairing_ratio = _to_float(last_metrics.get("pairing_ratio"), 0.0)
    observe_latency_p95_ms = _to_float(last_metrics.get("observe_latency_p95_ms"), 0.0)

    if coverage_ratio <= 0 and deltas.get("relevant_rows", 0) > 0:
        coverage_ratio = _safe_ratio(deltas.get("mapped_events", 0), deltas.get("relevant_rows", 1))
    if pairing_ratio <= 0 and post_events > 0:
        pairing_ratio = _safe_ratio(post_events - unmatched, post_events)

    if post_events > 0:
        unknown_exit_ratio = _safe_ratio(unknown_exit, post_events)
        post_unmatched_ratio = _safe_ratio(unmatched, post_events)
        post_ratio_basis = "window_delta"
    else:
        unknown_exit_ratio = _safe_ratio(latest_unknown_exit, latest_post_events)
        post_unmatched_ratio = _safe_ratio(latest_unmatched, latest_post_events)
        post_ratio_basis = "latest_snapshot"

    if observe_calls > 0:
        observe_success_ratio_window = _safe_ratio(observe_success, observe_calls)
        observe_ratio_basis = "window_delta"
    else:
        observe_success_ratio_window = _safe_ratio(latest_observe_success, latest_observe_calls)
        observe_ratio_basis = "latest_snapshot"

    if delta_mapped_events > 0:
        workflow_event_ratio = _safe_ratio(delta_pre_events + post_events, delta_mapped_events)
        workflow_ratio_basis = "window_delta"
    else:
        workflow_event_ratio = _safe_ratio(latest_pre_events + latest_post_events, latest_mapped_events)
        workflow_ratio_basis = "latest_snapshot"

    if delta_pre_events > 0:
        tool_result_capture_rate = _safe_ratio(post_events, delta_pre_events)
        capture_ratio_basis = "window_delta"
    else:
        tool_result_capture_rate = _safe_ratio(latest_post_events, latest_pre_events)
        capture_ratio_basis = "latest_snapshot"

    if post_events > 0:
        truncated_tool_result_ratio = _safe_ratio(delta_post_output_truncated, post_events)
        truncation_ratio_basis = "window_delta"
    else:
        truncated_tool_result_ratio = _safe_ratio(latest_post_output_truncated, latest_post_events)
        truncation_ratio_basis = "latest_snapshot"

    total_rows = max(1, len(window_rows))
    mode_shadow_ratio = _safe_ratio(sum(1 for r in window_rows if str(r.get("mode") or "") == "shadow"), total_rows)
    observe_forwarding_enabled_ratio = _safe_ratio(
        sum(1 for r in window_rows if bool(r.get("observe_forwarding_enabled"))),
        total_rows,
    )

    summary = {
        "available": True,
        "mode": str(last.get("mode") or "unknown"),
        "active_files": _to_int(last.get("active_files"), 0),
        "pending_calls": _to_int(last.get("pending_calls"), 0),
        "latest_ts": _to_float(last.get("ts"), 0.0),
        "window_minutes": int(window_minutes),
        "window_rows": len(window_rows),
        "latest_metrics": last_metrics,
        "delta_metrics": deltas,
        "derived": {
            "coverage_ratio": round(float(coverage_ratio), 4),
            "pairing_ratio": round(float(pairing_ratio), 4),
            "unknown_exit_ratio": round(float(unknown_exit_ratio), 4),
            "post_unmatched_ratio": round(float(post_unmatched_ratio), 4),
            "observe_success_ratio_window": round(float(observe_success_ratio_window), 4),
            "observe_latency_p95_ms": round(float(observe_latency_p95_ms), 2),
            "workflow_event_ratio": round(float(workflow_event_ratio), 4),
            "workflow_ratio_basis": workflow_ratio_basis,
            "tool_result_capture_rate": round(float(tool_result_capture_rate), 4),
            "capture_ratio_basis": capture_ratio_basis,
            "truncated_tool_result_ratio": round(float(truncated_tool_result_ratio), 4),
            "truncation_ratio_basis": truncation_ratio_basis,
            "mode_shadow_ratio": round(float(mode_shadow_ratio), 4),
            "observe_forwarding_enabled_ratio": round(float(observe_forwarding_enabled_ratio), 4),
            "post_ratio_basis": post_ratio_basis,
            "observe_ratio_basis": observe_ratio_basis,
            "window_activity_rows": _to_int(deltas.get("rows_seen"), 0),
        },
    }
    return summary


def evaluate_gates(summary: Dict[str, Any]) -> Dict[str, Any]:
    if not summary.get("available"):
        return {"passing": False, "failed_count": 1, "checks": [{"name": "telemetry.available", "pass": False}]}

    derived = summary.get("derived") if isinstance(summary.get("derived"), dict) else {}
    delta = summary.get("delta_metrics") if isinstance(summary.get("delta_metrics"), dict) else {}
    mode = str(summary.get("mode") or "unknown")
    pending_calls = _to_int(summary.get("pending_calls"), 0)

    checks: List[Dict[str, Any]] = []

    def _add_check(name: str, actual: float, expect: str, passed: bool, required: bool = True) -> None:
        checks.append(
            {
                "name": name,
                "actual": round(float(actual), 4),
                "expectation": expect,
                "pass": bool(passed),
                "required": bool(required),
            }
        )

    coverage = _to_float(derived.get("coverage_ratio"), 0.0)
    pairing = _to_float(derived.get("pairing_ratio"), 0.0)
    unknown_exit_ratio = _to_float(derived.get("unknown_exit_ratio"), 0.0)
    json_decode_delta = _to_int(delta.get("json_decode_errors"), 0)
    post_unmatched_delta = _to_int(delta.get("post_unmatched_call_id"), 0)
    pairing_required = pending_calls <= 0

    _add_check(
        "shadow.coverage_ratio",
        coverage,
        f">= {GATE_THRESHOLDS['coverage_ratio_min']}",
        coverage >= GATE_THRESHOLDS["coverage_ratio_min"],
    )
    _add_check(
        "shadow.pairing_ratio",
        pairing,
        (
            f">= {GATE_THRESHOLDS['pairing_ratio_min']}"
            if pairing_required
            else f">= {GATE_THRESHOLDS['pairing_ratio_min']} (after pending calls drain)"
        ),
        pairing >= GATE_THRESHOLDS["pairing_ratio_min"],
        required=pairing_required,
    )
    _add_check(
        "shadow.unknown_exit_ratio",
        unknown_exit_ratio,
        f"<= {GATE_THRESHOLDS['unknown_exit_ratio_max']}",
        unknown_exit_ratio <= GATE_THRESHOLDS["unknown_exit_ratio_max"],
    )
    _add_check(
        "shadow.json_decode_errors_delta",
        json_decode_delta,
        f"<= {GATE_THRESHOLDS['json_decode_errors_delta_max']}",
        json_decode_delta <= GATE_THRESHOLDS["json_decode_errors_delta_max"],
    )
    _add_check(
        "shadow.post_unmatched_delta",
        post_unmatched_delta,
        (
            f"<= {GATE_THRESHOLDS['post_unmatched_delta_max']}"
            if pairing_required
            else f"<= {GATE_THRESHOLDS['post_unmatched_delta_max']} (after pending calls drain)"
        ),
        post_unmatched_delta <= GATE_THRESHOLDS["post_unmatched_delta_max"],
        required=pairing_required,
    )

    observe_calls = _to_int(delta.get("observe_calls"), 0)
    observe_success_ratio = _to_float(derived.get("observe_success_ratio_window"), 0.0)
    observe_latency_p95 = _to_float(derived.get("observe_latency_p95_ms"), 0.0)
    observe_required = mode == "observe" or observe_calls > 0
    if observe_required:
        _add_check(
            "observe.success_ratio",
            observe_success_ratio,
            f">= {GATE_THRESHOLDS['observe_success_ratio_min']}",
            observe_success_ratio >= GATE_THRESHOLDS["observe_success_ratio_min"],
            required=True,
        )
        _add_check(
            "observe.latency_p95_ms",
            observe_latency_p95,
            f"<= {GATE_THRESHOLDS['observe_latency_p95_ms_max']}",
            observe_latency_p95 <= GATE_THRESHOLDS["observe_latency_p95_ms_max"],
            required=True,
        )
    else:
        _add_check("observe.success_ratio", observe_success_ratio, "N/A (shadow mode)", True, required=False)
        _add_check("observe.latency_p95_ms", observe_latency_p95, "N/A (shadow mode)", True, required=False)

    required_failures = [c for c in checks if c.get("required") and not c.get("pass")]
    return {
        "passing": len(required_failures) == 0,
        "failed_count": len(required_failures),
        "failed_names": [str(c.get("name")) for c in required_failures],
        "checks": checks,
        "thresholds": dict(GATE_THRESHOLDS),
    }


def _render_markdown(summary: Dict[str, Any], gates: Dict[str, Any]) -> str:
    now_utc = datetime.now(timezone.utc).isoformat()
    if not summary.get("available"):
        return "\n".join(
            [
                "# Codex Hooks",
                "",
                f"- Generated: {now_utc}",
                "- Status: no telemetry available yet.",
                f"- Expected file: `{TELEMETRY_FILE}`",
                "",
            ]
        )

    mode = summary.get("mode")
    derived = summary.get("derived") if isinstance(summary.get("derived"), dict) else {}
    delta = summary.get("delta_metrics") if isinstance(summary.get("delta_metrics"), dict) else {}
    latest = summary.get("latest_metrics") if isinstance(summary.get("latest_metrics"), dict) else {}
    hook_counts = latest.get("hook_event_counts") if isinstance(latest.get("hook_event_counts"), dict) else {}

    lines = [
        "# Codex Hooks",
        "",
        f"- Generated: {now_utc}",
        f"- Telemetry window: last {summary.get('window_minutes')} minutes",
        f"- Mode: `{mode}`",
        f"- Gate status: **{'PASS' if gates.get('passing') else 'FAIL'}**",
        "",
        "## Rollout Gates",
        "",
        "| Check | Actual | Expectation | Required | Status |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for check in gates.get("checks", []):
        if check.get("pass"):
            status = "PASS"
        else:
            status = "FAIL" if check.get("required") else "INFO"
        req = "yes" if check.get("required") else "no"
        lines.append(
            f"| {check.get('name')} | {check.get('actual')} | {check.get('expectation')} | {req} | {status} |"
        )

    lines.extend(
        [
            "",
            "## Core Metrics (Window Delta)",
            "",
            f"- `rows_seen`: {delta.get('rows_seen', 0)}",
            f"- `relevant_rows`: {delta.get('relevant_rows', 0)}",
            f"- `mapped_events`: {delta.get('mapped_events', 0)}",
            f"- `pre_events`: {delta.get('pre_events', 0)}",
            f"- `post_events`: {delta.get('post_events', 0)}",
            f"- `post_unknown_exit`: {delta.get('post_unknown_exit', 0)}",
            f"- `post_unmatched_call_id`: {delta.get('post_unmatched_call_id', 0)}",
            f"- `observe_calls`: {delta.get('observe_calls', 0)}",
            f"- `observe_failures`: {delta.get('observe_failures', 0)}",
            f"- `pre_input_truncated`: {delta.get('pre_input_truncated', 0)}",
            f"- `post_output_truncated`: {delta.get('post_output_truncated', 0)}",
            "",
            "## Ratios",
            "",
            f"- coverage_ratio: `{derived.get('coverage_ratio', 0.0)}`",
            f"- pairing_ratio: `{derived.get('pairing_ratio', 0.0)}`",
            f"- unknown_exit_ratio: `{derived.get('unknown_exit_ratio', 0.0)}` (basis: `{derived.get('post_ratio_basis', 'unknown')}`)",
            f"- observe_success_ratio_window: `{derived.get('observe_success_ratio_window', 0.0)}` (basis: `{derived.get('observe_ratio_basis', 'unknown')}`)",
            f"- observe_latency_p95_ms: `{derived.get('observe_latency_p95_ms', 0.0)}`",
            f"- workflow_event_ratio: `{derived.get('workflow_event_ratio', 0.0)}` (basis: `{derived.get('workflow_ratio_basis', 'unknown')}`)",
            f"- tool_result_capture_rate: `{derived.get('tool_result_capture_rate', 0.0)}` (basis: `{derived.get('capture_ratio_basis', 'unknown')}`)",
            f"- truncated_tool_result_ratio: `{derived.get('truncated_tool_result_ratio', 0.0)}` (basis: `{derived.get('truncation_ratio_basis', 'unknown')}`)",
            f"- mode_shadow_ratio: `{derived.get('mode_shadow_ratio', 0.0)}`",
            f"- observe_forwarding_enabled_ratio: `{derived.get('observe_forwarding_enabled_ratio', 0.0)}`",
            f"- window_activity_rows: `{derived.get('window_activity_rows', 0)}`",
            "",
            "## Hook Event Totals (Latest Snapshot)",
            "",
        ]
    )
    if hook_counts:
        for key, value in sorted(hook_counts.items(), key=lambda x: str(x[0])):
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Next Action",
            "",
        ]
    )
    if gates.get("passing"):
        lines.append("1. Keep running in current mode and continue monitoring telemetry deltas.")
        if str(mode) == "shadow":
            lines.append("2. Start a small `--mode observe` canary and re-check this page after active sessions.")
    else:
        failed = gates.get("failed_names") or []
        lines.append("1. Hold rollout progression and fix failing checks first.")
        lines.append(f"2. Failing checks: `{', '.join(str(x) for x in failed)}`")

    lines.append("")
    return "\n".join(lines)


def write_outputs(summary: Dict[str, Any], gates: Dict[str, Any]) -> Dict[str, str]:
    snapshot_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "gates": gates,
    }

    LOCAL_OBSERVATORY_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    snapshot_path = LOCAL_OBSERVATORY_DIR / "codex_hooks_snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot_payload, indent=2), encoding="utf-8")

    md = _render_markdown(summary, gates)

    local_page_path = LOCAL_OBSERVATORY_DIR / "codex_hooks.md"
    local_page_path.write_text(md, encoding="utf-8")

    day = datetime.now().strftime("%Y-%m-%d")
    report_path = REPORTS_DIR / f"{day}_codex_hooks.md"
    report_path.write_text(md, encoding="utf-8")

    cfg = load_config()
    vault_page_path = Path(cfg.vault_dir).expanduser() / "_observatory" / "codex_hooks.md"
    vault_page_path.parent.mkdir(parents=True, exist_ok=True)
    vault_page_path.write_text(md, encoding="utf-8")

    return {
        "snapshot_json": str(snapshot_path),
        "local_page": str(local_page_path),
        "report_md": str(report_path),
        "vault_page": str(vault_page_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate Codex hooks observability report")
    ap.add_argument("--telemetry-file", default=str(TELEMETRY_FILE), help="Path to codex_hook_bridge telemetry jsonl")
    ap.add_argument("--window-minutes", type=int, default=60, help="Window size for delta checks")
    ap.add_argument("--json-only", action="store_true", help="Print JSON summary instead of writing files")
    args = ap.parse_args()

    telemetry_path = Path(args.telemetry_file).expanduser()
    rows = _read_jsonl(telemetry_path)
    summary = summarize_telemetry(rows, window_minutes=max(1, int(args.window_minutes)))
    gates = evaluate_gates(summary)
    payload = {"summary": summary, "gates": gates, "telemetry_file": str(telemetry_path)}

    if args.json_only:
        print(json.dumps(payload, indent=2))
        return 0

    outputs = write_outputs(summary, gates)
    print(json.dumps({"gate_pass": gates.get("passing"), "outputs": outputs}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
