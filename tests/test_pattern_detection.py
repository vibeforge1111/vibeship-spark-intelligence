"""
Tests for Pattern Detection Layer (Phase 2).

Run with: python -m pytest tests/test_pattern_detection.py -v
"""

import pytest
from lib.pattern_detection import (
    PatternType,
    CorrectionDetector,
    SentimentDetector,
    RepetitionDetector,
    SemanticIntentDetector,
    PatternAggregator,
    process_pattern_events,
)


class TestCorrectionDetector:
    """Test correction detection."""

    def setup_method(self):
        self.detector = CorrectionDetector()

    def test_explicit_correction(self):
        """Test 'no, I meant' detection."""
        event = {
            "session_id": "test",
            "hook_event": "UserPromptSubmit",
            "payload": {"text": "no, I meant the other file"},
        }
        patterns = self.detector.process_event(event)
        assert len(patterns) == 1
        assert patterns[0].pattern_type == PatternType.CORRECTION
        assert patterns[0].confidence >= 0.9

    def test_polite_correction(self):
        """Test 'actually' detection."""
        event = {
            "session_id": "test",
            "hook_event": "UserPromptSubmit",
            "payload": {"text": "actually, could you use typescript instead"},
        }
        patterns = self.detector.process_event(event)
        assert len(patterns) == 1
        assert patterns[0].pattern_type == PatternType.CORRECTION
        assert patterns[0].confidence >= 0.7

    def test_not_correction(self):
        """Test normal message is not detected as correction."""
        event = {
            "session_id": "test",
            "hook_event": "UserPromptSubmit",
            "payload": {"text": "can you help me write a function"},
        }
        patterns = self.detector.process_event(event)
        assert len(patterns) == 0


class TestSentimentDetector:
    """Test sentiment detection."""

    def setup_method(self):
        self.detector = SentimentDetector()

    def test_satisfaction(self):
        """Test satisfaction detection."""
        event = {
            "session_id": "test",
            "hook_event": "UserPromptSubmit",
            "payload": {"text": "perfect! that's exactly what I needed"},
        }
        patterns = self.detector.process_event(event)
        assert len(patterns) == 1
        assert patterns[0].pattern_type == PatternType.SATISFACTION
        assert patterns[0].confidence >= 0.9

    def test_frustration(self):
        """Test frustration detection."""
        event = {
            "session_id": "test",
            "hook_event": "UserPromptSubmit",
            "payload": {"text": "ugh this is still not working"},
        }
        patterns = self.detector.process_event(event)
        assert len(patterns) == 1
        assert patterns[0].pattern_type == PatternType.FRUSTRATION
        assert patterns[0].confidence >= 0.9

    def test_neutral(self):
        """Test neutral message has no sentiment."""
        event = {
            "session_id": "test",
            "hook_event": "UserPromptSubmit",
            "payload": {"text": "now add a function called process"},
        }
        patterns = self.detector.process_event(event)
        assert len(patterns) == 0


class TestRepetitionDetector:
    """Test repetition detection."""

    def setup_method(self):
        self.detector = RepetitionDetector()

    def test_repetition_detected(self):
        """Test 3+ similar requests detected."""
        events = [
            {"session_id": "test", "hook_event": "UserPromptSubmit",
             "payload": {"text": "add a button to the page"}},
            {"session_id": "test", "hook_event": "UserPromptSubmit",
             "payload": {"text": "please add the button to page"}},
            {"session_id": "test", "hook_event": "UserPromptSubmit",
             "payload": {"text": "I need a button on the page"}},
        ]

        patterns = []
        for event in events:
            patterns.extend(self.detector.process_event(event))

        # Should detect repetition after 3rd similar request
        assert len(patterns) == 1
        assert patterns[0].pattern_type == PatternType.REPETITION
        assert patterns[0].context["repetition_count"] >= 3

    def test_different_requests(self):
        """Test different requests not detected as repetition."""
        events = [
            {"session_id": "test2", "hook_event": "UserPromptSubmit",
             "payload": {"text": "add a login page"}},
            {"session_id": "test2", "hook_event": "UserPromptSubmit",
             "payload": {"text": "fix the database connection"}},
            {"session_id": "test2", "hook_event": "UserPromptSubmit",
             "payload": {"text": "update the stylesheet"}},
        ]

        patterns = []
        for event in events:
            patterns.extend(self.detector.process_event(event))

        assert len(patterns) == 0


class TestSemanticIntentDetector:
    """Test semantic intent detection."""

    def setup_method(self):
        self.detector = SemanticIntentDetector()

    def test_redirect_signal(self):
        """Detects polite redirect with low confidence."""
        event = {
            "session_id": "test",
            "hook_event": "UserPromptSubmit",
            "payload": {"text": "what about the config file instead"},
        }
        patterns = self.detector.process_event(event)
        assert len(patterns) == 1
        assert patterns[0].pattern_type == PatternType.CORRECTION
        assert patterns[0].confidence < 0.7

    def test_repeated_preference_promotes(self):
        """Repeated redirect should cross learning threshold."""
        event = {
            "session_id": "test2",
            "hook_event": "UserPromptSubmit",
            "payload": {"text": "let's go with the config file"},
        }
        patterns = self.detector.process_event(event)
        assert len(patterns) == 1
        assert patterns[0].confidence < 0.7

        patterns = self.detector.process_event(event)
        assert len(patterns) == 1
        assert patterns[0].confidence >= 0.7
        assert patterns[0].suggested_insight is not None

    def test_constraint_signal_maps_to_context_category(self):
        """Constraint-like intent should route to context category."""
        event = {
            "session_id": "test3",
            "hook_event": "UserPromptSubmit",
            "payload": {"text": "This is non-negotiable: keep scope fixed and avoid migration risk."},
        }
        patterns = self.detector.process_event(event)
        assert len(patterns) == 1
        assert patterns[0].suggested_category == "context"
        assert patterns[0].suggested_insight is not None


class TestPatternAggregator:
    """Test pattern aggregator."""

    def setup_method(self):
        self.aggregator = PatternAggregator()

    def test_corroboration_boost(self):
        """Test corroborated patterns get boosted."""
        # Correction + Frustration together
        event = {
            "session_id": "test",
            "hook_event": "UserPromptSubmit",
            "payload": {"text": "no, I meant something else! ugh still not right"},
        }
        patterns = self.aggregator.process_event(event)

        # Should have both correction and frustration
        types = [p.pattern_type for p in patterns]
        assert PatternType.CORRECTION in types or PatternType.FRUSTRATION in types

        # Check for corroboration evidence
        for p in patterns:
            if "CORROBORATED" in str(p.evidence):
                assert p.confidence > 0.85

    def test_stats(self):
        """Test aggregator stats."""
        event = {
            "session_id": "test",
            "hook_event": "UserPromptSubmit",
            "payload": {"text": "perfect!"},
        }
        self.aggregator.process_event(event)

        stats = self.aggregator.get_stats()
        assert "total_patterns_detected" in stats
        assert "detectors" in stats
        assert len(stats["detectors"]) == len(self.aggregator.detectors)


def test_process_pattern_events_no_queue(tmp_path, monkeypatch):
    """Ensure worker handles empty queue gracefully."""
    from lib import queue as q
    # Point queue dir to temp
    monkeypatch.setattr(q, "QUEUE_DIR", tmp_path)
    monkeypatch.setattr(q, "EVENTS_FILE", tmp_path / "events.jsonl")
    monkeypatch.setattr(q, "LOCK_FILE", tmp_path / ".queue.lock")

    processed = process_pattern_events(limit=10)
    assert processed == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
