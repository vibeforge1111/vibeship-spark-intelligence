"""Provider-specific canary checks using advisory quality spine events."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ProviderCanaryConfig:
    spark_dir: Path
    providers: List[str]
    window_s: int = 6 * 3600
    min_events_per_provider: int = 10
    min_known_helpfulness: int = 3
    min_helpful_rate_pct: float = 40.0
    min_right_on_time_rate_pct: float = 35.0
    max_unknown_rate_pct: float = 90.0
    refresh_spine: bool = True


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _tail_jsonl(path: Path, max_rows: int) -> List[Dict[str, Any]]:
    if not path.exists() or max_rows <= 0:
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-max_rows:]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _refresh_quality_spine(spark_dir: Path) -> Dict[str, Any]:
    from .advisory_quality_spine import run_advisory_quality_spine_default

    out = run_advisory_quality_spine_default(spark_dir=spark_dir, write_files=True)
    return out.get("summary", {}) if isinstance(out, dict) else {}


def _pct(numer: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return round((100.0 * float(numer) / float(denom)), 2)


def run_provider_canary(cfg: ProviderCanaryConfig) -> Dict[str, Any]:
    if cfg.refresh_spine:
        _refresh_quality_spine(cfg.spark_dir)

    events_file = cfg.spark_dir / "advisor" / "advisory_quality_events.jsonl"
    rows = _tail_jsonl(events_file, 120000)
    now_ts = time.time()
    cutoff = now_ts - max(60, int(cfg.window_s))

    providers = [str(p).strip().lower() for p in (cfg.providers or []) if str(p).strip()]
    if not providers:
        providers = ["codex", "claude", "openclaw"]

    per_provider: Dict[str, Dict[str, Any]] = {}
    for provider in providers:
        pr_rows = [
            r for r in rows
            if _norm_text(r.get("provider")).lower() == provider
            and _safe_float(r.get("emitted_ts"), 0.0) >= cutoff
        ]
        total = len(pr_rows)
        known = 0
        helpful = 0
        right_on_time = 0
        unknown = 0
        impact_sum = 0.0
        for row in pr_rows:
            label = _norm_text(row.get("helpfulness_label")).lower()
            if label in {"helpful", "unhelpful", "harmful"}:
                known += 1
            if label == "helpful":
                helpful += 1
            if label == "unknown":
                unknown += 1
            if _norm_text(row.get("timing_bucket")).lower() == "right_on_time":
                right_on_time += 1
            impact_sum += _safe_float(row.get("impact_score"), 0.0)

        avg_impact = round(impact_sum / max(total, 1), 4) if total else 0.0
        helpful_rate = _pct(helpful, known if known > 0 else 0)
        right_rate = _pct(right_on_time, total if total > 0 else 0)
        unknown_rate = _pct(unknown, total if total > 0 else 0)
        active = total > 0
        reasons: List[str] = []
        passed = True
        if active:
            if total < int(cfg.min_events_per_provider):
                passed = False
                reasons.append(f"events<{int(cfg.min_events_per_provider)}")
            if known < int(cfg.min_known_helpfulness):
                passed = False
                reasons.append(f"known_helpfulness<{int(cfg.min_known_helpfulness)}")
            if known >= int(cfg.min_known_helpfulness) and helpful_rate < float(cfg.min_helpful_rate_pct):
                passed = False
                reasons.append(f"helpful_rate<{float(cfg.min_helpful_rate_pct):.1f}%")
            if right_rate < float(cfg.min_right_on_time_rate_pct):
                passed = False
                reasons.append(f"right_on_time_rate<{float(cfg.min_right_on_time_rate_pct):.1f}%")
            if unknown_rate > float(cfg.max_unknown_rate_pct):
                passed = False
                reasons.append(f"unknown_rate>{float(cfg.max_unknown_rate_pct):.1f}%")
        else:
            passed = True

        per_provider[provider] = {
            "active": active,
            "passed": bool(passed),
            "reasons": reasons,
            "events": total,
            "known_helpfulness": known,
            "helpful": helpful,
            "right_on_time": right_on_time,
            "unknown": unknown,
            "helpful_rate_pct": helpful_rate,
            "right_on_time_rate_pct": right_rate,
            "unknown_rate_pct": unknown_rate,
            "avg_impact_score": avg_impact,
        }

    active_providers = [p for p, row in per_provider.items() if bool(row.get("active"))]
    failing_active = [p for p in active_providers if not bool((per_provider.get(p) or {}).get("passed"))]
    ready = len(failing_active) == 0

    return {
        "generated_at": time.time(),
        "window_s": int(cfg.window_s),
        "thresholds": {
            "min_events_per_provider": int(cfg.min_events_per_provider),
            "min_known_helpfulness": int(cfg.min_known_helpfulness),
            "min_helpful_rate_pct": float(cfg.min_helpful_rate_pct),
            "min_right_on_time_rate_pct": float(cfg.min_right_on_time_rate_pct),
            "max_unknown_rate_pct": float(cfg.max_unknown_rate_pct),
        },
        "providers": per_provider,
        "active_providers": active_providers,
        "failing_active": failing_active,
        "ready": bool(ready),
    }


def run_provider_canary_default(
    *,
    spark_dir: Optional[Path] = None,
    providers: Optional[List[str]] = None,
    window_s: int = 6 * 3600,
    min_events_per_provider: int = 10,
    min_known_helpfulness: int = 3,
    min_helpful_rate_pct: float = 40.0,
    min_right_on_time_rate_pct: float = 35.0,
    max_unknown_rate_pct: float = 90.0,
    refresh_spine: bool = True,
) -> Dict[str, Any]:
    cfg = ProviderCanaryConfig(
        spark_dir=(spark_dir or (Path.home() / ".spark")),
        providers=list(providers or []),
        window_s=max(60, int(window_s)),
        min_events_per_provider=max(1, int(min_events_per_provider)),
        min_known_helpfulness=max(1, int(min_known_helpfulness)),
        min_helpful_rate_pct=max(0.0, float(min_helpful_rate_pct)),
        min_right_on_time_rate_pct=max(0.0, float(min_right_on_time_rate_pct)),
        max_unknown_rate_pct=max(0.0, min(100.0, float(max_unknown_rate_pct))),
        refresh_spine=bool(refresh_spine),
    )
    return run_provider_canary(cfg)
