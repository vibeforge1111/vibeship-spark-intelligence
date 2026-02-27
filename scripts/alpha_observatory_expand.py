#!/usr/bin/env python3
"""Expand Alpha Observatory pages with readiness, drift, and dependency views."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.observatory.config import load_config
from lib.production_gates import evaluate_gates, load_live_metrics
from scripts.alpha_preflight_bundle import evaluate_alpha_preflight


OBS_DIR = ROOT / "_observatory"
AUDIT_DIR = ROOT / "reports" / "audits"
TUNEABLES = ROOT / "config" / "tuneables.json"


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _latest_audit() -> Tuple[Path | None, Dict[str, Any]]:
    paths = sorted(AUDIT_DIR.glob("alpha_deep_system_audit_*.json"))
    if not paths:
        return None, {}
    p = paths[-1]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return p, data
    except Exception:
        pass
    return p, {}


def _load_tuneables() -> Dict[str, Any]:
    try:
        data = json.loads(TUNEABLES.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _find_legacy_doc_refs() -> List[Tuple[str, str]]:
    legacy_tokens = (
        "lib/advisory_engine.py",
        "lib/advisory_orchestrator.py",
    )
    refs: List[Tuple[str, str]] = []
    for p in ROOT.rglob("*.md"):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel.startswith(".venv/") or rel.startswith("node_modules/"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for token in legacy_tokens:
            if token in text:
                refs.append((rel, token))
    return refs


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n", encoding="utf-8")


def _render_readiness(payload: Dict[str, Any], gates: Dict[str, Any]) -> str:
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    failed = [c for c in checks if isinstance(c, dict) and not bool(c.get("ok"))]
    gate_checks = gates.get("checks") if isinstance(gates.get("checks"), list) else []
    gate_failed = [c for c in gate_checks if isinstance(c, dict) and not bool(c.get("ok"))]
    lines: List[str] = []
    lines.append("# Alpha Readiness Blockers")
    lines.append("")
    lines.append(f"- generated_at_utc: `{datetime.now(timezone.utc).isoformat()}`")
    lines.append(f"- preflight_ready: `{bool(payload.get('ready'))}`")
    lines.append(
        f"- production_gates: `{int(gates.get('passed', 0) or 0)}/{int(gates.get('total', 0) or 0)}`"
    )
    lines.append("")
    lines.append("## Bundle Checks")
    if not failed:
        lines.append("- none (all checks passing)")
    else:
        for row in failed:
            lines.append(f"- `{row.get('name')}`: `{json.dumps(row.get('value'), ensure_ascii=True)}`")
    lines.append("")
    lines.append("## Production Gate Failures")
    if not gate_failed:
        lines.append("- none (all production gates passing)")
    else:
        for row in gate_failed:
            lines.append(
                f"- `{row.get('name')}` value=`{row.get('value')}` target=`{row.get('target')}` "
                f"action=`{row.get('recommendation')}`"
            )
    return "\n".join(lines)


def _render_strict_funnel(metrics: Any, gates: Dict[str, Any]) -> str:
    actionable = int(getattr(metrics, "actionable_retrieved", 0) or 0)
    acted = int(getattr(metrics, "acted_on", 0) or 0)
    strict = int(getattr(metrics, "strict_acted_on", 0) or 0)
    explicit = int(getattr(metrics, "strict_with_outcome", 0) or 0)
    lines: List[str] = []
    lines.append("# Strict Attribution Funnel")
    lines.append("")
    lines.append(f"- generated_at_utc: `{datetime.now(timezone.utc).isoformat()}`")
    lines.append(f"- strict_require_trace: `{bool(getattr(metrics, 'strict_require_trace', False))}`")
    lines.append(f"- strict_window_s: `{int(getattr(metrics, 'strict_window_s', 0) or 0)}`")
    lines.append("")
    lines.append("| Stage | Count | Conversion |")
    lines.append("|---|---:|---:|")
    lines.append(f"| actionable_retrieved | {actionable} | 100.0% |")
    lines.append(f"| acted_on | {acted} | {((acted / max(actionable, 1))*100):.1f}% |")
    lines.append(f"| strict_trace_bound | {strict} | {((strict / max(acted, 1))*100):.1f}% of acted_on |")
    lines.append(f"| strict_explicit_outcome | {explicit} | {((explicit / max(strict, 1))*100):.1f}% of strict |")
    lines.append("")
    lines.append("## Gates")
    for name in (
        "strict_attribution_policy",
        "strict_outcome_sample_floor",
        "strict_acted_on_rate",
        "strict_trace_coverage",
        "strict_effectiveness_rate",
    ):
        row = next((c for c in (gates.get("checks") or []) if c.get("name") == name), {})
        lines.append(
            f"- `{name}`: `{_status(bool(row.get('ok')))} ` "
            f"value=`{row.get('value')}` target=`{row.get('target')}`"
        )
    return "\n".join(lines)


def _render_distillation(metrics: Any, gates: Dict[str, Any]) -> str:
    row = next((c for c in (gates.get("checks") or []) if c.get("name") == "distillation_floor"), {})
    lines = [
        "# Distillation Yield",
        "",
        f"- generated_at_utc: `{datetime.now(timezone.utc).isoformat()}`",
        f"- distillations_current: `{int(getattr(metrics, 'distillations', 0) or 0)}`",
        f"- floor_target: `{row.get('target')}`",
        f"- floor_status: `{_status(bool(row.get('ok')))} `",
        f"- queue_depth: `{int(getattr(metrics, 'queue_depth', 0) or 0)}`",
        "",
        "## Related Signals",
        f"- retrieval_rate: `{float(getattr(metrics, 'retrieval_rate', 0.0) or 0.0):.4f}`",
        f"- acted_on_rate: `{float(getattr(metrics, 'acted_on_rate', 0.0) or 0.0):.4f}`",
        f"- effectiveness_rate: `{float(getattr(metrics, 'effectiveness_rate', 0.0) or 0.0):.4f}`",
    ]
    return "\n".join(lines)


def _render_config_drift(tuneables: Dict[str, Any], audit: Dict[str, Any], legacy_refs: List[Tuple[str, str]]) -> str:
    rows = audit.get("rows") if isinstance(audit.get("rows"), list) else []
    migration_rows = [r for r in rows if isinstance(r, dict) and r.get("status") == "needs-migration"]
    doc_rows = [r for r in migration_rows if str(r.get("file", "")).startswith("docs/")]
    ref_lines = [f"- `{file}` references `{token}`" for file, token in sorted(set(legacy_refs))[:30]]
    lines: List[str] = []
    lines.append("# Config And Docs Drift")
    lines.append("")
    lines.append(f"- generated_at_utc: `{datetime.now(timezone.utc).isoformat()}`")
    lines.append(f"- tuneable_sections: `{len(tuneables)}`")
    lines.append(
        f"- tuneable_keys_total: `{sum(len(v) for v in tuneables.values() if isinstance(v, dict))}`"
    )
    lines.append(f"- audit_needs_migration: `{len(migration_rows)}`")
    lines.append(f"- audit_docs_needs_migration: `{len(doc_rows)}`")
    lines.append(f"- legacy_doc_refs_found: `{len(legacy_refs)}`")
    lines.append("")
    lines.append("## Legacy Doc References (sample)")
    if not ref_lines:
        lines.append("- none detected in markdown scan")
    else:
        lines.extend(ref_lines)
    return "\n".join(lines)


def _render_dependency_health(audit: Dict[str, Any]) -> str:
    rows = audit.get("rows") if isinstance(audit.get("rows"), list) else []
    cycles = audit.get("cycles") if isinstance(audit.get("cycles"), list) else []
    orphaned = [r for r in rows if isinstance(r, dict) and r.get("status") == "orphaned"]
    degraded = [r for r in rows if isinstance(r, dict) and r.get("status") == "degraded"]
    by_fan_in = sorted(
        [r for r in rows if isinstance(r, dict)],
        key=lambda r: len(r.get("depended_by") or []),
        reverse=True,
    )[:10]
    lines: List[str] = []
    lines.append("# Dependency Health")
    lines.append("")
    lines.append(f"- generated_at_utc: `{datetime.now(timezone.utc).isoformat()}`")
    lines.append(f"- file_count: `{int(audit.get('file_count', 0) or 0)}`")
    lines.append(f"- circular_components: `{len(cycles)}`")
    lines.append(f"- orphaned_files: `{len(orphaned)}`")
    lines.append(f"- degraded_files: `{len(degraded)}`")
    lines.append("")
    lines.append("## Circular Dependency Components")
    if not cycles:
        lines.append("- none")
    else:
        for comp in cycles:
            if isinstance(comp, list):
                lines.append(f"- size={len(comp)}: `{', '.join(str(x) for x in comp[:12])}`")
    lines.append("")
    lines.append("## Highest Fan-In Files")
    for row in by_fan_in:
        lines.append(f"- `{row.get('file')}` depended_by={len(row.get('depended_by') or [])}")
    return "\n".join(lines)


def main() -> int:
    preflight = evaluate_alpha_preflight(bridge_stale_s=90)
    metrics = load_live_metrics()
    gates = evaluate_gates(metrics)
    tuneables = _load_tuneables()
    audit_path, audit = _latest_audit()
    legacy_refs = _find_legacy_doc_refs()

    OBS_DIR.mkdir(parents=True, exist_ok=True)
    pages = {
        "alpha_readiness_blockers.md": _render_readiness(preflight, gates),
        "strict_attribution_funnel.md": _render_strict_funnel(metrics, gates),
        "distillation_yield.md": _render_distillation(metrics, gates),
        "config_and_docs_drift.md": _render_config_drift(tuneables, audit, legacy_refs),
        "dependency_health.md": _render_dependency_health(audit),
    }
    out_paths: Dict[str, str] = {}
    for name, body in pages.items():
        p = OBS_DIR / name
        _write(p, body)
        out_paths[name] = str(p)

    cfg = load_config()
    vault_obs = Path(cfg.vault_dir).expanduser() / "_observatory"
    vault_written: Dict[str, str] = {}
    for name, body in pages.items():
        try:
            p = vault_obs / name
            _write(p, body)
            vault_written[name] = str(p)
        except Exception:
            continue

    summary = {
        "ok": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "preflight_ready": bool(preflight.get("ready")),
        "production_ready": bool(gates.get("ready")),
        "audit_path": str(audit_path) if audit_path else "",
        "pages": out_paths,
        "vault_pages": vault_written,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
