from __future__ import annotations

import json

import lib.advisor as advisor_mod
import lib.advisory_preferences as prefs
import lib.advisory_engine as advisory_engine_mod
import lib.advisory_synthesizer as advisory_synth_mod


def test_setup_questions_has_two_questions_and_normalized_current():
    payload = prefs.setup_questions({"memory_mode": "bad-value", "guidance_style": "COACH"})

    assert payload["current"]["memory_mode"] == "standard"
    assert payload["current"]["guidance_style"] == "coach"
    assert len(payload["questions"]) == 2
    assert payload["questions"][0]["id"] == "memory_mode"
    assert payload["questions"][1]["id"] == "guidance_style"


def test_apply_preferences_persists_tuneables_and_metadata(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    monkeypatch.setattr(
        advisor_mod,
        "reload_advisor_config",
        lambda: {"replay_mode": "replay", "guidance_style": "coach"},
    )

    out = prefs.apply_preferences(
        memory_mode="replay",
        guidance_style="coach",
        path=tuneables,
        source="test",
    )
    data = json.loads(tuneables.read_text(encoding="utf-8"))

    assert out["ok"] is True
    assert out["memory_mode"] == "replay"
    assert out["guidance_style"] == "coach"
    assert out["runtime"]["replay_mode"] == "replay"
    assert out["runtime"]["guidance_style"] == "coach"
    assert data["advisor"]["replay_mode"] == "replay"
    assert data["advisor"]["guidance_style"] == "coach"
    assert data["advisor"]["replay_enabled"] is True
    assert data["advisor"]["max_items"] == 10
    assert data["advisor"]["min_rank_score"] == 0.5
    assert data["advisory_preferences"]["memory_mode"] == "replay"
    assert data["advisory_preferences"]["guidance_style"] == "coach"
    assert data["advisory_preferences"]["source"] == "test"


def test_get_current_preferences_preserves_explicit_overrides(tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "advisor": {
                    "replay_mode": "standard",
                    "guidance_style": "balanced",
                    "max_items": 3,
                    "replay_min_context": 0.42,
                }
            }
        ),
        encoding="utf-8",
    )

    out = prefs.get_current_preferences(path=tuneables)

    assert out["memory_mode"] == "standard"
    assert out["guidance_style"] == "balanced"
    assert out["effective"]["max_items"] == 3
    assert out["effective"]["replay_min_context"] == 0.42
    assert out["drift"]["has_drift"] is True
    assert out["drift"]["count"] >= 1
    assert any(item.get("key") == "max_items" for item in out["drift"]["overrides"])


def test_write_json_atomic_cleans_lock_file(tmp_path):
    tuneables = tmp_path / "tuneables.json"

    prefs._write_json_atomic(tuneables, {"advisor": {"replay_mode": "standard"}})

    assert tuneables.exists()
    assert not tuneables.with_suffix(".json.lock").exists()


