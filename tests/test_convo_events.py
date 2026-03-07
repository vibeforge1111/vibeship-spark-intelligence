"""Tests for lib/convo_events.py — ConvoIQ event factory and JSONL storage."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.convo_events as ce


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_convo_file(tmp_path, monkeypatch):
    f = tmp_path / "convo_events.jsonl"
    monkeypatch.setattr(ce, "CONVO_EVENTS_FILE", f)
    yield f


# ---------------------------------------------------------------------------
# create_reply_event
# ---------------------------------------------------------------------------

class TestCreateReplyEvent:
    def test_returns_dict(self):
        evt = ce.create_reply_event("Hello!", "Parent tweet")
        assert isinstance(evt, dict)

    def test_event_type(self):
        evt = ce.create_reply_event("Hello!", "Parent tweet")
        assert evt["event_type"] == "x_reply"

    def test_tool_name(self):
        evt = ce.create_reply_event("Hello!", "Parent tweet")
        assert evt["tool_name"] == "ConvoIQ"

    def test_session_id_present(self):
        evt = ce.create_reply_event("Hello!", "Parent tweet")
        assert evt["session_id"].startswith("convo_")

    def test_timestamp_recent(self):
        before = time.time()
        evt = ce.create_reply_event("Hello!", "Parent tweet")
        assert evt["timestamp"] >= before

    def test_data_contains_reply_and_parent(self):
        evt = ce.create_reply_event("My reply", "Their tweet")
        assert evt["data"]["reply_text"] == "My reply"
        assert evt["data"]["parent_text"] == "Their tweet"

    def test_defaults(self):
        evt = ce.create_reply_event("r", "p")
        assert evt["data"]["tone_used"] == "conversational"
        assert evt["data"]["hook_type"] == "observation"
        assert evt["data"]["thread_depth"] == 1
        assert evt["data"]["tweet_id"] == ""
        assert evt["data"]["reply_to_id"] == ""

    def test_author_handle(self):
        evt = ce.create_reply_event("r", "p", author_handle="@alice")
        assert evt["data"]["author_handle"] == "@alice"

    def test_tone_and_hook(self):
        evt = ce.create_reply_event("r", "p", tone_used="witty", hook_type="question")
        assert evt["data"]["tone_used"] == "witty"
        assert evt["data"]["hook_type"] == "question"

    def test_thread_depth(self):
        evt = ce.create_reply_event("r", "p", thread_depth=3)
        assert evt["data"]["thread_depth"] == 3

    def test_metadata_merged(self):
        evt = ce.create_reply_event("r", "p", metadata={"extra_key": "val"})
        assert evt["data"]["extra_key"] == "val"

    def test_input_field_present(self):
        evt = ce.create_reply_event("My reply", "Parent")
        assert evt["input"]["content"] == "My reply"
        assert evt["input"]["parent_content"] == "Parent"

    def test_tweet_ids(self):
        evt = ce.create_reply_event("r", "p", tweet_id="t1", reply_to_id="t0")
        assert evt["data"]["tweet_id"] == "t1"
        assert evt["data"]["reply_to_id"] == "t0"


# ---------------------------------------------------------------------------
# create_engagement_event
# ---------------------------------------------------------------------------

class TestCreateEngagementEvent:
    def test_event_type(self):
        evt = ce.create_engagement_event("t1")
        assert evt["event_type"] == "x_reply_engagement"

    def test_tool_name(self):
        evt = ce.create_engagement_event("t1")
        assert evt["tool_name"] == "ConvoIQ"

    def test_tweet_id_in_data(self):
        evt = ce.create_engagement_event("tweet123")
        assert evt["data"]["tweet_id"] == "tweet123"

    def test_default_counts_zero(self):
        evt = ce.create_engagement_event("t1")
        assert evt["data"]["likes"] == 0
        assert evt["data"]["replies"] == 0
        assert evt["data"]["retweets"] == 0

    def test_counts_stored(self):
        evt = ce.create_engagement_event("t1", likes=5, replies=3, retweets=2)
        assert evt["data"]["likes"] == 5
        assert evt["data"]["replies"] == 3
        assert evt["data"]["retweets"] == 2

    def test_engagement_total_formula(self):
        evt = ce.create_engagement_event("t1", likes=10, replies=2, retweets=1)
        # total = likes + replies*2 + retweets
        assert evt["data"]["engagement_total"] == 10 + 2 * 2 + 1

    def test_author_responded_flag(self):
        evt = ce.create_engagement_event("t1", author_responded=True)
        assert evt["data"]["author_responded"] is True

    def test_warmth_change(self):
        evt = ce.create_engagement_event("t1", warmth_change="increased")
        assert evt["data"]["warmth_change"] == "increased"

    def test_metadata_merged(self):
        evt = ce.create_engagement_event("t1", metadata={"campaign": "launch"})
        assert evt["data"]["campaign"] == "launch"

    def test_input_field_has_tweet_id(self):
        evt = ce.create_engagement_event("tweet-abc")
        assert evt["input"]["tweet_id"] == "tweet-abc"


# ---------------------------------------------------------------------------
# create_dna_event
# ---------------------------------------------------------------------------

class TestCreateDnaEvent:
    def test_event_type(self):
        evt = ce.create_dna_event("hook_and_expand", "question", "witty", 7.5)
        assert evt["event_type"] == "x_conversation_dna"

    def test_data_fields(self):
        evt = ce.create_dna_event("build_together", "agreement", "technical", 8.0,
                                  example_text="Great point!")
        assert evt["data"]["pattern_type"] == "build_together"
        assert evt["data"]["hook_type"] == "agreement"
        assert evt["data"]["tone"] == "technical"
        assert evt["data"]["engagement_score"] == 8.0
        assert evt["data"]["example_text"] == "Great point!"

    def test_example_text_truncated_at_280(self):
        long_text = "X" * 400
        evt = ce.create_dna_event("p", "h", "t", 5.0, example_text=long_text)
        assert len(evt["data"]["example_text"]) == 280

    def test_topic_tags_stored(self):
        evt = ce.create_dna_event("p", "h", "t", 5.0, topic_tags=["ai", "tech"])
        assert evt["data"]["topic_tags"] == ["ai", "tech"]

    def test_topic_tags_default_empty_list(self):
        evt = ce.create_dna_event("p", "h", "t", 5.0)
        assert evt["data"]["topic_tags"] == []

    def test_metadata_merged(self):
        evt = ce.create_dna_event("p", "h", "t", 5.0, metadata={"source": "x"})
        assert evt["data"]["source"] == "x"

    def test_input_field(self):
        evt = ce.create_dna_event("hook_and_expand", "h", "t", 5.0, example_text="hello")
        assert evt["input"]["pattern_type"] == "hook_and_expand"
        assert evt["input"]["content"] == "hello"


# ---------------------------------------------------------------------------
# store_convo_events
# ---------------------------------------------------------------------------

class TestStoreConvoEvents:
    def test_empty_list_returns_zero(self, isolate_convo_file):
        assert ce.store_convo_events([]) == 0
        assert not isolate_convo_file.exists()

    def test_writes_events_and_returns_count(self, isolate_convo_file):
        events = [{"a": 1}, {"b": 2}]
        count = ce.store_convo_events(events)
        assert count == 2
        assert isolate_convo_file.exists()

    def test_each_event_is_json_line(self, isolate_convo_file):
        events = [{"x": 1}, {"y": 2}]
        ce.store_convo_events(events)
        lines = [l for l in isolate_convo_file.read_text().splitlines() if l]
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"x": 1}
        assert json.loads(lines[1]) == {"y": 2}

    def test_appends_on_successive_calls(self, isolate_convo_file):
        ce.store_convo_events([{"a": 1}])
        ce.store_convo_events([{"b": 2}])
        lines = [l for l in isolate_convo_file.read_text().splitlines() if l]
        assert len(lines) == 2

    def test_creates_parent_dir(self, tmp_path, monkeypatch):
        deep_file = tmp_path / "a" / "b" / "events.jsonl"
        monkeypatch.setattr(ce, "CONVO_EVENTS_FILE", deep_file)
        ce.store_convo_events([{"z": 99}])
        assert deep_file.exists()


# ---------------------------------------------------------------------------
# read_pending_convo_events
# ---------------------------------------------------------------------------

class TestReadPendingConvoEvents:
    def test_returns_empty_when_no_file(self, isolate_convo_file):
        result = ce.read_pending_convo_events()
        assert result == []

    def test_reads_stored_events(self, isolate_convo_file):
        events = [{"a": i} for i in range(5)]
        ce.store_convo_events(events)
        result = ce.read_pending_convo_events()
        assert len(result) == 5

    def test_limit_respected(self, isolate_convo_file):
        events = [{"i": i} for i in range(20)]
        ce.store_convo_events(events)
        result = ce.read_pending_convo_events(limit=5)
        assert len(result) == 5

    def test_returns_last_n_events(self, isolate_convo_file):
        events = [{"i": i} for i in range(10)]
        ce.store_convo_events(events)
        result = ce.read_pending_convo_events(limit=3)
        vals = [r["i"] for r in result]
        assert vals == [7, 8, 9]

    def test_skips_blank_lines(self, isolate_convo_file):
        isolate_convo_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_convo_file.write_text('{"a":1}\n\n{"b":2}\n', encoding="utf-8")
        result = ce.read_pending_convo_events()
        assert len(result) == 2

    def test_returns_empty_on_corrupt_file(self, isolate_convo_file):
        isolate_convo_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_convo_file.write_text("not json at all\n", encoding="utf-8")
        result = ce.read_pending_convo_events()
        assert result == []
