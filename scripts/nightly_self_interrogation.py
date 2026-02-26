#!/usr/bin/env python3
"""Nightly 5-section self-interrogation report generator."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
MEMORY_SNAPSHOT = ROOT / "_observatory" / "memory_quality_snapshot.json"
SUPPRESSION_AUDIT = ROOT / "projects" / "observability-kanban" / "data" / "suppression_audit.json"
BUILD_QUEUE = ROOT / "projects" / "observability-kanban" / "data" / "terminal_build_queue.json"
PULSE_WIDGETS = ROOT / "projects" / "observability-kanban" / "data" / "pulse_widgets.json"
PULSE_ENDPOINTS = ROOT / "projects" / "observability-kanban" / "data" / "pulse_endpoints.json"
DRIFT_SNAPSHOT = ROOT / "_observatory" / "cross_surface_drift_snapshot.json"
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports"
SYSTEM28_APPLY_GLOB = "*_eidos_curriculum_autofix_apply*.json"
SYSTEM28_DRYRUN_GLOB = "*_eidos_curriculum_autofix_dryrun*.json"


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _latest_report_by_glob(pattern: str, *, root: Path = DEFAULT_REPORT_DIR) -> Optional[Path]:
    candidates = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _system28_metrics() -> Dict[str, Any]:
    apply_path = _latest_report_by_glob(SYSTEM28_APPLY_GLOB)
    dryrun_path = _latest_report_by_glob(SYSTEM28_DRYRUN_GLOB)

    src = apply_path or dryrun_path
    if not src:
        return {
            "available": False,
            "evidence": "no system-28 autofix report found",
        }

    data = _read_json(src)
    attempted = int(data.get("attempted") or 0)
    updated = int(data.get("updated") or 0)
    rows = data.get("rows") if isinstance(data.get("rows"), list) else []

    gains: List[float] = []
    unsuppressed = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        old_u = float(row.get("old_unified") or 0.0)
        new_u = float(row.get("new_unified") or 0.0)
        gains.append(max(0.0, new_u - old_u))
        if bool(row.get("old_suppressed")) and not bool(row.get("new_suppressed")):
            unsuppressed += 1

    avg_gain = (sum(gains) / len(gains)) if gains else 0.0
    update_rate = (updated / attempted) if attempted > 0 else 0.0

    score = min(1.0, (update_rate * 0.7) + (avg_gain * 0.5) + (0.05 if unsuppressed > 0 else 0.0))
    verdict = _verdict(score, good=0.45, mixed=0.25)

    return {
        "available": True,
        "source_file": str(src),
        "attempted": attempted,
        "updated": updated,
        "update_rate": round(update_rate, 3),
        "avg_unified_gain": round(avg_gain, 3),
        "unsuppressed_count": int(unsuppressed),
        "verdict": verdict,
        "score": round(score, 3),
    }


def _verdict(score: float, good: float, mixed: float) -> str:
    if score >= good:
        return "good"
    if score >= mixed:
        return "mixed"
    return "bad"


def _memory_section(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    grade = snapshot.get("grade") if isinstance(snapshot.get("grade"), dict) else {}
    capture = snapshot.get("capture") if isinstance(snapshot.get("capture"), dict) else {}
    context = snapshot.get("context") if isinstance(snapshot.get("context"), dict) else {}
    noise = float(capture.get("noise_like_ratio") or 0.0)
    p50 = int(context.get("p50") or 0)
    score = float(grade.get("score") or 0.0)
    verdict = _verdict(score, good=0.8, mixed=0.6)
    action = (
        "Lower capture noise by tightening source filters and pruning repeated low-signal patterns."
        if verdict != "good"
        else "Keep current capture policy and monitor drift daily."
    )
    return {
        "name": "Memory Quality",
        "question": "Did memory quality improve with less noise and better context?",
        "evidence": f"grade={grade.get('band', 'unknown')} score={score} noise_ratio={noise} context_p50={p50}",
        "verdict": verdict,
        "action": action,
    }


def _advisory_section(audit: Dict[str, Any]) -> Dict[str, Any]:
    emit = float(audit.get("current_emit_rate") or 0.0)
    target = float(audit.get("target_emit_rate") or 0.0)
    top = None
    causes = audit.get("causes")
    if isinstance(causes, list) and causes:
        top = causes[0] if isinstance(causes[0], dict) else None
    ratio = (emit / target) if target > 0 else 0.0
    verdict = _verdict(ratio, good=1.0, mixed=0.75)
    action = (
        f"Prioritize suppression fix: {top.get('reason')} -> {top.get('recommended_action')}"
        if top and verdict != "good"
        else "Maintain suppression tuning and validate emit quality with strict trace linkage."
    )
    return {
        "name": "Advisory Emissions",
        "question": "Are we recovering useful advisory emissions without raising noise?",
        "evidence": f"emit_rate={emit} target={target} ratio={round(ratio, 3)}",
        "verdict": verdict,
        "action": action,
    }


def _website_section(queue: Dict[str, Any]) -> Dict[str, Any]:
    tasks = queue.get("tasks")
    if not isinstance(tasks, list):
        tasks = []
    web = [t for t in tasks if isinstance(t, dict) and str(t.get("id", "")).startswith(("Q-WEB", "CB-014"))]
    ready = sum(1 for t in web if str(t.get("build_ready")).lower() == "true" or t.get("build_ready") is True)
    total = len(web)
    score = (ready / total) if total > 0 else 0.0
    verdict = _verdict(score, good=0.8, mixed=0.5)
    action = (
        "Convert onboarding measurement backlog into build-ready tasks with owner and ETA."
        if verdict != "good"
        else "Continue onboarding instrumentation rollout and watch first-value latency."
    )
    return {
        "name": "Website / Onboarding",
        "question": "Are onboarding and web-flow metrics actionable enough for daily decisions?",
        "evidence": f"web_tasks={total} build_ready={ready}",
        "verdict": verdict,
        "action": action,
    }


def _observatory_section(queue: Dict[str, Any], drift: Dict[str, Any]) -> Dict[str, Any]:
    tasks = queue.get("tasks")
    if not isinstance(tasks, list):
        tasks = []
    obs = [t for t in tasks if isinstance(t, dict) and str(t.get("id", "")).startswith(("CB-019", "CB-007", "CB-027", "Q-OBS"))]
    ready = sum(1 for t in obs if str(t.get("build_ready")).lower() == "true" or t.get("build_ready") is True)
    drift_count = int(drift.get("incident_count") or 0)
    score = 0.0
    if obs:
        score += (ready / len(obs)) * 0.6
    score += 0.4 if drift_count <= 1 else 0.0
    verdict = _verdict(score, good=0.8, mixed=0.55)
    action = (
        "Keep Operator-Now focused: surface top blockers and reduce drift incidents to <=1/day."
        if verdict != "good"
        else "Keep observatory front page action-focused and preserve drift checks."
    )
    return {
        "name": "Observatory Usability",
        "question": "Can the operator identify top actions in under 90 seconds?",
        "evidence": f"observatory_tasks={len(obs)} build_ready={ready} drift_incidents={drift_count}",
        "verdict": verdict,
        "action": action,
    }


def _pulse_section(widgets_data: Dict[str, Any], endpoints_data: Dict[str, Any]) -> Dict[str, Any]:
    widgets = widgets_data.get("widgets")
    if not isinstance(widgets, list):
        widgets = []
    endpoints = endpoints_data.get("endpoints")
    if not isinstance(endpoints, list):
        endpoints = []
    endpoint_ids = {str(e.get("id")) for e in endpoints if isinstance(e, dict) and e.get("id")}
    live = [w for w in widgets if isinstance(w, dict) and str(w.get("status")) != "dead"]
    dead = [w for w in widgets if isinstance(w, dict) and str(w.get("status")) == "dead"]
    mapped_live = [w for w in live if str(w.get("endpoint") or "") in endpoint_ids]
    coverage = (len(mapped_live) / len(live)) if live else 0.0
    score = coverage * 0.7 + (0.3 if len(dead) == 0 else 0.0)
    verdict = _verdict(score, good=0.85, mixed=0.6)
    action = (
        "Finish endpoint rewiring coverage and keep dead widgets hidden by default."
        if verdict != "good"
        else "Maintain live endpoint coverage and monitor stale-widget regressions."
    )
    return {
        "name": "Pulse Utility",
        "question": "Is Pulse showing only trustworthy, live, action-driving panes?",
        "evidence": f"live_widgets={len(live)} mapped_live={len(mapped_live)} dead_widgets={len(dead)} coverage={round(coverage, 3)}",
        "verdict": verdict,
        "action": action,
    }


def _action_quality(sections: List[Dict[str, Any]]) -> str:
    with_actions = sum(1 for s in sections if str(s.get("action") or "").strip())
    non_bad = sum(1 for s in sections if str(s.get("verdict")) != "bad")
    if with_actions >= 5 and non_bad >= 4:
        return "systematic"
    if with_actions >= 4:
        return "improving"
    return "ad_hoc"


def build_snapshot(
    *,
    memory_snapshot_path: Path = MEMORY_SNAPSHOT,
    suppression_audit_path: Path = SUPPRESSION_AUDIT,
    build_queue_path: Path = BUILD_QUEUE,
    pulse_widgets_path: Path = PULSE_WIDGETS,
    pulse_endpoints_path: Path = PULSE_ENDPOINTS,
    drift_snapshot_path: Path = DRIFT_SNAPSHOT,
) -> Dict[str, Any]:
    memory = _read_json(memory_snapshot_path)
    suppression = _read_json(suppression_audit_path)
    queue = _read_json(build_queue_path)
    widgets = _read_json(pulse_widgets_path)
    endpoints = _read_json(pulse_endpoints_path)
    drift = _read_json(drift_snapshot_path)

    sections = [
        _memory_section(memory),
        _advisory_section(suppression),
        _website_section(queue),
        _observatory_section(queue, drift),
        _pulse_section(widgets, endpoints),
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
        "daily_action_quality": _action_quality(sections),
        "system28_learning": _system28_metrics(),
    }


def render_report(snapshot: Dict[str, Any]) -> str:
    lines = [
        "# Nightly 5-Section Self-Interrogation",
        "",
        f"- Generated: {snapshot.get('generated_at')}",
        f"- Daily action quality: **{snapshot.get('daily_action_quality')}**",
        "",
    ]

    s28 = snapshot.get("system28_learning") if isinstance(snapshot.get("system28_learning"), dict) else {}
    if s28.get("available"):
        lines.extend(
            [
                "## System 28 Learning (Elevation)",
                f"- Verdict: **{s28.get('verdict')}** (score={s28.get('score')})",
                f"- Attempted/Updated: {s28.get('attempted')} / {s28.get('updated')} (rate={s28.get('update_rate')})",
                f"- Avg unified gain: {s28.get('avg_unified_gain')}",
                f"- Unsuppressed count: {s28.get('unsuppressed_count')}",
                f"- Source: `{s28.get('source_file')}`",
                "",
            ]
        )
    else:
        lines.extend([
            "## System 28 Learning (Elevation)",
            f"- Status: {s28.get('evidence', 'not available')}",
            "",
        ])
    for idx, section in enumerate(snapshot.get("sections", []), start=1):
        lines.extend(
            [
                f"## Section {idx}: {section.get('name')}",
                f"- Question: {section.get('question')}",
                f"- Evidence: {section.get('evidence')}",
                f"- Verdict: **{section.get('verdict')}**",
                f"- Action: {section.get('action')}",
                "",
            ]
        )
    lines.extend(
        [
            "## Global Top Actions",
            "1. Execute the highest-impact action from each non-good section.",
            "2. Re-run drift and memory observatory checks after changes.",
            "3. Update queue status + evidence links for tomorrow's run.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(snapshot: Dict[str, Any], *, output_dir: Path = DEFAULT_REPORT_DIR) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    report_path = output_dir / f"{day}_nightly_self_interrogation.md"
    json_path = output_dir / f"{day}_nightly_self_interrogation.json"
    report_path.write_text(render_report(snapshot), encoding="utf-8")
    json_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return {"report": report_path, "json": json_path}


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate nightly 5-section self-interrogation report")
    ap.add_argument("--json-only", action="store_true", help="Print JSON snapshot only")
    args = ap.parse_args()

    snapshot = build_snapshot()
    if args.json_only:
        print(json.dumps(snapshot, indent=2))
        return 0
    outputs = write_outputs(snapshot)
    print(json.dumps({"daily_action_quality": snapshot["daily_action_quality"], "outputs": {k: str(v) for k, v in outputs.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
