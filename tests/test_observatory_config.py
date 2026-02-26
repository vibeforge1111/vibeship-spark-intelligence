"""Tests for lib/observatory/config.py

Covers:
- ObservatoryConfig: dataclass field defaults
- load_config(): returns defaults when no tuneables file exists,
  loads all fields from observatory section, falls back to defaults
  for missing keys, handles invalid JSON gracefully, handles missing
  observatory section, coerces numeric fields via int()
- spark_dir(): returns a Path pointing to ~/.spark
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.observatory.config as obs_cfg
from lib.observatory.config import ObservatoryConfig, load_config, spark_dir


# ---------------------------------------------------------------------------
# ObservatoryConfig — dataclass defaults
# ---------------------------------------------------------------------------

def test_observatory_config_default_enabled():
    assert ObservatoryConfig().enabled is True


def test_observatory_config_default_auto_sync():
    assert ObservatoryConfig().auto_sync is True


def test_observatory_config_default_sync_cooldown():
    assert ObservatoryConfig().sync_cooldown_s == 120


def test_observatory_config_default_generate_canvas():
    assert ObservatoryConfig().generate_canvas is True


def test_observatory_config_default_max_recent_items():
    assert ObservatoryConfig().max_recent_items == 20


def test_observatory_config_default_vault_dir_is_string():
    assert isinstance(ObservatoryConfig().vault_dir, str)


def test_observatory_config_default_vault_dir_nonempty():
    assert ObservatoryConfig().vault_dir != ""


def test_observatory_config_custom_values():
    cfg = ObservatoryConfig(
        enabled=False,
        auto_sync=False,
        sync_cooldown_s=60,
        vault_dir="/tmp/vault",
        generate_canvas=False,
        max_recent_items=5,
    )
    assert cfg.enabled is False
    assert cfg.auto_sync is False
    assert cfg.sync_cooldown_s == 60
    assert cfg.vault_dir == "/tmp/vault"
    assert cfg.generate_canvas is False
    assert cfg.max_recent_items == 5


# ---------------------------------------------------------------------------
# load_config() — no tuneables file → all defaults
# ---------------------------------------------------------------------------

def test_load_config_no_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(obs_cfg, "_SPARK_DIR", tmp_path / "nonexistent")
    # Point the versioned config path somewhere that doesn't exist too
    monkeypatch.setattr(obs_cfg, "_DEFAULT_VAULT", "/default/vault")

    result = load_config()

    assert isinstance(result, ObservatoryConfig)
    assert result.enabled is True
    assert result.auto_sync is True
    assert result.sync_cooldown_s == 120
    assert result.generate_canvas is True
    assert result.max_recent_items == 20


# ---------------------------------------------------------------------------
# load_config() — reads all fields from tuneables.json
# ---------------------------------------------------------------------------

def test_load_config_reads_all_fields(tmp_path, monkeypatch):
    spark_dir_path = tmp_path / ".spark"
    spark_dir_path.mkdir()
    tuneables = spark_dir_path / "tuneables.json"
    tuneables.write_text(json.dumps({
        "observatory": {
            "enabled": False,
            "auto_sync": False,
            "sync_cooldown_s": 300,
            "vault_dir": "/my/vault",
            "generate_canvas": False,
            "max_recent_items": 50,
        }
    }), encoding="utf-8")
    monkeypatch.setattr(obs_cfg, "_SPARK_DIR", spark_dir_path)

    result = load_config()

    assert result.enabled is False
    assert result.auto_sync is False
    assert result.sync_cooldown_s == 300
    assert result.vault_dir == "/my/vault"
    assert result.generate_canvas is False
    assert result.max_recent_items == 50


def test_load_config_enabled_false(tmp_path, monkeypatch):
    spark_dir_path = tmp_path / ".spark"
    spark_dir_path.mkdir()
    (spark_dir_path / "tuneables.json").write_text(
        json.dumps({"observatory": {"enabled": False}}), encoding="utf-8"
    )
    monkeypatch.setattr(obs_cfg, "_SPARK_DIR", spark_dir_path)

    assert load_config().enabled is False


def test_load_config_custom_vault_dir(tmp_path, monkeypatch):
    spark_dir_path = tmp_path / ".spark"
    spark_dir_path.mkdir()
    (spark_dir_path / "tuneables.json").write_text(
        json.dumps({"observatory": {"vault_dir": "/custom/vault"}}), encoding="utf-8"
    )
    monkeypatch.setattr(obs_cfg, "_SPARK_DIR", spark_dir_path)

    assert load_config().vault_dir == "/custom/vault"


def test_load_config_sync_cooldown_coerced_to_int(tmp_path, monkeypatch):
    spark_dir_path = tmp_path / ".spark"
    spark_dir_path.mkdir()
    # Write sync_cooldown_s as a float string — should still work via int()
    (spark_dir_path / "tuneables.json").write_text(
        json.dumps({"observatory": {"sync_cooldown_s": "240"}}), encoding="utf-8"
    )
    monkeypatch.setattr(obs_cfg, "_SPARK_DIR", spark_dir_path)

    result = load_config()
    assert result.sync_cooldown_s == 240
    assert isinstance(result.sync_cooldown_s, int)


def test_load_config_max_recent_items_coerced_to_int(tmp_path, monkeypatch):
    spark_dir_path = tmp_path / ".spark"
    spark_dir_path.mkdir()
    (spark_dir_path / "tuneables.json").write_text(
        json.dumps({"observatory": {"max_recent_items": "10"}}), encoding="utf-8"
    )
    monkeypatch.setattr(obs_cfg, "_SPARK_DIR", spark_dir_path)

    result = load_config()
    assert result.max_recent_items == 10
    assert isinstance(result.max_recent_items, int)


# ---------------------------------------------------------------------------
# load_config() — missing observatory section → defaults
# ---------------------------------------------------------------------------

def test_load_config_missing_observatory_section_returns_defaults(tmp_path, monkeypatch):
    spark_dir_path = tmp_path / ".spark"
    spark_dir_path.mkdir()
    (spark_dir_path / "tuneables.json").write_text(
        json.dumps({"values": {"min_occurrences": 1}}), encoding="utf-8"
    )
    monkeypatch.setattr(obs_cfg, "_SPARK_DIR", spark_dir_path)

    result = load_config()
    assert result.enabled is True
    assert result.sync_cooldown_s == 120


def test_load_config_empty_observatory_section_returns_defaults(tmp_path, monkeypatch):
    spark_dir_path = tmp_path / ".spark"
    spark_dir_path.mkdir()
    # Empty dict is falsy → treated as missing section
    (spark_dir_path / "tuneables.json").write_text(
        json.dumps({"observatory": {}}), encoding="utf-8"
    )
    monkeypatch.setattr(obs_cfg, "_SPARK_DIR", spark_dir_path)

    result = load_config()
    assert result.enabled is True


# ---------------------------------------------------------------------------
# load_config() — bad JSON → falls through to defaults
# ---------------------------------------------------------------------------

def test_load_config_bad_json_returns_defaults(tmp_path, monkeypatch):
    spark_dir_path = tmp_path / ".spark"
    spark_dir_path.mkdir()
    (spark_dir_path / "tuneables.json").write_text("not json at all", encoding="utf-8")
    monkeypatch.setattr(obs_cfg, "_SPARK_DIR", spark_dir_path)

    result = load_config()
    assert isinstance(result, ObservatoryConfig)
    assert result.enabled is True


def test_load_config_bom_safe(tmp_path, monkeypatch):
    spark_dir_path = tmp_path / ".spark"
    spark_dir_path.mkdir()
    content = json.dumps({"observatory": {"enabled": False, "max_recent_items": 7}})
    (spark_dir_path / "tuneables.json").write_bytes(
        b"\xef\xbb\xbf" + content.encode("utf-8")
    )
    monkeypatch.setattr(obs_cfg, "_SPARK_DIR", spark_dir_path)

    result = load_config()
    assert result.enabled is False
    assert result.max_recent_items == 7


# ---------------------------------------------------------------------------
# load_config() — partial section uses defaults for missing keys
# ---------------------------------------------------------------------------

def test_load_config_partial_section_keeps_defaults_for_missing(tmp_path, monkeypatch):
    spark_dir_path = tmp_path / ".spark"
    spark_dir_path.mkdir()
    # Only override one key; the rest should come from ObservatoryConfig defaults
    (spark_dir_path / "tuneables.json").write_text(
        json.dumps({"observatory": {"max_recent_items": 99}}), encoding="utf-8"
    )
    monkeypatch.setattr(obs_cfg, "_SPARK_DIR", spark_dir_path)

    result = load_config()
    assert result.max_recent_items == 99
    assert result.enabled is True       # default
    assert result.sync_cooldown_s == 120  # default


# ---------------------------------------------------------------------------
# load_config() — returns ObservatoryConfig instance in all paths
# ---------------------------------------------------------------------------

def test_load_config_always_returns_observatory_config(tmp_path, monkeypatch):
    monkeypatch.setattr(obs_cfg, "_SPARK_DIR", tmp_path / "none")
    assert isinstance(load_config(), ObservatoryConfig)


# ---------------------------------------------------------------------------
# spark_dir()
# ---------------------------------------------------------------------------

def test_spark_dir_returns_path():
    assert isinstance(spark_dir(), Path)


def test_spark_dir_ends_with_spark():
    assert spark_dir().name == ".spark"


def test_spark_dir_is_under_home():
    assert str(Path.home()) in str(spark_dir())
