"""Tests for lib/observatory/linker.py

Covers:
- STAGE_SLUGS / STAGE_NAMES: all 12 stages present and consistent
- stage_link(): known stages, unknown stages, custom display text
- stage_link_from_stage(): sibling-path format, unknown stage fallback
- flow_link(): fixed return value
- existing_link(): with and without custom display
- health_badge(): healthy / warning / critical / unknown status
- fmt_ts(): valid timestamp, zero/None (returns 'never'), exception fallback
- fmt_ago(): ranges — seconds, minutes, hours, days, future timestamp
- fmt_size(): bytes, KB, MB boundaries
- fmt_num(): integers with commas, floats with 1 decimal
"""

from __future__ import annotations

import time

import pytest

from lib.observatory.linker import (
    STAGE_NAMES,
    STAGE_SLUGS,
    existing_link,
    flow_link,
    fmt_ago,
    fmt_num,
    fmt_size,
    fmt_ts,
    health_badge,
    stage_link,
    stage_link_from_stage,
)


# ---------------------------------------------------------------------------
# STAGE_SLUGS / STAGE_NAMES — completeness and consistency
# ---------------------------------------------------------------------------

def test_stage_slugs_has_all_12_stages():
    assert set(STAGE_SLUGS.keys()) == set(range(1, 13))


def test_stage_names_has_all_12_stages():
    assert set(STAGE_NAMES.keys()) == set(range(1, 13))


def test_stage_slugs_are_strings():
    assert all(isinstance(v, str) for v in STAGE_SLUGS.values())


def test_stage_names_are_strings():
    assert all(isinstance(v, str) for v in STAGE_NAMES.values())


def test_stage_slugs_include_zero_padded_number():
    # Each slug should start with its two-digit stage number
    for num, slug in STAGE_SLUGS.items():
        assert slug.startswith(f"{num:02d}-"), f"Stage {num} slug '{slug}' missing prefix"


def test_stage_names_nonempty():
    assert all(len(v) > 0 for v in STAGE_NAMES.values())


# ---------------------------------------------------------------------------
# stage_link
# ---------------------------------------------------------------------------

def test_stage_link_known_stage_format():
    result = stage_link(1)
    assert result == f"[[stages/{STAGE_SLUGS[1]}|{STAGE_NAMES[1]}]]"


def test_stage_link_all_known_stages():
    for num in range(1, 13):
        result = stage_link(num)
        assert result.startswith("[[stages/")
        assert STAGE_SLUGS[num] in result
        assert STAGE_NAMES[num] in result


def test_stage_link_unknown_stage_uses_fallback_slug():
    result = stage_link(99)
    assert "99-unknown" in result


def test_stage_link_unknown_stage_uses_fallback_label():
    result = stage_link(99)
    assert "Stage 99" in result


def test_stage_link_custom_display_overrides_default():
    result = stage_link(1, display="My Label")
    assert "My Label" in result
    assert STAGE_NAMES[1] not in result


def test_stage_link_format_is_obsidian_wikilink():
    result = stage_link(1)
    assert result.startswith("[[")
    assert result.endswith("]]")
    assert "|" in result


# ---------------------------------------------------------------------------
# stage_link_from_stage
# ---------------------------------------------------------------------------

def test_stage_link_from_stage_known():
    result = stage_link_from_stage(2)
    # Sibling link: no "stages/" prefix
    assert result == f"[[{STAGE_SLUGS[2]}|{STAGE_NAMES[2]}]]"


def test_stage_link_from_stage_no_stages_prefix():
    result = stage_link_from_stage(1)
    assert "stages/" not in result


def test_stage_link_from_stage_unknown_fallback():
    result = stage_link_from_stage(50)
    assert "50-unknown" in result
    assert "Stage 50" in result


def test_stage_link_from_stage_custom_display():
    result = stage_link_from_stage(3, display="Custom")
    assert "Custom" in result


# ---------------------------------------------------------------------------
# flow_link
# ---------------------------------------------------------------------------

def test_flow_link_returns_fixed_string():
    assert flow_link() == "[[../flow|Intelligence Flow]]"


def test_flow_link_is_obsidian_wikilink():
    result = flow_link()
    assert result.startswith("[[") and result.endswith("]]")


# ---------------------------------------------------------------------------
# existing_link
# ---------------------------------------------------------------------------

