from __future__ import annotations

import json

import lib.auto_promote as auto_promote
import lib.promoter as promoter


def test_promoter_load_config_reads_promotion_section(tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "promotion": {"threshold": 0.91, "min_age_hours": 9.0},
            }
        ),
        encoding="utf-8",
    )

    cfg = promoter._load_promotion_config(path=tuneables)

    assert cfg["threshold"] == 0.91
    assert cfg["min_age_hours"] == 9.0


def test_auto_promote_interval_uses_promotion_section(tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps({"promotion": {"auto_interval_s": 1234}}),
        encoding="utf-8",
    )

    interval = auto_promote._load_promotion_config_interval(path=tuneables)

    assert interval == 1234
