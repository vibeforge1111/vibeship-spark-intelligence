from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import lib.eidos_curriculum_autofix as autofix


def _seed_live_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE distillations (
            distillation_id TEXT PRIMARY KEY,
            statement TEXT,
            refined_statement TEXT,
            advisory_quality TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO distillations (distillation_id, statement, refined_statement, advisory_quality) VALUES (?, ?, ?, ?)",
        (
            "d1",
            "Do better validation",
            "",
            json.dumps(
                {
                    "unified_score": 0.2,
                    "suppressed": True,
                    "actionability": 0.2,
                    "reasoning": 0.1,
                    "specificity": 0.2,
                }
            ),
        ),
    )
    conn.commit()
    conn.close()


def _seed_archive_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE distillations (
            distillation_id TEXT PRIMARY KEY,
            type TEXT,
            statement TEXT,
            refined_statement TEXT,
            advisory_quality TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE distillations_archive (
            distillation_id TEXT,
            type TEXT,
            statement TEXT,
            advisory_quality TEXT,
            archive_reason TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO distillations (distillation_id, type, statement, refined_statement, advisory_quality) VALUES (?, ?, ?, ?, ?)",
        ("d2", "heuristic", "Stale live statement", "", json.dumps({"unified_score": 0.25, "suppressed": True})),
    )
    conn.execute(
        "INSERT INTO distillations_archive (distillation_id, type, statement, advisory_quality, archive_reason) VALUES (?, ?, ?, ?, ?)",
        (
            "d2",
            "heuristic",
            "Archive candidate statement",
            json.dumps(
                {
                    "unified_score": 0.28,
                    "suppressed": True,
                    "actionability": 0.35,
                    "reasoning": 0.3,
                    "specificity": 0.3,
                }
            ),
            "suppressed:too_vague",
        ),
    )
    conn.commit()
    conn.close()


def test_autofix_updates_when_improved(monkeypatch, tmp_path: Path):
    db = tmp_path / "eidos.db"
    _seed_live_db(db)

    monkeypatch.setattr(
        autofix,
        "build_curriculum",
        lambda **kwargs: {"cards": [{"source": "distillations", "distillation_id": "d1"}]},
    )

    def _refined(*args, **kwargs):
        return (
            "When validation is missing: enforce schema checks because malformed payloads break downstream steps",
            {"unified_score": 0.61, "suppressed": False, "actionability": 0.8, "reasoning": 0.7, "specificity": 0.7},
        )

    monkeypatch.setattr(autofix, "refine_distillation", _refined)

    report = autofix.run_curriculum_autofix(db_path=db, max_cards=3, min_gain=0.03, apply=True)
    assert report["updated"] == 1
    assert report["attempted"] == 1

    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT refined_statement, advisory_quality FROM distillations WHERE distillation_id = 'd1'").fetchone()
    conn.close()
    assert row and "schema checks" in str(row[0])
    aq = json.loads(str(row[1]))
    assert float(aq["unified_score"]) >= 0.6


def test_autofix_skips_when_not_improved(monkeypatch, tmp_path: Path):
    db = tmp_path / "eidos.db"
    _seed_live_db(db)
    monkeypatch.setattr(
        autofix,
        "build_curriculum",
        lambda **kwargs: {"cards": [{"source": "distillations", "distillation_id": "d1"}]},
    )
    monkeypatch.setattr(
        autofix,
        "refine_distillation",
        lambda *args, **kwargs: ("Do better validation", {"unified_score": 0.2, "suppressed": True}),
    )

    report = autofix.run_curriculum_autofix(db_path=db, max_cards=1, min_gain=0.03, apply=True)
    assert report["updated"] == 0
    assert report["attempted"] == 1
    assert report["rows"][0]["action"] == "noop"


def test_autofix_include_archive_path_runs(monkeypatch, tmp_path: Path):
    db = tmp_path / "eidos.db"
    _seed_archive_db(db)

    seen_kwargs = {}

    def _build_curriculum(**kwargs):
        seen_kwargs.update(kwargs)
        return {"cards": [{"source": "distillations_archive", "distillation_id": "d2"}]}

    monkeypatch.setattr(autofix, "build_curriculum", _build_curriculum)
    monkeypatch.setattr(
        autofix,
        "refine_distillation",
        lambda *args, **kwargs: (
            "When queue backpressure rises: cap retries first because retries amplify wait time",
            {"unified_score": 0.7, "suppressed": False, "actionability": 0.8, "reasoning": 0.7, "specificity": 0.8},
        ),
    )

    report = autofix.run_curriculum_autofix(
        db_path=db,
        max_cards=2,
        min_gain=0.03,
        apply=False,
        include_archive=True,
    )

    assert seen_kwargs.get("include_archive") is True
    assert report["attempted"] == 1
    assert report["archive_attempted"] == 1
    assert report["rows"][0]["source"] == "distillations_archive"


def test_archive_fallback_pass_recovers_suppressed_row(monkeypatch, tmp_path: Path):
    db = tmp_path / "eidos.db"
    _seed_archive_db(db)

    monkeypatch.setattr(
        autofix,
        "build_curriculum",
        lambda **kwargs: {"cards": [{"source": "distillations_archive", "distillation_id": "d2"}]},
    )

    seen_contexts = []

    def _refined(*args, **kwargs):
        context = dict(kwargs.get("context") or {})
        seen_contexts.append(context)
        if context.get("archive_fallback_pass"):
            return (
                "When queue backpressure rises: cap retries first because retries amplify wait time",
                {
                    "unified_score": 0.66,
                    "suppressed": False,
                    "actionability": 0.78,
                    "reasoning": 0.72,
                    "specificity": 0.74,
                },
            )
        return (
            "Archive candidate statement",
            {
                "unified_score": 0.29,
                "suppressed": True,
                "actionability": 0.3,
                "reasoning": 0.3,
                "specificity": 0.3,
            },
        )

    monkeypatch.setattr(autofix, "refine_distillation", _refined)

    report = autofix.run_curriculum_autofix(db_path=db, max_cards=1, min_gain=0.03, apply=True, include_archive=True)

    assert len(seen_contexts) == 2
    assert seen_contexts[0].get("archive_fallback_pass") is None
    assert seen_contexts[1].get("archive_fallback_pass") is True
    assert report["archive_updated"] == 1
    assert report["rows"][0]["action"] == "updated"

    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT advisory_quality FROM distillations_archive WHERE distillation_id = ?", ("d2",)).fetchone()
    conn.close()

    payload = json.loads(str(row[0]))
    assert payload["suppressed"] is False
    assert float(payload["unified_score"]) >= 0.6


def test_archive_promotion_gate_promotes_row(monkeypatch, tmp_path: Path):
    db = tmp_path / "eidos.db"
    _seed_archive_db(db)

    monkeypatch.setattr(
        autofix,
        "build_curriculum",
        lambda **kwargs: {"cards": [{"source": "distillations_archive", "distillation_id": "d2"}]},
    )

    monkeypatch.setattr(
        autofix,
        "refine_distillation",
        lambda *args, **kwargs: (
            "When queue backpressure rises: cap retries first because retries amplify wait time",
            {"unified_score": 0.81, "suppressed": False, "actionability": 0.85, "reasoning": 0.8, "specificity": 0.8},
        ),
    )

    report = autofix.run_curriculum_autofix(
        db_path=db,
        max_cards=1,
        min_gain=0.03,
        apply=True,
        include_archive=True,
        promote_on_success=True,
        promote_min_unified=0.6,
    )

    assert report["archive_updated"] == 1
    assert report["archive_promoted"] == 1
    assert report["rows"][0]["action"] == "promoted"

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT statement, refined_statement, advisory_quality FROM distillations WHERE distillation_id = ?",
        ("d2",),
    ).fetchone()
    conn.close()

    assert row is not None
    assert "Archive candidate statement" in str(row[0])
    assert "cap retries first" in str(row[1])
    aq = json.loads(str(row[2]))
    assert float(aq.get("unified_score", 0.0)) >= 0.8


