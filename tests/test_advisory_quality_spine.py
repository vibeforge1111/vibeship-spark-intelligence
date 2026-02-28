from __future__ import annotations

import json
from pathlib import Path

from lib.advisory_quality_spine import run_advisory_quality_spine_default


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def test_quality_spine_infers_provider_and_timing_from_emissions(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advisor" / "recent_advice.jsonl",
        [
            {
                "ts": 100.0,
                "recorded_at": 100.1,
                "tool": "Bash",
                "trace_id": "t1",
                "run_id": "r1",
                "route": "alpha",
                "delivered": True,
                "advice_ids": ["a1"],
                "advice_texts": ["Use safer edit path."],
                "sources": ["bank"],
                "advisory_readiness": [0.73],
                "advisory_quality": [{"unified_score": 0.81}],
            }
        ],
    )
    _write_jsonl(
        spark_dir / "advisory_engine_alpha.jsonl",
        [
            {
                "ts": 100.0,
                "event": "emitted",
                "session_id": "session-1",
                "tool_name": "Bash",
                "trace_id": "t1",
            },
            {
                "ts": 132.0,
                "event": "post_tool_recorded",
                "session_id": "session-1",
                "tool_name": "Bash",
                "trace_id": "t1",
                "extra": {"success": True},
            },
        ],
    )
    _write_jsonl(
        spark_dir / "logs" / "observe_hook_telemetry.jsonl",
        [
            {
                "ts": 99.0,
                "session_id": "session-1",
                "source": "claude_code",
                "event_type": "pre_tool",
                "tool_name": "Bash",
            }
        ],
    )
    _write_jsonl(
        spark_dir / "advisor" / "implicit_feedback.jsonl",
        [
            {
                "timestamp": 125.0,
                "trace_id": "t1",
                "tool": "Bash",
                "signal": "followed",
            }
        ],
    )

    out = run_advisory_quality_spine_default(spark_dir=spark_dir, write_files=False)

    assert out["summary"]["total_events"] == 1
    row = out["events"][0]
    assert row["provider"] == "claude"
    assert row["helpfulness_label"] == "unknown"
    assert row["timing_bucket"] == "right_on_time"
    assert row["impact_score"] >= 0.6
    assert out["summary"]["right_on_time_rate_pct"] == 100.0


def test_quality_spine_prefers_explicit_feedback_over_implicit(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advisor" / "recent_advice.jsonl",
        [
            {
                "ts": 200.0,
                "recorded_at": 200.2,
                "tool": "Edit",
                "trace_id": "t2",
                "run_id": "r2",
                "route": "alpha",
                "delivered": True,
                "advice_ids": ["a2"],
                "advice_texts": ["Apply patch with rollback guard."],
                "sources": ["workflow"],
                "advisory_readiness": [0.61],
                "advisory_quality": [{"unified_score": 0.55}],
            }
        ],
    )
    _write_jsonl(
        spark_dir / "advisory_engine_alpha.jsonl",
        [
            {
                "ts": 200.0,
                "event": "emitted",
                "session_id": "session-2",
                "tool_name": "Edit",
                "trace_id": "t2",
            },
            {
                "ts": 255.0,
                "event": "post_tool_recorded",
                "session_id": "session-2",
                "tool_name": "Edit",
                "trace_id": "t2",
            },
        ],
    )
    _write_jsonl(
        spark_dir / "logs" / "observe_hook_telemetry.jsonl",
        [
            {
                "ts": 198.0,
                "session_id": "session-2",
                "source": "codex",
                "event_type": "pre_tool",
                "tool_name": "Edit",
            }
        ],
    )
    _write_jsonl(
        spark_dir / "advisor" / "implicit_feedback.jsonl",
        [
            {"timestamp": 225.0, "trace_id": "t2", "tool": "Edit", "signal": "followed"}
        ],
    )
    _write_jsonl(
        spark_dir / "advice_feedback.jsonl",
        [
            {
                "created_at": 220.0,
                "trace_id": "t2",
                "tool": "Edit",
                "advice_ids": ["a2"],
                "status": "harmful",
                "helpful": False,
                "followed": True,
            }
        ],
    )

    out = run_advisory_quality_spine_default(spark_dir=spark_dir, write_files=False)
    row = out["events"][0]
    assert row["provider"] == "codex"
    assert row["helpfulness_label"] == "harmful"
    assert row["judge_source"] == "explicit_feedback"
    assert row["usefulness_score"] == 0.0
    assert out["summary"]["helpful_rate_pct"] == 0.0


def test_quality_spine_writes_summary_and_events_files(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advisor" / "recent_advice.jsonl",
        [
            {
                "ts": 10.0,
                "recorded_at": 10.0,
                "tool": "Read",
                "trace_id": "t3",
                "run_id": "r3",
                "route": "alpha",
                "delivered": True,
                "advice_ids": ["a3"],
                "advice_texts": ["Read file before edit."],
                "sources": ["bank"],
            }
        ],
    )
    _write_jsonl(
        spark_dir / "advisory_engine_alpha.jsonl",
        [
            {
                "ts": 10.0,
                "event": "emitted",
                "session_id": "s3",
                "tool_name": "Read",
                "trace_id": "t3",
            }
        ],
    )
    _write_jsonl(
        spark_dir / "logs" / "observe_hook_telemetry.jsonl",
        [
            {
                "ts": 9.0,
                "session_id": "s3",
                "source": "claude_code",
                "event_type": "pre_tool",
                "tool_name": "Read",
            }
        ],
    )

    out = run_advisory_quality_spine_default(spark_dir=spark_dir, write_files=True)
    paths = out["paths"]
    events_path = Path(paths["events_file"])
    summary_path = Path(paths["summary_file"])

    assert events_path.exists()
    assert summary_path.exists()
    events = [json.loads(x) for x in events_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert len(events) == 1
    assert summary["total_events"] == 1
