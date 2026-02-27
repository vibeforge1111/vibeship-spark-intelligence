import json
import time

import lib.advisor as advisor_mod


class _DummyCognitive:
    pass


class _DummyRalph:
    def __init__(self):
        self.calls = []

    def track_outcome(self, *_args, **_kwargs):
        self.calls.append((_args, _kwargs))
        return None

    def get_insight_effectiveness(self, *_args, **_kwargs):
        return 0.5


def _patch_advisor_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(advisor_mod, "ADVISOR_DIR", tmp_path)
    monkeypatch.setattr(advisor_mod, "ADVICE_LOG", tmp_path / "advice_log.jsonl")
    monkeypatch.setattr(advisor_mod, "EFFECTIVENESS_FILE", tmp_path / "effectiveness.json")
    monkeypatch.setattr(advisor_mod, "ADVISOR_METRICS", tmp_path / "metrics.json")
    monkeypatch.setattr(advisor_mod, "RECENT_ADVICE_LOG", tmp_path / "recent_advice.jsonl")
    monkeypatch.setattr(advisor_mod, "get_cognitive_learner", lambda: _DummyCognitive())
    monkeypatch.setattr(advisor_mod, "get_mind_bridge", lambda: None)
    monkeypatch.setattr("lib.meta_ralph.get_meta_ralph", lambda: _DummyRalph())


def test_effectiveness_normalization_clamps_invalid_counters(monkeypatch, tmp_path):
    _patch_advisor_paths(monkeypatch, tmp_path)
    advisor_mod.EFFECTIVENESS_FILE.write_text(
        json.dumps(
            {
                "total_advice_given": 2,
                "total_followed": 9,
                "total_helpful": 12,
                "by_source": {
                    "cognitive": {"total": 1, "helpful": 3},
                },
            }
        ),
        encoding="utf-8",
    )

    advisor = advisor_mod.SparkAdvisor()
    assert advisor.effectiveness["total_advice_given"] == 2
    assert advisor.effectiveness["total_followed"] == 2
    assert advisor.effectiveness["total_helpful"] == 2
    assert advisor.effectiveness["by_source"]["cognitive"]["total"] == 1
    assert advisor.effectiveness["by_source"]["cognitive"]["helpful"] == 1


def test_source_effectiveness_stale_rows_decay_to_zero(monkeypatch, tmp_path):
    _patch_advisor_paths(monkeypatch, tmp_path)
    stale_ts = time.time() - (advisor_mod.SOURCE_EFFECTIVENESS_STALE_SECONDS + 3600)
    advisor_mod.EFFECTIVENESS_FILE.write_text(
        json.dumps(
            {
                "by_source": {
                    "cognitive": {"total": 50, "helpful": 25, "last_ts": stale_ts},
                },
            }
        ),
        encoding="utf-8",
    )

    advisor = advisor_mod.SparkAdvisor()
    bucket = advisor.effectiveness["by_source"]["cognitive"]
    assert bucket["total"] == 0
    assert bucket["helpful"] == 0


def test_report_action_outcome_dedupes_followed_counts(monkeypatch, tmp_path):
    _patch_advisor_paths(monkeypatch, tmp_path)
    advisor = advisor_mod.SparkAdvisor()
    advisor.effectiveness["total_advice_given"] = 3
    advisor._save_effectiveness()

    recent_entry = {
        "ts": time.time(),
        "tool": "Edit",
        "advice_ids": ["a1", "a2", "a3"],
        "insight_keys": ["k1", "k2", "k3"],
        "sources": ["cognitive", "cognitive", "cognitive"],
    }
    advisor_mod.RECENT_ADVICE_LOG.write_text(
        json.dumps(recent_entry) + "\n",
        encoding="utf-8",
    )

    advisor.report_action_outcome("Edit", success=True, advice_was_relevant=False)
    assert advisor.effectiveness["total_followed"] == 0
    assert advisor.effectiveness["total_helpful"] == 0

    advisor.report_action_outcome("Edit", success=True, advice_was_relevant=True)
    assert advisor.effectiveness["total_followed"] == 3
    assert advisor.effectiveness["total_helpful"] == 3
    assert advisor.effectiveness["by_source"]["cognitive"]["last_ts"] > 0

    # Same advice IDs should not inflate aggregate counters on repeated reports.
    advisor.report_action_outcome("Edit", success=True, advice_was_relevant=True)
    assert advisor.effectiveness["total_followed"] == 3
    assert advisor.effectiveness["total_helpful"] == 3
    assert advisor.effectiveness["total_followed"] <= advisor.effectiveness["total_advice_given"]


