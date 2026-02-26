"""Tests for PR 1 config-authority migrations.

Covers: feature_flags, advisory_emitter, bridge_cycle (new keys),
advisor (env_overrides for replay/mind/retrieval/memory_emotion).
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tuneables(tmp_path: Path, sections: Dict[str, Any]) -> Path:
    """Write a minimal tuneables.json and return its path."""
    p = tmp_path / "tuneables.json"
    p.write_text(json.dumps(sections), encoding="utf-8")
    return p


def _make_baseline(tmp_path: Path, sections: Dict[str, Any]) -> Path:
    """Write a baseline config and return its path."""
    p = tmp_path / "baseline.json"
    p.write_text(json.dumps(sections), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# feature_flags
# ---------------------------------------------------------------------------

class TestFeatureFlags:

    def test_feature_flags_defaults(self, tmp_path, monkeypatch):
        """feature_flags resolves defaults when no config exists."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        for var in ("SPARK_PREMIUM_TOOLS", "SPARK_CHIPS_ENABLED", "SPARK_ADVISORY_DISABLE_CHIPS"):
            monkeypatch.delenv(var, raising=False)
        import lib.feature_flags as ff
        ff._load_feature_flags()
        assert ff.PREMIUM_TOOLS is False
        assert ff.CHIPS_ENABLED is False
        assert ff.ADVISORY_DISABLE_CHIPS is False

    def test_feature_flags_env_override(self, tmp_path, monkeypatch):
        """Env vars override file defaults."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("SPARK_PREMIUM_TOOLS", "1")
        monkeypatch.setenv("SPARK_CHIPS_ENABLED", "true")
        monkeypatch.setenv("SPARK_ADVISORY_DISABLE_CHIPS", "0")
        import lib.feature_flags as ff
        ff._load_feature_flags()
        assert ff.PREMIUM_TOOLS is True
        assert ff.CHIPS_ENABLED is True
        assert ff.ADVISORY_DISABLE_CHIPS is False

    def test_chips_active_requires_all_flags(self, tmp_path, monkeypatch):
        """chips_active() needs premium + chips - not disabled."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.feature_flags as ff
        monkeypatch.setenv("SPARK_PREMIUM_TOOLS", "1")
        monkeypatch.setenv("SPARK_CHIPS_ENABLED", "1")
        monkeypatch.setenv("SPARK_ADVISORY_DISABLE_CHIPS", "0")
        ff._load_feature_flags()
        assert ff.chips_active() is True
        # Disabling chips should make chips_active() false
        monkeypatch.setenv("SPARK_ADVISORY_DISABLE_CHIPS", "1")
        ff._load_feature_flags()
        assert ff.chips_active() is False


# ---------------------------------------------------------------------------
# advisory_emitter
# ---------------------------------------------------------------------------

class TestAdvisoryEmitter:

    def test_emitter_loads_defaults(self, tmp_path, monkeypatch):
        """Emitter falls back to schema defaults when no config."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        for var in ("SPARK_ADVISORY_EMIT", "SPARK_ADVISORY_MAX_CHARS", "SPARK_ADVISORY_FORMAT"):
            monkeypatch.delenv(var, raising=False)
        import lib.advisory_emitter as em
        em._load_emitter_config()
        assert em.EMIT_ENABLED is True
        assert em.MAX_EMIT_CHARS == 500
        assert em.FORMAT_STYLE == "inline"

    def test_emitter_env_override(self, tmp_path, monkeypatch):
        """Env vars override for emitter knobs."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("SPARK_ADVISORY_EMIT", "0")
        monkeypatch.setenv("SPARK_ADVISORY_MAX_CHARS", "200")
        monkeypatch.setenv("SPARK_ADVISORY_FORMAT", "block")
        import lib.advisory_emitter as em
        em._load_emitter_config()
        assert em.EMIT_ENABLED is False
        assert em.MAX_EMIT_CHARS == 200
        assert em.FORMAT_STYLE == "block"


# ---------------------------------------------------------------------------
# bridge_cycle — new keys
# ---------------------------------------------------------------------------

class TestBridgeCycleNewKeys:

    def test_bridge_new_keys_from_file(self, tmp_path, monkeypatch):
        """bridge_worker section keys are picked up from config file."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        for var in ("SPARK_OPENCLAW_NOTIFY", "SPARK_BRIDGE_STEP_TIMEOUT_S",
                     "SPARK_BRIDGE_DISABLE_TIMEOUTS", "SPARK_BRIDGE_GC_EVERY",
                     "SPARK_BRIDGE_STEP_EXECUTOR_WORKERS",
                     "SPARK_BRIDGE_MIND_SYNC_ENABLED", "SPARK_BRIDGE_MIND_SYNC_LIMIT",
                     "SPARK_BRIDGE_MIND_SYNC_MIN_READINESS", "SPARK_BRIDGE_MIND_SYNC_MIN_RELIABILITY",
                     "SPARK_BRIDGE_MIND_SYNC_MAX_AGE_S", "SPARK_BRIDGE_MIND_SYNC_DRAIN_QUEUE",
                     "SPARK_BRIDGE_MIND_SYNC_QUEUE_BUDGET"):
            monkeypatch.delenv(var, raising=False)
        spark_dir = tmp_path / ".spark"
        spark_dir.mkdir(parents=True, exist_ok=True)
        _make_tuneables(spark_dir, {
            "bridge_worker": {
                "openclaw_notify": False,
                "step_timeout_s": 90.0,
                "disable_timeouts": True,
                "gc_every": 5,
            }
        })
        import lib.bridge_cycle as bc
        bc._load_bridge_worker_config()
        assert bc.SPARK_OPENCLAW_NOTIFY is False
        assert bc.BRIDGE_STEP_TIMEOUT_S == 90.0
        assert bc.BRIDGE_DISABLE_TIMEOUTS is True
        assert bc._BRIDGE_GC_EVERY == 5

    def test_bridge_env_overrides_win(self, tmp_path, monkeypatch):
        """Env vars override file values for bridge keys."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        monkeypatch.setenv("SPARK_BRIDGE_STEP_TIMEOUT_S", "120")
        monkeypatch.setenv("SPARK_BRIDGE_GC_EVERY", "10")
        import lib.bridge_cycle as bc
        bc._load_bridge_worker_config()
        assert bc.BRIDGE_STEP_TIMEOUT_S == 120.0
        assert bc._BRIDGE_GC_EVERY == 10


