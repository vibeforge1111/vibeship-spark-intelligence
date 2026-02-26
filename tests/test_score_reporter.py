"""Tests for lib/score_reporter.py — advisory auto-scoring report utilities."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from lib.score_reporter import (
    _infer_theme,
    compute_kpis,
    build_report,
    write_report,
    render_terminal_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(
    status: str = "acted",
    effect: str = "positive",
    latency_s: float = 1.0,
    recommendation: str = "",
    tool: str = "",
) -> Dict[str, Any]:
    return {
        "status": status,
        "effect": effect,
        "latency_s": latency_s,
        "recommendation": recommendation,
        "tool": tool,
    }


def _items(n: int, **kwargs) -> List[Dict[str, Any]]:
    return [_item(**kwargs) for _ in range(n)]


# ---------------------------------------------------------------------------
# _infer_theme
# ---------------------------------------------------------------------------


def test_infer_theme_tool_takes_priority():
    assert _infer_theme({"tool": "MyTool", "recommendation": "test something"}) == "tool:mytool"


def test_infer_theme_tool_lowercased():
    assert _infer_theme({"tool": "ClaudeCode"}).startswith("tool:")
    assert "claudecode" in _infer_theme({"tool": "ClaudeCode"})


def test_infer_theme_testing():
    for kw in ("test", "pytest", "assert", "ci"):
        assert _infer_theme({"recommendation": f"run {kw} suite"}) == "testing"


def test_infer_theme_reliability():
    for kw in ("retry", "timeout", "fail", "error", "stability"):
        assert _infer_theme({"recommendation": f"handle {kw}"}) == "reliability"


def test_infer_theme_performance():
    for kw in ("latency", "slow", "perf", "memory", "cache"):
        assert _infer_theme({"recommendation": f"improve {kw}"}) == "performance"


def test_infer_theme_state():
    for kw in ("state", "transition", "constraint"):
        assert _infer_theme({"recommendation": f"manage {kw}"}) == "state"


def test_infer_theme_security():
    for kw in ("auth", "token", "secret", "permission"):
        assert _infer_theme({"recommendation": f"check {kw}"}) == "security"


def test_infer_theme_general_fallback():
    assert _infer_theme({"recommendation": "do something nice"}) == "general"


def test_infer_theme_empty_tool_falls_through():
    # empty string tool should not block keyword matching
    result = _infer_theme({"tool": "", "recommendation": "run the tests"})
    assert result == "testing"


def test_infer_theme_no_keys():
    assert _infer_theme({}) == "general"


# ---------------------------------------------------------------------------
# compute_kpis — counts
# ---------------------------------------------------------------------------


def test_compute_kpis_empty():
    kpis = compute_kpis([])
    assert kpis["total_advisories"] == 0
    assert kpis["acted"] == 0
    assert kpis["action_rate_pct"] == 0.0
    assert kpis["helpful_rate_pct"] == 0.0
    assert kpis["median_time_to_action_s"] is None


def test_compute_kpis_counts_statuses():
    items = [
        _item(status="acted"),
        _item(status="skipped"),
        _item(status="unresolved"),
        _item(status="acted"),
    ]
    kpis = compute_kpis(items)
    assert kpis["total_advisories"] == 4
    assert kpis["acted"] == 2
    assert kpis["skipped"] == 1
    assert kpis["unresolved"] == 1


def test_compute_kpis_counts_effects():
    items = [
        _item(status="acted", effect="positive"),
        _item(status="acted", effect="negative"),
        _item(status="acted", effect="positive"),
    ]
    kpis = compute_kpis(items)
    assert kpis["positive"] == 2
    assert kpis["negative"] == 1


def test_compute_kpis_action_rate():
    items = [_item(status="acted"), _item(status="skipped")]
    kpis = compute_kpis(items)
    assert kpis["action_rate_pct"] == 50.0


def test_compute_kpis_helpful_rate():
    items = [
        _item(status="acted", effect="positive"),
        _item(status="acted", effect="negative"),
    ]
    kpis = compute_kpis(items)
    assert kpis["helpful_rate_pct"] == 50.0


def test_compute_kpis_helpful_rate_zero_when_no_acted():
    kpis = compute_kpis([_item(status="skipped")])
    assert kpis["helpful_rate_pct"] == 0.0


def test_compute_kpis_100_pct_helpful():
    items = _items(3, status="acted", effect="positive")
    kpis = compute_kpis(items)
    assert kpis["helpful_rate_pct"] == 100.0


# ---------------------------------------------------------------------------
# compute_kpis — median latency
# ---------------------------------------------------------------------------


def test_compute_kpis_median_latency_single():
    kpis = compute_kpis([_item(status="acted", latency_s=4.0)])
    assert kpis["median_time_to_action_s"] == 4.0


def test_compute_kpis_median_latency_multiple():
    items = [
        _item(status="acted", latency_s=1.0),
        _item(status="acted", latency_s=3.0),
        _item(status="acted", latency_s=5.0),
    ]
    kpis = compute_kpis(items)
    assert kpis["median_time_to_action_s"] == 3.0


def test_compute_kpis_latency_ignores_non_acted():
    items = [
        _item(status="acted", latency_s=2.0),
        _item(status="skipped", latency_s=999.0),
    ]
    kpis = compute_kpis(items)
    assert kpis["median_time_to_action_s"] == 2.0


def test_compute_kpis_latency_none_when_no_acted():
    kpis = compute_kpis([_item(status="skipped", latency_s=1.0)])
    assert kpis["median_time_to_action_s"] is None


def test_compute_kpis_latency_ignores_missing_latency_s():
    items = [_item(status="acted", latency_s=3.0), {"status": "acted"}]
    kpis = compute_kpis(items)
    # Only one item with latency_s
    assert kpis["median_time_to_action_s"] == 3.0


# ---------------------------------------------------------------------------
# compute_kpis — top_ignored_advisory_themes
# ---------------------------------------------------------------------------


def test_compute_kpis_top_ignored_themes_empty_when_all_acted():
    kpis = compute_kpis(_items(3, status="acted"))
    assert kpis["top_ignored_advisory_themes"] == []


def test_compute_kpis_top_ignored_themes_present():
    items = [
        _item(status="skipped", recommendation="run tests"),
        _item(status="unresolved", recommendation="run tests again"),
        _item(status="skipped", recommendation="check latency"),
    ]
    kpis = compute_kpis(items)
    themes = {t["theme"] for t in kpis["top_ignored_advisory_themes"]}
    assert "testing" in themes or "performance" in themes


def test_compute_kpis_top_ignored_themes_max_5():
    # 6 different themes is impossible, but max 5 are returned
    kpis = compute_kpis([_item(status="skipped") for _ in range(10)])
    assert len(kpis["top_ignored_advisory_themes"]) <= 5


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


def test_build_report_structure():
    report = build_report(_items(2, status="acted"))
    assert "generated_at" in report
    assert "kpis" in report
    assert "items" in report


def test_build_report_generated_at_recent():
    before = time.time()
    report = build_report([])
    assert report["generated_at"] >= before


def test_build_report_items_preserved():
    items = _items(3, status="acted")
    report = build_report(items)
    assert len(report["items"]) == 3


def test_build_report_kpis_correct():
    items = [_item(status="acted"), _item(status="skipped")]
    report = build_report(items)
    assert report["kpis"]["total_advisories"] == 2


# ---------------------------------------------------------------------------
# write_report
# ---------------------------------------------------------------------------


def test_write_report_creates_file(tmp_path):
    report = build_report([])
    out = tmp_path / "report.json"
    result = write_report(report, out)
    assert result == out
    assert out.exists()


def test_write_report_valid_json(tmp_path):
    report = build_report(_items(2))
    out = tmp_path / "report.json"
    write_report(report, out)
    loaded = json.loads(out.read_text())
    assert "kpis" in loaded


def test_write_report_creates_parent_dirs(tmp_path):
    report = build_report([])
    out = tmp_path / "a" / "b" / "report.json"
    write_report(report, out)
    assert out.exists()


# ---------------------------------------------------------------------------
# render_terminal_summary
# ---------------------------------------------------------------------------


def test_render_terminal_summary_returns_string():
    report = build_report(_items(2))
    summary = render_terminal_summary(report)
    assert isinstance(summary, str)
    assert len(summary) > 0


def test_render_terminal_summary_contains_header():
    summary = render_terminal_summary(build_report([]))
    assert "Advice-to-Action" in summary


def test_render_terminal_summary_contains_counts():
    items = [_item(status="acted"), _item(status="skipped")]
    summary = render_terminal_summary(build_report(items))
    assert "acted=1" in summary
    assert "skipped=1" in summary


def test_render_terminal_summary_shows_action_rate():
    items = [_item(status="acted"), _item(status="skipped")]
    summary = render_terminal_summary(build_report(items))
    assert "action_rate=" in summary


def test_render_terminal_summary_shows_median_latency_when_present():
    items = [_item(status="acted", latency_s=2.5)]
    summary = render_terminal_summary(build_report(items))
    assert "median_time_to_action" in summary


def test_render_terminal_summary_omits_latency_when_absent():
    summary = render_terminal_summary(build_report([_item(status="skipped")]))
    assert "median_time_to_action" not in summary


def test_render_terminal_summary_shows_ignored_themes():
    items = [_item(status="skipped", recommendation="add tests")]
    summary = render_terminal_summary(build_report(items))
    assert "top_ignored_themes" in summary
