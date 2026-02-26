from __future__ import annotations

import sqlite3

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
