from __future__ import annotations

import json

from lib.advisor import Advice
from lib.advisory_gate import GateDecision, GateResult
import lib.advice_feedback as advice_feedback
import lib.advisory_engine as engine
import lib.advisory_packet_store as packet_store
import lib.advisory_state as advisory_state


def _patch_state_and_store(monkeypatch, tmp_path):
    state_dir = tmp_path / "state"
    monkeypatch.setattr(advisory_state, "STATE_DIR", state_dir)

    packet_dir = tmp_path / "packets"
    monkeypatch.setattr(packet_store, "PACKET_DIR", packet_dir)
    monkeypatch.setattr(packet_store, "INDEX_FILE", packet_dir / "index.json")
    monkeypatch.setattr(packet_store, "PREFETCH_QUEUE_FILE", packet_dir / "prefetch_queue.jsonl")

    monkeypatch.setattr(advice_feedback, "REQUESTS_FILE", tmp_path / "advice_feedback_requests.jsonl")
    monkeypatch.setattr(advice_feedback, "STATE_FILE", tmp_path / "advice_feedback_state.json")

    monkeypatch.setattr(engine, "ENGINE_LOG", tmp_path / "advisory_engine.jsonl")
    monkeypatch.setattr(engine, "_project_key", lambda: "proj")
    # Make tests independent of host env vars (e.g. SPARK_ADVISORY_ACTION_FIRST=1).
    monkeypatch.setattr(engine, "ACTION_FIRST_ENABLED", False)
    monkeypatch.setattr(engine, "ACTIONABILITY_ENFORCE", True)


def _allow_all_gate(advice_items, state, tool_name, tool_input=None, **kwargs):
    emitted = []
    decisions = []
    for idx, item in enumerate(advice_items[:2]):
        aid = getattr(item, "advice_id", f"aid_{idx}")
        d = GateDecision(
            advice_id=aid,
            authority="note",
            emit=True,
            reason="test",
            adjusted_score=0.9,
            original_score=0.9,
        )
        decisions.append(d)
        emitted.append(d)
    return GateResult(
        decisions=decisions,
        emitted=emitted,
        suppressed=[],
        phase="implementation",
        total_retrieved=len(advice_items),
    )


def _suppress_all_gate(advice_items, state, tool_name, tool_input=None, **kwargs):
    decisions = []
    for idx, item in enumerate(advice_items[:1]):
        aid = getattr(item, "advice_id", f"aid_{idx}")
        decisions.append(
            GateDecision(
                advice_id=aid,
                authority="silent",
                emit=False,
                reason="test_suppressed",
                adjusted_score=0.1,
                original_score=0.9,
            )
        )
    return GateResult(
        decisions=decisions,
        emitted=[],
        suppressed=decisions,
        phase="implementation",
        total_retrieved=len(advice_items),
    )


def _allow_warning_gate(advice_items, state, tool_name, tool_input=None, **kwargs):
    decisions = []
    emitted = []
    for idx, item in enumerate(advice_items[:1]):
        aid = getattr(item, "advice_id", f"aid_{idx}")
        d = GateDecision(
            advice_id=aid,
            authority="warning",
            emit=True,
            reason="test_warning",
            adjusted_score=0.95,
            original_score=0.95,
        )
        decisions.append(d)
        emitted.append(d)
    return GateResult(
        decisions=decisions,
        emitted=emitted,
        suppressed=[],
        phase="implementation",
        total_retrieved=len(advice_items),
    )


