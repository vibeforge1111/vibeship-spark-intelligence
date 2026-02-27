import sqlite3
import json

from lib.cognitive_learner import CognitiveCategory
from lib.cognitive_learner import CognitiveInsight
from lib.cognitive_learner import CognitiveLearner
from lib.spark_memory_spine import dual_write_cognitive_insights
from lib.spark_memory_spine import load_cognitive_insights_runtime_snapshot
from lib.spark_memory_spine import runtime_json_fallback_enabled
from lib.spark_memory_spine import runtime_snapshot_mtime


def test_memory_spine_dual_write_round_trip(tmp_path, monkeypatch):
    db_path = tmp_path / "spark_memory_spine.db"
    monkeypatch.setenv("SPARK_MEMORY_SPINE_DUAL_WRITE", "1")
    monkeypatch.setenv("SPARK_MEMORY_SPINE_DB", str(db_path))

    payload = {
        "reasoning:k1": {
            "category": "reasoning",
            "insight": "Use strict schema checks because malformed payloads break deploy",
            "confidence": 0.8,
            "context": "deploy hardening",
            "evidence": ["deploy failed twice before schema checks"],
            "counter_examples": [],
            "created_at": "2026-02-26T00:00:00",
            "times_validated": 1,
            "times_contradicted": 0,
            "promoted": False,
            "promoted_to": None,
            "last_validated_at": None,
            "source": "test",
            "action_domain": "code",
            "emotion_state": {},
            "advisory_quality": {},
            "advisory_readiness": 0.4,
            "reliability": 0.8,
        }
    }

    out = dual_write_cognitive_insights(payload)
    assert out["ok"] is True
    assert out["written"] == 1
    assert db_path.exists()

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM cognitive_insights").fetchone()[0]
        assert int(count) == 1
        key = conn.execute("SELECT insight_key FROM cognitive_insights LIMIT 1").fetchone()[0]
        assert key == "reasoning:k1"


def test_cognitive_learner_loads_from_spine_when_json_missing(tmp_path, monkeypatch):
    db_path = tmp_path / "spark_memory_spine.db"
    insights_path = tmp_path / "cognitive_insights.json"
    lock_path = tmp_path / ".cognitive.lock"

    monkeypatch.setenv("SPARK_MEMORY_SPINE_DUAL_WRITE", "1")
    monkeypatch.setenv("SPARK_MEMORY_SPINE_DB", str(db_path))
    monkeypatch.setenv("SPARK_MEMORY_SPINE_READ_FALLBACK", "0")
    monkeypatch.setattr(CognitiveLearner, "INSIGHTS_FILE", insights_path)
    monkeypatch.setattr(CognitiveLearner, "LOCK_FILE", lock_path)

    learner = CognitiveLearner()
    learner.insights["reasoning:test"] = CognitiveInsight(
        category=CognitiveCategory.REASONING,
        insight="Prefer replay canaries because they isolate regressions early",
        evidence=["shadow lane disagreement dropped"],
        confidence=0.7,
        context="alpha migration",
    )
    learner._save_insights_now()
    assert insights_path.exists()
    assert db_path.exists()

    insights_path.unlink()
    monkeypatch.setenv("SPARK_MEMORY_SPINE_READ_FALLBACK", "1")

    restored = CognitiveLearner()
    assert "reasoning:test" in restored.insights
    assert "Prefer replay canaries" in restored.insights["reasoning:test"].insight


def test_cognitive_learner_sqlite_canonical_mode_with_json_mirror(tmp_path, monkeypatch):
    db_path = tmp_path / "spark_memory_spine.db"
    insights_path = tmp_path / "cognitive_insights.json"
    lock_path = tmp_path / ".cognitive.lock"

    monkeypatch.setenv("SPARK_MEMORY_SPINE_CANONICAL", "1")
    monkeypatch.setenv("SPARK_MEMORY_SPINE_JSON_MIRROR", "1")
    monkeypatch.setenv("SPARK_MEMORY_SPINE_DB", str(db_path))
    monkeypatch.setattr(CognitiveLearner, "INSIGHTS_FILE", insights_path)
    monkeypatch.setattr(CognitiveLearner, "LOCK_FILE", lock_path)

    learner = CognitiveLearner()
    learner.insights["wisdom:sqlite-canonical"] = CognitiveInsight(
        category=CognitiveCategory.WISDOM,
        insight="Canonical SQLite mode keeps one durable source of truth.",
        evidence=["parity streak reached 4/3 before retirement"],
        confidence=0.82,
        context="memory spine migration",
    )
    learner._save_insights_now()

    assert db_path.exists()
    assert insights_path.exists()  # mirror retained for compatibility readers

    insights_path.unlink()
    restored = CognitiveLearner()
    assert "wisdom:sqlite-canonical" in restored.insights


def test_runtime_snapshot_prefers_sqlite_before_json_fallback(tmp_path, monkeypatch):
    db_path = tmp_path / "spark_memory_spine.db"
    insights_path = tmp_path / "cognitive_insights.json"

    monkeypatch.setenv("SPARK_MEMORY_SPINE_CANONICAL", "1")
    monkeypatch.setenv("SPARK_MEMORY_SPINE_DB", str(db_path))

    payload = {
        "reasoning:sqlite": {
            "category": "reasoning",
            "insight": "SQLite canonical snapshot should be used first.",
            "confidence": 0.8,
            "context": "memory migration",
            "evidence": [],
            "counter_examples": [],
            "created_at": "2026-02-27T00:00:00",
            "times_validated": 1,
            "times_contradicted": 0,
            "promoted": False,
            "promoted_to": None,
            "last_validated_at": None,
            "source": "test",
            "action_domain": "system",
            "emotion_state": {},
            "advisory_quality": {},
            "advisory_readiness": 0.5,
            "reliability": 0.8,
        }
    }
    out = dual_write_cognitive_insights(payload)
    assert out["ok"] is True

    # Deliberately divergent JSON fallback payload.
    insights_path.write_text(json.dumps({"json_only": {"insight": "legacy"}}), encoding="utf-8")
    snap = load_cognitive_insights_runtime_snapshot(json_fallback_path=insights_path)
    assert "reasoning:sqlite" in snap
    assert "json_only" not in snap


def test_runtime_snapshot_mtime_uses_available_source(tmp_path, monkeypatch):
    db_path = tmp_path / "spark_memory_spine.db"
    insights_path = tmp_path / "cognitive_insights.json"
    monkeypatch.setenv("SPARK_MEMORY_SPINE_DB", str(db_path))

    insights_path.write_text(json.dumps({"a": {"insight": "x"}}), encoding="utf-8")
    mtime = runtime_snapshot_mtime(json_fallback_path=insights_path)
    assert isinstance(mtime, float)


def test_runtime_snapshot_respects_json_fallback_disable(tmp_path, monkeypatch):
    insights_path = tmp_path / "cognitive_insights.json"
    db_path = tmp_path / "spark_memory_spine.db"
    insights_path.write_text(json.dumps({"json_only": {"insight": "legacy"}}), encoding="utf-8")
    monkeypatch.setenv("SPARK_MEMORY_SPINE_DB", str(db_path))
    monkeypatch.setenv("SPARK_MEMORY_RUNTIME_JSON_FALLBACK", "0")
    assert runtime_json_fallback_enabled() is False
    snap = load_cognitive_insights_runtime_snapshot(json_fallback_path=insights_path)
    assert snap == {}
