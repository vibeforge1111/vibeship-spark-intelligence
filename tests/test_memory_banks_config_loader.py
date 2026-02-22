"""Tests for memory_banks._load_memory_emotion_config() exception specificity fix."""
import json


def test_corrupt_json_logs_and_returns_empty(tmp_path, monkeypatch):
    """Corrupt tuneables.json should log via log_debug and return {}."""
    spark_dir = tmp_path / ".spark"
    spark_dir.mkdir(parents=True)
    (spark_dir / "tuneables.json").write_text("{not valid", encoding="utf-8")

    import lib.memory_banks as mb_mod

    monkeypatch.setattr(mb_mod, "TUNEABLES_FILE", spark_dir / "tuneables.json")

    captured = []
    monkeypatch.setattr(
        mb_mod, "log_debug", lambda tag, msg, exc: captured.append((tag, msg, exc))
    )

    result = mb_mod._load_memory_emotion_config()

    assert result == {}
    assert len(captured) == 1
    assert captured[0][0] == "memory_banks"
    assert "tuneables" in captured[0][1]


def test_valid_config_returned(tmp_path, monkeypatch):
    """Valid tuneables.json with memory_emotion section should be returned."""
    spark_dir = tmp_path / ".spark"
    spark_dir.mkdir(parents=True)
    (spark_dir / "tuneables.json").write_text(
        json.dumps({"memory_emotion": {"write_capture_enabled": False}}),
        encoding="utf-8",
    )

    import lib.memory_banks as mb_mod

    monkeypatch.setattr(mb_mod, "TUNEABLES_FILE", spark_dir / "tuneables.json")

    result = mb_mod._load_memory_emotion_config()

    assert result == {"write_capture_enabled": False}
