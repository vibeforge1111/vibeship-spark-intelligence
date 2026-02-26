from __future__ import annotations

import json
from pathlib import Path

from lib.helpfulness_watcher import WatcherConfig, run_helpfulness_watcher


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        out.append(json.loads(line))
    return out


def test_watcher_builds_canonical_events_from_explicit_and_implicit(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"

    _write_jsonl(
        spark_dir / "advice_feedback_requests.jsonl",
        [
            {
                "session_id": "s1",
                "tool": "Edit",
                "advice_ids": ["a1"],
                "sources": ["cognitive"],
                "trace_id": "t1",
                "run_id": "r1",
                "advisory_group_key": "g1",
                "created_at": 100.0,
            },
            {
                "session_id": "s2",
                "tool": "Bash",
                "advice_ids": ["a2"],
                "sources": ["eidos"],
                "trace_id": "t2",
                "run_id": "r2",
                "advisory_group_key": "g2",
                "created_at": 200.0,
            },
        ],
    )
    _write_jsonl(
        spark_dir / "advice_feedback.jsonl",
        [
            {
                "advice_ids": ["a1"],
                "tool": "Edit",
                "helpful": True,
                "followed": True,
                "trace_id": "t1",
                "run_id": "r1",
                "advisory_group_key": "g1",
                "created_at": 105.0,
            }
        ],
    )
    _write_jsonl(
        spark_dir / "advisor" / "implicit_feedback.jsonl",
        [
            {"tool": "Bash", "signal": "unhelpful", "trace_id": "t2", "timestamp": 210.0}
        ],
    )

    result = run_helpfulness_watcher(
        WatcherConfig(
            spark_dir=spark_dir,
            llm_review_confidence_threshold=0.7,
            write_files=True,
        )
    )
    assert result["ok"] is True
    assert result["summary"]["total_events"] == 2
    assert result["summary"]["labels"]["helpful"] == 1
    assert result["summary"]["labels"]["unhelpful"] == 1

    events = _read_jsonl(spark_dir / "advisor" / "helpfulness_events.jsonl")
    assert len(events) == 2
    by_advice = {row["advice_id"]: row for row in events}

    assert by_advice["a1"]["helpful_label"] == "helpful"
    assert by_advice["a1"]["judge_source"] == "explicit_feedback"
    assert by_advice["a1"]["conflict"] is False

    assert by_advice["a2"]["helpful_label"] == "unhelpful"
    assert by_advice["a2"]["judge_source"] == "implicit_feedback"


def test_watcher_flags_explicit_vs_implicit_conflicts(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advice_feedback_requests.jsonl",
        [
            {
                "session_id": "s3",
                "tool": "Write",
                "advice_ids": ["a3"],
                "trace_id": "t3",
                "run_id": "r3",
                "advisory_group_key": "g3",
                "created_at": 300.0,
            }
        ],
    )
    _write_jsonl(
        spark_dir / "advice_feedback.jsonl",
        [
            {
                "advice_ids": ["a3"],
                "tool": "Write",
                "helpful": True,
                "followed": True,
                "trace_id": "t3",
                "run_id": "r3",
                "advisory_group_key": "g3",
                "created_at": 302.0,
            }
        ],
    )
    _write_jsonl(
        spark_dir / "advisor" / "implicit_feedback.jsonl",
        [
            {"tool": "Write", "signal": "unhelpful", "trace_id": "t3", "timestamp": 305.0}
        ],
    )

    run_helpfulness_watcher(
        WatcherConfig(
            spark_dir=spark_dir,
            llm_review_confidence_threshold=0.95,
            write_files=True,
        )
    )

    events = _read_jsonl(spark_dir / "advisor" / "helpfulness_events.jsonl")
    assert len(events) == 1
    event = events[0]
    # Explicit remains authoritative, but we expose conflict.
    assert event["helpful_label"] == "helpful"
    assert event["conflict"] is True
    assert event["llm_review_required"] is True


def test_watcher_applies_llm_review_override(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advice_feedback_requests.jsonl",
        [
            {
                "session_id": "s4",
                "tool": "Edit",
                "advice_ids": ["a4"],
                "trace_id": "t4",
                "run_id": "r4",
                "advisory_group_key": "g4",
                "created_at": 400.0,
            }
        ],
    )
    _write_jsonl(
        spark_dir / "advisor" / "implicit_feedback.jsonl",
        [
            {"tool": "Edit", "signal": "followed", "trace_id": "t4", "timestamp": 410.0}
        ],
    )
    # First pass creates the baseline event and event_id.
    run_helpfulness_watcher(
        WatcherConfig(
            spark_dir=spark_dir,
            llm_review_confidence_threshold=0.95,
            min_applied_review_confidence=0.8,
            write_files=True,
        )
    )
    first_events = _read_jsonl(spark_dir / "advisor" / "helpfulness_events.jsonl")
    assert len(first_events) == 1
    event_id = first_events[0]["event_id"]

    _write_jsonl(
        spark_dir / "advisor" / "helpfulness_llm_reviews.jsonl",
        [
            {
                "event_id": event_id,
                "status": "ok",
                "label": "helpful",
                "confidence": 0.92,
                "provider": "minimax",
                "reviewed_at": 500.0,
            }
        ],
    )

    run_helpfulness_watcher(
        WatcherConfig(
            spark_dir=spark_dir,
            llm_review_confidence_threshold=0.95,
            min_applied_review_confidence=0.8,
            write_files=True,
        )
    )

    events = _read_jsonl(spark_dir / "advisor" / "helpfulness_events.jsonl")
    assert len(events) == 1
    event = events[0]
    assert event["helpful_label"] == "helpful"
    assert event["judge_source"] == "llm_review:minimax"
    assert event["llm_review_applied"] is True
    assert event["llm_review_required"] is False


def test_watcher_uses_unique_event_ids_for_repeated_exposures(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advice_feedback_requests.jsonl",
        [
            {
                "session_id": "s5",
                "tool": "Edit",
                "advice_ids": ["same-advice"],
                "trace_id": "t5",
                "run_id": "r5",
                "advisory_group_key": "g5",
                "created_at": 500.0,
            },
            {
                "session_id": "s5",
                "tool": "Edit",
                "advice_ids": ["same-advice"],
                "trace_id": "t5",
                "run_id": "r5",
                "advisory_group_key": "g5",
                "created_at": 560.0,
            },
        ],
    )
    _write_jsonl(spark_dir / "advisor" / "implicit_feedback.jsonl", [])

    run_helpfulness_watcher(
        WatcherConfig(
            spark_dir=spark_dir,
            write_files=True,
        )
    )

    events = _read_jsonl(spark_dir / "advisor" / "helpfulness_events.jsonl")
    assert len(events) == 2
    ids = {e["event_id"] for e in events}
    assert len(ids) == 2


def test_watcher_accepts_explicit_match_by_advice_id_only(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advice_feedback_requests.jsonl",
        [
            {
                "session_id": "s6",
                "tool": "Edit",
                "advice_ids": ["a6"],
                "trace_id": "trace-request",
                "run_id": "run-request",
                "advisory_group_key": "group-request",
                "created_at": 600.0,
            }
        ],
    )
    # Deliberately omit matching trace/run/group/tool; only advice_id matches.
    _write_jsonl(
        spark_dir / "advice_feedback.jsonl",
        [
            {
                "advice_ids": ["a6"],
                "tool": "Bash",
                "helpful": True,
                "followed": True,
                "trace_id": "trace-other",
                "run_id": "run-other",
                "advisory_group_key": "group-other",
                "created_at": 605.0,
            }
        ],
    )
    _write_jsonl(spark_dir / "advisor" / "implicit_feedback.jsonl", [])

    run_helpfulness_watcher(
        WatcherConfig(
            spark_dir=spark_dir,
            write_files=True,
        )
    )

    events = _read_jsonl(spark_dir / "advisor" / "helpfulness_events.jsonl")
    assert len(events) == 1
    event = events[0]
    assert event["helpful_label"] == "helpful"
    assert event["judge_source"] == "explicit_feedback"


def test_watcher_treats_abstain_review_as_terminal_for_queue(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advice_feedback_requests.jsonl",
        [
            {
                "session_id": "s7",
                "tool": "Edit",
                "advice_ids": ["a7"],
                "trace_id": "t7",
                "run_id": "r7",
                "advisory_group_key": "g7",
                "created_at": 700.0,
            }
        ],
    )
    _write_jsonl(
        spark_dir / "advisor" / "implicit_feedback.jsonl",
        [{"tool": "Edit", "signal": "followed", "trace_id": "t7", "timestamp": 710.0}],
    )

    run_helpfulness_watcher(
        WatcherConfig(
            spark_dir=spark_dir,
            llm_review_confidence_threshold=0.95,
            write_files=True,
        )
    )
    first_events = _read_jsonl(spark_dir / "advisor" / "helpfulness_events.jsonl")
    assert len(first_events) == 1
    event_id = first_events[0]["event_id"]
    assert first_events[0]["llm_review_required"] is True

    _write_jsonl(
        spark_dir / "advisor" / "helpfulness_llm_reviews.jsonl",
        [
            {
                "event_id": event_id,
                "status": "abstain",
                "label": "abstain",
                "confidence": 0.91,
                "provider": "minimax",
                "reviewed_at": 800.0,
            }
        ],
    )
    run_helpfulness_watcher(
        WatcherConfig(
            spark_dir=spark_dir,
            llm_review_confidence_threshold=0.95,
            write_files=True,
        )
    )

    events = _read_jsonl(spark_dir / "advisor" / "helpfulness_events.jsonl")
    assert len(events) == 1
    event = events[0]
    assert event["llm_review_status"] == "abstain"
    assert event["llm_review_applied"] is False
    assert event["llm_review_required"] is False
    assert _read_jsonl(spark_dir / "advisor" / "helpfulness_llm_queue.jsonl") == []
