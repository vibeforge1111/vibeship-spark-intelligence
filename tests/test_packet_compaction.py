from __future__ import annotations

from lib.packet_compaction import build_packet_compaction_plan


def test_plan_marks_stale_never_used_for_delete() -> None:
    now_ts = 1_000_000.0
    rows = [
        {
            "packet_id": "pkt-1",
            "updated_ts": now_ts - (10 * 86400.0),
            "fresh_until_ts": now_ts - 10.0,
            "usage_count": 0,
            "feedback_count": 0,
            "effectiveness_score": 0.9,
            "invalidated": False,
        }
    ]
    plan = build_packet_compaction_plan(rows, now_ts=now_ts, stale_age_days=7.0)
    assert plan["summary"]["by_action"]["delete"] == 1
    assert plan["candidates"][0]["reason"] == "stale_never_used"


def test_plan_marks_cold_packet_for_update() -> None:
    now_ts = 1_000_000.0
    rows = [
        {
            "packet_id": "pkt-2",
            "updated_ts": now_ts - (3 * 86400.0),
            "fresh_until_ts": now_ts + 60.0,
            "usage_count": 0,
            "feedback_count": 0,
            "effectiveness_score": 0.7,
            "invalidated": False,
        }
    ]
    plan = build_packet_compaction_plan(rows, now_ts=now_ts, review_age_days=2.0)
    assert plan["summary"]["by_action"]["update"] == 1
    assert plan["candidates"][0]["reason"] == "cold_packet_review"


def test_plan_keeps_invalidated_packets_noop() -> None:
    now_ts = 1_000_000.0
    rows = [
        {
            "packet_id": "pkt-3",
            "updated_ts": now_ts - (12 * 86400.0),
            "fresh_until_ts": now_ts - 100.0,
            "usage_count": 0,
            "feedback_count": 0,
            "effectiveness_score": 0.01,
            "invalidated": True,
        }
    ]
    plan = build_packet_compaction_plan(rows, now_ts=now_ts)
    assert plan["summary"]["by_action"]["noop"] == 1
    assert plan["candidates"][0]["reason"] == "already_invalidated"

