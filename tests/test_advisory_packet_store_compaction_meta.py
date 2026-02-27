from __future__ import annotations

import lib.advisory_packet_spine as packet_spine
import lib.advisory_packet_store as store


def _patch_store_paths(monkeypatch, tmp_path):
    packet_dir = tmp_path / "advice_packets"
    monkeypatch.setattr(store, "PACKET_DIR", packet_dir)
    monkeypatch.setattr(store, "INDEX_FILE", packet_dir / "index.json")
    monkeypatch.setattr(store, "PREFETCH_QUEUE_FILE", packet_dir / "prefetch_queue.jsonl")
    monkeypatch.setattr(packet_spine, "SPINE_DB", packet_dir / "packet_spine.db")


def _save_packet(monkeypatch, tmp_path, *, invalidated: bool, updated_ts: float, advisory_text: str = "alpha"):
    _patch_store_paths(monkeypatch, tmp_path)
    packet = store.build_packet(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Read",
        intent_family="knowledge_alignment",
        task_plane="build_delivery",
        advisory_text=advisory_text,
        source_mode="deterministic",
        lineage={"sources": ["baseline"], "memory_absent_declared": False},
        ttl_s=300,
    )
    packet["updated_ts"] = float(updated_ts)
    packet["fresh_until_ts"] = float(updated_ts + 300.0)
    packet_id = store.save_packet(packet)
    if invalidated:
        assert store.invalidate_packet(packet_id, reason="test")
    return packet_id


def test_list_packet_meta_filters_invalidated_and_orders(monkeypatch, tmp_path):
    active_id = _save_packet(monkeypatch, tmp_path, invalidated=False, updated_ts=200.0, advisory_text="active")
    _save_packet(monkeypatch, tmp_path, invalidated=True, updated_ts=100.0, advisory_text="inactive")

    all_rows = store.list_packet_meta(include_invalidated=True)
    assert len(all_rows) == 2
    assert float(all_rows[0]["updated_ts"]) >= float(all_rows[1]["updated_ts"])

    filtered = store.list_packet_meta(include_invalidated=False)
    assert len(filtered) == 1
    assert filtered[0]["packet_id"] == active_id


def test_mark_packet_compaction_review_sets_marker(monkeypatch, tmp_path):
    packet_id = _save_packet(monkeypatch, tmp_path, invalidated=False, updated_ts=100.0)
    assert store.mark_packet_compaction_review(packet_id, reason="cold_packet_review", ts=321.0) is True

    rows = store.list_packet_meta(include_invalidated=True)
    assert rows
    row = next(r for r in rows if r["packet_id"] == packet_id)
    assert row["compaction_flag"] == "review"
    assert row["compaction_reason"] == "cold_packet_review"
    assert row["compaction_ts"] == 321.0
