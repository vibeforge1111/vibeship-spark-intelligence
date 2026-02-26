"""Tests for lib/tuneables_reload.py — mtime-based hot-reload coordinator."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import lib.tuneables_reload as tr
from lib.tuneables_reload import (
    register_reload,
    check_and_reload,
    get_validated_data,
    get_section,
    get_reload_log,
    get_registered_sections,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_state(tmp_path, monkeypatch):
    """Reset all module-level state and redirect TUNEABLES_FILE."""
    tuneables_file = tmp_path / "tuneables.json"
    monkeypatch.setattr(tr, "TUNEABLES_FILE", tuneables_file)
    monkeypatch.setattr(tr, "_last_mtime", None)
    monkeypatch.setattr(tr, "_last_data", {})
    monkeypatch.setattr(tr, "_callbacks", {})
    monkeypatch.setattr(tr, "_reload_log", [])
    yield tuneables_file


# ---------------------------------------------------------------------------
# register_reload
# ---------------------------------------------------------------------------

class TestRegisterReload:
    def test_registers_callback(self):
        called = []
        register_reload("test_section", lambda d: called.append(d))
        sections = get_registered_sections()
        assert "test_section" in sections

    def test_multiple_callbacks_same_section(self):
        register_reload("sec", lambda d: None)
        register_reload("sec", lambda d: None)
        sections = get_registered_sections()
        assert len(sections["sec"]) == 2

    def test_custom_label_used(self):
        register_reload("sec", lambda d: None, label="my_label")
        sections = get_registered_sections()
        assert "my_label" in sections["sec"]

    def test_auto_label_generated_when_none(self):
        register_reload("sec", lambda d: None)
        sections = get_registered_sections()
        assert len(sections["sec"]) == 1
        assert sections["sec"][0]  # non-empty string

    def test_different_sections(self):
        register_reload("alpha", lambda d: None)
        register_reload("beta", lambda d: None)
        sections = get_registered_sections()
        assert "alpha" in sections
        assert "beta" in sections


# ---------------------------------------------------------------------------
# check_and_reload — basic behavior
# ---------------------------------------------------------------------------

class TestCheckAndReloadBasic:
    def test_returns_false_when_no_file(self):
        assert check_and_reload() is False

    def test_returns_false_when_same_mtime(self, reset_state):
        f = reset_state
        f.write_text('{"sec": {"k": 1}}', encoding="utf-8")
        check_and_reload()  # First load
        result = check_and_reload()  # Same mtime
        assert result is False

    def test_returns_true_on_first_load(self, reset_state):
        f = reset_state
        f.write_text('{"sec": {"k": 1}}', encoding="utf-8")
        register_reload("sec", lambda d: None)
        result = check_and_reload()
        assert result is True

    def test_returns_false_for_invalid_json(self, reset_state):
        f = reset_state
        f.write_text("not json", encoding="utf-8")
        result = check_and_reload()
        assert result is False

    def test_returns_false_for_non_dict_json(self, reset_state):
        f = reset_state
        f.write_text("[1, 2, 3]", encoding="utf-8")
        result = check_and_reload()
        assert result is False

    def test_force_bypasses_mtime_check(self, reset_state):
        f = reset_state
        f.write_text('{"sec": {"k": 1}}', encoding="utf-8")
        received = []
        register_reload("sec", lambda d: received.append(dict(d)))
        check_and_reload()  # First load — dispatches to sec

        # Change file content without updating mtime (use force to bypass)
        f.write_text('{"sec": {"k": 99}}', encoding="utf-8")
        import os
        st = f.stat()
        os.utime(f, (st.st_mtime, st.st_mtime))  # reset mtime to same value
        # Normal reload would skip (same mtime), but force should read anyway
        result = check_and_reload(force=True)
        assert result is True
        assert received[-1] == {"k": 99}


# ---------------------------------------------------------------------------
# check_and_reload — callback dispatch
# ---------------------------------------------------------------------------

class TestCheckAndReloadCallbacks:
    def test_callback_fired_on_first_load(self, reset_state):
        f = reset_state
        f.write_text('{"sec": {"k": 1}}', encoding="utf-8")
        received = []
        register_reload("sec", lambda d: received.append(d))
        check_and_reload()
        assert received == [{"k": 1}]

    def test_callback_fired_when_section_changes(self, reset_state):
        f = reset_state
        f.write_text('{"sec": {"k": 1}}', encoding="utf-8")
        received = []
        register_reload("sec", lambda d: received.append(dict(d)))
        check_and_reload()

        # Touch file with new content
        time.sleep(0.01)
        f.write_text('{"sec": {"k": 2}}', encoding="utf-8")
        # Force mtime update by bumping it
        mtime = f.stat().st_mtime
        import os
        os.utime(f, (mtime + 1, mtime + 1))
        check_and_reload()

        assert len(received) == 2
        assert received[1] == {"k": 2}

    def test_callback_error_doesnt_propagate(self, reset_state):
        f = reset_state
        f.write_text('{"sec": {"k": 1}}', encoding="utf-8")

        def bad_callback(d):
            raise RuntimeError("oops")

        register_reload("sec", bad_callback)
        # Should not raise
        check_and_reload()

    def test_non_dict_section_data_defaults_empty(self, reset_state):
        f = reset_state
        f.write_text('{"sec": "string_value"}', encoding="utf-8")
        received = []
        register_reload("sec", lambda d: received.append(d))
        check_and_reload()
        assert received == [{}]

    def test_section_not_in_file_gives_empty_dict(self, reset_state):
        f = reset_state
        f.write_text('{"other": {"k": 1}}', encoding="utf-8")
        received = []
        register_reload("missing_section", lambda d: received.append(d))
        check_and_reload()
        assert received == [{}]


# ---------------------------------------------------------------------------
# get_validated_data
# ---------------------------------------------------------------------------

class TestGetValidatedData:
    def test_empty_before_first_load(self):
        assert get_validated_data() == {}

    def test_returns_last_loaded_data(self, reset_state):
        f = reset_state
        f.write_text('{"sec": {"k": 99}}', encoding="utf-8")
        check_and_reload()
        data = get_validated_data()
        assert data.get("sec", {}).get("k") == 99

    def test_returns_copy(self, reset_state):
        f = reset_state
        f.write_text('{"sec": {"k": 1}}', encoding="utf-8")
        check_and_reload()
        d1 = get_validated_data()
        d2 = get_validated_data()
        assert d1 is not d2


# ---------------------------------------------------------------------------
# get_section
# ---------------------------------------------------------------------------

class TestGetSection:
    def test_returns_empty_before_load(self):
        assert get_section("anything") == {}

    def test_returns_section_data(self, reset_state):
        f = reset_state
        f.write_text('{"config": {"timeout": 30}}', encoding="utf-8")
        check_and_reload()
        section = get_section("config")
        assert section.get("timeout") == 30

    def test_returns_empty_for_missing_section(self, reset_state):
        f = reset_state
        f.write_text('{"config": {"k": 1}}', encoding="utf-8")
        check_and_reload()
        assert get_section("nonexistent") == {}

    def test_returns_copy_not_reference(self, reset_state):
        f = reset_state
        f.write_text('{"sec": {"k": 1}}', encoding="utf-8")
        check_and_reload()
        s1 = get_section("sec")
        s2 = get_section("sec")
        assert s1 is not s2


# ---------------------------------------------------------------------------
# get_reload_log
# ---------------------------------------------------------------------------

class TestGetReloadLog:
    def test_empty_before_any_reload(self):
        assert get_reload_log() == []

    def test_log_entry_added_after_reload(self, reset_state):
        f = reset_state
        f.write_text('{"sec": {"k": 1}}', encoding="utf-8")
        register_reload("sec", lambda d: None)
        check_and_reload()
        log = get_reload_log()
        assert len(log) >= 1

    def test_log_entry_has_required_keys(self, reset_state):
        f = reset_state
        f.write_text('{"sec": {"k": 1}}', encoding="utf-8")
        register_reload("sec", lambda d: None)
        check_and_reload()
        entry = get_reload_log()[0]
        for key in ("ts", "changed", "dispatched", "errors", "force"):
            assert key in entry

    def test_returns_list_copy(self):
        log = get_reload_log()
        assert isinstance(log, list)


# ---------------------------------------------------------------------------
# get_registered_sections
# ---------------------------------------------------------------------------

class TestGetRegisteredSections:
    def test_empty_before_registration(self):
        assert get_registered_sections() == {}

    def test_section_appears_after_register(self):
        register_reload("my_sec", lambda d: None, label="my_cb")
        sections = get_registered_sections()
        assert "my_sec" in sections
        assert "my_cb" in sections["my_sec"]

    def test_returns_dict(self):
        assert isinstance(get_registered_sections(), dict)
