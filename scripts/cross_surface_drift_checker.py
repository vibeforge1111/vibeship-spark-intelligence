#!/usr/bin/env python3
"""Cross-surface metric drift checker for Spark Alpha.

Compares canonical metrics across multiple runtime surfaces and reports drift
when source values diverge beyond metric-specific tolerances.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from lib.metric_contract import DRIFT_METRICS, METRIC_CONTRACT_VERSION

SPARK_DIR = Path.home() / ".spark"
REPORTS_DIR = Path("docs") / "reports"
OBSERVATORY_SNAPSHOT = Path("_observatory") / "memory_quality_snapshot.json"
OBSERVATORY_STATE = Path("_observatory") / ".observatory_snapshot.json"
_ALPHA_ENGINE_LOG = SPARK_DIR / "advisory_engine_alpha.jsonl"
_COMPAT_ENGINE_LOG = SPARK_DIR / "advisory_engine.jsonl"
ADVISORY_ENGINE_LOG = _ALPHA_ENGINE_LOG if _ALPHA_ENGINE_LOG.exists() else _COMPAT_ENGINE_LOG
ADVISORY_DECISION_LEDGER = SPARK_DIR / "advisory_decision_ledger.jsonl"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}


def _read_jsonl(path: Path, *, limit: int = 6000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    if limit > 0:
        lines = lines[-limit:]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _parse_ts(row: Dict[str, Any]) -> float:
    for key in ("ts", "timestamp", "created_at"):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except Exception:
                pass
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return float(dt.timestamp())
            except Exception:
                pass
    return 0.0


def _filter_window(rows: Iterable[Dict[str, Any]], *, window_s: float) -> List[Dict[str, Any]]:
    cutoff = time.time() - float(window_s)
    out: List[Dict[str, Any]] = []
    for row in rows:
        ts = _parse_ts(row)
        if ts <= 0:
            continue
        if ts >= cutoff:
            out.append(row)
    return out


def _collect_observatory_snapshot_metrics() -> Dict[str, float]:
    obj = _read_json(OBSERVATORY_SNAPSHOT)
    capture = obj.get("capture") if isinstance(obj.get("capture"), dict) else {}
    context = obj.get("context") if isinstance(obj.get("context"), dict) else {}
    advisory = obj.get("advisory_engine") if isinstance(obj.get("advisory_engine"), dict) else {}

    metrics: Dict[str, float] = {}
    noise = _safe_float(capture.get("noise_like_ratio"))
    context_p50 = _safe_float(context.get("p50"))
    emit_rate = _safe_float(advisory.get("emit_rate"))
    if noise is not None:
        metrics["memory_noise_ratio"] = noise
    if context_p50 is not None:
        metrics["context_p50_chars"] = context_p50
    if emit_rate is not None:
        metrics["advisory_emit_rate"] = emit_rate
    return metrics


def _collect_observatory_state_metrics() -> Dict[str, float]:
    obj = _read_json(OBSERVATORY_STATE)
    metrics: Dict[str, float] = {}
    emit_pct = _safe_float(obj.get("decision_emit_rate"))
    if emit_pct is not None:
        metrics["advisory_emit_rate"] = emit_pct / 100.0
    return metrics


def _collect_runtime_advisory_engine_metrics(window_s: float) -> Dict[str, float]:
    rows = _filter_window(_read_jsonl(ADVISORY_ENGINE_LOG, limit=8000), window_s=window_s)
    if not rows:
        return {}
    emitted = sum(1 for row in rows if str(row.get("event") or "") == "emitted")
    no_emit = sum(1 for row in rows if str(row.get("event") or "") == "no_emit")
    denom = emitted + no_emit
    if denom <= 0:
        return {}
    return {"advisory_emit_rate": round(emitted / denom, 6)}


def _collect_decision_ledger_metrics(window_s: float) -> Dict[str, float]:
    rows = _filter_window(_read_jsonl(ADVISORY_DECISION_LEDGER, limit=8000), window_s=window_s)
    if not rows:
        return {}
    emitted = sum(1 for row in rows if str(row.get("outcome") or "") == "emitted")
    blocked = sum(1 for row in rows if str(row.get("outcome") or "") == "blocked")
    denom = emitted + blocked
    if denom <= 0:
        return {}
    return {"advisory_emit_rate": round(emitted / denom, 6)}


def collect_surface_metrics(window_hours: float = 24.0) -> Dict[str, Dict[str, float]]:
    window_s = float(window_hours) * 3600.0
    sources: Dict[str, Dict[str, float]] = {}
    sources["observatory_snapshot"] = _collect_observatory_snapshot_metrics()
    sources["observatory_state"] = _collect_observatory_state_metrics()
    sources["runtime_advisory_engine"] = _collect_runtime_advisory_engine_metrics(window_s)
    sources["decision_ledger"] = _collect_decision_ledger_metrics(window_s)
    return {name: values for name, values in sources.items() if values}


def compute_drift_report(window_hours: float = 24.0) -> Dict[str, Any]:
    sources = collect_surface_metrics(window_hours=window_hours)
    comparisons: List[Dict[str, Any]] = []
    drift_incidents = 0

    for metric_id, spec in DRIFT_METRICS.items():
        values = {
            source_name: float(metric_values[metric_id])
            for source_name, metric_values in sources.items()
            if metric_id in metric_values
        }
        if len(values) < 2:
            comparisons.append(
                {
                    "metric": metric_id,
                    "status": "INSUFFICIENT",
                    "tolerance_abs": spec.tolerance_abs,
                    "span": None,
                    "sources": values,
                }
            )
            continue

        min_v = min(values.values())
        max_v = max(values.values())
        span = max_v - min_v
        status = "DRIFT" if span > float(spec.tolerance_abs) else "OK"
        if status == "DRIFT":
            drift_incidents += 1
        comparisons.append(
            {
                "metric": metric_id,
                "status": status,
                "tolerance_abs": spec.tolerance_abs,
                "span": round(span, 6),
                "sources": values,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metric_contract_version": METRIC_CONTRACT_VERSION,
        "window_hours": float(window_hours),
        "source_count": len(sources),
        "drift_incidents": int(drift_incidents),
        "comparisons": comparisons,
    }


def write_drift_outputs(report: Dict[str, Any]) -> Dict[str, str]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    json_path = REPORTS_DIR / f"{day}_cross_surface_drift.json"
    md_path = REPORTS_DIR / f"{day}_cross_surface_drift.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Cross-Surface Drift Report",
        "",
        f"- Generated: {report.get('generated_at')}",
        f"- Metric contract: `{report.get('metric_contract_version')}`",
        f"- Window (hours): {report.get('window_hours')}",
        f"- Source count: {report.get('source_count')}",
        f"- Drift incidents: **{report.get('drift_incidents')}**",
        "",
        "## Metric Comparisons",
    ]

    for item in report.get("comparisons", []):
        metric = item.get("metric")
        status = item.get("status")
        span = item.get("span")
        tol = item.get("tolerance_abs")
        lines.append(f"- `{metric}` => span={span}, tolerance={tol}, status={status}")
        sources = item.get("sources") if isinstance(item.get("sources"), dict) else {}
        for source_name, value in sources.items():
            lines.append(f"  - {source_name}: {value}")

    lines.extend(
        [
            "",
            "## Next Actions",
            "1. Align formulas if any metric is DRIFT.",
            "2. Check source freshness windows for mismatched timestamps.",
            "3. Regenerate observability surfaces after formula updates.",
        ]
    )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate cross-surface drift report.")
    parser.add_argument("--window-hours", type=float, default=24.0)
    args = parser.parse_args()

    report = compute_drift_report(window_hours=float(args.window_hours))
    paths = write_drift_outputs(report)
    out = {
        "metric_contract_version": report.get("metric_contract_version"),
        "drift_incidents": report.get("drift_incidents"),
        "report_paths": paths,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
