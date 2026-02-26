#!/usr/bin/env python3
"""Tests for spark_scheduler.py -- periodic X intelligence tasks."""

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Stub external deps that scheduler imports
for mod_name in ["tweepy", "src", "src.mention_monitor", "src.models", "src.storage"]:
    sys.modules.setdefault(mod_name, MagicMock())

import spark_scheduler as sched


class TestLoadConfig(unittest.TestCase):
    """Config loading: defaults, overrides, missing file."""

    def test_defaults_when_no_file(self):
        with patch.object(sched, "TUNEABLES_FILE", Path("/nonexistent/tuneables.json")):
            cfg = sched.load_scheduler_config()
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["mention_poll_interval"], 600)
        self.assertEqual(cfg["engagement_snapshot_interval"], 1800)
        self.assertEqual(cfg["daily_research_interval"], 86400)
        self.assertEqual(cfg["niche_scan_interval"], 21600)
        self.assertEqual(cfg["advisory_review_interval"], 43200)
        self.assertTrue(cfg["advisory_review_enabled"])
        self.assertEqual(cfg["advisory_review_window_hours"], 12)
        self.assertTrue(cfg["memory_quality_observatory_enabled"])

    def test_overrides_from_file(self, tmp_path=None):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "scheduler": {
                    "mention_poll_interval": 300,
                    "enabled": False,
                }
            }, f)
            f.flush()
            tmp = Path(f.name)
        try:
            with patch.object(sched, "TUNEABLES_FILE", tmp):
                cfg = sched.load_scheduler_config()
            self.assertFalse(cfg["enabled"])
            self.assertEqual(cfg["mention_poll_interval"], 300)
            # Non-overridden keys use defaults
            self.assertEqual(cfg["engagement_snapshot_interval"], 1800)
        finally:
            tmp.unlink(missing_ok=True)

    def test_corrupt_file_returns_defaults(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("NOT VALID JSON{{{")
            f.flush()
            tmp = Path(f.name)
        try:
            with patch.object(sched, "TUNEABLES_FILE", tmp):
                cfg = sched.load_scheduler_config()
            self.assertTrue(cfg["enabled"])
        finally:
            tmp.unlink(missing_ok=True)

    def test_missing_scheduler_section_returns_defaults(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"meta_ralph": {"threshold": 5}}, f)
            f.flush()
            tmp = Path(f.name)
        try:
            with patch.object(sched, "TUNEABLES_FILE", tmp):
                cfg = sched.load_scheduler_config()
            self.assertTrue(cfg["enabled"])
        finally:
            tmp.unlink(missing_ok=True)


class TestStatePersistence(unittest.TestCase):
    """State save/load round-trip."""

    def test_load_missing_state(self):
        with patch.object(sched, "STATE_FILE", Path("/nonexistent/state.json")):
            state = sched._load_state()
        self.assertEqual(state, {})

    def test_save_and_load(self):
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp())
        state_file = tmp_dir / "state.json"
        try:
            with patch.object(sched, "STATE_FILE", state_file), \
                 patch.object(sched, "SCHEDULER_DIR", tmp_dir):
                sched._save_state({"last_run_mention_poll": 12345.0, "last_mention_id": "999"})
                loaded = sched._load_state()
            self.assertEqual(loaded["last_run_mention_poll"], 12345.0)
            self.assertEqual(loaded["last_mention_id"], "999")
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestHeartbeat(unittest.TestCase):
    """Heartbeat write, read, and age calculation."""

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.hb_file = self.tmp_dir / "heartbeat.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_heartbeat_age_missing(self):
        with patch.object(sched, "HEARTBEAT_FILE", self.tmp_dir / "nope.json"):
            self.assertIsNone(sched.scheduler_heartbeat_age_s())

    def test_write_and_read_heartbeat(self):
        with patch.object(sched, "HEARTBEAT_FILE", self.hb_file), \
             patch.object(sched, "SCHEDULER_DIR", self.tmp_dir):
            sched.write_scheduler_heartbeat({"mention_poll": {"ok": True}})
            age = sched.scheduler_heartbeat_age_s()
        self.assertIsNotNone(age)
        self.assertLess(age, 5.0)  # Should be nearly instant

    def test_heartbeat_age_with_old_timestamp(self):
        old_ts = time.time() - 300  # 5 minutes ago
        self.hb_file.write_text(json.dumps({"ts": old_ts, "stats": {}}))
        with patch.object(sched, "HEARTBEAT_FILE", self.hb_file):
            age = sched.scheduler_heartbeat_age_s()
        self.assertIsNotNone(age)
        self.assertGreater(age, 290)


