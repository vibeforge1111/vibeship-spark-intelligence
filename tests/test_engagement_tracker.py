"""Tests for lib/engagement_tracker.py — EngagementTracker pulse."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

import lib.engagement_tracker as et_mod
from lib.engagement_tracker import (
    EngagementSnapshot,
    EngagementPrediction,
    TrackedTweet,
    EngagementTracker,
    get_engagement_tracker,
    SNAPSHOT_INTERVALS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_files(tmp_path, monkeypatch):
    pulse_dir = tmp_path / "engagement_pulse"
    tracked_file = pulse_dir / "tracked_tweets.json"
    monkeypatch.setattr(et_mod, "PULSE_DIR", pulse_dir)
    monkeypatch.setattr(et_mod, "TRACKED_FILE", tracked_file)
    yield tracked_file


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    monkeypatch.setattr(et_mod, "_tracker", None)
    yield
    monkeypatch.setattr(et_mod, "_tracker", None)


def _make_tracker() -> EngagementTracker:
    return EngagementTracker()


# ---------------------------------------------------------------------------
# EngagementSnapshot
# ---------------------------------------------------------------------------

class TestEngagementSnapshot:
    def test_total_engagement_sum(self):
        snap = EngagementSnapshot(age_label="1h", timestamp=time.time(),
                                  likes=10, replies=3, retweets=2)
        assert snap.total_engagement == 15

    def test_total_engagement_zero_by_default(self):
        snap = EngagementSnapshot(age_label="1h", timestamp=time.time())
        assert snap.total_engagement == 0

    def test_defaults_zero(self):
        snap = EngagementSnapshot(age_label="1h", timestamp=time.time())
        assert snap.likes == 0
        assert snap.replies == 0
        assert snap.retweets == 0
        assert snap.impressions == 0


# ---------------------------------------------------------------------------
# EngagementPrediction
# ---------------------------------------------------------------------------

class TestEngagementPrediction:
    def test_predicted_total_sum(self):
        pred = EngagementPrediction(predicted_likes=5, predicted_replies=2, predicted_retweets=1)
        assert pred.predicted_total == 8

    def test_defaults_zero(self):
        pred = EngagementPrediction()
        assert pred.predicted_total == 0

    def test_confidence_defaults_half(self):
        assert EngagementPrediction().confidence == 0.5


# ---------------------------------------------------------------------------
# TrackedTweet
# ---------------------------------------------------------------------------

class TestTrackedTweet:
    def test_content_preview_defaults_empty(self):
        t = TrackedTweet(tweet_id="t1", content_preview="", posted_at=time.time())
        assert t.content_preview == ""

    def test_defaults(self):
        t = TrackedTweet(tweet_id="t1", content_preview="hello", posted_at=time.time())
        assert t.tone == "conversational"
        assert t.topic == ""
        assert t.is_reply is False
        assert t.is_thread is False
        assert t.surprise_detected is False
        assert t.surprise_ratio == 1.0


# ---------------------------------------------------------------------------
# EngagementTracker.register_tweet
# ---------------------------------------------------------------------------

class TestRegisterTweet:
    def test_returns_tracked_tweet(self):
        tracker = _make_tracker()
        tweet = tracker.register_tweet("t1", "Hello world")
        assert isinstance(tweet, TrackedTweet)

    def test_tweet_stored_in_tracked(self):
        tracker = _make_tracker()
        tracker.register_tweet("t1", "Hello world")
        assert "t1" in tracker.tracked

    def test_content_preview_truncated_at_100(self):
        tracker = _make_tracker()
        content = "X" * 200
        tweet = tracker.register_tweet("t1", content)
        assert len(tweet.content_preview) == 100

    def test_tone_stored(self):
        tracker = _make_tracker()
        tweet = tracker.register_tweet("t1", "hello", tone="witty")
        assert tweet.tone == "witty"

    def test_is_reply_stored(self):
        tracker = _make_tracker()
        tweet = tracker.register_tweet("t1", "hello", is_reply=True)
        assert tweet.is_reply is True

    def test_prediction_generated(self):
        tracker = _make_tracker()
        tweet = tracker.register_tweet("t1", "hello")
        assert tweet.prediction is not None

    def test_saves_to_file(self, isolate_files):
        tracker = _make_tracker()
        tracker.register_tweet("t1", "hello")
        assert isolate_files.exists()

    def test_duplicate_tweet_id_overwrites(self):
        tracker = _make_tracker()
        tracker.register_tweet("t1", "first")
        tracker.register_tweet("t1", "second")
        assert tracker.tracked["t1"].content_preview == "second"


# ---------------------------------------------------------------------------
# EngagementTracker.predict_engagement
# ---------------------------------------------------------------------------

class TestPredictEngagement:
    def test_returns_prediction(self):
        tracker = _make_tracker()
        pred = tracker.predict_engagement()
        assert isinstance(pred, EngagementPrediction)

    def test_witty_tone_higher_likes(self):
        tracker = _make_tracker()
        conv = tracker.predict_engagement(tone="conversational")
        witty = tracker.predict_engagement(tone="witty")
        assert witty.predicted_likes >= conv.predicted_likes

    def test_provocative_tone_highest(self):
        tracker = _make_tracker()
        conv = tracker.predict_engagement(tone="conversational")
        prov = tracker.predict_engagement(tone="provocative")
        assert prov.predicted_likes >= conv.predicted_likes

    def test_is_reply_lower_likes(self):
        tracker = _make_tracker()
        normal = tracker.predict_engagement()
        reply = tracker.predict_engagement(is_reply=True)
        assert reply.predicted_likes <= normal.predicted_likes

    def test_is_thread_higher_retweets(self):
        tracker = _make_tracker()
        normal = tracker.predict_engagement()
        thread = tracker.predict_engagement(is_thread=True)
        assert thread.predicted_retweets >= normal.predicted_retweets

    def test_reasoning_field_set(self):
        tracker = _make_tracker()
        pred = tracker.predict_engagement(tone="witty")
        assert "witty" in pred.reasoning

    def test_confidence_at_least_0_3(self):
        tracker = _make_tracker()
        pred = tracker.predict_engagement()
        assert pred.confidence >= 0.3

    def test_unknown_tone_uses_default_multiplier(self):
        tracker = _make_tracker()
        pred = tracker.predict_engagement(tone="unknown_tone")
        assert pred.predicted_likes >= 1


# ---------------------------------------------------------------------------
# EngagementTracker._determine_age_label
# ---------------------------------------------------------------------------

class TestDetermineAgeLabel:
    def test_within_1h_window(self):
        tracker = _make_tracker()
        # 1h = 3600s, window is 0.8x–1.5x = 2880–5400
        result = tracker._determine_age_label(3600)
        assert result == "1h"

    def test_within_6h_window(self):
        tracker = _make_tracker()
        # 6h = 21600s, window is 17280–32400
        result = tracker._determine_age_label(21600)
        assert result == "6h"

    def test_within_24h_window(self):
        tracker = _make_tracker()
        # 24h = 86400s, window is 69120–129600
        result = tracker._determine_age_label(86400)
        assert result == "24h"

    def test_too_early_returns_none(self):
        tracker = _make_tracker()
        result = tracker._determine_age_label(100)  # Way too soon
        assert result is None

    def test_too_late_returns_none(self):
        tracker = _make_tracker()
        result = tracker._determine_age_label(200000)  # Way past 24h window
        assert result is None


# ---------------------------------------------------------------------------
# EngagementTracker.take_snapshot
# ---------------------------------------------------------------------------

class TestTakeSnapshot:
    def test_returns_none_for_untracked(self):
        tracker = _make_tracker()
        assert tracker.take_snapshot("unknown_id") is None

    def test_takes_1h_snapshot(self):
        tracker = _make_tracker()
        tracker.register_tweet("t1", "hello")
        # Fake posted_at to simulate 1h+ age
        tracker.tracked["t1"].posted_at = time.time() - 4000
        snap = tracker.take_snapshot("t1", likes=5, replies=1)
        assert snap is not None
        assert snap.age_label == "1h"
        assert snap.likes == 5

    def test_no_overwrite_existing_snapshot(self):
        tracker = _make_tracker()
        tracker.register_tweet("t1", "hello")
        tracker.tracked["t1"].posted_at = time.time() - 4000
        snap1 = tracker.take_snapshot("t1", likes=5)
        snap2 = tracker.take_snapshot("t1", likes=99)  # Should not overwrite
        assert snap2 is None
        assert tracker.tracked["t1"].snapshots["1h"]["likes"] == 5

    def test_returns_none_outside_window(self):
        tracker = _make_tracker()
        tracker.register_tweet("t1", "hello")
        # posted_at = now, so age ≈ 0 — not in any window
        snap = tracker.take_snapshot("t1", likes=5)
        assert snap is None

    def test_snapshot_stored_in_tweet(self):
        tracker = _make_tracker()
        tracker.register_tweet("t1", "hello")
        tracker.tracked["t1"].posted_at = time.time() - 4000
        tracker.take_snapshot("t1", likes=10)
        assert "1h" in tracker.tracked["t1"].snapshots


# ---------------------------------------------------------------------------
# EngagementTracker.get_pending_snapshots
# ---------------------------------------------------------------------------

class TestGetPendingSnapshots:
    def test_empty_when_no_tweets(self):
        tracker = _make_tracker()
        assert tracker.get_pending_snapshots() == []

    def test_pending_when_1h_overdue(self):
        tracker = _make_tracker()
        tracker.register_tweet("t1", "hello")
        tracker.tracked["t1"].posted_at = time.time() - 4000  # >1h
        pending = tracker.get_pending_snapshots()
        tweet_ids = [p[0] for p in pending]
        assert "t1" in tweet_ids

    def test_not_pending_when_snapshot_taken(self):
        tracker = _make_tracker()
        tracker.register_tweet("t1", "hello")
        tracker.tracked["t1"].posted_at = time.time() - 4000
        tracker.take_snapshot("t1", likes=5)
        pending = tracker.get_pending_snapshots()
        labels_for_t1 = [p[1] for p in pending if p[0] == "t1"]
        assert "1h" not in labels_for_t1


# ---------------------------------------------------------------------------
# EngagementTracker surprise detection
# ---------------------------------------------------------------------------

class TestSurpriseDetection:
    def _setup_tweet_with_prediction(self, tracker, total_predicted=8):
        tracker.register_tweet("t1", "hello")
        # Override prediction to known total
        tracker.tracked["t1"].prediction = {
            "predicted_likes": total_predicted,
            "predicted_replies": 0,
            "predicted_retweets": 0,
        }
        tracker.tracked["t1"].posted_at = time.time() - 4000

    def test_overperform_detected(self):
        tracker = _make_tracker()
        self._setup_tweet_with_prediction(tracker, total_predicted=8)
        # actual > 2x predicted = 8 * 2.0 = 16
        snap = EngagementSnapshot("1h", time.time(), likes=30, replies=5, retweets=2)
        tracker._check_surprise(tracker.tracked["t1"], snap)
        assert tracker.tracked["t1"].surprise_detected is True
        assert tracker.tracked["t1"].surprise_type == "overperform"

    def test_underperform_detected(self):
        tracker = _make_tracker()
        self._setup_tweet_with_prediction(tracker, total_predicted=8)
        # actual < 0.3x predicted = 8 * 0.3 = 2.4
        snap = EngagementSnapshot("1h", time.time(), likes=1, replies=0, retweets=0)
        tracker._check_surprise(tracker.tracked["t1"], snap)
        assert tracker.tracked["t1"].surprise_detected is True
        assert tracker.tracked["t1"].surprise_type == "underperform"

    def test_normal_range_no_surprise(self):
        tracker = _make_tracker()
        self._setup_tweet_with_prediction(tracker, total_predicted=8)
        snap = EngagementSnapshot("1h", time.time(), likes=8, replies=2, retweets=1)
        tracker._check_surprise(tracker.tracked["t1"], snap)
        assert tracker.tracked["t1"].surprise_detected is False

    def test_detect_surprise_returns_none_for_unknown(self):
        tracker = _make_tracker()
        assert tracker.detect_surprise("nonexistent") is None

    def test_detect_surprise_returns_none_when_no_surprise(self):
        tracker = _make_tracker()
        tracker.register_tweet("t1", "hello")
        assert tracker.detect_surprise("t1") is None

    def test_detect_surprise_returns_dict_when_surprise(self):
        tracker = _make_tracker()
        self._setup_tweet_with_prediction(tracker, total_predicted=8)
        snap = EngagementSnapshot("1h", time.time(), likes=30, replies=5, retweets=2)
        tracker._check_surprise(tracker.tracked["t1"], snap)
        result = tracker.detect_surprise("t1")
        assert result is not None
        assert result["tweet_id"] == "t1"
        assert result["surprise_type"] == "overperform"

    def test_prediction_history_appended(self):
        tracker = _make_tracker()
        self._setup_tweet_with_prediction(tracker, total_predicted=8)
        snap = EngagementSnapshot("1h", time.time(), likes=5, replies=1, retweets=1)
        tracker._check_surprise(tracker.tracked["t1"], snap)
        assert len(tracker._prediction_history) == 1


# ---------------------------------------------------------------------------
# EngagementTracker.get_prediction_accuracy
# ---------------------------------------------------------------------------

class TestGetPredictionAccuracy:
    def test_empty_history_returns_zero_accuracy(self):
        tracker = _make_tracker()
        result = tracker.get_prediction_accuracy()
        assert result["accuracy"] == 0.0
        assert result["total_predictions"] == 0

    def test_returns_required_keys(self):
        tracker = _make_tracker()
        result = tracker.get_prediction_accuracy()
        for key in ("accuracy", "total_predictions", "avg_ratio"):
            assert key in result

    def test_accuracy_calculated(self):
        tracker = _make_tracker()
        tracker._prediction_history = [
            {"accurate": True, "ratio": 1.0},
            {"accurate": False, "ratio": 0.1},
        ]
        result = tracker.get_prediction_accuracy(last_n=2)
        assert result["accuracy"] == 50.0

    def test_limit_last_n_respected(self):
        tracker = _make_tracker()
        tracker._prediction_history = [
            {"accurate": False, "ratio": 0.1},
            {"accurate": True, "ratio": 1.0},
        ]
        result = tracker.get_prediction_accuracy(last_n=1)
        # Only last entry (accurate=True) → 100%
        assert result["accuracy"] == 100.0


# ---------------------------------------------------------------------------
# EngagementTracker.get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_returns_required_keys(self):
        tracker = _make_tracker()
        stats = tracker.get_stats()
        for key in ("tracked_tweets", "total_snapshots", "surprises_detected",
                    "overperformers", "underperformers", "prediction_accuracy"):
            assert key in stats

    def test_empty_tracker_all_zeros(self):
        tracker = _make_tracker()
        stats = tracker.get_stats()
        assert stats["tracked_tweets"] == 0
        assert stats["total_snapshots"] == 0
        assert stats["surprises_detected"] == 0

    def test_tracked_tweets_count(self):
        tracker = _make_tracker()
        tracker.register_tweet("t1", "hello")
        tracker.register_tweet("t2", "world")
        stats = tracker.get_stats()
        assert stats["tracked_tweets"] == 2

    def test_snapshots_counted(self):
        tracker = _make_tracker()
        tracker.register_tweet("t1", "hello")
        tracker.tracked["t1"].posted_at = time.time() - 4000
        tracker.take_snapshot("t1", likes=5)
        stats = tracker.get_stats()
        assert stats["total_snapshots"] == 1


# ---------------------------------------------------------------------------
# EngagementTracker.cleanup_old
# ---------------------------------------------------------------------------

class TestCleanupOld:
    def test_removes_old_tweets(self):
        tracker = _make_tracker()
        tracker.register_tweet("old", "hello")
        tracker.tracked["old"].posted_at = time.time() - (10 * 86400)  # 10 days ago
        tracker.cleanup_old(max_age_days=7)
        assert "old" not in tracker.tracked

    def test_keeps_recent_tweets(self):
        tracker = _make_tracker()
        tracker.register_tweet("recent", "hello")
        # posted_at = now (default)
        tracker.cleanup_old(max_age_days=7)
        assert "recent" in tracker.tracked

    def test_saves_after_removal(self, isolate_files):
        tracker = _make_tracker()
        tracker.register_tweet("old", "hello")
        tracker.tracked["old"].posted_at = time.time() - (10 * 86400)
        tracker.cleanup_old(max_age_days=7)
        assert isolate_files.exists()


# ---------------------------------------------------------------------------
# get_engagement_tracker singleton
# ---------------------------------------------------------------------------

class TestGetEngagementTracker:
    def test_returns_engagement_tracker(self):
        tracker = get_engagement_tracker()
        assert isinstance(tracker, EngagementTracker)

    def test_same_instance_on_second_call(self):
        t1 = get_engagement_tracker()
        t2 = get_engagement_tracker()
        assert t1 is t2

    def test_singleton_reset_between_tests(self):
        assert et_mod._tracker is None
