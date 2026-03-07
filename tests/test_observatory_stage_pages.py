"""Tests for lib/observatory/stage_pages.py

Covers:
- _header(): heading format, breadcrumb links, upstream/downstream,
  no-upstream and no-downstream fallbacks, purpose text
- _health_table(): table structure, metric rows, health_badge applied
- _source_files(): lib path present, state file paths present
- generate_all_stage_pages(): yields exactly 12 items, correct filenames
  (01- through 12-), all content strings, each starts with a heading
- Per-generator spot-checks: each _gen_* produces content containing its
  stage name, health table, and source files section
"""

from __future__ import annotations

import pytest

from lib.observatory.stage_pages import (
    _header,
    _health_table,
    _source_files,
    generate_all_stage_pages,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_data() -> dict:
    return {i: {} for i in range(1, 13)}


EXPECTED_FILENAMES = [
    "01-event-capture.md",
    "02-queue.md",
    "03-pipeline.md",
    "04-memory-capture.md",
    "05-meta-ralph.md",
    "06-cognitive-learner.md",
    "07-eidos.md",
    "08-advisory.md",
    "09-promotion.md",
    "10-chips.md",
    "11-predictions.md",
    "12-tuneables.md",
]


# ---------------------------------------------------------------------------
# _header
# ---------------------------------------------------------------------------

def test_header_contains_stage_number():
    result = _header(3, "Pipeline", "Purpose text", [2], [4])
    assert "Stage 3" in result


def test_header_contains_name():
    result = _header(3, "Pipeline", "Purpose text", [2], [4])
    assert "Pipeline" in result


def test_header_contains_purpose():
    result = _header(3, "Pipeline", "Does stuff.", [2], [4])
    assert "Does stuff." in result


def test_header_contains_flow_link():
    result = _header(1, "Event Capture", "Captures events.", [], [2])
    assert "Intelligence Flow" in result


def test_header_upstream_empty_shows_external():
    result = _header(1, "Event Capture", "Purpose", [], [2])
    assert "External events" in result


def test_header_downstream_empty_shows_end_of_flow():
    result = _header(9, "Promotion", "Purpose", [8], [])
    assert "End of flow" in result


def test_header_upstream_links_included():
    result = _header(3, "Pipeline", "Purpose", [1, 2], [4])
    # Both upstream stages should appear as sibling links
    assert "01-event-capture" in result or "Event Capture" in result
    assert "02-queue" in result or "Queue" in result


def test_header_downstream_links_included():
    result = _header(2, "Queue", "Purpose", [1], [3])
    assert "03-pipeline" in result or "Pipeline" in result


def test_header_returns_string():
    assert isinstance(_header(1, "Name", "Purpose", [], []), str)


def test_header_has_markdown_heading():
    result = _header(5, "Meta-Ralph", "Purpose", [4], [6])
    assert result.startswith("# Stage 5")


# ---------------------------------------------------------------------------
# _health_table
# ---------------------------------------------------------------------------

def test_health_table_has_health_heading():
    result = _health_table([("CPU", "5%", "healthy")])
    assert "## Health" in result


def test_health_table_has_header_row():
    result = _health_table([("Metric", "Value", "healthy")])
    assert "| Metric | Value | Status |" in result


def test_health_table_has_separator_row():
    result = _health_table([("CPU", "5%", "healthy")])
    assert "|--------|-------|--------|" in result


def test_health_table_includes_metric():
    result = _health_table([("Queue depth", "100", "healthy")])
    assert "Queue depth" in result


def test_health_table_includes_value():
    result = _health_table([("Metric", "42 items", "healthy")])
    assert "42 items" in result


def test_health_table_applies_health_badge_warning():
    result = _health_table([("Status", "bad", "warning")])
    assert "WARNING" in result


def test_health_table_applies_health_badge_critical():
    result = _health_table([("Status", "bad", "critical")])
    assert "CRITICAL" in result


def test_health_table_applies_health_badge_healthy():
    result = _health_table([("Status", "ok", "healthy")])
    assert "healthy" in result


def test_health_table_multiple_rows():
    rows = [("A", "1", "healthy"), ("B", "2", "warning"), ("C", "3", "critical")]
    result = _health_table(rows)
    assert "A" in result
    assert "B" in result
    assert "C" in result


def test_health_table_returns_string():
    assert isinstance(_health_table([]), str)


# ---------------------------------------------------------------------------
# _source_files
# ---------------------------------------------------------------------------

def test_source_files_has_section_heading():
    result = _source_files("lib/foo.py", [])
    assert "## Source Files" in result


def test_source_files_contains_lib_path():
    result = _source_files("lib/pipeline.py", [])
    assert "lib/pipeline.py" in result


def test_source_files_contains_state_files():
    result = _source_files("lib/foo.py", ["queue/events.jsonl", "state.json"])
    assert "queue/events.jsonl" in result
    assert "state.json" in result


def test_source_files_state_files_prefixed_with_spark():
    result = _source_files("lib/foo.py", ["myfile.json"])
    assert "~/.spark/myfile.json" in result


def test_source_files_returns_string():
    assert isinstance(_source_files("lib/x.py", []), str)


def test_source_files_empty_state_files():
    result = _source_files("lib/foo.py", [])
    assert "lib/foo.py" in result


# ---------------------------------------------------------------------------
# generate_all_stage_pages — structure
# ---------------------------------------------------------------------------

def test_generate_all_stage_pages_yields_12_items():
    pages = list(generate_all_stage_pages(_empty_data()))
    assert len(pages) == 12


def test_generate_all_stage_pages_correct_filenames():
    filenames = [fn for fn, _ in generate_all_stage_pages(_empty_data())]
    assert filenames == EXPECTED_FILENAMES


def test_generate_all_stage_pages_all_content_is_string():
    for filename, content in generate_all_stage_pages(_empty_data()):
        assert isinstance(content, str), f"{filename} content is not a string"


def test_generate_all_stage_pages_content_nonempty():
    for filename, content in generate_all_stage_pages(_empty_data()):
        assert len(content) > 0, f"{filename} content is empty"


def test_generate_all_stage_pages_each_starts_with_heading():
    for filename, content in generate_all_stage_pages(_empty_data()):
        assert content.startswith("# Stage "), f"{filename} doesn't start with heading"


def test_generate_all_stage_pages_filenames_start_with_correct_prefix():
    for i, (filename, _) in enumerate(generate_all_stage_pages(_empty_data()), 1):
        assert filename.startswith(f"{i:02d}-"), f"Stage {i} filename wrong: {filename}"


def test_generate_all_stage_pages_all_filenames_end_with_md():
    for filename, _ in generate_all_stage_pages(_empty_data()):
        assert filename.endswith(".md")


def test_generate_all_stage_pages_safe_with_empty_data():
    # Should not raise
    pages = list(generate_all_stage_pages(_empty_data()))
    assert len(pages) == 12


# ---------------------------------------------------------------------------
# Per-stage content spot-checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stage_num,stage_name", [
    (1, "Event Capture"),
    (2, "Queue"),
    (3, "Pipeline"),
    (4, "Memory Capture"),
    (5, "Meta-Ralph"),
    (6, "Cognitive Learner"),
    (7, "EIDOS"),
    (8, "Advisory"),
    (9, "Promotion"),
    (10, "Chips"),
    (11, "Predictions"),
    (12, "Tuneables"),
])
def test_stage_page_contains_stage_name(stage_num, stage_name):
    pages = dict(generate_all_stage_pages(_empty_data()))
    filename = EXPECTED_FILENAMES[stage_num - 1]
    assert stage_name in pages[filename]


