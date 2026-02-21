"""Tests for lib/score_reporter.py

Covers:
- _infer_theme(): tool field takes priority, keyword group matching for all
  five themes, falls back to "general" when nothing matches
- compute_kpis(): counts (total/acted/skipped/unresolved/positive/negative),
  action_rate_pct, helpful_rate_pct, median_time_to_action_s, top_ignored
  advisory themes — correct with empty input and realistic data
- build_report(): has generated_at, kpis, items keys; generated_at is numeric
- write_report(): creates the file, content is valid JSON, returned path matches
- render_terminal_summary(): contains key label strings, reflects counts,
  shows median_time line when latency present, shows top_ignored when present
"""

from __future__ import annotations

import json
import time

import pytest

from lib.score_reporter import (
    _infer_theme,
    build_report,
    compute_kpis,
    render_terminal_summary,
    write_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(status="acted", effect="positive", latency_s=1.0, tool=None, recommendation=""):
    d = {
        "status": status,
        "effect": effect,
        "latency_s": latency_s,
        "recommendation": recommendation,
    }
    if tool is not None:
        d["tool"] = tool
    return d


def _empty_kpis():
    return compute_kpis([])


# ---------------------------------------------------------------------------
# _infer_theme — tool field
# ---------------------------------------------------------------------------

def test_infer_theme_tool_field_takes_priority():
    assert _infer_theme({"tool": "bash", "recommendation": "retry on failure"}) == "tool:bash"


def test_infer_theme_tool_prefixed_with_tool_colon():
    assert _infer_theme({"tool": "grep"}).startswith("tool:")


def test_infer_theme_tool_name_lowercased():
    assert _infer_theme({"tool": "BASH"}) == "tool:bash"


def test_infer_theme_empty_tool_falls_through_to_keywords():
    result = _infer_theme({"tool": "", "recommendation": "write a test"})
    assert result == "testing"


def test_infer_theme_none_tool_falls_through():
    result = _infer_theme({"tool": None, "recommendation": "run pytest"})
    assert result == "testing"


# ---------------------------------------------------------------------------
# _infer_theme — keyword groups
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected_theme", [
    ("write a test for this function", "testing"),
    ("add a pytest fixture", "testing"),
    ("assert the return value", "testing"),
    ("set up ci pipeline", "testing"),
    ("retry after timeout", "reliability"),
    ("handle the timeout gracefully", "reliability"),
    ("fix the failure", "reliability"),
    ("catch the error early", "reliability"),
    ("improve stability", "reliability"),
    ("reduce latency", "performance"),
    ("this is slow", "performance"),
    ("improve perf", "performance"),
    ("reduce memory usage", "performance"),
    ("add a cache", "performance"),
    ("manage state transitions", "state"),
    ("check the constraint", "state"),
    ("handle auth token", "security"),
    ("rotate the secret", "security"),
    ("check permission", "security"),
])
def test_infer_theme_keyword_groups(text, expected_theme):
    assert _infer_theme({"recommendation": text}) == expected_theme


def test_infer_theme_no_match_returns_general():
    assert _infer_theme({"recommendation": "do something unrelated"}) == "general"


def test_infer_theme_empty_dict_returns_general():
    assert _infer_theme({}) == "general"


# ---------------------------------------------------------------------------
# compute_kpis — empty list
# ---------------------------------------------------------------------------

def test_compute_kpis_empty_returns_dict():
    assert isinstance(_empty_kpis(), dict)


def test_compute_kpis_empty_total_zero():
    assert _empty_kpis()["total_advisories"] == 0


def test_compute_kpis_empty_acted_zero():
    assert _empty_kpis()["acted"] == 0


def test_compute_kpis_empty_action_rate_zero():
    assert _empty_kpis()["action_rate_pct"] == 0.0


def test_compute_kpis_empty_helpful_rate_zero():
    assert _empty_kpis()["helpful_rate_pct"] == 0.0


def test_compute_kpis_empty_median_latency_none():
    assert _empty_kpis()["median_time_to_action_s"] is None


def test_compute_kpis_empty_top_ignored_empty_list():
    assert _empty_kpis()["top_ignored_advisory_themes"] == []


