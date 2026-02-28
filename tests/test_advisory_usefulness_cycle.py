from __future__ import annotations

import json
import time
from pathlib import Path

import lib.advisory_usefulness_cycle as cycle
import lib.advisory_quality_rating as quality_rating
import lib.advisory_quality_spine as quality_spine
import lib.helpfulness_watcher as helpfulness_watcher


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_build_candidates_filters_known_and_rated(tmp_path):
    spark_dir = tmp_path / "spark"
    now = time.time()

    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_events.jsonl",
        [
            {
                "event_id": "ev-known",
                "trace_id": "trace-known",
                "advice_id": "aid-known",
                "tool": "Edit",
                "provider": "codex",
                "helpfulness_label": "helpful",
                "emitted_ts": now - 100,
            },
            {
                "event_id": "ev-rate-me",
                "trace_id": "trace-1",
                "advice_id": "aid-1",
                "tool": "Edit",
                "provider": "codex",
                "helpfulness_label": "unknown",
                "timing_bucket": "right_on_time",
                "impact_score": 0.9,
                "emitted_ts": now - 80,
            },
            {
                "event_id": "ev-already-rated",
                "trace_id": "trace-2",
                "advice_id": "aid-2",
                "tool": "Edit",
                "provider": "codex",
                "helpfulness_label": "unknown",
                "emitted_ts": now - 70,
            },
        ],
    )
    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_ratings.jsonl",
        [{"event_id": "ev-already-rated", "label": "helpful", "ts": now - 20}],
    )
    _write_jsonl(
        spark_dir / "advisory_engine_alpha.jsonl",
        [
            {"ts": now - 79, "trace_id": "trace-1", "event": "emitted"},
            {"ts": now - 70, "trace_id": "trace-1", "event": "post_tool_recorded", "extra": {"success": True}},
        ],
    )
    _write_jsonl(
        spark_dir / "advisor" / "implicit_feedback.jsonl",
        [{"timestamp": now - 75, "trace_id": "trace-1", "tool": "Edit", "signal": "followed"}],
    )

    out = cycle.build_candidates(
        spark_dir=spark_dir,
        window_hours=4.0,
        max_candidates=10,
    )
    assert len(out) == 1
    row = out[0]
    assert row["event_id"] == "ev-rate-me"
    assert row["heuristic_label"] == "helpful"
    assert row["heuristic_confidence"] >= 0.8


def test_run_usefulness_cycle_applies_heuristic_ratings(tmp_path, monkeypatch):
    spark_dir = tmp_path / "spark"
    now = time.time()

    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_events.jsonl",
        [
            {
                "event_id": "ev-1",
                "trace_id": "trace-1",
                "advice_id": "aid-1",
                "tool": "Edit",
                "provider": "codex",
                "helpfulness_label": "unknown",
                "timing_bucket": "right_on_time",
                "impact_score": 0.88,
                "emitted_ts": now - 120,
            }
        ],
    )
    _write_jsonl(
        spark_dir / "advisory_engine_alpha.jsonl",
        [
            {"ts": now - 119, "trace_id": "trace-1", "event": "emitted"},
            {"ts": now - 110, "trace_id": "trace-1", "event": "post_tool_recorded", "extra": {"success": True}},
        ],
    )
    _write_jsonl(
        spark_dir / "advisor" / "implicit_feedback.jsonl",
        [{"timestamp": now - 115, "trace_id": "trace-1", "tool": "Edit", "signal": "followed"}],
    )

    calls: list[dict] = []

    def _fake_rate_event(**kwargs):
        calls.append(dict(kwargs))
        return {"ok": True}

    monkeypatch.setattr(quality_rating, "rate_event", _fake_rate_event)
    monkeypatch.setattr(
        quality_spine,
        "run_advisory_quality_spine_default",
        lambda **_kwargs: {"summary": {"total_events": 1}},
    )
    monkeypatch.setattr(
        helpfulness_watcher,
        "run_helpfulness_watcher_default",
        lambda **_kwargs: {"summary": {"total_events": 1}},
    )

    out = cycle.run_usefulness_cycle(
        spark_dir=spark_dir,
        window_hours=4.0,
        max_candidates=10,
        run_llm=False,
        min_confidence=0.7,
        apply_limit=5,
        source="test_cycle",
    )

    assert out["ok"] is True
    assert out["candidate_count"] == 1
    assert out["applied_count"] == 1
    assert len(calls) == 1
    assert calls[0]["event_id"] == "ev-1"
    assert calls[0]["label"] == "helpful"

    paths = out["paths"]
    assert Path(paths["queue_file"]).exists()
    assert Path(paths["prompt_file"]).exists()
    assert Path(paths["summary_file"]).exists()
    assert Path(paths["history_file"]).exists()
