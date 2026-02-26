from __future__ import annotations

from pathlib import Path

import pytest

import lib.advisor as advisor_mod
import lib.meta_ralph as meta_ralph_mod
from lib.advisor import Advice

pytestmark = pytest.mark.integration


class _DummyCognitive:
    pass


def _patch_advisor_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    advisor_dir = tmp_path / "advisor"
    monkeypatch.setattr(advisor_mod, "ADVISOR_DIR", advisor_dir)
    monkeypatch.setattr(advisor_mod, "ADVICE_LOG", advisor_dir / "advice_log.jsonl")
    monkeypatch.setattr(advisor_mod, "RECENT_ADVICE_LOG", advisor_dir / "recent_advice.jsonl")
    monkeypatch.setattr(advisor_mod, "EFFECTIVENESS_FILE", advisor_dir / "effectiveness.json")
    monkeypatch.setattr(advisor_mod, "ADVISOR_METRICS", advisor_dir / "metrics.json")
    monkeypatch.setattr(advisor_mod, "HAS_EIDOS", False)
    monkeypatch.setattr(advisor_mod, "HAS_REQUESTS", False)
    monkeypatch.setattr(advisor_mod, "get_cognitive_learner", lambda: _DummyCognitive())
    monkeypatch.setattr(advisor_mod, "get_mind_bridge", lambda: None)


def _patch_advisor_retrieval(monkeypatch: pytest.MonkeyPatch, advice_items: list[Advice]) -> None:
    monkeypatch.setattr(advisor_mod.SparkAdvisor, "_get_bank_advice", lambda _s, _c: [])
    monkeypatch.setattr(
        advisor_mod.SparkAdvisor,
        "_get_cognitive_advice",
        lambda _s, _t, _c, _sc=None: list(advice_items),
    )
    monkeypatch.setattr(advisor_mod.SparkAdvisor, "_get_chip_advice", lambda _s, _c: [])
    monkeypatch.setattr(advisor_mod.SparkAdvisor, "_get_tool_specific_advice", lambda _s, _t: [])
    monkeypatch.setattr(advisor_mod.SparkAdvisor, "_get_opportunity_advice", lambda _s, **_k: [])
    monkeypatch.setattr(advisor_mod.SparkAdvisor, "_get_surprise_advice", lambda _s, _t, _c: [])
    monkeypatch.setattr(advisor_mod.SparkAdvisor, "_get_skill_advice", lambda _s, _c: [])
    monkeypatch.setattr(advisor_mod.SparkAdvisor, "_get_convo_advice", lambda _s, _t, _c: [])
    monkeypatch.setattr(advisor_mod.SparkAdvisor, "_get_engagement_advice", lambda _s, _t, _c: [])
    monkeypatch.setattr(advisor_mod.SparkAdvisor, "_get_niche_advice", lambda _s, _t, _c: [])
    monkeypatch.setattr(advisor_mod.SparkAdvisor, "_rank_advice", lambda _s, items: list(items))
    monkeypatch.setattr(advisor_mod.SparkAdvisor, "_rank_score", lambda _s, _item: 1.0)


@pytest.fixture
def isolated_meta_ralph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "meta_ralph"
    monkeypatch.setattr(meta_ralph_mod.MetaRalph, "DATA_DIR", data_dir)
    monkeypatch.setattr(meta_ralph_mod.MetaRalph, "ROAST_HISTORY_FILE", data_dir / "roast_history.json")
    monkeypatch.setattr(
        meta_ralph_mod.MetaRalph,
        "OUTCOME_TRACKING_FILE",
        data_dir / "outcome_tracking.json",
    )
    monkeypatch.setattr(
        meta_ralph_mod.MetaRalph,
        "LEARNINGS_STORE_FILE",
        data_dir / "learnings_store.json",
    )
    monkeypatch.setattr(meta_ralph_mod.MetaRalph, "SELF_ROAST_FILE", data_dir / "self_roast.json")
    monkeypatch.setattr(meta_ralph_mod, "_meta_ralph", None)

    ralph = meta_ralph_mod.MetaRalph()
    monkeypatch.setattr(meta_ralph_mod, "get_meta_ralph", lambda mind_client=None: ralph)
    return ralph


def _make_advice(advice_id: str) -> Advice:
    return Advice(
        advice_id=advice_id,
        insight_key=f"insight:{advice_id}",
        text=f"use {advice_id}",
        confidence=0.95,
        source="cognitive",
        context_match=1.0,
        reason="integration-test",
    )


def test_advisor_trace_bound_outcomes_count_as_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_meta_ralph,
):
    _patch_advisor_storage(monkeypatch, tmp_path)
    _patch_advisor_retrieval(monkeypatch, [_make_advice("aid-1"), _make_advice("aid-2")])

    advisor = advisor_mod.SparkAdvisor()
    trace_id = "rt-trace-good-1"
    advice = advisor.advise(
        "Edit",
        {"file_path": "src/main.ts"},
        "apply strict attribution fix",
        include_mind=False,
        trace_id=trace_id,
    )
    assert len(advice) >= 2

    advisor.report_action_outcome(
        "Edit",
        success=True,
        advice_was_relevant=True,
        trace_id=trace_id,
    )

    attr = isolated_meta_ralph.get_source_attribution(limit=8, window_s=1200, require_trace=True)
    row = {r["source"]: r for r in attr["rows"]}["cognitive"]
    assert row["retrieved"] == 2
    assert row["acted_on"] == 2
    assert row["strict_acted_on"] == 2
    assert row["strict_with_explicit_outcome"] == 2
    assert row["strict_effectiveness_rate"] == 1.0


def test_advisor_trace_mismatch_stays_weak_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_meta_ralph,
):
    _patch_advisor_storage(monkeypatch, tmp_path)
    _patch_advisor_retrieval(monkeypatch, [_make_advice("aid-3"), _make_advice("aid-4")])

    advisor = advisor_mod.SparkAdvisor()
    advice_trace = "rt-trace-retrieval"
    outcome_trace = "rt-trace-outcome-mismatch"
    advice = advisor.advise(
        "Edit",
        {"file_path": "src/worker.ts"},
        "simulate trace mismatch",
        include_mind=False,
        trace_id=advice_trace,
    )
    assert len(advice) >= 2

    advisor.report_action_outcome(
        "Edit",
        success=True,
        advice_was_relevant=True,
        trace_id=outcome_trace,
    )

    attr = isolated_meta_ralph.get_source_attribution(limit=8, window_s=1200, require_trace=True)
    row = {r["source"]: r for r in attr["rows"]}["cognitive"]
    assert row["retrieved"] == 2
    assert row["acted_on"] == 2
    assert row["strict_acted_on"] == 0
    assert row["strict_with_explicit_outcome"] == 0
    assert row["strict_effectiveness_rate"] is None
