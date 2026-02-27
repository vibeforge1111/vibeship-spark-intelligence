from __future__ import annotations

from lib.advisory_spine_parity import compare_snapshots, evaluate_parity_gate


def test_compare_snapshots_tracks_match_and_mismatch():
    index_meta = {
        "pkt-1": {
            "project_key": "proj",
            "session_context_key": "ctx",
            "tool_name": "Edit",
            "intent_family": "auth_security",
            "task_plane": "build_delivery",
            "invalidated": False,
            "fresh_until_ts": 100.0,
            "updated_ts": 90.0,
            "effectiveness_score": 0.7,
            "read_count": 1,
            "usage_count": 1,
            "emit_count": 1,
            "deliver_count": 1,
            "source_summary": ["baseline"],
            "category_summary": ["safety"],
        },
        "pkt-2": {
            "project_key": "proj",
            "session_context_key": "ctx",
            "tool_name": "Read",
            "intent_family": "knowledge_alignment",
            "task_plane": "build_delivery",
            "invalidated": False,
            "fresh_until_ts": 100.0,
            "updated_ts": 90.0,
            "effectiveness_score": 0.8,
            "read_count": 1,
            "usage_count": 1,
            "emit_count": 1,
            "deliver_count": 1,
            "source_summary": ["baseline"],
            "category_summary": ["quality"],
        },
    }
    spine_meta = {
        "pkt-1": dict(index_meta["pkt-1"]),
        "pkt-2": dict(index_meta["pkt-2"], effectiveness_score=0.2),
        "pkt-3": dict(index_meta["pkt-1"], packet_id="pkt-3"),
    }

    parity = compare_snapshots(index_meta, spine_meta, list_limit=10)
    assert parity["index_count"] == 2
    assert parity["spine_count"] == 3
    assert parity["key_overlap_count"] == 2
    assert parity["payload_match_count"] == 1
    assert parity["payload_mismatch_count"] == 1
    assert parity["extra_in_spine_count"] == 1
    assert parity["payload_parity_ratio"] == 0.5


def test_evaluate_parity_gate_enforces_rows_and_ratio():
    parity = {"index_count": 20, "payload_parity_ratio": 0.99}
    gate = evaluate_parity_gate(parity, min_payload_parity=0.995, min_rows=10)
    assert gate["pass"] is False
    assert gate["pass_rows"] is True
    assert gate["pass_ratio"] is False
