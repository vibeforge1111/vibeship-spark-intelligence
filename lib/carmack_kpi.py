"""Carmack KPI scorecard helpers for Spark runtime reviews."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import time


SPARK_DIR = Path.home() / ".spark"
_ALPHA_ADVISORY_LOG = SPARK_DIR / "advisory_engine_alpha.jsonl"
_COMPAT_ADVISORY_LOG = SPARK_DIR / "advisory_engine.jsonl"
ADVISORY_LOG = _ALPHA_ADVISORY_LOG if _ALPHA_ADVISORY_LOG.exists() else _COMPAT_ADVISORY_LOG
ADVICE_FEEDBACK_REQUESTS = SPARK_DIR / "advice_feedback_requests.jsonl"
EFFECTIVENESS_FILE = SPARK_DIR / "advisor" / "effectiveness.json"
SYNC_STATS_FILE = SPARK_DIR / "sync_stats.json"
CHIP_MERGE_FILE = SPARK_DIR / "chip_merge_state.json"

DEFAULT_ALERT_THRESHOLDS = {
    "max_bridge_heartbeat_age_s": 120.0,
    "min_core_reliability": 0.75,
    "max_noise_burden": 0.65,
    "min_gaur": 0.20,
}


def _safe_ratio(num: float, den: float) -> Optional[float]:
    if den <= 0:
        return None
    return float(num) / float(den)


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonl(path: Path, limit: int = 0) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    if limit and limit > 0:
        lines = lines[-int(limit):]
    rows: List[Dict[str, Any]] = []
    for line in lines:
        raw = (line or "").strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _count_advisory_events(rows: List[Dict[str, Any]], start_ts: float, end_ts: float) -> Dict[str, Any]:
    counts: Counter[str] = Counter()
    total = 0
    for row in rows:
        ts = float(row.get("ts") or 0.0)
        if ts < start_ts or ts >= end_ts:
            continue
        total += 1
        counts[str(row.get("event") or "unknown")] += 1
    emitted = int(counts.get("emitted", 0))
    fallback_emit = int(counts.get("fallback_emit", 0))
    delivered = emitted + fallback_emit
    no_emit = int(counts.get("no_emit", 0))
    synth_empty = int(counts.get("synth_empty", 0))
    duplicate_suppressed = int(counts.get("duplicate_suppressed", 0))
    noise_num = no_emit + synth_empty + duplicate_suppressed
    return {
        "event_counts": dict(counts),
        "total_events": total,
        "emitted": emitted,
        "fallback_emit": fallback_emit,
        "delivered": delivered,
        "no_emit": no_emit,
        "synth_empty": synth_empty,
        "duplicate_suppressed": duplicate_suppressed,
        "fallback_burden": _safe_ratio(fallback_emit, delivered),
        "noise_burden": _safe_ratio(noise_num, total),
    }


def _count_emitted_advice_items(rows: List[Dict[str, Any]], start_ts: float, end_ts: float) -> int:
    total = 0
    for row in rows:
        ts = float(row.get("created_at") or 0.0)
        if ts < start_ts or ts >= end_ts:
            continue
        advice_ids = row.get("advice_ids")
        if isinstance(advice_ids, list):
            total += len(advice_ids)
    return total


def _feedback_schema_stats(rows: List[Dict[str, Any]], start_ts: float, end_ts: float) -> Dict[str, Any]:
    total_rows = 0
    schema_v2_rows = 0
    legacy_rows = 0
    items_total = 0
    items_schema_v2 = 0
    items_legacy = 0

    for row in rows:
        ts = float(row.get("created_at") or 0.0)
        if ts < start_ts or ts >= end_ts:
            continue
        total_rows += 1
        advice_ids = row.get("advice_ids")
        n = len(advice_ids) if isinstance(advice_ids, list) else 0
        items_total += n

        schema_version = int(row.get("schema_version") or 0)
        if schema_version >= 2:
            schema_v2_rows += 1
            items_schema_v2 += n
        else:
            legacy_rows += 1
            items_legacy += n

    return {
        "rows_total": int(total_rows),
        "rows_schema_v2": int(schema_v2_rows),
        "rows_legacy": int(legacy_rows),
        "schema_v2_ratio": _safe_ratio(schema_v2_rows, total_rows),
        "items_total": int(items_total),
        "items_schema_v2": int(items_schema_v2),
        "items_legacy": int(items_legacy),
    }


def _count_good_advice_outcomes(recent_outcomes: Dict[str, Any], start_ts: float, end_ts: float) -> Dict[str, int]:
    total = 0
    followed = 0
    helpful = 0
    for meta in recent_outcomes.values():
        if not isinstance(meta, dict):
            continue
        ts = float(meta.get("ts") or 0.0)
        if ts < start_ts or ts >= end_ts:
            continue
        total += 1
        if bool(meta.get("followed_counted")):
            followed += 1
        if bool(meta.get("helpful_counted")):
            helpful += 1
    return {"outcome_rows": total, "followed": followed, "helpful": helpful}


def _window_metrics(
    *,
    advisory_rows: List[Dict[str, Any]],
    feedback_rows: List[Dict[str, Any]],
    recent_outcomes: Dict[str, Any],
    start_ts: float,
    end_ts: float,
) -> Dict[str, Any]:
    event_stats = _count_advisory_events(advisory_rows, start_ts, end_ts)
    feedback_schema = _feedback_schema_stats(feedback_rows, start_ts, end_ts)
    emitted_items = int(feedback_schema["items_total"])
    emitted_items_schema_v2 = int(feedback_schema["items_schema_v2"])
    outcome_stats = _count_good_advice_outcomes(recent_outcomes, start_ts, end_ts)
    good_used_raw = int(outcome_stats["helpful"])
    followed_raw = int(outcome_stats["followed"])
    good_used = min(good_used_raw, emitted_items)
    followed_used = min(followed_raw, emitted_items)
    good_used_schema_v2 = min(good_used_raw, emitted_items_schema_v2)
    followed_used_schema_v2 = min(followed_raw, emitted_items_schema_v2)
    gaur = _safe_ratio(good_used, emitted_items)
    gaur_schema_v2 = _safe_ratio(good_used_schema_v2, emitted_items_schema_v2)
    return {
        **event_stats,
        "emitted_advice_items": emitted_items,
        "emitted_advice_items_schema_v2": emitted_items_schema_v2,
        "emitted_advice_items_legacy": int(feedback_schema["items_legacy"]),
        "feedback_rows_total": int(feedback_schema["rows_total"]),
        "feedback_rows_schema_v2": int(feedback_schema["rows_schema_v2"]),
        "feedback_rows_legacy": int(feedback_schema["rows_legacy"]),
        "feedback_schema_v2_ratio": feedback_schema.get("schema_v2_ratio"),
        "good_advice_used": int(good_used),
        "good_advice_used_raw": int(good_used_raw),
        "good_advice_used_schema_v2": int(good_used_schema_v2),
        "followed_advice": int(followed_used),
        "followed_advice_raw": int(followed_raw),
        "followed_advice_schema_v2": int(followed_used_schema_v2),
        "outcome_overflow_clamped": bool(good_used_raw > emitted_items or followed_raw > emitted_items),
        "gaur": gaur,
        "gaur_schema_v2": gaur_schema_v2,
        "quality_gate_schema_version": 2,
        "quality_gate_emitted_items": int(emitted_items_schema_v2),
        "quality_gate_ready": bool(emitted_items_schema_v2 > 0),
    }


def _delta(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None:
        return None
    return float(current) - float(previous)


def _trend(current: Optional[float], previous: Optional[float], eps: float = 1e-9) -> str:
    if current is None or previous is None:
        return "unknown"
    d = current - previous
    if d > eps:
        return "up"
    if d < -eps:
        return "down"
    return "flat"


def _service_effective_running(name: str, svc: Dict[str, Any]) -> bool:
    """Robust running/health interpretation for core reliability scoring."""
    if not isinstance(svc, dict):
        return False
    if bool(svc.get("running")):
        return True

    # HTTP services may report running=False transiently; healthy endpoint implies alive.
    if name in {"sparkd", "dashboard", "pulse", "meta_ralph"} and bool(svc.get("healthy")):
        return True

    # Loop workers: process_running and heartbeat freshness are stronger signals.
    if name in {"bridge_worker", "scheduler"}:
        if bool(svc.get("process_running")):
            return True
        if bool(svc.get("heartbeat_fresh")):
            return True

    # Watchdog: a PID usually means active management loop.
    if name == "watchdog":
        try:
            return int(svc.get("pid") or 0) > 0
        except Exception:
            return False

    return False


def _core_reliability(status: Dict[str, Any]) -> Dict[str, Any]:
    core_keys = ("sparkd", "bridge_worker", "scheduler", "watchdog")
    running = 0
    details: Dict[str, bool] = {}
    for key in core_keys:
        svc = status.get(key) if isinstance(status, dict) else {}
        ok = _service_effective_running(key, svc if isinstance(svc, dict) else {})
        details[key] = ok
        if ok:
            running += 1
    ratio = _safe_ratio(running, len(core_keys))
    return {
        "core_running": running,
        "core_total": len(core_keys),
        "core_reliability": ratio,
        "core_effective_running": details,
    }


def _service_status_snapshot() -> Dict[str, Any]:
    try:
        from lib.service_control import service_status

        return service_status(include_pulse_probe=False)
    except Exception:
        return {}


def _sample_failure_snapshot(limit: int = 12) -> Dict[str, Any]:
    rows = _read_jsonl(ADVISORY_LOG, limit=max(40, int(limit * 4)))
    interesting = {
        "engine_error",
        "fallback_emit_failed",
        "global_dedupe_suppressed",
        "low_auth_global_suppressed",
        "synth_empty",
        "no_advice",
    }
    out: List[Dict[str, Any]] = []
    for row in reversed(rows):
        event = str(row.get("event") or "")
        if event not in interesting:
            continue
        out.append(
            {
                "ts": float(row.get("ts") or 0.0),
                "event": event,
                "tool": str(row.get("tool") or ""),
                "trace_id": str(row.get("trace_id") or ""),
                "route": str(row.get("route") or ""),
                "error_code": str(row.get("error_code") or ""),
                "error_kind": str(row.get("error_kind") or ""),
            }
        )
        if len(out) >= max(1, int(limit)):
            break
    out.reverse()
    return {"sampled_failures": out, "sample_count": len(out)}


def build_scorecard(window_hours: float = 4.0, now_ts: Optional[float] = None) -> Dict[str, Any]:
    now = float(now_ts if now_ts is not None else time.time())
    window_s = max(300.0, float(window_hours) * 3600.0)
    current_start = now - window_s
    previous_start = now - (2.0 * window_s)

    advisory_rows = _read_jsonl(ADVISORY_LOG)
    feedback_rows = _read_jsonl(ADVICE_FEEDBACK_REQUESTS)
    effectiveness = _read_json(EFFECTIVENESS_FILE)
    recent_outcomes = effectiveness.get("recent_outcomes") if isinstance(effectiveness, dict) else {}
    if not isinstance(recent_outcomes, dict):
        recent_outcomes = {}

    current = _window_metrics(
        advisory_rows=advisory_rows,
        feedback_rows=feedback_rows,
        recent_outcomes=recent_outcomes,
        start_ts=current_start,
        end_ts=now,
    )
    previous = _window_metrics(
        advisory_rows=advisory_rows,
        feedback_rows=feedback_rows,
        recent_outcomes=recent_outcomes,
        start_ts=previous_start,
        end_ts=current_start,
    )

    status = _service_status_snapshot()
    core = _core_reliability(status)

    sync_stats = _read_json(SYNC_STATS_FILE)
    chip_state = _read_json(CHIP_MERGE_FILE)
    chip_last = chip_state.get("last_stats") if isinstance(chip_state, dict) else {}
    if not isinstance(chip_last, dict):
        chip_last = {}

    metrics = {
        "gaur": {
            # Quality KPI is gated on deterministic join schema only.
            "current": current.get("gaur_schema_v2"),
            "previous": previous.get("gaur_schema_v2"),
        },
        "gaur_all": {
            "current": current.get("gaur"),
            "previous": previous.get("gaur"),
        },
        "fallback_burden": {
            "current": current.get("fallback_burden"),
            "previous": previous.get("fallback_burden"),
        },
        "noise_burden": {
            "current": current.get("noise_burden"),
            "previous": previous.get("noise_burden"),
        },
        "core_reliability": {
            "current": core.get("core_reliability"),
            "previous": None,
        },
        "feedback_schema_v2_ratio": {
            "current": current.get("feedback_schema_v2_ratio"),
            "previous": previous.get("feedback_schema_v2_ratio"),
        },
    }
    for _, row in metrics.items():
        row["delta"] = _delta(row.get("current"), row.get("previous"))
        row["trend"] = _trend(row.get("current"), row.get("previous"))

    return {
        "generated_at": now,
        "window_hours": float(window_hours),
        "windows": {
            "current": {"start": current_start, "end": now},
            "previous": {"start": previous_start, "end": current_start},
        },
        "current": current,
        "previous": previous,
        "metrics": metrics,
        "core": core,
        "service_status": status,
        "sync": {
            "last_full_sync": sync_stats.get("last_full_sync"),
            "total_syncs": sync_stats.get("total_syncs"),
            "adapters": (sync_stats.get("adapters") or {}),
        },
        "chip_merge": {
            "last_merge": chip_state.get("last_merge"),
            "last_stats": chip_last,
        },
    }


def build_health_alert(
    scorecard: Dict[str, Any],
    *,
    thresholds: Optional[Dict[str, float]] = None,
    include_snapshot_on_breach: bool = True,
) -> Dict[str, Any]:
    """Build summary-first health alert with optional sampled debug snapshot.

    Returns a compact summary suitable for webhook/cron notifications. When
    thresholds are breached, includes a lightweight sampled failure snapshot for
    debuggability (without dumping full logs).
    """
    cfg = dict(DEFAULT_ALERT_THRESHOLDS)
    for k, v in (thresholds or {}).items():
        try:
            cfg[str(k)] = float(v)
        except Exception:
            continue

    breaches: List[Dict[str, Any]] = []
    status = scorecard.get("service_status") if isinstance(scorecard, dict) else {}
    bridge = status.get("bridge_worker") if isinstance(status, dict) else {}
    hb_age = bridge.get("heartbeat_age_s") if isinstance(bridge, dict) else None
    if hb_age is not None and float(hb_age) > float(cfg["max_bridge_heartbeat_age_s"]):
        breaches.append(
            {
                "kind": "bridge_heartbeat_stale",
                "value": float(hb_age),
                "threshold": float(cfg["max_bridge_heartbeat_age_s"]),
                "direction": "max",
            }
        )

    core_rel = (((scorecard.get("core") or {}).get("core_reliability")) if isinstance(scorecard, dict) else None)
    if core_rel is not None and float(core_rel) < float(cfg["min_core_reliability"]):
        breaches.append(
            {
                "kind": "core_reliability_low",
                "value": float(core_rel),
                "threshold": float(cfg["min_core_reliability"]),
                "direction": "min",
            }
        )

    gaur = (((scorecard.get("metrics") or {}).get("gaur") or {}).get("current")) if isinstance(scorecard, dict) else None
    if gaur is not None and float(gaur) < float(cfg["min_gaur"]):
        breaches.append(
            {
                "kind": "gaur_low",
                "value": float(gaur),
                "threshold": float(cfg["min_gaur"]),
                "direction": "min",
            }
        )

    noise = (((scorecard.get("metrics") or {}).get("noise_burden") or {}).get("current")) if isinstance(scorecard, dict) else None
    if noise is not None and float(noise) > float(cfg["max_noise_burden"]):
        breaches.append(
            {
                "kind": "noise_burden_high",
                "value": float(noise),
                "threshold": float(cfg["max_noise_burden"]),
                "direction": "max",
            }
        )

    summary = {
        "generated_at": float(scorecard.get("generated_at") or time.time()),
        "window_hours": float(scorecard.get("window_hours") or 0.0),
        "status": "breach" if breaches else "ok",
        "breach_count": len(breaches),
        "breaches": breaches,
        "thresholds": cfg,
        "headline": (
            "Health thresholds breached" if breaches else "Health within thresholds"
        ),
    }

    if breaches and include_snapshot_on_breach:
        summary["snapshot"] = {
            "current": {
                "event_counts": ((scorecard.get("current") or {}).get("event_counts") or {}),
                "delivered": int(((scorecard.get("current") or {}).get("delivered") or 0)),
                "gaur": gaur,
                "noise_burden": noise,
            },
            "service": {
                "sparkd": ((status or {}).get("sparkd") or {}),
                "bridge_worker": ((status or {}).get("bridge_worker") or {}),
                "scheduler": ((status or {}).get("scheduler") or {}),
                "watchdog": ((status or {}).get("watchdog") or {}),
            },
            **_sample_failure_snapshot(limit=10),
        }

    return summary
