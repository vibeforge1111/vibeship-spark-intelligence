from __future__ import annotations

import json
from types import SimpleNamespace

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


def test_engine_config_exposes_packet_fallback_flag(monkeypatch):
    monkeypatch.setattr(advisory_engine, "PACKET_FALLBACK_EMIT_ENABLED", False)
    advisory_engine.apply_engine_config({"packet_fallback_emit_enabled": True})
    cfg = advisory_engine.get_engine_config()
    assert cfg["packet_fallback_emit_enabled"] is True


def test_engine_config_exposes_fallback_rate_guard_fields(monkeypatch):
    monkeypatch.setattr(advisory_engine, "FALLBACK_RATE_GUARD_ENABLED", True)
    monkeypatch.setattr(advisory_engine, "FALLBACK_RATE_GUARD_MAX_RATIO", 0.55)
    monkeypatch.setattr(advisory_engine, "FALLBACK_RATE_GUARD_WINDOW", 80)
    advisory_engine.apply_engine_config(
        {
            "fallback_rate_guard_enabled": False,
            "fallback_rate_max_ratio": 0.35,
            "fallback_rate_window": 120,
        }
    )
    cfg = advisory_engine.get_engine_config()
    assert cfg["fallback_rate_guard_enabled"] is False
    assert cfg["fallback_rate_max_ratio"] == 0.35
    assert cfg["fallback_rate_window"] == 120


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


def test_fallback_rate_guard_blocks_when_recent_ratio_exceeded(monkeypatch, tmp_path):
    log_path = tmp_path / "advisory_engine.jsonl"
    rows = []
    rows.extend({"event": "fallback_emit"} for _ in range(9))
    rows.extend({"event": "emitted"} for _ in range(3))
    log_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(advisory_engine, "ENGINE_LOG", log_path)
    monkeypatch.setattr(advisory_engine, "FALLBACK_RATE_GUARD_ENABLED", True)
    monkeypatch.setattr(advisory_engine, "FALLBACK_RATE_GUARD_MAX_RATIO", 0.5)
    monkeypatch.setattr(advisory_engine, "FALLBACK_RATE_GUARD_WINDOW", 20)

    out = advisory_engine._fallback_guard_allows()
    assert out["allowed"] is False
    assert out["reason"] == "ratio_exceeded"
    assert round(float(out["ratio"] or 0.0), 3) == 0.75


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
