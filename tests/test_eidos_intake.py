from __future__ import annotations

import json
from pathlib import Path

import lib.eidos_intake as intake
from lib.eidos.store import EidosStore


class _AQ:
    def __init__(self, *, advisory_text: str, unified_score: float, suppressed: bool, reason: str = ""):
        self.advisory_text = advisory_text
        self.unified_score = unified_score
        self.suppressed = suppressed
        self.suppression_reason = reason

    def to_dict(self):
        return {
            "advisory_text": self.advisory_text,
            "unified_score": self.unified_score,
            "suppressed": self.suppressed,
            "suppression_reason": self.suppression_reason,
        }


def _quarantine_recorder():
    rows = []

    def _rec(**kwargs):
        rows.append(dict(kwargs))

    return rows, _rec


def test_ingest_structured_update_and_skip_duplicate(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        intake,
        "transform_for_advisory",
        lambda text, source="unknown": _AQ(
            advisory_text="Keep structured action because it prevents repeat failures.",
            unified_score=0.82,
            suppressed=False,
        ),
    )
    update = json.dumps(
        {
            "schema": "spark.eidos.v1",
            "insights": [
                {
                    "decision": "keep",
                    "action": "Use schema validation before writing runtime config.",
                    "usage_context": "startup",
                    "priority_score": 0.8,
                },
                {
                    "decision": "drop",
                    "action": "short",
                },
            ],
        }
    )
    eidos_file = tmp_path / "eidos_distillations.jsonl"
    spine_db = tmp_path / "eidos.db"
    quarantine_rows, quarantine = _quarantine_recorder()

    first = intake.ingest_eidos_update(
        update,
        eidos_file=eidos_file,
        store_db_path=spine_db,
        quarantine_fn=quarantine,
    )
    second = intake.ingest_eidos_update(
        update,
        eidos_file=eidos_file,
        store_db_path=spine_db,
        quarantine_fn=quarantine,
    )

    assert first.ok is True
    assert first.duplicate is False
    assert first.reason in {"ok_structured", "ok"}
    assert isinstance(first.entry, dict)
    assert first.entry.get("insights")
    assert second.ok is True
    assert second.duplicate is True
    assert second.reason == "duplicate_skipped"
    assert first.spine_saved >= 1
    assert second.spine_saved >= 1
    lines = eidos_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    store = EidosStore(str(spine_db))
    distillations = store.get_all_distillations(limit=20)
    assert len(distillations) == 1
    assert "schema validation" in (distillations[0].statement or "").lower()
    assert quarantine_rows == []


def test_ingest_rejects_short_and_records_quarantine(tmp_path: Path):
    eidos_file = tmp_path / "eidos_distillations.jsonl"
    spine_db = tmp_path / "eidos.db"
    quarantine_rows, quarantine = _quarantine_recorder()

    result = intake.ingest_eidos_update(
        "too short",
        eidos_file=eidos_file,
        store_db_path=spine_db,
        quarantine_fn=quarantine,
    )

    assert result.ok is False
    assert result.reason == "too_short"
    assert not eidos_file.exists()
    assert quarantine_rows
    assert quarantine_rows[-1].get("reason") == "validator:too_short"


def test_ingest_respects_transformer_suppression(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        intake,
        "transform_for_advisory",
        lambda text, source="unknown": _AQ(
            advisory_text="",
            unified_score=0.2,
            suppressed=True,
            reason="noise_pattern",
        ),
    )
    update = (
        "When editing deployment config: add rollback check because "
        "missing rollback causes prolonged incidents."
    )
    eidos_file = tmp_path / "eidos_distillations.jsonl"
    spine_db = tmp_path / "eidos.db"
    quarantine_rows, quarantine = _quarantine_recorder()

    result = intake.ingest_eidos_update(
        update,
        eidos_file=eidos_file,
        store_db_path=spine_db,
        quarantine_fn=quarantine,
    )

    assert result.ok is False
    assert result.reason == "transformer_suppressed:noise_pattern"
    assert not eidos_file.exists()
    assert quarantine_rows
    assert quarantine_rows[-1].get("reason") == "transformer_suppressed:noise_pattern"


def test_ingest_unstructured_update_persists_to_spine(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        intake,
        "transform_for_advisory",
        lambda text, source="unknown": _AQ(
            advisory_text="Validate payload schema before applying config updates.",
            unified_score=0.79,
            suppressed=False,
        ),
    )
    update = "Validate payload schema before applying config updates because malformed writes corrupt runtime state."
    eidos_file = tmp_path / "eidos_distillations.jsonl"
    spine_db = tmp_path / "eidos.db"

    result = intake.ingest_eidos_update(
        update,
        eidos_file=eidos_file,
        store_db_path=spine_db,
    )

    assert result.ok is True
    assert result.spine_saved >= 1
    store = EidosStore(str(spine_db))
    distillations = store.get_all_distillations(limit=10)
    assert distillations
    assert "validate payload schema" in (distillations[0].statement or "").lower()
