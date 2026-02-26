from __future__ import annotations

import json
from pathlib import Path

import lib.observatory.explorer as explorer
import lib.observatory.readers as readers


def _write_roast_history(path: Path, payload: dict) -> None:
    meta_dir = path / "meta_ralph"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "roast_history.json").write_text(json.dumps(payload), encoding="utf-8")


def test_read_meta_ralph_uses_cumulative_total_roasted(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(readers, "_SD", tmp_path)
    _write_roast_history(
        tmp_path,
        {
            "total_roasted": 2500,
            "quality_passed": 600,
            "history": [
                {"result": {"verdict": "quality", "score": {"total": 8}}},
                {"result": {"verdict": "needs_work", "score": {"total": 4}}},
                {"result": {"verdict": "primitive_rejected", "score": {"total": 1}}},
            ],
        },
    )

    out = readers.read_meta_ralph(max_recent=2)

    assert out["total_roasted"] == 2500
    assert out["quality_passed"] == 600
    assert out["pass_rate"] == 24.0
    assert len(out["recent_verdicts"]) == 2


def test_export_verdicts_uses_cumulative_total_in_index_and_ids(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(explorer, "_SD", tmp_path)
    _write_roast_history(
        tmp_path,
        {
            "total_roasted": 2500,
            "history": [
                {
                    "timestamp": "2026-01-01T00:00:01",
                    "source": "a",
                    "result": {"verdict": "quality", "score": {"total": 8}},
                },
                {
                    "timestamp": "2026-01-01T00:00:02",
                    "source": "b",
                    "result": {"verdict": "needs_work", "score": {"total": 4}},
                },
                {
                    "timestamp": "2026-01-01T00:00:03",
                    "source": "c",
                    "result": {"verdict": "quality", "score": {"total": 9}},
                },
            ],
        },
    )

    written = explorer._export_verdicts(tmp_path / "explore", limit=2)

    index_text = (tmp_path / "explore" / "verdicts" / "_index.md").read_text(encoding="utf-8")
    assert written == 3
    assert "total: 2500" in index_text
    assert "# Meta-Ralph Verdicts (2/2500)" in index_text
    assert (tmp_path / "explore" / "verdicts" / "verdict_02498.md").exists()
    assert (tmp_path / "explore" / "verdicts" / "verdict_02499.md").exists()
