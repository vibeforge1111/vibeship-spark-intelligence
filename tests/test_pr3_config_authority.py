"""Tests for PR 3 config-authority migrations.

Covers: observe_hook (10 keys), eidos extended (5 keys), chips_runtime (10 keys).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tuneables(tmp_path: Path, sections: Dict[str, Any]) -> Path:
    p = tmp_path / "tuneables.json"
    p.write_text(json.dumps(sections), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# observe_hook
# ---------------------------------------------------------------------------

class TestObserveHookConfig:

    def test_observe_defaults(self, tmp_path, monkeypatch):
        """observe_hook resolves schema defaults when no config exists."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        for var in ("SPARK_EIDOS_ENABLED", "SPARK_OUTCOME_CHECKIN_MIN_S",
                     "SPARK_ADVICE_FEEDBACK", "SPARK_ADVICE_FEEDBACK_PROMPT",
                     "SPARK_ADVICE_FEEDBACK_MIN_S", "SPARK_OBSERVE_PRETOOL_BUDGET_MS",
                     "SPARK_EIDOS_ENFORCE_BLOCK", "SPARK_HOOK_PAYLOAD_TEXT_LIMIT",
                     "SPARK_OUTCOME_CHECKIN", "SPARK_OUTCOME_CHECKIN_PROMPT"):
            monkeypatch.delenv(var, raising=False)
        from lib.config_authority import resolve_section
        cfg = resolve_section("observe_hook").data
        assert cfg["eidos_enabled"] is True
        assert cfg["outcome_checkin_min_s"] == 1800
        assert cfg["pretool_budget_ms"] == 2500.0
        assert cfg["eidos_enforce_block"] is False
        assert cfg["outcome_checkin_enabled"] is False

    def test_observe_env_overrides(self, tmp_path, monkeypatch):
        """Env vars override observe_hook file values."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        monkeypatch.setenv("SPARK_EIDOS_ENABLED", "0")
        monkeypatch.setenv("SPARK_OBSERVE_PRETOOL_BUDGET_MS", "1000")
        monkeypatch.setenv("SPARK_OUTCOME_CHECKIN", "1")
        from lib.config_authority import resolve_section, env_bool, env_float
        cfg = resolve_section(
            "observe_hook",
            env_overrides={
                "eidos_enabled": env_bool("SPARK_EIDOS_ENABLED"),
                "pretool_budget_ms": env_float("SPARK_OBSERVE_PRETOOL_BUDGET_MS"),
                "outcome_checkin_enabled": env_bool("SPARK_OUTCOME_CHECKIN"),
            },
        ).data
        assert cfg["eidos_enabled"] is False
        assert cfg["pretool_budget_ms"] == 1000.0
        assert cfg["outcome_checkin_enabled"] is True


# ---------------------------------------------------------------------------
# eidos extended
# ---------------------------------------------------------------------------

class TestEidosExtendedConfig:

    def test_eidos_extended_defaults(self, tmp_path, monkeypatch):
        """Extended eidos keys have correct defaults."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        for var in ("SPARK_SAFETY_GUARDRAILS", "SPARK_SAFETY_ALLOW_SECRETS",
                     "SPARK_TRACE_STRICT", "SPARK_ENABLE_TOOL_DISTILLATION",
                     "SPARK_EIDOS_PROVIDER"):
            monkeypatch.delenv(var, raising=False)
        from lib.config_authority import resolve_section
        cfg = resolve_section("eidos").data
        assert cfg["safety_guardrails_enabled"] is True
        assert cfg["safety_allow_secrets"] is False
        assert cfg["trace_strict"] is False
        assert cfg["tool_distillation_enabled"] is True
        assert cfg["llm_provider"] == "minimax"

    def test_eidos_extended_env_overrides(self, tmp_path, monkeypatch):
        """Env vars override eidos extended keys."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        monkeypatch.setenv("SPARK_SAFETY_GUARDRAILS", "0")
        monkeypatch.setenv("SPARK_TRACE_STRICT", "1")
        monkeypatch.setenv("SPARK_EIDOS_PROVIDER", "ollama")
        from lib.config_authority import resolve_section, env_bool, env_str
        cfg = resolve_section(
            "eidos",
            env_overrides={
                "safety_guardrails_enabled": env_bool("SPARK_SAFETY_GUARDRAILS"),
                "trace_strict": env_bool("SPARK_TRACE_STRICT"),
                "llm_provider": env_str("SPARK_EIDOS_PROVIDER"),
            },
        ).data
        assert cfg["safety_guardrails_enabled"] is False
        assert cfg["trace_strict"] is True
        assert cfg["llm_provider"] == "ollama"

    def test_eidos_file_values(self, tmp_path, monkeypatch):
        """EIDOS extended keys read from config file."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        spark_dir = tmp_path / ".spark"
        spark_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", spark_dir / "tuneables.json")
        for var in ("SPARK_SAFETY_GUARDRAILS", "SPARK_TRACE_STRICT", "SPARK_EIDOS_PROVIDER"):
            monkeypatch.delenv(var, raising=False)
        _make_tuneables(spark_dir, {
            "eidos": {
                "safety_guardrails_enabled": False,
                "trace_strict": True,
                "llm_provider": "gemini",
            }
        })
        from lib.config_authority import resolve_section
        cfg = resolve_section("eidos").data
        assert cfg["safety_guardrails_enabled"] is False
        assert cfg["trace_strict"] is True
        assert cfg["llm_provider"] == "gemini"


