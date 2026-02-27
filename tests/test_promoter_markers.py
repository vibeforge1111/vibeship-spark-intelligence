from __future__ import annotations

from pathlib import Path

from lib.promoter import Promoter


def test_append_to_section_preserves_spark_learning_markers(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "\n".join(
            [
                "# AGENTS",
                "",
                "## Spark Learnings",
                "",
                "*Auto-promoted insights from Spark*",
                "",
                "<!-- SPARK_LEARNINGS_START -->",
                "<!-- Spark auto-promotes agent-level learnings here -->",
                "<!-- SPARK_LEARNINGS_END -->",
                "",
            ]
        ),
        encoding="utf-8",
    )

    promoter = Promoter(project_dir=tmp_path)
    promoter._append_to_section(
        target,
        "## Spark Learnings",
        "- Validate contracts before changing payload shapes (100% reliable, 5 validations)",
    )

    content = target.read_text(encoding="utf-8")
    assert "<!-- SPARK_LEARNINGS_START -->" in content
    assert "<!-- SPARK_LEARNINGS_END -->" in content
    assert "- Validate contracts before changing payload shapes (100% reliable, 5 validations)" in content

    lines = content.splitlines()
    start_idx = lines.index("<!-- SPARK_LEARNINGS_START -->")
    end_idx = lines.index("<!-- SPARK_LEARNINGS_END -->")
    assert start_idx < end_idx
    assert any(line.strip().startswith("- ") for line in lines[start_idx + 1 : end_idx])
