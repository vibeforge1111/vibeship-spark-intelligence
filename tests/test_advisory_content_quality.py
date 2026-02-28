from __future__ import annotations

import json
from pathlib import Path

from lib.advisory_content_quality import build_production_noise_report


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def test_build_production_noise_report_detects_known_live_noise_shapes(tmp_path: Path) -> None:
    spark_dir = tmp_path / ".spark"
    spark_dir.mkdir(parents=True, exist_ok=True)
    (spark_dir / "cognitive_insights.json").write_text(
        json.dumps(
            {
                "noise_chunk_id": {"insight": "exec_command failed: Chunk ID: c6305b"},
                "signal_guidance": {"insight": "Use Glob to verify files before Edit to avoid path mistakes."},
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        spark_dir / "promotion_log.jsonl",
        [
            {"key": "#sky-egg { position: relative; display: block; padding: 2px; }"},
            {"key": "Always validate authentication tokens against canonical schema before deploy."},
        ],
    )
    _write_jsonl(
        spark_dir / "advisory_emit.jsonl",
        [
            {"advice_text": "it worked, can we now run localhost"},
            {"advice_text": "Add a provider-specific capture gate for Claude before release."},
        ],
    )

    report = build_production_noise_report(
        spark_dir=spark_dir,
        max_rows_per_source=100,
        detail_rows=50,
    )

    assert report["rows_analyzed"] >= 4
    assert report["expected_noise_rows"] >= 3
    signature_counts = report.get("hard_noise_signature_counts") or {}
    assert signature_counts.get("chunk_id_telemetry", 0) >= 1
    assert signature_counts.get("css_fragment", 0) >= 1
    assert signature_counts.get("conversational_directive", 0) >= 1
    assert isinstance(report.get("false_negative_examples"), list)
    assert isinstance(report.get("false_positive_examples"), list)
    assert isinstance(report.get("detailed_rows"), list)

