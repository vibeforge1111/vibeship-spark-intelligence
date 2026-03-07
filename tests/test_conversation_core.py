"""Tests for lib/conversation_core.py."""

from __future__ import annotations

import pytest

from lib.conversation_core import (
    NON_CONVERSATIONAL_PATTERNS,
    ConversationCore,
    ConversationScore,
)


# ---------------------------------------------------------------------------
# ConversationScore dataclass
# ---------------------------------------------------------------------------

def test_conversation_score_total():
    s = ConversationScore(naturalness=2, clarity=2, tone_match=2, clean_speech=2, brevity=2)
    assert s.total == 10


def test_conversation_score_total_zero():
    s = ConversationScore(naturalness=0, clarity=0, tone_match=0, clean_speech=0, brevity=0)
    assert s.total == 0


def test_conversation_score_total_partial():
    s = ConversationScore(naturalness=2, clarity=1, tone_match=2, clean_speech=0, brevity=2)
    assert s.total == 7


def test_conversation_score_fields_accessible():
    s = ConversationScore(naturalness=1, clarity=2, tone_match=1, clean_speech=2, brevity=1)
    assert s.naturalness == 1
    assert s.clarity == 2
    assert s.tone_match == 1
    assert s.clean_speech == 2
    assert s.brevity == 1


# ---------------------------------------------------------------------------
# ConversationCore.select_mode
# ---------------------------------------------------------------------------

@pytest.fixture
def core():
    return ConversationCore()


def test_select_mode_frustrated_returns_calm_focus(core):
    assert core.select_mode(user_signal="I'm frustrated") == "calm_focus"


def test_select_mode_stressed_returns_calm_focus(core):
    assert core.select_mode(user_signal="I'm stressed out") == "calm_focus"


def test_select_mode_urgent_returns_calm_focus(core):
    assert core.select_mode(user_signal="this is urgent") == "calm_focus"


def test_select_mode_serious_returns_calm_focus(core):
    assert core.select_mode(user_signal="this is serious") == "calm_focus"


def test_select_mode_sensitive_returns_calm_focus(core):
    assert core.select_mode(user_signal="sensitive topic here") == "calm_focus"


def test_select_mode_win_returns_spark_alive(core):
    assert core.select_mode(user_signal="we win today!") == "spark_alive"


def test_select_mode_excited_returns_spark_alive(core):
    assert core.select_mode(user_signal="I'm so excited about this") == "spark_alive"


def test_select_mode_celebrate_returns_spark_alive(core):
    assert core.select_mode(user_signal="let's celebrate!") == "spark_alive"


def test_select_mode_great_returns_spark_alive(core):
    assert core.select_mode(user_signal="this is great") == "spark_alive"


def test_select_mode_awesome_returns_spark_alive(core):
    assert core.select_mode(user_signal="awesome work") == "spark_alive"


def test_select_mode_neutral_returns_real_talk(core):
    assert core.select_mode(user_signal="what is the weather") == "real_talk"


def test_select_mode_empty_returns_real_talk(core):
    assert core.select_mode(user_signal="") == "real_talk"


def test_select_mode_topic_considered(core):
    result = core.select_mode(user_signal="regular message", topic="frustrated work")
    assert result == "calm_focus"


def test_select_mode_case_insensitive_keyword(core):
    assert core.select_mode(user_signal="I am FRUSTRATED") == "calm_focus"


def test_select_mode_win_in_topic(core):
    assert core.select_mode(user_signal="hello", topic="we win") == "spark_alive"


# ---------------------------------------------------------------------------
# ConversationCore.sanitize_for_voice
# ---------------------------------------------------------------------------

def test_sanitize_empty_string(core):
    assert core.sanitize_for_voice("") == ""


def test_sanitize_plain_text_unchanged(core):
    result = core.sanitize_for_voice("hello world")
    assert "hello world" in result


def test_sanitize_removes_terminal_escape(core):
    result = core.sanitize_for_voice(r"text \[\?9001h more")
    # The escape pattern should be removed
    assert "\\[\\?9001h" not in result


def test_sanitize_removes_windows_path(core):
    text = "path is C:\\\\Users\\\\john\\\\file.txt"
    result = core.sanitize_for_voice(text)
    # Windows path pattern should be removed
    assert "Users" not in result or "C:" not in result


def test_sanitize_removes_hex_hash(core):
    text = "commit abc1234def56789 was bad"
    result = core.sanitize_for_voice(text)
    assert "abc1234def56789" not in result


def test_sanitize_removes_syntax_error(core):
    text = "you got a SyntaxError in the file"
    result = core.sanitize_for_voice(text)
    assert "SyntaxError" not in result


def test_sanitize_removes_command_exited(core):
    text = "Command exited with code 1 during build"
    result = core.sanitize_for_voice(text)
    assert "Command exited with code" not in result


def test_sanitize_collapses_whitespace(core):
    result = core.sanitize_for_voice("hello   world  ")
    assert "  " not in result
    assert result == result.strip()


def test_sanitize_returns_string(core):
    assert isinstance(core.sanitize_for_voice("anything"), str)


# ---------------------------------------------------------------------------
# ConversationCore.should_suppress_voice
# ---------------------------------------------------------------------------

def test_should_suppress_empty_string(core):
    assert core.should_suppress_voice("") is True


