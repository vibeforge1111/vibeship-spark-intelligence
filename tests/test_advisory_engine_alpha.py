from __future__ import annotations

import json

import lib.advisory_engine_alpha as alpha_engine
import lib.advisory_implicit_feedback as implicit_feedback
import lib.advisory_packet_store as packet_store
import lib.advisory_state as advisory_state


def _patch_state_and_store(monkeypatch, tmp_path):
    state_dir = tmp_path / "state"
    monkeypatch.setattr(advisory_state, "STATE_DIR", state_dir)

    packet_dir = tmp_path / "packets"
    monkeypatch.setattr(packet_store, "PACKET_DIR", packet_dir)
    monkeypatch.setattr(packet_store, "INDEX_FILE", packet_dir / "index.json")
    monkeypatch.setattr(packet_store, "PREFETCH_QUEUE_FILE", packet_dir / "prefetch_queue.jsonl")

    alpha_log = tmp_path / "advisory_engine_alpha.jsonl"
    monkeypatch.setattr(alpha_engine, "ALPHA_LOG", alpha_log)
    return state_dir, packet_dir, alpha_log


def test_on_user_prompt_builds_alpha_baseline_packet(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)
    monkeypatch.setattr(alpha_engine, "ALPHA_PREFETCH_QUEUE_ENABLED", True)
    monkeypatch.setattr(alpha_engine, "ALPHA_INLINE_PREFETCH_ENABLED", False)
    monkeypatch.setattr(alpha_engine, "_project_key", lambda: "proj")

    alpha_engine.on_user_prompt("s-alpha-1", "Focus on auth hardening and tests.")

    packets = list(packet_store.PACKET_DIR.glob("pkt_*.json"))
    assert packets
    packet = json.loads(packets[-1].read_text(encoding="utf-8"))
    assert packet.get("source_mode") == "baseline_deterministic_alpha"
    assert packet_store.PREFETCH_QUEUE_FILE.exists()

    rows = packet_store.PREFETCH_QUEUE_FILE.read_text(encoding="utf-8").splitlines()
    assert rows
    job = json.loads(rows[-1])
    assert job.get("session_id") == "s-alpha-1"
    assert job.get("alpha_route") is True


def test_on_post_tool_records_outcome_and_invokes_implicit_feedback(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)
    monkeypatch.setattr(alpha_engine, "_project_key", lambda: "proj")

    state = advisory_state.load_state("s-alpha-2")
    state.shown_advice_ids = {"aid-1": 1.0}
    state.last_advisory_packet_id = "pkt-test"
    state.last_advisory_tool = "Edit"
    state.last_advisory_at = 9999999999.0
    advisory_state.save_state(state)

    calls = {"implicit": 0, "packet": 0}

    def _fake_implicit(_state, _tool_name, _success, _trace_id):
        calls["implicit"] += 1

    def _fake_packet_outcome(*_a, **_k):
        calls["packet"] += 1

    monkeypatch.setattr(implicit_feedback, "record_implicit_feedback", _fake_implicit)
    monkeypatch.setattr(packet_store, "record_packet_outcome", _fake_packet_outcome)

    alpha_engine.on_post_tool(
        "s-alpha-2",
        "Edit",
        success=True,
        tool_input={"file_path": "src/app.py"},
        trace_id="trace-alpha-post",
    )

    refreshed = advisory_state.load_state("s-alpha-2")
    assert refreshed.recent_tools
    assert refreshed.recent_tools[-1]["tool_name"] == "Edit"
    assert refreshed.recent_tools[-1]["trace_id"] == "trace-alpha-post"
    assert calls["implicit"] == 1
    assert calls["packet"] == 1


def test_log_alpha_can_mirror_to_engine_compat_log(monkeypatch, tmp_path):
    alpha_log = tmp_path / "advisory_engine_alpha.jsonl"
    compat_log = tmp_path / "advisory_engine.jsonl"
    monkeypatch.setattr(alpha_engine, "ALPHA_LOG", alpha_log)
    monkeypatch.setattr(alpha_engine, "ENGINE_COMPAT_LOG", compat_log)
    monkeypatch.setattr(alpha_engine, "ALPHA_COMPAT_ENGINE_LOG_ENABLED", True)

    alpha_engine._log_alpha(
        "emitted",
        session_id="s1",
        tool_name="Read",
        trace_id="t1",
        emitted=True,
        elapsed_ms=12.5,
    )

    assert alpha_log.exists()
    assert compat_log.exists()
