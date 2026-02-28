from __future__ import annotations

import json
from pathlib import Path

import lib.advisory_quality_rating as quality_rating


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def test_list_events_filters_and_limits(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_events.jsonl",
        [
            {"event_id": "e1", "provider": "codex", "tool": "Edit"},
            {"event_id": "e2", "provider": "claude", "tool": "Edit"},
            {"event_id": "e3", "provider": "codex", "tool": "Bash"},
            {"event_id": "e4", "provider": "codex", "tool": "Edit"},
        ],
    )

    rows = quality_rating.list_events(
        spark_dir=spark_dir,
        limit=2,
        provider="codex",
        tool="edit",
    )

    assert [row["event_id"] for row in rows] == ["e4", "e1"]


def test_rate_event_rejects_missing_trace_id(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_events.jsonl",
        [{"event_id": "e1", "advice_id": "a1"}],
    )

    out = quality_rating.rate_event(
        spark_dir=spark_dir,
        event_id="e1",
        label="helpful",
        refresh_spine=False,
    )

    assert out["ok"] is False
    assert out["reason"] == "missing_trace_id"


def test_rate_event_rejects_missing_advice_id(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_events.jsonl",
        [{"event_id": "e1", "trace_id": "t1"}],
    )

    out = quality_rating.rate_event(
        spark_dir=spark_dir,
        event_id="e1",
        label="helpful",
        refresh_spine=False,
    )

    assert out["ok"] is False
    assert out["reason"] == "missing_advice_id"


def test_rate_event_records_feedback_packet_and_rating_row(monkeypatch, tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_events.jsonl",
        [
            {
                "event_id": "e1",
                "trace_id": "trace-1",
                "advice_id": "adv-1",
                "run_id": "run-1",
                "session_id": "session-1",
                "provider": "claude",
                "tool": "Edit",
                "route": "alpha",
            }
        ],
    )

    ratings_path = tmp_path / ".spark" / "advisor" / "advisory_quality_ratings.jsonl"
    monkeypatch.setattr(quality_rating, "RATINGS_FILE", ratings_path)

    feedback_calls: list[dict] = []
    packet_calls: list[dict] = []

    def _fake_record_feedback(**kwargs):
        feedback_calls.append(dict(kwargs))
        return True

    def _fake_record_packet(
        advice_id: str,
        *,
        status: str,
        source: str,
        tool_name,
        trace_id,
        notes: str,
        count_effectiveness: bool,
    ):
        packet_calls.append(
            {
                "advice_id": advice_id,
                "status": status,
                "source": source,
                "tool_name": tool_name,
                "trace_id": trace_id,
                "notes": notes,
                "count_effectiveness": count_effectiveness,
            }
        )
        return {"ok": True, "updated": 1}

    monkeypatch.setattr(quality_rating, "_record_feedback", _fake_record_feedback)
    monkeypatch.setattr(quality_rating, "_record_packet_outcome_for_advice", _fake_record_packet)
    monkeypatch.setattr(
        quality_rating,
        "_refresh_quality_spine",
        lambda spark_dir: {"total_events": 10},
    )

    out = quality_rating.rate_event(
        spark_dir=spark_dir,
        event_id="e1",
        label="helpful",
        notes="Right before tool call.",
        source="cli",
        refresh_spine=True,
    )

    assert out["ok"] is True
    assert out["feedback_ok"] is True
    assert out["packet_result"]["ok"] is True
    assert out["rating_row"]["label"] == "helpful"
    assert out["rating_row"]["status"] == "acted"
    assert out["refreshed_summary"]["total_events"] == 10

    assert len(feedback_calls) == 1
    feedback_call = feedback_calls[0]
    assert feedback_call["advice_ids"] == ["adv-1"]
    assert feedback_call["trace_id"] == "trace-1"
    assert feedback_call["helpful"] is True
    assert feedback_call["followed"] is True
    assert feedback_call["status"] == "acted"
    assert feedback_call["tool"] == "Edit"

    assert len(packet_calls) == 1
    packet_call = packet_calls[0]
    assert packet_call["advice_id"] == "adv-1"
    assert packet_call["trace_id"] == "trace-1"
    assert packet_call["status"] == "acted"

    written = [
        json.loads(line)
        for line in ratings_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(written) == 1
    assert written[0]["event_id"] == "e1"
    assert written[0]["provider"] == "claude"


def test_rate_latest_filters_by_trace_and_advice(monkeypatch, tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_events.jsonl",
        [
            {"event_id": "e1", "trace_id": "t1", "advice_id": "a1", "tool": "Edit", "provider": "codex"},
            {"event_id": "e2", "trace_id": "t2", "advice_id": "a2", "tool": "Edit", "provider": "codex"},
        ],
    )

    refresh_calls = {"count": 0}

    def _fake_refresh(_spark_dir: Path):
        refresh_calls["count"] += 1
        return {"total_events": 2}

    seen: list[dict] = []

    def _fake_rate_event(**kwargs):
        seen.append(dict(kwargs))
        return {"ok": True, "event_id": kwargs["event_id"], "refreshed_summary": {}}

    monkeypatch.setattr(quality_rating, "_refresh_quality_spine", _fake_refresh)
    monkeypatch.setattr(quality_rating, "rate_event", _fake_rate_event)

    out = quality_rating.rate_latest(
        spark_dir=spark_dir,
        trace_id="t2",
        advice_id="a2",
        tool="Edit",
        label="helpful",
        refresh_spine=True,
    )

    assert out["ok"] is True
    assert out["event_id"] == "e2"
    assert out["refreshed_summary"]["total_events"] == 2
    assert refresh_calls["count"] == 2
    assert len(seen) == 1
    assert seen[0]["event_id"] == "e2"
    assert seen[0]["refresh_spine"] is False


def test_rate_latest_returns_not_found_for_filters(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advisor" / "advisory_quality_events.jsonl",
        [{"event_id": "e1", "trace_id": "t1", "advice_id": "a1", "tool": "Edit", "provider": "codex"}],
    )

    out = quality_rating.rate_latest(
        spark_dir=spark_dir,
        trace_id="missing-trace",
        advice_id="a1",
        tool="Edit",
        label="helpful",
        refresh_spine=False,
    )

    assert out["ok"] is False
    assert out["reason"] == "event_not_found_for_filters"
