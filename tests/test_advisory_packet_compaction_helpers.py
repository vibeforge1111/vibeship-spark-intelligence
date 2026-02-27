from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "advisory_packet_compaction.py"
    name = "advisory_packet_compaction_script"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_apply_plan_delete_respects_limit(monkeypatch):
    mod = _load_module()
    calls = {"invalidated": [], "saved": 0}

    class _Store:
        @staticmethod
        def _load_index():
            return {"packet_meta": {}}

        @staticmethod
        def invalidate_packet(packet_id: str, reason: str = "") -> bool:
            calls["invalidated"].append((packet_id, reason))
            return True

        @staticmethod
        def _save_index(_index):
            calls["saved"] += 1

    monkeypatch.setattr(mod, "packet_store", _Store)
    plan = {
        "candidates": [
            {"packet_id": "p1", "action": "delete", "reason": "a"},
            {"packet_id": "p2", "action": "delete", "reason": "b"},
        ]
    }
    out = mod._apply_plan(plan, apply_limit=1, apply_updates=False)
    assert out["deleted"] == 1
    assert len(calls["invalidated"]) == 1
    assert calls["saved"] == 0


def test_apply_plan_updates_write_meta(monkeypatch):
    mod = _load_module()
    calls = {"saved": 0}
    index = {"packet_meta": {"p1": {"packet_id": "p1"}}}

    class _Store:
        @staticmethod
        def _load_index():
            return index

        @staticmethod
        def invalidate_packet(_packet_id: str, reason: str = "") -> bool:
            return False

        @staticmethod
        def _save_index(_index):
            calls["saved"] += 1

    monkeypatch.setattr(mod, "packet_store", _Store)
    plan = {"candidates": [{"packet_id": "p1", "action": "update", "reason": "cold_packet_review"}]}
    out = mod._apply_plan(plan, apply_limit=3, apply_updates=True)
    assert out["updated"] == 1
    assert calls["saved"] == 1
    row = index["packet_meta"]["p1"]
    assert row["compaction_flag"] == "review"
    assert row["compaction_reason"] == "cold_packet_review"

