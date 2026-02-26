"""Config-authority tests for PR 4: small modules sweep.

Covers: memory_deltas, orchestration, feature_gates, flow (env override),
bridge_worker (context slots), and schema/config alignment.
"""

import json
import os
from pathlib import Path
from unittest import mock

import pytest


# --------------- helpers ---------------

def _resolve(section, env_overrides=None, runtime_path=None):
    import lib.config_authority as ca
    if runtime_path is None:
        runtime_path = Path(__file__).resolve().parent / "_nonexistent_runtime.json"
    old = ca.DEFAULT_RUNTIME_PATH
    ca.DEFAULT_RUNTIME_PATH = runtime_path
    try:
        return ca.resolve_section(section, env_overrides=env_overrides)
    finally:
        ca.DEFAULT_RUNTIME_PATH = old


# --------------- memory_deltas ---------------

class TestMemoryDeltasConfig:
    def test_defaults(self):
        r = _resolve("memory_deltas")
        assert r.data["patchified_enabled"] is False
        assert r.data["deltas_enabled"] is False
        assert r.data["delta_min_similarity"] == pytest.approx(0.86)
        assert r.data["patch_max_chars"] == 600
        assert r.data["patch_min_chars"] == 120

    def test_env_overrides(self):
        from lib.config_authority import env_bool, env_float, env_int
        with mock.patch.dict(os.environ, {
            "SPARK_MEMORY_PATCHIFIED": "1",
            "SPARK_MEMORY_DELTAS": "1",
            "SPARK_MEMORY_DELTA_MIN_SIM": "0.92",
            "SPARK_MEMORY_PATCH_MAX_CHARS": "800",
            "SPARK_MEMORY_PATCH_MIN_CHARS": "200",
        }):
            r = _resolve("memory_deltas", env_overrides={
                "patchified_enabled": env_bool("SPARK_MEMORY_PATCHIFIED"),
                "deltas_enabled": env_bool("SPARK_MEMORY_DELTAS"),
                "delta_min_similarity": env_float("SPARK_MEMORY_DELTA_MIN_SIM"),
                "patch_max_chars": env_int("SPARK_MEMORY_PATCH_MAX_CHARS"),
                "patch_min_chars": env_int("SPARK_MEMORY_PATCH_MIN_CHARS"),
            })
        assert r.data["patchified_enabled"] is True
        assert r.data["deltas_enabled"] is True
        assert r.data["delta_min_similarity"] == pytest.approx(0.92)
        assert r.data["patch_max_chars"] == 800
        assert r.data["patch_min_chars"] == 200

    def test_file_values(self, tmp_path):
        cfg = {"memory_deltas": {"patchified_enabled": True, "patch_max_chars": 900}}
        rt = tmp_path / "tuneables.json"
        rt.write_text(json.dumps(cfg))
        r = _resolve("memory_deltas", runtime_path=rt)
        assert r.data["patchified_enabled"] is True
        assert r.data["patch_max_chars"] == 900
        # others fall back to defaults
        assert r.data["deltas_enabled"] is False


# --------------- orchestration ---------------

class TestOrchestrationConfig:
    def test_defaults(self):
        r = _resolve("orchestration")
        assert r.data["inject_enabled"] is False
        assert r.data["context_max_chars"] == 1200
        assert r.data["context_item_limit"] == 3

    def test_env_overrides(self):
        from lib.config_authority import env_bool, env_int
        with mock.patch.dict(os.environ, {
            "SPARK_AGENT_INJECT": "1",
            "SPARK_AGENT_CONTEXT_MAX_CHARS": "2000",
            "SPARK_AGENT_CONTEXT_ITEM_LIMIT": "5",
        }):
            r = _resolve("orchestration", env_overrides={
                "inject_enabled": env_bool("SPARK_AGENT_INJECT"),
                "context_max_chars": env_int("SPARK_AGENT_CONTEXT_MAX_CHARS"),
                "context_item_limit": env_int("SPARK_AGENT_CONTEXT_ITEM_LIMIT"),
            })
        assert r.data["inject_enabled"] is True
        assert r.data["context_max_chars"] == 2000
        assert r.data["context_item_limit"] == 5


# --------------- feature_gates ---------------