def test_pre_tool_uses_packet_path_when_available(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)

    # Prepare a packet that should be selected.
    pkt = packet_store.build_packet(
        project_key="proj",
        session_context_key="dummy",
        tool_name="Edit",
        intent_family="emergent_other",
        task_plane="build_delivery",
        advisory_text="Use packet guidance.",
        source_mode="baseline",
        advice_items=[{"advice_id": "pkt-a1", "text": "Use packet guidance."}],
        lineage={"sources": ["baseline"], "memory_absent_declared": False},
    )
    packet_store.save_packet(pkt)

    monkeypatch.setattr("lib.advisory_gate.evaluate", _allow_all_gate)
    monkeypatch.setattr(
        "lib.advisory_memory_fusion.build_memory_bundle",
        lambda **kwargs: {
            "memory_absent_declared": False,
            "sources": {"cognitive": {"count": 1}},
        },
    )
    monkeypatch.setattr("lib.advisor.advise_on_tool", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("live should not be called")))
    monkeypatch.setattr("lib.advisory_synthesizer.synthesize", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synth should not be called")))
    monkeypatch.setattr(
        "lib.advisory_emitter.emit_advisory",
        lambda gate_result, synthesized_text, advice_items=None, **_k: True,
    )

    text = engine.on_pre_tool("s1", "Edit", {"file_path": "x.py"})
    assert text.startswith("Use packet guidance.")
    assert "`python -m pytest -q`" in text
    req_lines = advice_feedback.REQUESTS_FILE.read_text(encoding="utf-8").splitlines()
    assert req_lines
    row = json.loads(req_lines[-1])
    assert row["tool"] == "Edit"
    assert row["advice_ids"] == ["pkt-a1"]
    assert row.get("route") in {"packet_exact", "packet_relaxed"}


def test_pre_tool_falls_back_to_live_and_persists_packet(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)

    monkeypatch.setattr("lib.advisory_gate.evaluate", _allow_all_gate)
    monkeypatch.setattr(
        "lib.advisory_memory_fusion.build_memory_bundle",
        lambda **kwargs: {
            "memory_absent_declared": True,
            "sources": {"cognitive": {"count": 0}},
        },
    )
    monkeypatch.setattr(
        "lib.advisor.advise_on_tool",
        lambda *a, **k: [
            Advice(
                advice_id="live-a1",
                insight_key="k1",
                text="Live guidance.",
                confidence=0.8,
                source="advisor",
                context_match=0.8,
                reason="test",
            )
        ],
    )
    monkeypatch.setattr("lib.advisory_synthesizer.synthesize", lambda *a, **k: "Live synthesized guidance.")
    monkeypatch.setattr(
        "lib.advisory_emitter.emit_advisory",
        lambda gate_result, synthesized_text, advice_items=None, **_k: True,
    )

    text = engine.on_pre_tool("s2", "Read", {"file_path": "y.py"})
    assert text.startswith("Live synthesized guidance.")
    assert '`rg -n "TODO|FIXME" .`' in text

    status = packet_store.get_store_status()
    assert status["total_packets"] >= 1


def test_pre_tool_live_path_propagates_include_mind_policy(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)

    monkeypatch.setattr(engine, "INCLUDE_MIND_IN_MEMORY", False)
    monkeypatch.setattr("lib.advisory_gate.evaluate", _allow_all_gate)
    monkeypatch.setattr(
        "lib.advisory_memory_fusion.build_memory_bundle",
        lambda **kwargs: {
            "memory_absent_declared": False,
            "sources": {"cognitive": {"count": 1}},
        },
    )
    capture = {"include_mind": None}

    def _live_advice(*_args, **kwargs):
        capture["include_mind"] = kwargs.get("include_mind")
        return [
            Advice(
                advice_id="live-a2",
                insight_key="k2",
                text="Live guidance with policy.",
                confidence=0.8,
                source="advisor",
                context_match=0.8,
                reason="test",
            )
        ]

    monkeypatch.setattr("lib.advisor.advise_on_tool", _live_advice)
    monkeypatch.setattr("lib.advisory_synthesizer.synthesize", lambda *a, **k: "Live synthesized guidance.")
    monkeypatch.setattr(
        "lib.advisory_emitter.emit_advisory",
        lambda gate_result, synthesized_text, advice_items=None, **_k: True,
    )

    text = engine.on_pre_tool("s2b", "Read", {"file_path": "y.py"})
    assert text.startswith("Live synthesized guidance.")
    assert capture["include_mind"] is False


def test_pre_tool_live_path_uses_fallback_when_synth_empty(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)

    monkeypatch.setattr("lib.advisory_gate.evaluate", _allow_all_gate)
    monkeypatch.setattr(
        "lib.advisory_memory_fusion.build_memory_bundle",
        lambda **kwargs: {
            "memory_absent_declared": False,
            "sources": {"cognitive": {"count": 1}},
        },
    )
    monkeypatch.setattr(
        "lib.advisor.advise_on_tool",
        lambda *a, **k: [
            Advice(
                advice_id="live-empty-a1",
                insight_key="k-empty-1",
                text="Fallback from emitted advice text.",
                confidence=0.81,
                source="cognitive",
                context_match=0.82,
                reason="test",
            )
        ],
    )
    monkeypatch.setattr("lib.advisory_synthesizer.synthesize", lambda *a, **k: "")

    capture = {"synth_text": None}

    def _fake_emit(gate_result, synthesized_text, advice_items=None, **_k):
        capture["synth_text"] = synthesized_text
        return bool(str(synthesized_text or "").strip())

    monkeypatch.setattr("lib.advisory_emitter.emit_advisory", _fake_emit)

    text = engine.on_pre_tool("s2d", "Read", {"file_path": "y.py"})
    assert text is not None
    assert "Fallback from emitted advice text." in text
    assert capture["synth_text"] is not None
    assert "Fallback from emitted advice text." in str(capture["synth_text"])

    lines = engine.ENGINE_LOG.read_text(encoding="utf-8").splitlines()
    assert lines
    row = json.loads(lines[-1])
    assert row["event"] == "emitted"
    assert row.get("synth_fallback_used") is True


def test_pre_tool_resolves_missing_trace_id_for_engine_and_feedback(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)

    monkeypatch.setattr("lib.advisory_state.resolve_recent_trace_id", lambda _state, _tool: "trace-auto-1")
    monkeypatch.setattr("lib.advisory_gate.evaluate", _allow_all_gate)
    monkeypatch.setattr(
        "lib.advisory_memory_fusion.build_memory_bundle",
        lambda **kwargs: {
            "memory_absent_declared": False,
            "sources": {"cognitive": {"count": 1}},
        },
    )
    monkeypatch.setattr(
        "lib.advisor.advise_on_tool",
        lambda *a, **k: [
            Advice(
                advice_id="live-a3",
                insight_key="k3",
                text="Trace-linked live guidance.",
                confidence=0.8,
                source="advisor",
                context_match=0.8,
                reason="test",
            )
        ],
    )
    monkeypatch.setattr("lib.advisory_synthesizer.synthesize", lambda *a, **k: "Trace linked synthesis.")
    monkeypatch.setattr(
        "lib.advisory_emitter.emit_advisory",
        lambda gate_result, synthesized_text, advice_items=None, **_k: True,
    )

    text = engine.on_pre_tool("s2c", "Read", {"file_path": "z.py"})
    assert text.startswith("Trace linked synthesis.")

    eng_rows = engine.ENGINE_LOG.read_text(encoding="utf-8").splitlines()
    assert eng_rows
    eng_row = json.loads(eng_rows[-1])
    assert eng_row.get("trace_id") == "trace-auto-1"

    req_rows = advice_feedback.REQUESTS_FILE.read_text(encoding="utf-8").splitlines()
    assert req_rows
    req_row = json.loads(req_rows[-1])
    assert req_row.get("trace_id") == "trace-auto-1"


def test_on_user_prompt_creates_baseline_and_prefetch_job(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)

    engine.on_user_prompt("s3", "Harden auth and benchmark options.")

    status = packet_store.get_store_status()
    assert status["total_packets"] >= 1
    packet = None
    for fp in packet_store.PACKET_DIR.glob("pkt_*.json"):
        row = json.loads(fp.read_text(encoding="utf-8"))
        if row.get("source_mode") == "baseline_deterministic":
            packet = row
            break
    assert packet is not None
    advice_row = (packet.get("advice_items") or [{}])[0]
    assert advice_row.get("proof_refs")
    assert advice_row.get("evidence_hash")
    assert packet_store.PREFETCH_QUEUE_FILE.exists()
    lines = packet_store.PREFETCH_QUEUE_FILE.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 1
    row = json.loads(lines[-1])
    assert row["session_id"] == "s3"


def test_pre_tool_packet_no_emit_stays_gate_suppressed_without_fallback(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)

    pkt = packet_store.build_packet(
        project_key="proj",
        session_context_key="dummy",
        tool_name="Edit",
        intent_family="emergent_other",
        task_plane="build_delivery",
        advisory_text="Use packet guidance.",
        source_mode="baseline",
        advice_items=[{"advice_id": "pkt-a1", "text": "Use packet guidance."}],
        lineage={"sources": ["baseline"], "memory_absent_declared": False},
    )
    packet_store.save_packet(pkt)

    monkeypatch.setattr("lib.advisory_gate.evaluate", _suppress_all_gate)
    monkeypatch.setattr(
        "lib.advisory_memory_fusion.build_memory_bundle",
        lambda **kwargs: {
            "memory_absent_declared": False,
            "sources": {"cognitive": {"count": 1}},
        },
    )
    monkeypatch.setattr(
        "lib.advisory_emitter.emit_advisory",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("emit should not be called")),
    )

    text = engine.on_pre_tool("s4", "Edit", {"file_path": "x.py"})
    assert text is None

    lines = engine.ENGINE_LOG.read_text(encoding="utf-8").splitlines()
    assert lines
    row = json.loads(lines[-1])
    assert row["event"] == "no_emit"
    assert row.get("fallback_candidate_blocked") is None
    assert row.get("error_code") == "AE_GATE_SUPPRESSED"
    assert row.get("gate_reason") == "test_suppressed"
    assert row.get("suppressed_count") == 1