@pytest.mark.parametrize("filename", EXPECTED_FILENAMES)
def test_stage_page_contains_health_table(filename):
    pages = dict(generate_all_stage_pages(_empty_data()))
    assert "## Health" in pages[filename]


@pytest.mark.parametrize("filename", EXPECTED_FILENAMES)
def test_stage_page_contains_source_files_section(filename):
    pages = dict(generate_all_stage_pages(_empty_data()))
    assert "## Source Files" in pages[filename]


@pytest.mark.parametrize("filename", EXPECTED_FILENAMES)
def test_stage_page_contains_flow_link(filename):
    pages = dict(generate_all_stage_pages(_empty_data()))
    assert "Intelligence Flow" in pages[filename]


# ---------------------------------------------------------------------------
# Stage pages reflect data values
# ---------------------------------------------------------------------------

def test_queue_page_reflects_pending_count():
    data = _empty_data()
    data[2] = {"estimated_pending": 8888}
    pages = dict(generate_all_stage_pages(data))
    assert "8,888" in pages["02-queue.md"]


def test_pipeline_page_reflects_events_processed():
    data = _empty_data()
    data[3] = {"total_events_processed": 54321}
    pages = dict(generate_all_stage_pages(data))
    assert "54,321" in pages["03-pipeline.md"]


def test_cognitive_page_reflects_insight_count():
    data = _empty_data()
    data[6] = {"total_insights": 999, "category_distribution": {}, "top_insights": []}
    pages = dict(generate_all_stage_pages(data))
    assert "999" in pages["06-cognitive-learner.md"]


def test_eidos_page_db_missing_shows_status():
    data = _empty_data()
    data[7] = {"db_exists": False, "recent_distillations": []}
    pages = dict(generate_all_stage_pages(data))
    assert "not found" in pages["07-eidos.md"] or "MISSING" in pages["07-eidos.md"]


def test_queue_overflow_section_appears_when_active():
    data = _empty_data()
    data[2] = {"overflow_exists": True, "overflow_size": 1024}
    pages = dict(generate_all_stage_pages(data))
    assert "Overflow" in pages["02-queue.md"]
