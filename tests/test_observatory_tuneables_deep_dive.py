from __future__ import annotations

import lib.observatory.tuneables_deep_dive as deep_dive
from lib.tuneables_schema import SCHEMA, SECTION_CONSUMERS


def test_deep_dive_sections_track_tuneables_schema():
    assert set(deep_dive.SCHEMA_SECTIONS) == set(SCHEMA.keys())


def test_deep_dive_consumers_track_schema_consumers():
    assert deep_dive.SECTION_CONSUMERS.get("opportunity_scanner") == SECTION_CONSUMERS.get("opportunity_scanner")
    assert deep_dive.SECTION_CONSUMERS.get("feature_gates") == SECTION_CONSUMERS.get("feature_gates")


def test_deep_dive_reload_map_has_recent_sections():
    assert "memory_deltas" in deep_dive.KNOWN_RELOAD_SECTIONS
    assert "opportunity_scanner" in deep_dive.KNOWN_RELOAD_SECTIONS