def test_pre_tool_selective_ai_uses_auto_mode_for_warning(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)

    monkeypatch.setattr(engine, "FORCE_PROGRAMMATIC_SYNTH", True)
    monkeypatch.setattr(engine, "SELECTIVE_AI_SYNTH_ENABLED", True)
    monkeypatch.setattr(engine, "SELECTIVE_AI_MIN_REMAINING_MS", 0.0)
    monkeypatch.setattr(engine, "SELECTIVE_AI_MIN_AUTHORITY", "warning")

    monkeypatch.setattr("lib.advisory_gate.evaluate", _allow_warning_gate)
    monkeypatch.setattr(
        "lib.advisory_memory_fusion.build_memory_bundle",
        lambda **kwargs: {
            "memory_absent_declared": False,
            "sources": {"cognitive": {"count": 1}},
        },
    )
    monkeypatch.setattr(
        "lib.advisor.advise_on_tool",
        lambda *a, **k: [
            Advice(
                advice_id="live-w1",
                insight_key="kw1",
                text="Warning-level guidance.",
                confidence=0.92,
                source="advisor",
                context_match=0.9,
                reason="test",
            )
        ],
    )
    capture = {"force_mode": "unset"}

    def _fake_synth(*_args, **kwargs):
        capture["force_mode"] = kwargs.get("force_mode")
        return "Selective AI path."

    monkeypatch.setattr("lib.advisory_synthesizer.synthesize", _fake_synth)
    monkeypatch.setattr("lib.advisory_emitter.emit_advisory", lambda *a, **k: True)

    text = engine.on_pre_tool("s6", "Edit", {"file_path": "x.py"})
    assert text is not None
    assert capture["force_mode"] is None

    lines = engine.ENGINE_LOG.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[-1])
    assert row.get("event") == "emitted"
    assert row.get("synth_policy") == "selective_ai_auto"


