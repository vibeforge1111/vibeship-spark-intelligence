from __future__ import annotations

import lib.advisory_engine as engine


def test_session_lineage_detects_subagent_tree():
    out = engine._session_lineage("agent:spark-ship:subagent:abc")
    assert out["session_kind"] == "subagent"
    assert out["is_subagent"] is True
    assert out["depth_hint"] == 2
    assert out["session_tree_key"] == "agent:spark-ship"


def test_dedupe_scope_key_tree_mode(monkeypatch):
    monkeypatch.setattr(engine, "GLOBAL_DEDUPE_SCOPE", "tree")
    key = engine._dedupe_scope_key("agent:spark-ship:subagent:abc")
    assert key == "agent:spark-ship"


def test_dedupe_scope_key_contextual_mode(monkeypatch):
    """Contextual mode includes intent_family and task_phase in the scope key."""
    monkeypatch.setattr(engine, "GLOBAL_DEDUPE_SCOPE", "contextual")

    # With both context dimensions
    key = engine._dedupe_scope_key(
        "agent:spark-ship:subagent:abc",
        intent_family="emergent_refactor",
        task_phase="implementation",
    )
    assert key == "agent:spark-ship:implementation:emergent_refactor"

    # Different phase = different key
    key2 = engine._dedupe_scope_key(
        "agent:spark-ship:subagent:abc",
        intent_family="emergent_refactor",
        task_phase="exploration",
    )
    assert key2 == "agent:spark-ship:exploration:emergent_refactor"
    assert key != key2

    # Different intent = different key
    key3 = engine._dedupe_scope_key(
        "agent:spark-ship:subagent:abc",
        intent_family="emergent_debug",
        task_phase="implementation",
    )
    assert key3 == "agent:spark-ship:implementation:emergent_debug"
    assert key != key3

    # Missing context falls back to tree key only
    key_bare = engine._dedupe_scope_key("agent:spark-ship:main")
    assert key_bare == "agent:spark-ship"


def test_global_recently_emitted_respects_scope_key(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "GLOBAL_DEDUPE_LOG", tmp_path / "global.jsonl")
    now = 1000.0
    engine._append_jsonl_capped(
        engine.GLOBAL_DEDUPE_LOG,
        {"ts": now - 5, "tool": "Edit", "advice_id": "a1", "scope_key": "agent:spark-ship"},
        max_lines=50,
    )

    hit_same_scope = engine._global_recently_emitted(
        tool_name="Read",
        advice_id="a1",
        now_ts=now,
        cooldown_s=60.0,
        scope_key="agent:spark-ship",
    )
    miss_other_scope = engine._global_recently_emitted(
        tool_name="Read",
        advice_id="a1",
        now_ts=now,
        cooldown_s=60.0,
        scope_key="agent:other",
    )

    assert hit_same_scope is not None
    assert miss_other_scope is None
