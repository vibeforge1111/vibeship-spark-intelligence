"""Tests for lib.taste_api."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

import lib.taste_api as ta


# ---------------------------------------------------------------------------
# Helper: fake TasteItem returned by add_item mock
# ---------------------------------------------------------------------------

def _fake_item(**fields) -> Any:
    ns = SimpleNamespace(**fields)
    ns.to_dict = lambda: dict(fields)
    return ns


# ---------------------------------------------------------------------------
# Missing domain / source → error response
# ---------------------------------------------------------------------------

def test_missing_domain_returns_error(monkeypatch):
    monkeypatch.setattr(ta, "add_item", MagicMock())
    result = ta.add_from_dashboard({"source": "twitter", "notes": "n"})
    assert result == {"ok": False, "error": "missing_domain_or_source"}
    ta.add_item.assert_not_called()


def test_missing_source_returns_error(monkeypatch):
    monkeypatch.setattr(ta, "add_item", MagicMock())
    result = ta.add_from_dashboard({"domain": "finance"})
    assert result == {"ok": False, "error": "missing_domain_or_source"}
    ta.add_item.assert_not_called()


def test_empty_domain_string_returns_error(monkeypatch):
    monkeypatch.setattr(ta, "add_item", MagicMock())
    result = ta.add_from_dashboard({"domain": "   ", "source": "x"})
    assert result["ok"] is False


def test_empty_source_string_returns_error(monkeypatch):
    monkeypatch.setattr(ta, "add_item", MagicMock())
    result = ta.add_from_dashboard({"domain": "finance", "source": "  "})
    assert result["ok"] is False


def test_none_domain_returns_error(monkeypatch):
    monkeypatch.setattr(ta, "add_item", MagicMock())
    result = ta.add_from_dashboard({"domain": None, "source": "x"})
    assert result["ok"] is False


def test_none_source_returns_error(monkeypatch):
    monkeypatch.setattr(ta, "add_item", MagicMock())
    result = ta.add_from_dashboard({"domain": "finance", "source": None})
    assert result["ok"] is False


def test_empty_payload_returns_error(monkeypatch):
    monkeypatch.setattr(ta, "add_item", MagicMock())
    result = ta.add_from_dashboard({})
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# Valid payload → success
# ---------------------------------------------------------------------------

def test_valid_payload_returns_ok(monkeypatch):
    item = _fake_item(domain="finance", source="twitter", notes="", label="")
    monkeypatch.setattr(ta, "add_item", MagicMock(return_value=item))
    result = ta.add_from_dashboard({"domain": "finance", "source": "twitter"})
    assert result["ok"] is True


def test_valid_payload_contains_item(monkeypatch):
    item = _fake_item(domain="tech", source="rss", notes="note", label="lbl")
    monkeypatch.setattr(ta, "add_item", MagicMock(return_value=item))
    result = ta.add_from_dashboard({"domain": "tech", "source": "rss",
                                    "notes": "note", "label": "lbl"})
    assert result["item"] == {"domain": "tech", "source": "rss",
                              "notes": "note", "label": "lbl"}


def test_add_item_called_with_stripped_values(monkeypatch):
    item = _fake_item(domain="fin", source="tw", notes="", label="")
    mock = MagicMock(return_value=item)
    monkeypatch.setattr(ta, "add_item", mock)
    ta.add_from_dashboard({"domain": "  fin  ", "source": "  tw  "})
    mock.assert_called_once_with(domain="fin", source="tw", notes="", label="")


def test_notes_optional_defaults_empty(monkeypatch):
    item = _fake_item(domain="d", source="s", notes="", label="")
    mock = MagicMock(return_value=item)
    monkeypatch.setattr(ta, "add_item", mock)
    ta.add_from_dashboard({"domain": "d", "source": "s"})
    _, kwargs = mock.call_args
    assert kwargs["notes"] == ""


def test_label_optional_defaults_empty(monkeypatch):
    item = _fake_item(domain="d", source="s", notes="", label="")
    mock = MagicMock(return_value=item)
    monkeypatch.setattr(ta, "add_item", mock)
    ta.add_from_dashboard({"domain": "d", "source": "s"})
    _, kwargs = mock.call_args
    assert kwargs["label"] == ""


def test_notes_and_label_passed_through(monkeypatch):
    item = _fake_item(domain="d", source="s", notes="n", label="l")
    mock = MagicMock(return_value=item)
    monkeypatch.setattr(ta, "add_item", mock)
    ta.add_from_dashboard({"domain": "d", "source": "s", "notes": "n", "label": "l"})
    _, kwargs = mock.call_args
    assert kwargs["notes"] == "n"
    assert kwargs["label"] == "l"


def test_whitespace_only_notes_stripped(monkeypatch):
    item = _fake_item(domain="d", source="s", notes="", label="")
    mock = MagicMock(return_value=item)
    monkeypatch.setattr(ta, "add_item", mock)
    ta.add_from_dashboard({"domain": "d", "source": "s", "notes": "  "})
    _, kwargs = mock.call_args
    assert kwargs["notes"] == ""
