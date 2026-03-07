"""Tests for lib/markdown_writer.py — cognitive learning markdown output."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

import lib.markdown_writer as mw
from lib.markdown_writer import (
    MarkdownWriter,
    _generate_id,
    _category_to_area,
    _category_to_learning_category,
    _reliability_to_priority,
    write_learning,
    write_error,
    write_all_learnings,
    get_markdown_writer,
)


# ---------------------------------------------------------------------------
# Minimal stubs for CognitiveInsight / CognitiveCategory
# ---------------------------------------------------------------------------


class _FakeCategory:
    """Mirrors CognitiveCategory enum members used in mapping dicts."""

    def __init__(self, value: str):
        self.value = value

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        return isinstance(other, _FakeCategory) and self.value == other.value


# Build category constants matching CognitiveCategory enum values
_CATS = {
    name: _FakeCategory(name.lower())
    for name in [
        "SELF_AWARENESS", "USER_UNDERSTANDING", "WISDOM", "REASONING",
        "CONTEXT", "META_LEARNING", "COMMUNICATION", "CREATIVITY",
    ]
}


def _fake_insight(
    category_name: str = "WISDOM",
    insight: str = "Use simple solutions first.",
    context: str = "Context description",
    reliability: float = 0.8,
    evidence: Optional[List[str]] = None,
    counter_examples: Optional[List[str]] = None,
    times_validated: int = 2,
    times_contradicted: int = 0,
    created_at: str = "2026-01-01T00:00:00",
) -> MagicMock:
    obj = MagicMock()
    obj.category = _CATS[category_name]
    obj.insight = insight
    obj.context = context
    obj.reliability = reliability
    obj.evidence = evidence if evidence is not None else ["Observed in 3 sessions"]
    obj.counter_examples = counter_examples if counter_examples is not None else []
    obj.times_validated = times_validated
    obj.times_contradicted = times_contradicted
    obj.created_at = created_at
    return obj


def _patch_category_maps(monkeypatch):
    """Patch the mapping dicts to use _FakeCategory keys."""
    monkeypatch.setattr(mw, "_category_to_area", lambda cat: {
        _CATS["SELF_AWARENESS"]: "config",
        _CATS["USER_UNDERSTANDING"]: "docs",
        _CATS["WISDOM"]: "docs",
        _CATS["REASONING"]: "backend",
        _CATS["CONTEXT"]: "config",
        _CATS["META_LEARNING"]: "docs",
        _CATS["COMMUNICATION"]: "docs",
        _CATS["CREATIVITY"]: "frontend",
    }.get(cat, "docs"))
    monkeypatch.setattr(mw, "_category_to_learning_category", lambda cat: {
        _CATS["SELF_AWARENESS"]: "self_awareness",
        _CATS["USER_UNDERSTANDING"]: "user_preference",
        _CATS["WISDOM"]: "best_practice",
        _CATS["REASONING"]: "reasoning_pattern",
        _CATS["CONTEXT"]: "context_rule",
        _CATS["META_LEARNING"]: "knowledge_gap",
        _CATS["COMMUNICATION"]: "correction",
        _CATS["CREATIVITY"]: "best_practice",
    }.get(cat, "observation"))


def _make_writer(tmp_path: Path) -> MarkdownWriter:
    return MarkdownWriter(project_dir=tmp_path)


# ---------------------------------------------------------------------------
# _generate_id
# ---------------------------------------------------------------------------


def test_generate_id_prefix():
    id_val = _generate_id("LRN")
    assert id_val.startswith("LRN-")


def test_generate_id_format():
    id_val = _generate_id("ERR")
    # Should match ERR-YYYYMMDD-XXX
    assert re.match(r"^ERR-\d{8}-[A-Z0-9]{3}$", id_val)


def test_generate_id_unique():
    ids = {_generate_id("LRN") for _ in range(20)}
    # IDs have random suffix — expect reasonable uniqueness
    assert len(ids) > 10


# ---------------------------------------------------------------------------
# MarkdownWriter.__init__ / _ensure_dir
# ---------------------------------------------------------------------------


def test_writer_creates_learnings_dir(tmp_path):
    writer = _make_writer(tmp_path)
    assert (tmp_path / ".learnings").is_dir()


def test_writer_creates_learnings_md(tmp_path):
    writer = _make_writer(tmp_path)
    assert (tmp_path / ".learnings" / "LEARNINGS.md").exists()


def test_writer_creates_errors_md(tmp_path):
    writer = _make_writer(tmp_path)
    assert (tmp_path / ".learnings" / "ERRORS.md").exists()


def test_writer_does_not_overwrite_existing_files(tmp_path):
    (tmp_path / ".learnings").mkdir()
    existing = tmp_path / ".learnings" / "LEARNINGS.md"
    existing.write_text("# My custom content\n", encoding="utf-8")
    _make_writer(tmp_path)
    assert existing.read_text() == "# My custom content\n"


def test_writer_custom_learnings_dir(tmp_path):
    writer = MarkdownWriter(project_dir=tmp_path, learnings_dir="custom_dir")
    assert (tmp_path / "custom_dir").is_dir()


# ---------------------------------------------------------------------------
# _learnings_header / _errors_header
# ---------------------------------------------------------------------------


def test_learnings_header_content(tmp_path):
    writer = _make_writer(tmp_path)
    header = writer._learnings_header()
    assert "Learnings" in header
    assert "LRN-" in header


def test_errors_header_content(tmp_path):
    writer = _make_writer(tmp_path)
    header = writer._errors_header()
    assert "Errors" in header
    assert "ERR-" in header


# ---------------------------------------------------------------------------
# insight_to_markdown
# ---------------------------------------------------------------------------


def test_insight_to_markdown_contains_lrn_id(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)
    insight = _fake_insight()
    md = writer.insight_to_markdown(insight)
    assert re.search(r"\[LRN-\d{8}-[A-Z0-9]{3}\]", md)


def test_insight_to_markdown_contains_insight_text(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)
    insight = _fake_insight(insight="Always validate at system boundaries.")
    md = writer.insight_to_markdown(insight)
    assert "Always validate at system boundaries." in md


def test_insight_to_markdown_contains_context(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)
    insight = _fake_insight(context="Seen when parsing user input")
    md = writer.insight_to_markdown(insight)
    assert "Seen when parsing user input" in md


def test_insight_to_markdown_evidence_listed(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)
    insight = _fake_insight(evidence=["Example A", "Example B"])
    md = writer.insight_to_markdown(insight)
    assert "Example A" in md
    assert "Example B" in md


def test_insight_to_markdown_max_5_evidence(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)
    insight = _fake_insight(evidence=[f"ev{i}" for i in range(10)])
    md = writer.insight_to_markdown(insight)
    # Only up to 5 evidence items
    found = re.findall(r"- ev\d+", md)
    assert len(found) <= 5


def test_insight_to_markdown_counter_examples(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)
    insight = _fake_insight(counter_examples=["Counter 1"])
    md = writer.insight_to_markdown(insight)
    assert "Counter 1" in md


def test_insight_to_markdown_reliability_percentage(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)
    insight = _fake_insight(reliability=0.75)
    md = writer.insight_to_markdown(insight)
    assert "75%" in md


def test_insight_to_markdown_times_validated(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)
    insight = _fake_insight(times_validated=7)
    md = writer.insight_to_markdown(insight)
    assert "7" in md


def test_insight_to_markdown_no_evidence_placeholder(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)
    insight = _fake_insight(evidence=[])
    md = writer.insight_to_markdown(insight)
    assert "Initial observation" in md


# ---------------------------------------------------------------------------
# error_to_markdown
# ---------------------------------------------------------------------------


def test_error_to_markdown_contains_err_id(tmp_path):
    writer = _make_writer(tmp_path)
    md = writer.error_to_markdown("edit_tool", "File not found", {})
    assert re.search(r"\[ERR-\d{8}-[A-Z0-9]{3}\]", md)


def test_error_to_markdown_contains_tool_name(tmp_path):
    writer = _make_writer(tmp_path)
    md = writer.error_to_markdown("bash_tool", "Permission denied", {})
    assert "bash_tool" in md


def test_error_to_markdown_contains_error_text(tmp_path):
    writer = _make_writer(tmp_path)
    md = writer.error_to_markdown("write_tool", "Disk full", {})
    assert "Disk full" in md


def test_error_to_markdown_recovery_suggestion(tmp_path):
    writer = _make_writer(tmp_path)
    context = {"recovery_suggestion": {"approach": "Try smaller writes."}}
    md = writer.error_to_markdown("write_tool", "err", context)
    assert "Try smaller writes." in md


def test_error_to_markdown_alternative_tools(tmp_path):
    writer = _make_writer(tmp_path)
    context = {"recovery_suggestion": {"alternative_tools": ["read_tool", "glob_tool"]}}
    md = writer.error_to_markdown("write_tool", "err", context)
    assert "read_tool" in md


def test_error_to_markdown_empty_context(tmp_path):
    writer = _make_writer(tmp_path)
    md = writer.error_to_markdown("some_tool", "oops", {})
    assert "ERR-" in md


def test_error_to_markdown_truncates_long_error(tmp_path):
    writer = _make_writer(tmp_path)
    long_error = "E" * 1000
    md = writer.error_to_markdown("t", long_error, {})
    # Rendered error block should not contain more than 500 chars of the error
    error_block_match = re.search(r"```\n(.*?)\n```", md, re.DOTALL)
    if error_block_match:
        assert len(error_block_match.group(1)) <= 510  # some slack for formatting


# ---------------------------------------------------------------------------
# write_insight
# ---------------------------------------------------------------------------


def test_write_insight_appends_to_learnings_md(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)
    insight = _fake_insight()
    writer.write_insight(insight)
    content = (tmp_path / ".learnings" / "LEARNINGS.md").read_text()
    assert "LRN-" in content


def test_write_insight_returns_entry_id(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)
    insight = _fake_insight()
    entry_id = writer.write_insight(insight)
    assert entry_id.startswith("LRN-")


def test_write_insight_multiple_appends(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)
    writer.write_insight(_fake_insight(insight="Insight 1"))
    writer.write_insight(_fake_insight(insight="Insight 2"))
    content = (tmp_path / ".learnings" / "LEARNINGS.md").read_text()
    assert content.count("## [LRN-") == 2


# ---------------------------------------------------------------------------
# write_error
# ---------------------------------------------------------------------------


def test_write_error_appends_to_errors_md(tmp_path):
    writer = _make_writer(tmp_path)
    writer.write_error("tool", "something failed", {})
    content = (tmp_path / ".learnings" / "ERRORS.md").read_text()
    assert "ERR-" in content


def test_write_error_returns_entry_id(tmp_path):
    writer = _make_writer(tmp_path)
    entry_id = writer.write_error("tool", "fail", {})
    assert entry_id.startswith("ERR-")


def test_write_error_multiple_appends(tmp_path):
    writer = _make_writer(tmp_path)
    writer.write_error("t1", "err1", {})
    writer.write_error("t2", "err2", {})
    content = (tmp_path / ".learnings" / "ERRORS.md").read_text()
    assert content.count("## [ERR-") == 2


def test_write_error_none_context_handled(tmp_path):
    writer = _make_writer(tmp_path)
    # Should not raise even with None context
    entry_id = writer.write_error("tool", "err", None)
    assert entry_id.startswith("ERR-")


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


def test_get_stats_initial(tmp_path):
    writer = _make_writer(tmp_path)
    stats = writer.get_stats()
    assert stats["learnings_count"] == 0
    assert stats["errors_count"] == 0
    assert stats["dir_exists"] is True


def test_get_stats_counts_entries(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)
    writer.write_insight(_fake_insight())
    writer.write_insight(_fake_insight())
    writer.write_error("t", "e", {})
    stats = writer.get_stats()
    assert stats["learnings_count"] == 2
    assert stats["errors_count"] == 1


def test_get_stats_learnings_dir_path(tmp_path):
    writer = _make_writer(tmp_path)
    stats = writer.get_stats()
    assert str(tmp_path / ".learnings") in stats["learnings_dir"]


# ---------------------------------------------------------------------------
# write_all_insights
# ---------------------------------------------------------------------------


def test_write_all_insights_writes_new(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)

    insight1 = _fake_insight(insight="Insight A")
    insight2 = _fake_insight(insight="Insight B")

    fake_learner = MagicMock()
    fake_learner.insights = {"key_a": insight1, "key_b": insight2}
    monkeypatch.setattr(mw, "get_cognitive_learner", lambda: fake_learner)

    stats = writer.write_all_insights()
    assert stats["written"] == 2
    assert stats["skipped"] == 0


def test_write_all_insights_skips_already_written(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)

    insight1 = _fake_insight(insight="Insight A")
    fake_learner = MagicMock()
    fake_learner.insights = {"key_a": insight1}
    monkeypatch.setattr(mw, "get_cognitive_learner", lambda: fake_learner)

    writer.write_all_insights()  # first run — writes it
    stats = writer.write_all_insights()  # second run — should skip
    assert stats["written"] == 0
    assert stats["skipped"] == 1


def test_write_all_insights_updates_tracker_file(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    writer = _make_writer(tmp_path)

    insight1 = _fake_insight()
    fake_learner = MagicMock()
    fake_learner.insights = {"key_z": insight1}
    monkeypatch.setattr(mw, "get_cognitive_learner", lambda: fake_learner)

    writer.write_all_insights()
    tracker = tmp_path / ".learnings" / ".written_insights.txt"
    assert tracker.exists()
    assert "key_z" in tracker.read_text()


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def test_write_learning_function(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    monkeypatch.setattr(mw, "_markdown_writer", None)
    insight = _fake_insight()
    entry_id = write_learning(insight, project_dir=tmp_path)
    assert entry_id.startswith("LRN-")


def test_write_error_function(tmp_path, monkeypatch):
    monkeypatch.setattr(mw, "_markdown_writer", None)
    entry_id = write_error("tool", "error message", {}, project_dir=tmp_path)
    assert entry_id.startswith("ERR-")


def test_write_all_learnings_function(tmp_path, monkeypatch):
    _patch_category_maps(monkeypatch)
    monkeypatch.setattr(mw, "_markdown_writer", None)

    fake_learner = MagicMock()
    fake_learner.insights = {"k": _fake_insight()}
    monkeypatch.setattr(mw, "get_cognitive_learner", lambda: fake_learner)

    stats = write_all_learnings(project_dir=tmp_path)
    assert stats["written"] == 1


# ---------------------------------------------------------------------------
# get_markdown_writer singleton
# ---------------------------------------------------------------------------


def test_get_markdown_writer_returns_same_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(mw, "_markdown_writer", None)
    w1 = get_markdown_writer(project_dir=tmp_path)
    w2 = get_markdown_writer(project_dir=tmp_path)
    assert w1 is w2


def test_get_markdown_writer_new_project_dir_creates_new_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(mw, "_markdown_writer", None)
    dir1 = tmp_path / "p1"
    dir2 = tmp_path / "p2"
    w1 = get_markdown_writer(project_dir=dir1)
    w2 = get_markdown_writer(project_dir=dir2)
    assert w1 is not w2


# ---------------------------------------------------------------------------
# _reliability_to_priority
# ---------------------------------------------------------------------------


def test_reliability_critical():
    assert _reliability_to_priority(0.95) == "critical"


def test_reliability_high():
    assert _reliability_to_priority(0.75) == "high"


def test_reliability_medium():
    assert _reliability_to_priority(0.55) == "medium"


def test_reliability_low():
    assert _reliability_to_priority(0.3) == "low"


def test_reliability_boundary_0_9():
    assert _reliability_to_priority(0.9) == "critical"


def test_reliability_boundary_0_7():
    assert _reliability_to_priority(0.7) == "high"


def test_reliability_boundary_0_5():
    assert _reliability_to_priority(0.5) == "medium"
