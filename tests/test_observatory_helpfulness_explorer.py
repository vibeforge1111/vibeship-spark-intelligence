from __future__ import annotations

import json
from pathlib import Path

import lib.observatory.explorer as explorer
from lib.observatory.config import ObservatoryConfig


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def test_generate_helpfulness_explorer_section(monkeypatch, tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    vault_dir = tmp_path / "vault"
    monkeypatch.setattr(explorer, "_SD", spark_dir)

    _write_json(
        spark_dir / "advisor" / "helpfulness_summary.json",
        {
            "total_events": 3,
            "known_helpfulness_total": 2,
            "helpful_rate_pct": 50.0,
            "unknown_rate_pct": 33.33,
            "conflict_count": 1,
            "conflict_rate_pct": 33.33,
            "llm_review_queue_count": 1,
            "llm_review_applied_count": 1,
            "follow_rate_pct": 50.0,
            "labels": {"helpful": 1, "unhelpful": 1, "unknown": 1},
            "judge_source": {"explicit_feedback": 1, "llm_review:minimax": 1, "implicit_feedback": 1},
        },
    )
    _write_jsonl(
        spark_dir / "advisor" / "helpfulness_events.jsonl",
        [
            {
                "event_id": "e1",
                "request_ts": 1700000000.0,
                "tool": "Edit",
                "helpful_label": "helpful",
                "confidence": 0.98,
                "judge_source": "explicit_feedback",
                "llm_review_required": False,
                "conflict": False,
            },
            {
                "event_id": "e2",
                "request_ts": 1700000100.0,
                "tool": "Edit",
                "helpful_label": "unhelpful",
                "confidence": 0.62,
                "judge_source": "llm_review:minimax",
                "llm_review_required": False,
                "llm_review_applied": True,
                "conflict": True,
            },
            {
                "event_id": "e3",
                "request_ts": 1700000200.0,
                "tool": "Bash",
                "helpful_label": "unknown",
                "confidence": 0.55,
                "judge_source": "implicit_feedback",
                "llm_review_required": True,
                "conflict": False,
            },
        ],
    )
    _write_jsonl(
        spark_dir / "advisor" / "helpfulness_llm_queue.jsonl",
        [
            {"event_id": "e3", "request_ts": 1700000200.0, "tool": "Bash"},
        ],
    )
    _write_jsonl(
        spark_dir / "advisor" / "helpfulness_llm_reviews.jsonl",
        [
            {
                "event_id": "e2",
                "provider": "minimax",
                "status": "ok",
                "label": "unhelpful",
                "confidence": 0.81,
                "reviewed_at": 1700000300.0,
            },
            {
                "event_id": "e3",
                "provider": "kimi",
                "status": "provider_error",
                "label": "",
                "confidence": 0.0,
                "reviewed_at": 1700000400.0,
            },
        ],
    )
    _write_jsonl(spark_dir / "advisor" / "implicit_feedback.jsonl", [])
    _write_jsonl(spark_dir / "advisory_decision_ledger.jsonl", [])
    _write_json(spark_dir / "advisor" / "effectiveness.json", {})
    _write_json(spark_dir / "advisor" / "metrics.json", {})

    cfg = ObservatoryConfig(vault_dir=str(vault_dir), explore_feedback_max=50)
    counts = explorer.generate_explorer(cfg)

    assert counts["helpfulness"] == 1
    helpfulness_index = vault_dir / "_observatory" / "explore" / "helpfulness" / "_index.md"
    assert helpfulness_index.exists()

    content = helpfulness_index.read_text(encoding="utf-8")
    assert "# Helpfulness Calibration" in content
    assert "LLM Queue Health" in content
    assert "Recent LLM Reviews" in content

    master_index = (vault_dir / "_observatory" / "explore" / "_index.md").read_text(encoding="utf-8")
    assert "[[helpfulness/_index]]" in master_index
