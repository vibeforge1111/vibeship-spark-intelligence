"""Tests for lib/spark_voice.py

Covers:
- Opinion dataclass: fields present, times_confirmed default=1
- GrowthMoment dataclass: fields present
- SparkVoice.form_opinion(): stores opinion, returns Opinion, strengthens
  existing opinion on second call (times_confirmed + 1, strength increased),
  key is lowercased/underscored topic
- SparkVoice.get_opinions(): returns list of Opinion
- SparkVoice.get_strong_opinions(): filters by strength threshold
- SparkVoice.express_opinion(): None when unknown topic, text when known,
  contains 'strongly' when strength > 0.8
- SparkVoice.record_growth(): returns GrowthMoment, appends to data
- SparkVoice.get_recent_growth(): returns list, respects limit
- SparkVoice.record_interaction(): increments interactions count
- SparkVoice.get_stats(): returns dict with expected keys
"""

from __future__ import annotations

from pathlib import Path

import pytest

import lib.spark_voice as sv
from lib.spark_voice import Opinion, GrowthMoment, SparkVoice


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_voice(tmp_path: Path) -> SparkVoice:
    monkeypath_file = tmp_path / "voice.json"
    sv.VOICE_FILE = monkeypath_file
    sv.SPARK_DIR = tmp_path
    return SparkVoice()


# ---------------------------------------------------------------------------
# Opinion dataclass
# ---------------------------------------------------------------------------

def test_opinion_has_topic():
    o = Opinion(topic="tabs", preference="tabs", reason="cleaner", strength=0.7)
    assert o.topic == "tabs"


def test_opinion_default_times_confirmed():
    o = Opinion(topic="tabs", preference="tabs", reason="cleaner", strength=0.7)
    assert o.times_confirmed == 1


def test_opinion_strength_stored():
    o = Opinion(topic="tabs", preference="tabs", reason="cleaner", strength=0.9)
    assert o.strength == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# GrowthMoment dataclass
# ---------------------------------------------------------------------------

def test_growth_moment_has_all_fields():
    g = GrowthMoment(before="did X", after="now do Y", trigger="learned Z", impact="better Q")
    assert g.before == "did X"
    assert g.after == "now do Y"
    assert g.trigger == "learned Z"
    assert g.impact == "better Q"


def test_growth_moment_has_timestamp():
    g = GrowthMoment(before="a", after="b", trigger="c", impact="d")
    assert g.timestamp  # non-empty ISO string


# ---------------------------------------------------------------------------
# SparkVoice.form_opinion
# ---------------------------------------------------------------------------

def test_form_opinion_returns_opinion(tmp_path):
    voice = _make_voice(tmp_path)
    result = voice.form_opinion("indentation", "spaces", "PEP8", strength=0.7)
    assert isinstance(result, Opinion)


def test_form_opinion_stores_preference(tmp_path):
    voice = _make_voice(tmp_path)
    voice.form_opinion("testing", "pytest", "great fixtures")
    assert "testing" in voice.data["opinions"]


def test_form_opinion_key_is_lowercased(tmp_path):
    voice = _make_voice(tmp_path)
    voice.form_opinion("Code Style", "black", "consistent")
    assert "code_style" in voice.data["opinions"]


def test_form_opinion_strengthens_on_repeat(tmp_path):
    voice = _make_voice(tmp_path)
    voice.form_opinion("tabs", "tabs", "alignment")
    first_strength = voice.data["opinions"]["tabs"]["strength"]
    result = voice.form_opinion("tabs", "tabs", "still alignment")
    assert result.strength > first_strength


def test_form_opinion_increments_times_confirmed(tmp_path):
    voice = _make_voice(tmp_path)
    voice.form_opinion("tabs", "tabs", "reason")
    voice.form_opinion("tabs", "tabs", "same")
    assert voice.data["opinions"]["tabs"]["times_confirmed"] == 2


def test_form_opinion_saves_to_disk(tmp_path):
    voice = _make_voice(tmp_path)
    voice.form_opinion("tabs", "tabs", "reason")
    assert (tmp_path / "voice.json").exists()


# ---------------------------------------------------------------------------
# SparkVoice.get_opinions
# ---------------------------------------------------------------------------

def test_get_opinions_returns_list(tmp_path):
    voice = _make_voice(tmp_path)
    assert isinstance(voice.get_opinions(), list)


def test_get_opinions_empty_initially(tmp_path):
    voice = _make_voice(tmp_path)
    assert voice.get_opinions() == []


def test_get_opinions_returns_opinion_instances(tmp_path):
    voice = _make_voice(tmp_path)
    voice.form_opinion("tabs", "tabs", "reason")
    opinions = voice.get_opinions()
    assert all(isinstance(o, Opinion) for o in opinions)


def test_get_opinions_count(tmp_path):
    voice = _make_voice(tmp_path)
    voice.form_opinion("tabs", "tabs", "reason")
    voice.form_opinion("quotes", "double", "consistency")
    assert len(voice.get_opinions()) == 2


# ---------------------------------------------------------------------------
# SparkVoice.get_strong_opinions
# ---------------------------------------------------------------------------

