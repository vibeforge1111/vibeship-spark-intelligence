from __future__ import annotations

import json
import time
from types import SimpleNamespace

import lib.advisory_engine_alpha as alpha_engine
import lib.advisory_gate as advisory_gate
import lib.advisory_packet_store as packet_store
import lib.runtime_session_state as runtime_session_state


def _patch_state_and_store(monkeypatch, tmp_path):
    state_dir = tmp_path / "state"
    monkeypatch.setattr(runtime_session_state, "STATE_DIR", state_dir)

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

    state = runtime_session_state.load_state("s-alpha-2")
    state.shown_advice_ids = {"aid-1": 1.0}
    state.last_advisory_packet_id = "pkt-test"
    state.last_advisory_tool = "Edit"
    state.last_advisory_at = 9999999999.0
    runtime_session_state.save_state(state)

    calls = {"implicit": 0, "packet": 0}

    def _fake_implicit(_state, _tool_name, _success, _trace_id):
        calls["implicit"] += 1

    def _fake_packet_outcome(*_a, **_k):
        calls["packet"] += 1

    monkeypatch.setattr(alpha_engine, "record_implicit_feedback", _fake_implicit)
    monkeypatch.setattr(packet_store, "record_packet_outcome", _fake_packet_outcome)

    alpha_engine.on_post_tool(
        "s-alpha-2",
        "Edit",
        success=True,
        tool_input={"file_path": "src/app.py"},
        trace_id="trace-alpha-post",
    )

    refreshed = runtime_session_state.load_state("s-alpha-2")
    assert refreshed.recent_tools
    assert refreshed.recent_tools[-1]["tool_name"] == "Edit"
    assert refreshed.recent_tools[-1]["trace_id"] == "trace-alpha-post"
    assert calls["implicit"] == 1
    assert calls["packet"] == 1


def test_log_alpha_writes_alpha_log_only(monkeypatch, tmp_path):
    alpha_log = tmp_path / "advisory_engine_alpha.jsonl"
    monkeypatch.setattr(alpha_engine, "ALPHA_LOG", alpha_log)

    alpha_engine._log_alpha(
        "emitted",
        session_id="s1",
        tool_name="Read",
        trace_id="t1",
        emitted=True,
        elapsed_ms=12.5,
    )

    assert alpha_log.exists()
    assert not (tmp_path / "advisory_engine.jsonl").exists()


def _patch_pre_tool_runtime(monkeypatch):
    import lib.advisor as advisor
    import lib.advisory_synthesizer as synthesizer
    import lib.emitter as emitter
    import lib.meta_ralph as meta_ralph

    advice = SimpleNamespace(
        advice_id="aid-1",
        text="Repeat caution text",
        source="workflow",
        confidence=0.9,
        context_match=0.9,
        insight_key="insight:repeat",
        category="context",
        advisory_readiness=0.8,
        advisory_quality={},
    )
    monkeypatch.setattr(
        advisor,
        "advise_on_tool",
        lambda *_a, **_k: [advice],
    )
    monkeypatch.setattr(
        advisor,
        "record_recent_delivery",
        lambda **_k: None,
    )
    monkeypatch.setattr(
        advisory_gate,
        "evaluate",
        lambda advice_items, state, tool_name, tool_input, recent_global_emissions=None: advisory_gate.GateResult(
            decisions=[
                advisory_gate.GateDecision(
                    advice_id="aid-1",
                    authority=advisory_gate.AuthorityLevel.NOTE,
                    emit=True,
                    reason="ok",
                    adjusted_score=0.9,
                    original_score=0.9,
                )
            ],
            emitted=[
                advisory_gate.GateDecision(
                    advice_id="aid-1",
                    authority=advisory_gate.AuthorityLevel.NOTE,
                    emit=True,
                    reason="ok",
                    adjusted_score=0.9,
                    original_score=0.9,
                )
            ],
            suppressed=[],
            phase="implementation",
            total_retrieved=len(advice_items),
        ),
    )
    monkeypatch.setattr(advisory_gate, "get_tool_cooldown_s", lambda: 10)
    monkeypatch.setattr(synthesizer, "synthesize", lambda *_a, **_k: "Repeat caution text")

    emitted_calls = {"count": 0}

    def _emit(*_a, **_k):
        emitted_calls["count"] += 1
        return True

    monkeypatch.setattr(emitter, "emit_advisory", _emit)
    monkeypatch.setattr(meta_ralph, "get_meta_ralph", lambda: SimpleNamespace(track_retrieval=lambda *_a, **_k: None))
    return emitted_calls


