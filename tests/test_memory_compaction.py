from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lib.memory_compaction import activation_score
from lib.memory_compaction import age_days
from lib.memory_compaction import build_compaction_plan
from lib.memory_compaction import build_duplicate_groups
from lib.memory_compaction import normalize_insight_text


def test_activation_score_decays_with_age():
    fresh = activation_score(reliability=0.8, age_days_value=0.0, half_life_days=60.0)
    stale = activation_score(reliability=0.8, age_days_value=120.0, half_life_days=60.0)
    assert fresh > stale
    assert stale > 0.0


def test_normalize_insight_text_collapses_noise():
    raw = "  Improve! retrieval-rate, with   better  context.  "
    assert normalize_insight_text(raw) == "improve retrieval rate with better context"


def test_build_duplicate_groups_uses_normalized_signature():
    rows = [
        {"key": "a", "insight": "Use semantic retrieval before lexical backoff for memory quality."},
        {"key": "b", "insight": "Use semantic retrieval before lexical backoff for memory quality!"},
        {"key": "c", "insight": "different"},
    ]
    groups = build_duplicate_groups(rows, min_chars=20)
    assert len(groups) == 1
    merged = next(iter(groups.values()))
    assert sorted(merged) == ["a", "b"]


def test_build_compaction_plan_marks_delete_and_update():
    now = datetime.now(timezone.utc)
    very_old = (now - timedelta(days=240)).isoformat()
    recent = (now - timedelta(days=2)).isoformat()
    rows = [
        {
            "key": "old_low",
            "insight": "A stale low confidence insight that should be evicted from compaction plan.",
            "category": "context",
            "reliability": 0.2,
            "created_at": very_old,
            "last_validated_at": very_old,
        },
        {
            "key": "dup_1",
            "insight": "Always bind advisory outcomes to explicit trace ids.",
            "category": "reasoning",
            "reliability": 0.8,
            "created_at": recent,
            "last_validated_at": recent,
        },
        {
            "key": "dup_2",
            "insight": "Always bind advisory outcomes to explicit trace ids!",
            "category": "reasoning",
            "reliability": 0.78,
            "created_at": recent,
            "last_validated_at": recent,
        },
    ]
    plan = build_compaction_plan(rows, max_age_days=180.0, min_activation=0.2)
    by_key = {row["key"]: row for row in plan["candidates"]}
    assert by_key["old_low"]["action"] == "delete"
    assert by_key["dup_1"]["action"] == "update"
    assert by_key["dup_2"]["action"] == "update"
    assert plan["summary"]["by_action"]["delete"] >= 1
    assert plan["summary"]["by_action"]["update"] >= 2


def test_age_days_prefers_last_validated():
    now = datetime.now(timezone.utc)
    created = (now - timedelta(days=120)).isoformat()
    validated = (now - timedelta(days=5)).isoformat()
    age = age_days(created_at=created, last_validated_at=validated, now=now)
    assert 4.5 <= age <= 5.5

