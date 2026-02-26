from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from lib.eidos_distillation_curriculum import build_curriculum, render_curriculum_markdown


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE distillations (
            distillation_id TEXT PRIMARY KEY,
            type TEXT,
            statement TEXT,
            refined_statement TEXT,
            advisory_quality TEXT,
            times_used INTEGER,
            times_helped INTEGER
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
        """
        INSERT INTO distillations
            (distillation_id, type, statement, refined_statement, advisory_quality, times_used, times_helped)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "d1",
            "heuristic",
            "Do validation",
            "",
            json.dumps(
                {
                    "suppressed": True,
                    "unified_score": 0.2,
                    "actionability": 0.2,
                    "reasoning": 0.1,
                    "specificity": 0.2,
                }
            ),
            7,
            1,
        ),
    )
    conn.execute(
        """
        INSERT INTO distillations_archive
            (distillation_id, type, statement, advisory_quality, archive_reason)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "d2",
            "heuristic",
            "When timeout spikes, increase pool size because retries amplify queue delay",
            json.dumps({"suppressed": False, "unified_score": 0.31}),
            "unified_score_below_floor:0.35",
        ),
    )
    conn.commit()
    conn.close()


def test_build_curriculum_extracts_high_priority_cards(tmp_path: Path):
    db = tmp_path / "eidos.db"
    _seed_db(db)

    report = build_curriculum(db_path=db, max_rows=100, max_cards=50, include_archive=True)
    stats = report.get("stats") or {}
    cards = report.get("cards") or []

    assert stats.get("rows_scanned", 0) >= 2
    assert len(cards) >= 2

    gaps = {c.get("gap") for c in cards}
    assert "suppressed_statement" in gaps
    assert "low_effectiveness" in gaps

    suppressed_cards = [c for c in cards if c.get("gap") == "suppressed_statement"]
    assert suppressed_cards
    assert suppressed_cards[0].get("recommended_loop") == "deterministic_then_llm"
    assert suppressed_cards[0].get("answer_mode") == "single_plus_llm"


def test_render_curriculum_markdown_has_expected_sections(tmp_path: Path):
    db = tmp_path / "eidos.db"
    _seed_db(db)
    report = build_curriculum(db_path=db, max_rows=30, max_cards=10, include_archive=False)

    md = render_curriculum_markdown(report, max_cards=5)
    assert "# EIDOS Distillation Curriculum" in md
    assert "## Top Question Cards" in md
    assert "Recommended loop:" in md

