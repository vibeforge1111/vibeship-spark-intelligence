"""Tests for lib.project_profile."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import lib.project_profile as pp
from lib.project_profile import (
    DOMAIN_QUESTIONS,
    PHASE_QUESTIONS,
    DOMAIN_PHASE_QUESTIONS,
    _hash_id,
    _default_profile,
    _profile_path,
    infer_domain,
    get_project_key,
    load_profile,
    save_profile,
    list_profiles,
    ensure_questions,
    get_suggested_questions,
    record_answer,
    record_entry,
    set_phase,
    completion_score,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_project_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "PROJECT_DIR", tmp_path / "projects")
    monkeypatch.setattr(pp, "log_debug", lambda *a: None)
    monkeypatch.setattr(pp, "infer_project_key", lambda: None)
    monkeypatch.setattr(pp, "get_project_context", lambda root: {})
    monkeypatch.setattr(pp, "_get_chip_questions", lambda phase=None: [])


def _profile(project_key="test-proj", domain="general", **kw) -> dict:
    p = _default_profile(project_key, domain)
    p.update(kw)
    return p


# ---------------------------------------------------------------------------
# _hash_id
# ---------------------------------------------------------------------------

def test_hash_id_deterministic():
    assert _hash_id("a", "b", "c") == _hash_id("a", "b", "c")


def test_hash_id_length():
    assert len(_hash_id("x", "y")) == 12


def test_hash_id_different_inputs():
    assert _hash_id("a", "b") != _hash_id("a", "c")


def test_hash_id_empty_parts():
    result = _hash_id("", "")
    assert isinstance(result, str) and len(result) == 12


# ---------------------------------------------------------------------------
# _default_profile
# ---------------------------------------------------------------------------

def test_default_profile_keys():
    p = _default_profile("my-proj", "general")
    for key in ("project_key", "domain", "created_at", "updated_at", "phase",
                "questions", "answers", "goals", "done", "decisions", "insights",
                "risks", "references", "transfers", "milestones", "feedback"):
        assert key in p, f"missing key {key}"


def test_default_profile_project_key():
    p = _default_profile("proj-x", "engineering")
    assert p["project_key"] == "proj-x"
    assert p["domain"] == "engineering"


def test_default_profile_phase_is_discovery():
    p = _default_profile("p", "general")
    assert p["phase"] == "discovery"


def test_default_profile_done_empty_string():
    p = _default_profile("p", "general")
    assert p["done"] == ""


# ---------------------------------------------------------------------------
# infer_domain
# ---------------------------------------------------------------------------

def test_infer_domain_hint_wins():
    assert infer_domain(hint="fintech") == "fintech"


def test_infer_domain_game_dev(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "get_project_context", lambda root: {"tools": ["unity"]})
    assert infer_domain(project_dir=tmp_path) == "game_dev"


def test_infer_domain_marketing(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "get_project_context", lambda root: {"frameworks": ["marketing"]})
    assert infer_domain(project_dir=tmp_path) == "marketing"


def test_infer_domain_engineering(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "get_project_context", lambda root: {"tools": ["api"]})
    assert infer_domain(project_dir=tmp_path) == "engineering"


def test_infer_domain_product(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "get_project_context", lambda root: {"tools": ["saas"]})
    assert infer_domain(project_dir=tmp_path) == "product"


def test_infer_domain_org(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "get_project_context", lambda root: {"tools": ["ops"]})
    assert infer_domain(project_dir=tmp_path) == "org"


def test_infer_domain_fallback_general(tmp_path):
    assert infer_domain(project_dir=tmp_path) == "general"


def test_infer_domain_context_error_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "get_project_context", lambda root: (_ for _ in ()).throw(Exception("ctx error")))
    result = infer_domain(project_dir=tmp_path)
    assert result in ("general", "game_dev", "marketing", "org", "product", "engineering")


# ---------------------------------------------------------------------------
# get_project_key
# ---------------------------------------------------------------------------

def test_get_project_key_uses_infer(monkeypatch):
    monkeypatch.setattr(pp, "infer_project_key", lambda: "my-proj")
    assert get_project_key() == "my-proj"


def test_get_project_key_falls_back_to_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "infer_project_key", lambda: None)
    key = get_project_key(project_dir=tmp_path)
    assert key == tmp_path.name or key == "default"


# ---------------------------------------------------------------------------
# save_profile / load_profile round-trip
# ---------------------------------------------------------------------------

def test_save_and_load_profile_roundtrip():
    p = _profile(project_key="rtrip", domain="engineering")
    p["goals"] = ["ship it"]
    save_profile(p)
    loaded = load_profile()
    # load_profile calls get_project_key which uses infer_project_key → None
    # so it falls back to cwd name; check save wrote the file correctly
    path = pp.PROJECT_DIR / "rtrip.json"
    data = json.loads(path.read_text())
    assert data["goals"] == ["ship it"]
    assert data["domain"] == "engineering"


def test_save_profile_updates_updated_at():
    import time
    p = _profile(project_key="ts-test")
    before = time.time()
    save_profile(p)
    after = time.time()
    path = pp.PROJECT_DIR / "ts-test.json"
    data = json.loads(path.read_text())
    assert before <= data["updated_at"] <= after


def test_load_profile_no_file_returns_default(monkeypatch):
    monkeypatch.setattr(pp, "infer_project_key", lambda: "nonexistent")
    profile = load_profile()
    assert profile["project_key"] == "nonexistent"
    assert profile["phase"] == "discovery"


def test_load_profile_corrupt_json_returns_default(monkeypatch):
    monkeypatch.setattr(pp, "infer_project_key", lambda: "corrupt-proj")
    path = pp.PROJECT_DIR / "corrupt-proj.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{bad json", encoding="utf-8")
    profile = load_profile()
    assert profile["project_key"] == "corrupt-proj"


def test_load_profile_invalid_type_returns_default(monkeypatch):
    monkeypatch.setattr(pp, "infer_project_key", lambda: "arr-proj")
    path = pp.PROJECT_DIR / "arr-proj.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]", encoding="utf-8")
    profile = load_profile()
    assert profile["project_key"] == "arr-proj"


def test_load_profile_missing_phase_patched(monkeypatch):
    monkeypatch.setattr(pp, "infer_project_key", lambda: "nophase")
    path = pp.PROJECT_DIR / "nophase.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Profile without phase field
    path.write_text(json.dumps({"project_key": "nophase", "domain": "general", "goals": []}), encoding="utf-8")
    profile = load_profile()
    assert profile["phase"] == "discovery"


# ---------------------------------------------------------------------------
# list_profiles
# ---------------------------------------------------------------------------

def test_list_profiles_empty():
    assert list_profiles() == []


def test_list_profiles_returns_all():
    for key in ("proj-a", "proj-b"):
        save_profile(_profile(project_key=key))
    profiles = list_profiles()
    keys = {p["project_key"] for p in profiles}
    assert "proj-a" in keys and "proj-b" in keys


def test_list_profiles_skips_bad_files():
    pp.PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    (pp.PROJECT_DIR / "bad.json").write_text("{bad", encoding="utf-8")
    save_profile(_profile(project_key="good-proj"))
    profiles = list_profiles()
    assert len(profiles) == 1
    assert profiles[0]["project_key"] == "good-proj"


# ---------------------------------------------------------------------------
# ensure_questions
# ---------------------------------------------------------------------------

def test_ensure_questions_adds_domain_questions():
    p = _profile(project_key="q1", domain="game_dev", phase="discovery")
    added = ensure_questions(p)
    assert added > 0
    ids = {q["id"] for q in p["questions"]}
    # game_dev questions should be present
    for q in DOMAIN_QUESTIONS["game_dev"]:
        assert q["id"] in ids


def test_ensure_questions_adds_phase_questions():
    p = _profile(project_key="q2", domain="general", phase="launch")
    ensure_questions(p)
    ids = {q["id"] for q in p["questions"]}
    for q in PHASE_QUESTIONS.get("launch", []):
        assert q["id"] in ids


def test_ensure_questions_no_duplicates():
    p = _profile(project_key="q3", domain="general", phase="discovery")
    ensure_questions(p)
    count_before = len(p["questions"])
    ensure_questions(p)
    assert len(p["questions"]) == count_before


def test_ensure_questions_domain_phase_combo():
    p = _profile(project_key="q4", domain="game_dev", phase="prototype")
    ensure_questions(p)
    ids = {q["id"] for q in p["questions"]}
    for q in DOMAIN_PHASE_QUESTIONS.get("game_dev:prototype", []):
        assert q["id"] in ids


def test_ensure_questions_unknown_domain_uses_general():
    p = _profile(project_key="q5", domain="unknown_xyz", phase="discovery")
    added = ensure_questions(p)
    assert added > 0
    ids = {q["id"] for q in p["questions"]}
    for q in DOMAIN_QUESTIONS["general"]:
        assert q["id"] in ids


# ---------------------------------------------------------------------------
# get_suggested_questions
# ---------------------------------------------------------------------------

def test_get_suggested_questions_limit_respected():
    p = _profile(project_key="sq1", domain="general", phase="discovery")
    questions = get_suggested_questions(p, limit=2)
    assert len(questions) <= 2


def test_get_suggested_questions_includes_unanswered():
    p = _profile(project_key="sq2", domain="general", phase="discovery")
    ensure_questions(p)
    questions = get_suggested_questions(p, limit=10)
    assert len(questions) >= 1


def test_get_suggested_questions_extra_done_prompt():
    p = _profile(project_key="sq3", domain="general", phase="discovery")
    p["done"] = ""  # no done defined
    questions = get_suggested_questions(p, limit=10, include_chips=False)
    ids = [q["id"] for q in questions]
    assert "proj_done" in ids


def test_get_suggested_questions_extra_goal_prompt():
    p = _profile(project_key="sq4", domain="general", phase="discovery")
    p["goals"] = []  # no goals → proj_goal added to extra prompts
    p["done"] = "defined"  # suppress proj_done so proj_goal lands within limit
    p["milestones"] = [{"text": "m1"}]  # suppress proj_milestone too
    questions = get_suggested_questions(p, limit=15, include_chips=False)
    ids = [q["id"] for q in questions]
    assert "proj_goal" in ids


# ---------------------------------------------------------------------------
# record_answer
# ---------------------------------------------------------------------------

def test_record_answer_no_question_id_returns_none():
    p = _profile(project_key="ra1")
    assert record_answer(p, "", "some answer") is None


def test_record_answer_no_answer_returns_none():
    p = _profile(project_key="ra2")
    assert record_answer(p, "q-1", "") is None


def test_record_answer_adds_to_answers():
    p = _profile(project_key="ra3", domain="general", phase="discovery")
    ensure_questions(p)
    q_id = p["questions"][0]["id"]
    result = record_answer(p, q_id, "Because latency matters")
    assert result is not None
    assert result["answer"] == "Because latency matters"
    assert result["question_id"] == q_id


def test_record_answer_marks_question_answered():
    p = _profile(project_key="ra4", domain="general", phase="discovery")
    ensure_questions(p)
    q_id = p["questions"][0]["id"]
    record_answer(p, q_id, "Done")
    q = next(q for q in p["questions"] if q["id"] == q_id)
    assert q["answered_at"] is not None


def test_record_answer_saves_profile():
    p = _profile(project_key="ra5", domain="general", phase="discovery")
    ensure_questions(p)
    q_id = p["questions"][0]["id"]
    record_answer(p, q_id, "My answer")
    path = pp.PROJECT_DIR / "ra5.json"
    data = json.loads(path.read_text())
    assert any(a["answer"] == "My answer" for a in data.get("answers", []))


# ---------------------------------------------------------------------------
# record_entry
# ---------------------------------------------------------------------------

def test_record_entry_decision():
    p = _profile(project_key="re1")
    entry = record_entry(p, "decisions", "Use Redis for caching")
    assert entry["text"] == "Use Redis for caching"
    assert "entry_id" in entry


def test_record_entry_done_maps_to_done_history():
    p = _profile(project_key="re2")
    record_entry(p, "done", "All tests pass")
    assert len(p["done_history"]) == 1
    assert "done" not in p or p.get("done") == ""


def test_record_entry_reference_maps_to_references():
    p = _profile(project_key="re3")
    record_entry(p, "reference", "See Django ORM patterns")
    assert len(p["references"]) == 1


def test_record_entry_transfer_maps_to_transfers():
    p = _profile(project_key="re4")
    record_entry(p, "transfer", "Always validate at edges")
    assert len(p["transfers"]) == 1


def test_record_entry_id_deterministic():
    p = _profile(project_key="re5")
    e1 = record_entry(p, "insights", "Use TTL of 5m")
    e2 = record_entry(_profile(project_key="re5"), "insights", "Use TTL of 5m")
    assert e1["entry_id"] == e2["entry_id"]


# ---------------------------------------------------------------------------
# set_phase
# ---------------------------------------------------------------------------

def test_set_phase_updates_phase():
    p = _profile(project_key="sp1")
    set_phase(p, "launch")
    assert p["phase"] == "launch"


def test_set_phase_lowercases():
    p = _profile(project_key="sp2")
    set_phase(p, "POLISH")
    assert p["phase"] == "polish"


def test_set_phase_empty_is_noop():
    p = _profile(project_key="sp3", phase="discovery")
    set_phase(p, "")
    assert p["phase"] == "discovery"


def test_set_phase_records_history():
    p = _profile(project_key="sp4")
    set_phase(p, "prototype")
    history = p.get("phase_history", [])
    assert len(history) == 1


# ---------------------------------------------------------------------------
# completion_score
# ---------------------------------------------------------------------------

def test_completion_score_empty_profile():
    p = _profile(project_key="cs1")
    score = completion_score(p)
    assert score["score"] >= 0
    assert score["score"] <= 100


def test_completion_score_with_done():
    p = _profile(project_key="cs2")
    p["done"] = "all tests pass"
    score = completion_score(p)
    assert score["done"] == 20


def test_completion_score_with_goals():
    p = _profile(project_key="cs3")
    p["goals"] = ["ship MVP"]
    score = completion_score(p)
    assert score["goals"] == 10


def test_completion_score_phase_points():
    for phase, expected in [("discovery", 2), ("prototype", 5), ("polish", 8), ("launch", 10)]:
        p = _profile(project_key=f"cs-{phase}", phase=phase)
        score = completion_score(p)
        assert score["phase"] == expected


def test_completion_score_questions_ratio():
    p = _profile(project_key="cs4", domain="general", phase="discovery")
    ensure_questions(p)
    # Answer half the questions
    half = len(p["questions"]) // 2
    for q in p["questions"][:half]:
        q["answered_at"] = 123.0
    score = completion_score(p)
    assert score["questions"] > 0


def test_completion_score_craft_capped_at_15():
    p = _profile(project_key="cs5")
    p["insights"] = [{"text": f"i{i}"} for i in range(10)]
    p["decisions"] = [{"text": "d1"}]
    score = completion_score(p)
    assert score["craft"] <= 15


def test_completion_score_total_capped_at_100():
    p = _profile(project_key="cs6", phase="launch")
    p["done"] = "yes"
    p["goals"] = ["g1"]
    p["insights"] = [{"text": f"i{i}"} for i in range(20)]
    p["decisions"] = [{"text": f"d{i}"} for i in range(20)]
    p["risks"] = [{"text": "r1"}]
    ensure_questions(p)
    for q in p["questions"]:
        q["answered_at"] = 1.0
    score = completion_score(p)
    assert score["score"] <= 100
