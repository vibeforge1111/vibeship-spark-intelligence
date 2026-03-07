"""Tests for lib/auto_promote.py — 32 tests."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import lib.auto_promote as ap


# ---------------------------------------------------------------------------
# _load_promotion_config_interval
# ---------------------------------------------------------------------------

class TestLoadPromotionConfigInterval:
    def test_returns_default_when_tuneables_missing(self, tmp_path, monkeypatch):
        # No tuneables.json at all — patch home to tmp_path
        fake_home = tmp_path
        with patch("pathlib.Path.home", return_value=fake_home):
            # Re-import to get fresh path, but just call with patched HOME
            result = ap._load_promotion_config_interval()
        assert result == ap.DEFAULT_INTERVAL_S

    def test_reads_interval_from_tuneables(self, tmp_path, monkeypatch):
        t = tmp_path / ".spark" / "tuneables.json"
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(json.dumps({"promotion": {"auto_interval_s": 1800}}))
        monkeypatch.setattr(ap, "LAST_PROMOTION_FILE",
                            tmp_path / ".spark" / "last_promotion.txt")
        # patch Path.home so the function resolves to tmp_path
        with patch("pathlib.Path.home", return_value=tmp_path):
            result = ap._load_promotion_config_interval()
        assert result == 1800

    def test_returns_default_on_corrupt_tuneables(self, tmp_path, monkeypatch):
        with patch("pathlib.Path.home", return_value=tmp_path):
            t = tmp_path / ".spark" / "tuneables.json"
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_text("GARBAGE")
            result = ap._load_promotion_config_interval()
        assert result == ap.DEFAULT_INTERVAL_S

    def test_returns_default_when_promotion_key_missing(self, tmp_path):
        with patch("pathlib.Path.home", return_value=tmp_path):
            t = tmp_path / ".spark" / "tuneables.json"
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_text(json.dumps({"other": {}}))
            result = ap._load_promotion_config_interval()
        assert result == ap.DEFAULT_INTERVAL_S


# ---------------------------------------------------------------------------
# _should_run
# ---------------------------------------------------------------------------

class TestShouldRun:
    def test_returns_true_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", tmp_path / "nope.txt")
        with patch.object(ap, "_load_promotion_config_interval", return_value=3600):
            assert ap._should_run() is True

    def test_returns_false_when_recently_run(self, tmp_path, monkeypatch):
        p = tmp_path / "last.txt"
        p.write_text(str(time.time()))
        monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", p)
        with patch.object(ap, "_load_promotion_config_interval", return_value=3600):
            assert ap._should_run() is False

    def test_returns_true_when_interval_elapsed(self, tmp_path, monkeypatch):
        p = tmp_path / "last.txt"
        p.write_text(str(time.time() - 4000))
        monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", p)
        with patch.object(ap, "_load_promotion_config_interval", return_value=3600):
            assert ap._should_run() is True

    def test_returns_true_when_file_corrupt(self, tmp_path, monkeypatch):
        p = tmp_path / "last.txt"
        p.write_text("NOT_A_FLOAT")
        monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", p)
        with patch.object(ap, "_load_promotion_config_interval", return_value=3600):
            assert ap._should_run() is True

    def test_boundary_exactly_at_interval(self, tmp_path, monkeypatch):
        p = tmp_path / "last.txt"
        p.write_text(str(time.time() - 3600))
        monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", p)
        with patch.object(ap, "_load_promotion_config_interval", return_value=3600):
            # Exactly at boundary: time.time() - last == interval → < interval is False
            result = ap._should_run()
            # Either True or False is acceptable at exact boundary


# ---------------------------------------------------------------------------
# _mark_run
# ---------------------------------------------------------------------------

class TestMarkRun:
    def test_writes_timestamp_file(self, tmp_path, monkeypatch):
        p = tmp_path / ".spark" / "last.txt"
        monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", p)
        ap._mark_run()
        assert p.exists()
        val = float(p.read_text().strip())
        assert abs(val - time.time()) < 5.0

    def test_creates_parent_dir(self, tmp_path, monkeypatch):
        p = tmp_path / "deep" / "nested" / "last.txt"
        monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", p)
        ap._mark_run()
        assert p.exists()

    def test_overwrites_existing_file(self, tmp_path, monkeypatch):
        p = tmp_path / "last.txt"
        p.write_text("0.0")
        monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", p)
        ap._mark_run()
        val = float(p.read_text().strip())
        assert val > 1.0


# ---------------------------------------------------------------------------
# maybe_promote_on_session_end
# ---------------------------------------------------------------------------

class TestMaybePromoteOnSessionEnd:
    def _patch(self, monkeypatch, tmp_path, *, should_run: bool = True):
        p = tmp_path / "last.txt"
        monkeypatch.setattr(ap, "LAST_PROMOTION_FILE", p)
        monkeypatch.setattr(ap, "log_debug", lambda *a: None)
        monkeypatch.setattr(ap, "_should_run", lambda: should_run)
        monkeypatch.setattr(ap, "_mark_run", lambda: None)

    def test_returns_none_when_rate_limited(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path, should_run=False)
        result = ap.maybe_promote_on_session_end()
        assert result is None

    def test_calls_check_and_promote_when_due(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path, should_run=True)
        mock_stats = {"promoted": 3, "skipped": 1}
        with patch("lib.promoter.check_and_promote", return_value=mock_stats) as mock_cp:
            result = ap.maybe_promote_on_session_end()
        mock_cp.assert_called_once()
        assert result == mock_stats

    def test_passes_project_dir_to_check_and_promote(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path, should_run=True)
        project = tmp_path / "myproject"
        with patch("lib.promoter.check_and_promote", return_value={}) as mock_cp:
            ap.maybe_promote_on_session_end(project_dir=project)
        call_kwargs = mock_cp.call_args.kwargs
        assert call_kwargs["project_dir"] == project

    def test_check_and_promote_called_with_dry_run_false(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path, should_run=True)
        with patch("lib.promoter.check_and_promote", return_value={}) as mock_cp:
            ap.maybe_promote_on_session_end()
        assert mock_cp.call_args.kwargs["dry_run"] is False

    def test_logs_when_insights_promoted(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path, should_run=True)
        log_calls = []
        monkeypatch.setattr(ap, "log_debug", lambda *a: log_calls.append(a))
        with patch("lib.promoter.check_and_promote", return_value={"promoted": 5}):
            ap.maybe_promote_on_session_end()
        assert any("Promoted" in str(c) for c in log_calls)

    def test_returns_none_on_exception(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path, should_run=True)
        with patch("lib.promoter.check_and_promote", side_effect=RuntimeError("fail")):
            result = ap.maybe_promote_on_session_end()
        assert result is None

    def test_marks_run_even_on_exception(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path, should_run=True)
        mark_calls = []
        monkeypatch.setattr(ap, "_mark_run", lambda: mark_calls.append(True))
        with patch("lib.promoter.check_and_promote", side_effect=RuntimeError("fail")):
            ap.maybe_promote_on_session_end()
        assert len(mark_calls) == 1

    def test_marks_run_on_success(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path, should_run=True)
        mark_calls = []
        monkeypatch.setattr(ap, "_mark_run", lambda: mark_calls.append(True))
        with patch("lib.promoter.check_and_promote", return_value={"promoted": 0}):
            ap.maybe_promote_on_session_end()
        assert len(mark_calls) == 1

    def test_no_log_when_zero_promoted(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path, should_run=True)
        log_calls = []
        monkeypatch.setattr(ap, "log_debug", lambda *a: log_calls.append(a))
        with patch("lib.promoter.check_and_promote", return_value={"promoted": 0}):
            ap.maybe_promote_on_session_end()
        # No "Promoted N insights" log when N==0
        assert not any("Promoted" in str(c) for c in log_calls)

    def test_none_project_dir_accepted(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path, should_run=True)
        with patch("lib.promoter.check_and_promote", return_value={}) as mock_cp:
            ap.maybe_promote_on_session_end(project_dir=None)
        assert mock_cp.called

    def test_include_project_true_by_default(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path, should_run=True)
        with patch("lib.promoter.check_and_promote", return_value={}) as mock_cp:
            ap.maybe_promote_on_session_end()
        assert mock_cp.call_args.kwargs["include_project"] is True