def test_get_strong_opinions_filters_by_strength(tmp_path):
    voice = _make_voice(tmp_path)
    voice.form_opinion("tabs", "tabs", "reason", strength=0.9)
    voice.form_opinion("spaces", "spaces", "pep8", strength=0.4)
    strong = voice.get_strong_opinions(min_strength=0.7)
    assert len(strong) == 1
    assert strong[0].topic == "tabs"


def test_get_strong_opinions_empty_when_none_qualify(tmp_path):
    voice = _make_voice(tmp_path)
    voice.form_opinion("tabs", "tabs", "reason", strength=0.3)
    assert voice.get_strong_opinions(min_strength=0.7) == []


# ---------------------------------------------------------------------------
# SparkVoice.express_opinion
# ---------------------------------------------------------------------------

def test_express_opinion_none_when_unknown(tmp_path):
    voice = _make_voice(tmp_path)
    assert voice.express_opinion("unknown topic") is None


def test_express_opinion_returns_string(tmp_path):
    voice = _make_voice(tmp_path)
    voice.form_opinion("tabs", "tabs", "better alignment")
    result = voice.express_opinion("tabs")
    assert isinstance(result, str)


def test_express_opinion_contains_preference(tmp_path):
    voice = _make_voice(tmp_path)
    voice.form_opinion("formatting", "black", "auto-formats")
    result = voice.express_opinion("formatting")
    assert "black" in result


def test_express_opinion_strongly_when_strength_high(tmp_path):
    voice = _make_voice(tmp_path)
    # Form opinion many times to push strength above 0.8
    for _ in range(5):
        voice.form_opinion("tabs", "tabs over spaces", "alignment")
    result = voice.express_opinion("tabs")
    assert "strongly" in result


# ---------------------------------------------------------------------------
# SparkVoice.record_growth
# ---------------------------------------------------------------------------

def test_record_growth_returns_growth_moment(tmp_path):
    voice = _make_voice(tmp_path)
    result = voice.record_growth("did X", "now Y", "learned Z", "better Q")
    assert isinstance(result, GrowthMoment)


def test_record_growth_stores_in_data(tmp_path):
    voice = _make_voice(tmp_path)
    voice.record_growth("before", "after", "trigger", "impact")
    assert len(voice.data["growth_moments"]) == 1


def test_record_growth_fields_correct(tmp_path):
    voice = _make_voice(tmp_path)
    voice.record_growth("used X", "now use Y", "discovered Y", "Y is faster")
    g = voice.data["growth_moments"][0]
    assert g["before"] == "used X"
    assert g["after"] == "now use Y"


def test_record_growth_saves_to_disk(tmp_path):
    voice = _make_voice(tmp_path)
    voice.record_growth("before", "after", "trigger", "impact")
    assert (tmp_path / "voice.json").exists()


# ---------------------------------------------------------------------------
# SparkVoice.get_recent_growth
# ---------------------------------------------------------------------------

def test_get_recent_growth_returns_list(tmp_path):
    voice = _make_voice(tmp_path)
    assert isinstance(voice.get_recent_growth(), list)


def test_get_recent_growth_empty_initially(tmp_path):
    voice = _make_voice(tmp_path)
    assert voice.get_recent_growth() == []


def test_get_recent_growth_respects_limit(tmp_path):
    voice = _make_voice(tmp_path)
    for i in range(10):
        voice.record_growth(f"before{i}", f"after{i}", "trigger", "impact")
    result = voice.get_recent_growth(limit=3)
    assert len(result) == 3


def test_get_recent_growth_returns_growth_moment_instances(tmp_path):
    voice = _make_voice(tmp_path)
    voice.record_growth("x", "y", "z", "w")
    items = voice.get_recent_growth()
    assert all(isinstance(g, GrowthMoment) for g in items)


# ---------------------------------------------------------------------------
# SparkVoice.record_interaction
# ---------------------------------------------------------------------------

def test_record_interaction_increments_count(tmp_path):
    voice = _make_voice(tmp_path)
    voice.record_interaction()
    assert voice.data["interactions"] == 1


def test_record_interaction_increments_again(tmp_path):
    voice = _make_voice(tmp_path)
    voice.record_interaction()
    voice.record_interaction()
    assert voice.data["interactions"] == 2


# ---------------------------------------------------------------------------
# SparkVoice.get_stats
# ---------------------------------------------------------------------------

def test_get_stats_returns_dict(tmp_path):
    voice = _make_voice(tmp_path)
    assert isinstance(voice.get_stats(), dict)


def test_get_stats_has_expected_keys(tmp_path):
    voice = _make_voice(tmp_path)
    stats = voice.get_stats()
    for key in ("opinions_formed", "growth_moments", "interactions", "strong_opinions"):
        assert key in stats


def test_get_stats_opinions_formed_correct(tmp_path):
    voice = _make_voice(tmp_path)
    voice.form_opinion("tabs", "tabs", "reason")
    voice.form_opinion("quotes", "double", "consistency")
    assert voice.get_stats()["opinions_formed"] == 2


def test_get_stats_interactions_correct(tmp_path):
    voice = _make_voice(tmp_path)
    voice.record_interaction()
    voice.record_interaction()
    assert voice.get_stats()["interactions"] == 2