def test_repair_effectiveness_counters_clamps(monkeypatch, tmp_path):
    _patch_advisor_paths(monkeypatch, tmp_path)
    advisor_mod.EFFECTIVENESS_FILE.write_text(
        json.dumps(
            {
                "total_advice_given": 4,
                "total_followed": 99,
                "total_helpful": 88,
            }
        ),
        encoding="utf-8",
    )

    advisor = advisor_mod.SparkAdvisor()
    result = advisor.repair_effectiveness_counters()

    assert result["after"]["total_advice_given"] == 4
    assert result["after"]["total_followed"] == 4
    assert result["after"]["total_helpful"] == 4


def test_report_outcome_does_not_emit_unknown_to_meta_ralph(monkeypatch, tmp_path):
    _patch_advisor_paths(monkeypatch, tmp_path)
    ralph = _DummyRalph()
    monkeypatch.setattr("lib.meta_ralph.get_meta_ralph", lambda: ralph)

    advisor = advisor_mod.SparkAdvisor()
    advisor.report_outcome("aid-1", was_followed=False, was_helpful=None, notes="unknown case")
    advisor.report_outcome("aid-2", was_followed=True, was_helpful=False, notes="bad case")

    # unknown outcome should not be emitted; explicit bad should be emitted once.
    assert len(ralph.calls) == 1
    args, _kwargs = ralph.calls[0]
    assert args[0] == "aid-2"
    assert args[1] == "bad"


def test_report_action_outcome_links_by_trace_id(monkeypatch, tmp_path):
    _patch_advisor_paths(monkeypatch, tmp_path)
    advisor = advisor_mod.SparkAdvisor()
    advisor.effectiveness["total_advice_given"] = 2
    advisor._save_effectiveness()

    recent_entry = {
        "ts": time.time(),
        "tool": "UnrelatedTool",
        "trace_id": "trace-123",
        "advice_ids": ["a1", "a2"],
        "insight_keys": ["k1", "k2"],
        "sources": ["cognitive", "cognitive"],
    }
    advisor_mod.RECENT_ADVICE_LOG.write_text(
        json.dumps(recent_entry) + "\n",
        encoding="utf-8",
    )

    # Tool name does not match; trace_id match should still link and count.
    advisor.report_action_outcome(
        "Edit",
        success=True,
        advice_was_relevant=True,
        trace_id="trace-123",
    )
    assert advisor.effectiveness["total_followed"] == 2
    assert advisor.effectiveness["total_helpful"] == 2


def test_recent_advice_lookup_does_not_cross_link_task_fallback(monkeypatch, tmp_path):
    _patch_advisor_paths(monkeypatch, tmp_path)
    advisor = advisor_mod.SparkAdvisor()

    recent_entry = {
        "ts": time.time(),
        "tool": "Task",
        "trace_id": "trace-task-1",
        "advice_ids": ["task-a1"],
        "insight_keys": ["tool:task"],
        "sources": ["self_awareness"],
    }
    advisor_mod.RECENT_ADVICE_LOG.write_text(
        json.dumps(recent_entry) + "\n",
        encoding="utf-8",
    )

    # Do not link Task advice to other tool outcomes by default.
    assert advisor._get_recent_advice_entry("Edit") is None

    # Explicit fallback keeps legacy behavior available for Task workflows.
    task_entry = advisor._get_recent_advice_entry(
        "Edit",
        allow_task_fallback=True,
    )
    assert task_entry is not None
    assert task_entry.get("tool") == "Task"
