from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.rebind_outcome_traces as repair


def test_plan_rebind_selects_only_window_bounded_mismatches(tmp_path: Path):
    path = tmp_path / "outcome_tracking.json"
    payload = {
        "records": [
            {
                "learning_id": "aid-1",
                "acted_on": True,
                "trace_id": "t-retrieval-1",
                "outcome_trace_id": "t-outcome-1",
                "retrieved_at": "2026-02-26T10:00:00",
                "outcome_at": "2026-02-26T10:05:00",
            },
            {
                "learning_id": "aid-2",
                "acted_on": True,
                "trace_id": "t-retrieval-2",
                "outcome_trace_id": "t-outcome-2",
                "retrieved_at": "2026-02-26T10:00:00",
                "outcome_at": "2026-02-26T11:30:00",
            },
            {
                "learning_id": "aid-3",
                "acted_on": True,
                "trace_id": "t-same",
                "outcome_trace_id": "t-same",
                "retrieved_at": "2026-02-26T10:00:00",
                "outcome_at": "2026-02-26T10:01:00",
            },
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    plan = repair.plan_rebind(path, window_s=1800)

    assert plan["ok"] is True
    assert plan["mismatched"] == 2
    assert plan["candidates"] == 1
    assert plan["updates"][0]["learning_id"] == "aid-1"


def test_apply_rebind_sets_outcome_trace_to_retrieval_trace(tmp_path: Path):
    path = tmp_path / "outcome_tracking.json"
    payload = {
        "records": [
            {
                "learning_id": "aid-1",
                "source": "cognitive",
                "acted_on": True,
                "trace_id": "t-retrieval-1",
                "outcome_trace_id": "t-outcome-1",
                "retrieved_at": "2026-02-26T10:00:00",
                "outcome_at": "2026-02-26T10:05:00",
            }
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    plan = repair.plan_rebind(path, window_s=1800)
    result = repair.apply_rebind(plan)

    assert result["applied"] is True
    assert result["updated"] == 1
    assert Path(str(result["backup"])).exists()

    updated = json.loads(path.read_text(encoding="utf-8"))
    row = updated["records"][0]
    assert row["outcome_trace_id"] == "t-retrieval-1"
    assert row["reported_outcome_trace_id"] == "t-outcome-1"
