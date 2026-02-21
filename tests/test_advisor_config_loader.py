from __future__ import annotations

import json

import lib.advisor as advisor_mod


def test_load_advisor_config_supports_utf8_bom(monkeypatch, tmp_path):
    spark_dir = tmp_path / ".spark"
    spark_dir.mkdir(parents=True, exist_ok=True)
    tuneables = spark_dir / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "advisor": {
                    "max_items": 4,
                    "max_advice_items": 4,
                    "min_rank_score": 0.55,
                    "cache_ttl": 120,
                }
            }
        ),
        encoding="utf-8-sig",
    )

    monkeypatch.setattr(advisor_mod.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(advisor_mod, "MAX_ADVICE_ITEMS", 8)
    monkeypatch.setattr(advisor_mod, "MIN_RANK_SCORE", 0.35)
    monkeypatch.setattr(advisor_mod, "ADVICE_CACHE_TTL_SECONDS", 180)

    advisor_mod._load_advisor_config()

    assert advisor_mod.MAX_ADVICE_ITEMS == 4
    assert advisor_mod.MIN_RANK_SCORE == 0.55
    assert advisor_mod.ADVICE_CACHE_TTL_SECONDS == 120


def test_load_advisor_config_corrupt_json_logs_warning(monkeypatch, tmp_path):
    """Corrupt tuneables.json must log a warning and leave defaults unchanged."""
    import logging

    spark_dir = tmp_path / ".spark"
    spark_dir.mkdir(parents=True, exist_ok=True)
    tuneables = spark_dir / "tuneables.json"
    tuneables.write_text("{bad json !!!", encoding="utf-8")

    monkeypatch.setattr(advisor_mod.Path, "home", lambda: tmp_path)
    original_max = advisor_mod.MAX_ADVICE_ITEMS

    logged = []
    logger = logging.getLogger("spark.advisor")
    original_propagate = logger.propagate
    logger.propagate = False

    class _Capture(logging.Handler):
        def emit(self, record):
            logged.append(record.getMessage())

    cap = _Capture()
    logger.addHandler(cap)
    try:
        advisor_mod._load_advisor_config()
    finally:
        logger.removeHandler(cap)
        logger.propagate = original_propagate

    assert any("tuneables" in msg.lower() or "advisor" in msg.lower() for msg in logged), (
        f"Expected a warning about config load failure; got: {logged}"
    )
    assert advisor_mod.MAX_ADVICE_ITEMS == original_max


def test_load_advisor_config_corrupt_json_no_double_read(monkeypatch, tmp_path):
    """JSONDecodeError must not trigger the pointless utf-8 retry (same bytes = same error)."""
    from pathlib import Path
    from unittest.mock import patch

    spark_dir = tmp_path / ".spark"
    spark_dir.mkdir(parents=True, exist_ok=True)
    tuneables = spark_dir / "tuneables.json"
    tuneables.write_text("{bad json !!!", encoding="utf-8")

    monkeypatch.setattr(advisor_mod.Path, "home", lambda: tmp_path)

    read_count = [0]
    original_read = Path.read_text

    def counted_read(self, *args, **kwargs):
        if self.name == "tuneables.json":
            read_count[0] += 1
        return original_read(self, *args, **kwargs)

    with patch.object(Path, "read_text", counted_read):
        advisor_mod._load_advisor_config()

    assert read_count[0] == 1, (
        f"tuneables.json was read {read_count[0]} time(s); expected 1. "
        "JSONDecodeError must not trigger the pointless utf-8 retry."
    )
