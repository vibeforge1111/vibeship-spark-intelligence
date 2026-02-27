from __future__ import annotations

import json
import sqlite3

import sparkd


def test_memory_health_reports_cold_start_when_stores_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(sparkd, "COGNITIVE_FILE", tmp_path / "cognitive_insights.json")
    monkeypatch.setattr(sparkd, "EIDOS_DB_FILE", tmp_path / "eidos.db")
    monkeypatch.setattr(sparkd, "MIND_SYNC_STATE_FILE", tmp_path / "mind_sync_state.json")
    monkeypatch.setattr(sparkd, "CHIP_INSIGHTS_DIR", tmp_path / "chip_insights")

    out = sparkd._memory_health_snapshot(now_ts=1234.5)

    assert out["ok"] is True
    assert out["status"] == "cold_start"
    assert out["stores"]["cognitive"]["exists"] is False
    assert out["stores"]["eidos"]["exists"] is False


def test_memory_health_reports_healthy_with_readable_stores(monkeypatch, tmp_path):
    cognitive = tmp_path / "cognitive_insights.json"
    eidos = tmp_path / "eidos.db"
    mind = tmp_path / "mind_sync_state.json"
    chips = tmp_path / "chip_insights"
    chips.mkdir(parents=True, exist_ok=True)

    cognitive.write_text(json.dumps({"insights": [{"k": 1}, {"k": 2}]}), encoding="utf-8")
    mind.write_text(json.dumps({"queue": [{"id": 1}, {"id": 2}]}), encoding="utf-8")
    (chips / "demo.jsonl").write_text('{"id":1}\n{"id":2}\n', encoding="utf-8")

    conn = sqlite3.connect(str(eidos))
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE distillations (id INTEGER PRIMARY KEY, statement TEXT)")
        cur.execute("INSERT INTO distillations(statement) VALUES ('s1')")
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(sparkd, "COGNITIVE_FILE", cognitive)
    monkeypatch.setattr(sparkd, "EIDOS_DB_FILE", eidos)
    monkeypatch.setattr(sparkd, "MIND_SYNC_STATE_FILE", mind)
    monkeypatch.setattr(sparkd, "CHIP_INSIGHTS_DIR", chips)

    out = sparkd._memory_health_snapshot(now_ts=2000.0)

    assert out["ok"] is True
    assert out["status"] == "healthy"
    assert out["stores"]["cognitive"]["insights"] == 2
    assert out["stores"]["eidos"]["distillations"] == 1
    assert out["stores"]["mind_sync_state"]["pending_queue"] == 2
    assert out["stores"]["chip_insights"]["rows"] == 2


def test_memory_health_reports_malformed_cognitive_store(monkeypatch, tmp_path):
    cognitive = tmp_path / "cognitive_insights.json"
    eidos = tmp_path / "eidos.db"

    cognitive.write_text("{not-json", encoding="utf-8")
    conn = sqlite3.connect(str(eidos))
    conn.close()

    monkeypatch.setattr(sparkd, "COGNITIVE_FILE", cognitive)
    monkeypatch.setattr(sparkd, "EIDOS_DB_FILE", eidos)
    monkeypatch.setattr(sparkd, "MIND_SYNC_STATE_FILE", tmp_path / "mind_sync_state.json")
    monkeypatch.setattr(sparkd, "CHIP_INSIGHTS_DIR", tmp_path / "chip_insights")

    out = sparkd._memory_health_snapshot(now_ts=3000.0)

    assert out["ok"] is False
    assert out["status"] == "degraded"
    codes = {row.get("code") for row in out.get("issues") or []}
    assert "memory_store_malformed" in codes