def test_should_suppress_whitespace_only(core):
    assert core.should_suppress_voice("   ") is True


def test_should_suppress_clean_text_is_false(core):
    assert core.should_suppress_voice("let's ship the feature") is False


def test_should_suppress_one_pattern_is_false(core):
    # Only one pattern match → hits < 2 → not suppressed
    text = "you got a SyntaxError in your code"
    assert core.should_suppress_voice(text) is False


def test_should_suppress_two_patterns_is_true(core):
    # Two hits: SyntaxError + Command exited with code
    text = "SyntaxError raised. Command exited with code 1"
    assert core.should_suppress_voice(text) is True


def test_should_suppress_three_patterns_is_true(core):
    text = "SyntaxError: bad syntax. Command exited with code 2. abc1234def56789"
    assert core.should_suppress_voice(text) is True


# ---------------------------------------------------------------------------
# ConversationCore.score_reply
# ---------------------------------------------------------------------------

def _short_reply(n_words=10):
    return " ".join(["word"] * n_words)


def _long_reply(n_words=130):
    return " ".join(["word"] * n_words)


def test_score_reply_returns_conversation_score(core):
    s = core.score_reply(user_text="hello", reply_text="Hi there", mode="real_talk")
    assert isinstance(s, ConversationScore)


def test_score_reply_short_reply_naturalness_2(core):
    s = core.score_reply(user_text="hello", reply_text=_short_reply(10), mode="real_talk")
    assert s.naturalness == 2


def test_score_reply_long_reply_naturalness_1(core):
    s = core.score_reply(user_text="hello", reply_text=_long_reply(130), mode="real_talk")
    assert s.naturalness == 1


def test_score_reply_few_lines_clarity_2(core):
    reply = "\n".join(["line"] * 5)
    s = core.score_reply(user_text="hi", reply_text=reply, mode="real_talk")
    assert s.clarity == 2


def test_score_reply_many_lines_clarity_1(core):
    reply = "\n".join(["line"] * 20)
    s = core.score_reply(user_text="hi", reply_text=reply, mode="real_talk")
    assert s.clarity == 1


def test_score_reply_tone_match_correct_calm(core):
    s = core.score_reply(
        user_text="this is serious",
        reply_text=_short_reply(),
        mode="calm_focus",
    )
    assert s.tone_match == 2


def test_score_reply_tone_mismatch_serious_not_calm(core):
    s = core.score_reply(
        user_text="this is serious",
        reply_text=_short_reply(),
        mode="real_talk",  # not calm_focus
    )
    assert s.tone_match == 1


def test_score_reply_tone_mismatch_excited_but_calm(core):
    s = core.score_reply(
        user_text="I'm so excited and celebrate",
        reply_text=_short_reply(),
        mode="calm_focus",
    )
    assert s.tone_match == 1


def test_score_reply_clean_speech_2_for_clean_text(core):
    s = core.score_reply(user_text="hi", reply_text="Nice reply here", mode="real_talk")
    assert s.clean_speech == 2


def test_score_reply_clean_speech_0_for_suppressed_text(core):
    noisy = "SyntaxError raised. Command exited with code 1"
    s = core.score_reply(user_text="hi", reply_text=noisy, mode="real_talk")
    assert s.clean_speech == 0


def test_score_reply_no_fluff_brevity_2(core):
    s = core.score_reply(user_text="hi", reply_text="Here is a direct answer", mode="real_talk")
    assert s.brevity == 2


def test_score_reply_fluff_marker_brevity_1(core):
    s = core.score_reply(
        user_text="hi",
        reply_text="Great question! I'd be happy to help you.",
        mode="real_talk",
    )
    assert s.brevity == 1


def test_score_reply_absolutely_fluff(core):
    s = core.score_reply(
        user_text="hi",
        reply_text="Absolutely! That makes sense.",
        mode="real_talk",
    )
    assert s.brevity == 1


def test_score_reply_totally_fluff(core):
    s = core.score_reply(
        user_text="hi",
        reply_text="Totally agree with your point.",
        mode="real_talk",
    )
    assert s.brevity == 1


def test_score_reply_total_max_is_10(core):
    s = core.score_reply(user_text="hello", reply_text="Good work done here.", mode="real_talk")
    assert s.total <= 10


def test_score_reply_total_is_sum(core):
    s = core.score_reply(user_text="hello", reply_text="Good work done here.", mode="real_talk")
    expected = s.naturalness + s.clarity + s.tone_match + s.clean_speech + s.brevity
    assert s.total == expected


def test_score_reply_mode_spark_alive_no_penalty_for_calm_signal(core):
    s = core.score_reply(
        user_text="win and celebrate",
        reply_text=_short_reply(),
        mode="spark_alive",
    )
    # excited user + spark_alive mode → tone_match should be 2
    assert s.tone_match == 2


# ---------------------------------------------------------------------------
# NON_CONVERSATIONAL_PATTERNS – sanity check list
# ---------------------------------------------------------------------------

def test_non_conversational_patterns_is_list():
    assert isinstance(NON_CONVERSATIONAL_PATTERNS, list)


def test_non_conversational_patterns_not_empty():
    assert len(NON_CONVERSATIONAL_PATTERNS) > 0


def test_non_conversational_patterns_are_strings():
    for p in NON_CONVERSATIONAL_PATTERNS:
        assert isinstance(p, str)
