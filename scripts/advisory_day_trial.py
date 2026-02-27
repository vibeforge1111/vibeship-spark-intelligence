#!/usr/bin/env python3
"""Run and summarize a real-time advisory day trial (start/snapshot/close)."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lib.action_matcher import FEEDBACK_FILE, OUTCOMES_FILE, match_actions
from lib.advice_feedback import REQUESTS_FILE
from lib.advisory_parser import parse_feedback_requests
from lib.production_gates import evaluate_gates, load_live_metrics


ROOT = Path(__file__).resolve().parents[1]
SPARK_DIR = Path.home() / ".spark"
DEFAULT_TRIAL_ROOT = ROOT / "docs" / "reports" / "day_trials"
DEFAULT_TUNEABLES = SPARK_DIR / "tuneables.json"
_ALPHA_ENGINE_FILE = SPARK_DIR / "advisory_engine_alpha.jsonl"
_COMPAT_ENGINE_FILE = SPARK_DIR / "advisory_engine.jsonl"
DEFAULT_ENGINE_FILE = _ALPHA_ENGINE_FILE if _ALPHA_ENGINE_FILE.exists() else _COMPAT_ENGINE_FILE
DEFAULT_MEMORY_CASES = ROOT / "benchmarks" / "data" / "memory_retrieval_eval_multidomain_real_user_2026_02_16.json"
DEFAULT_MEMORY_GATES = ROOT / "benchmarks" / "data" / "memory_retrieval_domain_gates_multidomain_v1.json"
DEFAULT_ADVISORY_CASES = ROOT / "benchmarks" / "data" / "advisory_quality_eval_seed.json"

EDIT_NOTE_TOKENS = ("edit", "edited", "tweak", "modified", "adapted", "changed")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_slug(text: str) -> str:
    out = "".join(ch if (ch.isalnum() or ch in {"_", "-"}) else "_" for ch in str(text or ""))
    out = "_".join(x for x in out.split("_") if x)
    return out.lower() or "trial"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Dict[str, Any]) -> Path:
    _ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _parse_ts(row: Dict[str, Any]) -> float:
    for key in ("created_at", "ts", "timestamp"):
        value = row.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            continue
    return 0.0


def _read_jsonl_since(path: Path, since_ts: float) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if _parse_ts(row) >= float(since_ts):
            out.append(row)
    return out


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _sha1_file(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha1()
    try:
        with path.open("rb") as f:
            while True:
                block = f.read(64 * 1024)
                if not block:
                    break
                h.update(block)
    except Exception:
        return ""
    return h.hexdigest()


def _status_from_feedback_row(row: Dict[str, Any]) -> str:
    status = str(row.get("status") or "").strip().lower()
    if status:
        return status
    followed = row.get("followed")
    if followed is True:
        return "acted"
    if followed is False:
        return "ignored"
    return "unknown"


def summarize_feedback_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    status_counts: Counter[str] = Counter()
    helpful_true = 0
    helpful_false = 0
    edited = 0
    total = 0
    for row in rows:
        total += 1
        status = _status_from_feedback_row(row)
        status_counts[status] += 1
        helpful = row.get("helpful")
        if helpful is True:
            helpful_true += 1
        elif helpful is False:
            helpful_false += 1
        notes = str(row.get("notes") or "").lower()
        if notes and any(tok in notes for tok in EDIT_NOTE_TOKENS):
            edited += 1

    acted = int(status_counts.get("acted", 0))
    rejected = int(status_counts.get("blocked", 0) + status_counts.get("harmful", 0))
    neutral = int(status_counts.get("ignored", 0) + status_counts.get("skipped", 0))
    noisy = int(rejected + helpful_false)
    non_followed = int(total - acted)
    return {
        "total_feedback": total,
        "status_counts": dict(status_counts),
        "acted": acted,
        "rejected": rejected,
        "neutral": neutral,
        "noisy": noisy,
        "edited": edited,
        "helpful_true": helpful_true,
        "helpful_false": helpful_false,
        "acceptance_rate": round((acted / total), 4) if total else 0.0,
        "override_rate": round((non_followed / total), 4) if total else 0.0,
        "noisy_rate": round((noisy / total), 4) if total else 0.0,
        "edited_rate": round((edited / total), 4) if total else 0.0,
    }


def _build_recommendation_index(request_rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for row in request_rows:
        advice_ids = [str(x).strip() for x in (row.get("advice_ids") or []) if str(x).strip()]
        advice_texts = [str(x).strip() for x in (row.get("advice_texts") or []) if str(x).strip()]
        sources = [str(x).strip() for x in (row.get("sources") or []) if str(x).strip()]
        for i, aid in enumerate(advice_ids):
            if aid in idx:
                continue
            recommendation = advice_texts[i] if i < len(advice_texts) else ""
            idx[aid] = {
                "recommendation": recommendation,
                "tool": str(row.get("tool") or ""),
                "trace_id": str(row.get("trace_id") or ""),
                "sources": sources,
                "created_at": _parse_ts(row),
            }
    return idx


def summarize_request_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    total_requests = 0
    advice_shown = 0
    tool_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    top_recommendations: List[Dict[str, Any]] = []
    seen_advice_ids: set[str] = set()
    for row in rows:
        total_requests += 1
        tool = str(row.get("tool") or "").strip() or "unknown"
        tool_counts[tool] += 1
        ids = [str(x).strip() for x in (row.get("advice_ids") or []) if str(x).strip()]
        texts = [str(x).strip() for x in (row.get("advice_texts") or []) if str(x).strip()]
        sources = [str(x).strip() for x in (row.get("sources") or []) if str(x).strip()]
        for src in sources:
            source_counts[src] += 1
        advice_shown += len(ids)
        for i, aid in enumerate(ids):
            if aid in seen_advice_ids:
                continue
            seen_advice_ids.add(aid)
            top_recommendations.append(
                {
                    "advice_id": aid,
                    "recommendation": texts[i] if i < len(texts) else "",
                    "tool": tool,
                    "sources": sources,
                    "created_at": _parse_ts(row),
                }
            )

    top_recommendations.sort(key=lambda x: float(x.get("created_at") or 0.0), reverse=True)
    return {
        "request_count": total_requests,
        "advice_shown_count": advice_shown,
        "by_tool": dict(tool_counts),
        "top_memory_sources": [{"source": k, "count": int(v)} for k, v in source_counts.most_common(8)],
        "recent_recommendations": top_recommendations[:8],
    }


def summarize_autoscore_items(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(items)
    total = len(rows)
    status_counts: Counter[str] = Counter(str(x.get("status") or "unknown") for x in rows)
    match_counts: Counter[str] = Counter(str(x.get("match_type") or "none") for x in rows)
    effect_counts: Counter[str] = Counter(str(x.get("effect") or "neutral") for x in rows)
    unresolved = int(status_counts.get("unresolved", 0))
    acted = int(status_counts.get("acted", 0))
    return {
        "total_items": total,
        "status_counts": dict(status_counts),
        "match_type_counts": dict(match_counts),
        "effect_counts": dict(effect_counts),
        "retrieval_match_rate": round((1.0 - (unresolved / total)), 4) if total else 0.0,
        "unresolved_rate": round((unresolved / total), 4) if total else 0.0,
        "positive_effect_rate": round((int(effect_counts.get("positive", 0)) / acted), 4) if acted else 0.0,
    }


def _build_wow_and_failures(
    feedback_rows: Iterable[Dict[str, Any]],
    rec_index: Dict[str, Dict[str, Any]],
    *,
    limit: int = 5,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    wow: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    seen_wow: set[str] = set()
    seen_fail: set[str] = set()

    rows = sorted(list(feedback_rows), key=_parse_ts, reverse=True)
    for row in rows:
        status = _status_from_feedback_row(row)
        helpful = row.get("helpful")
        notes = str(row.get("notes") or "").strip()
        for aid in [str(x).strip() for x in (row.get("advice_ids") or []) if str(x).strip()]:
            rec = rec_index.get(aid) or {}
            entry = {
                "advice_id": aid,
                "status": status,
                "helpful": helpful,
                "tool": rec.get("tool", ""),
                "recommendation": rec.get("recommendation", ""),
                "memory_sources": rec.get("sources", []),
                "notes": notes,
                "created_at": _parse_ts(row),
            }
            if (status == "acted" or helpful is True) and aid not in seen_wow and len(wow) < limit:
                wow.append(entry)
                seen_wow.add(aid)
            if (
                status in {"blocked", "harmful"}
                or helpful is False
                or status == "unresolved"
            ) and aid not in seen_fail and len(failures) < limit:
                failures.append(entry)
                seen_fail.add(aid)
        if len(wow) >= limit and len(failures) >= limit:
            break
    return wow, failures


def _latest_report(pattern: str) -> Optional[Path]:
    files = sorted((ROOT / "docs" / "reports").glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _run_canary_from_state(state: Dict[str, Any], timeout_s: int) -> Dict[str, Any]:
    canary = state.get("canary") or {}
    thresholds = state.get("thresholds") or {}
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_advisory_retrieval_canary.py"),
        "--memory-cases",
        str(canary.get("memory_cases") or DEFAULT_MEMORY_CASES),
        "--memory-gates",
        str(canary.get("memory_gates") or DEFAULT_MEMORY_GATES),
        "--advisory-cases",
        str(canary.get("advisory_cases") or DEFAULT_ADVISORY_CASES),
        "--memory-mrr-min",
        str(float(thresholds.get("memory_mrr_min", 0.245))),
        "--memory-gate-pass-rate-min",
        str(float(thresholds.get("memory_gate_pass_rate_min", 0.32))),
        "--advisory-score-min",
        str(float(thresholds.get("advisory_score_min", 0.49))),
        "--timeout-s",
        str(max(60, int(timeout_s))),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=max(120, int(timeout_s)),
        check=False,
    )
    out = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
    latest = _latest_report("*_advisory_retrieval_canary_*.json")
    payload = _read_json(latest, {}) if latest else {}
    return {
        "returncode": int(proc.returncode),
        "stdout": out[:6000],
        "report_path": str(latest) if latest else "",
        "report": payload if isinstance(payload, dict) else {},
    }


def _collect_trial_observations(
    *,
    started_at: float,
    max_match_window_s: float,
) -> Dict[str, Any]:
    request_rows = _read_jsonl_since(REQUESTS_FILE, started_at)
    feedback_rows = _read_jsonl_since(FEEDBACK_FILE, started_at)
    outcomes_rows = _read_jsonl_since(OUTCOMES_FILE, started_at)
    engine_rows = _read_jsonl_since(DEFAULT_ENGINE_FILE, started_at)

    advisories = [x for x in parse_feedback_requests(REQUESTS_FILE, limit=200000) if float(x.get("created_at") or 0.0) >= started_at]
    matches = match_actions(
        advisories,
        feedback_file=FEEDBACK_FILE,
        outcomes_file=OUTCOMES_FILE,
        max_match_window_s=max(0.0, float(max_match_window_s)),
    )
    item_rows: List[Dict[str, Any]] = []
    by_id = {str(m.get("advisory_instance_id") or ""): m for m in matches}
    for adv in advisories:
        aid = str(adv.get("advisory_instance_id") or "")
        match = by_id.get(aid, {})
        item_rows.append(
            {
                "advisory_instance_id": aid,
                "advisory_id": str(adv.get("advisory_id") or ""),
                "recommendation": str(adv.get("recommendation") or ""),
                "created_at": float(adv.get("created_at") or 0.0),
                "tool": str(adv.get("tool") or ""),
                "status": str(match.get("status") or "unresolved"),
                "match_type": str(match.get("match_type") or "none"),
                "effect": str(match.get("effect_hint") or "neutral"),
            }
        )

    request_summary = summarize_request_rows(request_rows)
    feedback_summary = summarize_feedback_rows(feedback_rows)
    autoscore_summary = summarize_autoscore_items(item_rows)
    rec_index = _build_recommendation_index(request_rows)
    wow, failures = _build_wow_and_failures(feedback_rows, rec_index, limit=5)

    return {
        "request_rows_count": len(request_rows),
        "feedback_rows_count": len(feedback_rows),
        "outcomes_rows_count": len(outcomes_rows),
        "engine_rows_count": len(engine_rows),
        "request_summary": request_summary,
        "feedback_summary": feedback_summary,
        "autoscore_summary": autoscore_summary,
        "wow_moments": wow,
        "top_failure_modes": failures,
    }


def _render_markdown(report: Dict[str, Any]) -> str:
    trial = report.get("trial") or {}
    obs = report.get("observations") or {}
    req = obs.get("request_summary") or {}
    fb = obs.get("feedback_summary") or {}
    auto = obs.get("autoscore_summary") or {}
    canary = report.get("canary") or {}
    canary_eval = ((canary.get("report") or {}).get("evaluation") or {})
    canary_metrics = canary_eval.get("metrics") or {}

    lines: List[str] = []
    lines.append("# Spark Advisory Day Trial Report")
    lines.append("")
    lines.append(f"- Trial id: `{trial.get('trial_id', '')}`")
    lines.append(f"- Stage: `{report.get('stage', '')}`")
    lines.append(f"- Generated at: `{report.get('generated_at', '')}`")
    lines.append(f"- Started at: `{trial.get('started_at_iso', '')}`")
    lines.append("")
    lines.append("## Engagement")
    lines.append("")
    lines.append(f"- Advisory requests: `{req.get('request_count', 0)}`")
    lines.append(f"- Advice shown: `{req.get('advice_shown_count', 0)}`")
    lines.append(f"- Feedback tags: `{fb.get('total_feedback', 0)}`")
    lines.append(f"- Acceptance rate: `{float(fb.get('acceptance_rate', 0.0)):.2%}`")
    lines.append(f"- Override rate: `{float(fb.get('override_rate', 0.0)):.2%}`")
    lines.append(f"- Noisy rate: `{float(fb.get('noisy_rate', 0.0)):.2%}`")
    lines.append(f"- Edited/adapted rate: `{float(fb.get('edited_rate', 0.0)):.2%}`")
    lines.append("")
    lines.append("## Retrieval Quality")
    lines.append("")
    lines.append(f"- Retrieval match rate: `{float(auto.get('retrieval_match_rate', 0.0)):.2%}`")
    lines.append(f"- Unresolved rate: `{float(auto.get('unresolved_rate', 0.0)):.2%}`")
    lines.append(f"- Positive effect rate: `{float(auto.get('positive_effect_rate', 0.0)):.2%}`")
    top_sources = req.get("top_memory_sources") or []
    if top_sources:
        lines.append("- Top memory sources:")
        for row in top_sources[:6]:
            lines.append(f"  - `{row.get('source')}`: `{row.get('count')}`")
    lines.append("")
    lines.append("## Wow Moments")
    lines.append("")
    wow = obs.get("wow_moments") or []
    if wow:
        for row in wow[:5]:
            lines.append(
                f"- `{row.get('tool')}` | {row.get('recommendation')[:140]} "
                f"(status=`{row.get('status')}`, helpful=`{row.get('helpful')}`)"
            )
    else:
        lines.append("- No high-confidence wow moments captured yet.")
    lines.append("")
    lines.append("## Top Failure Modes")
    lines.append("")
    failures = obs.get("top_failure_modes") or []
    if failures:
        for row in failures[:5]:
            lines.append(
                f"- `{row.get('tool')}` | {row.get('recommendation')[:140]} "
                f"(status=`{row.get('status')}`, notes=`{str(row.get('notes') or '')[:80]}`)"
            )
    else:
        lines.append("- No clear failure clusters captured in this window.")
    lines.append("")
    if canary:
        lines.append("## Canary")
        lines.append("")
        lines.append(f"- Return code: `{canary.get('returncode')}`")
        lines.append(f"- Report: `{canary.get('report_path')}`")
        if canary_metrics:
            lines.append(f"- Memory weighted MRR: `{float(canary_metrics.get('memory_weighted_mrr', 0.0)):.4f}`")
            lines.append(f"- Domain gate pass rate: `{float(canary_metrics.get('memory_domain_gate_pass_rate', 0.0)):.2%}`")
            lines.append(f"- Advisory winner score: `{float(canary_metrics.get('advisory_winner_score', 0.0)):.4f}`")
            lines.append(f"- Advisory winner profile: `{canary_metrics.get('advisory_winner_profile', 'n/a')}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _trial_dir(root: Path, trial_id: str) -> Path:
    return _ensure_dir(root / _safe_slug(trial_id))


def _state_path(root: Path, trial_id: str) -> Path:
    return _trial_dir(root, trial_id) / "state.json"


def _write_runbook(trial_dir: Path, trial_id: str) -> Path:
    text = f"""# Advisory Day Trial Commands

