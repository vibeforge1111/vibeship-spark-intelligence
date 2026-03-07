"""Tests for lib/sync_tracker.py — SyncTracker adapter sync status."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.sync_tracker as st
from lib.sync_tracker import AdapterStatus, SyncTracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_sync_file(tmp_path, monkeypatch):
    sync_file = tmp_path / "sync_stats.json"
    monkeypatch.setattr(st, "SYNC_STATS_FILE", sync_file)
    yield sync_file


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    monkeypatch.setattr(st, "_tracker", None)
    yield
    monkeypatch.setattr(st, "_tracker", None)


# ---------------------------------------------------------------------------
# AdapterStatus dataclass
# ---------------------------------------------------------------------------

class TestAdapterStatus:
    def test_default_status_never(self):
        a = AdapterStatus(name="test")
        assert a.status == "never"

    def test_default_tier_optional(self):
        a = AdapterStatus(name="test")
        assert a.tier == "optional"

    def test_default_items_zero(self):
        a = AdapterStatus(name="test")
        assert a.items_synced == 0

    def test_none_last_sync_by_default(self):
        a = AdapterStatus(name="test")
        assert a.last_sync is None

    def test_custom_values(self):
        a = AdapterStatus(name="cursor", tier="core", status="success", items_synced=5)
        assert a.name == "cursor"
        assert a.tier == "core"
        assert a.status == "success"
        assert a.items_synced == 5

    def test_error_field_defaults_none(self):
        a = AdapterStatus(name="test")
        assert a.error is None


# ---------------------------------------------------------------------------
# SyncTracker.__post_init__
# ---------------------------------------------------------------------------

class TestSyncTrackerInit:
    def test_known_adapters_populated(self):
        tracker = SyncTracker()
        for key in SyncTracker.KNOWN_ADAPTERS:
            assert key in tracker.adapters

    def test_all_adapters_start_never(self):
        tracker = SyncTracker()
        for adapter in tracker.adapters.values():
            assert adapter.status == "never"

    def test_exports_is_core(self):
        tracker = SyncTracker()
        assert tracker.adapters["exports"].tier == "core"

    def test_openclaw_is_core(self):
        tracker = SyncTracker()
        assert tracker.adapters["openclaw"].tier == "core"

    def test_cursor_is_optional(self):
        tracker = SyncTracker()
        assert tracker.adapters["cursor"].tier == "optional"

    def test_claude_code_is_optional(self):
        tracker = SyncTracker()
        assert tracker.adapters["claude_code"].tier == "optional"

    def test_total_syncs_starts_zero(self):
        tracker = SyncTracker()
        assert tracker.total_syncs == 0

    def test_last_full_sync_starts_none(self):
        tracker = SyncTracker()
        assert tracker.last_full_sync is None

    def test_six_known_adapters(self):
        assert len(SyncTracker.KNOWN_ADAPTERS) == 6


# ---------------------------------------------------------------------------
# SyncTracker._tier_for
# ---------------------------------------------------------------------------

class TestTierFor:
    def test_exports_is_core(self):
        tracker = SyncTracker()
        assert tracker._tier_for("exports") == "core"

    def test_openclaw_is_core(self):
        tracker = SyncTracker()
        assert tracker._tier_for("openclaw") == "core"

    def test_cursor_is_optional(self):
        tracker = SyncTracker()
        assert tracker._tier_for("cursor") == "optional"

    def test_unknown_adapter_is_optional(self):
        tracker = SyncTracker()
        assert tracker._tier_for("nonexistent") == "optional"


# ---------------------------------------------------------------------------
# SyncTracker.record_sync
# ---------------------------------------------------------------------------

class TestRecordSync:
    def test_updates_adapter_status(self):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "success", items=3)
        assert tracker.adapters["cursor"].status == "success"
        assert tracker.adapters["cursor"].items_synced == 3

    def test_increments_total_syncs(self):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "success")
        assert tracker.total_syncs == 1

    def test_multiple_syncs_accumulate(self):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "success")
        tracker.record_sync("exports", "success")
        assert tracker.total_syncs == 2

    def test_sets_last_full_sync(self):
        tracker = SyncTracker()
        assert tracker.last_full_sync is None
        tracker.record_sync("cursor", "success")
        assert tracker.last_full_sync is not None

    def test_error_status_stores_error(self):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "error", error="disk full")
        assert tracker.adapters["cursor"].error == "disk full"

    def test_success_status_clears_error(self):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "error", error="oops")
        tracker.record_sync("cursor", "success")
        assert tracker.adapters["cursor"].error is None

    def test_unknown_adapter_creates_entry(self):
        tracker = SyncTracker()
        tracker.record_sync("new_adapter", "success")
        assert "new_adapter" in tracker.adapters

    def test_saves_to_file(self, isolate_sync_file):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "success")
        assert isolate_sync_file.exists()

    def test_last_sync_set_on_adapter(self):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "success")
        assert tracker.adapters["cursor"].last_sync is not None

    def test_skipped_status_recorded(self):
        tracker = SyncTracker()
        tracker.record_sync("windsurf", "skipped")
        assert tracker.adapters["windsurf"].status == "skipped"


# ---------------------------------------------------------------------------
# SyncTracker.record_full_sync
# ---------------------------------------------------------------------------

class TestRecordFullSync:
    def test_written_status_becomes_success(self):
        tracker = SyncTracker()
        tracker.record_full_sync({"cursor": "written"})
        assert tracker.adapters["cursor"].status == "success"

    def test_non_written_status_preserved(self):
        tracker = SyncTracker()
        tracker.record_full_sync({"cursor": "skipped"})
        assert tracker.adapters["cursor"].status == "skipped"

    def test_items_per_adapter_set_for_written(self):
        tracker = SyncTracker()
        tracker.record_full_sync({"cursor": "written"}, items_per_adapter=7)
        assert tracker.adapters["cursor"].items_synced == 7

    def test_items_zero_for_non_written(self):
        tracker = SyncTracker()
        tracker.record_full_sync({"cursor": "skipped"}, items_per_adapter=7)
        assert tracker.adapters["cursor"].items_synced == 0

    def test_increments_total_syncs(self):
        tracker = SyncTracker()
        tracker.record_full_sync({"cursor": "written"})
        assert tracker.total_syncs == 1

    def test_multiple_adapters(self):
        tracker = SyncTracker()
        tracker.record_full_sync({"cursor": "written", "exports": "written"})
        assert tracker.adapters["cursor"].status == "success"
        assert tracker.adapters["exports"].status == "success"

    def test_unknown_adapter_created(self):
        tracker = SyncTracker()
        tracker.record_full_sync({"new_adapter": "written"})
        assert "new_adapter" in tracker.adapters

    def test_sets_last_full_sync(self):
        tracker = SyncTracker()
        tracker.record_full_sync({"cursor": "written"})
        assert tracker.last_full_sync is not None

    def test_empty_results_still_increments(self):
        tracker = SyncTracker()
        tracker.record_full_sync({})
        assert tracker.total_syncs == 1


# ---------------------------------------------------------------------------
# SyncTracker.get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_required_keys_present(self):
        tracker = SyncTracker()
        stats = tracker.get_stats()
        for key in ("last_sync", "total_syncs", "adapters_ok", "adapters_error",
                    "adapters_never", "core_ok", "core_error", "core_never",
                    "optional_ok", "optional_error", "optional_never",
                    "core_healthy", "adapters"):
            assert key in stats

    def test_adapters_never_count_fresh(self):
        tracker = SyncTracker()
        stats = tracker.get_stats()
        assert stats["adapters_never"] == len(SyncTracker.KNOWN_ADAPTERS)

    def test_adapters_ok_after_success(self):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "success")
        stats = tracker.get_stats()
        assert stats["adapters_ok"] >= 1

    def test_adapters_error_after_error(self):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "error")
        stats = tracker.get_stats()
        assert stats["adapters_error"] >= 1

    def test_core_healthy_when_no_errors(self):
        tracker = SyncTracker()
        stats = tracker.get_stats()
        assert stats["core_healthy"] is True

    def test_core_healthy_false_when_core_error(self):
        tracker = SyncTracker()
        tracker.record_sync("exports", "error")
        stats = tracker.get_stats()
        assert stats["core_healthy"] is False

    def test_core_healthy_true_when_only_optional_error(self):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "error")
        stats = tracker.get_stats()
        assert stats["core_healthy"] is True

    def test_adapters_list_has_all_entries(self):
        tracker = SyncTracker()
        stats = tracker.get_stats()
        adapter_keys = {a["key"] for a in stats["adapters"]}
        for key in SyncTracker.KNOWN_ADAPTERS:
            assert key in adapter_keys

    def test_adapter_entry_has_required_keys(self):
        tracker = SyncTracker()
        stats = tracker.get_stats()
        entry = stats["adapters"][0]
        for key in ("key", "name", "tier", "status", "last_sync", "items", "file"):
            assert key in entry

    def test_total_syncs_reflected(self):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "success")
        assert tracker.get_stats()["total_syncs"] == 1


# ---------------------------------------------------------------------------
# SyncTracker._save and load
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_save_creates_file(self, isolate_sync_file):
        tracker = SyncTracker()
        tracker._save()
        assert isolate_sync_file.exists()

    def test_save_is_valid_json(self, isolate_sync_file):
        tracker = SyncTracker()
        tracker._save()
        data = json.loads(isolate_sync_file.read_text(encoding="utf-8"))
        assert "adapters" in data
        assert "total_syncs" in data

    def test_save_creates_parent_dirs(self, tmp_path, monkeypatch):
        deep = tmp_path / "a" / "b" / "sync.json"
        monkeypatch.setattr(st, "SYNC_STATS_FILE", deep)
        tracker = SyncTracker()
        tracker._save()
        assert deep.exists()

    def test_load_creates_fresh_when_no_file(self, isolate_sync_file):
        tracker = SyncTracker.load()
        assert isinstance(tracker, SyncTracker)

    def test_load_restores_total_syncs(self, isolate_sync_file):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "success")
        tracker2 = SyncTracker.load()
        assert tracker2.total_syncs == 1

    def test_load_restores_adapter_status(self, isolate_sync_file):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "success", items=5)
        tracker2 = SyncTracker.load()
        assert tracker2.adapters["cursor"].status == "success"
        assert tracker2.adapters["cursor"].items_synced == 5

    def test_load_handles_corrupt_file(self, isolate_sync_file):
        isolate_sync_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_sync_file.write_text("not json", encoding="utf-8")
        tracker = SyncTracker.load()
        assert isinstance(tracker, SyncTracker)

    def test_load_ensures_known_adapters(self, isolate_sync_file):
        isolate_sync_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_sync_file.write_text(
            json.dumps({"adapters": {}, "total_syncs": 0}), encoding="utf-8"
        )
        tracker = SyncTracker.load()
        for key in SyncTracker.KNOWN_ADAPTERS:
            assert key in tracker.adapters

    def test_load_restores_last_full_sync(self, isolate_sync_file):
        tracker = SyncTracker()
        tracker.record_sync("cursor", "success")
        saved_sync = tracker.last_full_sync
        tracker2 = SyncTracker.load()
        assert tracker2.last_full_sync == saved_sync


# ---------------------------------------------------------------------------
# get_sync_tracker singleton
# ---------------------------------------------------------------------------

class TestGetSyncTracker:
    def test_returns_sync_tracker(self):
        tracker = st.get_sync_tracker()
        assert isinstance(tracker, SyncTracker)

    def test_same_instance_on_second_call(self):
        t1 = st.get_sync_tracker()
        t2 = st.get_sync_tracker()
        assert t1 is t2

    def test_singleton_reset_between_tests(self):
        # reset_singleton fixture sets _tracker=None before each test
        assert st._tracker is None
