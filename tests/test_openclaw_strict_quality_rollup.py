from __future__ import annotations

import json
from pathlib import Path

from scripts.openclaw_strict_quality_rollup import build_rollup, render_markdown


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_build_rollup_counts_strict_rows_and_lineage_slices(tmp_path):
    now_ts = 1_800_000_000.0
    req = tmp_path / "advice_feedback_requests.jsonl"
    fb = tmp_path / "advice_feedback.jsonl"

    req_rows = [
        {
            "schema_version": 2,
            "trace_id": "t1",
            "run_id": "r1",
            "advisory_group_key": "g1",
            "created_at": now_ts - 10,
            "tool": "Edit",
        },
        {
            "schema_version": 1,
            "trace_id": "t-old",
            "run_id": "r-old",
            "advisory_group_key": "g-old",
            "created_at": now_ts - 20,
            "tool": "Edit",
        },
        {
            "schema_version": 2,
            "trace_id": "",
            "run_id": "r2",
            "advisory_group_key": "g2",
            "created_at": now_ts - 30,
            "tool": "Task",
        },
    ]
    fb_rows = [
        {
            "schema_version": 2,
            "trace_id": "t1",
            "run_id": "r1",
            "advisory_group_key": "g1",
            "created_at": now_ts - 15,
            "tool": "Edit",
            "session_kind": "main",
            "sources": ["semantic", "bank"],
            "helpful": True,
            "followed": True,
            "status": "acted",
        },
        {
            "schema_version": 2,
            "trace_id": "t2",
            "run_id": "r2",
            "advisory_group_key": "g2",
            "created_at": now_ts - 25,
            "tool": "Task",
            "session_kind": "subagent",
            "sources": ["semantic"],
            "helpful": False,
            "followed": True,
            "status": "ignored",
        },
        {
            "schema_version": 2,
            "trace_id": "t3",
            "run_id": "",
            "advisory_group_key": "g3",
            "created_at": now_ts - 35,
            "tool": "Task",
            "session_kind": "subagent",
            "sources": [],
            "helpful": True,
            "followed": False,
            "status": "acted",
        },
    ]

    _write_jsonl(req, req_rows)
    _write_jsonl(fb, fb_rows)

    out = build_rollup(
        now_ts=now_ts,
        window_days=7,
        requests_file=req,
        feedback_file=fb,
    )

    totals = out["totals"]
    assert totals["requests_window"] == 3
    assert totals["strict_requests_window"] == 1
    assert totals["feedback_window"] == 3
    assert totals["strict_feedback_window"] == 2
    assert totals["strict_request_ratio"] == 0.3333
    assert totals["strict_feedback_ratio"] == 0.6667

    slices = out["lineage_slices"]
    assert slices["by_tool"]["Edit"] == 1
    assert slices["by_tool"]["Task"] == 1
    assert slices["by_session_kind"]["main"] == 1
    assert slices["by_session_kind"]["subagent"] == 1
    assert slices["by_source"]["semantic"] == 2
    assert slices["by_source"]["bank"] == 1

    quality = out["quality"]
    assert quality["helpful_rate"] == 0.5
    assert quality["followed_rate"] == 1.0
    assert quality["acted_rate"] == 0.5


def test_render_markdown_includes_rollup_sections():
    report = {
        "generated_at": "2026-02-26T00:00:00+00:00",
        "window_days": 7,
        "totals": {
            "requests_window": 10,
            "feedback_window": 8,
            "strict_request_ratio": 0.9,
            "strict_feedback_ratio": 0.75,
        },
        "quality": {"helpful_rate": 0.5, "followed_rate": 0.625, "acted_rate": 0.25},
        "lineage_slices": {
            "by_source": {"semantic": 3},
            "by_tool": {"Edit": 2},
            "by_session_kind": {"main": 2},
        },
    }
    md = render_markdown(report)
    assert "OpenClaw Strict Quality Rollup" in md
    assert "By Source" in md
    assert "`semantic`: `3`" in md

