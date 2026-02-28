from __future__ import annotations

import json
from pathlib import Path

import lib.observatory.readers as readers


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def test_read_advisory_uses_strict_feedback_denominator_and_loads_summary(monkeypatch, tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    monkeypatch.setattr(readers, "_SD", spark_dir)

    _write_json(
        spark_dir / "advisor" / "effectiveness.json",
        {
            "total_advice_given": 10,
            "total_followed": 3,
            "total_helpful": 2,
            "by_source": {},
        },
    )
    _write_json(
        spark_dir / "advisor" / "metrics.json",
        {
            "cognitive_helpful_rate": 0.5,
            "cognitive_helpful_known": 2,
            "last_updated": "2026-02-26T00:00:00",
        },
    )
    _write_jsonl(
        spark_dir / "advisor" / "implicit_feedback.jsonl",
        [
            {"tool": "Edit", "signal": "followed"},
            {"tool": "Edit", "signal": "followed"},
            {"tool": "Edit", "signal": "unhelpful"},
            {"tool": "Edit", "signal": "ignored"},
        ],
    )
    _write_json(
        spark_dir / "advisor" / "helpfulness_summary.json",
        {
            "total_events": 4,
            "helpful_rate_pct": 50.0,
            "unknown_rate_pct": 25.0,
            "conflict_rate_pct": 0.0,
        },
    )
    _write_jsonl(
        spark_dir / "advisor" / "helpfulness_events.jsonl",
        [
            {"event_id": "e1", "helpful_label": "helpful"},
            {"event_id": "e2", "helpful_label": "unknown"},
        ],
    )
    _write_jsonl(
        spark_dir / "advisory_decision_ledger.jsonl",
        [{"outcome": "emitted"}, {"outcome": "blocked"}],
    )
    _write_jsonl(spark_dir / "advisor" / "advice_log.jsonl", [])

    data = readers.read_advisory(max_recent=10)

    # Strict denominator includes unhelpful + ignored.
    assert data["feedback_followed"] == 2
    assert data["feedback_unhelpful"] == 1
    assert data["feedback_ignored"] == 1
    assert data["feedback_eval_total"] == 4
    assert data["feedback_follow_rate"] == 50.0

    by_tool = data["feedback_by_tool"]["Edit"]
    assert by_tool["followed"] == 2
    assert by_tool["unhelpful"] == 1
    assert by_tool["ignored"] == 1

    assert data["helpfulness_summary"]["helpful_rate_pct"] == 50.0
    assert len(data["recent_helpfulness_events"]) == 2


def test_read_advisory_falls_back_to_advisory_emit_when_ledger_missing(monkeypatch, tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    monkeypatch.setattr(readers, "_SD", spark_dir)
    _write_json(spark_dir / "advisor" / "effectiveness.json", {"total_advice_given": 0, "total_followed": 0, "total_helpful": 0})
    _write_json(spark_dir / "advisor" / "metrics.json", {})
    _write_jsonl(
        spark_dir / "advisory_emit.jsonl",
        [
            {"tool_name": "Edit", "trace_id": "t1", "ts": 1},
            {"tool_name": "Bash", "trace_id": "t2", "ts": 2},
            {"tool_name": "Read", "trace_id": "t3", "ts": 3},
        ],
    )
    data = readers.read_advisory(max_recent=10)
    assert data["decision_source"] == "advisory_emit_fallback"
    assert data["decision_total"] == 3
    assert data["decision_outcomes"].get("emitted", 0) == 3
    assert data["decision_emit_rate"] == 100.0


def test_read_advisory_falls_back_to_alpha_engine_events(monkeypatch, tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    monkeypatch.setattr(readers, "_SD", spark_dir)
    _write_json(spark_dir / "advisor" / "effectiveness.json", {"total_advice_given": 0, "total_followed": 0, "total_helpful": 0})
    _write_json(spark_dir / "advisor" / "metrics.json", {})
    _write_jsonl(
        spark_dir / "advisory_engine_alpha.jsonl",
        [
            {"event": "emitted", "tool_name": "Edit"},
            {"event": "gate_no_emit", "tool_name": "Edit"},
            {"event": "context_repeat_blocked", "tool_name": "Bash"},
            {"event": "post_tool_recorded", "tool_name": "Bash"},
        ],
    )
    data = readers.read_advisory(max_recent=10)
    assert data["decision_source"] == "advisory_engine_alpha_fallback"
    assert data["decision_total"] == 3
    assert data["decision_outcomes"].get("emitted", 0) == 1
    assert data["decision_outcomes"].get("blocked", 0) == 2
    assert data["decision_emit_rate"] == 33.3


def test_read_advisory_prefers_engine_over_emit_when_both_exist(monkeypatch, tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    monkeypatch.setattr(readers, "_SD", spark_dir)
    _write_json(spark_dir / "advisor" / "effectiveness.json", {"total_advice_given": 0, "total_followed": 0, "total_helpful": 0})
    _write_json(spark_dir / "advisor" / "metrics.json", {})
    _write_jsonl(
        spark_dir / "advisory_engine_alpha.jsonl",
        [
            {"event": "emitted", "tool_name": "Edit"},
            {"event": "gate_no_emit", "tool_name": "Edit"},
        ],
    )
    _write_jsonl(
        spark_dir / "advisory_emit.jsonl",
        [
            {"tool_name": "Edit", "trace_id": "t1", "ts": 1},
            {"tool_name": "Bash", "trace_id": "t2", "ts": 2},
            {"tool_name": "Read", "trace_id": "t3", "ts": 3},
        ],
    )
    data = readers.read_advisory(max_recent=10)
    assert data["decision_source"] == "advisory_engine_alpha_fallback"
    assert data["decision_total"] == 2
    assert data["decision_outcomes"].get("emitted", 0) == 1
    assert data["decision_outcomes"].get("blocked", 0) == 1
    assert data["decision_emit_rate"] == 50.0
