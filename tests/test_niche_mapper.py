"""Tests for lib/niche_mapper.py — niche intelligence network."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

import pytest

import lib.niche_mapper as nm
from lib.niche_mapper import (
    NicheMapper,
    TrackedAccount,
    ConversationHub,
    EngagementOpportunity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mapper(monkeypatch, tmp_path: Path) -> NicheMapper:
    """Return a fresh NicheMapper with all paths redirected to tmp_path."""
    niche_dir = tmp_path / "niche_intel"
    monkeypatch.setattr(nm, "NICHE_DIR", niche_dir)
    monkeypatch.setattr(nm, "ACCOUNTS_FILE", niche_dir / "tracked_accounts.json")
    monkeypatch.setattr(nm, "HUBS_FILE", niche_dir / "hubs.json")
    monkeypatch.setattr(nm, "OPPORTUNITIES_FILE", niche_dir / "opportunities.json")
    # Disable XVoice integration
    monkeypatch.setattr(nm, "get_x_voice", lambda: None)
    return NicheMapper()


# ---------------------------------------------------------------------------
# TrackedAccount dataclass
# ---------------------------------------------------------------------------


def test_tracked_account_defaults():
    acc = TrackedAccount(handle="testuser")
    assert acc.handle == "testuser"
    assert acc.warmth == "cold"
    assert acc.relevance == 0.5
    assert acc.interaction_count == 0
    assert isinstance(acc.topics, list)


# ---------------------------------------------------------------------------
# NicheMapper.discover_account
# ---------------------------------------------------------------------------


def test_discover_new_account(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    acc = mapper.discover_account("Alice", topics=["ai", "startups"], relevance=0.8)
    assert acc.handle == "alice"
    assert "ai" in acc.topics
    assert acc.relevance == 0.8
    assert "alice" in mapper.accounts


def test_discover_strips_at_sign(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    acc = mapper.discover_account("@BobUser")
    assert acc.handle == "bobuser"


def test_discover_lowercases_handle(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    acc = mapper.discover_account("CAROL")
    assert acc.handle == "carol"


def test_discover_existing_merges_topics(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.discover_account("dave", topics=["ml"])
    mapper.discover_account("dave", topics=["nlp"])
    assert set(mapper.accounts["dave"].topics) == {"ml", "nlp"}


def test_discover_existing_keeps_higher_relevance(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.discover_account("eve", relevance=0.3)
    mapper.discover_account("eve", relevance=0.9)
    assert mapper.accounts["eve"].relevance == 0.9


def test_discover_persists_to_disk(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.discover_account("frank", topics=["startups"])
    data = json.loads((tmp_path / "niche_intel" / "tracked_accounts.json").read_text())
    assert "frank" in data


def test_discover_enforces_max_tracked(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.MAX_TRACKED = 3

    for i in range(4):
        mapper.discover_account(f"user{i}", relevance=0.5)

    assert len(mapper.accounts) <= 3


def test_discover_prunes_least_relevant(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.MAX_TRACKED = 2

    mapper.discover_account("lowrel", relevance=0.1)
    mapper.discover_account("highrel", relevance=0.9)
    mapper.discover_account("newuser", relevance=0.5)  # triggers prune

    assert "lowrel" not in mapper.accounts


def test_discover_via_stored(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.discover_account("gina", discovered_via="search")
    assert mapper.accounts["gina"].discovered_via == "search"


# ---------------------------------------------------------------------------
# NicheMapper.update_relationship
# ---------------------------------------------------------------------------


def test_update_relationship_increments_count(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.discover_account("henry")
    mapper.update_relationship("henry", "reply")
    assert mapper.accounts["henry"].interaction_count == 1


def test_update_relationship_we_initiated(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.discover_account("irene")
    mapper.update_relationship("irene", "reply", they_initiated=False)
    assert mapper.accounts["irene"].we_initiated_count == 1
    assert mapper.accounts["irene"].they_initiated_count == 0


def test_update_relationship_they_initiated(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.discover_account("jack")
    mapper.update_relationship("jack", "mention", they_initiated=True)
    assert mapper.accounts["jack"].they_initiated_count == 1


def test_update_relationship_auto_discovers(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    # handle not yet tracked
    mapper.update_relationship("newuser", "reply")
    assert "newuser" in mapper.accounts


def test_update_relationship_sets_last_interaction(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.discover_account("kate")
    mapper.update_relationship("kate", "like")
    assert mapper.accounts["kate"].last_interaction != ""


def test_update_relationship_returns_none_when_warmth_unchanged(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.discover_account("leo")
    # x_voice is None → warmth stays "cold"
    result = mapper.update_relationship("leo", "reply")
    assert result is None


# ---------------------------------------------------------------------------
# NicheMapper.get_account / get_accounts_by_warmth
# ---------------------------------------------------------------------------


def test_get_account_returns_correct(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.discover_account("maria")
    acc = mapper.get_account("maria")
    assert acc is not None
    assert acc.handle == "maria"


def test_get_account_missing_returns_none(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    assert mapper.get_account("nobody") is None


def test_get_accounts_by_warmth_filters(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    a1 = mapper.discover_account("w1")
    a1.warmth = "warm"
    a2 = mapper.discover_account("w2")
    a2.warmth = "cold"

    warm = mapper.get_accounts_by_warmth("warm")
    cold = mapper.get_accounts_by_warmth("cold")
    assert any(a.handle == "w1" for a in warm)
    assert all(a.warmth == "warm" for a in warm)
    assert any(a.handle == "w2" for a in cold)


# ---------------------------------------------------------------------------
# NicheMapper.identify_hub
# ---------------------------------------------------------------------------


def test_identify_new_hub(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    hub = mapper.identify_hub("topic", "AI tools", key_accounts=["alice"], engagement_level=7.0)
    assert hub.hub_type == "topic"
    assert hub.engagement_level == 7.0
    assert "alice" in hub.key_accounts


def test_identify_hub_id_derived_from_type_and_desc(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    hub = mapper.identify_hub("account", "sam altman")
    assert hub.hub_id.startswith("account_sam")


def test_identify_existing_hub_updates_engagement(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.identify_hub("topic", "AI tools", engagement_level=4.0)
    hub = mapper.identify_hub("topic", "AI tools", engagement_level=10.0)
    # EWMA: 4.0*0.7 + 10.0*0.3 = 5.8
    assert abs(hub.engagement_level - 5.8) < 0.01


def test_identify_existing_hub_merges_accounts(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.identify_hub("topic", "AI tools", key_accounts=["alice"])
    hub = mapper.identify_hub("topic", "AI tools", key_accounts=["bob"])
    assert "alice" in hub.key_accounts
    assert "bob" in hub.key_accounts


def test_identify_hub_increments_times_observed(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.identify_hub("topic", "startups")
    hub = mapper.identify_hub("topic", "startups")
    assert hub.times_observed == 2


def test_identify_hub_enforces_max_hubs(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.MAX_HUBS = 3
    for i in range(4):
        mapper.identify_hub("topic", f"topic {i}", engagement_level=float(i))
    assert len(mapper.hubs) <= 3


def test_get_active_hubs_filters_by_engagement(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.identify_hub("topic", "high", engagement_level=8.0)
    mapper.identify_hub("topic", "low", engagement_level=1.0)
    active = mapper.get_active_hubs(min_engagement=3.0)
    assert all(h.engagement_level >= 3.0 for h in active)


def test_get_active_hubs_sorted_by_engagement_desc(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.identify_hub("topic", "mid", engagement_level=5.0)
    mapper.identify_hub("topic", "top", engagement_level=9.0)
    active = mapper.get_active_hubs()
    assert active[0].engagement_level >= active[-1].engagement_level


# ---------------------------------------------------------------------------
# NicheMapper.generate_opportunity / get_active_opportunities / act_on_opportunity
# ---------------------------------------------------------------------------


def test_generate_opportunity_creates_entry(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    opp = mapper.generate_opportunity("nick", "interesting thread", urgency=4)
    assert opp.target == "nick"
    assert opp.urgency == 4
    assert not opp.acted_on


def test_generate_opportunity_strips_at(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    opp = mapper.generate_opportunity("@olivia", "hot tweet")
    assert opp.target == "olivia"


def test_generate_opportunity_urgency_clamped(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    opp_high = mapper.generate_opportunity("t1", "r", urgency=99)
    opp_low = mapper.generate_opportunity("t2", "r", urgency=-5)
    assert opp_high.urgency == 5
    assert opp_low.urgency == 1


def test_opportunity_expiry_set(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    before = time.time()
    opp = mapper.generate_opportunity("peter", "reason", expires_hours=2.0)
    after = time.time()
    assert before + 2 * 3600 <= opp.expires_at <= after + 2 * 3600


def test_opportunity_no_expiry_when_zero(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    opp = mapper.generate_opportunity("quinn", "reason", expires_hours=0)
    assert opp.expires_at == 0.0


def test_get_active_opportunities_excludes_acted(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.generate_opportunity("rose", "r")
    mapper.generate_opportunity("sam", "r")
    mapper.act_on_opportunity("rose")
    active = mapper.get_active_opportunities()
    assert all(o.target != "rose" for o in active)


def test_get_active_opportunities_excludes_expired(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    # Create with expires_at already in the past
    opp = mapper.generate_opportunity("tom", "reason")
    opp.expires_at = time.time() - 100  # already expired
    active = mapper.get_active_opportunities()
    assert all(o.target != "tom" for o in active)


def test_get_active_opportunities_min_urgency_filter(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.generate_opportunity("uma", "r", urgency=1)
    mapper.generate_opportunity("victor", "r", urgency=5)
    active = mapper.get_active_opportunities(min_urgency=3)
    assert all(o.urgency >= 3 for o in active)


def test_get_active_opportunities_sorted_by_urgency_desc(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.generate_opportunity("u1", "r", urgency=2)
    mapper.generate_opportunity("u2", "r", urgency=5)
    mapper.generate_opportunity("u3", "r", urgency=3)
    active = mapper.get_active_opportunities()
    urgencies = [o.urgency for o in active]
    assert urgencies == sorted(urgencies, reverse=True)


def test_act_on_opportunity_returns_true(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.generate_opportunity("wendy", "r")
    result = mapper.act_on_opportunity("wendy")
    assert result is True


def test_act_on_opportunity_returns_false_if_not_found(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    assert mapper.act_on_opportunity("nobody") is False


def test_act_on_opportunity_marks_acted_on(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.generate_opportunity("xena", "r")
    mapper.act_on_opportunity("xena")
    # Should no longer appear in active
    assert all(o.target != "xena" for o in mapper.get_active_opportunities())


def test_enforce_max_opportunities(monkeypatch, tmp_path):
    # _cleanup_opportunities runs before the append, so the list may be
    # MAX_OPPORTUNITIES + 1 immediately after a new entry is added.
    # What matters is that it doesn't grow unboundedly.
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.MAX_OPPORTUNITIES = 5
    for i in range(20):
        mapper.generate_opportunity(f"user{i}", "r")
    assert len(mapper.opportunities) <= mapper.MAX_OPPORTUNITIES + 1


# ---------------------------------------------------------------------------
# NicheMapper.get_network_stats
# ---------------------------------------------------------------------------


def test_get_network_stats_empty(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    stats = mapper.get_network_stats()
    assert stats["tracked_accounts"] == 0
    assert stats["reciprocity_rate"] == 0.0


def test_get_network_stats_counts(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.discover_account("a1")
    mapper.discover_account("a2")
    mapper.identify_hub("topic", "hub1", engagement_level=5.0)
    mapper.generate_opportunity("a1", "r")
    stats = mapper.get_network_stats()
    assert stats["tracked_accounts"] == 2
    assert stats["total_hubs"] == 1
    assert stats["total_opportunities"] == 1


def test_get_network_stats_warmth_distribution(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    a = mapper.discover_account("warm_user")
    a.warmth = "warm"
    b = mapper.discover_account("cold_user")
    b.warmth = "cold"
    stats = mapper.get_network_stats()
    assert stats["warmth_distribution"]["warm"] == 1
    assert stats["warmth_distribution"]["cold"] == 1


def test_calculate_reciprocity(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    a = mapper.discover_account("a")
    a.they_initiated_count = 3
    a.we_initiated_count = 1
    # reciprocity = 3 / (3+1) = 0.75
    rate = mapper._calculate_reciprocity()
    assert abs(rate - 0.75) < 0.01


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


def test_accounts_persist_and_reload(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.discover_account("yvonne", topics=["ai"])
    # Create a new mapper reading the same files
    mapper2 = NicheMapper()
    # It should have loaded from the files written by mapper
    # (files already in place via monkeypatched paths)
    assert "yvonne" in mapper2.accounts


def test_hubs_persist_and_reload(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.identify_hub("topic", "persistent hub", engagement_level=7.0)
    mapper2 = NicheMapper()
    hub_ids = list(mapper2.hubs.keys())
    assert any("persistent" in hid for hid in hub_ids)


def test_opportunities_persist_and_reload(monkeypatch, tmp_path):
    mapper = _make_mapper(monkeypatch, tmp_path)
    mapper.generate_opportunity("zara", "important target")
    mapper2 = NicheMapper()
    assert any(o.target == "zara" for o in mapper2.opportunities)


# ---------------------------------------------------------------------------
# get_niche_mapper singleton
# ---------------------------------------------------------------------------


def test_get_niche_mapper_returns_singleton(monkeypatch, tmp_path):
    niche_dir = tmp_path / "niche_intel"
    monkeypatch.setattr(nm, "NICHE_DIR", niche_dir)
    monkeypatch.setattr(nm, "ACCOUNTS_FILE", niche_dir / "tracked_accounts.json")
    monkeypatch.setattr(nm, "HUBS_FILE", niche_dir / "hubs.json")
    monkeypatch.setattr(nm, "OPPORTUNITIES_FILE", niche_dir / "opportunities.json")
    monkeypatch.setattr(nm, "get_x_voice", lambda: None)
    monkeypatch.setattr(nm, "_mapper", None)

    m1 = nm.get_niche_mapper()
    m2 = nm.get_niche_mapper()
    assert m1 is m2