class TestDraftReplyQueue(unittest.TestCase):
    """Draft reply queue: append, max cap, get pending."""

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.drafts_file = self.tmp_dir / "draft_replies.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_save_and_get_draft(self):
        with patch.object(sched, "DRAFT_REPLIES_FILE", self.drafts_file):
            sched._save_draft_reply({
                "tweet_id": "123",
                "author": "alice",
                "action": "reward",
                "reply_text": "Great tweet!",
            })
            pending = sched.get_pending_drafts()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["tweet_id"], "123")
        self.assertFalse(pending[0]["posted"])

    def test_max_200_entries(self):
        with patch.object(sched, "DRAFT_REPLIES_FILE", self.drafts_file):
            for i in range(210):
                sched._save_draft_reply({"tweet_id": str(i), "author": f"u{i}"})
            pending = sched.get_pending_drafts()
        self.assertEqual(len(pending), 200)
        # Oldest entries should have been dropped (FIFO)
        ids = [d["tweet_id"] for d in pending]
        self.assertNotIn("0", ids)
        self.assertIn("209", ids)

    def test_get_pending_filters_posted(self):
        drafts = [
            {"tweet_id": "1", "posted": True},
            {"tweet_id": "2", "posted": False},
            {"tweet_id": "3", "posted": False},
        ]
        self.drafts_file.write_text(json.dumps(drafts))
        with patch.object(sched, "DRAFT_REPLIES_FILE", self.drafts_file):
            pending = sched.get_pending_drafts()
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0]["tweet_id"], "2")

    def test_empty_file_returns_empty(self):
        with patch.object(sched, "DRAFT_REPLIES_FILE", self.tmp_dir / "missing.json"):
            self.assertEqual(sched.get_pending_drafts(), [])


class TestRunDueTasks(unittest.TestCase):
    """Task scheduling: due, not due, disabled, force, failures."""

    def _base_config(self):
        return {
            "enabled": True,
            "mention_poll_interval": 600,
            "engagement_snapshot_interval": 1800,
            "daily_research_interval": 86400,
            "niche_scan_interval": 21600,
            "advisory_review_interval": 43200,
            "mention_poll_enabled": True,
            "engagement_snapshot_enabled": True,
            "daily_research_enabled": True,
            "niche_scan_enabled": True,
            "advisory_review_enabled": True,
            "advisory_review_window_hours": 12,
            "memory_quality_observatory_enabled": True,
        }

    def test_task_runs_when_due(self):
        config = self._base_config()
        state = {}  # No last_run = always due
        mock_fn = MagicMock(return_value={"ok": True})

        with patch.dict(sched.TASKS, {
            "mention_poll": {
                "fn": mock_fn,
                "config_key_interval": "mention_poll_interval",
                "config_key_enabled": "mention_poll_enabled",
            },
        }), patch.object(sched, "_save_state"):
            stats = sched.run_due_tasks(config, state, only_task="mention_poll")

        mock_fn.assert_called_once()
        self.assertIn("mention_poll", stats)

    def test_task_skipped_when_not_due(self):
        config = self._base_config()
        state = {"last_run_mention_poll": time.time()}  # Just ran
        mock_fn = MagicMock(return_value={"ok": True})

        with patch.dict(sched.TASKS, {
            "mention_poll": {
                "fn": mock_fn,
                "config_key_interval": "mention_poll_interval",
                "config_key_enabled": "mention_poll_enabled",
            },
        }), patch.object(sched, "_save_state"):
            stats = sched.run_due_tasks(config, state, only_task="mention_poll")

        mock_fn.assert_not_called()
        self.assertEqual(stats, {})

    def test_task_skipped_when_disabled(self):
        config = self._base_config()
        config["mention_poll_enabled"] = False
        state = {}  # Would be due, but disabled
        mock_fn = MagicMock(return_value={"ok": True})

        with patch.dict(sched.TASKS, {
            "mention_poll": {
                "fn": mock_fn,
                "config_key_interval": "mention_poll_interval",
                "config_key_enabled": "mention_poll_enabled",
            },
        }), patch.object(sched, "_save_state"):
            stats = sched.run_due_tasks(config, state, only_task="mention_poll")

        mock_fn.assert_not_called()

    def test_force_overrides_interval(self):
        config = self._base_config()
        state = {"last_run_mention_poll": time.time()}  # Just ran
        mock_fn = MagicMock(return_value={"forced": True})

        with patch.dict(sched.TASKS, {
            "mention_poll": {
                "fn": mock_fn,
                "config_key_interval": "mention_poll_interval",
                "config_key_enabled": "mention_poll_enabled",
            },
        }), patch.object(sched, "_save_state"):
            stats = sched.run_due_tasks(config, state, only_task="mention_poll", force=True)

        mock_fn.assert_called_once()
        self.assertIn("mention_poll", stats)

    def test_force_overrides_disabled(self):
        config = self._base_config()
        config["mention_poll_enabled"] = False
        state = {}
        mock_fn = MagicMock(return_value={"forced": True})

        with patch.dict(sched.TASKS, {
            "mention_poll": {
                "fn": mock_fn,
                "config_key_interval": "mention_poll_interval",
                "config_key_enabled": "mention_poll_enabled",
            },
        }), patch.object(sched, "_save_state"):
            stats = sched.run_due_tasks(config, state, only_task="mention_poll", force=True)

        mock_fn.assert_called_once()

    def test_task_failure_doesnt_block_others(self):
        config = self._base_config()
        state = {}
        fail_fn = MagicMock(side_effect=RuntimeError("boom"))
        ok_fn = MagicMock(return_value={"ok": True})

        with patch.dict(sched.TASKS, {
            "mention_poll": {
                "fn": fail_fn,
                "config_key_interval": "mention_poll_interval",
                "config_key_enabled": "mention_poll_enabled",
            },
            "engagement_snapshots": {
                "fn": ok_fn,
                "config_key_interval": "engagement_snapshot_interval",
                "config_key_enabled": "engagement_snapshot_enabled",
            },
        }), patch.object(sched, "_save_state"), \
             patch("spark_scheduler.log_exception"):
            stats = sched.run_due_tasks(config, state)

        # Both tasks attempted
        fail_fn.assert_called_once()
        ok_fn.assert_called_once()
        # Failed task recorded error
        self.assertIn("error", stats["mention_poll"])
        # OK task succeeded
        self.assertEqual(stats["engagement_snapshots"], {"ok": True})

    def test_only_task_filters(self):
        config = self._base_config()
        state = {}
        poll_fn = MagicMock(return_value={"polled": True})
        snap_fn = MagicMock(return_value={"snapped": True})

        with patch.dict(sched.TASKS, {
            "mention_poll": {
                "fn": poll_fn,
                "config_key_interval": "mention_poll_interval",
                "config_key_enabled": "mention_poll_enabled",
            },
            "engagement_snapshots": {
                "fn": snap_fn,
                "config_key_interval": "engagement_snapshot_interval",
                "config_key_enabled": "engagement_snapshot_enabled",
            },
        }), patch.object(sched, "_save_state"):
            stats = sched.run_due_tasks(config, state, only_task="mention_poll", force=True)

        poll_fn.assert_called_once()
        snap_fn.assert_not_called()

    def test_state_updated_after_success(self):
        config = self._base_config()
        state = {}
        mock_fn = MagicMock(return_value={"ok": True})
        saved_state = {}

        def capture_state(s):
            saved_state.update(s)

        with patch.dict(sched.TASKS, {
            "mention_poll": {
                "fn": mock_fn,
                "config_key_interval": "mention_poll_interval",
                "config_key_enabled": "mention_poll_enabled",
            },
        }), patch.object(sched, "_save_state", side_effect=capture_state):
            sched.run_due_tasks(config, state, only_task="mention_poll", force=True)

        self.assertIn("last_run_mention_poll", saved_state)
        self.assertEqual(saved_state["last_result_mention_poll"], "ok")

    def test_state_records_error_on_failure(self):
        config = self._base_config()
        state = {}
        fail_fn = MagicMock(side_effect=ValueError("test error"))
        saved_state = {}

        def capture_state(s):
            saved_state.update(s)

        with patch.dict(sched.TASKS, {
            "mention_poll": {
                "fn": fail_fn,
                "config_key_interval": "mention_poll_interval",
                "config_key_enabled": "mention_poll_enabled",
            },
        }), patch.object(sched, "_save_state", side_effect=capture_state), \
             patch("spark_scheduler.log_exception"):
            sched.run_due_tasks(config, state, only_task="mention_poll", force=True)

        self.assertIn("error:", saved_state["last_result_mention_poll"])


