"""Tests for lib.llm_dispatch — central LLM area dispatch."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root on path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.llm_dispatch import (
    ALL_AREAS,
    ARCHITECTURE_AREAS,
    LEARNING_AREAS,
    LLMAreaResult,
    get_all_area_configs,
    get_area_config,
    llm_area_call,
)


# ── Registry tests ───────────────────────────────────────────────────────

class TestAreaRegistry:
    def test_learning_areas_count(self):
        assert len(LEARNING_AREAS) == 20

    def test_architecture_areas_count(self):
        assert len(ARCHITECTURE_AREAS) == 10

    def test_all_areas_count(self):
        assert len(ALL_AREAS) == 30

    def test_no_duplicates(self):
        assert len(set(ALL_AREAS)) == len(ALL_AREAS)

    def test_all_areas_is_union(self):
        assert set(ALL_AREAS) == set(LEARNING_AREAS) | set(ARCHITECTURE_AREAS)


# ── Config resolution tests ─────────────────────────────────────────────

class TestAreaConfig:
    def test_unknown_area_returns_defaults(self):
        cfg = get_area_config("nonexistent_area_xyz")
        assert cfg["enabled"] is False
        assert cfg["provider"] == "minimax"

    def test_known_area_returns_config(self):
        cfg = get_area_config("archive_rewrite")
        assert "enabled" in cfg
        assert "provider" in cfg
        assert "timeout_s" in cfg
        assert "max_chars" in cfg

    def test_all_configs_returns_all(self):
        configs = get_all_area_configs()
        assert len(configs) == 30
        for area_id in ALL_AREAS:
            assert area_id in configs

    def test_default_provider_is_valid(self):
        for area_id in ALL_AREAS:
            cfg = get_area_config(area_id)
            assert cfg["provider"] in {"auto", "minimax", "ollama", "gemini", "openai", "anthropic", "claude"}


# ── Dispatch tests ───────────────────────────────────────────────────────

class TestLLMAreaCall:
    def test_disabled_returns_fallback(self):
        """When area is disabled, return fallback immediately with no LLM call."""
        result = llm_area_call("archive_rewrite", "test prompt", fallback="original text")
        assert result.text == "original text"
        assert result.used_llm is False
        assert result.provider == "none"
        assert result.area_id == "archive_rewrite"
        assert result.latency_ms == 0.0

    def test_unknown_area_returns_fallback(self):
        result = llm_area_call("nonexistent_area", "test", fallback="fb")
        assert result.text == "fb"
        assert result.used_llm is False

    @patch("lib.llm_dispatch._load_area_config")
    @patch("lib.llm_dispatch._dispatch_provider")
    def test_enabled_calls_provider(self, mock_dispatch, mock_config):
        mock_config.return_value = {
            "enabled": True,
            "provider": "minimax",
            "timeout_s": 6.0,
            "max_chars": 300,
        }
        mock_dispatch.return_value = "improved statement"

        result = llm_area_call("archive_rewrite", "test prompt", fallback="original")
        assert result.text == "improved statement"
        assert result.used_llm is True
        assert result.provider == "minimax"
        mock_dispatch.assert_called_once_with("minimax", "test prompt", 6.0)

    @patch("lib.llm_dispatch._load_area_config")
    @patch("lib.llm_dispatch._dispatch_provider")
    def test_provider_returns_none_falls_back(self, mock_dispatch, mock_config):
        mock_config.return_value = {
            "enabled": True,
            "provider": "minimax",
            "timeout_s": 6.0,
            "max_chars": 300,
        }
        mock_dispatch.return_value = None

        result = llm_area_call("archive_rewrite", "test prompt", fallback="original")
        assert result.text == "original"
        assert result.used_llm is True  # LLM was called but returned empty

    @patch("lib.llm_dispatch._load_area_config")
    @patch("lib.llm_dispatch._dispatch_provider")
    def test_max_chars_truncation(self, mock_dispatch, mock_config):
        mock_config.return_value = {
            "enabled": True,
            "provider": "minimax",
            "timeout_s": 6.0,
            "max_chars": 20,
        }
        mock_dispatch.return_value = "this is a very long response that should be truncated"

        result = llm_area_call("archive_rewrite", "test", fallback="fb")
        assert len(result.text) <= 20

    @patch("lib.llm_dispatch._load_area_config")
    @patch("lib.llm_dispatch._dispatch_provider")
    def test_auto_provider_resolves_to_minimax(self, mock_dispatch, mock_config):
        mock_config.return_value = {
            "enabled": True,
            "provider": "auto",
            "timeout_s": 6.0,
            "max_chars": 300,
        }
        mock_dispatch.return_value = "result"

        result = llm_area_call("archive_rewrite", "test", fallback="fb")
        mock_dispatch.assert_called_once_with("minimax", "test", 6.0)

    def test_result_is_frozen_dataclass(self):
        result = llm_area_call("archive_rewrite", "test", fallback="fb")
        assert isinstance(result, LLMAreaResult)
        with pytest.raises(AttributeError):
            result.text = "new"  # frozen


# ── Prompt templates tests ───────────────────────────────────────────────

class TestPromptTemplates:
    def test_all_areas_have_prompts(self):
        from lib.llm_area_prompts import AREA_PROMPTS
        for area_id in ALL_AREAS:
            assert area_id in AREA_PROMPTS, f"Missing prompt for {area_id}"

    def test_each_prompt_has_system_and_template(self):
        from lib.llm_area_prompts import AREA_PROMPTS
        for area_id, prompts in AREA_PROMPTS.items():
            assert "system" in prompts, f"{area_id} missing system prompt"
            assert "template" in prompts, f"{area_id} missing template"
            assert len(prompts["system"]) > 10, f"{area_id} system prompt too short"
            assert len(prompts["template"]) > 10, f"{area_id} template too short"

    def test_format_prompt_safe(self):
        from lib.llm_area_prompts import format_prompt
        # Should not raise even with missing kwargs
        result = format_prompt("archive_rewrite")
        assert isinstance(result, str)

    def test_format_prompt_with_kwargs(self):
        from lib.llm_area_prompts import format_prompt
        result = format_prompt("archive_rewrite", statement="test", reason="too vague", score="3")
        assert "test" in result
        assert "too vague" in result


# ── Schema validation tests ──────────────────────────────────────────────

class TestSchemaIntegration:
    def test_tuneables_schema_has_llm_areas(self):
        from lib.tuneables_schema import SCHEMA
        assert "llm_areas" in SCHEMA

    def test_llm_areas_schema_has_all_keys(self):
        from lib.tuneables_schema import SCHEMA
        llm_schema = SCHEMA["llm_areas"]
        for area_id in ALL_AREAS:
            assert f"{area_id}_enabled" in llm_schema, f"Missing {area_id}_enabled"
            assert f"{area_id}_provider" in llm_schema, f"Missing {area_id}_provider"
            assert f"{area_id}_timeout_s" in llm_schema, f"Missing {area_id}_timeout_s"
            assert f"{area_id}_max_chars" in llm_schema, f"Missing {area_id}_max_chars"

    def test_config_json_has_llm_areas(self):
        config_path = ROOT / "config" / "tuneables.json"
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        assert "llm_areas" in data

    def test_config_json_validates(self):
        from lib.tuneables_schema import validate_tuneables
        config_path = ROOT / "config" / "tuneables.json"
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        result = validate_tuneables(data)
        # No errors for llm_areas keys
        llm_warnings = [w for w in result.warnings if "llm_areas" in w]
        assert len(llm_warnings) == 0, f"Schema warnings: {llm_warnings}"

    def test_section_consumers_includes_llm_areas(self):
        from lib.tuneables_schema import SECTION_CONSUMERS
        assert "llm_areas" in SECTION_CONSUMERS
