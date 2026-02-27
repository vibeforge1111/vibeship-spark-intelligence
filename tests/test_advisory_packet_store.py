from __future__ import annotations

import json
import time

import lib.advisory_packet_spine as packet_spine
import lib.advisory_packet_store as store


def _patch_store_paths(monkeypatch, tmp_path):
    packet_dir = tmp_path / "advice_packets"
    monkeypatch.setattr(store, "PACKET_DIR", packet_dir)
    monkeypatch.setattr(store, "INDEX_FILE", packet_dir / "index.json")
    monkeypatch.setattr(store, "PREFETCH_QUEUE_FILE", packet_dir / "prefetch_queue.jsonl")
    monkeypatch.setattr(packet_spine, "SPINE_DB", packet_dir / "packet_spine.db")
    monkeypatch.setattr(store, "PACKET_SQLITE_LOOKUP_ENABLED", False)


def test_packet_store_create_lookup_invalidate(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)

    packet = store.build_packet(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
        advisory_text="Validate auth server-side.",
        source_mode="deterministic",
        advice_items=[{"advice_id": "a1", "text": "Validate auth server-side."}],
        lineage={"sources": ["baseline"], "memory_absent_declared": False},
        ttl_s=120,
    )
    packet_id = store.save_packet(packet)

    fetched = store.lookup_exact(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Edit",
        intent_family="auth_security",
    )
    assert fetched is not None
    assert fetched["packet_id"] == packet_id

    assert store.invalidate_packet(packet_id, reason="test") is True
    assert (
        store.lookup_exact(
            project_key="proj",
            session_context_key="ctx",
            tool_name="Edit",
            intent_family="auth_security",
        )
        is None
    )


def test_packet_store_requires_lineage_fields(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)

    packet = store.build_packet(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Read",
        intent_family="knowledge_alignment",
        task_plane="build_delivery",
        advisory_text="Read target files first.",
        source_mode="deterministic",
        lineage={"sources": ["x"], "memory_absent_declared": False},
    )
    packet["lineage"] = {"sources": ["x"]}

    try:
        store.save_packet(packet)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "missing_lineage_fields" in str(exc)


def test_packet_store_relaxed_lookup_prefers_matching_tool(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)

    p1 = store.build_packet(
        project_key="proj",
        session_context_key="c1",
        tool_name="*",
        intent_family="auth_security",
        task_plane="build_delivery",
        advisory_text="Generic auth guidance.",
        source_mode="baseline",
        lineage={"sources": ["baseline"], "memory_absent_declared": False},
        ttl_s=120,
    )
    time.sleep(0.01)
    p2 = store.build_packet(
        project_key="proj",
        session_context_key="c2",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
        advisory_text="Edit auth middleware safely.",
        source_mode="live",
        lineage={"sources": ["cognitive"], "memory_absent_declared": False},
        ttl_s=120,
    )
    store.save_packet(p1)
    store.save_packet(p2)

    relaxed = store.lookup_relaxed(
        project_key="proj",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
    )
    assert relaxed is not None
    assert relaxed["tool_name"] == "Edit"


def test_prefetch_queue_append(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)
    job_id = store.enqueue_prefetch_job({"session_id": "s1", "intent_family": "auth_security"})
    assert job_id.startswith("pf_")

    lines = store.PREFETCH_QUEUE_FILE.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["job_id"] == job_id


def test_relaxed_lookup_prefers_higher_effectiveness(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)

    stale = store.build_packet(
        project_key="proj",
        session_context_key="c1",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
        advisory_text="Older packet.",
        source_mode="prefetch",
        advice_items=[{"advice_id": "old-a1", "text": "older"}],
        lineage={"sources": ["prefetch"], "memory_absent_declared": False},
        ttl_s=300,
    )
    better = store.build_packet(
        project_key="proj",
        session_context_key="c2",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
        advisory_text="Better packet.",
        source_mode="prefetch",
        advice_items=[{"advice_id": "new-a1", "text": "better"}],
        lineage={"sources": ["prefetch"], "memory_absent_declared": False},
        ttl_s=300,
    )
    stale_id = store.save_packet(stale)
    better_id = store.save_packet(better)

    store.record_packet_feedback(stale_id, helpful=False, followed=True, source="test")
    store.record_packet_feedback(stale_id, helpful=False, followed=True, source="test")
    store.record_packet_feedback(better_id, helpful=True, followed=True, source="test")
    store.record_packet_feedback(better_id, helpful=True, followed=True, source="test")

    chosen = store.lookup_relaxed(
        project_key="proj",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
    )
    assert chosen is not None
    assert chosen["packet_id"] == better_id


