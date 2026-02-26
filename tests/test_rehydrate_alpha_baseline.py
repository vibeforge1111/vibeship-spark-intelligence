from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.rehydrate_alpha_baseline as rehydrate


def _make_memory_db(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.execute(
            "create table if not exists memories (id integer primary key, content text)"
        )
        con.execute("delete from memories")
        for i in range(rows):
            con.execute("insert into memories(content) values(?)", (f"m{i}",))
        con.commit()


def test_plan_rehydrate_uses_latest_archive_with_nonempty_data(tmp_path: Path):
    spark_dir = tmp_path / ".spark"
    archive = spark_dir / "archive"
    old = archive / "legacy_old"
    new = archive / "legacy_new"
    old.mkdir(parents=True)
    new.mkdir(parents=True)

    _make_memory_db(old / "memory_store.sqlite", rows=1)
    _make_memory_db(new / "memory_store.sqlite", rows=2)
    (old / "cognitive_insights.json").write_text(json.dumps({"k": {"insight": "x"}}), encoding="utf-8")
    (new / "cognitive_insights.json").write_text(json.dumps({"k2": {"insight": "y"}}), encoding="utf-8")

    # Ensure deterministic "newest" ordering by mtime.
    old.touch()
    new.touch()

    plan = rehydrate.plan_rehydrate(
        spark_dir=spark_dir,
        archive_root=archive,
        max_candidates=5,
    )
    relpaths = {item["relpath"]: item for item in plan["actions"]}
    assert "memory_store.sqlite" in relpaths
    assert "legacy_new" in str(relpaths["memory_store.sqlite"]["source"])


def test_plan_rehydrate_skips_nonempty_target_without_force(tmp_path: Path):
    spark_dir = tmp_path / ".spark"
    archive = spark_dir / "archive"
    cand = archive / "legacy_a"
    cand.mkdir(parents=True)

    _make_memory_db(spark_dir / "memory_store.sqlite", rows=3)
    _make_memory_db(cand / "memory_store.sqlite", rows=4)

    plan = rehydrate.plan_rehydrate(
        spark_dir=spark_dir,
        archive_root=archive,
        max_candidates=5,
        force=False,
    )
    assert all(item["relpath"] != "memory_store.sqlite" for item in plan["actions"])
