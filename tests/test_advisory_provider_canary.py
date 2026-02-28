from __future__ import annotations

import json
import time
from pathlib import Path

from lib.advisory_provider_canary import ProviderCanaryConfig, run_provider_canary


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def test_provider_canary_passes_for_healthy_active_provider(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    now = time.time()
    rows = []
    labels = [
        "helpful",
        "helpful",
        "helpful",
        "helpful",
        "helpful",
        "unhelpful",
        "unhelpful",
        "unknown",
        "unknown",
        "helpful",
    ]
    for i, label in enumerate(labels):
        rows.append(
            {
                "provider": "codex",
                "emitted_ts": now - 30 - i,
                "helpfulness_label": label,
                "timing_bucket": "right_on_time" if i < 7 else "late",
                "impact_score": 0.8,
            }
        )
    _write_jsonl(spark_dir / "advisor" / "advisory_quality_events.jsonl", rows)

    out = run_provider_canary(
        ProviderCanaryConfig(
            spark_dir=spark_dir,
            providers=["codex"],
            window_s=3600,
            min_events_per_provider=10,
            min_known_helpfulness=3,
            min_helpful_rate_pct=40.0,
            min_right_on_time_rate_pct=35.0,
            max_unknown_rate_pct=90.0,
            refresh_spine=False,
        )
    )

    assert out["ready"] is True
    assert out["active_providers"] == ["codex"]
    assert out["failing_active"] == []
    codex = out["providers"]["codex"]
    assert codex["passed"] is True
    assert codex["events"] == 10
    assert codex["known_helpfulness"] == 8
    assert codex["helpful_rate_pct"] == 75.0


def test_provider_canary_fails_active_provider_with_low_quality(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    now = time.time()
    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_events.jsonl",
        [
            {
                "provider": "claude",
                "emitted_ts": now - 20,
                "helpfulness_label": "unknown",
                "timing_bucket": "late",
                "impact_score": 0.3,
            },
            {
                "provider": "claude",
                "emitted_ts": now - 30,
                "helpfulness_label": "unknown",
                "timing_bucket": "late",
                "impact_score": 0.2,
            },
        ],
    )

    out = run_provider_canary(
        ProviderCanaryConfig(
            spark_dir=spark_dir,
            providers=["claude"],
            window_s=3600,
            min_events_per_provider=10,
            min_known_helpfulness=3,
            min_helpful_rate_pct=40.0,
            min_right_on_time_rate_pct=35.0,
            max_unknown_rate_pct=90.0,
            refresh_spine=False,
        )
    )

    assert out["ready"] is False
    assert out["active_providers"] == ["claude"]
    assert out["failing_active"] == ["claude"]
    claude = out["providers"]["claude"]
    assert claude["passed"] is False
    assert "events<10" in claude["reasons"]
    assert "known_helpfulness<3" in claude["reasons"]
    assert "right_on_time_rate<35.0%" in claude["reasons"]


def test_provider_canary_ignores_inactive_provider(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    now = time.time()
    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_events.jsonl",
        [
            {
                "provider": "codex",
                "emitted_ts": now - 15,
                "helpfulness_label": "helpful",
                "timing_bucket": "right_on_time",
                "impact_score": 0.9,
            },
            {
                "provider": "codex",
                "emitted_ts": now - 12,
                "helpfulness_label": "helpful",
                "timing_bucket": "right_on_time",
                "impact_score": 0.9,
            },
            {
                "provider": "codex",
                "emitted_ts": now - 10,
                "helpfulness_label": "helpful",
                "timing_bucket": "right_on_time",
                "impact_score": 0.9,
            },
        ],
    )

    out = run_provider_canary(
        ProviderCanaryConfig(
            spark_dir=spark_dir,
            providers=["codex", "openclaw"],
            window_s=3600,
            min_events_per_provider=3,
            min_known_helpfulness=3,
            min_helpful_rate_pct=40.0,
            min_right_on_time_rate_pct=35.0,
            max_unknown_rate_pct=90.0,
            refresh_spine=False,
        )
    )

    assert out["ready"] is True
    assert out["active_providers"] == ["codex"]
    assert out["failing_active"] == []
    assert out["providers"]["openclaw"]["active"] is False
    assert out["providers"]["openclaw"]["passed"] is True


def test_provider_canary_filters_synthetic_trace_rows(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    now = time.time()
    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_events.jsonl",
        [
            {
                "provider": "codex",
                "emitted_ts": now - 12,
                "helpfulness_label": "helpful",
                "timing_bucket": "right_on_time",
                "impact_score": 0.9,
                "trace_id": "arena:case-1",
                "route": "alpha",
            },
            {
                "provider": "codex",
                "emitted_ts": now - 10,
                "helpfulness_label": "helpful",
                "timing_bucket": "right_on_time",
                "impact_score": 0.9,
            },
            {
                "provider": "codex",
                "emitted_ts": now - 8,
                "helpfulness_label": "helpful",
                "timing_bucket": "delayed",
                "impact_score": 0.8,
            },
            {
                "provider": "codex",
                "emitted_ts": now - 6,
                "helpfulness_label": "unknown",
                "timing_bucket": "unknown",
                "impact_score": 0.5,
            },
        ],
    )

    out = run_provider_canary(
        ProviderCanaryConfig(
            spark_dir=spark_dir,
            providers=["codex"],
            window_s=3600,
            min_events_per_provider=3,
            min_known_helpfulness=2,
            min_helpful_rate_pct=40.0,
            min_right_on_time_rate_pct=35.0,
            max_unknown_rate_pct=90.0,
            refresh_spine=False,
        )
    )

    codex = out["providers"]["codex"]
    assert codex["raw_events"] == 4
    assert codex["events"] == 3
    assert codex["filtered_synthetic"] == 1
    assert codex["timing_known_events"] == 2
    assert codex["right_on_time_rate_pct"] == 50.0
    assert codex["passed"] is True