# ---------------------------------------------------------------------------
# chips_runtime
# ---------------------------------------------------------------------------

class TestChipsRuntimeConfig:

    def test_chips_defaults(self, tmp_path, monkeypatch):
        """chips_runtime resolves schema defaults when no config exists."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        for var in ("SPARK_CHIP_OBSERVER_ONLY", "SPARK_CHIP_MIN_SCORE",
                     "SPARK_CHIP_MIN_CONFIDENCE", "SPARK_CHIP_GATE_MODE",
                     "SPARK_CHIP_MIN_LEARNING_EVIDENCE", "SPARK_CHIP_BLOCKED_IDS",
                     "SPARK_CHIP_TELEMETRY_OBSERVERS", "SPARK_CHIP_EVENT_ACTIVE_LIMIT",
                     "SPARK_CHIP_PREFERRED_FORMAT", "SPARK_CHIP_SCHEMA_VALIDATION"):
            monkeypatch.delenv(var, raising=False)
        from lib.config_authority import resolve_section
        cfg = resolve_section("chips_runtime").data
        assert cfg["observer_only"] is True
        assert cfg["min_score"] == pytest.approx(0.35)
        assert cfg["min_confidence"] == pytest.approx(0.7)
        assert cfg["gate_mode"] == "balanced"
        assert cfg["preferred_format"] == "multifile"
        assert cfg["schema_validation"] == "warn"

    def test_chips_env_overrides(self, tmp_path, monkeypatch):
        """Env vars override chips_runtime values."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        monkeypatch.setenv("SPARK_CHIP_MIN_SCORE", "0.5")
        monkeypatch.setenv("SPARK_CHIP_GATE_MODE", "strict")
        monkeypatch.setenv("SPARK_CHIP_EVENT_ACTIVE_LIMIT", "10")
        from lib.config_authority import resolve_section, env_float, env_str, env_int
        cfg = resolve_section(
            "chips_runtime",
            env_overrides={
                "min_score": env_float("SPARK_CHIP_MIN_SCORE"),
                "gate_mode": env_str("SPARK_CHIP_GATE_MODE"),
                "max_active_per_event": env_int("SPARK_CHIP_EVENT_ACTIVE_LIMIT"),
            },
        ).data
        assert cfg["min_score"] == pytest.approx(0.5)
        assert cfg["gate_mode"] == "strict"
        assert cfg["max_active_per_event"] == 10


# ---------------------------------------------------------------------------
# Schema alignment
# ---------------------------------------------------------------------------

class TestPR3SchemaAlignment:

    def test_observe_hook_in_schema(self):
        from lib.tuneables_schema import SCHEMA
        assert "observe_hook" in SCHEMA
        oh = SCHEMA["observe_hook"]
        for key in ("eidos_enabled", "outcome_checkin_min_s", "advice_feedback_enabled",
                     "advice_feedback_prompt", "advice_feedback_min_s", "pretool_budget_ms",
                     "eidos_enforce_block", "hook_payload_text_limit",
                     "outcome_checkin_enabled", "outcome_checkin_prompt"):
            assert key in oh, f"Missing key: {key}"

    def test_eidos_extended_keys_in_schema(self):
        from lib.tuneables_schema import SCHEMA
        eidos = SCHEMA["eidos"]
        for key in ("safety_guardrails_enabled", "safety_allow_secrets",
                     "trace_strict", "tool_distillation_enabled", "llm_provider"):
            assert key in eidos, f"Missing key: {key}"

    def test_chips_runtime_in_schema(self):
        from lib.tuneables_schema import SCHEMA
        assert "chips_runtime" in SCHEMA
        cr = SCHEMA["chips_runtime"]
        for key in ("observer_only", "min_score", "min_confidence", "gate_mode",
                     "min_learning_evidence", "blocked_ids", "telemetry_observer_blocklist",
                     "max_active_per_event", "preferred_format", "schema_validation"):
            assert key in cr, f"Missing key: {key}"

    def test_section_consumers_updated(self):
        from lib.tuneables_schema import SECTION_CONSUMERS
        assert "observe_hook" in SECTION_CONSUMERS
        assert "hooks/observe.py" in SECTION_CONSUMERS["observe_hook"]
        assert "chips_runtime" in SECTION_CONSUMERS
        assert "lib/chips/runtime.py" in SECTION_CONSUMERS["chips_runtime"]
        # eidos extended consumers
        eidos_consumers = SECTION_CONSUMERS["eidos"]
        assert "lib/eidos/guardrails.py" in eidos_consumers
        assert "lib/llm.py" in eidos_consumers


# ---------------------------------------------------------------------------
# Config file alignment
# ---------------------------------------------------------------------------

class TestPR3ConfigFileAlignment:

    def test_config_has_observe_hook(self):
        config_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        assert "observe_hook" in data
        oh = data["observe_hook"]
        assert oh["eidos_enabled"] is True
        assert oh["pretool_budget_ms"] == 2500.0

    def test_config_has_eidos_extended(self):
        config_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        eidos = data["eidos"]
        assert "safety_guardrails_enabled" in eidos
        assert "trace_strict" in eidos
        assert "llm_provider" in eidos

    def test_config_has_chips_runtime(self):
        config_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        assert "chips_runtime" in data
        cr = data["chips_runtime"]
        assert cr["observer_only"] is True
        assert cr["gate_mode"] == "balanced"
        assert cr["schema_validation"] == "warn"
