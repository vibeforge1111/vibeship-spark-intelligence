"""Tests for outcome_predictor store read exception specificity fix."""
import json


def test_corrupt_store_logs_and_uses_empty(tmp_path, monkeypatch):
    """Corrupt store file should log via log_debug and fall back to empty keys."""
    store = tmp_path / "outcome_predictor.json"
    store.write_text("not json {{", encoding="utf-8")

    import lib.outcome_predictor as op_mod

    monkeypatch.setattr(op_mod, "STORE_PATH", store)
    monkeypatch.setattr(op_mod, "_cache", None)
    monkeypatch.setattr(op_mod, "_cache_ts", 0.0)

    captured = []
    monkeypatch.setattr(
        op_mod, "log_debug", lambda tag, msg, exc: captured.append((tag, msg, exc))
    )

    result = op_mod._load_store()

    assert result["keys"] == {}
    assert len(captured) == 1
    assert captured[0][0] == "outcome_predictor"


def test_valid_store_loaded(tmp_path, monkeypatch):
    """Valid store JSON should be loaded and cached correctly."""
    store = tmp_path / "outcome_predictor.json"
    payload = {"version": 1, "updated_at": 1000.0, "keys": {"k1": {"phase": "learn"}}}
    store.write_text(json.dumps(payload), encoding="utf-8")

    import lib.outcome_predictor as op_mod

    monkeypatch.setattr(op_mod, "STORE_PATH", store)
    monkeypatch.setattr(op_mod, "_cache", None)
    monkeypatch.setattr(op_mod, "_cache_ts", 0.0)

    result = op_mod._load_store()

    assert "k1" in result["keys"]
