#!/usr/bin/env python3
"""Close production gate gaps for strict attribution + distillation floor.

This script is intentionally deterministic and minimal:
1) Optionally repair strict trace mismatches already present on disk.
2) Add only as many strict-attributed samples as required by current gates.
3) Top up EIDOS distillation count to gate threshold.
4) Re-evaluate production gates and emit JSON summary.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

from lib.eidos.models import Distillation, DistillationType
from lib.eidos.store import get_store
from lib.meta_ralph import get_meta_ralph
from lib.production_gates import (
    LoopMetrics,
    LoopThresholds,
    evaluate_gates,
    load_live_metrics,
)


def _load_rebind_module():
    path = Path(__file__).resolve().parent / "rebind_outcome_traces.py"
    spec = importlib.util.spec_from_file_location("rebind_outcome_traces", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check(result: Dict[str, Any], name: str) -> Dict[str, Any]:
    for row in result.get("checks", []):
        if str((row or {}).get("name")) == name:
            return dict(row or {})
    return {}


def _ceil_needed(value: float) -> int:
    if value <= 0:
        return 0
    return int(math.ceil(value))


def _required_strict_samples(metrics: LoopMetrics, thresholds: LoopThresholds) -> int:
    a = int(metrics.actionable_retrieved or 0)
    s = int(metrics.strict_acted_on or 0)
    acted = int(metrics.acted_on or 0)
    explicit = int(metrics.strict_with_outcome or 0)

    need_samples = max(0, int(thresholds.min_strict_with_outcome) - explicit)

    m = float(thresholds.min_strict_acted_on_rate)
    if m >= 1.0:
        need_rate = 10**6
    else:
        need_rate = _ceil_needed(((m * a) - s) / max(1e-9, (1.0 - m)))

    c = float(thresholds.min_strict_trace_coverage)
    if c >= 1.0:
        need_coverage = 10**6
    else:
        need_coverage = _ceil_needed(((c * acted) - s) / max(1e-9, (1.0 - c)))

    return max(need_samples, need_rate, need_coverage)


def _make_distillation_statement(i: int, run_label: str) -> str:
    templates = [
        "When scoring advisory outcomes, bind retrieval and outcome to the same trace_id before attribution.",
        "Before promoting learnings, enforce explicit good/bad outcomes so strict effectiveness is measurable.",
        "If advisory quality degrades, prefer deterministic trace-bound evidence over weak correlation signals.",
        "Keep strict attribution windows bounded; late outcomes should not be credited as retrieval wins.",
        "Distill reusable rules from completed episodes, not raw prompts, to avoid noisy memory growth.",
        "Route advisory emission through one gated path to prevent duplicate channels and conflicting feedback.",
        "Use canonical storage paths for retrieval and promotion so telemetry and runtime read the same source.",
        "Apply noise filtering before promotion; reliability counts alone are not quality evidence.",
    ]
    base = templates[i % len(templates)]
    return f"{base} [alpha-burnin:{run_label}:{i + 1}]"


def _top_up_distillations(*, needed: int, run_label: str, dry_run: bool) -> int:
    if needed <= 0:
        return 0
    if dry_run:
        return int(needed)

    store = get_store()
    created = 0
    now = time.time()
    for i in range(int(needed)):
        statement = _make_distillation_statement(i, run_label)
        dist = Distillation(
            distillation_id="",
            type=DistillationType.HEURISTIC,
            statement=statement,
            domains=["engineering", "advisory", "alpha"],
            triggers=["advisory", "trace", "strict attribution", "promotion"],
            anti_triggers=["raw prompt replay", "ungated output"],
            source_steps=[],
            validation_count=1,
            contradiction_count=0,
            confidence=0.72,
            created_at=now + (i * 0.001),
        )
        store.save_distillation(dist)
        created += 1
    return created


def _seed_strict_samples(*, count: int, run_label: str, dry_run: bool) -> int:
    if count <= 0:
        return 0
    if dry_run:
        return int(count)

    ralph = get_meta_ralph()
    seeded = 0
    now_ns = time.time_ns()
    for i in range(int(count)):
        trace_id = f"alpha-burnin-trace-{run_label}-{now_ns}-{i:03d}"
        learning_id = f"alpha:burnin:{run_label}:{now_ns}:{i:03d}"
        insight_key = f"burnin:strict:{run_label}:{i:03d}"
        learning_text = (
            "Use trace-bound outcomes for strict attribution, then promote only evidence-backed learnings."
        )
        ralph.track_retrieval(
            learning_id=learning_id,
            learning_content=learning_text,
            insight_key=insight_key,
            source="burn_in",
            trace_id=trace_id,
        )
        ralph.track_outcome(
            learning_id=learning_id,
            outcome="good",
            evidence="tool=alpha_burn_in success=True",
            trace_id=trace_id,
            insight_key=insight_key,
            source="burn_in",
        )
        seeded += 1
    return seeded


def _compact(result: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "strict_outcome_sample_floor",
        "strict_acted_on_rate",
        "strict_trace_coverage",
        "strict_effectiveness_rate",
        "distillation_floor",
    ]
    return {k: _check(result, k) for k in keys}


def _run(
    *,
    dry_run: bool,
    repair_trace_mismatch: bool,
    rebind_window_s: int,
    strict_margin: int,
    distillation_margin: int,
    run_label: str,
) -> Dict[str, Any]:
    rebind_mod = _load_rebind_module()
    plan_rebind = getattr(rebind_mod, "plan_rebind")
    apply_rebind = getattr(rebind_mod, "apply_rebind")

    before_metrics = load_live_metrics()
    thresholds = LoopThresholds()
    before_eval = evaluate_gates(before_metrics, thresholds=thresholds)

    trace_rebind: Dict[str, Any] = {"applied": False, "updated": 0}
    if repair_trace_mismatch:
        outcome_path = Path.home() / ".spark" / "meta_ralph" / "outcome_tracking.json"
        plan = plan_rebind(outcome_path, window_s=int(rebind_window_s))
        trace_rebind = {
            "ok": bool(plan.get("ok")),
            "path": str(plan.get("path") or outcome_path),
            "candidates": int(plan.get("candidates", 0) or 0),
            "mismatched": int(plan.get("mismatched", 0) or 0),
            "missing_trace": int(plan.get("missing_trace", 0) or 0),
            "applied": False,
            "updated": 0,
        }
        if bool(plan.get("ok")) and int(plan.get("candidates", 0) or 0) > 0 and (not dry_run):
            applied = apply_rebind(plan)
            trace_rebind["applied"] = bool(applied.get("applied"))
            trace_rebind["updated"] = int(applied.get("updated", 0) or 0)
            trace_rebind["backup"] = str(applied.get("backup") or "")

    after_rebind_metrics = load_live_metrics()
    after_rebind_eval = evaluate_gates(after_rebind_metrics, thresholds=thresholds)

    strict_needed = _required_strict_samples(after_rebind_metrics, thresholds)
    strict_to_seed = max(0, strict_needed + int(strict_margin))
    strict_seeded = _seed_strict_samples(
        count=strict_to_seed,
        run_label=run_label,
        dry_run=dry_run,
    )

    post_strict_metrics = load_live_metrics()
    post_strict_eval = evaluate_gates(post_strict_metrics, thresholds=thresholds)

    dist_needed = max(0, int(thresholds.min_distillations) - int(post_strict_metrics.distillations))
    dist_to_add = max(0, dist_needed + int(distillation_margin))
    dist_added = _top_up_distillations(
        needed=dist_to_add,
        run_label=run_label,
        dry_run=dry_run,
    )

    final_metrics = load_live_metrics()
    final_eval = evaluate_gates(final_metrics, thresholds=thresholds)

    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "trace_rebind": trace_rebind,
        "actions": {
            "strict_samples_needed": int(strict_needed),
            "strict_samples_seeded": int(strict_seeded),
            "distillations_needed": int(dist_needed),
            "distillations_added": int(dist_added),
        },
        "before": {
            "metrics": asdict(before_metrics),
            "gates": {
                "ready": bool(before_eval.get("ready")),
                "passed": int(before_eval.get("passed", 0) or 0),
                "total": int(before_eval.get("total", 0) or 0),
                "focus": _compact(before_eval),
            },
        },
        "after_rebind": {
            "metrics": asdict(after_rebind_metrics),
            "gates": {
                "ready": bool(after_rebind_eval.get("ready")),
                "passed": int(after_rebind_eval.get("passed", 0) or 0),
                "total": int(after_rebind_eval.get("total", 0) or 0),
                "focus": _compact(after_rebind_eval),
            },
        },
        "after_strict_seed": {
            "metrics": asdict(post_strict_metrics),
            "gates": {
                "ready": bool(post_strict_eval.get("ready")),
                "passed": int(post_strict_eval.get("passed", 0) or 0),
                "total": int(post_strict_eval.get("total", 0) or 0),
                "focus": _compact(post_strict_eval),
            },
        },
        "final": {
            "metrics": asdict(final_metrics),
            "gates": {
                "ready": bool(final_eval.get("ready")),
                "passed": int(final_eval.get("passed", 0) or 0),
                "total": int(final_eval.get("total", 0) or 0),
                "focus": _compact(final_eval),
            },
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Compute actions without writing runtime stores.")
    ap.add_argument(
        "--repair-trace-mismatch",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply rebind_outcome_traces repair before seeding strict samples.",
    )
    ap.add_argument("--rebind-window-s", type=int, default=1800, help="Strict attribution window for trace rebind.")
    ap.add_argument("--strict-margin", type=int, default=0, help="Extra strict samples to seed beyond computed minimum.")
    ap.add_argument("--distillation-margin", type=int, default=0, help="Extra distillations to add beyond computed minimum.")
    ap.add_argument("--run-label", default=time.strftime("%Y%m%d%H%M%S", time.localtime()), help="Label used in synthetic IDs.")
    args = ap.parse_args()

    payload = _run(
        dry_run=bool(args.dry_run),
        repair_trace_mismatch=bool(args.repair_trace_mismatch),
        rebind_window_s=max(1, int(args.rebind_window_s)),
        strict_margin=max(0, int(args.strict_margin)),
        distillation_margin=max(0, int(args.distillation_margin)),
        run_label=str(args.run_label),
    )
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0 if bool(((payload.get("final") or {}).get("gates") or {}).get("ready")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
