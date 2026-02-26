#!/usr/bin/env python3
"""Cross-provider workflow fidelity observatory.

Builds per-provider KPIs for OpenClaw, Claude, and Codex surfaces:
- workflow_event_ratio
- tool_result_capture_rate
- truncated_tool_result_ratio
- skipped_by_filter_ratio
- mode_shadow_ratio

Publishes snapshot + markdown report + Obsidian page.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from lib.observatory.config import load_config
from scripts.codex_hooks_observatory import summarize_telemetry as summarize_codex_telemetry


SPARK_DIR = Path.home() / ".spark"
CODEX_TELEMETRY_FILE = SPARK_DIR / "logs" / "codex_hook_bridge_telemetry.jsonl"
OPENCLAW_TELEMETRY_FILE = SPARK_DIR / "logs" / "openclaw_tailer_telemetry.jsonl"
OBSERVE_TELEMETRY_FILE = SPARK_DIR / "logs" / "observe_hook_telemetry.jsonl"

OBSERVATORY_DIR = Path("_observatory")
REPORTS_DIR = Path("docs") / "reports"
STATE_FILE = OBSERVATORY_DIR / "workflow_fidelity_alert_state.json"

ALERT_THRESHOLDS = {
    "workflow_event_ratio_min": 0.60,
    "tool_result_capture_rate_min": 0.65,
    "truncated_tool_result_ratio_max": 0.80,
    "skipped_by_filter_ratio_max": 0.50,
    "mode_shadow_ratio_max": 0.80,
    "stale_max_age_s": 1800,
}


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


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_ratio(numer: float, denom: float) -> float:
    if denom <= 0:
        return 0.0
    return float(numer) / float(denom)


def _window_rows(rows: List[Dict[str, Any]], *, window_minutes: int, now_ts: float | None = None) -> List[Dict[str, Any]]:
    if not rows:
        return []
    rows_sorted = sorted(rows, key=lambda r: _to_float(r.get("ts"), 0.0))
    if now_ts is None:
        now_ts = _to_float(rows_sorted[-1].get("ts"), time.time())
    cutoff = float(now_ts) - max(1, int(window_minutes)) * 60.0
    out = [r for r in rows_sorted if _to_float(r.get("ts"), 0.0) >= cutoff]
    if not out:
        out = [rows_sorted[-1]]
    return out


def _metric_delta(first: Dict[str, Any], last: Dict[str, Any], key: str) -> int:
    start = _to_int(first.get(key), 0)
    end = _to_int(last.get(key), 0)
    if end >= start:
        return end - start
    return end


def summarize_openclaw(rows: List[Dict[str, Any]], *, window_minutes: int = 60) -> Dict[str, Any]:
    if not rows:
        return {"provider": "openclaw", "available": False, "reason": "no_rows"}
    win = _window_rows(rows, window_minutes=window_minutes)
    first = win[0].get("metrics") if isinstance(win[0].get("metrics"), dict) else {}
    last = win[-1].get("metrics") if isinstance(win[-1].get("metrics"), dict) else {}

    keys = {
        "rows_seen",
        "rows_skipped_filter",
        "json_decode_errors",
        "events_posted",
        "tool_events",
        "tool_calls",
        "tool_results",
        "tool_result_truncated",
        "hook_rows_seen",
        "hook_events_posted",
        "report_files_seen",
        "report_events_posted",
    }
    delta = {k: _metric_delta(first, last, k) for k in keys}

    events_posted = max(0, delta.get("events_posted", 0))
    tool_events = max(0, delta.get("tool_events", 0))
    tool_calls = max(0, delta.get("tool_calls", 0))
    tool_results = max(0, delta.get("tool_results", 0))
    rows_seen = max(0, delta.get("rows_seen", 0))
    skipped_rows = max(0, delta.get("rows_skipped_filter", 0))
    truncated = max(0, delta.get("tool_result_truncated", 0))
    window_activity_rows = rows_seen + max(0, delta.get("hook_rows_seen", 0)) + max(0, delta.get("report_files_seen", 0))

    return {
        "provider": "openclaw",
        "available": True,
        "latest_ts": _to_float(win[-1].get("ts"), 0.0),
        "window_rows": len(win),
        "window_activity_rows": int(window_activity_rows),
        "delta_metrics": delta,
        "kpis": {
            "workflow_event_ratio": round(_safe_ratio(tool_events, max(1, events_posted)), 4),
            "tool_result_capture_rate": round(_safe_ratio(tool_results, max(1, tool_calls)), 4),
            "truncated_tool_result_ratio": round(_safe_ratio(truncated, max(1, tool_results)), 4),
            "skipped_by_filter_ratio": round(_safe_ratio(skipped_rows, max(1, rows_seen)), 4),
            "mode_shadow_ratio": 0.0,
        },
    }


def summarize_claude(rows: List[Dict[str, Any]], *, window_minutes: int = 60) -> Dict[str, Any]:
    claude_rows = [r for r in rows if str(r.get("source") or "") == "claude_code"]
    if not claude_rows:
        return {"provider": "claude", "available": False, "reason": "no_rows"}
    win = _window_rows(claude_rows, window_minutes=window_minutes)

    total = len(win)
    workflow = sum(1 for r in win if bool(r.get("workflow_event")))
    pre_events = sum(1 for r in win if bool(r.get("pre_event")))
    result_events = sum(1 for r in win if bool(r.get("tool_result_event")))
    captured_results = sum(1 for r in win if bool(r.get("tool_result_captured")))
    truncated_results = sum(1 for r in win if bool(r.get("tool_result_truncated")))
    payload_truncated = sum(1 for r in win if bool(r.get("payload_truncated")))
    capture_failures = sum(1 for r in win if not bool(r.get("capture_ok", True)))

    return {
        "provider": "claude",
        "available": True,
        "latest_ts": max((_to_float(r.get("ts"), 0.0) for r in win), default=0.0),
        "window_rows": len(win),
        "window_activity_rows": int(total),
        "delta_metrics": {
            "rows_seen": int(total),
            "workflow_events": int(workflow),
            "pre_events": int(pre_events),
            "tool_result_events": int(result_events),
            "tool_result_captured": int(captured_results),
            "tool_result_truncated": int(truncated_results),
            "payload_truncated": int(payload_truncated),
            "capture_failures": int(capture_failures),
        },
        "kpis": {
            "workflow_event_ratio": round(_safe_ratio(workflow, max(1, total)), 4),
            "tool_result_capture_rate": round(_safe_ratio(captured_results, max(1, pre_events)), 4),
            "truncated_tool_result_ratio": round(_safe_ratio(truncated_results, max(1, result_events)), 4),
            "skipped_by_filter_ratio": 0.0,
            "mode_shadow_ratio": 0.0,
        },
    }


def summarize_codex(rows: List[Dict[str, Any]], *, window_minutes: int = 60) -> Dict[str, Any]:
    summary = summarize_codex_telemetry(rows, window_minutes=window_minutes)
    if not summary.get("available"):
        return {"provider": "codex", "available": False, "reason": "no_rows"}
    derived = summary.get("derived") if isinstance(summary.get("derived"), dict) else {}
    delta = summary.get("delta_metrics") if isinstance(summary.get("delta_metrics"), dict) else {}
    relevant_rows = max(0, _to_int(delta.get("relevant_rows"), 0))
    mapped_events = max(0, _to_int(delta.get("mapped_events"), 0))
    skipped_by_filter = max(0, relevant_rows - mapped_events)

    return {
        "provider": "codex",
        "available": True,
        "latest_ts": _to_float(summary.get("latest_ts"), 0.0),
        "window_rows": _to_int(summary.get("window_rows"), 0),
        "window_activity_rows": _to_int(derived.get("window_activity_rows"), 0),
        "delta_metrics": delta,
        "kpis": {
            "workflow_event_ratio": _to_float(derived.get("workflow_event_ratio"), 0.0),
            "tool_result_capture_rate": _to_float(derived.get("tool_result_capture_rate"), 0.0),
            "truncated_tool_result_ratio": _to_float(derived.get("truncated_tool_result_ratio"), 0.0),
            "skipped_by_filter_ratio": round(_safe_ratio(skipped_by_filter, max(1, relevant_rows)), 4),
            "mode_shadow_ratio": _to_float(derived.get("mode_shadow_ratio"), 0.0),
        },
    }


def _read_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def evaluate_alerts(
    provider_summaries: Dict[str, Dict[str, Any]],
    *,
    state_file: Path = STATE_FILE,
    now_ts: float | None = None,
) -> Dict[str, Any]:
    if now_ts is None:
        now_ts = time.time()
    prev = _read_state(state_file)
    prev_providers = prev.get("providers") if isinstance(prev.get("providers"), dict) else {}

    alerts: Dict[str, Any] = {}
    next_state: Dict[str, Any] = {"providers": {}}

    for provider, summary in provider_summaries.items():
        previous = prev_providers.get(provider) if isinstance(prev_providers.get(provider), dict) else {}
        prev_consecutive = _to_int(previous.get("consecutive_breach_windows"), 0)

        if not summary.get("available"):
            alert = {
                "level": "unknown",
                "breaches": [],
                "consecutive_breach_windows": 0,
                "stale": True,
                "stale_age_s": None,
            }
            alerts[provider] = alert
            next_state["providers"][provider] = {
                "consecutive_breach_windows": 0,
                "updated_at": now_ts,
            }
            continue

        kpis = summary.get("kpis") if isinstance(summary.get("kpis"), dict) else {}
        breaches: List[Dict[str, Any]] = []
        activity = _to_int(summary.get("window_activity_rows"), 0)
        latest_ts = _to_float(summary.get("latest_ts"), 0.0)
        stale_age_s = max(0.0, float(now_ts) - float(latest_ts))
        stale = stale_age_s > float(ALERT_THRESHOLDS["stale_max_age_s"])

        if activity > 0:
            workflow_event_ratio = _to_float(kpis.get("workflow_event_ratio"), 0.0)
            tool_result_capture_rate = _to_float(kpis.get("tool_result_capture_rate"), 0.0)
            truncated_ratio = _to_float(kpis.get("truncated_tool_result_ratio"), 0.0)
            skipped_ratio = kpis.get("skipped_by_filter_ratio")
            mode_shadow_ratio = kpis.get("mode_shadow_ratio")

            if workflow_event_ratio < float(ALERT_THRESHOLDS["workflow_event_ratio_min"]):
                breaches.append(
                    {
                        "name": "workflow_event_ratio",
                        "actual": round(workflow_event_ratio, 4),
                        "expectation": f">= {ALERT_THRESHOLDS['workflow_event_ratio_min']}",
                    }
                )
            if tool_result_capture_rate < float(ALERT_THRESHOLDS["tool_result_capture_rate_min"]):
                breaches.append(
                    {
                        "name": "tool_result_capture_rate",
                        "actual": round(tool_result_capture_rate, 4),
                        "expectation": f">= {ALERT_THRESHOLDS['tool_result_capture_rate_min']}",
                    }
                )
            if truncated_ratio > float(ALERT_THRESHOLDS["truncated_tool_result_ratio_max"]):
                breaches.append(
                    {
                        "name": "truncated_tool_result_ratio",
                        "actual": round(truncated_ratio, 4),
                        "expectation": f"<= {ALERT_THRESHOLDS['truncated_tool_result_ratio_max']}",
                    }
                )
            if skipped_ratio is not None and _to_float(skipped_ratio, 0.0) > float(ALERT_THRESHOLDS["skipped_by_filter_ratio_max"]):
                breaches.append(
                    {
                        "name": "skipped_by_filter_ratio",
                        "actual": round(_to_float(skipped_ratio, 0.0), 4),
                        "expectation": f"<= {ALERT_THRESHOLDS['skipped_by_filter_ratio_max']}",
                    }
                )
            if mode_shadow_ratio is not None and _to_float(mode_shadow_ratio, 0.0) > float(ALERT_THRESHOLDS["mode_shadow_ratio_max"]):
                breaches.append(
                    {
                        "name": "mode_shadow_ratio",
                        "actual": round(_to_float(mode_shadow_ratio, 0.0), 4),
                        "expectation": f"<= {ALERT_THRESHOLDS['mode_shadow_ratio_max']}",
                    }
                )

        consecutive = prev_consecutive + 1 if breaches else 0
        if consecutive >= 2 and stale:
            level = "critical"
        elif breaches:
            level = "warning"
        else:
            level = "ok"

        alert = {
            "level": level,
            "breaches": breaches,
            "consecutive_breach_windows": int(consecutive),
            "stale": bool(stale),
            "stale_age_s": round(stale_age_s, 1),
        }
        alerts[provider] = alert
        next_state["providers"][provider] = {
            "consecutive_breach_windows": int(consecutive),
            "updated_at": float(now_ts),
        }

    _write_state(state_file, next_state)
    return {"providers": alerts, "thresholds": dict(ALERT_THRESHOLDS)}


def _render_markdown(
    provider_summaries: Dict[str, Dict[str, Any]],
    alerts: Dict[str, Any],
    *,
    window_minutes: int,
) -> str:
    now_utc = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Workflow Fidelity",
        "",
        f"- Generated: {now_utc}",
        f"- Window: last {window_minutes} minutes",
        "",
        "## Providers",
        "",
        "| Provider | Status | workflow_event_ratio | tool_result_capture_rate | truncated_tool_result_ratio | skipped_by_filter_ratio | mode_shadow_ratio |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]

    provider_alerts = alerts.get("providers") if isinstance(alerts.get("providers"), dict) else {}
    for provider in ("openclaw", "claude", "codex"):
        summary = provider_summaries.get(provider) if isinstance(provider_summaries.get(provider), dict) else {}
        alert = provider_alerts.get(provider) if isinstance(provider_alerts.get(provider), dict) else {}
        if not summary.get("available"):
            lines.append(f"| {provider} | unavailable | - | - | - | - | - |")
            continue
        k = summary.get("kpis") if isinstance(summary.get("kpis"), dict) else {}
        lines.append(
            "| "
            + " | ".join(
                [
                    provider,
                    str(alert.get("level") or "unknown"),
                    str(k.get("workflow_event_ratio", 0.0)),
                    str(k.get("tool_result_capture_rate", 0.0)),
                    str(k.get("truncated_tool_result_ratio", 0.0)),
                    str(k.get("skipped_by_filter_ratio", 0.0)),
                    str(k.get("mode_shadow_ratio", 0.0)),
                ]
            )
            + " |"
        )

    lines.extend(["", "## Alerts", ""])
    for provider in ("openclaw", "claude", "codex"):
        alert = provider_alerts.get(provider) if isinstance(provider_alerts.get(provider), dict) else {}
        lines.append(
            f"- `{provider}`: level=`{alert.get('level', 'unknown')}` consecutive=`{alert.get('consecutive_breach_windows', 0)}` stale=`{alert.get('stale', False)}` stale_age_s=`{alert.get('stale_age_s', 0)}`"
        )
        breaches = alert.get("breaches") if isinstance(alert.get("breaches"), list) else []
        if breaches:
            for b in breaches:
                lines.append(
                    f"  - {b.get('name')}: {b.get('actual')} (expected {b.get('expectation')})"
                )
    lines.append("")
    return "\n".join(lines)


def write_outputs(
    *,
    provider_summaries: Dict[str, Dict[str, Any]],
    alerts: Dict[str, Any],
    window_minutes: int,
) -> Dict[str, str]:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_minutes": int(window_minutes),
        "providers": provider_summaries,
        "alerts": alerts,
    }

    OBSERVATORY_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    snapshot_path = OBSERVATORY_DIR / "workflow_fidelity_snapshot.json"
    snapshot_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md = _render_markdown(provider_summaries, alerts, window_minutes=window_minutes)
    local_page = OBSERVATORY_DIR / "workflow_fidelity.md"
    local_page.write_text(md, encoding="utf-8")

    day = datetime.now().strftime("%Y-%m-%d")
    report_path = REPORTS_DIR / f"{day}_workflow_fidelity.md"
    report_path.write_text(md, encoding="utf-8")

    cfg = load_config()
    vault_page = Path(cfg.vault_dir).expanduser() / "_observatory" / "workflow_fidelity.md"
    vault_page.parent.mkdir(parents=True, exist_ok=True)
    vault_page.write_text(md, encoding="utf-8")

    return {
        "snapshot_json": str(snapshot_path),
        "local_page": str(local_page),
        "report_md": str(report_path),
        "vault_page": str(vault_page),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate cross-provider workflow fidelity observability report")
    ap.add_argument("--window-minutes", type=int, default=60)
    ap.add_argument("--codex-telemetry-file", default=str(CODEX_TELEMETRY_FILE))
    ap.add_argument("--openclaw-telemetry-file", default=str(OPENCLAW_TELEMETRY_FILE))
    ap.add_argument("--observe-telemetry-file", default=str(OBSERVE_TELEMETRY_FILE))
    ap.add_argument("--state-file", default=str(STATE_FILE))
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    window_minutes = max(1, int(args.window_minutes))
    codex_rows = _read_jsonl(Path(args.codex_telemetry_file).expanduser())
    openclaw_rows = _read_jsonl(Path(args.openclaw_telemetry_file).expanduser())
    observe_rows = _read_jsonl(Path(args.observe_telemetry_file).expanduser())

    providers = {
        "openclaw": summarize_openclaw(openclaw_rows, window_minutes=window_minutes),
        "claude": summarize_claude(observe_rows, window_minutes=window_minutes),
        "codex": summarize_codex(codex_rows, window_minutes=window_minutes),
    }
    alerts = evaluate_alerts(providers, state_file=Path(args.state_file).expanduser())
    payload = {"providers": providers, "alerts": alerts, "window_minutes": window_minutes}

    if args.json_only:
        print(json.dumps(payload, indent=2))
        return 0

    outputs = write_outputs(provider_summaries=providers, alerts=alerts, window_minutes=window_minutes)
    print(json.dumps({"outputs": outputs, "alerts": alerts.get("providers")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
