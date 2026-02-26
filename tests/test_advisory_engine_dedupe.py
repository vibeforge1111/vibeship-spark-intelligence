from __future__ import annotations

import time

from lib import advisory_engine
from lib.advisory_state import SessionState


def test_text_fingerprint_normalizes_whitespace_and_case():
    a = advisory_engine._text_fingerprint("Run focused TESTS now")
    b = advisory_engine._text_fingerprint("  run focused tests   now  ")
    assert a
    assert a == b


def test_duplicate_repeat_state_within_cooldown(monkeypatch):
    monkeypatch.setattr(advisory_engine, "ADVISORY_TEXT_REPEAT_COOLDOWN_S", 60.0)
    state = SessionState(session_id="s1")
    state.last_advisory_text_fingerprint = advisory_engine._text_fingerprint(
        "Run focused tests now"
    )
    state.last_advisory_at = time.time() - 10

    meta = advisory_engine._duplicate_repeat_state(state, "run focused tests now")
    assert meta["repeat"] is True
    assert meta["fingerprint"] == state.last_advisory_text_fingerprint


def test_duplicate_repeat_state_allows_after_cooldown(monkeypatch):
    monkeypatch.setattr(advisory_engine, "ADVISORY_TEXT_REPEAT_COOLDOWN_S", 15.0)
    state = SessionState(session_id="s2")
    state.last_advisory_text_fingerprint = advisory_engine._text_fingerprint(
        "Run focused tests now"
    )
    state.last_advisory_at = time.time() - 30

    meta = advisory_engine._duplicate_repeat_state(state, "run focused tests now")
    assert meta["repeat"] is False


def test_global_recently_emitted_ignores_tool(monkeypatch, tmp_path):
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_LOG", tmp_path / "global.jsonl")
    now = time.time()
    advisory_engine._append_jsonl_capped(
        advisory_engine.GLOBAL_DEDUPE_LOG,
        {"ts": now - 3, "tool": "Edit", "advice_id": "a1"},
        max_lines=50,
    )
    hit = advisory_engine._global_recently_emitted(
        tool_name="Read",
        advice_id="a1",
        now_ts=now,
        cooldown_s=60.0,
    )
    assert hit is not None
    assert float(hit["age_s"]) >= 0.0


def test_global_recently_emitted_text_sig(monkeypatch, tmp_path):
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_LOG", tmp_path / "global.jsonl")
    now = time.time()
    advisory_engine._append_jsonl_capped(
        advisory_engine.GLOBAL_DEDUPE_LOG,
        {"ts": now - 2, "tool": "Read", "advice_id": "x", "text_sig": "sig1"},
        max_lines=50,
    )
    hit = advisory_engine._global_recently_emitted_text_sig(
        text_sig="sig1",
        now_ts=now,
        cooldown_s=60.0,
    )
    assert hit is not None
    assert float(hit["age_s"]) >= 0.0


