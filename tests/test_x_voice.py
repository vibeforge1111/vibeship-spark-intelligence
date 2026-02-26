"""Tests for lib/x_voice.py — XVoice warmth tracker and ToneProfile."""

import json
import sys
import importlib
from pathlib import Path

import pytest

import lib.x_voice as xv
from lib.x_voice import (
    ToneProfile,
    TONE_PROFILES,
    XVoice,
    _WARMTH_PROGRESS,
    get_x_voice,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_voice(tmp_path, monkeypatch):
    """Return an XVoice instance pointing at tmp_path."""
    monkeypatch.setattr(xv, "X_VOICE_DIR", tmp_path / "x_voice")
    monkeypatch.setattr(xv, "PROFILES_FILE", tmp_path / "x_voice" / "profiles.json")
    # Reset singleton so get_x_voice() creates a fresh instance
    monkeypatch.setattr(xv, "_x_voice", None)
    return XVoice()


# ---------------------------------------------------------------------------
# ToneProfile dataclass
# ---------------------------------------------------------------------------

class TestToneProfile:
    def test_default_empty_markers(self):
        tp = ToneProfile()
        assert tp.tone_markers == []

    def test_markers_stored(self):
        tp = ToneProfile(["a", "b", "c"])
        assert tp.tone_markers == ["a", "b", "c"]

    def test_markers_are_list(self):
        tp = ToneProfile(["x"])
        assert isinstance(tp.tone_markers, list)

    def test_independent_instances(self):
        tp1 = ToneProfile(["x"])
        tp2 = ToneProfile()
        assert tp1.tone_markers is not tp2.tone_markers


# ---------------------------------------------------------------------------
# TONE_PROFILES dict
# ---------------------------------------------------------------------------

class TestToneProfilesDict:
    def test_has_witty(self):
        assert "witty" in TONE_PROFILES

    def test_has_technical(self):
        assert "technical" in TONE_PROFILES

    def test_has_conversational(self):
        assert "conversational" in TONE_PROFILES

    def test_has_provocative(self):
        assert "provocative" in TONE_PROFILES

    def test_all_values_are_tone_profile(self):
        for v in TONE_PROFILES.values():
            assert isinstance(v, ToneProfile)

    def test_witty_contains_humor(self):
        assert "humor" in TONE_PROFILES["witty"].tone_markers

    def test_technical_contains_api(self):
        assert "api" in TONE_PROFILES["technical"].tone_markers

    def test_conversational_contains_hey(self):
        assert "hey" in TONE_PROFILES["conversational"].tone_markers

    def test_provocative_contains_disagree(self):
        assert "disagree" in TONE_PROFILES["provocative"].tone_markers


# ---------------------------------------------------------------------------
# _WARMTH_PROGRESS list
# ---------------------------------------------------------------------------

class TestWarmthProgress:
    def test_starts_cold(self):
        assert _WARMTH_PROGRESS[0] == "cold"

    def test_ends_ally(self):
        assert _WARMTH_PROGRESS[-1] == "ally"

    def test_has_five_levels(self):
        assert len(_WARMTH_PROGRESS) == 5

    def test_order(self):
        assert _WARMTH_PROGRESS == ["cold", "cool", "warm", "hot", "ally"]


# ---------------------------------------------------------------------------
# XVoice._normalize_handle
# ---------------------------------------------------------------------------

class TestNormalizeHandle:
    def test_strips_at_sign(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        assert v._normalize_handle("@Alice") == "alice"

    def test_lowercases(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        assert v._normalize_handle("BOB") == "bob"

    def test_strips_whitespace(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        assert v._normalize_handle("  carol  ") == "carol"

    def test_at_and_upper(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        assert v._normalize_handle("@DAVE") == "dave"

    def test_no_at_unchanged(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        assert v._normalize_handle("eve") == "eve"


# ---------------------------------------------------------------------------
# XVoice._clamp_warmth
# ---------------------------------------------------------------------------

class TestClampWarmth:
    def test_clamp_below_zero(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        assert v._clamp_warmth(-1) == 0

    def test_clamp_zero_stays(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        assert v._clamp_warmth(0) == 0

    def test_clamp_valid_middle(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        assert v._clamp_warmth(2) == 2

    def test_clamp_at_max(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        assert v._clamp_warmth(4) == 4

    def test_clamp_above_max(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        # len == 5, so >=5 should clamp to 4
        assert v._clamp_warmth(10) == 4

    def test_clamp_exactly_len(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        assert v._clamp_warmth(5) == 4


# ---------------------------------------------------------------------------
# XVoice.get_user_warmth / _set_user_warmth
# ---------------------------------------------------------------------------

class TestGetSetUserWarmth:
    def test_unknown_handle_returns_cold(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        assert v.get_user_warmth("@nobody") == "cold"

    def test_set_and_get_warmth(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v._set_user_warmth("@alice", "warm")
        assert v.get_user_warmth("@alice") == "warm"

    def test_handle_normalised_on_get(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v._set_user_warmth("alice", "hot")
        assert v.get_user_warmth("@ALICE") == "hot"

    def test_set_persists_to_disk(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v._set_user_warmth("bob", "ally")
        profiles_file = tmp_path / "x_voice" / "profiles.json"
        assert profiles_file.exists()
        data = json.loads(profiles_file.read_text())
        assert data["bob"] == "ally"


# ---------------------------------------------------------------------------
# XVoice._load (persistence round-trip)
# ---------------------------------------------------------------------------

class TestLoad:
    def test_load_empty_when_no_file(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        assert v._state == {}

    def test_load_existing_file(self, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "x_voice"
        profiles_dir.mkdir(parents=True)
        profiles_file = profiles_dir / "profiles.json"
        profiles_file.write_text(json.dumps({"carol": "warm"}), encoding="utf-8")
        monkeypatch.setattr(xv, "X_VOICE_DIR", profiles_dir)
        monkeypatch.setattr(xv, "PROFILES_FILE", profiles_file)
        monkeypatch.setattr(xv, "_x_voice", None)
        v = XVoice()
        assert v.get_user_warmth("carol") == "warm"

    def test_load_corrupted_file_returns_empty(self, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "x_voice"
        profiles_dir.mkdir(parents=True)
        profiles_file = profiles_dir / "profiles.json"
        profiles_file.write_text("not-json!", encoding="utf-8")
        monkeypatch.setattr(xv, "X_VOICE_DIR", profiles_dir)
        monkeypatch.setattr(xv, "PROFILES_FILE", profiles_file)
        monkeypatch.setattr(xv, "_x_voice", None)
        v = XVoice()
        assert v._state == {}

    def test_load_non_dict_json_returns_empty(self, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "x_voice"
        profiles_dir.mkdir(parents=True)
        profiles_file = profiles_dir / "profiles.json"
        profiles_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        monkeypatch.setattr(xv, "X_VOICE_DIR", profiles_dir)
        monkeypatch.setattr(xv, "PROFILES_FILE", profiles_file)
        monkeypatch.setattr(xv, "_x_voice", None)
        v = XVoice()
        assert v._state == {}


# ---------------------------------------------------------------------------
# XVoice.update_warmth
# ---------------------------------------------------------------------------

class TestUpdateWarmth:
    def test_reply_increases_one_step(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v.update_warmth("alice", "reply")
        # cold(0) + 1 = cool(1)
        assert v.get_user_warmth("alice") == "cool"

    def test_like_increases_one_step(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v.update_warmth("alice", "like")
        assert v.get_user_warmth("alice") == "cool"

    def test_mention_increases_one_step(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v.update_warmth("alice", "mention")
        assert v.get_user_warmth("alice") == "cool"

    def test_share_increases_one_step(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v.update_warmth("alice", "share")
        assert v.get_user_warmth("alice") == "cool"

    def test_mutual_like_increases_one_step(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v.update_warmth("alice", "mutual_like")
        assert v.get_user_warmth("alice") == "cool"

    def test_they_mention_us_increases_two_steps(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v.update_warmth("bob", "they_mention_us")
        # cold(0) + 2 = warm(2)
        assert v.get_user_warmth("bob") == "warm"

    def test_reply_received_increases_two_steps(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v.update_warmth("bob", "reply_received")
        assert v.get_user_warmth("bob") == "warm"

    def test_sustained_engagement_increases_two_steps(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v.update_warmth("bob", "sustained_engagement")
        assert v.get_user_warmth("bob") == "warm"

    def test_collaboration_increases_three_steps(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v.update_warmth("carol", "collaboration")
        # cold(0) + 3 = hot(3)
        assert v.get_user_warmth("carol") == "hot"

    def test_multi_turn_convo_increases_three_steps(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v.update_warmth("carol", "multi_turn_convo")
        assert v.get_user_warmth("carol") == "hot"

    def test_conflict_decreases_one_step(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        # Set to warm(2) first
        v._set_user_warmth("dave", "warm")
        v.update_warmth("dave", "conflict")
        # warm(2) - 1 = cool(1)
        assert v.get_user_warmth("dave") == "cool"

    def test_spam_decreases_one_step(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v._set_user_warmth("dave", "warm")
        v.update_warmth("dave", "spam")
        assert v.get_user_warmth("dave") == "cool"

    def test_conflict_at_cold_stays_cold(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v.update_warmth("eve", "conflict")
        # cold(0) - 1 = clamped to 0 = cold
        assert v.get_user_warmth("eve") == "cold"

    def test_unknown_event_no_change(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v._set_user_warmth("frank", "warm")
        v.update_warmth("frank", "unknown_event_xyz")
        assert v.get_user_warmth("frank") == "warm"

    def test_update_clamps_at_ally(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        # Set to ally(4), +3 steps should stay at ally
        v._set_user_warmth("grace", "ally")
        v.update_warmth("grace", "collaboration")
        assert v.get_user_warmth("grace") == "ally"

    def test_multiple_updates_accumulate(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v.update_warmth("henry", "reply")   # cool
        v.update_warmth("henry", "reply")   # warm
        assert v.get_user_warmth("henry") == "warm"

    def test_update_persists_to_disk(self, tmp_path, monkeypatch):
        v = _make_voice(tmp_path, monkeypatch)
        v.update_warmth("iris", "like")
        profiles_file = tmp_path / "x_voice" / "profiles.json"
        data = json.loads(profiles_file.read_text())
        assert data.get("iris") == "cool"


# ---------------------------------------------------------------------------
# get_x_voice singleton
# ---------------------------------------------------------------------------

class TestGetXVoice:
    def test_returns_xvoice_instance(self, tmp_path, monkeypatch):
        monkeypatch.setattr(xv, "X_VOICE_DIR", tmp_path / "x_voice")
        monkeypatch.setattr(xv, "PROFILES_FILE", tmp_path / "x_voice" / "profiles.json")
        monkeypatch.setattr(xv, "_x_voice", None)
        instance = get_x_voice()
        assert isinstance(instance, XVoice)

    def test_returns_same_instance_on_second_call(self, tmp_path, monkeypatch):
        monkeypatch.setattr(xv, "X_VOICE_DIR", tmp_path / "x_voice")
        monkeypatch.setattr(xv, "PROFILES_FILE", tmp_path / "x_voice" / "profiles.json")
        monkeypatch.setattr(xv, "_x_voice", None)
        inst1 = get_x_voice()
        inst2 = get_x_voice()
        assert inst1 is inst2

    def test_cached_instance_reused(self, tmp_path, monkeypatch):
        existing = XVoice.__new__(XVoice)
        existing._state = {"cached": "warm"}
        monkeypatch.setattr(xv, "_x_voice", existing)
        result = get_x_voice()
        assert result is existing
