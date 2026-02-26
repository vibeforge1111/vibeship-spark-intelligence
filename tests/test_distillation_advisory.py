from __future__ import annotations

import sqlite3
from pathlib import Path

import lib.advisor as advisor_mod
from lib.advisor import SparkAdvisor
from lib.eidos.distillation_engine import DistillationCandidate, DistillationEngine
from lib.eidos.models import Distillation, DistillationType
from lib.eidos.store import EidosStore


class _DummyCognitive:
    def get_insights_for_context(self, *_a, **_kw):
        return []

    def get_self_awareness_insights(self):
        return []

    def get_insights_by_category(self, *_a, **_kw):
        return []

    def search_semantic(self, *_a, **_kw):
        return []


class _DummyMindBridge:
    def retrieve(self, *_a, **_kw):
        return []

    def get_stats(self):
        return {}


class _StubRetriever:
    def __init__(self, distillations):
        self._distillations = distillations

    def retrieve_for_intent(self, _intent):
        return self._distillations


class _RalphRoutesToStore:
    def __init__(self, store: EidosStore):
        self._store = store

    def track_outcome(self, _advice_id, outcome, _notes, **kwargs):
        ik = (kwargs.get("insight_key") or "").strip()
        if not ik.startswith("eidos:"):
            return
        parts = ik.split(":")
        if len(parts) < 3:
            return
        full_id = self._store.find_distillation_by_prefix(parts[2])
        if full_id:
            self._store.record_distillation_usage(full_id, helped=(outcome == "good"))