def test_apply_preferences_raises_clear_error_on_lock_timeout(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"

    monkeypatch.setattr(
        prefs,
        "_write_json_atomic",
        lambda path, payload: (_ for _ in ()).throw(TimeoutError("busy")),
    )

    try:
        prefs.apply_preferences(memory_mode="standard", guidance_style="balanced", path=tuneables)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "busy" in str(exc)


def test_get_current_preferences_no_drift_after_apply(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    monkeypatch.setattr(advisor_mod, "reload_advisor_config", lambda: {})

    prefs.apply_preferences(
        memory_mode="standard",
        guidance_style="balanced",
        path=tuneables,
        source="test",
    )

    out = prefs.get_current_preferences(path=tuneables)

    assert out["memory_mode"] == "standard"
    assert out["guidance_style"] == "balanced"
    assert out["drift"]["has_drift"] is False
    assert out["drift"]["count"] == 0


def test_apply_quality_uplift_persists_and_hot_applies(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    calls = {"engine": None, "synth": None}

    def _fake_apply_engine(cfg):
        calls["engine"] = dict(cfg)
        return {"applied": ["enabled", "force_programmatic_synth"], "warnings": []}

    def _fake_get_engine_status():
        return {"enabled": True}

    def _fake_apply_synth(cfg):
        calls["synth"] = dict(cfg)
        return {"applied": ["mode", "preferred_provider"], "warnings": []}

    def _fake_get_synth_status():
        return {"tier_label": "AI-Enhanced", "ai_available": True}

    monkeypatch.setattr(advisory_engine_mod, "apply_engine_config", _fake_apply_engine)
    monkeypatch.setattr(advisory_engine_mod, "get_engine_status", _fake_get_engine_status)
    monkeypatch.setattr(advisory_synth_mod, "apply_synth_config", _fake_apply_synth)
    monkeypatch.setattr(advisory_synth_mod, "get_synth_status", _fake_get_synth_status)

    out = prefs.apply_quality_uplift(
        profile="enhanced",
        preferred_provider="ollama",
        ai_timeout_s=5.5,
        path=tuneables,
        source="test",
    )
    data = json.loads(tuneables.read_text(encoding="utf-8"))

    assert out["ok"] is True
    assert out["profile"] == "enhanced"
    assert out["preferred_provider"] == "ollama"
    assert out["warnings"] == []
    assert calls["engine"]["enabled"] is True
    assert calls["engine"]["force_programmatic_synth"] is False
    assert calls["synth"]["mode"] == "auto"
    assert calls["synth"]["preferred_provider"] == "ollama"
    assert calls["synth"]["ai_timeout_s"] == 5.5
    assert data["advisory_engine"]["force_programmatic_synth"] is False
    assert data["synthesizer"]["mode"] == "auto"
    assert data["synthesizer"]["preferred_provider"] == "ollama"
    assert data["advisory_quality"]["profile"] == "enhanced"


def test_repair_profile_drift_clears_overrides(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "advisor": {
                    "replay_mode": "standard",
                    "guidance_style": "balanced",
                    "max_items": 3,
                    "min_rank_score": 0.45,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(advisor_mod, "reload_advisor_config", lambda: {})

    out = prefs.repair_profile_drift(path=tuneables, source="test")

    assert out["ok"] is True
    assert out["before_drift"]["has_drift"] is True
    assert out["after_drift"]["has_drift"] is False


def test_apply_quality_uplift_sets_minimax_model(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    calls = {"synth": None}

    monkeypatch.setattr(advisory_engine_mod, "apply_engine_config", lambda cfg: {"applied": [], "warnings": []})
    monkeypatch.setattr(advisory_engine_mod, "get_engine_status", lambda: {"enabled": True})
    monkeypatch.setattr(
        advisory_synth_mod,
        "apply_synth_config",
        lambda cfg: calls.update({"synth": dict(cfg)}) or {"applied": [], "warnings": []},
    )
    monkeypatch.setattr(
        advisory_synth_mod,
        "get_synth_status",
        lambda: {"tier_label": "AI-Enhanced", "ai_available": True, "minimax_model": "MiniMax-M2.5"},
    )

    out = prefs.apply_quality_uplift(
        profile="enhanced",
        preferred_provider="minimax",
        minimax_model="MiniMax-M2.5",
        path=tuneables,
        source="test",
    )
    data = json.loads(tuneables.read_text(encoding="utf-8"))

    assert out["ok"] is True
    assert out["preferred_provider"] == "minimax"
    assert out["minimax_model"] == "MiniMax-M2.5"
    assert calls["synth"]["preferred_provider"] == "minimax"
    assert calls["synth"]["minimax_model"] == "MiniMax-M2.5"
    assert data["synthesizer"]["minimax_model"] == "MiniMax-M2.5"


def test_read_json_supports_bom_encoded_file(tmp_path):
    """_read_json must parse a UTF-8-BOM-prefixed JSON file correctly."""
    p = tmp_path / "prefs.json"
    p.write_text(json.dumps({"memory_mode": "replay"}), encoding="utf-8-sig")
    result = prefs._read_json(p)
    assert result["memory_mode"] == "replay"


def test_read_json_corrupt_json_returns_empty_without_double_read(tmp_path):
    """Corrupt JSON must return {} and must NOT trigger the utf-8 retry (reads file once)."""
    from pathlib import Path
    from unittest.mock import patch

    p = tmp_path / "prefs.json"
    p.write_text("{bad json!!!", encoding="utf-8")

    read_count = [0]
    original_read = Path.read_text

    def counted_read(self, *args, **kwargs):
        if self.name == "prefs.json":
            read_count[0] += 1
        return original_read(self, *args, **kwargs)

    with patch.object(Path, "read_text", counted_read):
        result = prefs._read_json(p)

    assert result == {}, f"Expected empty dict for corrupt JSON; got {result!r}"
    assert read_count[0] == 1, (
        f"prefs.json was read {read_count[0]} time(s); expected 1. "
        "JSONDecodeError must not trigger the pointless utf-8 retry."
    )