class TestFeatureGatesConfig:
    def test_defaults(self):
        r = _resolve("feature_gates")
        assert r.data["personality_evolution"] is False
        assert r.data["personality_observer"] is False
        assert r.data["outcome_predictor"] is False
        assert r.data["cognitive_emotion_capture"] is True
        assert r.data["learning_bridge"] is True

    def test_env_overrides(self):
        from lib.config_authority import env_bool
        with mock.patch.dict(os.environ, {
            "SPARK_PERSONALITY_EVOLUTION_V1": "1",
            "SPARK_OUTCOME_PREDICTOR": "1",
            "SPARK_COGNITIVE_EMOTION_CAPTURE": "0",
            "SPARK_LEARNING_BRIDGE_ENABLED": "0",
        }):
            r = _resolve("feature_gates", env_overrides={
                "personality_evolution": env_bool("SPARK_PERSONALITY_EVOLUTION_V1"),
                "outcome_predictor": env_bool("SPARK_OUTCOME_PREDICTOR"),
                "cognitive_emotion_capture": env_bool("SPARK_COGNITIVE_EMOTION_CAPTURE"),
                "learning_bridge": env_bool("SPARK_LEARNING_BRIDGE_ENABLED"),
            })
        assert r.data["personality_evolution"] is True
        assert r.data["outcome_predictor"] is True
        assert r.data["cognitive_emotion_capture"] is False
        assert r.data["learning_bridge"] is False


# --------------- flow env override ---------------

class TestFlowEnvOverride:
    def test_validate_and_store_env_override(self):
        from lib.config_authority import env_bool
        with mock.patch.dict(os.environ, {"SPARK_VALIDATE_AND_STORE": "0"}):
            r = _resolve("flow", env_overrides={
                "validate_and_store_enabled": env_bool("SPARK_VALIDATE_AND_STORE"),
            })
        assert r.data["validate_and_store_enabled"] is False


# --------------- bridge_worker context slots ---------------

class TestBridgeWorkerContextSlots:
    def test_defaults(self):
        r = _resolve("bridge_worker")
        assert r.data["context_mind_reserved_slots"] == 1
        assert r.data["context_advisor_include_mind"] is True

    def test_env_overrides(self):
        from lib.config_authority import env_int, env_bool
        with mock.patch.dict(os.environ, {
            "SPARK_CONTEXT_MIND_RESERVED_SLOTS": "3",
            "SPARK_CONTEXT_ADVISOR_INCLUDE_MIND": "0",
        }):
            r = _resolve("bridge_worker", env_overrides={
                "context_mind_reserved_slots": env_int("SPARK_CONTEXT_MIND_RESERVED_SLOTS"),
                "context_advisor_include_mind": env_bool("SPARK_CONTEXT_ADVISOR_INCLUDE_MIND"),
            })
        assert r.data["context_mind_reserved_slots"] == 3
        assert r.data["context_advisor_include_mind"] is False


# --------------- schema alignment ---------------

class TestPR4SchemaAlignment:
    def test_memory_deltas_in_schema(self):
        from lib.tuneables_schema import SCHEMA, SECTION_CONSUMERS
        assert "memory_deltas" in SCHEMA
        assert len(SCHEMA["memory_deltas"]) == 5
        assert "memory_deltas" in SECTION_CONSUMERS

    def test_orchestration_in_schema(self):
        from lib.tuneables_schema import SCHEMA, SECTION_CONSUMERS
        assert "orchestration" in SCHEMA
        assert len(SCHEMA["orchestration"]) == 3
        assert "orchestration" in SECTION_CONSUMERS

    def test_feature_gates_in_schema(self):
        from lib.tuneables_schema import SCHEMA, SECTION_CONSUMERS
        assert "feature_gates" in SCHEMA
        assert len(SCHEMA["feature_gates"]) == 5
        assert "feature_gates" in SECTION_CONSUMERS

    def test_bridge_worker_extended(self):
        from lib.tuneables_schema import SCHEMA
        bw = SCHEMA["bridge_worker"]
        assert "context_mind_reserved_slots" in bw
        assert "context_advisor_include_mind" in bw


# --------------- config file alignment ---------------

class TestPR4ConfigFileAlignment:
    def test_config_has_memory_deltas(self):
        cfg_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        assert "memory_deltas" in cfg
        assert cfg["memory_deltas"]["patch_max_chars"] == 600

    def test_config_has_orchestration(self):
        cfg_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        assert "orchestration" in cfg
        assert cfg["orchestration"]["inject_enabled"] is False

    def test_config_has_feature_gates(self):
        cfg_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        assert "feature_gates" in cfg
        assert cfg["feature_gates"]["learning_bridge"] is True

    def test_config_bridge_worker_extended(self):
        cfg_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        assert cfg["bridge_worker"]["context_mind_reserved_slots"] == 1
        assert cfg["bridge_worker"]["context_advisor_include_mind"] is True
