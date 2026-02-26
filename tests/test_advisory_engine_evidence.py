from __future__ import annotations

import json
from types import SimpleNamespace

import lib.advisor as advisor_mod
import lib.implicit_outcome_tracker as implicit_tracker_mod
from lib import advisory_engine


def test_advice_rows_include_proof_refs_and_evidence_hash():
    item = SimpleNamespace(
        advice_id="aid-1",
        insight_key="reasoning:k1",
        text="Run focused tests after edit.",
        confidence=0.8,
        source="cognitive",
        context_match=0.7,
        reason="Recent failures on the same flow.",
    )

    rows = advisory_engine._advice_to_rows_with_proof([item], trace_id="trace-123")
    assert len(rows) == 1
    row = rows[0]
    assert row["proof_refs"]["trace_id"] == "trace-123"
    assert row["proof_refs"]["insight_key"] == "reasoning:k1"
    assert row["proof_refs"]["source"] == "cognitive"
    assert row["evidence_hash"]


def test_advice_rows_wrapper_works_without_trace_id():
    item = SimpleNamespace(
        advice_id="aid-2",
        insight_key="context:k2",
        text="Validate payload contract before merge.",
        confidence=0.6,
        source="advisor",
        context_match=0.5,
        reason="",
    )

    rows = advisory_engine._advice_to_rows([item])
    assert len(rows) == 1
    assert "trace_id" not in rows[0]["proof_refs"]
    assert rows[0]["proof_refs"]["advice_id"] == "aid-2"


def test_diagnostics_envelope_has_session_scope_and_provider():
    bundle = {
        "memory_absent_declared": False,
        "sources": {"cognitive": {"count": 2}, "eidos": {"count": 0}},
        "missing_sources": ["eidos"],
    }
    env = advisory_engine._diagnostics_envelope(
        session_id="session-1",
        trace_id="trace-1",
        route="packet_exact",
        session_context_key="ctx-1",
        scope="session",
        memory_bundle=bundle,
    )

    assert env["session_id"] == "session-1"
    assert env["trace_id"] == "trace-1"
    assert env["scope"] == "session"
    assert env["provider_path"] == "packet_store"
    assert env["source_counts"]["cognitive"] == 2
    assert "eidos" in env["missing_sources"]


def test_ensure_actionability_appends_command_when_missing(monkeypatch):
    monkeypatch.setattr(advisory_engine, "ACTIONABILITY_ENFORCE", True)
    meta = advisory_engine._ensure_actionability(
        "Validate auth inputs before changes.",
        "Edit",
        "build_delivery",
    )
    assert meta["added"] is True
    assert "`python -m pytest -q`" in meta["text"]


def test_ensure_actionability_keeps_existing_command(monkeypatch):
    monkeypatch.setattr(advisory_engine, "ACTIONABILITY_ENFORCE", True)
    meta = advisory_engine._ensure_actionability(
        "Run focused checks now: `python -m pytest -q`.",
        "Edit",
        "build_delivery",
    )
    assert meta["added"] is False


def test_delivery_badge_live_and_stale_states():
    now = 2000.0
    live = advisory_engine._derive_delivery_badge(
        [{"ts": 1995.0, "event": "emitted", "delivery_mode": "live"}],
        now_ts=now,
        stale_after_s=30.0,
    )
    stale = advisory_engine._derive_delivery_badge(
        [{"ts": 1500.0, "event": "emitted", "delivery_mode": "live"}],
        now_ts=now,
        stale_after_s=30.0,
    )
    assert live["state"] == "live"
    assert stale["state"] == "stale"


def test_engine_config_exposes_global_dedupe_cooldown(monkeypatch):
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_COOLDOWN_S", 600.0)
    advisory_engine.apply_engine_config({"global_dedupe_cooldown_s": 180.0})
    cfg = advisory_engine.get_engine_config()
    assert cfg["global_dedupe_cooldown_s"] == 180.0


def test_engine_config_exposes_global_dedupe_scope(monkeypatch):
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_SCOPE", "global")
    advisory_engine.apply_engine_config({"global_dedupe_scope": "contextual"})
    cfg = advisory_engine.get_engine_config()
    assert cfg["global_dedupe_scope"] == "contextual"


