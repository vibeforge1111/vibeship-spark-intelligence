from __future__ import annotations

import json
from pathlib import Path

import lib.observatory.advisory_context_pages as context_pages


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def test_generate_advisory_context_pages_with_engine_fallback_and_integrity_flags(monkeypatch, tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    reports_root = tmp_path / "repo"
    monkeypatch.setattr(context_pages, "_SD", spark_dir)
    monkeypatch.setattr(context_pages, "_REPO_ROOT", reports_root)

    _write_jsonl(
        spark_dir / "logs" / "observe_hook_telemetry.jsonl",
        [
            {"ts": 100.0, "trace_id": "t1", "event": "pre_tool"},
            {"ts": 101.0, "trace_id": "t2", "event": "pre_tool"},
        ],
    )
    _write_jsonl(
        spark_dir / "queue" / "events.jsonl",
        [
            {"ts": 100.5, "trace_id": "t1", "event_type": "tool_call"},
            {"ts": 102.0, "trace_id": "t2", "event_type": "tool_call"},
        ],
    )
    _write_jsonl(
        spark_dir / "advisory_engine_alpha.jsonl",
        [
            {"ts": 103.0, "trace_id": "t1", "event": "emitted", "tool_name": "Edit", "route": "alpha"},
            {
                "ts": 104.0,
                "trace_id": "t2",
                "event": "gate_no_emit",
                "tool_name": "Bash",
                "route": "alpha",
                "gate_reason": "tool_cooldown",
                "selected_count": 1,
            },
        ],
    )
    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_events.jsonl",
        [
            {
                "emitted_ts": 103.0,
                "trace_id": "t1",
                "advice_id": "a1",
                "provider": "codex",
                "tool": "Edit",
                "task_phase": "implementation",
                "helpfulness_label": "helpful",
                "timing_bucket": "right_on_time",
            },
            {
                "emitted_ts": 104.0,
                "trace_id": "t2",
                "advice_id": "a2",
                "provider": "claude",
                "tool": "Bash",
                "task_phase": "exploration",
                "helpfulness_label": "unknown",
                "timing_bucket": "late",
            },
        ],
    )
    _write_json(
        spark_dir / "advisor" / "helpfulness_summary.json",
        {
            "total_events": 2,
            "known_helpfulness_total": 1,
            "helpful_rate_pct": 100.0,
            "unknown_rate_pct": 50.0,
            "llm_review_queue_count": 1,
        },
    )
    _write_jsonl(
        spark_dir / "advisor" / "helpfulness_events.jsonl",
        [
            {"request_ts": 103.0, "trace_id": "t1", "tool": "Edit", "helpful_label": "helpful"},
            {"request_ts": 104.0, "trace_id": "t2", "tool": "Bash", "helpful_label": "unknown", "llm_review_required": True},
        ],
    )
    _write_jsonl(spark_dir / "advisor" / "helpfulness_llm_queue.jsonl", [{"event_id": "evt-2"}])
    _write_jsonl(
        spark_dir / "advisor" / "helpfulness_llm_reviews.jsonl",
        [{"event_id": "evt-2", "status": "provider_error", "reviewed_at": 105.0}],
    )
    _write_jsonl(
        spark_dir / "advice_feedback.jsonl",
        [{"trace_id": "t1", "advice_ids": ["a1"], "helpful": True, "created_at": 106.0}],
    )
    _write_jsonl(
        spark_dir / "advice_feedback_requests.jsonl",
        [{"trace_id": "t1", "advice_ids": ["a1"], "created_at": 102.0, "tool": "Edit"}],
    )
    _write_json(
        reports_root / "reports" / "2026-02-28_103318_advisory_context_external_review.json",
        {
            "results": [
                {"provider": "claude", "ok": True, "response": "Execution error"},
            ]
        },
    )

    pages = context_pages.generate_advisory_context_pages(
        {
            8: {
                "advisory_rating_coverage_summary": {
                    "prompted_total": 2,
                    "explicit_rated_total": 1,
                    "known_helpful_total": 1,
                    "explicit_rate_pct": 50.0,
                    "known_helpful_rate_pct": 50.0,
                    "explicit_gap": 1,
                    "known_helpful_gap": 1,
                },
                "advisory_quality_summary": {
                    "total_events": 2,
                    "avg_impact_score": 0.75,
                    "right_on_time_rate_pct": 50.0,
                },
            }
        }
    )

    assert set(pages.keys()) == {
        "advisory_trace_lineage.md",
        "advisory_emission_lineage_deep.md",
        "meta_ralph_trace_binding_health.md",
        "intelligence_intake_lifecycle.md",
        "advisory_unknown_helpfulness_burndown.md",
        "advisory_suppression_replay.md",
        "advisory_context_drift.md",
        "advisory_data_integrity.md",
        "retrieval_route_forensics.md",
        "advisory_content_quality_forensics.md",
        "intelligence_constitution.md",
        "keepability_gate_review.md",
        "context_trace_cohorts.md",
        "intelligence_signal_tables.md",
    }
    assert "Decision source used for lineage: `advisory_engine_alpha_fallback`" in pages["advisory_trace_lineage.md"]
    assert "Decision source: `advisory_engine_alpha_fallback`" in pages["advisory_suppression_replay.md"]
    assert "Warning: decision ledger missing; observatory is using fallback source" in pages["advisory_data_integrity.md"]
    assert "external review result status inconsistent with error response" in pages["advisory_data_integrity.md"]
    assert "Advisory Content Quality Forensics" in pages["advisory_content_quality_forensics.md"]
    assert "Intelligence Constitution" in pages["intelligence_constitution.md"]
    assert "Keepability Gate Review" in pages["keepability_gate_review.md"]
    assert "Context Trace Cohorts" in pages["context_trace_cohorts.md"]
    assert "False Wisdom Table" in pages["intelligence_signal_tables.md"]


def test_context_drift_page_contains_dimension_rows(monkeypatch, tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    monkeypatch.setattr(context_pages, "_SD", spark_dir)

    _write_jsonl(
        spark_dir / "advisory_decision_ledger.jsonl",
        [
            {"ts": 1.0, "trace_id": "a", "tool": "Edit", "route": "alpha", "outcome": "emitted"},
            {"ts": 2.0, "trace_id": "b", "tool": "Edit", "route": "alpha", "outcome": "blocked", "gate_reason": "tool_cooldown"},
            {"ts": 3.0, "trace_id": "c", "tool": "Bash", "route": "alpha", "outcome": "emitted"},
            {"ts": 4.0, "trace_id": "d", "tool": "Bash", "route": "packet", "outcome": "blocked", "gate_reason": "global_dedupe"},
        ],
    )
    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_events.jsonl",
        [
            {"emitted_ts": 1.0, "provider": "codex", "task_phase": "implementation"},
            {"emitted_ts": 2.0, "provider": "codex", "task_phase": "implementation"},
            {"emitted_ts": 3.0, "provider": "claude", "task_phase": "exploration"},
            {"emitted_ts": 4.0, "provider": "claude", "task_phase": "exploration"},
        ],
    )

    page = context_pages.generate_advisory_context_pages({})["advisory_context_drift.md"]
    assert "Drift Scores (Previous vs Current Window)" in page
    assert "| decision_tool |" in page
    assert "| decision_route |" in page
    assert "| quality_provider |" in page
    assert "| quality_phase |" in page
    assert "| suppression_bucket |" in page
