"""Tests for lib/clawdbot_memory_setup.py — 40 tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import lib.clawdbot_memory_setup as cms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_config() -> dict:
    return {"agents": {"defaults": {"memorySearch": {}}}}


def _write_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# _load_config
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_raises_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cms, "CONFIG_PATH", tmp_path / "nope.json")
        with pytest.raises(FileNotFoundError):
            cms._load_config()

    def test_loads_valid_config(self, tmp_path, monkeypatch):
        p = tmp_path / "cfg.json"
        _write_config(p, {"key": "value"})
        monkeypatch.setattr(cms, "CONFIG_PATH", p)
        cfg = cms._load_config()
        assert cfg["key"] == "value"

    def test_raises_on_corrupt_json(self, tmp_path, monkeypatch):
        p = tmp_path / "cfg.json"
        p.write_text("NOT JSON")
        monkeypatch.setattr(cms, "CONFIG_PATH", p)
        with pytest.raises(Exception):
            cms._load_config()


# ---------------------------------------------------------------------------
# _save_config
# ---------------------------------------------------------------------------

class TestSaveConfig:
    def test_writes_json_file(self, tmp_path, monkeypatch):
        p = tmp_path / "cfg.json"
        monkeypatch.setattr(cms, "CONFIG_PATH", p)
        cms._save_config({"hello": "world"})
        loaded = json.loads(p.read_text())
        assert loaded["hello"] == "world"

    def test_ends_with_newline(self, tmp_path, monkeypatch):
        p = tmp_path / "cfg.json"
        monkeypatch.setattr(cms, "CONFIG_PATH", p)
        cms._save_config({"x": 1})
        assert p.read_text().endswith("\n")


# ---------------------------------------------------------------------------
# _ensure_path
# ---------------------------------------------------------------------------

class TestEnsurePath:
    def test_creates_nested_path(self):
        cfg = {}
        result = cms._ensure_path(cfg, "a.b.c")
        cfg["a"]["b"]["c"]["test"] = True
        assert result == cfg["a"]["b"]["c"]

    def test_preserves_existing_dicts(self):
        cfg = {"a": {"existing": "data"}}
        cms._ensure_path(cfg, "a.b")
        assert cfg["a"]["existing"] == "data"

    def test_overwrites_non_dict_with_empty_dict(self):
        cfg = {"a": "not-a-dict"}
        cms._ensure_path(cfg, "a.b")
        assert isinstance(cfg["a"], dict)

    def test_single_level_path(self):
        cfg = {}
        cms._ensure_path(cfg, "level")
        assert "level" in cfg
        assert cfg["level"] == {}


# ---------------------------------------------------------------------------
# _restart_gateway
# ---------------------------------------------------------------------------

class TestRestartGateway:
    def test_no_op_when_bin_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cms, "CLAWDBOT_BIN", tmp_path / "nope_bin")
        with patch("subprocess.run") as mock_run:
            cms._restart_gateway()
        mock_run.assert_not_called()

    def test_calls_subprocess_when_bin_exists(self, tmp_path, monkeypatch):
        bin_path = tmp_path / "clawdbot"
        bin_path.write_text("#!/bin/sh")
        monkeypatch.setattr(cms, "CLAWDBOT_BIN", bin_path)
        with patch("subprocess.run") as mock_run:
            cms._restart_gateway()
        mock_run.assert_called_once()

    def test_subprocess_error_silently_ignored(self, tmp_path, monkeypatch):
        bin_path = tmp_path / "clawdbot"
        bin_path.write_text("#!/bin/sh")
        monkeypatch.setattr(cms, "CLAWDBOT_BIN", bin_path)
        with patch("subprocess.run", side_effect=OSError("fail")):
            cms._restart_gateway()  # Should not raise


# ---------------------------------------------------------------------------
# get_current_memory_search
# ---------------------------------------------------------------------------

class TestGetCurrentMemorySearch:
    def test_returns_memory_search_config(self, tmp_path, monkeypatch):
        cfg = {"agents": {"defaults": {"memorySearch": {"provider": "openai"}}}}
        p = tmp_path / "cfg.json"
        _write_config(p, cfg)
        monkeypatch.setattr(cms, "CONFIG_PATH", p)
        result = cms.get_current_memory_search()
        assert result["provider"] == "openai"

    def test_accepts_pre_loaded_cfg(self):
        cfg = {"agents": {"defaults": {"memorySearch": {"enabled": False}}}}
        result = cms.get_current_memory_search(cfg)
        assert result["enabled"] is False

    def test_returns_empty_dict_when_path_missing(self, tmp_path, monkeypatch):
        cfg = {}
        p = tmp_path / "cfg.json"
        _write_config(p, cfg)
        monkeypatch.setattr(cms, "CONFIG_PATH", p)
        result = cms.get_current_memory_search()
        assert result == {}


# ---------------------------------------------------------------------------
# apply_memory_mode
# ---------------------------------------------------------------------------

class TestApplyMemoryMode:
    def _make_cfg(self, tmp_path, monkeypatch):
        p = tmp_path / "cfg.json"
        _write_config(p, _base_config())
        monkeypatch.setattr(cms, "CONFIG_PATH", p)
        monkeypatch.setattr(cms, "CLAWDBOT_BIN", tmp_path / "nope_bin")
        return p

    def test_off_mode_disables_search(self, tmp_path, monkeypatch):
        self._make_cfg(tmp_path, monkeypatch)
        result = cms.apply_memory_mode("off", restart=False)
        assert result["enabled"] is False
        assert result["provider"] == "none"

    def test_local_mode_sets_provider(self, tmp_path, monkeypatch):
        self._make_cfg(tmp_path, monkeypatch)
        result = cms.apply_memory_mode("local", local_model_path="/models/gguf.bin", restart=False)
        assert result["provider"] == "local"
        assert result["local"]["modelPath"] == "/models/gguf.bin"

    def test_local_mode_requires_model_path(self, tmp_path, monkeypatch):
        self._make_cfg(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="local_model_path"):
            cms.apply_memory_mode("local", restart=False)

    def test_openai_mode_sets_defaults(self, tmp_path, monkeypatch):
        self._make_cfg(tmp_path, monkeypatch)
        result = cms.apply_memory_mode("openai", restart=False)
        assert result["provider"] == "openai"
        assert result["model"] == "text-embedding-3-small"

    def test_openai_mode_custom_model(self, tmp_path, monkeypatch):
        self._make_cfg(tmp_path, monkeypatch)
        result = cms.apply_memory_mode("openai", model="text-embedding-ada-002", restart=False)
        assert result["model"] == "text-embedding-ada-002"

    def test_gemini_mode_sets_defaults(self, tmp_path, monkeypatch):
        self._make_cfg(tmp_path, monkeypatch)
        result = cms.apply_memory_mode("gemini", restart=False)
        assert result["provider"] == "gemini"
        assert result["model"] == "gemini-embedding-001"

    def test_remote_mode_requires_base_url_and_key(self, tmp_path, monkeypatch):
        self._make_cfg(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="remote_base_url"):
            cms.apply_memory_mode("remote", restart=False)

    def test_remote_mode_sets_remote_section(self, tmp_path, monkeypatch):
        self._make_cfg(tmp_path, monkeypatch)
        result = cms.apply_memory_mode(
            "remote",
            remote_base_url="https://my.api/v1",
            remote_api_key="sk-abc",
            restart=False,
        )
        assert result["remote"]["baseUrl"] == "https://my.api/v1"
        assert result["remote"]["apiKey"] == "sk-abc"

    def test_unknown_mode_raises_value_error(self, tmp_path, monkeypatch):
        self._make_cfg(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="Unknown mode"):
            cms.apply_memory_mode("magic", restart=False)

    def test_config_persisted_to_disk(self, tmp_path, monkeypatch):
        p = self._make_cfg(tmp_path, monkeypatch)
        cms.apply_memory_mode("off", restart=False)
        saved = json.loads(p.read_text())
        ms = saved["agents"]["defaults"]["memorySearch"]
        assert ms["enabled"] is False

    def test_fallback_defaults_to_none_when_unset(self, tmp_path, monkeypatch):
        self._make_cfg(tmp_path, monkeypatch)
        result = cms.apply_memory_mode("openai", restart=False)
        assert result["fallback"] == "none"

    def test_custom_fallback_preserved(self, tmp_path, monkeypatch):
        self._make_cfg(tmp_path, monkeypatch)
        result = cms.apply_memory_mode("openai", fallback="local", restart=False)
        assert result["fallback"] == "local"

    def test_restart_not_called_when_bin_missing(self, tmp_path, monkeypatch):
        self._make_cfg(tmp_path, monkeypatch)
        with patch("subprocess.run") as mock_run:
            cms.apply_memory_mode("off", restart=True)
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# run_memory_status
# ---------------------------------------------------------------------------

class TestRunMemoryStatus:
    def test_returns_not_found_when_bin_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cms, "CLAWDBOT_BIN", tmp_path / "nope")
        result = cms.run_memory_status()
        assert "not found" in result

    def test_returns_output_on_success(self, tmp_path, monkeypatch):
        bin_path = tmp_path / "clawdbot"
        bin_path.write_text("#!/bin/sh")
        monkeypatch.setattr(cms, "CLAWDBOT_BIN", bin_path)
        with patch("subprocess.check_output", return_value="status ok"):
            result = cms.run_memory_status()
        assert result == "status ok"

    def test_returns_error_output_on_failure(self, tmp_path, monkeypatch):
        import subprocess
        bin_path = tmp_path / "clawdbot"
        bin_path.write_text("#!/bin/sh")
        monkeypatch.setattr(cms, "CLAWDBOT_BIN", bin_path)
        err = subprocess.CalledProcessError(1, "cmd", output="error output")
        with patch("subprocess.check_output", side_effect=err):
            result = cms.run_memory_status()
        assert "error output" in result


# ---------------------------------------------------------------------------
# recommended_modes
# ---------------------------------------------------------------------------

class TestRecommendedModes:
    def test_returns_all_five_modes(self):
        modes = cms.recommended_modes()
        assert set(modes.keys()) == {"off", "local", "remote", "openai", "gemini"}

    def test_each_mode_has_required_keys(self):
        for mode, info in cms.recommended_modes().items():
            for key in ("cost", "privacy", "setup"):
                assert key in info, f"Mode {mode} missing key {key}"

    def test_off_mode_is_free(self):
        assert cms.recommended_modes()["off"]["cost"] == "free"