class TestAdvisoryReviewTask(unittest.TestCase):
    """Advisory self-review scheduler task behavior."""

    def test_advisory_review_task_success(self):
        with patch.object(sched, "load_scheduler_config", return_value={"advisory_review_window_hours": 12}), \
             patch("spark_scheduler.subprocess.run") as mock_run, \
             patch("glob.glob", return_value=[]):  # bypass file-based gap guard
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Advisory self-review written: docs/reports/x.md\n",
                stderr="",
            )
            out = sched.task_advisory_review({})
        self.assertEqual(out["status"], "ok")
        self.assertIn("Advisory self-review written", out["message"])

    def test_advisory_review_runs_memory_observatory_when_due(self):
        with patch.object(sched, "load_scheduler_config", return_value={"advisory_review_window_hours": 12}), \
             patch("spark_scheduler.subprocess.run") as mock_run, \
             patch("glob.glob", return_value=[]):
            mock_run.side_effect = [
                MagicMock(
                    returncode=0,
                    stdout="Advisory self-review written: docs/reports/x.md\n",
                    stderr="",
                ),
                MagicMock(
                    returncode=0,
                    stdout="{\"grade\":{\"band\":\"YELLOW\"}}\n",
                    stderr="",
                ),
            ]
            out = sched.task_advisory_review({})
        self.assertEqual(out["status"], "ok")
        self.assertGreaterEqual(mock_run.call_count, 2)

    def test_advisory_review_skips_memory_observatory_when_disabled(self):
        with patch.object(
            sched,
            "load_scheduler_config",
            return_value={
                "advisory_review_window_hours": 12,
                "memory_quality_observatory_enabled": False,
            },
        ), patch("spark_scheduler.subprocess.run") as mock_run, \
             patch("glob.glob", return_value=[]):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Advisory self-review written: docs/reports/x.md\n",
                stderr="",
            )
            out = sched.task_advisory_review({})
        self.assertEqual(out["status"], "ok")
        self.assertEqual(mock_run.call_count, 1)

if __name__ == "__main__":
    unittest.main()
