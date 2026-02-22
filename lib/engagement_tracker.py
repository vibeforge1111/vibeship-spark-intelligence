#!/usr/bin/env python3
"""
Engagement Pulse - Async engagement tracking and prediction.

Registers tweets, takes engagement snapshots at 1h/6h/24h,
predicts engagement, and detects surprise over/underperformance.

"The algorithm remembers what you forget. Track everything."
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# State directory
PULSE_DIR = Path.home() / ".spark" / "engagement_pulse"
TRACKED_FILE = PULSE_DIR / "tracked_tweets.json"


# Snapshot intervals in seconds
SNAPSHOT_INTERVALS = {
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EngagementSnapshot:
    """A point-in-time capture of engagement metrics."""

    age_label: str  # 1h, 6h, 24h
    timestamp: float
    likes: int = 0
    replies: int = 0
    retweets: int = 0
    impressions: int = 0

    @property
    def total_engagement(self) -> int:
        return self.likes + self.replies + self.retweets

    @property
    def velocity(self) -> float:
        """Engagements per hour since posting."""
        hours = max(0.1, (self.timestamp - self.timestamp) / 3600)  # placeholder
        return self.total_engagement / hours


@dataclass
class EngagementPrediction:
    """A predicted engagement outcome."""

    predicted_likes: int = 0
    predicted_replies: int = 0
    predicted_retweets: int = 0
    confidence: float = 0.5
    reasoning: str = ""

    @property
    def predicted_total(self) -> int:
        return self.predicted_likes + self.predicted_replies + self.predicted_retweets


@dataclass
class TrackedTweet:
    """A tweet being tracked for engagement."""

    tweet_id: str
    content_preview: str  # First 100 chars
    posted_at: float  # Unix timestamp
    tone: str = "conversational"
    topic: str = ""
    is_reply: bool = False
    is_thread: bool = False

    prediction: Optional[Dict] = None  # EngagementPrediction as dict
    snapshots: Dict[str, Dict] = field(default_factory=dict)  # age_label -> snapshot dict
    surprise_detected: bool = False
    surprise_type: str = ""  # overperform / underperform
    surprise_ratio: float = 1.0


# ---------------------------------------------------------------------------
# Core Engagement Tracker
# ---------------------------------------------------------------------------


class EngagementTracker:
    """Tracks tweet engagement over time and learns prediction accuracy.

    Key capabilities:
    - Register tweets for tracking
    - Predict engagement based on learned patterns
    - Take snapshots at 1h/6h/24h intervals
    - Detect surprises (actual >> predicted or actual << predicted)
    - Track prediction accuracy over time
    """

    SURPRISE_THRESHOLD_HIGH = 2.0  # actual/predicted > 2x = overperform
    SURPRISE_THRESHOLD_LOW = 0.3  # actual/predicted < 0.3x = underperform

    def __init__(self) -> None:
        self.tracked: Dict[str, TrackedTweet] = {}
        self._prediction_history: List[Dict] = []
        self._load()

    def _load(self) -> None:
        """Load tracked tweets from disk."""
        if TRACKED_FILE.exists():
            try:
                raw = json.loads(TRACKED_FILE.read_text(encoding="utf-8"))
                for tid, data in raw.get("tracked", {}).items():
                    self.tracked[tid] = TrackedTweet(**data)
                self._prediction_history = raw.get("prediction_history", [])
            except Exception:
                pass

    def _save(self) -> None:
        """Persist tracked tweets."""
        PULSE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "tracked": {tid: asdict(t) for tid, t in self.tracked.items()},
            "prediction_history": self._prediction_history[-200:],
        }
        TRACKED_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ------ Registration ------

    def register_tweet(
        self,
        tweet_id: str,
        content: str,
        tone: str = "conversational",
        topic: str = "",
        is_reply: bool = False,
        is_thread: bool = False,
    ) -> TrackedTweet:
        """Register a tweet for engagement tracking.

        Args:
            tweet_id: The tweet's ID
            content: Tweet content
            tone: Tone used
            topic: Topic of the tweet
            is_reply: Whether it's a reply
            is_thread: Whether it starts a thread

        Returns:
            The TrackedTweet object
        """
        tweet = TrackedTweet(
            tweet_id=tweet_id,
            content_preview=content[:100],
            posted_at=time.time(),
            tone=tone,
            topic=topic,
            is_reply=is_reply,
            is_thread=is_thread,
        )

        # Generate prediction
        prediction = self.predict_engagement(tone, topic, is_reply, is_thread)
        tweet.prediction = asdict(prediction)

        self.tracked[tweet_id] = tweet
        self._save()
        return tweet

    # ------ Prediction ------

    def predict_engagement(
        self,
        tone: str = "conversational",
        topic: str = "",
        is_reply: bool = False,
        is_thread: bool = False,
    ) -> EngagementPrediction:
        """Predict engagement for a tweet.

        Uses learned baselines and adjusts for tone, topic, format.

        Returns:
            EngagementPrediction with estimated likes/replies/retweets
        """
        # Base predictions from historical data
        base_likes = 5
        base_replies = 2
        base_retweets = 1

        # Tone adjustments
        tone_multiplier = {
            "witty": 1.3,
            "technical": 0.9,
            "conversational": 1.0,
            "provocative": 1.5,
        }.get(tone, 1.0)

        # Format adjustments
        if is_reply:
            base_likes = max(1, int(base_likes * 0.5))
            base_replies = max(1, int(base_replies * 1.5))
            base_retweets = max(0, int(base_retweets * 0.3))
        elif is_thread:
            base_likes = int(base_likes * 1.5)
            base_retweets = int(base_retweets * 2.0)

        # Apply tone multiplier
        predicted_likes = max(1, int(base_likes * tone_multiplier))
        predicted_replies = max(1, int(base_replies * tone_multiplier))
        predicted_retweets = max(0, int(base_retweets * tone_multiplier))

        # Learn from history
        confidence = 0.3  # Start low
        if self._prediction_history:
            # Improve confidence based on prediction accuracy
            recent = self._prediction_history[-20:]
            accurate = sum(1 for p in recent if p.get("accurate", False))
            confidence = min(0.9, 0.3 + (accurate / len(recent)) * 0.6)

        reasoning = f"Base prediction for {tone} tone"
        if is_reply:
            reasoning += " (reply - lower likes, higher replies)"
        if is_thread:
            reasoning += " (thread - higher likes, higher retweets)"

        return EngagementPrediction(
            predicted_likes=predicted_likes,
            predicted_replies=predicted_replies,
            predicted_retweets=predicted_retweets,
            confidence=confidence,
            reasoning=reasoning,
        )

    # ------ Snapshots ------

    def take_snapshot(
        self,
        tweet_id: str,
        likes: int = 0,
        replies: int = 0,
        retweets: int = 0,
        impressions: int = 0,
    ) -> Optional[EngagementSnapshot]:
        """Take an engagement snapshot for a tracked tweet.

        Automatically determines the age label (1h/6h/24h) based
        on how long ago the tweet was posted.

        Args:
            tweet_id: Which tweet
            likes: Current likes
            replies: Current replies
            retweets: Current retweets
            impressions: Current impressions

        Returns:
            The snapshot, or None if tweet isn't tracked
        """
        if tweet_id not in self.tracked:
            return None

        tweet = self.tracked[tweet_id]
        now = time.time()
        age_seconds = now - tweet.posted_at

        # Determine appropriate age label
        age_label = self._determine_age_label(age_seconds)
        if not age_label:
            return None

        # Don't overwrite existing snapshots
        if age_label in tweet.snapshots:
            return None

        snapshot = EngagementSnapshot(
            age_label=age_label,
            timestamp=now,
            likes=likes,
            replies=replies,
            retweets=retweets,
            impressions=impressions,
        )

        tweet.snapshots[age_label] = asdict(snapshot)

        # Check for surprise
        self._check_surprise(tweet, snapshot)

        self._save()
        return snapshot

    def _determine_age_label(self, age_seconds: float) -> Optional[str]:
        """Determine which snapshot interval this falls into."""
        for label, threshold in SNAPSHOT_INTERVALS.items():
            # Allow 20% window around each interval
            lower = threshold * 0.8
            upper = threshold * 1.5
            if lower <= age_seconds <= upper:
                return label
        return None

    def get_pending_snapshots(self) -> List[Tuple[str, str]]:
        """Get tweets that need snapshots taken.

        Returns:
            List of (tweet_id, age_label) tuples for snapshots due
        """
        pending = []
        now = time.time()

        for tid, tweet in self.tracked.items():
            age = now - tweet.posted_at
            for label, threshold in SNAPSHOT_INTERVALS.items():
                if label not in tweet.snapshots:
                    # Check if we're in the window for this snapshot
                    if age >= threshold * 0.8:
                        pending.append((tid, label))

        return pending

    # ------ Surprise Detection ------

    def _check_surprise(self, tweet: TrackedTweet, snapshot: EngagementSnapshot) -> None:
        """Check if actual engagement is a surprise vs prediction."""
        if not tweet.prediction:
            return

        predicted_total = (
            tweet.prediction.get("predicted_likes", 0)
            + tweet.prediction.get("predicted_replies", 0)
            + tweet.prediction.get("predicted_retweets", 0)
        )

        if predicted_total == 0:
            predicted_total = 1  # Avoid division by zero

        actual_total = snapshot.total_engagement
        ratio = actual_total / predicted_total

        if ratio >= self.SURPRISE_THRESHOLD_HIGH:
            tweet.surprise_detected = True
            tweet.surprise_type = "overperform"
            tweet.surprise_ratio = round(ratio, 2)
        elif ratio <= self.SURPRISE_THRESHOLD_LOW:
            tweet.surprise_detected = True
            tweet.surprise_type = "underperform"
            tweet.surprise_ratio = round(ratio, 2)

        # Record for learning
        self._prediction_history.append({
            "tweet_id": tweet.tweet_id,
            "predicted_total": predicted_total,
            "actual_total": actual_total,
            "ratio": round(ratio, 2),
            "accurate": 0.5 <= ratio <= 2.0,
            "snapshot_age": snapshot.age_label,
            "timestamp": time.time(),
        })

    def detect_surprise(self, tweet_id: str) -> Optional[Dict[str, Any]]:
        """Check if a tracked tweet has a detected surprise.

        Returns:
            Dict with surprise info, or None
        """
        if tweet_id not in self.tracked:
            return None

        tweet = self.tracked[tweet_id]
        if not tweet.surprise_detected:
            return None

        return {
            "tweet_id": tweet_id,
            "surprise_type": tweet.surprise_type,
            "surprise_ratio": tweet.surprise_ratio,
            "content_preview": tweet.content_preview,
            "tone": tweet.tone,
            "topic": tweet.topic,
        }

    # ------ Accuracy ------

    def get_prediction_accuracy(self, last_n: int = 20) -> Dict[str, Any]:
        """Get prediction accuracy metrics.

        Returns:
            Dict with accuracy percentage, avg ratio, etc.
        """
        if not self._prediction_history:
            return {
                "accuracy": 0.0,
                "total_predictions": 0,
                "avg_ratio": 0.0,
            }

        recent = self._prediction_history[-last_n:]
        accurate = sum(1 for p in recent if p.get("accurate", False))
        ratios = [p.get("ratio", 1.0) for p in recent]

        return {
            "accuracy": round(accurate / len(recent) * 100, 1),
            "total_predictions": len(self._prediction_history),
            "recent_predictions": len(recent),
            "avg_ratio": round(sum(ratios) / len(ratios), 2),
            "overperformers": sum(1 for r in ratios if r > 2.0),
            "underperformers": sum(1 for r in ratios if r < 0.3),
        }

    # ------ Stats ------

    def get_stats(self) -> Dict[str, Any]:
        """Get engagement tracker statistics."""
        surprises = [t for t in self.tracked.values() if t.surprise_detected]

        return {
            "tracked_tweets": len(self.tracked),
            "total_snapshots": sum(
                len(t.snapshots) for t in self.tracked.values()
            ),
            "surprises_detected": len(surprises),
            "overperformers": sum(
                1 for s in surprises if s.surprise_type == "overperform"
            ),
            "underperformers": sum(
                1 for s in surprises if s.surprise_type == "underperform"
            ),
            "prediction_accuracy": self.get_prediction_accuracy(),
        }

    def cleanup_old(self, max_age_days: int = 7) -> None:
        """Remove tweets older than max_age_days."""
        cutoff = time.time() - (max_age_days * 86400)
        to_remove = [
            tid
            for tid, t in self.tracked.items()
            if t.posted_at < cutoff
        ]
        for tid in to_remove:
            del self.tracked[tid]
        if to_remove:
            self._save()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_tracker: Optional[EngagementTracker] = None


def get_engagement_tracker() -> EngagementTracker:
    """Get the singleton EngagementTracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = EngagementTracker()
    return _tracker