# ---------------------------------------------------------------------------
# advisor — replay env_overrides
# ---------------------------------------------------------------------------

class TestAdvisorReplayEnvOverrides:

    def test_replay_env_overrides(self, tmp_path, monkeypatch):
        """Replay env vars flow through resolve_section env_overrides."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        spark_dir = tmp_path / ".spark"
        spark_dir.mkdir(parents=True, exist_ok=True)
        _make_tuneables(spark_dir, {"advisor": {}})
        monkeypatch.setenv("SPARK_TEST_ALLOW_HOME_TUNEABLES", "1")
        monkeypatch.setenv("SPARK_ADVISORY_REPLAY_ENABLED", "0")
        monkeypatch.setenv("SPARK_ADVISORY_REPLAY_MIN_STRICT", "10")
        import lib.advisor as adv
        adv._load_advisor_config()
        assert adv.REPLAY_ADVISORY_ENABLED is False
        assert adv.REPLAY_MODE == "off"
        assert adv.REPLAY_MIN_STRICT_SAMPLES == 10

    def test_mind_env_overrides(self, tmp_path, monkeypatch):
        """Mind bridge env vars flow through resolve_section env_overrides."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        spark_dir = tmp_path / ".spark"
        spark_dir.mkdir(parents=True, exist_ok=True)
        _make_tuneables(spark_dir, {"advisor": {}})
        monkeypatch.setenv("SPARK_TEST_ALLOW_HOME_TUNEABLES", "1")
        monkeypatch.setenv("SPARK_ADVISOR_MIND_MIN_SALIENCE", "0.75")
        monkeypatch.setenv("SPARK_ADVISOR_MIND_RESERVE_SLOTS", "3")
        import lib.advisor as adv
        adv._load_advisor_config()
        assert adv.MIND_MIN_SALIENCE == 0.75
        assert adv.MIND_RESERVE_SLOTS == 3


# ---------------------------------------------------------------------------
# Schema alignment
# ---------------------------------------------------------------------------

class TestSchemaAlignment:

    def test_feature_flags_in_schema(self):
        """feature_flags section exists in schema with correct keys."""
        from lib.tuneables_schema import SCHEMA
        assert "feature_flags" in SCHEMA
        ff = SCHEMA["feature_flags"]
        assert "premium_tools" in ff
        assert "chips_enabled" in ff
        assert "advisory_disable_chips" in ff

    def test_advisory_engine_emit_keys_in_schema(self):
        """advisory_engine section has emitter keys."""
        from lib.tuneables_schema import SCHEMA
        ae = SCHEMA["advisory_engine"]
        assert "emit_enabled" in ae
        assert "emit_max_chars" in ae
        assert "emit_format" in ae

    def test_bridge_worker_new_keys_in_schema(self):
        """bridge_worker section has new keys."""
        from lib.tuneables_schema import SCHEMA
        bw = SCHEMA["bridge_worker"]
        for key in ("openclaw_notify", "step_timeout_s", "disable_timeouts",
                     "gc_every", "step_executor_workers"):
            assert key in bw, f"Missing key: {key}"

    def test_retrieval_minimax_keys_in_schema(self):
        """retrieval section has minimax keys."""
        from lib.tuneables_schema import SCHEMA
        ret = SCHEMA["retrieval"]
        for key in ("minimax_fast_rerank", "minimax_fast_rerank_top_k",
                     "minimax_fast_rerank_min_items", "minimax_fast_rerank_timeout_s"):
            assert key in ret, f"Missing key: {key}"

    def test_section_consumers_complete(self):
        """SECTION_CONSUMERS lists new consumers."""
        from lib.tuneables_schema import SECTION_CONSUMERS
        assert "feature_flags" in SECTION_CONSUMERS
        assert "lib/feature_flags.py" in SECTION_CONSUMERS["feature_flags"]
        assert "lib/advisory_emitter.py" in SECTION_CONSUMERS["advisory_engine"]


# ---------------------------------------------------------------------------
# Config file alignment
# ---------------------------------------------------------------------------

class TestConfigFileAlignment:

    def test_config_has_feature_flags(self):
        """config/tuneables.json has feature_flags section."""
        config_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        assert "feature_flags" in data
        ff = data["feature_flags"]
        assert ff["premium_tools"] is False
        assert ff["chips_enabled"] is False

    def test_config_has_emitter_keys(self):
        """config/tuneables.json advisory_engine has emitter keys."""
        config_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        ae = data["advisory_engine"]
        assert "emit_enabled" in ae
        assert "emit_max_chars" in ae
        assert "emit_format" in ae

    def test_config_has_bridge_new_keys(self):
        """config/tuneables.json bridge_worker has new keys."""
        config_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        bw = data["bridge_worker"]
        for key in ("openclaw_notify", "step_timeout_s", "disable_timeouts",
                     "gc_every", "step_executor_workers"):
            assert key in bw, f"Missing key in config: {key}"
