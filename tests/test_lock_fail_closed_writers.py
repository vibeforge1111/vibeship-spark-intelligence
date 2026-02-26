from __future__ import annotations

import contextlib
import time

from lib import advice_feedback
from lib import implicit_outcome_tracker
from lib import outcome_log


def test_advice_feedback_append_uses_fail_closed_lock(monkeypatch, tmp_path):
    calls = []

    @contextlib.contextmanager
    def _fake_lock(_path, **kwargs):
        calls.append(kwargs)
        yield

    monkeypatch.setattr(advice_feedback, "file_lock_for", _fake_lock)
    target = tmp_path / "feedback.jsonl"

    advice_feedback._append_jsonl_row(target, {"k": "v"}, max_lines=10)

    assert calls
    assert calls[0].get("fail_open") is False


def test_outcome_log_append_uses_fail_closed_lock(monkeypatch, tmp_path):
    calls = []

    @contextlib.contextmanager
    def _fake_lock(_path, **kwargs):
        calls.append(kwargs)
        yield

    monkeypatch.setattr(outcome_log, "file_lock_for", _fake_lock)
    monkeypatch.setattr(outcome_log, "OUTCOMES_FILE", tmp_path / "outcomes.jsonl")
    monkeypatch.setattr(outcome_log, "OUTCOMES_FILE_MAX", 100)

    outcome_log.append_outcome(
        {"outcome_id": "o1", "polarity": "pos", "created_at": time.time()}
    )

    assert calls
    assert calls[0].get("fail_open") is False


def test_implicit_tracker_append_uses_fail_closed_lock(monkeypatch, tmp_path):
    calls = []

    @contextlib.contextmanager
    def _fake_lock(_path, **kwargs):
        calls.append(kwargs)
        yield

    monkeypatch.setattr(implicit_outcome_tracker, "file_lock_for", _fake_lock)
    monkeypatch.setattr(
        implicit_outcome_tracker,
        "FEEDBACK_FILE",
        tmp_path / "implicit_feedback.jsonl",
    )
    tracker = implicit_outcome_tracker.ImplicitOutcomeTracker()

    tracker._append_feedback({"tool": "Read", "signal": "followed", "timestamp": time.time()})

    assert calls
    assert calls[0].get("fail_open") is False