# ---------------------------------------------------------------------------
# compute_kpis — counts
# ---------------------------------------------------------------------------

def test_compute_kpis_total_count():
    items = [_item("acted"), _item("skipped"), _item("unresolved")]
    assert compute_kpis(items)["total_advisories"] == 3


def test_compute_kpis_acted_count():
    items = [_item("acted"), _item("acted"), _item("skipped")]
    assert compute_kpis(items)["acted"] == 2


def test_compute_kpis_skipped_count():
    items = [_item("acted"), _item("skipped"), _item("skipped")]
    assert compute_kpis(items)["skipped"] == 2


def test_compute_kpis_unresolved_count():
    items = [_item("unresolved"), _item("acted")]
    assert compute_kpis(items)["unresolved"] == 1


def test_compute_kpis_positive_count():
    items = [_item(effect="positive"), _item(effect="positive"), _item(effect="negative")]
    assert compute_kpis(items)["positive"] == 2


def test_compute_kpis_negative_count():
    items = [_item(effect="negative"), _item(effect="positive")]
    assert compute_kpis(items)["negative"] == 1


# ---------------------------------------------------------------------------
# compute_kpis — rates
# ---------------------------------------------------------------------------

def test_compute_kpis_action_rate_100_pct():
    items = [_item("acted"), _item("acted")]
    assert compute_kpis(items)["action_rate_pct"] == 100.0


def test_compute_kpis_action_rate_50_pct():
    items = [_item("acted"), _item("skipped")]
    assert compute_kpis(items)["action_rate_pct"] == 50.0


def test_compute_kpis_helpful_rate_100_pct():
    items = [_item("acted", "positive"), _item("acted", "positive")]
    assert compute_kpis(items)["helpful_rate_pct"] == 100.0


def test_compute_kpis_helpful_rate_50_pct():
    items = [_item("acted", "positive"), _item("acted", "negative")]
    assert compute_kpis(items)["helpful_rate_pct"] == 50.0


def test_compute_kpis_helpful_rate_zero_when_no_acted():
    items = [_item("skipped", "positive")]
    assert compute_kpis(items)["helpful_rate_pct"] == 0.0


# ---------------------------------------------------------------------------
# compute_kpis — median latency
# ---------------------------------------------------------------------------

def test_compute_kpis_median_latency_single():
    items = [_item("acted", latency_s=5.0)]
    assert compute_kpis(items)["median_time_to_action_s"] == 5.0


def test_compute_kpis_median_latency_multiple():
    items = [_item("acted", latency_s=1.0), _item("acted", latency_s=3.0), _item("acted", latency_s=5.0)]
    assert compute_kpis(items)["median_time_to_action_s"] == 3.0


def test_compute_kpis_median_latency_ignores_non_acted():
    # skipped item has latency but shouldn't count
    items = [_item("acted", latency_s=10.0), _item("skipped", latency_s=1.0)]
    assert compute_kpis(items)["median_time_to_action_s"] == 10.0


def test_compute_kpis_median_latency_none_when_no_latency_data():
    items = [_item("skipped"), _item("unresolved")]
    assert compute_kpis(items)["median_time_to_action_s"] is None


def test_compute_kpis_median_latency_skips_none_latency():
    # acted item with None latency_s should be excluded
    items = [_item("acted", latency_s=None), _item("acted", latency_s=4.0)]
    result = compute_kpis(items)["median_time_to_action_s"]
    assert result == 4.0


# ---------------------------------------------------------------------------
# compute_kpis — top ignored themes
# ---------------------------------------------------------------------------

def test_compute_kpis_top_ignored_excludes_acted():
    items = [_item("acted", recommendation="write a test"), _item("skipped", recommendation="write a test")]
    themes = [t["theme"] for t in compute_kpis(items)["top_ignored_advisory_themes"]]
    assert "testing" in themes


def test_compute_kpis_top_ignored_max_5():
    items = [
        _item("skipped", recommendation="write a test"),
        _item("skipped", recommendation="retry on failure"),
        _item("skipped", recommendation="reduce latency"),
        _item("skipped", recommendation="manage state"),
        _item("skipped", recommendation="auth token"),
        _item("skipped", recommendation="do something general"),
    ]
    assert len(compute_kpis(items)["top_ignored_advisory_themes"]) <= 5


