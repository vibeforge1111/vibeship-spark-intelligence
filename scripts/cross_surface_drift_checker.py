#!/usr/bin/env python3
"""Daily cross-surface metric drift checker.

Compares a small set of canonical metrics across:
- Observatory snapshot
- Pulse/kanban data files
- Runtime advisory engine logs
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
OBSERVATORY_SNAPSHOT = ROOT / "_observatory" / "memory_quality_snapshot.json"
KPI_HISTORY = ROOT / "projects" / "observability-kanban" / "data" / "kpi_history.json"
SUPPRESSION_AUDIT = ROOT / "projects" / "observability-kanban" / "data" / "suppression_audit.json"
ADVISORY_ENGINE_LOG = Path.home() / ".spark" / "advisory_engine.jsonl"
DEFAULT_OBSERVATORY_OUT = ROOT / "_observatory" / "cross_surface_drift_snapshot.json"
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports"

TOLERANCES = {
    "memory_noise_ratio": 0.03,
    "context_p50_chars": 12.0,
    "advisory_emit_rate": 0.02,
}


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonl(path: Path, max_lines: int = 6000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if max_lines > 0:
        lines = lines[-max_lines:]
    out: List[Dict[str, Any]] = []
    for line in lines:
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


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _latest_kpi_metrics(path: Path) -> Dict[str, float]:
    data = _read_json(path)
    history = data.get("history")
    if not isinstance(history, list) or not history:
        return {}
    latest = history[-1]
    if not isinstance(latest, dict):
        return {}
    metrics = latest.get("metrics")
    if not isinstance(metrics, dict):
        return {}
    out: Dict[str, float] = {}
    for key in ("memory_noise_ratio", "context_p50_chars", "advisory_emit_rate"):
        val = _to_float(metrics.get(key))
        if val is not None:
            out[key] = val
    return out


def _runtime_emit_rate(path: Path, window_hours: float, now_ts: Optional[float] = None) -> Optional[float]:
    if now_ts is None:
        now_ts = time.time()
    cutoff = now_ts - max(1.0, float(window_hours)) * 3600.0
    rows = _read_jsonl(path, max_lines=12000)
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        ts = _to_float(row.get("ts"))
        if ts is None or ts < cutoff:
            continue
        filtered.append(row)
    if not filtered:
        return None
    emitted = 0
    total = 0
    for row in filtered:
        event = str(row.get("event") or "")
        if not event:
            continue
        total += 1
        if event in {"emitted", "fallback_emit"}:
            emitted += 1
    if total <= 0:
        return None
    return round(emitted / total, 4)


def _llm_area_drift_diagnose(incidents: List[Dict[str, Any]]) -> str:
    """LLM area: explain drift mismatches between surfaces.

    When disabled (default), returns empty string.
    """
    if not incidents:
        return ""
    try:
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from lib.llm_dispatch import llm_area_call
        from lib.llm_area_prompts import format_prompt

        incident_summary = [
            {"metric": i.get("metric"), "span": i.get("span"), "values": i.get("values")}
            for i in incidents[:5]
        ]
        prompt = format_prompt(
            "drift_diagnose",
            incidents=str(incident_summary),
        )
        result = llm_area_call("drift_diagnose", prompt, fallback="")
        if result.used_llm and result.text:
            return result.text
        return ""
    except Exception:
        return ""


def compute_snapshot(
    *,
    observatory_snapshot_path: Path = OBSERVATORY_SNAPSHOT,
    kpi_history_path: Path = KPI_HISTORY,
    suppression_audit_path: Path = SUPPRESSION_AUDIT,
    advisory_engine_log_path: Path = ADVISORY_ENGINE_LOG,
    window_hours: float = 24.0,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    if now_ts is None:
        now_ts = time.time()

    obs = _read_json(observatory_snapshot_path)
    kpi = _latest_kpi_metrics(kpi_history_path)
    suppression = _read_json(suppression_audit_path)
    runtime_emit = _runtime_emit_rate(advisory_engine_log_path, window_hours=window_hours, now_ts=now_ts)

    sources: Dict[str, Dict[str, float]] = {
        "memory_noise_ratio": {},
        "context_p50_chars": {},
        "advisory_emit_rate": {},
    }

    if "memory_noise_ratio" in kpi:
        sources["memory_noise_ratio"]["pulse_kpi_history"] = kpi["memory_noise_ratio"]
    if "context_p50_chars" in kpi:
        sources["context_p50_chars"]["pulse_kpi_history"] = kpi["context_p50_chars"]
    if "advisory_emit_rate" in kpi:
        sources["advisory_emit_rate"]["pulse_kpi_history"] = kpi["advisory_emit_rate"]

    obs_capture = obs.get("capture") if isinstance(obs.get("capture"), dict) else {}
    obs_context = obs.get("context") if isinstance(obs.get("context"), dict) else {}
    obs_noise = _to_float(obs_capture.get("noise_like_ratio"))
    obs_p50 = _to_float(obs_context.get("p50"))
    if obs_noise is not None:
        sources["memory_noise_ratio"]["observatory_snapshot"] = obs_noise
    if obs_p50 is not None:
        sources["context_p50_chars"]["observatory_snapshot"] = obs_p50

    suppression_emit = _to_float(suppression.get("current_emit_rate"))
    if suppression_emit is not None:
        sources["advisory_emit_rate"]["suppression_audit"] = suppression_emit
    if runtime_emit is not None:
        sources["advisory_emit_rate"]["runtime_advisory_engine"] = runtime_emit

    comparisons: List[Dict[str, Any]] = []
    incidents: List[Dict[str, Any]] = []
    for metric, values in sources.items():
        numeric = list(values.values())
        if not numeric:
            comparisons.append(
                {
                    "metric": metric,
                    "values": values,
                    "span": None,
                    "tolerance": TOLERANCES[metric],
                    "drift_incident": False,
                }
            )
            continue
        span = round(max(numeric) - min(numeric), 4)
        tolerance = TOLERANCES[metric]
        incident = span > tolerance and len(numeric) >= 2
        row = {
            "metric": metric,
            "values": values,
            "span": span,
            "tolerance": tolerance,
            "drift_incident": incident,
        }
        comparisons.append(row)
        if incident:
            incidents.append(row)

    # LLM area: drift_diagnose — explain drift mismatches
    drift_analysis = _llm_area_drift_diagnose(incidents)

    return {
        "generated_at": datetime.fromtimestamp(now_ts, timezone.utc).isoformat(),
        "window_hours": float(window_hours),
        "comparisons": comparisons,
        "incidents": incidents,
        "incident_count": len(incidents),
        "drift_analysis": drift_analysis,
    }


def render_report(snapshot: Dict[str, Any]) -> str:
    lines = [
        "# Cross-Surface Drift Report",
        "",
        f"- Generated: {snapshot.get('generated_at')}",
        f"- Window (hours): {snapshot.get('window_hours')}",
        f"- Drift incidents: **{snapshot.get('incident_count', 0)}**",
        "",
        "## Metric Comparisons",
    ]
    for row in snapshot.get("comparisons", []):
        metric = row.get("metric")
        span = row.get("span")
        tol = row.get("tolerance")
        status = "DRIFT" if row.get("drift_incident") else "OK"
        lines.append(f"- `{metric}` => span={span}, tolerance={tol}, status={status}")
        vals = row.get("values") or {}
        for source, value in vals.items():
            lines.append(f"  - {source}: {value}")
    lines.extend(["", "## Next Actions"])
    if snapshot.get("incident_count", 0) <= 0:
        lines.append("1. No contradiction above thresholds. Keep daily drift check active.")
    else:
        lines.append("1. Align metric contracts across Observatory and Pulse for drifted metrics.")
        lines.append("2. Check freshness windows and timestamp lag in contributing sources.")
        lines.append("3. Update one authoritative source and regenerate dependent views.")
    lines.append("")
    return "\n".join(lines)


def write_outputs(
    snapshot: Dict[str, Any],
    *,
    observatory_out: Path = DEFAULT_OBSERVATORY_OUT,
    report_dir: Path = DEFAULT_REPORT_DIR,
) -> Dict[str, Path]:
    observatory_out.parent.mkdir(parents=True, exist_ok=True)
    observatory_out.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    report_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    report_path = report_dir / f"{day}_cross_surface_drift.md"
    report_path.write_text(render_report(snapshot), encoding="utf-8")
    return {"json": observatory_out, "report": report_path}


def main() -> int:
    ap = argparse.ArgumentParser(description="Run daily cross-surface drift checks")
    ap.add_argument("--window-hours", type=float, default=24.0, help="Runtime advisory log lookback window")
    ap.add_argument("--json-only", action="store_true", help="Print snapshot JSON only")
    args = ap.parse_args()

    snapshot = compute_snapshot(window_hours=args.window_hours)
    if args.json_only:
        print(json.dumps(snapshot, indent=2))
        return 0

    paths = write_outputs(snapshot)
    print(json.dumps({"incident_count": snapshot["incident_count"], "outputs": {k: str(v) for k, v in paths.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
