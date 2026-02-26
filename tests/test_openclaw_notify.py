"""Tests for lib/openclaw_notify.py."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import lib.openclaw_notify as ocn
from lib.openclaw_notify import (
    _cleanup_notification_files,
    _get_gateway_token,
    _get_gateway_url,
    _update_notifications_md,
    _workspace_paths,
    notify_agent,
    wake_agent,
)


# ---------------------------------------------------------------------------
# _get_gateway_url
# ---------------------------------------------------------------------------

def test_get_gateway_url_default_port(monkeypatch):
    monkeypatch.setattr(ocn, "_read_openclaw_config", lambda: {})
    url = _get_gateway_url()
    assert "18789" in url
    assert url.startswith("http://127.0.0.1:")


def test_get_gateway_url_custom_port(monkeypatch):
    monkeypatch.setattr(ocn, "_read_openclaw_config", lambda: {"gateway": {"port": 9090}})
    url = _get_gateway_url()
    assert "9090" in url


def test_get_gateway_url_starts_with_http(monkeypatch):
    monkeypatch.setattr(ocn, "_read_openclaw_config", lambda: {})
    assert _get_gateway_url().startswith("http://")


# ---------------------------------------------------------------------------
# _get_gateway_token
# ---------------------------------------------------------------------------

def test_get_gateway_token_missing_returns_none(monkeypatch):
    monkeypatch.setattr(ocn, "_read_openclaw_config", lambda: {})
    assert _get_gateway_token() is None


def test_get_gateway_token_returns_value(monkeypatch):
    cfg = {"gateway": {"auth": {"token": "secret-abc"}}}
    monkeypatch.setattr(ocn, "_read_openclaw_config", lambda: cfg)
    assert _get_gateway_token() == "secret-abc"


def test_get_gateway_token_partial_config_returns_none(monkeypatch):
    monkeypatch.setattr(ocn, "_read_openclaw_config", lambda: {"gateway": {}})
    assert _get_gateway_token() is None


# ---------------------------------------------------------------------------
# _workspace_paths
# ---------------------------------------------------------------------------

def test_workspace_paths_uses_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
    result = _workspace_paths()
    assert result == [tmp_path]


def test_workspace_paths_openclaw_workspace_env(tmp_path, monkeypatch):
    monkeypatch.delenv("SPARK_OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    result = _workspace_paths()
    assert result == [tmp_path]


def test_workspace_paths_falls_back_to_discover(monkeypatch):
    monkeypatch.delenv("SPARK_OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.setattr(ocn, "discover_openclaw_workspaces", lambda **kw: [])
    result = _workspace_paths()
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# _update_notifications_md
# ---------------------------------------------------------------------------

def test_update_notifications_md_creates_file(tmp_path):
    md = tmp_path / "SPARK_NOTIFICATIONS.md"
    _update_notifications_md(md, "2026-02-22 10:00:00", "Test message")
    assert md.exists()


def test_update_notifications_md_contains_header(tmp_path):
    md = tmp_path / "SPARK_NOTIFICATIONS.md"
    _update_notifications_md(md, "2026-02-22 10:00:00", "hello")
    text = md.read_text(encoding="utf-8")
    assert "# Spark Notifications" in text


def test_update_notifications_md_contains_message(tmp_path):
    md = tmp_path / "SPARK_NOTIFICATIONS.md"
    _update_notifications_md(md, "2026-02-22 10:00:00", "critical alert")
    assert "critical alert" in md.read_text(encoding="utf-8")


def test_update_notifications_md_contains_timestamp(tmp_path):
    md = tmp_path / "SPARK_NOTIFICATIONS.md"
    _update_notifications_md(md, "2026-02-22 10:00:00", "msg")
    assert "2026-02-22 10:00:00" in md.read_text(encoding="utf-8")


def test_update_notifications_md_keeps_last_5(tmp_path):
    md = tmp_path / "SPARK_NOTIFICATIONS.md"
    for i in range(8):
        _update_notifications_md(md, f"2026-02-22 10:0{i}:00", f"message {i}")
    text = md.read_text(encoding="utf-8")
    entries = [l for l in text.splitlines() if l.startswith("- **")]
    assert len(entries) == 5


def test_update_notifications_md_appends_to_existing(tmp_path):
    md = tmp_path / "SPARK_NOTIFICATIONS.md"
    _update_notifications_md(md, "2026-02-22 10:00:00", "first")
    _update_notifications_md(md, "2026-02-22 10:01:00", "second")
    text = md.read_text(encoding="utf-8")
    assert "first" in text
    assert "second" in text


def test_update_notifications_md_creates_parent_dir(tmp_path):
    md = tmp_path / "sub" / "dir" / "SPARK_NOTIFICATIONS.md"
    _update_notifications_md(md, "2026-02-22 10:00:00", "msg")
    assert md.exists()


def test_update_notifications_md_entry_format(tmp_path):
    md = tmp_path / "SPARK_NOTIFICATIONS.md"
    _update_notifications_md(md, "2026-02-22 12:00:00", "test msg")
    text = md.read_text(encoding="utf-8")
    assert "- **2026-02-22 12:00:00** — test msg" in text


# ---------------------------------------------------------------------------
# _cleanup_notification_files
# ---------------------------------------------------------------------------

def test_cleanup_keeps_most_recent(tmp_path):
    for i in range(25):
        (tmp_path / f"notif_{i:04d}.json").write_text("{}", encoding="utf-8")
    _cleanup_notification_files(tmp_path, keep=20)
    remaining = list(tmp_path.glob("notif_*.json"))
    assert len(remaining) == 20


def test_cleanup_removes_oldest(tmp_path):
    for i in range(25):
        (tmp_path / f"notif_{i:04d}.json").write_text("{}", encoding="utf-8")
    _cleanup_notification_files(tmp_path, keep=20)
    # Oldest files (notif_0000 through notif_0004) should be removed
    assert not (tmp_path / "notif_0000.json").exists()


def test_cleanup_keeps_all_when_under_limit(tmp_path):
    for i in range(10):
        (tmp_path / f"notif_{i:04d}.json").write_text("{}", encoding="utf-8")
    _cleanup_notification_files(tmp_path, keep=20)
    assert len(list(tmp_path.glob("notif_*.json"))) == 10


def test_cleanup_empty_dir_no_error(tmp_path):
    _cleanup_notification_files(tmp_path, keep=20)  # should not raise


def test_cleanup_nonexistent_dir_no_error(tmp_path):
    _cleanup_notification_files(tmp_path / "no_such_dir", keep=20)


# ---------------------------------------------------------------------------
# notify_agent
# ---------------------------------------------------------------------------

def test_notify_agent_writes_json_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ocn, "_workspace_paths", lambda: [tmp_path])
    result = notify_agent("Hello world", priority="high")
    assert result is True
    notif_dir = tmp_path / "spark_notifications"
    files = list(notif_dir.glob("notif_*.json"))
    assert len(files) == 1


def test_notify_agent_json_contains_message(tmp_path, monkeypatch):
    monkeypatch.setattr(ocn, "_workspace_paths", lambda: [tmp_path])
    notify_agent("important finding")
    notif_dir = tmp_path / "spark_notifications"
    data = json.loads(list(notif_dir.glob("notif_*.json"))[0].read_text())
    assert data["message"] == "important finding"


def test_notify_agent_json_contains_priority(tmp_path, monkeypatch):
    monkeypatch.setattr(ocn, "_workspace_paths", lambda: [tmp_path])
    notify_agent("msg", priority="urgent")
    notif_dir = tmp_path / "spark_notifications"
    data = json.loads(list(notif_dir.glob("notif_*.json"))[0].read_text())
    assert data["priority"] == "urgent"


def test_notify_agent_json_contains_source(tmp_path, monkeypatch):
    monkeypatch.setattr(ocn, "_workspace_paths", lambda: [tmp_path])
    notify_agent("msg")
    notif_dir = tmp_path / "spark_notifications"
    data = json.loads(list(notif_dir.glob("notif_*.json"))[0].read_text())
    assert data["source"] == "spark_bridge"


def test_notify_agent_updates_md(tmp_path, monkeypatch):
    monkeypatch.setattr(ocn, "_workspace_paths", lambda: [tmp_path])
    notify_agent("md test")
    md = tmp_path / "SPARK_NOTIFICATIONS.md"
    assert md.exists()
    assert "md test" in md.read_text(encoding="utf-8")


def test_notify_agent_no_workspaces_returns_false(monkeypatch):
    monkeypatch.setattr(ocn, "_workspace_paths", lambda: [])
    result = notify_agent("msg")
    assert result is False


def test_notify_agent_returns_true_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(ocn, "_workspace_paths", lambda: [tmp_path])
    assert notify_agent("test") is True


def test_notify_agent_returns_false_on_exception(monkeypatch):
    def _bad_paths():
        raise OSError("boom")
    monkeypatch.setattr(ocn, "_workspace_paths", _bad_paths)
    assert notify_agent("msg") is False


# ---------------------------------------------------------------------------
# wake_agent
# ---------------------------------------------------------------------------

def test_wake_agent_returns_false_without_token(monkeypatch):
    monkeypatch.setattr(ocn, "_get_gateway_token", lambda: None)
    assert wake_agent("hello") is False


def test_wake_agent_calls_correct_endpoint(monkeypatch):
    monkeypatch.setattr(ocn, "_get_gateway_token", lambda: "tok")
    monkeypatch.setattr(ocn, "_get_gateway_url", lambda: "http://127.0.0.1:18789")
    captured = {}
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    def _fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.method
        return mock_resp
    with patch("urllib.request.urlopen", _fake_urlopen):
        wake_agent("test text")
    assert captured.get("url") == "http://127.0.0.1:18789/api/cron/wake"
    assert captured.get("method") == "POST"


def test_wake_agent_returns_true_on_200(monkeypatch):
    monkeypatch.setattr(ocn, "_get_gateway_token", lambda: "tok")
    monkeypatch.setattr(ocn, "_get_gateway_url", lambda: "http://127.0.0.1:18789")
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert wake_agent("text") is True


def test_wake_agent_returns_false_on_exception(monkeypatch):
    monkeypatch.setattr(ocn, "_get_gateway_token", lambda: "tok")
    monkeypatch.setattr(ocn, "_get_gateway_url", lambda: "http://127.0.0.1:18789")
    with patch("urllib.request.urlopen", side_effect=OSError("conn refused")):
        assert wake_agent("text") is False


def test_wake_agent_sends_bearer_auth(monkeypatch):
    monkeypatch.setattr(ocn, "_get_gateway_token", lambda: "my-secret")
    monkeypatch.setattr(ocn, "_get_gateway_url", lambda: "http://127.0.0.1:18789")
    captured = {}
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    def _fake_urlopen(req, timeout=None):
        captured["auth"] = req.get_header("Authorization")
        return mock_resp
    with patch("urllib.request.urlopen", _fake_urlopen):
        wake_agent("hi")
    assert captured.get("auth") == "Bearer my-secret"