def _patch_advisor(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(advisor_mod, "ADVISOR_DIR", tmp_path)
    monkeypatch.setattr(advisor_mod, "ADVICE_LOG", tmp_path / "advice_log.jsonl")
    monkeypatch.setattr(advisor_mod, "EFFECTIVENESS_FILE", tmp_path / "effectiveness.json")
    monkeypatch.setattr(advisor_mod, "ADVISOR_METRICS", tmp_path / "metrics.json")
    monkeypatch.setattr(advisor_mod, "RECENT_ADVICE_LOG", tmp_path / "recent_advice.jsonl")
    monkeypatch.setattr(advisor_mod, "RETRIEVAL_ROUTE_LOG", tmp_path / "retrieval_route.jsonl")
    monkeypatch.setattr(advisor_mod, "CHIP_INSIGHTS_DIR", tmp_path / "chip_insights")
    monkeypatch.setattr(advisor_mod, "get_cognitive_learner", lambda: _DummyCognitive())
    monkeypatch.setattr(advisor_mod, "get_mind_bridge", lambda: _DummyMindBridge())
    monkeypatch.setattr(advisor_mod, "AUTO_TUNER_SOURCE_BOOSTS", {})
    monkeypatch.setattr(advisor_mod, "_advisor", None)


def test_distillation_refinement_persists_round_trip(tmp_path):
    store = EidosStore(str(tmp_path / "eidos.db"))
    engine = DistillationEngine()

    candidate = DistillationCandidate(
        type=DistillationType.HEURISTIC,
        statement="When handling auth tokens, always validate expiration because stale tokens fail unexpectedly",
        domains=["auth"],
        triggers=["token"],
        source_steps=["s1"],
        confidence=0.4,
        rationale="token auth episode",
    )

    dist = engine.finalize_distillation(candidate)
    assert isinstance(dist.advisory_quality, dict)
    assert "unified_score" in dist.advisory_quality

    did = store.save_distillation(dist)
    loaded = store.get_distillation(did)
    assert loaded is not None
    assert isinstance(loaded.advisory_quality, dict)
    assert "unified_score" in loaded.advisory_quality


def test_archive_and_purge_low_quality_distillations(tmp_path):
    db = tmp_path / "eidos.db"
    store = EidosStore(str(db))

    keep = Distillation(
        distillation_id="",
        type=DistillationType.HEURISTIC,
        statement="When using SQLite with concurrent writes, enable WAL mode to avoid lock contention",
    )
    drop = Distillation(
        distillation_id="",
        type=DistillationType.HEURISTIC,
        statement="Try a different approach",
    )
    store.save_distillation(keep)
    store.save_distillation(drop)

    result = store.archive_and_purge_low_quality_distillations(unified_floor=0.35, dry_run=False)
    assert result["archived"] >= 1

    with sqlite3.connect(str(db)) as conn:
        active_count = conn.execute("SELECT COUNT(*) FROM distillations").fetchone()[0]
        archived_count = conn.execute("SELECT COUNT(*) FROM distillations_archive").fetchone()[0]
    assert archived_count >= 1
    assert active_count >= 1


def test_archive_purge_respects_stored_quality_and_refined_statement(tmp_path):
    db = tmp_path / "eidos.db"
    store = EidosStore(str(db))

    strong = Distillation(
        distillation_id="",
        type=DistillationType.HEURISTIC,
        statement="Always verify",
        refined_statement="When validating OAuth callbacks: verify state token before exchange",
        advisory_quality={
            "unified_score": 0.82,
            "suppressed": False,
            "advisory_text": "When validating OAuth callbacks: verify state token before exchange",
        },
    )
    store.save_distillation(strong)

    result = store.archive_and_purge_low_quality_distillations(unified_floor=0.35, dry_run=False)
    assert result["archived"] == 0

    with sqlite3.connect(str(db)) as conn:
        active_count = conn.execute("SELECT COUNT(*) FROM distillations").fetchone()[0]
        archived_count = conn.execute("SELECT COUNT(*) FROM distillations_archive").fetchone()[0]
    assert active_count == 1
    assert archived_count == 0


def test_advisor_uses_stored_eidos_quality_without_live_transform(monkeypatch, tmp_path):
    _patch_advisor(monkeypatch, tmp_path)
    monkeypatch.setattr(advisor_mod, "HAS_EIDOS", True)

    dist = Distillation(
        distillation_id="abc12345ffff",
        type=DistillationType.HEURISTIC,
        statement="Raw statement",
        refined_statement="When validating webhook payloads: enforce schema before processing",
        advisory_quality={
            "unified_score": 0.78,
            "suppressed": False,
            "advisory_text": "When validating webhook payloads: enforce schema before processing",
        },
    )

    monkeypatch.setattr(advisor_mod, "get_retriever", lambda: _StubRetriever([dist]))

    def _must_not_call(*_a, **_kw):
        raise AssertionError("live transformer should not be called when advisory_quality is stored")

    monkeypatch.setattr(advisor_mod, "_transform_distillation", _must_not_call)

    advisor = SparkAdvisor()
    advice = advisor._get_eidos_advice("Read", "webhook payload validation")

    assert len(advice) == 1
    assert advice[0].advisory_quality.get("unified_score") == 0.78
    assert "webhook payloads" in advice[0].text


def test_eidos_feedback_updates_once_via_meta_ralph_path(monkeypatch, tmp_path):
    _patch_advisor(monkeypatch, tmp_path)
    monkeypatch.setattr(advisor_mod, "HAS_EIDOS", False)

    store = EidosStore(str(tmp_path / "eidos.db"))
    dist = Distillation(
        distillation_id="feedbeef1234",
        type=DistillationType.HEURISTIC,
        statement="When writing migrations: run schema checks before deploy",
    )
    did = store.save_distillation(dist)

    advisor = SparkAdvisor()
    advice_id = "advice:eidos:test"
    insight_key = f"eidos:heuristic:{did[:8]}"

    monkeypatch.setattr(
        advisor,
        "_find_recent_advice_by_id",
        lambda _aid: {
            "advice_ids": [advice_id],
            "insight_keys": [insight_key],
            "sources": ["eidos"],
            "trace_id": "trace-1",
        },
    )

    monkeypatch.setattr(
        "lib.meta_ralph.get_meta_ralph",
        lambda: _RalphRoutesToStore(store),
    )

    advisor.report_outcome(advice_id=advice_id, was_followed=True, was_helpful=True)
    updated = store.get_distillation(did)
    assert updated is not None
    assert updated.times_used == 1
    assert updated.times_helped == 1
