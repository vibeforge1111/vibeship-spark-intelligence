"""Tests for lib/observatory/flow_dashboard.py

Covers:
- _stage_description(): all 12 stages return non-empty strings, unknown → ""
- _health_status(): queue healthy/warning/critical thresholds, pipeline
  timing thresholds, all rows have 3 elements, returns list of tuples
- _mermaid_diagram(): contains mermaid fences, flowchart directive,
  reflects data values in output
- generate_flow_dashboard(): required section headings, stage links present,
  mermaid block included, data values surfaced in output, empty data safe
"""

from __future__ import annotations

import pytest

from lib.observatory.flow_dashboard import (
    _health_status,
    _mermaid_diagram,
    _stage_description,
    generate_flow_dashboard,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_data() -> dict:
    """Minimal data dict with all 12 stages as empty dicts."""
    return {i: {} for i in range(1, 13)}


def _data_with(**kwargs) -> dict:
    """Build a data dict with stage-keyed overrides."""
    d = _empty_data()
    for stage, values in kwargs.items():
        d[int(stage)] = values
    return d


# ---------------------------------------------------------------------------
# _stage_description
# ---------------------------------------------------------------------------

def test_stage_description_all_12_non_empty():
    for i in range(1, 13):
        assert _stage_description(i) != "", f"Stage {i} description is empty"


def test_stage_description_unknown_returns_empty():
    assert _stage_description(99) == ""


def test_stage_description_returns_string():
    for i in range(1, 13):
        assert isinstance(_stage_description(i), str)


@pytest.mark.parametrize("stage,keyword", [
    (1, "Hook"),
    (2, "buffer"),
    (3, "Batch"),
    (4, "Importance"),
    (5, "Quality"),
    (6, "Insight"),
    (7, "Episode"),
    (8, "Retrieval"),
    (9, "Target"),
    (10, "Domain"),
    (11, "Outcomes"),
    (12, "Configuration"),
])
def test_stage_description_contains_expected_keyword(stage, keyword):
    assert keyword.lower() in _stage_description(stage).lower()


# ---------------------------------------------------------------------------
# _health_status — structure
# ---------------------------------------------------------------------------

def test_health_status_returns_list():
    assert isinstance(_health_status(_empty_data()), list)


def test_health_status_each_row_has_3_elements():
    rows = _health_status(_empty_data())
    for row in rows:
        assert len(row) == 3, f"Row has {len(row)} elements: {row}"


def test_health_status_row_elements_are_strings():
    rows = _health_status(_empty_data())
    for metric, value, status in rows:
        assert isinstance(metric, str)
        assert isinstance(value, str)
        assert isinstance(status, str)


def test_health_status_nonempty():
    assert len(_health_status(_empty_data())) > 0


# ---------------------------------------------------------------------------
# _health_status — queue thresholds
# ---------------------------------------------------------------------------

def test_health_status_queue_healthy_below_5000():
    data = _data_with(**{"2": {"estimated_pending": 100}})
    rows = _health_status(data)
    queue_row = next(r for r in rows if "Queue" in r[0])
    assert queue_row[2] == "healthy"


def test_health_status_queue_warning_5000_to_20000():
    data = _data_with(**{"2": {"estimated_pending": 10000}})
    rows = _health_status(data)
    queue_row = next(r for r in rows if "Queue" in r[0])
    assert queue_row[2] == "warning"


def test_health_status_queue_critical_above_20000():
    data = _data_with(**{"2": {"estimated_pending": 25000}})
    rows = _health_status(data)
    queue_row = next(r for r in rows if "Queue" in r[0])
    assert queue_row[2] == "critical"


# ---------------------------------------------------------------------------
# _health_status — pipeline timing
# ---------------------------------------------------------------------------

def test_health_status_pipeline_healthy_recent():
    import time
    data = _data_with(**{"3": {"last_cycle_ts": time.time() - 30}})
    rows = _health_status(data)
    pipeline_row = next(r for r in rows if "pipeline" in r[0].lower())
    assert pipeline_row[2] == "healthy"


def test_health_status_pipeline_warning_5_to_10_min():
    import time
    data = _data_with(**{"3": {"last_cycle_ts": time.time() - 400}})
    rows = _health_status(data)
    pipeline_row = next(r for r in rows if "pipeline" in r[0].lower())
    assert pipeline_row[2] == "warning"


def test_health_status_pipeline_critical_over_10_min():
    import time
    data = _data_with(**{"3": {"last_cycle_ts": time.time() - 700}})
    rows = _health_status(data)
    pipeline_row = next(r for r in rows if "pipeline" in r[0].lower())
    assert pipeline_row[2] == "critical"


def test_health_status_pipeline_healthy_when_no_ts():
    # No timestamp → no time comparison → defaults to healthy
    data = _data_with(**{"3": {}})
    rows = _health_status(data)
    pipeline_row = next(r for r in rows if "pipeline" in r[0].lower())
    assert pipeline_row[2] == "healthy"


# ---------------------------------------------------------------------------
# _mermaid_diagram
# ---------------------------------------------------------------------------

def test_mermaid_diagram_returns_string():
    assert isinstance(_mermaid_diagram(_empty_data()), str)


def test_mermaid_diagram_has_opening_fence():
    assert "```mermaid" in _mermaid_diagram(_empty_data())


def test_mermaid_diagram_has_closing_fence():
    assert _mermaid_diagram(_empty_data()).strip().endswith("```")


def test_mermaid_diagram_has_flowchart_directive():
    assert "flowchart" in _mermaid_diagram(_empty_data())


def test_mermaid_diagram_reflects_queue_pending():
    data = _data_with(**{"2": {"estimated_pending": 9999}})
    assert "9,999" in _mermaid_diagram(data)


def test_mermaid_diagram_reflects_events_processed():
    data = _data_with(**{"3": {"total_events_processed": 12345}})
    assert "12,345" in _mermaid_diagram(data)


def test_mermaid_diagram_safe_with_empty_data():
    result = _mermaid_diagram(_empty_data())
    assert "```mermaid" in result
    assert "```" in result


# ---------------------------------------------------------------------------
# generate_flow_dashboard — section headings
# ---------------------------------------------------------------------------

def test_generate_flow_dashboard_returns_string():
    assert isinstance(generate_flow_dashboard(_empty_data()), str)


def test_generate_flow_dashboard_has_main_heading():
    assert "# Spark Intelligence Observatory" in generate_flow_dashboard(_empty_data())


def test_generate_flow_dashboard_has_system_health_section():
    assert "## System Health" in generate_flow_dashboard(_empty_data())


def test_generate_flow_dashboard_has_intelligence_flow_section():
    assert "## Intelligence Flow" in generate_flow_dashboard(_empty_data())


def test_generate_flow_dashboard_has_stage_detail_pages_section():
    assert "## Stage Detail Pages" in generate_flow_dashboard(_empty_data())


def test_generate_flow_dashboard_has_how_data_flows_section():
    assert "## How Data Flows" in generate_flow_dashboard(_empty_data())


def test_generate_flow_dashboard_has_quick_links_section():
    assert "## Quick Links" in generate_flow_dashboard(_empty_data())


# ---------------------------------------------------------------------------
# generate_flow_dashboard — content
# ---------------------------------------------------------------------------

def test_generate_flow_dashboard_contains_mermaid_block():
    assert "```mermaid" in generate_flow_dashboard(_empty_data())


def test_generate_flow_dashboard_has_12_stage_links():
    result = generate_flow_dashboard(_empty_data())
    # Each stage link starts with [[stages/
    count = result.count("[[stages/")
    assert count >= 12


def test_generate_flow_dashboard_reflects_events_processed():
    data = _data_with(**{"3": {"total_events_processed": 77777}})
    assert "77,777" in generate_flow_dashboard(data)


def test_generate_flow_dashboard_reflects_insights_created():
    data = _data_with(**{"3": {"total_insights_created": 42}})
    assert "42" in generate_flow_dashboard(data)


def test_generate_flow_dashboard_health_table_has_pipe_chars():
    # Markdown table rows have | separators
    result = generate_flow_dashboard(_empty_data())
    assert "| Metric | Value | Status |" in result


def test_generate_flow_dashboard_safe_with_empty_data():
    # Must not raise
    result = generate_flow_dashboard(_empty_data())
    assert len(result) > 0


def test_generate_flow_dashboard_watchtower_link_present():
    assert "watchtower" in generate_flow_dashboard(_empty_data())
