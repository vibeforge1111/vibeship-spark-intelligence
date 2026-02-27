from __future__ import annotations

import json
from pathlib import Path

from lib.action_matcher import match_actions
from lib.runtime_feedback_parser import split_atomic_recommendations
from lib.score_reporter import compute_kpis


def test_split_atomic_recommendations_markdown_bullets() -> None:
    text = """
    # Spark Advisory
    1. Add retry jitter for outbound requests.
    2) Enforce one state transition at a time.
    - [ ] Log failures with trace_id.
    """
    items = split_atomic_recommendations(text)
    assert len(items) == 3
    assert "retry jitter" in items[0].lower()
    assert "state transition" in items[1].lower()
    assert "trace_id" in items[2].lower()


def test_match_actions_prefers_explicit_feedback(tmp_path: Path) -> None:
    feedback_file = tmp_path / "advice_feedback.jsonl"
    feedback_row = {
        "advice_ids": ["adv-1"],
        "tool": "Bash",
        "helpful": True,
        "followed": True,
        "created_at": 200.0,
    }
    feedback_file.write_text(json.dumps(feedback_row) + "\n", encoding="utf-8")
    reports_dir = tmp_path / "spark_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    outcomes_file = tmp_path / "outcomes.jsonl"
    outcomes_file.write_text("", encoding="utf-8")

    advisories = [
        {
            "advisory_instance_id": "inst-1",
            "advisory_id": "adv-1",
            "recommendation": "Run tests after edits.",
            "created_at": 100.0,
            "session_id": "s1",
            "tool": "Bash",
        }
    ]
    matches = match_actions(
        advisories,
        feedback_file=feedback_file,
        reports_dir=reports_dir,
        outcomes_file=outcomes_file,
        max_match_window_s=3600,
    )
    assert len(matches) == 1
    assert matches[0]["status"] == "acted"
    assert matches[0]["match_type"] == "explicit_feedback"
    assert matches[0]["effect_hint"] == "positive"
    assert matches[0]["latency_s"] == 100.0


def test_compute_kpis_basic() -> None:
    items = [
        {"status": "acted", "effect": "positive", "latency_s": 10.0, "recommendation": "A", "tool": "Bash"},
        {"status": "skipped", "effect": "neutral", "latency_s": None, "recommendation": "B", "tool": "Read"},
        {"status": "unresolved", "effect": "neutral", "latency_s": None, "recommendation": "C", "tool": ""},
    ]
    k = compute_kpis(items)
    assert k["total_advisories"] == 3
    assert k["acted"] == 1
    assert k["action_rate_pct"] == 33.33
    assert k["helpful_rate_pct"] == 100.0
    assert k["median_time_to_action_s"] == 10.0
