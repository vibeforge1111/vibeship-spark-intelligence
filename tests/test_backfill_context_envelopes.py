from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.backfill_context_envelopes as backfill


def test_plan_backfill_updates_short_contexts(tmp_path: Path):
    path = tmp_path / "cognitive_insights.json"
    data = {
        "k1": {
            "insight": "Validate input schemas before writing to storage.",
            "context": "write path",
            "category": "reasoning",
            "source": "distillation",
            "advisory_quality": {
                "structure": {
                    "condition": "saving user records",
                    "action": "enforce schema validation",
                    "reasoning": "avoids malformed persistence",
                }
            },
        },
        "k2": {
            "insight": "Keep tests deterministic for CI stability.",
            "context": "tests",
            "category": "wisdom",
            "source": "capture",
        },
    }
    path.write_text(json.dumps(data), encoding="utf-8")

    plan = backfill.plan_backfill(path)

    assert plan["ok"] is True
    assert plan["items_total"] == 2
    assert plan["items_updated"] == 2
    assert plan["context_p50_after"] > plan["context_p50_before"]


def test_apply_backfill_writes_backup_and_updates_context(tmp_path: Path):
    path = tmp_path / "cognitive_insights.json"
    data = {
        "k1": {
            "insight": "Use retries with jitter for flaky network APIs.",
            "context": "network",
            "category": "reasoning",
            "source": "capture",
        }
    }
    path.write_text(json.dumps(data), encoding="utf-8")

    plan = backfill.plan_backfill(path)
    result = backfill.apply_backfill(plan)

    assert result["applied"] is True
    assert Path(str(result["backup"])).exists()

    updated = json.loads(path.read_text(encoding="utf-8"))
    assert len(updated["k1"]["context"]) >= 120
    assert "Source: capture" in updated["k1"]["context"]
