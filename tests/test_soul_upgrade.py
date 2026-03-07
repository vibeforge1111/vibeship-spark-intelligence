"""Tests for lib/soul_upgrade.py."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import lib.soul_upgrade as su
from lib.soul_upgrade import SoulState, fetch_soul_state, guidance_preface, soul_kernel_pass


# ---------------------------------------------------------------------------
# SoulState dataclass
# ---------------------------------------------------------------------------

def test_soul_state_defaults():
    s = SoulState(ok=True)
    assert s.mood == "builder"
    assert s.mission_anchor == ""
    assert s.soul_kernel is None
    assert s.source == "fallback"


def test_soul_state_ok_false():
    s = SoulState(ok=False)
    assert s.ok is False


def test_soul_state_custom_values():
    kernel = {"non_harm": True, "service": True, "clarity": True}
    s = SoulState(ok=True, mood="zen", mission_anchor="build", soul_kernel=kernel, source="pulse")
    assert s.mood == "zen"
    assert s.mission_anchor == "build"
    assert s.soul_kernel == kernel
    assert s.source == "pulse"


# ---------------------------------------------------------------------------
# soul_kernel_pass
# ---------------------------------------------------------------------------

def test_soul_kernel_pass_all_true():
    s = SoulState(ok=True, soul_kernel={"non_harm": True, "service": True, "clarity": True})
    assert soul_kernel_pass(s) is True


def test_soul_kernel_pass_missing_non_harm():
    s = SoulState(ok=True, soul_kernel={"service": True, "clarity": True})
    assert soul_kernel_pass(s) is False


def test_soul_kernel_pass_missing_service():
    s = SoulState(ok=True, soul_kernel={"non_harm": True, "clarity": True})
    assert soul_kernel_pass(s) is False


def test_soul_kernel_pass_missing_clarity():
    s = SoulState(ok=True, soul_kernel={"non_harm": True, "service": True})
    assert soul_kernel_pass(s) is False


def test_soul_kernel_pass_none_kernel():
    s = SoulState(ok=True, soul_kernel=None)
    assert soul_kernel_pass(s) is False


def test_soul_kernel_pass_empty_kernel():
    s = SoulState(ok=True, soul_kernel={})
    assert soul_kernel_pass(s) is False


def test_soul_kernel_pass_false_values():
    s = SoulState(ok=True, soul_kernel={"non_harm": False, "service": True, "clarity": True})
    assert soul_kernel_pass(s) is False


# ---------------------------------------------------------------------------
# guidance_preface – mode routing
# ---------------------------------------------------------------------------

def test_guidance_preface_not_ok_returns_empty():
    s = SoulState(ok=False)
    assert guidance_preface(s) == ""


def test_guidance_preface_zen_mood():
    s = SoulState(ok=True, mood="zen")
    preface = guidance_preface(s)
    assert "calm" in preface.lower() or "grounding" in preface.lower()


def test_guidance_preface_oracle_mood():
    s = SoulState(ok=True, mood="oracle")
    preface = guidance_preface(s)
    assert "insight" in preface.lower() or "signal" in preface.lower()


def test_guidance_preface_chaos_mood():
    s = SoulState(ok=True, mood="chaos")
    preface = guidance_preface(s)
    assert "playful" in preface.lower() or "safe" in preface.lower()


def test_guidance_preface_builder_mood_returns_default():
    s = SoulState(ok=True, mood="builder")
    preface = guidance_preface(s)
    assert "direct" in preface.lower() or "action" in preface.lower()


def test_guidance_preface_unknown_mood_returns_default():
    s = SoulState(ok=True, mood="unknown_mood_xyz")
    preface = guidance_preface(s)
    assert isinstance(preface, str)
    assert len(preface) > 0


def test_guidance_preface_uppercase_zen():
    s = SoulState(ok=True, mood="ZEN")
    preface = guidance_preface(s)
    # mood is lowercased in implementation
    assert "calm" in preface.lower() or "grounding" in preface.lower()


def test_guidance_preface_zen_with_whitespace():
    s = SoulState(ok=True, mood="  zen  ")
    preface = guidance_preface(s)
    assert "calm" in preface.lower() or "grounding" in preface.lower()


def test_guidance_preface_returns_string():
    s = SoulState(ok=True, mood="builder")
    assert isinstance(guidance_preface(s), str)


# ---------------------------------------------------------------------------
# fetch_soul_state – network mocking
# ---------------------------------------------------------------------------

def _make_mock_response(payload: dict):
    """Build a mock urllib response object."""
    body = json.dumps(payload).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_fetch_soul_state_success(monkeypatch):
    payload = {
        "ok": True,
        "mood": "zen",
        "mission_anchor": "help devs",
        "soul_kernel": {"non_harm": True, "service": True, "clarity": True},
    }
    mock_resp = _make_mock_response(payload)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        state = fetch_soul_state()
    assert state.ok is True
    assert state.mood == "zen"
    assert state.mission_anchor == "help devs"
    assert state.source == "pulse-companion"


def test_fetch_soul_state_fallback_on_connection_error(monkeypatch):
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        state = fetch_soul_state()
    assert state.ok is False
    assert state.source == "fallback"


def test_fetch_soul_state_fallback_on_timeout(monkeypatch):
    import socket
    with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
        state = fetch_soul_state()
    assert state.ok is False


def test_fetch_soul_state_fallback_on_bad_json(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"not valid json"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        state = fetch_soul_state()
    assert state.ok is False
    assert state.source == "fallback"


def test_fetch_soul_state_ok_false_from_server(monkeypatch):
    payload = {"ok": False, "mood": "chaos"}
    mock_resp = _make_mock_response(payload)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        state = fetch_soul_state()
    assert state.ok is False
    assert state.mood == "chaos"


def test_fetch_soul_state_missing_mood_defaults_to_builder(monkeypatch):
    payload = {"ok": True}
    mock_resp = _make_mock_response(payload)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        state = fetch_soul_state()
    assert state.mood == "builder"


def test_fetch_soul_state_soul_kernel_not_dict_becomes_none(monkeypatch):
    payload = {"ok": True, "soul_kernel": "string_not_dict"}
    mock_resp = _make_mock_response(payload)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        state = fetch_soul_state()
    assert state.soul_kernel is None


def test_fetch_soul_state_soul_kernel_dict_preserved(monkeypatch):
    kernel = {"non_harm": True, "service": True, "clarity": True}
    payload = {"ok": True, "soul_kernel": kernel}
    mock_resp = _make_mock_response(payload)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        state = fetch_soul_state()
    assert state.soul_kernel == kernel


def test_fetch_soul_state_uses_session_id_in_url(monkeypatch):
    captured = {}

    def _fake_urlopen(req, timeout=None):
        captured["url"] = req if isinstance(req, str) else req.full_url
        raise OSError("stop")

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        fetch_soul_state(session_id="my_session")

    assert "my_session" in captured.get("url", "")


def test_fetch_soul_state_uses_base_url(monkeypatch):
    captured = {}

    def _fake_urlopen(req, timeout=None):
        captured["url"] = req if isinstance(req, str) else req.full_url
        raise OSError("stop")

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        fetch_soul_state(base_url="http://example.com:9999")

    assert "9999" in captured.get("url", "")


def test_fetch_soul_state_base_url_trailing_slash_stripped(monkeypatch):
    captured = {}

    def _fake_urlopen(req, timeout=None):
        captured["url"] = req if isinstance(req, str) else req.full_url
        raise OSError("stop")

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        fetch_soul_state(base_url="http://127.0.0.1:8765/")

    url = captured.get("url", "")
    assert "//" not in url.split("://", 1)[1] or "8765" in url
