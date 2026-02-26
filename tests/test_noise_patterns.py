from __future__ import annotations

from lib.noise_patterns import is_session_boilerplate


def test_session_boilerplate_matches_inventory_headers():
    assert is_session_boilerplate("Mission ID: abc123")
    assert is_session_boilerplate("Assigned tasks: 3")
    assert is_session_boilerplate("Execution expectations: strict")


def test_session_boilerplate_does_not_match_regular_text():
    assert not is_session_boilerplate("Keep scope fixed and avoid migration risk.")
