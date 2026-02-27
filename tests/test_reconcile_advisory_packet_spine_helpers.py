from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import lib.packet_spine as packet_spine

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.reconcile_advisory_packet_spine as reconcile


def _write_index(index_path: Path) -> None:
    payload = {
        "by_exact": {
            "proj|ctx|edit|auth": "pkt_a",
            "proj|ctx2|read|knowledge": "pkt_b",
        },
        "packet_meta": {
            "pkt_a": {
                "project_key": "proj",
                "session_context_key": "ctx",
                "tool_name": "Edit",
                "intent_family": "auth_security",
                "task_plane": "build_delivery",
                "fresh_until_ts": 500.0,
                "updated_ts": 200.0,
                "effectiveness_score": 0.7,
                "read_count": 2,
                "usage_count": 2,
                "emit_count": 1,
                "deliver_count": 1,
                "source_summary": ["cognitive"],
                "category_summary": ["security"],
                "invalidated": False,
            },
            "pkt_b": {
                "project_key": "proj",
                "session_context_key": "ctx2",
                "tool_name": "Read",
                "intent_family": "knowledge_alignment",
                "task_plane": "build_delivery",
                "fresh_until_ts": 450.0,
                "updated_ts": 180.0,
                "effectiveness_score": 0.6,
                "read_count": 0,
                "usage_count": 0,
                "emit_count": 0,
                "deliver_count": 0,
                "source_summary": ["baseline"],
                "category_summary": ["docs"],
                "invalidated": False,
            },
        },
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_reconcile_plan_counts_packet_meta_fallback(tmp_path: Path):
    index_path = tmp_path / "advice_packets" / "index.json"
    packet_dir = tmp_path / "advice_packets" / "packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    _write_index(index_path)
    (packet_dir / "pkt_a.json").write_text(
        json.dumps(
            {
                "packet_id": "pkt_a",
                "project_key": "proj",
                "session_context_key": "ctx",
                "tool_name": "Edit",
                "intent_family": "auth_security",
                "task_plane": "build_delivery",
                "fresh_until_ts": 500.0,
                "updated_ts": 200.0,
                "effectiveness_score": 0.7,
                "read_count": 2,
                "usage_count": 2,
                "emit_count": 1,
                "deliver_count": 1,
                "source_summary": ["cognitive"],
                "category_summary": ["security"],
                "invalidated": False,
            }
        ),
        encoding="utf-8",
    )

    plan = reconcile.build_reconcile_plan(index_path=index_path, packet_dir=packet_dir)
    summary = plan["summary"]
    assert summary["index_packet_meta_rows"] == 2
    assert summary["packet_file_rows"] == 1
    assert summary["packet_meta_rows"] == 1
    assert summary["packet_missing_files"] == 1
    assert summary["planned_alias_upserts"] == 2


def test_apply_reconcile_upserts_packets_and_aliases(monkeypatch, tmp_path: Path):
    index_path = tmp_path / "advice_packets" / "index.json"
    packet_dir = tmp_path / "advice_packets" / "packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    _write_index(index_path)
    monkeypatch.setattr(packet_spine, "SPINE_DB", tmp_path / "advice_packets" / "packet_spine.db")

    plan = reconcile.build_reconcile_plan(index_path=index_path, packet_dir=packet_dir)
    out = reconcile.apply_reconcile(plan)
    assert out["applied"] is True
    assert out["packet_upserts"] == 2
    assert out["packet_errors"] == 0
    assert out["alias_upserts"] == 2
    assert out["alias_errors"] == 0

    with sqlite3.connect(str(packet_spine.SPINE_DB)) as conn:
        meta_count = int(conn.execute("SELECT COUNT(*) FROM packet_meta").fetchone()[0])
        alias_count = int(conn.execute("SELECT COUNT(*) FROM exact_alias").fetchone()[0])
    assert meta_count == 2
    assert alias_count == 2
