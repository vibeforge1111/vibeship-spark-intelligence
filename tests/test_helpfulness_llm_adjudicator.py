from __future__ import annotations

import json
from pathlib import Path

from lib.helpfulness_llm_adjudicator import LLMAdjudicatorConfig, run_helpfulness_llm_adjudicator


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def test_llm_adjudicator_writes_reviews_with_fake_judge(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    queue = spark_dir / "advisor" / "helpfulness_llm_queue.jsonl"
    _write_jsonl(
        queue,
        [
            {"event_id": "e1", "tool": "Edit", "trace_id": "t1", "request_ts": 10.0},
            {"event_id": "e2", "tool": "Bash", "trace_id": "t2", "request_ts": 20.0},
        ],
    )

    def fake_judge(event: dict, _cfg: LLMAdjudicatorConfig) -> dict:
        if event["event_id"] == "e1":
            return {
                "ok": True,
                "status": "ok",
                "label": "helpful",
                "confidence": 0.91,
                "rationale": "explicit context in evidence",
                "provider": "fake",
                "model": "fake-model",
                "raw_excerpt": '{"label":"helpful","confidence":0.91}',
            }
        return {
            "ok": True,
            "status": "abstain",
            "label": "abstain",
            "confidence": 0.55,
            "rationale": "insufficient evidence",
            "provider": "fake",
            "model": "fake-model",
            "raw_excerpt": '{"label":"abstain","confidence":0.55}',
        }

    out = run_helpfulness_llm_adjudicator(
        LLMAdjudicatorConfig(
            spark_dir=spark_dir,
            provider="auto",
            max_events=10,
            write_files=True,
        ),
        judge_fn=fake_judge,
    )
    assert out["ok"] is True
    assert out["processed"] == 2
    assert out["reviewed_now"] == 2
    assert out["by_status"]["ok"] == 1
    assert out["by_status"]["abstain"] == 1

    reviews = _read_jsonl(spark_dir / "advisor" / "helpfulness_llm_reviews.jsonl")
    assert len(reviews) == 2
    by_event = {r["event_id"]: r for r in reviews}
    assert by_event["e1"]["label"] == "helpful"
    assert by_event["e1"]["status"] == "ok"
    assert by_event["e2"]["status"] == "abstain"


def test_llm_adjudicator_skips_existing_ok_when_not_forced(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    _write_jsonl(
        spark_dir / "advisor" / "helpfulness_llm_queue.jsonl",
        [{"event_id": "e3", "tool": "Edit", "trace_id": "t3", "request_ts": 30.0}],
    )
    _write_jsonl(
        spark_dir / "advisor" / "helpfulness_llm_reviews.jsonl",
        [{"event_id": "e3", "status": "ok", "label": "unhelpful", "confidence": 0.9, "reviewed_at": 100.0}],
    )

    called = {"n": 0}

    def fake_judge(_event: dict, _cfg: LLMAdjudicatorConfig) -> dict:
        called["n"] += 1
        return {"ok": True, "status": "ok", "label": "helpful", "confidence": 0.99}

    out = run_helpfulness_llm_adjudicator(
        LLMAdjudicatorConfig(
            spark_dir=spark_dir,
            max_events=5,
            force=False,
            write_files=True,
        ),
        judge_fn=fake_judge,
    )
    assert out["processed"] == 0
    assert out["skipped_existing"] == 1
    assert called["n"] == 0

