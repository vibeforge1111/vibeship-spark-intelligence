"""Tests for auto_promote._load_promotion_config_interval() exception specificity fixes."""
import json
from pathlib import Path

import pytest


def test_corrupt_json_logs_and_returns_default(tmp_path, monkeypatch):
    """Corrupt tuneables.json should log via log_debug and return DEFAULT_INTERVAL_S."""
    spark_dir = tmp_path / ".spark"
    spark_dir.mkdir(parents=True)
    (spark_dir / "tuneables.json").write_text("{broken json}", encoding="utf-8")

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    import lib.auto_promote as ap_mod

    captured = []
    monkeypatch.setattr(
        ap_mod, "log_debug", lambda tag, msg, exc: captured.append((tag, msg, exc))
    )

    result = ap_mod._load_promotion_config_interval()

    assert result == ap_mod.DEFAULT_INTERVAL_S
    assert len(captured) == 1
    assert captured[0][0] == "auto_promote"


def test_valid_interval_returned(tmp_path, monkeypatch):
    """Valid tuneables.json with promotion.auto_interval_s should be returned."""
    spark_dir = tmp_path / ".spark"
    spark_dir.mkdir(parents=True)
    (spark_dir / "tuneables.json").write_text(
        json.dumps({"promotion": {"auto_interval_s": 7200}}), encoding="utf-8"
    )

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    import lib.auto_promote as ap_mod

    result = ap_mod._load_promotion_config_interval()

    assert result == 7200
