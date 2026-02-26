from __future__ import annotations

import json
from pathlib import Path

import lib.observatory.readers as readers


def test_read_eidos_includes_curriculum_metrics(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(readers, "_SD", tmp_path)
    (tmp_path / "eidos_active_episodes.json").write_text("{}", encoding="utf-8")
    (tmp_path / "eidos_active_steps.json").write_text("{}", encoding="utf-8")
    (tmp_path / "eidos_curriculum_latest.json").write_text(
        json.dumps(
            {
                "generated_at": 123,
                "stats": {
                    "rows_scanned": 50,
                    "cards_generated": 8,
                    "severity": {"high": 3, "medium": 4, "low": 1},
                    "gaps": {"low_unified_score": 5},
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "eidos_curriculum_history.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"ts": 1, "high": 6}),
                json.dumps({"ts": 2, "high": 5}),
                json.dumps({"ts": 3, "high": 3}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    out = readers.read_eidos()
    assert out["curriculum_rows_scanned"] == 50
    assert out["curriculum_cards_generated"] == 8
    assert out["curriculum_high"] == 3
    assert out["curriculum_gaps"]["low_unified_score"] == 5
    assert out["curriculum_history_points"] == 3
    assert out["curriculum_high_delta"] == -3

