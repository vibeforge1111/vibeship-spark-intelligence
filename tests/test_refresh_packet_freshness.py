from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.refresh_packet_freshness as refresh


def test_plan_refresh_selects_recent_stale_packets(tmp_path: Path):
    now = time.time()
    index = tmp_path / "index.json"
    packet_dir = tmp_path / "packets"
    packet_dir.mkdir(parents=True)

    payload = {
        "packet_meta": {
            "p_recent": {
                "updated_ts": now - 900,
                "fresh_until_ts": now - 100,
                "invalidated": False,
            },
            "p_old": {
                "updated_ts": now - 30000,
                "fresh_until_ts": now - 29000,
                "invalidated": False,
            },
        }
    }
    index.write_text(json.dumps(payload), encoding="utf-8")

    plan = refresh.plan_refresh(index_path=index, packet_dir=packet_dir, ttl_s=1800, max_age_s=3600)

    assert plan["ok"] is True
    assert len(plan["candidates"]) == 1
    assert plan["candidates"][0]["packet_id"] == "p_recent"


def test_apply_refresh_updates_index_and_packet_file(tmp_path: Path):
    now = time.time()
    index = tmp_path / "index.json"
    packet_dir = tmp_path / "packets"
    packet_dir.mkdir(parents=True)

    updated_ts = now - 600
    payload = {
        "packet_meta": {
            "p1": {
                "updated_ts": updated_ts,
                "fresh_until_ts": now - 10,
                "invalidated": False,
            }
        }
    }
    index.write_text(json.dumps(payload), encoding="utf-8")
    (packet_dir / "p1.json").write_text(
        json.dumps({"packet_id": "p1", "updated_ts": updated_ts, "fresh_until_ts": now - 10}),
        encoding="utf-8",
    )

    plan = refresh.plan_refresh(index_path=index, packet_dir=packet_dir, ttl_s=1800, max_age_s=7200)
    result = refresh.apply_refresh(plan)

    assert result["applied"] is True
    assert result["updated_meta_rows"] == 1
    assert result["updated_packet_files"] == 1

    new_index = json.loads(index.read_text(encoding="utf-8"))
    fresh_until = float(new_index["packet_meta"]["p1"]["fresh_until_ts"])
    assert fresh_until >= updated_ts + 1800

    packet = json.loads((packet_dir / "p1.json").read_text(encoding="utf-8"))
    assert float(packet["fresh_until_ts"]) == fresh_until
    assert float(packet["ttl_s"]) >= 1800
