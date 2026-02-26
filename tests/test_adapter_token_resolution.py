from __future__ import annotations

from pathlib import Path

import pytest

from adapters import _common as adapter_common
from adapters import clawdbot_tailer, openclaw_tailer, stdin_ingest


def test_stdin_ingest_prefers_cli_token(monkeypatch, tmp_path: Path):
    token_file = tmp_path / "sparkd.token"
    token_file.write_text("file-token", encoding="utf-8")
    monkeypatch.setattr(adapter_common, "TOKEN_FILE", token_file)
    monkeypatch.setenv("SPARKD_TOKEN", "env-token")
    assert stdin_ingest._resolve_token("cli-token") == "cli-token"


def test_openclaw_tailer_uses_env_then_file(monkeypatch, tmp_path: Path):
    token_file = tmp_path / "sparkd.token"
    token_file.write_text("file-token", encoding="utf-8")
    monkeypatch.setattr(adapter_common, "TOKEN_FILE", token_file)

    monkeypatch.setenv("SPARKD_TOKEN", "env-token")
    assert openclaw_tailer._resolve_token(None) == "env-token"

    monkeypatch.delenv("SPARKD_TOKEN", raising=False)
    assert openclaw_tailer._resolve_token(None) == "file-token"


def test_clawdbot_tailer_returns_none_when_no_token(monkeypatch, tmp_path: Path):
    token_file = tmp_path / "sparkd.token"
    monkeypatch.setattr(adapter_common, "TOKEN_FILE", token_file)
    monkeypatch.delenv("SPARKD_TOKEN", raising=False)
    assert clawdbot_tailer._resolve_token(None) is None


def test_stdin_ingest_blocks_remote_sparkd_by_default():
    with pytest.raises(ValueError):
        stdin_ingest._normalize_sparkd_base_url("http://example.com", allow_remote=False)
    assert stdin_ingest._normalize_sparkd_base_url("http://example.com", allow_remote=True) == "http://example.com"


def test_openclaw_tailer_blocks_remote_sparkd_by_default():
    with pytest.raises(ValueError):
        openclaw_tailer._normalize_sparkd_base_url("https://evil.test", allow_remote=False)
    assert openclaw_tailer._normalize_sparkd_base_url("localhost:8787", allow_remote=False) == "http://localhost:8787"


def test_clawdbot_tailer_blocks_remote_sparkd_by_default():
    with pytest.raises(ValueError):
        clawdbot_tailer._normalize_sparkd_base_url("https://evil.test", allow_remote=False)
    assert clawdbot_tailer._normalize_sparkd_base_url("127.0.0.1:8787", allow_remote=False) == "http://127.0.0.1:8787"
