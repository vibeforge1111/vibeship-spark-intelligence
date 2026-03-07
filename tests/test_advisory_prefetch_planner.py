"""Tests for lib/advisory_prefetch_planner.py — deterministic prefetch planner."""
from __future__ import annotations

from typing import Any, Dict

import pytest

from lib.advisory_prefetch_planner import (
    plan_prefetch_jobs,
    INTENT_TOOL_PRIORS,
    FALLBACK_TOOLS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job(**kwargs) -> Dict[str, Any]:
    base = {
        "session_id": "sess_001",
        "project_key": "my_project",
        "session_context_key": "default",
        "intent_family": "testing_validation",
        "task_plane": "build_delivery",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# INTENT_TOOL_PRIORS / FALLBACK_TOOLS constants
# ---------------------------------------------------------------------------


def test_all_intent_families_have_entries():
    for family, tools in INTENT_TOOL_PRIORS.items():
        assert len(tools) > 0, f"{family} has no tools"


def test_all_priors_have_tool_name():
    for family, tools in INTENT_TOOL_PRIORS.items():
        for t in tools:
            assert "tool_name" in t


def test_all_priors_have_probability():
    for family, tools in INTENT_TOOL_PRIORS.items():
        for t in tools:
            assert "probability" in t
            assert 0.0 <= t["probability"] <= 1.0


def test_fallback_tools_non_empty():
    assert len(FALLBACK_TOOLS) > 0


def test_fallback_tools_have_required_keys():
    for t in FALLBACK_TOOLS:
        assert "tool_name" in t
        assert "probability" in t


# ---------------------------------------------------------------------------
# plan_prefetch_jobs — basic output structure
# ---------------------------------------------------------------------------


def test_returns_list():
    result = plan_prefetch_jobs(_job())
    assert isinstance(result, list)


def test_each_row_has_required_keys():
    rows = plan_prefetch_jobs(_job())
    required = {"session_id", "project_key", "session_context_key",
                "intent_family", "task_plane", "tool_name", "probability"}
    for row in rows:
        assert required <= set(row.keys())


def test_tool_name_is_non_empty_string():
    rows = plan_prefetch_jobs(_job())
    for row in rows:
        assert isinstance(row["tool_name"], str)
        assert len(row["tool_name"]) > 0


def test_probability_is_float():
    rows = plan_prefetch_jobs(_job())
    for row in rows:
        assert isinstance(row["probability"], float)


# ---------------------------------------------------------------------------
# plan_prefetch_jobs — known intent families
# ---------------------------------------------------------------------------


def test_testing_validation_includes_bash():
    rows = plan_prefetch_jobs(_job(intent_family="testing_validation"))
    tools = {r["tool_name"] for r in rows}
    assert "Bash" in tools


def test_auth_security_includes_read():
    rows = plan_prefetch_jobs(_job(intent_family="auth_security", max_jobs=5))
    tools = {r["tool_name"] for r in rows}
    assert "Read" in tools


def test_knowledge_alignment_includes_read():
    rows = plan_prefetch_jobs(_job(intent_family="knowledge_alignment", max_jobs=5))
    tools = {r["tool_name"] for r in rows}
    assert "Read" in tools


def test_orchestration_includes_task():
    rows = plan_prefetch_jobs(_job(intent_family="orchestration_execution", max_jobs=5))
    tools = {r["tool_name"] for r in rows}
    assert "Task" in tools


# ---------------------------------------------------------------------------
# plan_prefetch_jobs — unknown intent falls back
# ---------------------------------------------------------------------------


def test_unknown_intent_uses_fallback():
    rows = plan_prefetch_jobs(_job(intent_family="totally_unknown"))
    assert len(rows) >= 1
    # Fallback tools should include Read
    tools = {r["tool_name"] for r in rows}
    assert "Read" in tools or "Edit" in tools or "Bash" in tools


def test_empty_intent_uses_fallback():
    rows = plan_prefetch_jobs(_job(intent_family=""))
    assert len(rows) >= 1


# ---------------------------------------------------------------------------
# plan_prefetch_jobs — max_jobs
# ---------------------------------------------------------------------------


def test_max_jobs_default_3():
    rows = plan_prefetch_jobs(_job(intent_family="auth_security"))
    assert len(rows) <= 3


def test_max_jobs_1():
    rows = plan_prefetch_jobs(_job(intent_family="testing_validation"), max_jobs=1)
    assert len(rows) == 1


def test_max_jobs_2():
    rows = plan_prefetch_jobs(_job(intent_family="testing_validation"), max_jobs=2)
    assert len(rows) <= 2


def test_max_jobs_large_returns_all_above_min_prob():
    rows = plan_prefetch_jobs(_job(intent_family="testing_validation"), max_jobs=100, min_probability=0.0)
    priors = INTENT_TOOL_PRIORS["testing_validation"]
    assert len(rows) == len(priors)


# ---------------------------------------------------------------------------
# plan_prefetch_jobs — min_probability filter
# ---------------------------------------------------------------------------


def test_min_probability_filters_low_prob():
    rows = plan_prefetch_jobs(
        _job(intent_family="testing_validation"),
        max_jobs=10,
        min_probability=0.99,
    )
    for row in rows:
        assert row["probability"] >= 0.99


def test_min_probability_zero_includes_all():
    rows = plan_prefetch_jobs(
        _job(intent_family="auth_security"),
        max_jobs=10,
        min_probability=0.0,
    )
    priors = INTENT_TOOL_PRIORS["auth_security"]
    assert len(rows) == len(priors)


def test_min_probability_very_high_may_return_empty():
    # When all tools are below the threshold, rows list is empty (no artificial floor)
    rows = plan_prefetch_jobs(
        _job(intent_family="testing_validation"),
        max_jobs=3,
        min_probability=0.999,
    )
    # All priors for testing_validation have probability < 0.999, so result is []
    assert isinstance(rows, list)
    for row in rows:
        assert row["probability"] >= 0.999


# ---------------------------------------------------------------------------
# plan_prefetch_jobs — result sorted by probability descending
# ---------------------------------------------------------------------------


def test_rows_sorted_descending_by_probability():
    rows = plan_prefetch_jobs(_job(intent_family="auth_security"), max_jobs=10, min_probability=0.0)
    probs = [r["probability"] for r in rows]
    assert probs == sorted(probs, reverse=True)


# ---------------------------------------------------------------------------
# plan_prefetch_jobs — metadata propagated
# ---------------------------------------------------------------------------


def test_session_id_propagated():
    rows = plan_prefetch_jobs(_job(session_id="my_sess"))
    for row in rows:
        assert row["session_id"] == "my_sess"


def test_project_key_propagated():
    rows = plan_prefetch_jobs(_job(project_key="proj_abc"))
    for row in rows:
        assert row["project_key"] == "proj_abc"


def test_intent_family_propagated():
    rows = plan_prefetch_jobs(_job(intent_family="testing_validation"))
    for row in rows:
        assert row["intent_family"] == "testing_validation"


def test_task_plane_propagated():
    rows = plan_prefetch_jobs(_job(task_plane="research_analysis"))
    for row in rows:
        assert row["task_plane"] == "research_analysis"


# ---------------------------------------------------------------------------
# plan_prefetch_jobs — edge cases
# ---------------------------------------------------------------------------


def test_none_job_dict_safe():
    rows = plan_prefetch_jobs(None)  # type: ignore[arg-type]
    assert isinstance(rows, list)
    assert len(rows) >= 1


def test_empty_dict_job_safe():
    rows = plan_prefetch_jobs({})
    assert isinstance(rows, list)
    assert len(rows) >= 1


def test_max_jobs_zero_returns_one():
    # max(1, 0) = 1, so at least one row always
    rows = plan_prefetch_jobs(_job(), max_jobs=0)
    assert len(rows) >= 1
