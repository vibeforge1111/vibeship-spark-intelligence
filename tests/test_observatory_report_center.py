from __future__ import annotations

import json
from pathlib import Path

import lib.observatory.report_center as report_center
import lib.llm as llm


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_generate_report_center_creates_index_and_source_pages(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    obs_dir = tmp_path / "vault" / "_observatory"

    _write(repo_root / "docs" / "reports" / "alpha.md", "# Alpha\n\nTop blockers.")
    _write(repo_root / "reports" / "beta.json", json.dumps({"health": 7.5}))

    summary = report_center.generate_report_center(
        obs_dir=obs_dir,
        repo_root=repo_root,
        max_reports=20,
    )

    assert summary["reports_indexed"] == 2
    assert (obs_dir / "report_center.md").exists()
    assert summary["files_written"] >= 3

    index_text = (obs_dir / "report_center.md").read_text(encoding="utf-8")
    assert "Report Center" in index_text
    assert "alpha.md" in index_text
    assert "beta.json" in index_text
    assert "not_analyzed" in index_text

    source_files = sorted((obs_dir / "reports" / "source").glob("*.md"))
    assert len(source_files) == 2
    source_text = source_files[0].read_text(encoding="utf-8")
    assert "Run: `python scripts/claude_observatory_report_analyzer.py --report" in source_text


def test_analyze_reports_with_claude_writes_analysis_pages(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    obs_dir = tmp_path / "vault" / "_observatory"
    report_path = repo_root / "docs" / "reports" / "quality.md"
    _write(report_path, "# Quality\n\nEmit rate is low.")

    monkeypatch.setattr(llm, "ask_claude", lambda *args, **kwargs: "1. Verdict: partial risk.")

    result = report_center.analyze_reports_with_claude(
        obs_dir=obs_dir,
        repo_root=repo_root,
        max_reports=10,
        timeout_s=60,
        overwrite=True,
    )

    assert result["ok"] is True
    assert result["attempted"] == 1
    assert result["written"] == 1
    assert result["errors"] == []

    slug = report_center._slug_for_path(report_path, repo_root=repo_root)
    analysis_page = obs_dir / "reports" / "claude_analysis" / f"{slug}.md"
    assert analysis_page.exists()
    page_text = analysis_page.read_text(encoding="utf-8")
    assert "Claude Analysis" in page_text
    assert "Verdict: partial risk." in page_text

    index_payload = json.loads((obs_dir / "reports" / "claude_analysis" / "_index.json").read_text(encoding="utf-8"))
    entries = index_payload.get("entries") or {}
    assert entries.get(slug, {}).get("status") == "analyzed"


def test_analyze_reports_with_claude_respects_report_filter(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    obs_dir = tmp_path / "vault" / "_observatory"
    first = repo_root / "docs" / "reports" / "first.md"
    second = repo_root / "reports" / "second.md"
    _write(first, "# First\n")
    _write(second, "# Second\n")

    monkeypatch.setattr(llm, "ask_claude", lambda *args, **kwargs: "analysis")

    result = report_center.analyze_reports_with_claude(
        obs_dir=obs_dir,
        repo_root=repo_root,
        max_reports=10,
        report_paths=["docs/reports/first.md"],
        overwrite=True,
    )

    assert result["attempted"] == 1
    assert result["written"] == 1

    first_slug = report_center._slug_for_path(first, repo_root=repo_root)
    second_slug = report_center._slug_for_path(second, repo_root=repo_root)
    assert (obs_dir / "reports" / "claude_analysis" / f"{first_slug}.md").exists()
    assert not (obs_dir / "reports" / "claude_analysis" / f"{second_slug}.md").exists()
