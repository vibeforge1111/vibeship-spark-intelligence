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


def test_export_advisory_collapses_duplicates_and_repairs_text(monkeypatch, tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    monkeypatch.setattr(explorer, "_SD", spark_dir)

    _write_json(
        spark_dir / "advisor" / "effectiveness.json",
        {
            "total_advice_given": 6,
            "total_followed": 2,
            "total_helpful": 1,
            "by_source": {"cognitive": {"total": 6, "helpful": 1}},
        },
    )
    _write_json(spark_dir / "advisor" / "metrics.json", {})
    _write_json(spark_dir / "advisor" / "helpfulness_summary.json", {})

    mojibake = (
        "Reasoning: query parsing takes 200ms+ and hits are 80%+ "
        "\u00e2\u20ac\u201d reduces p95 latency by 60%"
    )
    _write_jsonl(
        spark_dir / "advisor" / "advice_log.jsonl",
        [
            {
                "timestamp": "2026-02-26T11:15:05",
                "tool": "task",
                "advice_texts": [mojibake, "Update delta quality signal"],
                "sources": ["cognitive", "bank"],
            },
            {
                "timestamp": "2026-02-26T11:14:39",
                "tool": "task",
                "advice_texts": [mojibake, "Update delta quality signal"],
                "sources": ["cognitive", "bank"],
            },
            {
                "timestamp": "2026-02-26T11:14:04",
                "tool": "task",
                "advice_texts": ["Verify functionality with bash check"],
                "sources": ["eidos"],
            },
        ],
    )

    explore_dir = tmp_path / "vault" / "_observatory" / "explore"
    count = explorer._export_advisory(explore_dir, advice_limit=50)
    assert count == 1

    content = (explore_dir / "advisory" / "_index.md").read_text(encoding="utf-8")
    assert "duplicates collapsed" in content
    assert content.count("### ") == 2
    assert "repeated 2x" in content
    assert "\u00e2\u20ac\u201d" not in content
    assert " - reduces p95 latency by 60%" in content