def test_on_pre_tool_global_dedupe_filters_emitted(monkeypatch, tmp_path):
    monkeypatch.setattr(advisory_engine, "ENGINE_ENABLED", True)
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_ENABLED", True)
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_COOLDOWN_S", 600.0)
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_LOG", tmp_path / "global.jsonl")
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_LOG_MAX", 200)
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_TEXT_ENABLED", True)


    # Avoid writing state into the real ~/.spark folder.
    import lib.advisory_state as advisory_state

    monkeypatch.setattr(advisory_state, "STATE_DIR", tmp_path / "state")

    # Avoid writing packets into the real ~/.spark folder.
    import lib.advisory_packet_store as packet_store

    monkeypatch.setattr(packet_store, "PACKET_DIR", tmp_path / "packets")
    monkeypatch.setattr(packet_store, "INDEX_FILE", (tmp_path / "packets" / "index.json"))
    monkeypatch.setattr(
        packet_store, "PREFETCH_QUEUE_FILE", (tmp_path / "packets" / "prefetch_queue.jsonl")
    )

    # Avoid writing advisor logs into the real ~/.spark folder.
    import lib.advisor as advisor_mod

    monkeypatch.setattr(advisor_mod, "ADVISOR_DIR", tmp_path / "advisor")
    monkeypatch.setattr(advisor_mod, "RECENT_ADVICE_LOG", (tmp_path / "advisor" / "recent_advice.jsonl"))

    # Force live path (no packets).
    monkeypatch.setattr(packet_store, "lookup_exact", lambda **kwargs: None)
    monkeypatch.setattr(packet_store, "lookup_relaxed", lambda **kwargs: None)

    # Deterministic advice retrieval: two items, one of which should be globally suppressed.
    from lib.advisor import Advice

    def fake_advise_on_tool(*args, **kwargs):
        return [
            Advice(
                advice_id="a1",
                insight_key="k1",
                text="Advice one",
                confidence=0.9,
                source="cognitive",
                context_match=0.9,
            ),
            Advice(
                advice_id="a2",
                insight_key="k2",
                text="Advice two",
                confidence=0.9,
                source="cognitive",
                context_match=0.9,
            ),
        ]

    monkeypatch.setattr(advisor_mod, "advise_on_tool", fake_advise_on_tool)

    # Gate: emit both, in deterministic order.
    import lib.advisory_gate as gate
    from lib.advisory_gate import GateDecision, GateResult

    def fake_evaluate(advice_items, state, tool_name, tool_input=None, recent_global_emissions=None):
        # Simulate real gate behavior: filter out globally-deduped items.
        candidates = [
            ("a1", GateDecision(advice_id="a1", authority="note", emit=True, reason="ok", adjusted_score=0.9, original_score=0.9)),
            ("a2", GateDecision(advice_id="a2", authority="note", emit=True, reason="ok", adjusted_score=0.9, original_score=0.9)),
        ]
        emitted = []
        suppressed = []
        decisions = []
        for aid, d in candidates:
            if recent_global_emissions and aid in recent_global_emissions:
                d.emit = False
                d.reason = f"global_dedupe: advice_id emitted {recent_global_emissions[aid]:.0f}s ago"
                suppressed.append(d)
            else:
                emitted.append(d)
            decisions.append(d)
        return GateResult(
            decisions=decisions,
            emitted=emitted,
            suppressed=suppressed,
            phase="implementation",
            total_retrieved=len(advice_items),
        )

    monkeypatch.setattr(gate, "evaluate", fake_evaluate)
    monkeypatch.setattr(gate, "get_tool_cooldown_s", lambda: 0.0)

    # Synthesis and emission: capture which advice_ids are emitted.
    import lib.advisory_synthesizer as synth

    monkeypatch.setattr(synth, "synthesize", lambda *args, **kwargs: "SYNTH")

    import lib.advisory_emitter as emitter

    captured = {}

    def fake_emit_advisory(gate_result, synth_text, advice_items, authority=None):
        captured["ids"] = [d.advice_id for d in (gate_result.emitted or [])]
        return True

    monkeypatch.setattr(emitter, "emit_advisory", fake_emit_advisory)

    # Seed dedupe log with a1 recently emitted, so it should be suppressed.
    advisory_engine._append_jsonl_capped(
        advisory_engine.GLOBAL_DEDUPE_LOG,
        {"ts": time.time(), "tool": "Edit", "advice_id": "a1"},
        max_lines=200,
    )

    out = advisory_engine.on_pre_tool("sess_global_dedupe", "Read", {}, trace_id="t1")
    assert out is not None
    assert captured.get("ids") == ["a2"]


def test_on_pre_tool_global_dedupe_filters_by_text_sig(monkeypatch, tmp_path):
    monkeypatch.setattr(advisory_engine, "ENGINE_ENABLED", True)
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_ENABLED", True)
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_TEXT_ENABLED", True)
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_COOLDOWN_S", 600.0)
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_LOG", tmp_path / "global.jsonl")
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_LOG_MAX", 200)


    import lib.advisory_state as advisory_state

    monkeypatch.setattr(advisory_state, "STATE_DIR", tmp_path / "state2")

    import lib.advisory_packet_store as packet_store

    monkeypatch.setattr(packet_store, "PACKET_DIR", tmp_path / "packets2")
    monkeypatch.setattr(packet_store, "INDEX_FILE", (tmp_path / "packets2" / "index.json"))
    monkeypatch.setattr(
        packet_store, "PREFETCH_QUEUE_FILE", (tmp_path / "packets2" / "prefetch_queue.jsonl")
    )

    monkeypatch.setattr(packet_store, "lookup_exact", lambda **kwargs: None)
    monkeypatch.setattr(packet_store, "lookup_relaxed", lambda **kwargs: None)

    import lib.advisor as advisor_mod
    from lib.advisor import Advice

    monkeypatch.setattr(advisor_mod, "ADVISOR_DIR", tmp_path / "advisor2")
    monkeypatch.setattr(advisor_mod, "RECENT_ADVICE_LOG", (tmp_path / "advisor2" / "recent_advice.jsonl"))

    def fake_advise_on_tool(*args, **kwargs):
        return [
            Advice(
                advice_id="b1",
                insight_key="k1",
                text="Always Read a file before Edit to verify current content",
                confidence=0.9,
                source="cognitive",
                context_match=0.9,
            ),
            Advice(
                advice_id="b2",
                insight_key="k2",
                text="Different advice",
                confidence=0.9,
                source="cognitive",
                context_match=0.9,
            ),
        ]

    monkeypatch.setattr(advisor_mod, "advise_on_tool", fake_advise_on_tool)

    import lib.advisory_gate as gate
    from lib.advisory_gate import GateDecision, GateResult

    def fake_evaluate(advice_items, state, tool_name, tool_input=None, **kwargs):
        d1 = GateDecision(
            advice_id="b1",
            authority="warning",
            emit=True,
            reason="ok",
            adjusted_score=0.9,
            original_score=0.9,
        )
        d2 = GateDecision(
            advice_id="b2",
            authority="note",
            emit=True,
            reason="ok",
            adjusted_score=0.9,
            original_score=0.9,
        )
        return GateResult(
            decisions=[d1, d2],
            emitted=[d1, d2],
            suppressed=[],
            phase="implementation",
            total_retrieved=len(advice_items),
        )

    monkeypatch.setattr(gate, "evaluate", fake_evaluate)
    monkeypatch.setattr(gate, "get_tool_cooldown_s", lambda: 0.0)

    import lib.advisory_synthesizer as synth

    monkeypatch.setattr(synth, "synthesize", lambda *args, **kwargs: "SYNTH")

    import lib.advisory_emitter as emitter

    captured = {}

    def fake_emit_advisory(gate_result, synth_text, advice_items, authority=None):
        captured["ids"] = [d.advice_id for d in (gate_result.emitted or [])]
        return True

    monkeypatch.setattr(emitter, "emit_advisory", fake_emit_advisory)

    # Seed dedupe log with the signature of b1 but a different advice_id.
    sig = advisory_engine._text_fingerprint(
        "Always Read a file before Edit to verify current content"
    )
    advisory_engine._append_jsonl_capped(
        advisory_engine.GLOBAL_DEDUPE_LOG,
        {"ts": time.time(), "tool": "Edit", "advice_id": "other", "text_sig": sig},
        max_lines=200,
    )

    out = advisory_engine.on_pre_tool("sess_global_dedupe_sig", "Read", {}, trace_id="t2")
    assert out is not None
    assert captured.get("ids") == ["b2"]