Trial id: `{trial_id}`

Tag outcomes during the day:

```bash
python scripts/advisory_tag_outcome.py --tool Bash --status acted --notes "helpful and used as-is"
python scripts/advisory_tag_outcome.py --tool Edit --status blocked --notes "noisy for this context"
python scripts/advisory_tag_outcome.py --tool Edit --status acted --notes "edited adaptation before applying"
```

Capture a mid-day snapshot:

```bash
python scripts/advisory_day_trial.py snapshot --trial-id {trial_id}
```

Close and generate final report:

```bash
python scripts/advisory_day_trial.py close --trial-id {trial_id}
```
"""
    path = trial_dir / "HOW_TO_RUN.md"
    path.write_text(text, encoding="utf-8")
    return path


def cmd_start(args: argparse.Namespace) -> int:
    trial_id = str(args.trial_id or f"advisory_day_{time.strftime('%Y%m%d_%H%M%S')}")
    root = Path(args.trial_root)
    trial_dir = _trial_dir(root, trial_id)
    state_path = trial_dir / "state.json"
    if state_path.exists() and not bool(args.overwrite):
        raise SystemExit(f"trial already exists: {state_path} (use --overwrite to replace)")

    metrics = dataclasses.asdict(load_live_metrics())
    line_counts = {
        "requests": _line_count(REQUESTS_FILE),
        "feedback": _line_count(FEEDBACK_FILE),
        "outcomes": _line_count(OUTCOMES_FILE),
        "engine": _line_count(DEFAULT_ENGINE_FILE),
    }
    started_at = time.time()
    state = {
        "trial_id": trial_id,
        "started_at": started_at,
        "started_at_iso": _utc_now_iso(),
        "planned_duration_h": float(args.duration_h),
        "max_match_window_s": float(args.max_match_window_s),
        "thresholds": {
            "memory_mrr_min": float(args.memory_mrr_min),
            "memory_gate_pass_rate_min": float(args.memory_gate_pass_rate_min),
            "advisory_score_min": float(args.advisory_score_min),
            "min_feedback_samples": int(args.min_feedback_samples),
            "min_acceptance_rate": float(args.min_acceptance_rate),
            "max_noisy_rate": float(args.max_noisy_rate),
            "max_unresolved_rate": float(args.max_unresolved_rate),
        },
        "canary": {
            "memory_cases": str(args.memory_cases),
            "memory_gates": str(args.memory_gates),
            "advisory_cases": str(args.advisory_cases),
        },
        "baseline": {
            "metrics": metrics,
            "line_counts": line_counts,
        },
        "tuneables": {
            "path": str(args.tuneables),
            "sha1": _sha1_file(Path(args.tuneables)),
        },
        "advisory_emit_expected": True,
        "env_snapshot": {
            "SPARK_ADVISORY_EMIT": os.environ.get("SPARK_ADVISORY_EMIT", ""),
        },
    }
    _write_json(state_path, state)
    runbook = _write_runbook(trial_dir, trial_id)
    print(f"trial_id={trial_id}")
    print(f"state={state_path}")
    print(f"runbook={runbook}")
    return 0


def _collect_report(
    *,
    stage: str,
    trial_id: str,
    state: Dict[str, Any],
    trial_dir: Path,
    run_canary: bool,
    timeout_s: int,
) -> Tuple[Dict[str, Any], Path, Path]:
    started_at = float(state.get("started_at") or 0.0)
    max_match_window_s = float(state.get("max_match_window_s") or 24 * 3600)
    obs = _collect_trial_observations(started_at=started_at, max_match_window_s=max_match_window_s)
    metrics = dataclasses.asdict(load_live_metrics())
    gates = evaluate_gates(load_live_metrics())

    canary_payload: Dict[str, Any] = {}
    if run_canary:
        canary_payload = _run_canary_from_state(state, timeout_s=timeout_s)

    report = {
        "generated_at": _utc_now_iso(),
        "stage": stage,
        "trial": {
            "trial_id": trial_id,
            "started_at": started_at,
            "started_at_iso": str(state.get("started_at_iso") or ""),
            "planned_duration_h": float(state.get("planned_duration_h") or 24.0),
        },
        "thresholds": state.get("thresholds") or {},
        "observations": obs,
        "live_metrics": metrics,
        "production_gates": gates,
        "canary": canary_payload,
    }

    th = state.get("thresholds") or {}
    fb = (obs.get("feedback_summary") or {})
    auto = (obs.get("autoscore_summary") or {})
    readiness_checks = {
        "feedback_sample_floor": int(fb.get("total_feedback", 0)) >= int(th.get("min_feedback_samples", 10)),
        "acceptance_rate": float(fb.get("acceptance_rate", 0.0)) >= float(th.get("min_acceptance_rate", 0.35)),
        "noisy_rate": float(fb.get("noisy_rate", 1.0)) <= float(th.get("max_noisy_rate", 0.35)),
        "unresolved_rate": float(auto.get("unresolved_rate", 1.0)) <= float(th.get("max_unresolved_rate", 0.5)),
    }
    if run_canary:
        readiness_checks["canary_promoted"] = int((report.get("canary") or {}).get("returncode", 2)) == 0
    report["day_trial_readiness"] = {
        "checks": readiness_checks,
        "ready": all(readiness_checks.values()),
    }

    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    json_path = trial_dir / f"{stage}_{stamp}.json"
    md_path = trial_dir / f"{stage}_{stamp}.md"
    _write_json(json_path, report)
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    return report, json_path, md_path


def cmd_snapshot(args: argparse.Namespace) -> int:
    trial_id = str(args.trial_id).strip()
    root = Path(args.trial_root)
    trial_dir = _trial_dir(root, trial_id)
    state = _read_json(trial_dir / "state.json", {})
    if not state:
        raise SystemExit(f"missing state file: {trial_dir / 'state.json'}")
    report, json_path, md_path = _collect_report(
        stage="snapshot",
        trial_id=trial_id,
        state=state,
        trial_dir=trial_dir,
        run_canary=bool(args.run_canary),
        timeout_s=int(args.timeout_s),
    )
    ready = bool((report.get("day_trial_readiness") or {}).get("ready"))
    print(f"trial_id={trial_id}")
    print(f"ready={ready}")
    print(f"report_json={json_path}")
    print(f"report_md={md_path}")
    return 0 if ready else 2


def cmd_close(args: argparse.Namespace) -> int:
    trial_id = str(args.trial_id).strip()
    root = Path(args.trial_root)
    trial_dir = _trial_dir(root, trial_id)
    state_path = trial_dir / "state.json"
    state = _read_json(state_path, {})
    if not state:
        raise SystemExit(f"missing state file: {state_path}")

    report, json_path, md_path = _collect_report(
        stage="close",
        trial_id=trial_id,
        state=state,
        trial_dir=trial_dir,
        run_canary=not bool(args.skip_canary),
        timeout_s=int(args.timeout_s),
    )
    state["closed_at"] = time.time()
    state["closed_at_iso"] = _utc_now_iso()
    state["last_close_report"] = str(json_path)
    _write_json(state_path, state)

    ready = bool((report.get("day_trial_readiness") or {}).get("ready"))
    print(f"trial_id={trial_id}")
    print(f"ready={ready}")
    print(f"report_json={json_path}")
    print(f"report_md={md_path}")
    return 0 if ready else 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Run Spark advisory day trial (start/snapshot/close).")
    ap.add_argument("--trial-root", default=str(DEFAULT_TRIAL_ROOT), help="Directory for trial state/reports.")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="Start a day trial and persist baseline contract.")
    p_start.add_argument("--trial-id", default="", help="Optional trial id.")
    p_start.add_argument("--duration-h", type=float, default=24.0, help="Planned trial duration in hours.")
    p_start.add_argument("--max-match-window-s", type=float, default=24 * 3600, help="Action-match time window.")
    p_start.add_argument("--overwrite", action="store_true", help="Overwrite existing state for trial-id.")
    p_start.add_argument("--tuneables", default=str(DEFAULT_TUNEABLES), help="Tuneables file to fingerprint.")
    p_start.add_argument("--memory-cases", default=str(DEFAULT_MEMORY_CASES))
    p_start.add_argument("--memory-gates", default=str(DEFAULT_MEMORY_GATES))
    p_start.add_argument("--advisory-cases", default=str(DEFAULT_ADVISORY_CASES))
    p_start.add_argument("--memory-mrr-min", type=float, default=0.245)
    p_start.add_argument("--memory-gate-pass-rate-min", type=float, default=0.32)
    p_start.add_argument("--advisory-score-min", type=float, default=0.49)
    p_start.add_argument("--min-feedback-samples", type=int, default=12)
    p_start.add_argument("--min-acceptance-rate", type=float, default=0.35)
    p_start.add_argument("--max-noisy-rate", type=float, default=0.35)
    p_start.add_argument("--max-unresolved-rate", type=float, default=0.55)
    p_start.set_defaults(func=cmd_start)

    p_snapshot = sub.add_parser("snapshot", help="Build an in-progress trial snapshot report.")
    p_snapshot.add_argument("--trial-id", required=True)
    p_snapshot.add_argument("--run-canary", action="store_true", help="Run canary in snapshot stage.")
    p_snapshot.add_argument("--timeout-s", type=int, default=1200)
    p_snapshot.set_defaults(func=cmd_snapshot)

    p_close = sub.add_parser("close", help="Close trial and write final report.")
    p_close.add_argument("--trial-id", required=True)
    p_close.add_argument("--skip-canary", action="store_true", help="Skip close-stage canary run.")
    p_close.add_argument("--timeout-s", type=int, default=1200)
    p_close.set_defaults(func=cmd_close)

    return ap


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
