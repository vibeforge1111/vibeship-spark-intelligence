from __future__ import annotations

from lib.observatory.stage_pages import _gen_eidos


def test_stage7_page_includes_curriculum_burndown_section():
    page = _gen_eidos(
        {
            "db_exists": True,
            "db_size": 2048,
            "episodes": 12,
            "steps": 80,
            "distillations": 15,
            "active_episodes": 2,
            "active_steps": 6,
            "curriculum_rows_scanned": 120,
            "curriculum_cards_generated": 18,
            "curriculum_high": 4,
            "curriculum_medium": 9,
            "curriculum_low": 5,
            "curriculum_high_delta": -2,
            "curriculum_history_points": 7,
            "curriculum_gaps": {"low_unified_score": 5, "suppressed_statement": 3},
            "recent_distillations": [],
            "advisory_quality_histogram": [],
            "feedback_loop": {},
            "suppression_breakdown": {},
        },
        {},
    )

    assert "Distillation Curriculum Burn-Down" in page
    assert "| High severity | 4 |" in page
    assert "| High-severity delta | -2 |" in page
    assert "low_unified_score" in page
