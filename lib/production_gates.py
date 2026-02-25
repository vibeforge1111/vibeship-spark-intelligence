"""Production loop gates for Spark iteration cycles.

Defines measurable quality and readiness gates so each iteration can be
evaluated consistently from live storage state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Dict, List

from .config_authority import resolve_section


SPARK_DIR = Path.home() / ".spark"
COGNITIVE_FILE = SPARK_DIR / "cognitive_insights.json"
EFFECTIVENESS_FILE = SPARK_DIR / "advisor" / "effectiveness.json"
CHIP_INSIGHTS_DIR = SPARK_DIR / "chip_insights"
TUNEABLES_FILE = SPARK_DIR / "tuneables.json"


@dataclass
class LoopMetrics:
    total_stored: int = 0
    total_retrieved: int = 0
    actionable_retrieved: int = 0
    ignored_non_actionable: int = 0
    retrieval_rate: float = 0.0
    acted_on: int = 0
    acted_on_rate: float = 0.0
    effectiveness_rate: float = 0.0
    strict_acted_on: int = 0
    strict_with_outcome: int = 0
    strict_acted_on_rate: float = 0.0
    strict_trace_coverage: float = 0.0
    strict_effectiveness_rate: float = 0.0
    strict_require_trace: bool = False
    strict_window_s: int = 0
    quality_rate: float = 0.0
    quality_rate_samples: int = 0
    quality_rate_filtered_pipeline_tests: int = 0
    quality_rate_filtered_duplicates: int = 0
    distillations: int = 0
    queue_depth: int = 0
    advice_total: int = 0
    advice_followed: int = 0
    advice_helpful: int = 0
    chip_insights: int = 0
    chip_to_cognitive_ratio: float = 0.0
    advisory_readiness_ratio: float = 0.0
    advisory_freshness_ratio: float = 0.0
    advisory_avg_effectiveness: float = 0.0
    advisory_store_queue_depth: int = 0
    advisory_inactive_ratio: float = 0.0
    advisory_top_category_concentration: float = 0.0


@dataclass
class LoopThresholds:
    min_retrieval_rate: float = 0.10
    min_acted_on_rate: float = 0.30
    min_effectiveness_rate: float = 0.50
    min_strict_acted_on_rate: float = 0.20
    min_strict_trace_coverage: float = 0.50
    min_strict_effectiveness_rate: float = 0.50
    min_strict_with_outcome: int = 5
    require_strict_trace_binding: bool = True
    max_strict_window_s: int = 1800
    min_distillations: int = 5
    min_quality_rate: float = 0.30
    max_quality_rate: float = 0.60
    # Meta-Ralph quality band is now telemetry-only by default.
    # Keep data visible, but do not block production readiness on this signal.
    enforce_meta_ralph_quality_band: bool = False
    min_quality_samples: int = 50
    max_queue_depth: int = 2000
    max_chip_to_cognitive_ratio: float = 100.0
    min_advisory_readiness_ratio: float = 0.40
    min_advisory_freshness_ratio: float = 0.35
    max_advisory_inactive_ratio: float = 0.40
    min_advisory_avg_effectiveness: float = 0.35
    max_advisory_store_queue_depth: int = 1200
    max_advisory_top_category_concentration: float = 0.85


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _count_chip_insights(chip_dir: Path) -> int:
    if not chip_dir.exists():
        return 0
    total = 0
    for path in chip_dir.glob("*.jsonl"):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                total += sum(1 for _ in f)
        except Exception:
            continue
    return total


def _count_stored_learnings(path: Path) -> int:
    data = _read_json(path, {})
    if isinstance(data, dict):
        if "insights" in data and isinstance(data.get("insights"), list):
            return len(data.get("insights") or [])
        return len(data)
    if isinstance(data, list):
        return len(data)
    return 0


def _read_meta_metrics() -> Dict[str, Any]:
    try:
        from lib.meta_ralph import get_meta_ralph

        ralph = get_meta_ralph()
        stats = ralph.get_stats()
        out = stats.get("outcome_stats") or {}
        source_attr: Dict[str, Any] = {}
        try:
            source_attr = ralph.get_source_attribution(limit=8)
        except Exception:
            source_attr = {}
        totals = source_attr.get("totals") if isinstance(source_attr, dict) else {}
        if not isinstance(totals, dict):
            totals = {}
        mode = source_attr.get("attribution_mode") if isinstance(source_attr, dict) else {}
        if not isinstance(mode, dict):
            mode = {}
        raw_strict_eff = totals.get("strict_effectiveness_rate")
        strict_effectiveness_rate = (
            float(raw_strict_eff) if raw_strict_eff is not None else 0.0
        )
        total_retrieved = int(out.get("total_tracked", 0) or 0)
        raw_actionable = out.get("actionable_tracked")
        if raw_actionable is None:
            actionable_retrieved = total_retrieved
        else:
            actionable_retrieved = int(raw_actionable or 0)
        return {
            "total_retrieved": total_retrieved,
            "actionable_retrieved": max(0, actionable_retrieved),
            "ignored_non_actionable": int(out.get("ignored_non_actionable", 0) or 0),
            "acted_on": int(out.get("acted_on", 0) or 0),
            "effectiveness_rate": float(out.get("effectiveness_rate", 0.0) or 0.0),
            "strict_acted_on": int(totals.get("strict_acted_on", 0) or 0),
            "strict_with_outcome": int(
                totals.get("strict_with_explicit_outcome", 0) or 0
            ),
            "strict_effectiveness_rate": strict_effectiveness_rate,
            "strict_require_trace": bool(mode.get("require_trace", False)),
            "strict_window_s": int(mode.get("window_s", 0) or 0),
            "quality_rate": float(
                stats.get("quality_rate", stats.get("pass_rate", 0.0)) or 0.0
            ),
            "quality_rate_samples": int(stats.get("quality_rate_window_samples", 0) or 0),
            "quality_rate_filtered_pipeline_tests": int(
                stats.get("quality_rate_window_filtered_pipeline_tests", 0) or 0
            ),
            "quality_rate_filtered_duplicates": int(
                stats.get("quality_rate_window_filtered_duplicates", 0) or 0
            ),
        }
    except Exception:
        return {}


def _read_distillation_count() -> int:
    try:
        from lib.eidos import get_store

        return int((get_store().get_stats() or {}).get("distillations", 0) or 0)
    except Exception:
        return 0


def _read_queue_depth() -> int:
    try:
        from lib.queue import count_events

        return int(count_events())
    except Exception:
        return 0


def _read_effectiveness_metrics() -> Dict[str, int]:
    """Read advisor effectiveness counters with on-read normalization."""
    data = _read_json(EFFECTIVENESS_FILE, {})
    if not isinstance(data, dict):
        data = {}

    def _as_int(value: Any) -> int:
        try:
            return max(0, int(value))
        except Exception:
            return 0

    total = _as_int(data.get("total_advice_given", 0))
    followed = _as_int(data.get("total_followed", 0))
    helpful = _as_int(data.get("total_helpful", 0))
    invalid = followed > total or helpful > followed

    if invalid:
        try:
            from lib.advisor import repair_effectiveness_counters

            repaired = repair_effectiveness_counters() or {}
            after = repaired.get("after") if isinstance(repaired, dict) else {}
            if isinstance(after, dict):
                total = _as_int(after.get("total_advice_given", total))
                followed = _as_int(after.get("total_followed", followed))
                helpful = _as_int(after.get("total_helpful", helpful))
        except Exception:
            # Fallback to bounded values for reporting if repair is unavailable.
            followed = min(followed, total)
            helpful = min(helpful, followed)

    return {
        "total_advice_given": total,
        "total_followed": min(followed, total),
        "total_helpful": min(helpful, min(followed, total)),
    }


def load_live_metrics() -> LoopMetrics:
    """Collect loop metrics from live local stores."""
    stored = _count_stored_learnings(COGNITIVE_FILE)
    chip_count = _count_chip_insights(CHIP_INSIGHTS_DIR)

    retrieved = 0
    actionable_retrieved = 0
    ignored_non_actionable = 0
    acted_on = 0
    effectiveness_rate = 0.0
    strict_acted_on = 0
    strict_with_outcome = 0
    strict_effectiveness_rate = 0.0
    strict_require_trace = False
    strict_window_s = 0
    quality_rate = 0.0
    quality_rate_samples = 0
    quality_rate_filtered_pipeline_tests = 0
    quality_rate_filtered_duplicates = 0
    distillations = 0
    queue_depth = 0
    advice_total = 0
    advice_followed = 0
    advice_helpful = 0
    advisory_readiness_ratio = 0.0
    advisory_freshness_ratio = 0.0
    advisory_avg_effectiveness = 0.0
    advisory_store_queue_depth = 0
    advisory_inactive_ratio = 0.0
    advisory_top_category_concentration = 0.0

    meta = _read_meta_metrics()
    if meta:
        retrieved = int(meta.get("total_retrieved", 0) or 0)
        raw_actionable = meta.get("actionable_retrieved")
        if raw_actionable is None:
            actionable_retrieved = retrieved
        else:
            actionable_retrieved = int(raw_actionable or 0)
        ignored_non_actionable = int(meta.get("ignored_non_actionable", 0) or 0)
        acted_on = int(meta.get("acted_on", 0) or 0)
        effectiveness_rate = float(meta.get("effectiveness_rate", 0.0) or 0.0)
        strict_acted_on = int(meta.get("strict_acted_on", 0) or 0)
        strict_with_outcome = int(meta.get("strict_with_outcome", 0) or 0)
        strict_effectiveness_rate = float(
            meta.get("strict_effectiveness_rate", 0.0) or 0.0
        )
        strict_require_trace = bool(meta.get("strict_require_trace", False))
        strict_window_s = int(meta.get("strict_window_s", 0) or 0)
        quality_rate = float(meta.get("quality_rate", 0.0) or 0.0)
        quality_rate_samples = int(meta.get("quality_rate_samples", 0) or 0)
        quality_rate_filtered_pipeline_tests = int(
            meta.get("quality_rate_filtered_pipeline_tests", 0) or 0
        )
        quality_rate_filtered_duplicates = int(
            meta.get("quality_rate_filtered_duplicates", 0) or 0
        )

    distillations = _read_distillation_count()
    queue_depth = _read_queue_depth()
    try:
        from .advisory_packet_store import get_store_status

        packet_store_status = get_store_status()
        advisory_readiness_ratio = float(packet_store_status.get("readiness_ratio", 0.0) or 0.0)
        advisory_freshness_ratio = float(packet_store_status.get("freshness_ratio", 0.0) or 0.0)
        advisory_avg_effectiveness = float(packet_store_status.get("avg_effectiveness_score", 0.0) or 0.0)
        advisory_store_queue_depth = int(packet_store_status.get("queue_depth", 0) or 0)
        advisory_inactive_ratio = float(packet_store_status.get("inactive_ratio", 0.0) or 0.0)
        advisory_top_category_concentration = float(
            packet_store_status.get("top_category_concentration", 0.0) or 0.0
        )
    except Exception:
        pass

    eff = _read_effectiveness_metrics()
    advice_total = int(eff.get("total_advice_given", 0) or 0)
    advice_followed = int(eff.get("total_followed", 0) or 0)
    advice_helpful = int(eff.get("total_helpful", 0) or 0)

    retrieval_rate = (retrieved / max(stored, 1)) if stored > 0 else 0.0
    acted_on_rate = (
        acted_on / max(actionable_retrieved, 1)
        if actionable_retrieved > 0
        else 0.0
    )
    strict_acted_on_rate = (
        strict_acted_on / max(actionable_retrieved, 1)
        if actionable_retrieved > 0
        else 0.0
    )
    strict_trace_coverage = (
        strict_acted_on / max(acted_on, 1)
        if acted_on > 0
        else 0.0
    )
    chip_ratio = (chip_count / max(stored, 1)) if stored > 0 else float(chip_count > 0)

    return LoopMetrics(
        total_stored=stored,
        total_retrieved=retrieved,
        actionable_retrieved=actionable_retrieved,
        ignored_non_actionable=ignored_non_actionable,
        retrieval_rate=retrieval_rate,
        acted_on=acted_on,
        acted_on_rate=acted_on_rate,
        effectiveness_rate=effectiveness_rate,
        strict_acted_on=strict_acted_on,
        strict_with_outcome=strict_with_outcome,
        strict_acted_on_rate=strict_acted_on_rate,
        strict_trace_coverage=strict_trace_coverage,
        strict_effectiveness_rate=strict_effectiveness_rate,
        strict_require_trace=strict_require_trace,
        strict_window_s=strict_window_s,
        quality_rate=quality_rate,
        quality_rate_samples=quality_rate_samples,
        quality_rate_filtered_pipeline_tests=quality_rate_filtered_pipeline_tests,
        quality_rate_filtered_duplicates=quality_rate_filtered_duplicates,
        distillations=distillations,
        queue_depth=queue_depth,
        advice_total=advice_total,
        advice_followed=advice_followed,
        advice_helpful=advice_helpful,
        chip_insights=chip_count,
        chip_to_cognitive_ratio=chip_ratio,
        advisory_readiness_ratio=advisory_readiness_ratio,
        advisory_freshness_ratio=advisory_freshness_ratio,
        advisory_avg_effectiveness=advisory_avg_effectiveness,
        advisory_store_queue_depth=advisory_store_queue_depth,
        advisory_inactive_ratio=advisory_inactive_ratio,
        advisory_top_category_concentration=advisory_top_category_concentration,
    )


def _load_loop_thresholds_from_tuneables(
    path: Path | None = None,
    *,
    baseline_path: Path | None = None,
) -> LoopThresholds:
    """Load production-gate thresholds through config authority."""
    default = LoopThresholds()
    cfg = resolve_section(
        "production_gates",
        baseline_path=baseline_path,
        runtime_path=(path or TUNEABLES_FILE),
    ).data
    if not isinstance(cfg, dict):
        return default

    values: Dict[str, Any] = {}
    for f in fields(LoopThresholds):
        if f.name not in cfg:
            continue
        raw = cfg.get(f.name)
        try:
            if f.type is bool:
                if isinstance(raw, bool):
                    values[f.name] = raw
                elif isinstance(raw, (int, float)):
                    values[f.name] = bool(raw)
                else:
                    values[f.name] = str(raw).strip().lower() in {"1", "true", "yes", "on"}
            elif f.type is int:
                values[f.name] = int(raw)
            elif f.type is float:
                values[f.name] = float(raw)
            else:
                values[f.name] = raw
        except Exception:
            continue

    try:
        return LoopThresholds(**values)
    except Exception:
        return default


def evaluate_gates(
    metrics: LoopMetrics,
    thresholds: LoopThresholds | None = None,
) -> Dict[str, Any]:
    """Evaluate metrics against production loop thresholds."""
    t = thresholds or _load_loop_thresholds_from_tuneables()
    checks: List[Dict[str, Any]] = []

    def _add(
        name: str,
        ok: bool,
        value: Any,
        target: str,
        recommendation: str,
    ) -> None:
        checks.append(
            {
                "name": name,
                "ok": bool(ok),
                "value": value,
                "target": target,
                "recommendation": recommendation,
            }
        )

    _add(
        "effectiveness_counter_integrity",
        metrics.advice_followed <= metrics.advice_total and metrics.advice_helpful <= metrics.advice_followed,
        {
            "advice_total": metrics.advice_total,
            "advice_followed": metrics.advice_followed,
            "advice_helpful": metrics.advice_helpful,
        },
        "helpful <= followed <= total",
        "Repair effectiveness counters and dedupe outcome counting.",
    )
    _add(
        "retrieval_rate",
        metrics.retrieval_rate >= t.min_retrieval_rate,
        round(metrics.retrieval_rate, 4),
        f">= {t.min_retrieval_rate:.2f}",
        "Improve advisor retrieval coverage and trigger rules.",
    )
    _add(
        "acted_on_rate",
        metrics.acted_on_rate >= t.min_acted_on_rate,
        round(metrics.acted_on_rate, 4),
        f">= {t.min_acted_on_rate:.2f}",
        "Increase advice actionability and UX surfacing before tool execution.",
    )
    strict_policy_ok = (
        (not t.require_strict_trace_binding or metrics.strict_require_trace)
        and metrics.strict_window_s > 0
        and metrics.strict_window_s <= t.max_strict_window_s
    )
    _add(
        "strict_attribution_policy",
        strict_policy_ok,
        {
            "require_trace": metrics.strict_require_trace,
            "window_s": metrics.strict_window_s,
        },
        f"trace_required={t.require_strict_trace_binding}, 0<window<={t.max_strict_window_s}s",
        "Enable strict trace binding and keep attribution window bounded.",
    )
    _add(
        "strict_outcome_sample_floor",
        metrics.strict_with_outcome >= t.min_strict_with_outcome,
        metrics.strict_with_outcome,
        f">= {t.min_strict_with_outcome}",
        "Collect more explicit good/bad outcomes with trace_id to calibrate strict attribution.",
    )
    _add(
        "strict_acted_on_rate",
        metrics.strict_acted_on_rate >= t.min_strict_acted_on_rate,
        round(metrics.strict_acted_on_rate, 4),
        f">= {t.min_strict_acted_on_rate:.2f}",
        "Raise trace-binding quality and reduce latency/window misses before scoring readiness.",
    )
    _add(
        "strict_trace_coverage",
        metrics.strict_trace_coverage >= t.min_strict_trace_coverage,
        round(metrics.strict_trace_coverage, 4),
        f">= {t.min_strict_trace_coverage:.2f}",
        "Ensure acted-on outcomes stay bound to the originating retrieval trace.",
    )
    strict_eff_ok = (
        metrics.strict_with_outcome >= t.min_strict_with_outcome
        and metrics.strict_effectiveness_rate >= t.min_strict_effectiveness_rate
    )
    _add(
        "strict_effectiveness_rate",
        strict_eff_ok,
        {
            "rate": round(metrics.strict_effectiveness_rate, 4),
            "samples": metrics.strict_with_outcome,
        },
        f">= {t.min_strict_effectiveness_rate:.2f} with >= {t.min_strict_with_outcome} samples",
        "Improve strict-attributed outcomes before promoting to production defaults.",
    )
    _add(
        "effectiveness_rate",
        metrics.effectiveness_rate >= t.min_effectiveness_rate,
        round(metrics.effectiveness_rate, 4),
        f">= {t.min_effectiveness_rate:.2f}",
        "Demote low-impact learnings and tune ranking weights toward proven outcomes.",
    )
    _add(
        "distillation_floor",
        metrics.distillations >= t.min_distillations,
        metrics.distillations,
        f">= {t.min_distillations}",
        "Increase distillation yield and episode completion quality.",
    )
    advisory_store_active = any(
        (
            metrics.advisory_readiness_ratio > 0.0,
            metrics.advisory_freshness_ratio > 0.0,
            metrics.advisory_avg_effectiveness > 0.0,
            metrics.advisory_store_queue_depth > 0,
            metrics.advisory_inactive_ratio > 0.0,
            metrics.advisory_top_category_concentration > 0.0,
        )
    )
    _add(
        "advisory_store_readiness",
        (not advisory_store_active) or (metrics.advisory_readiness_ratio >= t.min_advisory_readiness_ratio),
        round(metrics.advisory_readiness_ratio, 3),
        f">= {t.min_advisory_readiness_ratio:.2f}",
        "Improve packet freshness in the advisory store and stabilize exact lookup keys.",
    )
    _add(
        "advisory_store_freshness",
        (not advisory_store_active) or (metrics.advisory_freshness_ratio >= t.min_advisory_freshness_ratio),
        round(metrics.advisory_freshness_ratio, 3),
        f">= {t.min_advisory_freshness_ratio:.2f}",
        "Tune packet TTL and invalidation policy to keep useful packets fresh.",
    )
    _add(
        "advisory_store_inactive",
        (not advisory_store_active) or (metrics.advisory_inactive_ratio <= t.max_advisory_inactive_ratio),
        round(metrics.advisory_inactive_ratio, 3),
        f"<= {t.max_advisory_inactive_ratio:.2f}",
        "Reduce invalidation churn and strengthen packet reuse quality control.",
    )
    _add(
        "advisory_store_effectiveness",
        (not advisory_store_active) or (metrics.advisory_avg_effectiveness >= t.min_advisory_avg_effectiveness),
        round(metrics.advisory_avg_effectiveness, 3),
        f">= {t.min_advisory_avg_effectiveness:.2f}",
        "Increase explicit feedback/actual outcome capture for packet ranking signal quality.",
    )
    _add(
        "advisory_store_queue_depth",
        (not advisory_store_active) or (metrics.advisory_store_queue_depth <= t.max_advisory_store_queue_depth),
        metrics.advisory_store_queue_depth,
        f"<= {t.max_advisory_store_queue_depth}",
        "Increase worker throughput or raise prefetch thresholding to reduce packet queue pressure.",
    )
    _add(
        "advisory_store_category_diversity",
        (not advisory_store_active) or (metrics.advisory_top_category_concentration <= t.max_advisory_top_category_concentration),
        round(metrics.advisory_top_category_concentration, 3),
        f"<= {t.max_advisory_top_category_concentration:.2f}",
        "Diversify packet authorship/categorization so single domains don’t dominate.",
    )
    meta_ralph_quality_ok = (
        (not t.enforce_meta_ralph_quality_band)
        or metrics.quality_rate_samples < t.min_quality_samples
        or (t.min_quality_rate <= metrics.quality_rate <= t.max_quality_rate)
    )
    _add(
        "meta_ralph_quality_band",
        meta_ralph_quality_ok,
        {
            "quality_rate": round(metrics.quality_rate, 4),
            "samples": int(metrics.quality_rate_samples),
            "filtered_pipeline_tests": int(metrics.quality_rate_filtered_pipeline_tests),
            "filtered_duplicates": int(metrics.quality_rate_filtered_duplicates),
            "enforced": bool(t.enforce_meta_ralph_quality_band and metrics.quality_rate_samples >= t.min_quality_samples),
            "mode": "telemetry_only" if not t.enforce_meta_ralph_quality_band else "enforced",
        },
        (
            f"{t.min_quality_rate:.2f}..{t.max_quality_rate:.2f} "
            f"(enforced after >= {t.min_quality_samples} samples; toggle enforce_meta_ralph_quality_band)"
        ),
        (
            "Meta-Ralph is telemetry-only by default. "
            "If re-enabled and out-of-band, tune primitive filtering and quality thresholds."
        ),
    )
    _add(
        "chip_noise_ratio",
        metrics.chip_to_cognitive_ratio <= t.max_chip_to_cognitive_ratio,
        round(metrics.chip_to_cognitive_ratio, 3),
        f"<= {t.max_chip_to_cognitive_ratio:.1f}",
        "Raise chip quality gates or reduce noisy triggers in high-volume chips.",
    )
    _add(
        "queue_backpressure",
        metrics.queue_depth <= t.max_queue_depth,
        metrics.queue_depth,
        f"<= {t.max_queue_depth}",
        "Increase bridge cadence or processing batch size to reduce backlog.",
    )

    passed = sum(1 for c in checks if c["ok"])
    total = len(checks)
    return {
        "passed": passed,
        "total": total,
        "ready": passed == total,
        "checks": checks,
    }


def format_gate_report(metrics: LoopMetrics, result: Dict[str, Any]) -> str:
    """Render a compact report for CLI/scripts."""
    lines = []
    lines.append("=" * 66)
    lines.append(" SPARK PRODUCTION LOOP GATES")
    lines.append("=" * 66)
    lines.append(
        f"Gate status: {'READY' if result.get('ready') else 'NOT READY'} "
        f"({result.get('passed', 0)}/{result.get('total', 0)} passed)"
    )
    lines.append("")
    lines.append("Metrics:")
    lines.append(
        f"  stored={metrics.total_stored} retrieved={metrics.total_retrieved} "
        f"actionable={metrics.actionable_retrieved} acted_on={metrics.acted_on}"
    )
    lines.append(
        f"  retrieval_rate={metrics.retrieval_rate:.1%} acted_on_rate={metrics.acted_on_rate:.1%} "
        f"effectiveness={metrics.effectiveness_rate:.1%}"
    )
    lines.append(
        f"  advisory_readiness={metrics.advisory_readiness_ratio:.1%} "
        f"advisory_freshness={metrics.advisory_freshness_ratio:.1%} "
        f"advisory_effectiveness={metrics.advisory_avg_effectiveness:.1%} "
        f"advisory_inactive={metrics.advisory_inactive_ratio:.1%} "
        f"advisory_queue={metrics.advisory_store_queue_depth} "
        f"advisory_cat_concentration={metrics.advisory_top_category_concentration:.1%}"
    )
    lines.append(
        f"  strict_acted_on={metrics.strict_acted_on} strict_with_outcome={metrics.strict_with_outcome} "
        f"strict_rate={metrics.strict_acted_on_rate:.1%} strict_trace_coverage={metrics.strict_trace_coverage:.1%} "
        f"strict_effectiveness={metrics.strict_effectiveness_rate:.1%} "
        f"strict_mode=(trace={metrics.strict_require_trace}, window_s={metrics.strict_window_s})"
    )
    lines.append(
        f"  quality_rate={metrics.quality_rate:.1%} quality_samples={metrics.quality_rate_samples} "
        f"filtered_pipeline_tests={metrics.quality_rate_filtered_pipeline_tests} "
        f"filtered_duplicates={metrics.quality_rate_filtered_duplicates} "
        f"distillations={metrics.distillations} "
        f"chip_ratio={metrics.chip_to_cognitive_ratio:.1f} queue_depth={metrics.queue_depth} "
        f"non_actionable={metrics.ignored_non_actionable}"
    )
    lines.append("")
    lines.append("Checks:")
    for check in result.get("checks", []):
        status = "PASS" if check.get("ok") else "FAIL"
        lines.append(
            f"  [{status}] {check.get('name')}: value={check.get('value')} target={check.get('target')}"
        )
        if not check.get("ok"):
            lines.append(f"         action: {check.get('recommendation')}")
    lines.append("=" * 66)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Hot-reload registration
# ---------------------------------------------------------------------------

def _reload_production_gates_from(_cfg) -> None:
    """Hot-reload callback — config is read fresh each call, no cached state."""
    pass


try:
    from .tuneables_reload import register_reload as _pg_register
    _pg_register("production_gates", _reload_production_gates_from, label="production_gates.reload")
except Exception:
    pass
