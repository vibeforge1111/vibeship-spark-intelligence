import json

import lib.spark_emotions as se
from lib.spark_emotions import SparkEmotions


def test_emotion_timeline_continuity_persists(tmp_path):
    state_file = tmp_path / "emotion_state.json"
    emotions = SparkEmotions(state_file=state_file)

    emotions.register_trigger("user_confusion", intensity=0.8, note="asked for clarification")
    first_len = len(emotions.state.emotion_timeline)

    reloaded = SparkEmotions(state_file=state_file)
    assert len(reloaded.state.emotion_timeline) >= first_len
    assert any(e["event"] == "trigger_applied" for e in reloaded.state.emotion_timeline)


def test_trigger_mapping_updates_emotional_state(tmp_path):
    emotions = SparkEmotions(state_file=tmp_path / "emotion_state.json")
    before = emotions.state
    base_calm = before.calm
    base_strain = before.strain

    emotions.register_trigger("user_frustration", intensity=1.0)

    assert emotions.state.primary_emotion == "supportive_focus"
    assert emotions.state.calm > base_calm
    assert emotions.state.strain > base_strain
    assert emotions.state.recovery_cooldown >= 1


def test_recovery_de_escalates_strain_and_resets_emotion(tmp_path):
    emotions = SparkEmotions(state_file=tmp_path / "emotion_state.json")

    emotions.register_trigger("high_stakes_request", intensity=1.0)
    strained = emotions.state.strain

    for _ in range(6):
        emotions.recover()

    assert emotions.state.strain < strained
    assert emotions.state.primary_emotion == "steady"


def test_unknown_trigger_is_safe_and_logged(tmp_path):
    emotions = SparkEmotions(state_file=tmp_path / "emotion_state.json")
    before = len(emotions.state.emotion_timeline)

    emotions.register_trigger("not_a_real_trigger", intensity=1.0)

    assert len(emotions.state.emotion_timeline) == before + 1
    assert emotions.state.emotion_timeline[-1]["event"] == "trigger_ignored"


def test_legacy_repo_local_state_migrates_to_runtime_path(tmp_path, monkeypatch):
    legacy_state = tmp_path / "repo" / ".spark" / "emotion_state.json"
    legacy_state.parent.mkdir(parents=True, exist_ok=True)
    legacy_state.write_text(
        json.dumps(
            {
                "warmth": 0.51,
                "energy": 0.52,
                "confidence": 0.53,
                "calm": 0.54,
                "playfulness": 0.55,
                "strain": 0.21,
                "mode": "real_talk",
                "primary_emotion": "steady",
                "recovery_cooldown": 0,
                "emotion_timeline": [],
                "updated_at": "2026-02-17T00:00:00+00:00",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    runtime_state = tmp_path / "home" / ".spark" / "emotion_state.json"
    monkeypatch.setattr(se, "LEGACY_STATE_FILE", legacy_state)

    emotions = se.SparkEmotions(state_file=runtime_state)

    assert runtime_state.exists()
    assert emotions.state.warmth == 0.51
    assert len(emotions.state.emotion_timeline) >= 1


def test_load_state_corrupt_json_logs_and_returns_default(tmp_path, monkeypatch):
    """Corrupt emotion state file must log and return default EmotionState."""
    from unittest.mock import patch
    from lib.spark_emotions import SparkEmotions, EmotionState

    state_file = tmp_path / "emotion_state.json"
    state_file.write_text("{corrupt", encoding="utf-8")

    logged = []
    with patch("lib.spark_emotions.log_debug", side_effect=lambda *a, **kw: logged.append(a)):
        se = SparkEmotions(state_file=state_file)

    # Must recover to a fresh default state (not crash)
    assert isinstance(se.state, EmotionState)
    # Must have logged the failure
    assert any("emotion state" in str(args).lower() or "starting fresh" in str(args).lower()
               for args in logged), (
        f"Expected log_debug about state load failure; got: {logged}"
    )