def test_engine_config_exposes_global_dedupe_scope_tree(monkeypatch):
    monkeypatch.setattr(advisory_engine, "GLOBAL_DEDUPE_SCOPE", "global")
    advisory_engine.apply_engine_config({"global_dedupe_scope": "tree"})
    cfg = advisory_engine.get_engine_config()
    assert cfg["global_dedupe_scope"] == "tree"


def test_record_rejection_flushes_global_dedupe_suppressed(monkeypatch, tmp_path):
    telemetry_file = tmp_path / "advisory_rejection_telemetry.json"
    monkeypatch.setattr(advisory_engine, "REJECTION_TELEMETRY_FILE", telemetry_file)
    monkeypatch.setattr(advisory_engine, "_rejection_counts", {})
    monkeypatch.setattr(advisory_engine, "_rejection_flush_counter", 0)
    monkeypatch.setattr(advisory_engine, "_rejection_flush_interval", 50)

    advisory_engine._record_rejection("global_dedupe_suppressed")

    assert telemetry_file.exists()
    payload = json.loads(telemetry_file.read_text(encoding="utf-8"))
    assert int(payload.get("global_dedupe_suppressed", 0)) >= 1


def test_load_engine_config_reads_advisory_engine_section(tmp_path):
    cfg_path = tmp_path / "tuneables.json"
    cfg_path.write_text(
        json.dumps(
            {
                "advisory_engine": {
                    "include_mind": True,
                    "max_ms": 3200,
                }
            }
        ),
        encoding="utf-8",
    )

    cfg = advisory_engine._load_engine_config(path=cfg_path)
    assert cfg["include_mind"] is True
    assert cfg["max_ms"] == 3200


def test_advice_source_counts_aggregates_sources():
    items = [
        SimpleNamespace(source="semantic"),
        SimpleNamespace(source="semantic-agentic"),
        SimpleNamespace(source="cognitive"),
        SimpleNamespace(source=""),
    ]
    counts = advisory_engine._advice_source_counts(items)
    assert counts["semantic"] == 1
    assert counts["semantic-agentic"] == 1
    assert counts["cognitive"] == 1


def test_record_implicit_feedback_prefers_retrieval_trace(monkeypatch):
    class _DummyAdvisor:
        def __init__(self):
            self.calls = []

        def _get_recent_advice_entry(self, *_args, **_kwargs):
            return {
                "trace_id": "trace-retrieval-1",
                "advice_ids": ["aid-1"],
                "advice_texts": ["Run focused tests after edit."],
                "sources": ["cognitive"],
            }

        def report_outcome(self, advice_id, was_followed, was_helpful, notes, trace_id):
            self.calls.append(
                {
                    "advice_id": advice_id,
                    "was_followed": was_followed,
                    "was_helpful": was_helpful,
                    "trace_id": trace_id,
                    "notes": notes,
                }
            )

    class _DummyTracker:
        def __init__(self):
            self.advice_calls = []
            self.outcome_calls = []

        def record_advice(self, **kwargs):
            self.advice_calls.append(kwargs)

        def record_outcome(self, **kwargs):
            self.outcome_calls.append(kwargs)

    advisor = _DummyAdvisor()
    tracker = _DummyTracker()
    monkeypatch.setattr(advisor_mod, "get_advisor", lambda: advisor)
    monkeypatch.setattr(implicit_tracker_mod, "get_implicit_tracker", lambda: tracker)

    state = SimpleNamespace(shown_advice_ids={"aid-1": 1})
    advisory_engine._record_implicit_feedback(
        state,
        tool_name="Edit",
        success=True,
        trace_id="trace-post-tool-mismatch",
    )

    assert len(advisor.calls) == 1
    assert advisor.calls[0]["trace_id"] == "trace-retrieval-1"
    assert tracker.advice_calls and tracker.advice_calls[0]["trace_id"] == "trace-retrieval-1"
    assert tracker.outcome_calls and tracker.outcome_calls[0]["trace_id"] == "trace-retrieval-1"