def test_existing_link_no_display_uses_page_as_label():
    result = existing_link("watchtower")
    assert result == "[[../watchtower|watchtower]]"


def test_existing_link_custom_display():
    result = existing_link("packets/index", display="Packets")
    assert result == "[[../packets/index|Packets]]"


def test_existing_link_format():
    result = existing_link("some/page")
    assert result.startswith("[[../")
    assert result.endswith("]]")
    assert "|" in result


# ---------------------------------------------------------------------------
# health_badge
# ---------------------------------------------------------------------------

def test_health_badge_healthy():
    assert health_badge("healthy") == "healthy"


def test_health_badge_warning():
    assert health_badge("warning") == "WARNING"


def test_health_badge_critical():
    assert health_badge("critical") == "CRITICAL"


def test_health_badge_unknown_passthrough():
    assert health_badge("degraded") == "degraded"


def test_health_badge_empty_string_passthrough():
    assert health_badge("") == ""


# ---------------------------------------------------------------------------
# fmt_ts
# ---------------------------------------------------------------------------

def test_fmt_ts_none_returns_never():
    assert fmt_ts(None) == "never"


def test_fmt_ts_zero_returns_never():
    assert fmt_ts(0) == "never"


def test_fmt_ts_valid_timestamp_returns_datetime_string():
    ts = 1700000000.0  # 2023-11-14 22:13:20 UTC (approx)
    result = fmt_ts(ts)
    # Should be a datetime string, not "never"
    assert result != "never"
    assert "-" in result  # YYYY-MM-DD format
    assert ":" in result  # HH:MM:SS format


def test_fmt_ts_returns_string():
    assert isinstance(fmt_ts(time.time()), str)


def test_fmt_ts_invalid_timestamp_does_not_raise():
    # Very large negative number should trigger exception path
    result = fmt_ts(-99999999999)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# fmt_ago
# ---------------------------------------------------------------------------

def test_fmt_ago_none_returns_never():
    assert fmt_ago(None) == "never"


def test_fmt_ago_zero_returns_never():
    assert fmt_ago(0) == "never"


def test_fmt_ago_seconds():
    ts = time.time() - 30
    result = fmt_ago(ts)
    assert result.endswith("s ago")


def test_fmt_ago_minutes():
    ts = time.time() - 120  # 2 minutes ago
    result = fmt_ago(ts)
    assert result.endswith("m ago")


def test_fmt_ago_hours():
    ts = time.time() - 7200  # 2 hours ago
    result = fmt_ago(ts)
    assert result.endswith("h ago")


def test_fmt_ago_days():
    ts = time.time() - 86400 * 2  # 2 days ago
    result = fmt_ago(ts)
    assert result.endswith("d ago")


def test_fmt_ago_future_returns_just_now():
    ts = time.time() + 60  # 1 minute in the future
    result = fmt_ago(ts)
    assert result == "just now"


def test_fmt_ago_returns_string():
    assert isinstance(fmt_ago(time.time() - 10), str)


# ---------------------------------------------------------------------------
# fmt_size
# ---------------------------------------------------------------------------

def test_fmt_size_bytes():
    assert fmt_size(512) == "512B"


def test_fmt_size_zero_bytes():
    assert fmt_size(0) == "0B"


def test_fmt_size_exactly_1kb():
    assert fmt_size(1024) == "1.0KB"


def test_fmt_size_kilobytes():
    result = fmt_size(2048)
    assert result.endswith("KB")
    assert "2.0" in result


def test_fmt_size_megabytes():
    result = fmt_size(1024 * 1024)
    assert result.endswith("MB")
    assert "1.0" in result


def test_fmt_size_large_mb():
    result = fmt_size(5 * 1024 * 1024)
    assert "5.0MB" == result


def test_fmt_size_below_1kb_boundary():
    assert fmt_size(1023) == "1023B"


# ---------------------------------------------------------------------------
# fmt_num
# ---------------------------------------------------------------------------

def test_fmt_num_small_int():
    assert fmt_num(42) == "42"


def test_fmt_num_thousands():
    assert fmt_num(1000) == "1,000"


def test_fmt_num_millions():
    assert fmt_num(1_000_000) == "1,000,000"


def test_fmt_num_float():
    result = fmt_num(1234.5)
    assert "1,234.5" == result


def test_fmt_num_zero():
    assert fmt_num(0) == "0"


def test_fmt_num_returns_string():
    assert isinstance(fmt_num(100), str)
