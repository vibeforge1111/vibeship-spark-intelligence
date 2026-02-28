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
    monkeypatch.setattr(alpha_engine, "ADVISORY_DECISION_LEDGER_FILE", tmp_path / "advisory_decision_ledger.jsonl")
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
    ledger_log = tmp_path / "advisory_decision_ledger.jsonl"
    monkeypatch.setattr(alpha_engine, "ALPHA_LOG", alpha_log)
    monkeypatch.setattr(alpha_engine, "ADVISORY_DECISION_LEDGER_FILE", ledger_log)

    alpha_engine._log_alpha(
        "emitted",
        session_id="s1",
        tool_name="Read",
        trace_id="t1",
        emitted=True,
        elapsed_ms=12.5,
    )

    assert alpha_log.exists()
    assert ledger_log.exists()
    rows = [json.loads(line) for line in ledger_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[-1]["outcome"] == "emitted"
    assert not (tmp_path / "advisory_engine.jsonl").exists()


def test_log_alpha_skips_non_decision_events_in_ledger(monkeypatch, tmp_path):
    alpha_log = tmp_path / "advisory_engine_alpha.jsonl"
    ledger_log = tmp_path / "advisory_decision_ledger.jsonl"
    monkeypatch.setattr(alpha_engine, "ALPHA_LOG", alpha_log)
    monkeypatch.setattr(alpha_engine, "ADVISORY_DECISION_LEDGER_FILE", ledger_log)

    alpha_engine._log_alpha(
        "post_tool_recorded",
        session_id="s2",
        tool_name="Edit",
        trace_id="t2",
        emitted=False,
        elapsed_ms=5.0,
    )

    assert alpha_log.exists()
    if ledger_log.exists():
        rows = [json.loads(line) for line in ledger_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows == []


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
    monkeypatch.setattr(
        alpha_engine,
        "_record_feedback_request",
        lambda **_k: {"enabled": False, "requested": False, "run_id": "", "min_interval_s": 600},
    )
    return emitted_calls


def test_record_feedback_request_uses_trace_bound_context(monkeypatch):
    import lib.advice_feedback as advice_feedback

    monkeypatch.setattr(
        alpha_engine,
        "_feedback_prompt_settings",
        lambda: {"enabled": True, "min_interval_s": 321},
    )
    calls = []

    def _fake_record_advice_request(**kwargs):
        calls.append(dict(kwargs))
        return True

    monkeypatch.setattr(advice_feedback, "record_advice_request", _fake_record_advice_request)

    out = alpha_engine._record_feedback_request(
        session_id="session-1",
        tool_name="Edit",
        trace_id="trace-1",
        advice_ids=["adv-1", "adv-2"],
        advice_texts=["first advice", "second advice"],
        sources=["bank", "eidos"],
        route="alpha",
    )

    assert out["enabled"] is True
    assert out["requested"] is True
    assert out["min_interval_s"] == 321
    assert isinstance(out["run_id"], str) and len(out["run_id"]) == 20
    assert len(calls) == 1
    call = calls[0]
    assert call["session_id"] == "session-1"
    assert call["tool"] == "Edit"
    assert call["trace_id"] == "trace-1"
    assert call["route"] == "alpha"
    assert call["min_interval_s"] == 321
    assert call["run_id"] == out["run_id"]


def test_on_pre_tool_logs_feedback_request_metadata(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)
    _patch_pre_tool_runtime(monkeypatch)
    monkeypatch.setattr(
        alpha_engine,
        "_record_feedback_request",
        lambda **_k: {"enabled": True, "requested": True, "run_id": "run-abc", "min_interval_s": 600},
    )
    monkeypatch.setattr(alpha_engine, "ADVISORY_GLOBAL_DEDUPE_FILE", tmp_path / "advisory_global_dedupe.jsonl")

    out = alpha_engine.on_pre_tool(
        "s-alpha-feedback-log",
        "Edit",
        {"file_path": "src/app.py"},
        trace_id="trace-feedback-log",
    )

    assert out == "Repeat caution text"
    rows = [
        json.loads(line)
        for line in alpha_engine.ALPHA_LOG.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    emitted_rows = [row for row in rows if str(row.get("event") or "") == "emitted"]
    assert emitted_rows
    extra = emitted_rows[-1].get("extra") if isinstance(emitted_rows[-1].get("extra"), dict) else {}
    assert extra.get("feedback_request_enabled") is True
    assert extra.get("feedback_request_requested") is True
    assert extra.get("feedback_request_run_id") == "run-abc"


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


def test_question_like_helpers_detect_and_sanitize():
    advice = SimpleNamespace(text="Verify contracts before changing payload shapes.")
    assert alpha_engine._is_question_like_advice("What should we do now?") is True
    assert alpha_engine._is_question_like_advice("Can you check this first") is True
    assert alpha_engine._is_question_like_advice(advice.text) is False

    text, mode = alpha_engine._sanitize_emission_text(
        text="What should we do now?",
        emitted_items=[advice],
        tool_name="Edit",
    )
    assert mode == "fallback_item_text"
    assert text == advice.text


def test_on_pre_tool_rewrites_question_like_synth(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)
    monkeypatch.setattr(alpha_engine, "ADVISORY_GLOBAL_DEDUPE_FILE", tmp_path / "advisory_global_dedupe.jsonl")
    import lib.advisor as advisor
    import lib.advisory_synthesizer as synthesizer
    import lib.emitter as emitter
    import lib.meta_ralph as meta_ralph

    advice = SimpleNamespace(
        advice_id="aid-q-1",
        text="Verify contracts before changing payload shapes.",
        source="workflow",
        confidence=0.9,
        context_match=0.9,
        insight_key="insight:verify-contracts",
        category="context",
        advisory_readiness=0.8,
        advisory_quality={},
    )
    monkeypatch.setattr(advisor, "advise_on_tool", lambda *_a, **_k: [advice])
    monkeypatch.setattr(advisor, "record_recent_delivery", lambda **_k: None)
    monkeypatch.setattr(
        advisory_gate,
        "evaluate",
        lambda advice_items, state, tool_name, tool_input, recent_global_emissions=None: advisory_gate.GateResult(
            decisions=[
                advisory_gate.GateDecision(
                    advice_id="aid-q-1",
                    authority=advisory_gate.AuthorityLevel.NOTE,
                    emit=True,
                    reason="ok",
                    adjusted_score=0.9,
                    original_score=0.9,
                )
            ],
            emitted=[
                advisory_gate.GateDecision(
                    advice_id="aid-q-1",
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
    monkeypatch.setattr(synthesizer, "synthesize", lambda *_a, **_k: "What should we do now?")
    monkeypatch.setattr(meta_ralph, "get_meta_ralph", lambda: SimpleNamespace(track_retrieval=lambda *_a, **_k: None))

    captured = {"text": ""}

    def _emit(gate_result, synth_text, emitted_items, **_kwargs):
        _ = gate_result
        _ = emitted_items
        captured["text"] = str(synth_text or "")
        return True

    monkeypatch.setattr(emitter, "emit_advisory", _emit)

    out = alpha_engine.on_pre_tool(
        "s-alpha-question-like",
        "Edit",
        {"file_path": "src/app.py"},
        trace_id="trace-alpha-question-like",
    )
    assert "?" not in out
    assert out == "Verify contracts before changing payload shapes."
    assert captured["text"] == out


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