def test_on_pre_tool_blocks_global_text_repeat(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)
    emitted_calls = _patch_pre_tool_runtime(monkeypatch)
    dedupe_file = tmp_path / "advisory_global_dedupe.jsonl"
    monkeypatch.setattr(alpha_engine, "ADVISORY_GLOBAL_DEDUPE_FILE", dedupe_file)
    monkeypatch.setattr(alpha_engine, "ALPHA_GLOBAL_DEDUPE_COOLDOWN_S", 600.0)
    text_sig = alpha_engine._hash_text("Repeat caution text")
    dedupe_file.write_text(
        json.dumps(
            {
                "ts": time.time(),
                "advice_id": "older-advice-id",
                "text_sig": text_sig,
                "text": "Repeat caution text",
                "trace_id": "older-trace",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    out = alpha_engine.on_pre_tool(
        "s-alpha-global-dedupe",
        "Edit",
        {"file_path": "src/app.py"},
        trace_id="trace-global-dedupe",
    )

    assert out is None
    assert emitted_calls["count"] == 0
    rows = [json.loads(line) for line in alpha_engine.ALPHA_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(str(r.get("event") or "") == "global_dedupe_suppressed" for r in rows)


def test_on_pre_tool_bench_session_bypasses_global_dedupe(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)
    emitted_calls = _patch_pre_tool_runtime(monkeypatch)
    dedupe_file = tmp_path / "advisory_global_dedupe.jsonl"
    monkeypatch.setattr(alpha_engine, "ADVISORY_GLOBAL_DEDUPE_FILE", dedupe_file)
    monkeypatch.setattr(alpha_engine, "ALPHA_GLOBAL_DEDUPE_COOLDOWN_S", 600.0)
    dedupe_file.write_text(
        json.dumps(
            {
                "ts": time.time(),
                "advice_id": "older-advice-id",
                "text_sig": alpha_engine._hash_text("Repeat caution text"),
                "text": "Repeat caution text",
                "trace_id": "older-trace",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    out = alpha_engine.on_pre_tool(
        "advisory-bench-smoke",
        "Edit",
        {"file_path": "src/app.py"},
        trace_id="bench:trace-1",
    )

    assert out == "Repeat caution text"
    assert emitted_calls["count"] == 1


def test_on_pre_tool_arena_trace_bypasses_global_dedupe(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)
    emitted_calls = _patch_pre_tool_runtime(monkeypatch)
    dedupe_file = tmp_path / "advisory_global_dedupe.jsonl"
    monkeypatch.setattr(alpha_engine, "ADVISORY_GLOBAL_DEDUPE_FILE", dedupe_file)
    monkeypatch.setattr(alpha_engine, "ALPHA_GLOBAL_DEDUPE_COOLDOWN_S", 600.0)
    dedupe_file.write_text(
        json.dumps(
            {
                "ts": time.time(),
                "advice_id": "older-advice-id",
                "text_sig": alpha_engine._hash_text("Repeat caution text"),
                "text": "Repeat caution text",
                "trace_id": "older-trace",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    out = alpha_engine.on_pre_tool(
        "s-alpha-replay",
        "Edit",
        {"file_path": "src/app.py"},
        trace_id="arena:replay-1",
    )

    assert out == "Repeat caution text"
    assert emitted_calls["count"] == 1


def test_on_pre_tool_blocks_normalized_text_repeat(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)
    emitted_calls = _patch_pre_tool_runtime(monkeypatch)
    dedupe_file = tmp_path / "advisory_global_dedupe.jsonl"
    monkeypatch.setattr(alpha_engine, "ADVISORY_GLOBAL_DEDUPE_FILE", dedupe_file)
    monkeypatch.setattr(alpha_engine, "ALPHA_GLOBAL_DEDUPE_COOLDOWN_S", 600.0)
    dedupe_file.write_text(
        json.dumps(
            {
                "ts": time.time(),
                "advice_id": "older-advice-id",
                "text_sig": alpha_engine._advice_text_sig("[Caution] Repeat caution text!!!"),
                "text": "[Caution] Repeat caution text!!!",
                "trace_id": "older-trace",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    out = alpha_engine.on_pre_tool(
        "s-alpha-global-dedupe-normalized",
        "Edit",
        {"file_path": "src/app.py"},
        trace_id="trace-global-dedupe-normalized",
    )

    assert out is None
    assert emitted_calls["count"] == 0
