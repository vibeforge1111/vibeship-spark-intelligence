"""Tests for lib/tastebank.py — TasteBank JSONL storage and retrieval."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.tastebank as tb


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_taste_dir(tmp_path, monkeypatch):
    """Redirect TASTE_DIR to tmp_path so no real ~/.spark writes occur."""
    taste_dir = tmp_path / "taste"
    monkeypatch.setattr(tb, "TASTE_DIR", taste_dir)
    yield taste_dir


# ---------------------------------------------------------------------------
# _hash_id
# ---------------------------------------------------------------------------

class TestHashId:
    def test_deterministic(self):
        assert tb._hash_id("a", "b") == tb._hash_id("a", "b")

    def test_different_inputs_differ(self):
        assert tb._hash_id("x", "y") != tb._hash_id("p", "q")

    def test_length_12(self):
        assert len(tb._hash_id("hello", "world")) == 12

    def test_empty_parts(self):
        h = tb._hash_id("", "")
        assert len(h) == 12


# ---------------------------------------------------------------------------
# _file (domain resolution)
# ---------------------------------------------------------------------------

class TestFile:
    def test_valid_domain_social_posts(self, tmp_path):
        p = tb._file("social_posts")
        assert p.name == "social_posts.jsonl"

    def test_valid_domain_ui_design(self):
        p = tb._file("ui_design")
        assert p.name == "ui_design.jsonl"

    def test_valid_domain_art(self):
        p = tb._file("art")
        assert p.name == "art.jsonl"

    def test_invalid_domain_raises(self):
        with pytest.raises(ValueError, match="Unknown domain"):
            tb._file("music")

    def test_normalizes_case(self):
        p = tb._file("SOCIAL_POSTS")
        assert p.name == "social_posts.jsonl"

    def test_creates_taste_dir(self, tmp_path, monkeypatch):
        taste_dir = tmp_path / "new_taste"
        monkeypatch.setattr(tb, "TASTE_DIR", taste_dir)
        assert not taste_dir.exists()
        tb._file("art")
        assert taste_dir.exists()


# ---------------------------------------------------------------------------
# add_item
# ---------------------------------------------------------------------------

class TestAddItem:
    def test_adds_item_returns_taste_item(self):
        item = tb.add_item("art", "http://example.com/img.png", label="Cool Art")
        assert item.domain == "art"
        assert item.source == "http://example.com/img.png"
        assert item.label == "Cool Art"

    def test_item_written_to_jsonl(self, tmp_path, monkeypatch):
        taste_dir = tmp_path / "taste"
        monkeypatch.setattr(tb, "TASTE_DIR", taste_dir)
        tb.add_item("art", "http://example.com/1.png")
        p = taste_dir / "art.jsonl"
        assert p.exists()
        data = json.loads(p.read_text().strip().splitlines()[-1])
        assert data["domain"] == "art"

    def test_dedup_same_source(self):
        item1 = tb.add_item("art", "http://example.com/dup.png", label="First")
        item2 = tb.add_item("art", "http://example.com/dup.png", label="Second")
        assert item1.item_id == item2.item_id

    def test_different_sources_different_ids(self):
        item1 = tb.add_item("art", "http://a.com/1.png")
        item2 = tb.add_item("art", "http://a.com/2.png")
        assert item1.item_id != item2.item_id

    def test_label_auto_from_source(self):
        item = tb.add_item("art", "http://example.com/some-art.png")
        assert item.label  # should be truthy

    def test_label_strips_channel_prefix(self):
        item = tb.add_item("art", "src", label="[Telegram ch] Real Label")
        assert item.label == "Real Label"

    def test_label_strips_message_id(self):
        item = tb.add_item("art", "src", label="Some Art\n[message_id: abc123]")
        assert "message_id" not in item.label

    def test_invalid_domain_raises(self):
        with pytest.raises(ValueError, match="Unknown domain"):
            tb.add_item("music", "http://a.com/song.mp3")

    def test_tags_and_signals_stored(self):
        item = tb.add_item("art", "http://x.com/a.png", tags=["bold"], signals=["wow"])
        assert item.tags == ["bold"]
        assert item.signals == ["wow"]

    def test_scope_and_project_key(self):
        item = tb.add_item("ui_design", "http://x.com/", scope="project", project_key="proj1")
        assert item.scope == "project"
        assert item.project_key == "proj1"

    def test_to_dict_roundtrip(self):
        item = tb.add_item("social_posts", "http://x.com/post/1")
        d = item.to_dict()
        assert d["domain"] == "social_posts"
        assert d["item_id"] == item.item_id
        assert isinstance(d["tags"], list)


# ---------------------------------------------------------------------------
# recent
# ---------------------------------------------------------------------------

class TestRecent:
    def test_returns_empty_when_no_files(self):
        items = tb.recent()
        assert items == []

    def test_returns_items_sorted_newest_first(self):
        i1 = tb.add_item("art", "http://a.com/1.png")
        time.sleep(0.01)
        i2 = tb.add_item("art", "http://a.com/2.png")
        items = tb.recent(domain="art")
        ids = [it["item_id"] for it in items]
        assert ids.index(i2.item_id) < ids.index(i1.item_id)

    def test_limit_respected(self):
        for i in range(5):
            tb.add_item("art", f"http://a.com/{i}.png")
        items = tb.recent(domain="art", limit=3)
        assert len(items) <= 3

    def test_domain_filter(self):
        tb.add_item("art", "http://a.com/art.png")
        tb.add_item("ui_design", "http://a.com/ui.png")
        items = tb.recent(domain="art")
        assert all(it["domain"] == "art" for it in items)

    def test_all_domains_when_no_filter(self):
        tb.add_item("art", "http://a.com/art.png")
        tb.add_item("ui_design", "http://a.com/ui.png")
        items = tb.recent()
        domains = {it["domain"] for it in items}
        assert "art" in domains
        assert "ui_design" in domains

    def test_invalid_domain_raises_from_file(self):
        with pytest.raises(ValueError):
            tb.recent(domain="invalid")


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_all_domains_in_stats(self):
        s = tb.stats()
        assert "art" in s
        assert "social_posts" in s
        assert "ui_design" in s

    def test_counts_items(self):
        tb.add_item("art", "http://a.com/1.png")
        tb.add_item("art", "http://a.com/2.png")
        s = tb.stats()
        assert s["art"] == 2

    def test_zero_when_no_items(self):
        s = tb.stats()
        assert s["art"] == 0
        assert s["social_posts"] == 0


# ---------------------------------------------------------------------------
# retrieve
# ---------------------------------------------------------------------------

class TestRetrieve:
    def test_empty_query_returns_empty(self):
        tb.add_item("art", "http://x.com/a.png", label="cool art")
        assert tb.retrieve("art", "") == []

    def test_finds_matching_item_by_label(self):
        tb.add_item("art", "http://x.com/unique_xyz.png", label="unique_xyz label")
        results = tb.retrieve("art", "unique_xyz")
        assert len(results) >= 1

    def test_no_match_returns_empty(self):
        tb.add_item("art", "http://x.com/pic.png", label="normal label")
        results = tb.retrieve("art", "zzz_no_match_zzz")
        assert results == []

    def test_limit_respected(self):
        for i in range(10):
            tb.add_item("art", f"http://x.com/{i}.png", label=f"testword item {i}")
        results = tb.retrieve("art", "testword", limit=3)
        assert len(results) <= 3

    def test_searches_notes(self):
        tb.add_item("art", "http://x.com/p.png", label="plain", notes="special_keyword")
        results = tb.retrieve("art", "special_keyword")
        assert len(results) >= 1

    def test_searches_source(self):
        tb.add_item("art", "http://x.com/findthis_source.png", label="label")
        results = tb.retrieve("art", "findthis_source")
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# infer_domain
# ---------------------------------------------------------------------------

class TestInferDomain:
    def test_post_keyword(self):
        assert tb.infer_domain("I like this post") == "social_posts"

    def test_thread_keyword(self):
        assert tb.infer_domain("great thread here") == "social_posts"

    def test_tweet_keyword(self):
        assert tb.infer_domain("this tweet is viral") == "social_posts"

    def test_ui_keyword(self):
        assert tb.infer_domain("awesome ui design") == "ui_design"

    def test_website_keyword(self):
        assert tb.infer_domain("check this website") == "ui_design"

    def test_dashboard_keyword(self):
        assert tb.infer_domain("love this dashboard") == "ui_design"

    def test_art_keyword(self):
        assert tb.infer_domain("beautiful art piece") == "art"

    def test_poster_keyword(self):
        # NOTE: "poster" contains "post" so the social_posts branch fires first
        # This is a known ordering quirk in the source's if/elif chain.
        assert tb.infer_domain("cool poster") == "social_posts"

    def test_illustration_keyword(self):
        assert tb.infer_domain("awesome illustration") == "art"

    def test_render_keyword(self):
        assert tb.infer_domain("3D render") == "art"

    def test_graphics_keyword(self):
        assert tb.infer_domain("cool graphics") == "art"

    def test_unknown_returns_none(self):
        assert tb.infer_domain("just some random text") is None

    def test_empty_returns_none(self):
        assert tb.infer_domain("") is None


# ---------------------------------------------------------------------------
# parse_like_message
# ---------------------------------------------------------------------------

class TestParseLikeMessage:
    def test_i_like_post_with_url(self):
        result = tb.parse_like_message("I like this post: http://x.com/post/123")
        assert result is not None
        assert result["domain"] == "social_posts"
        assert result["source"] == "http://x.com/post/123"

    def test_i_like_ui_with_url(self):
        result = tb.parse_like_message("I like this UI: http://example.com/ui")
        assert result is not None
        assert result["domain"] == "ui_design"

    def test_i_like_art_with_url(self):
        result = tb.parse_like_message("I like this art: http://example.com/art.png")
        assert result is not None
        assert result["domain"] == "art"

    def test_i_love_triggers_match(self):
        result = tb.parse_like_message("I love this post: http://x.com/p/1")
        assert result is not None

    def test_no_i_like_returns_none(self):
        result = tb.parse_like_message("Check this out: http://x.com/p/1")
        assert result is None

    def test_notes_from_because_clause(self):
        result = tb.parse_like_message("I like this art: http://x.com/a.png because it's bold")
        assert result is not None
        assert "bold" in result["notes"]

    def test_no_url_falls_back_to_text(self):
        result = tb.parse_like_message("I like this post: cool text content here")
        assert result is not None
        assert result["source"] == "cool text content here"

    def test_strips_channel_prefix(self):
        result = tb.parse_like_message("[Telegram ch] I like this art: http://x.com/img.png")
        assert result is not None

    def test_no_domain_returns_none(self):
        result = tb.parse_like_message("I like this thing without a domain")
        assert result is None

    def test_empty_message_returns_none(self):
        result = tb.parse_like_message("")
        assert result is None

    def test_graphic_keyword(self):
        result = tb.parse_like_message("I like this graphic: http://x.com/g.png")
        assert result is not None
        assert result["domain"] == "art"
