from __future__ import annotations

import sqlite3

import lib.eidos.store as store_mod
from lib.eidos.models import Distillation, DistillationType
from lib.eidos.store import EidosStore


def _dist_count(db_path: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM distillations").fetchone()
    return int(row[0] if row else 0)


def test_save_distillation_collapses_exact_statement_duplicates(tmp_path):
    db = tmp_path / "eidos.db"
    store = EidosStore(str(db))

    d1 = Distillation(
        distillation_id="",
        type=DistillationType.HEURISTIC,
        statement="When budget is high without progress, simplify scope",
        domains=["escape_protocol"],
        triggers=["Budget high"],
    )
    d2 = Distillation(
        distillation_id="",
        type=DistillationType.HEURISTIC,
        statement="When budget is high without progress, simplify scope",
        domains=["rabbit_hole_recovery"],
        triggers=["Budget exhausted"],
    )

    id1 = store.save_distillation(d1)
    id2 = store.save_distillation(d2)

    assert id2 == id1
    assert _dist_count(str(db)) == 1


def test_save_distillation_collapses_budget_percentage_variants(tmp_path):
    db = tmp_path / "eidos.db"
    store = EidosStore(str(db))

    d1 = Distillation(
        distillation_id="",
        type=DistillationType.HEURISTIC,
        statement="When budget is 82% used without progress, simplify scope",
    )
    d2 = Distillation(
        distillation_id="",
        type=DistillationType.HEURISTIC,
        statement="When budget is 91% used without progress, simplify scope",
    )

    id1 = store.save_distillation(d1)
    id2 = store.save_distillation(d2)

    assert id2 == id1
    assert _dist_count(str(db)) == 1


def test_save_distillation_updates_statement_when_incoming_quality_is_better(tmp_path):
    db = tmp_path / "eidos.db"
    store = EidosStore(str(db))

    d1 = Distillation(
        distillation_id="",
        type=DistillationType.HEURISTIC,
        statement="When budget is 82% used without progress, simplify scope",
        advisory_quality={"unified_score": 0.21, "suppressed": False},
    )
    d2 = Distillation(
        distillation_id="",
        type=DistillationType.HEURISTIC,
        statement="When budget is 91% used without progress, simplify scope",
        advisory_quality={"unified_score": 0.91, "suppressed": False},
    )

    id1 = store.save_distillation(d1)
    id2 = store.save_distillation(d2)

    assert id2 == id1
    assert _dist_count(str(db)) == 1
    saved = store.get_distillation(id1)
    assert saved is not None
    assert saved.statement == d2.statement


def test_save_distillation_hydrates_projection_when_missing(monkeypatch, tmp_path):
    db = tmp_path / "eidos.db"
    store = EidosStore(str(db))

    class _FakeTransform:
        advisory_text = "When retries loop: reduce scope and run one proving check."

        def to_dict(self):
            return {
                "unified_score": 0.88,
                "suppressed": False,
                "advisory_text": self.advisory_text,
            }

    monkeypatch.setattr(store_mod, "transform_for_advisory", lambda *_a, **_kw: _FakeTransform())

    did = store.save_distillation(
        Distillation(
            distillation_id="",
            type=DistillationType.HEURISTIC,
            statement="Retries keep looping with no proof.",
        )
    )
    saved = store.get_distillation(did)
    assert saved is not None
    assert float(saved.advisory_quality.get("unified_score", 0.0)) == 0.88
    assert "reduce scope" in str(saved.refined_statement).lower()


def test_save_distillation_keeps_stronger_existing_quality(monkeypatch, tmp_path):
    db = tmp_path / "eidos.db"
    store = EidosStore(str(db))

    class _LowTransform:
        advisory_text = "weak"

        def to_dict(self):
            return {"unified_score": 0.11, "suppressed": False, "advisory_text": self.advisory_text}

    monkeypatch.setattr(store_mod, "transform_for_advisory", lambda *_a, **_kw: _LowTransform())

    did = store.save_distillation(
        Distillation(
            distillation_id="",
            type=DistillationType.HEURISTIC,
            statement="Validate state before callback exchange.",
            refined_statement="Validate OAuth state before callback exchange.",
            advisory_quality={"unified_score": 0.91, "suppressed": False, "advisory_text": "strong"},
        )
    )
    saved = store.get_distillation(did)
    assert saved is not None
    assert float(saved.advisory_quality.get("unified_score", 0.0)) == 0.91
    assert "oauth state" in str(saved.refined_statement).lower()