def test_compute_kpis_top_ignored_has_theme_and_count_keys():
    items = [_item("skipped", recommendation="write a test")]
    entry = compute_kpis(items)["top_ignored_advisory_themes"][0]
    assert "theme" in entry and "count" in entry


def test_compute_kpis_top_ignored_count_is_int():
    items = [_item("skipped", recommendation="write a test")]
    entry = compute_kpis(items)["top_ignored_advisory_themes"][0]
    assert isinstance(entry["count"], int)


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------

def test_build_report_returns_dict():
    assert isinstance(build_report([]), dict)


def test_build_report_has_generated_at():
    assert "generated_at" in build_report([])


def test_build_report_generated_at_is_numeric():
    ts = build_report([])["generated_at"]
    assert isinstance(ts, float)


def test_build_report_generated_at_is_recent():
    ts = build_report([])["generated_at"]
    assert abs(ts - time.time()) < 5


def test_build_report_has_kpis():
    assert "kpis" in build_report([])


def test_build_report_has_items():
    assert "items" in build_report([])


def test_build_report_items_preserved():
    items = [_item()]
    assert build_report(items)["items"] == items


def test_build_report_kpis_is_dict():
    assert isinstance(build_report([])["kpis"], dict)


# ---------------------------------------------------------------------------
# write_report
# ---------------------------------------------------------------------------

def test_write_report_creates_file(tmp_path):
    report = build_report([])
    out = tmp_path / "report.json"
    write_report(report, out)
    assert out.exists()


def test_write_report_returns_path(tmp_path):
    report = build_report([])
    out = tmp_path / "report.json"
    returned = write_report(report, out)
    assert returned == out


def test_write_report_content_is_valid_json(tmp_path):
    report = build_report([_item()])
    out = tmp_path / "report.json"
    write_report(report, out)
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert "kpis" in parsed


def test_write_report_creates_parent_dirs(tmp_path):
    report = build_report([])
    out = tmp_path / "nested" / "deep" / "report.json"
    write_report(report, out)
    assert out.exists()


def test_write_report_content_utf8(tmp_path):
    report = build_report([])
    report["note"] = "caf\u00e9"
    out = tmp_path / "r.json"
    write_report(report, out)
    content = out.read_text(encoding="utf-8")
    assert "caf\u00e9" in content


# ---------------------------------------------------------------------------
# render_terminal_summary
# ---------------------------------------------------------------------------

def test_render_terminal_summary_returns_string():
    assert isinstance(render_terminal_summary(build_report([])), str)


def test_render_terminal_summary_has_title():
    assert "Advice-to-Action" in render_terminal_summary(build_report([]))


def test_render_terminal_summary_has_total():
    assert "total=" in render_terminal_summary(build_report([]))


def test_render_terminal_summary_has_acted():
    assert "acted=" in render_terminal_summary(build_report([]))


def test_render_terminal_summary_has_action_rate():
    assert "action_rate=" in render_terminal_summary(build_report([]))


def test_render_terminal_summary_reflects_counts():
    items = [_item("acted"), _item("skipped"), _item("unresolved")]
    result = render_terminal_summary(build_report(items))
    assert "total=3" in result
    assert "acted=1" in result
    assert "skipped=1" in result
    assert "unresolved=1" in result


def test_render_terminal_summary_no_median_line_when_no_latency():
    result = render_terminal_summary(build_report([_item("skipped")]))
    assert "median_time_to_action" not in result


def test_render_terminal_summary_has_median_line_when_acted():
    items = [_item("acted", latency_s=2.5)]
    result = render_terminal_summary(build_report(items))
    assert "median_time_to_action" in result


def test_render_terminal_summary_has_top_ignored_when_present():
    items = [_item("skipped", recommendation="write a test")]
    result = render_terminal_summary(build_report(items))
    assert "top_ignored_themes" in result


def test_render_terminal_summary_no_top_ignored_when_all_acted():
    items = [_item("acted")]
    result = render_terminal_summary(build_report(items))
    assert "top_ignored_themes" not in result


def test_render_terminal_summary_empty_report_safe():
    result = render_terminal_summary({})
    assert isinstance(result, str)
    assert len(result) > 0