def test_archive_soft_promotion_tags_archive_only(monkeypatch, tmp_path: Path):
    db = tmp_path / "eidos.db"
    _seed_archive_db(db)

    monkeypatch.setattr(
        autofix,
        "build_curriculum",
        lambda **kwargs: {"cards": [{"source": "distillations_archive", "distillation_id": "d2"}]},
    )
    monkeypatch.setattr(
        autofix,
        "refine_distillation",
        lambda *args, **kwargs: (
            "When queue backpressure rises: cap retries first because retries amplify wait time",
            {
                "unified_score": 0.52,
                "suppressed": False,
                "actionability": 0.75,
                "reasoning": 0.74,
                "specificity": 0.71,
            },
        ),
    )

    report = autofix.run_curriculum_autofix(
        db_path=db,
        max_cards=1,
        min_gain=0.03,
        apply=True,
        include_archive=True,
        promote_on_success=True,
        promote_min_unified=0.8,
        soft_promote_on_success=True,
        soft_promote_min_unified=0.35,
    )

    assert report["archive_promoted"] == 0
    assert report["rows"][0]["action"] == "soft_promoted"

    conn = sqlite3.connect(str(db))
    archive_row = conn.execute("SELECT advisory_quality FROM distillations_archive WHERE distillation_id = ?", ("d2",)).fetchone()
    live_row = conn.execute("SELECT refined_statement FROM distillations WHERE distillation_id = ?", ("d2",)).fetchone()
    conn.close()

    assert json.loads(str(archive_row[0])).get("soft_promoted") is True
    assert str(live_row[0] or "") == ""


def test_report_contains_archive_metrics(monkeypatch, tmp_path: Path):
    db = tmp_path / "eidos.db"
    _seed_live_db(db)

    monkeypatch.setattr(
        autofix,
        "build_curriculum",
        lambda **kwargs: {"cards": [{"source": "distillations", "distillation_id": "d1"}]},
    )
    monkeypatch.setattr(
        autofix,
        "refine_distillation",
        lambda *args, **kwargs: (
            "When validation fails: enforce schema checks before dispatch",
            {"unified_score": 0.6, "suppressed": False, "actionability": 0.7, "reasoning": 0.7, "specificity": 0.7},
        ),
    )

    report = autofix.run_curriculum_autofix(db_path=db, max_cards=1, min_gain=0.03, apply=False)

    assert "archive_attempted" in report
    assert "archive_updated" in report
    assert "archive_promoted" in report
    assert "archive_stagnation_detected" in report
    assert "archive_update_rate" in report
    assert "mode_used" in report
    assert "suppression_recovery_rate" in report