def test_relaxed_lookup_skips_low_readiness_packets(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(store, "RELAXED_MIN_READINESS_SCORE", 0.95)

    packet = store.build_packet(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
        advisory_text="Soon-expiring low-readiness packet.",
        source_mode="prefetch",
        lineage={"sources": ["prefetch"], "memory_absent_declared": False},
        ttl_s=300,
    )
    store.save_packet(packet)

    chosen = store.lookup_relaxed(
        project_key="proj",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
    )
    assert chosen is None


def test_implicit_feedback_updates_effectiveness_even_when_not_followed(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)
    packet = store.build_packet(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
        advisory_text="Use safer edit path.",
        source_mode="prefetch",
        lineage={"sources": ["prefetch"], "memory_absent_declared": False},
        ttl_s=300,
    )
    packet_id = store.save_packet(packet)
    before = store.get_packet(packet_id)
    before_score = float((before or {}).get("effectiveness_score", 0.5))

    store.record_packet_feedback(
        packet_id,
        helpful=False,
        noisy=False,
        followed=False,
        source="implicit_post_tool",
    )

    after = store.get_packet(packet_id)
    assert after is not None
    assert int(after.get("unhelpful_count", 0)) >= 1
    assert float(after.get("effectiveness_score", 0.5)) < before_score


def test_record_packet_feedback_for_advice(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)
    packet = store.build_packet(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Read",
        intent_family="knowledge_alignment",
        task_plane="build_delivery",
        advisory_text="Read docs first.",
        source_mode="prefetch",
        advice_items=[{"advice_id": "aid-1", "text": "Read docs first."}],
        lineage={"sources": ["prefetch"], "memory_absent_declared": False},
        ttl_s=300,
    )
    packet_id = store.save_packet(packet)
    result = store.record_packet_feedback_for_advice(
        "aid-1",
        helpful=False,
        noisy=True,
        followed=False,
        source="test",
    )
    assert result.get("ok") is True
    assert result.get("packet_id") == packet_id
    updated = store.get_packet(packet_id)
    assert updated is not None
    assert int(updated.get("feedback_count", 0)) >= 1
    assert int(updated.get("noisy_count", 0)) >= 1


def test_invalidate_packets_with_file_hint_matches_full_packet(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)

    p_hit = store.build_packet(
        project_key="proj",
        session_context_key="ctx1",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
        advisory_text="Update lib/bridge_cycle.py and re-run validation.",
        source_mode="prefetch",
        advice_items=[{"advice_id": "a1", "text": "Touch bridge_cycle.py only"}],
        lineage={"sources": ["prefetch"], "memory_absent_declared": False},
        ttl_s=300,
    )
    p_miss = store.build_packet(
        project_key="proj",
        session_context_key="ctx2",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
        advisory_text="Update lib/advisor.py with safer ranking.",
        source_mode="prefetch",
        advice_items=[{"advice_id": "a2", "text": "Touch advisor.py"}],
        lineage={"sources": ["prefetch"], "memory_absent_declared": False},
        ttl_s=300,
    )

    hit_id = store.save_packet(p_hit)
    miss_id = store.save_packet(p_miss)

    count = store.invalidate_packets(project_key="proj", file_hint="lib/bridge_cycle.py", reason="edited_file")
    assert count == 1

    hit_packet = store.get_packet(hit_id)
    miss_packet = store.get_packet(miss_id)
    assert hit_packet is not None and bool(hit_packet.get("invalidated")) is True
    assert miss_packet is not None and bool(miss_packet.get("invalidated")) is False


def test_packet_store_apply_config_updates_defaults(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(store, "DEFAULT_PACKET_TTL_S", 900.0)
    monkeypatch.setattr(store, "MAX_INDEX_PACKETS", 2000)

    result = store.apply_packet_store_config(
        {
            "packet_ttl_s": 1800,
            "max_index_packets": 3500,
            "relaxed_effectiveness_weight": 3.0,
            "relaxed_low_effectiveness_threshold": 0.25,
            "relaxed_low_effectiveness_penalty": 0.8,
            "relaxed_min_match_dimensions": 1,
            "relaxed_min_match_score": 3.0,
        }
    )
    assert "packet_ttl_s" in result.get("applied", [])
    assert "max_index_packets" in result.get("applied", [])

    packet = store.build_packet(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Read",
        intent_family="knowledge_alignment",
        task_plane="build_delivery",
        advisory_text="Read docs first.",
        source_mode="deterministic",
        lineage={"sources": ["baseline"], "memory_absent_declared": False},
    )
    ttl_s = float(packet.get("fresh_until_ts", 0.0)) - float(packet.get("created_ts", 0.0))
    assert 1799.0 <= ttl_s <= 1801.0

    cfg = store.get_packet_store_config()
    assert int(cfg.get("max_index_packets", 0)) == 3500
    assert float(cfg.get("packet_ttl_s", 0.0)) == 1800.0
    assert int(cfg.get("relaxed_min_match_dimensions", 0)) == 1
    assert float(cfg.get("relaxed_min_match_score", 0.0)) == 3.0


def test_relaxed_lookup_rejects_plane_only_match(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)

    packet = store.build_packet(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Read",
        intent_family="knowledge_alignment",
        task_plane="build_delivery",
        advisory_text="Read docs first.",
        source_mode="prefetch",
        lineage={"sources": ["prefetch"], "memory_absent_declared": False},
        ttl_s=300,
    )
    store.save_packet(packet)

    # Same project and plane, but different tool + intent should not pass
    # relaxed minimum match score.
    chosen = store.lookup_relaxed(
        project_key="proj",
        tool_name="Bash",
        intent_family="orchestration_execution",
        task_plane="build_delivery",
    )
    assert chosen is None


def test_relaxed_lookup_candidates_returns_empty_list_on_miss(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)

    out = store.lookup_relaxed_candidates(
        project_key="proj",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
    )
    assert out == []


def test_lookup_exact_can_resolve_via_sqlite_alias_when_index_missing(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(store, "PACKET_SQLITE_LOOKUP_ENABLED", True)

    packet = store.build_packet(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
        advisory_text="sqlite exact lookup path",
        source_mode="prefetch",
        lineage={"sources": ["prefetch"], "memory_absent_declared": False},
        ttl_s=300,
    )
    packet_id = store.save_packet(packet)

    index = store._load_index()
    index["by_exact"] = {}
    store._save_index(index)

    out = store.lookup_exact(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Edit",
        intent_family="auth_security",
    )
    assert out is not None
    assert str(out.get("packet_id") or "") == packet_id


def test_lookup_relaxed_candidates_can_resolve_via_sqlite_when_index_missing(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(store, "PACKET_SQLITE_LOOKUP_ENABLED", True)

    packet = store.build_packet(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
        advisory_text="sqlite relaxed lookup path",
        source_mode="prefetch",
        lineage={"sources": ["prefetch"], "memory_absent_declared": False},
        ttl_s=300,
    )
    store.save_packet(packet)

    index = store._load_index()
    index["packet_meta"] = {}
    store._save_index(index)

    out = store.lookup_relaxed_candidates(
        project_key="proj",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
    )
    assert out
    assert str((out[0] or {}).get("packet_id") or "").startswith("pkt_")


def test_record_packet_usage_refreshes_fresh_until(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)

    packet = store.build_packet(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
        advisory_text="Keep auth checks deterministic.",
        source_mode="prefetch",
        lineage={"sources": ["prefetch"], "memory_absent_declared": False},
        ttl_s=120,
    )
    packet_id = store.save_packet(packet)

    stale = store.get_packet(packet_id)
    assert stale is not None
    stale["fresh_until_ts"] = time.time() - 5.0
    store.save_packet(stale)

    before = store.get_packet(packet_id)
    assert before is not None
    assert float(before.get("fresh_until_ts", 0.0) or 0.0) < time.time()

    out = store.record_packet_usage(packet_id, emitted=False, route="packet_exact")
    assert out.get("ok") is True

    after = store.get_packet(packet_id)
    assert after is not None
    assert float(after.get("fresh_until_ts", 0.0) or 0.0) > time.time() + 100.0


def test_store_status_counts_recent_used_stale_as_refreshable(monkeypatch, tmp_path):
    _patch_store_paths(monkeypatch, tmp_path)
    now = time.time()

    packet = store.build_packet(
        project_key="proj",
        session_context_key="ctx",
        tool_name="Edit",
        intent_family="auth_security",
        task_plane="build_delivery",
        advisory_text="Refresh stale packets that were recently used.",
        source_mode="prefetch",
        lineage={"sources": ["prefetch"], "memory_absent_declared": False},
        ttl_s=120,
    )
    packet["fresh_until_ts"] = now - 10.0
    packet["updated_ts"] = now - 120.0
    packet["usage_count"] = 2
    store.save_packet(packet)

    status = store.get_store_status()
    assert int(status.get("fresh_packets", 0)) == 0
    assert int(status.get("refreshable_stale_packets", 0)) >= 1
    assert int(status.get("effective_fresh_packets", 0)) >= 1
    assert float(status.get("freshness_ratio", 0.0)) >= 1.0