def test_classify_emission_quality_issue_detects_placeholder_noise_and_unsafe():
    assert advisory_engine._classify_emission_quality_issue("Reasoning: [reason] explaining why") == "template_placeholder"
    assert advisory_engine._classify_emission_quality_issue("<task-n failed with approach: unknow") == "template_placeholder"
    assert advisory_engine._classify_emission_quality_issue(
        "Read failed 3/9 times (67% success rate). Most common: File content (70603 tokens) exceeds maximum allowed tokens"
    ) == "operational_noise"
    assert advisory_engine._classify_emission_quality_issue(
        "Principle: skip error handling because it prevents bugs and improves security"
    ) == "unsafe_principle"


def test_apply_emission_quality_filters_enforces_repeat_cooldown_without_outcome_update():
    from lib.advisor import Advice
    from lib.advisory_gate import GateDecision

    advice = Advice(
        advice_id="r1",
        insight_key="reasoning:always_read_before_edit",
        text="Always Read before Edit to verify current content",
        confidence=0.9,
        source="cognitive",
        context_match=0.9,
    )
    decision = GateDecision(
        advice_id="r1",
        authority="note",
        emit=True,
        reason="ok",
        adjusted_score=0.9,
        original_score=0.9,
    )
    identity = advisory_engine._repeat_identity_for_item(advice, advice_id="r1")
    now = time.time()
    kept, suppressed = advisory_engine._apply_emission_quality_filters(
        [decision],
        {"r1": advice},
        now_ts=now,
        cooldown_s=600.0,
        recent_identity_ts={identity: now - 45.0},
        outcome_ts_by_insight={},
        outcome_ts_by_advice_id={},
    )
    assert kept == []
    assert suppressed
    assert suppressed[0]["reason"] == "insight_repeat_cooldown"


def test_apply_emission_quality_filters_allows_repeat_after_outcome_update():
    from lib.advisor import Advice
    from lib.advisory_gate import GateDecision

    advice = Advice(
        advice_id="r2",
        insight_key="reasoning:always_read_before_edit",
        text="Always Read before Edit to verify current content",
        confidence=0.9,
        source="cognitive",
        context_match=0.9,
    )
    decision = GateDecision(
        advice_id="r2",
        authority="note",
        emit=True,
        reason="ok",
        adjusted_score=0.9,
        original_score=0.9,
    )
    identity = advisory_engine._repeat_identity_for_item(advice, advice_id="r2")
    now = time.time()
    last_emit_ts = now - 80.0
    kept, suppressed = advisory_engine._apply_emission_quality_filters(
        [decision],
        {"r2": advice},
        now_ts=now,
        cooldown_s=600.0,
        recent_identity_ts={identity: last_emit_ts},
        outcome_ts_by_insight={"reasoning:always_read_before_edit": now - 20.0},
        outcome_ts_by_advice_id={},
    )
    assert len(kept) == 1
    assert suppressed == []