def test_pre_tool_selective_ai_keeps_programmatic_for_note(monkeypatch, tmp_path):
    _patch_state_and_store(monkeypatch, tmp_path)

    monkeypatch.setattr(engine, "FORCE_PROGRAMMATIC_SYNTH", True)
    monkeypatch.setattr(engine, "SELECTIVE_AI_SYNTH_ENABLED", True)
    monkeypatch.setattr(engine, "SELECTIVE_AI_MIN_REMAINING_MS", 0.0)
    monkeypatch.setattr(engine, "SELECTIVE_AI_MIN_AUTHORITY", "warning")

    monkeypatch.setattr("lib.advisory_gate.evaluate", _allow_all_gate)
    monkeypatch.setattr(
        "lib.advisory_memory_fusion.build_memory_bundle",
        lambda **kwargs: {
            "memory_absent_declared": False,
            "sources": {"cognitive": {"count": 1}},
        },
    )
    monkeypatch.setattr(
        "lib.advisor.advise_on_tool",
        lambda *a, **k: [
            Advice(
                advice_id="live-n1",
                insight_key="kn1",
                text="Note-level guidance.",
                confidence=0.82,
                source="advisor",
                context_match=0.82,
                reason="test",
            )
        ],
    )
    capture = {"force_mode": "unset"}

    def _fake_synth(*_args, **kwargs):
        capture["force_mode"] = kwargs.get("force_mode")
        return "Programmatic path."

    monkeypatch.setattr("lib.advisory_synthesizer.synthesize", _fake_synth)
    monkeypatch.setattr("lib.advisory_emitter.emit_advisory", lambda *a, **k: True)

    text = engine.on_pre_tool("s7", "Read", {"file_path": "y.py"})
    assert text is not None
    assert capture["force_mode"] == "programmatic"

    lines = engine.ENGINE_LOG.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[-1])
    assert row.get("event") == "emitted"
    assert row.get("synth_policy") == "programmatic_forced"
