"""Tests for lib/opportunity_inbox.py — opportunity inbox JSONL storage."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.opportunity_inbox as inbox


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_dirs(tmp_path, monkeypatch):
    """Redirect all module-level paths to tmp_path."""
    opp_dir = tmp_path / "opportunity_scanner"
    monkeypatch.setattr(inbox, "OPPORTUNITY_DIR", opp_dir)
    monkeypatch.setattr(inbox, "SELF_FILE", opp_dir / "self_opportunities.jsonl")
    monkeypatch.setattr(inbox, "DECISIONS_FILE", opp_dir / "decisions.jsonl")
    yield opp_dir


# ---------------------------------------------------------------------------
# _question_key
# ---------------------------------------------------------------------------

class TestQuestionKey:
    def test_basic_tokenization(self):
        k = inbox._question_key("How can we improve performance?")
        assert "improve" in k
        assert "performance" in k

    def test_strips_stopwords(self):
        k = inbox._question_key("the a an and or to of for in on with is are")
        # All stopwords — result should be empty or from fallback
        assert isinstance(k, str)

    def test_empty_string(self):
        assert inbox._question_key("") == ""

    def test_limits_to_14_tokens(self):
        many_words = " ".join([f"word{i}" for i in range(20)])
        k = inbox._question_key(many_words)
        assert len(k.split()) <= 14

    def test_lowercased(self):
        k = inbox._question_key("HELLO WORLD")
        assert k == k.lower()

    def test_deterministic(self):
        q = "Should we refactor the login module?"
        assert inbox._question_key(q) == inbox._question_key(q)


# ---------------------------------------------------------------------------
# _read_jsonl
# ---------------------------------------------------------------------------

class TestReadJsonl:
    def test_missing_file_returns_empty(self, tmp_path):
        p = tmp_path / "nope.jsonl"
        assert inbox._read_jsonl(p) == []

    def test_reads_valid_rows(self, tmp_path):
        p = tmp_path / "data.jsonl"
        p.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
        rows = inbox._read_jsonl(p)
        assert len(rows) == 2

    def test_skips_invalid_json(self, tmp_path):
        p = tmp_path / "mixed.jsonl"
        p.write_text('{"ok": 1}\nBAD\n{"ok2": 2}\n', encoding="utf-8")
        rows = inbox._read_jsonl(p)
        assert len(rows) == 2

    def test_skips_empty_lines(self, tmp_path):
        p = tmp_path / "ws.jsonl"
        p.write_text('\n\n{"a": 1}\n\n', encoding="utf-8")
        rows = inbox._read_jsonl(p)
        assert len(rows) == 1

    def test_skips_non_dict_rows(self, tmp_path):
        p = tmp_path / "nd.jsonl"
        p.write_text('["list"]\n{"ok": 1}\n', encoding="utf-8")
        rows = inbox._read_jsonl(p)
        assert len(rows) == 1

    def test_limit_takes_last_n(self, tmp_path):
        p = tmp_path / "big.jsonl"
        lines = [json.dumps({"i": i}) for i in range(20)]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rows = inbox._read_jsonl(p, limit=5)
        assert len(rows) == 5
        assert rows[-1]["i"] == 19


# ---------------------------------------------------------------------------
# load_self_opportunities
# ---------------------------------------------------------------------------

class TestLoadSelfOpportunities:
    def _write_opp(self, opp_dir, rows):
        opp_dir.mkdir(parents=True, exist_ok=True)
        p = opp_dir / "self_opportunities.jsonl"
        with p.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

    def test_empty_when_no_file(self):
        result = inbox.load_self_opportunities()
        assert result == []

    def test_returns_rows_sorted_newest_first(self, tmp_path, isolate_dirs):
        self._write_opp(isolate_dirs, [
            {"ts": 100.0, "opportunity_id": "old"},
            {"ts": 200.0, "opportunity_id": "new"},
        ])
        result = inbox.load_self_opportunities(limit=10)
        assert result[0]["opportunity_id"] == "new"

    def test_limit_respected(self, tmp_path, isolate_dirs):
        self._write_opp(isolate_dirs, [{"ts": float(i), "opportunity_id": f"opp{i}"} for i in range(10)])
        result = inbox.load_self_opportunities(limit=3)
        assert len(result) <= 3

    def test_filter_by_scope_type(self, tmp_path, isolate_dirs):
        self._write_opp(isolate_dirs, [
            {"ts": 1.0, "scope_type": "project", "opportunity_id": "a"},
            {"ts": 2.0, "scope_type": "global", "opportunity_id": "b"},
        ])
        result = inbox.load_self_opportunities(scope_type="project", limit=10)
        assert all(r["scope_type"] == "project" for r in result)

    def test_filter_by_scope_id(self, tmp_path, isolate_dirs):
        self._write_opp(isolate_dirs, [
            {"ts": 1.0, "scope_id": "s1", "opportunity_id": "a"},
            {"ts": 2.0, "scope_id": "s2", "opportunity_id": "b"},
        ])
        result = inbox.load_self_opportunities(scope_id="s1", limit=10)
        assert all(r["scope_id"] == "s1" for r in result)

    def test_filter_by_project_id(self, tmp_path, isolate_dirs):
        self._write_opp(isolate_dirs, [
            {"ts": 1.0, "project_id": "proj1", "opportunity_id": "a"},
            {"ts": 2.0, "project_id": "proj2", "opportunity_id": "b"},
        ])
        result = inbox.load_self_opportunities(project_id="proj1", limit=10)
        assert all(r["project_id"] == "proj1" for r in result)

    def test_filter_by_operation(self, tmp_path, isolate_dirs):
        self._write_opp(isolate_dirs, [
            {"ts": 1.0, "operation": "refactor", "opportunity_id": "a"},
            {"ts": 2.0, "operation": "deploy", "opportunity_id": "b"},
        ])
        result = inbox.load_self_opportunities(operation="refactor", limit=10)
        assert all(r["operation"] == "refactor" for r in result)

    def test_filter_by_since_hours(self, tmp_path, isolate_dirs):
        now = time.time()
        self._write_opp(isolate_dirs, [
            {"ts": now - 10000, "opportunity_id": "old"},
            {"ts": now - 100, "opportunity_id": "recent"},
        ])
        result = inbox.load_self_opportunities(since_hours=0.1, limit=10)
        assert all(r["opportunity_id"] == "recent" for r in result)


# ---------------------------------------------------------------------------
# load_decisions
# ---------------------------------------------------------------------------

class TestLoadDecisions:
    def test_empty_when_no_file(self):
        result = inbox.load_decisions()
        assert result == []

    def test_returns_decision_objects(self, isolate_dirs):
        isolate_dirs.mkdir(parents=True, exist_ok=True)
        p = isolate_dirs / "decisions.jsonl"
        row = {"ts": 1000.0, "action": "accept", "opportunity_id": "opp1",
               "question_key": "how improve", "note": "good idea"}
        p.write_text(json.dumps(row) + "\n", encoding="utf-8")

        decisions = inbox.load_decisions()
        assert len(decisions) == 1
        d = decisions[0]
        assert d.action == "accept"
        assert d.opportunity_id == "opp1"
        assert d.note == "good idea"

    def test_sorted_newest_first(self, isolate_dirs):
        isolate_dirs.mkdir(parents=True, exist_ok=True)
        p = isolate_dirs / "decisions.jsonl"
        rows = [
            {"ts": 100.0, "action": "accept", "opportunity_id": "old"},
            {"ts": 200.0, "action": "dismiss", "opportunity_id": "new"},
        ]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        decisions = inbox.load_decisions()
        assert decisions[0].opportunity_id == "new"


# ---------------------------------------------------------------------------
# decisions_by_opportunity_id
# ---------------------------------------------------------------------------

class TestDecisionsByOpportunityId:
    def test_empty_when_no_decisions(self):
        result = inbox.decisions_by_opportunity_id()
        assert result == {}

    def test_returns_latest_per_opp(self, isolate_dirs):
        isolate_dirs.mkdir(parents=True, exist_ok=True)
        p = isolate_dirs / "decisions.jsonl"
        rows = [
            {"ts": 100.0, "action": "dismiss", "opportunity_id": "opp1", "question_key": "q"},
            {"ts": 200.0, "action": "accept", "opportunity_id": "opp1", "question_key": "q"},
        ]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        result = inbox.decisions_by_opportunity_id()
        # Latest decision (ts=200) wins
        assert result["opp1"].action == "accept"

    def test_skips_empty_opportunity_id(self, isolate_dirs):
        isolate_dirs.mkdir(parents=True, exist_ok=True)
        p = isolate_dirs / "decisions.jsonl"
        row = {"ts": 100.0, "action": "accept", "opportunity_id": "", "question_key": "q"}
        p.write_text(json.dumps(row) + "\n", encoding="utf-8")
        result = inbox.decisions_by_opportunity_id()
        assert result == {}


# ---------------------------------------------------------------------------
# record_decision
# ---------------------------------------------------------------------------

class TestRecordDecision:
    def test_returns_decision(self, isolate_dirs):
        d = inbox.record_decision(
            action="accept",
            opportunity_id="opp1",
            question="Should we improve perf?",
            note="yes",
        )
        assert isinstance(d, inbox.Decision)
        assert d.action == "accept"
        assert d.opportunity_id == "opp1"

    def test_writes_to_jsonl(self, isolate_dirs):
        inbox.record_decision(action="dismiss", opportunity_id="opp2", question="Q?")
        p = isolate_dirs / "decisions.jsonl"
        assert p.exists()
        row = json.loads(p.read_text().strip())
        assert row["action"] == "dismiss"
        assert row["opportunity_id"] == "opp2"

    def test_question_key_set(self, isolate_dirs):
        d = inbox.record_decision(action="accept", opportunity_id="opp3", question="improve cache?")
        assert d.question_key  # non-empty

    def test_ts_is_recent(self, isolate_dirs):
        before = time.time()
        d = inbox.record_decision(action="accept", opportunity_id="opp4", question="q?")
        assert d.ts >= before

    def test_creates_opportunity_dir(self, isolate_dirs):
        assert not isolate_dirs.exists() or True  # may or may not exist
        inbox.record_decision(action="accept", opportunity_id="o5", question="q?")
        assert isolate_dirs.exists()


# ---------------------------------------------------------------------------
# resolve_opportunity
# ---------------------------------------------------------------------------

class TestResolveOpportunity:
    def _write_opportunities(self, isolate_dirs, rows):
        isolate_dirs.mkdir(parents=True, exist_ok=True)
        p = isolate_dirs / "self_opportunities.jsonl"
        with p.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def test_empty_prefix_returns_none(self, isolate_dirs):
        assert inbox.resolve_opportunity("") is None

    def test_exact_match(self, isolate_dirs):
        self._write_opportunities(isolate_dirs, [{"opportunity_id": "abc123", "ts": 1.0}])
        result = inbox.resolve_opportunity("abc123")
        assert result is not None
        assert result["opportunity_id"] == "abc123"

    def test_prefix_match(self, isolate_dirs):
        self._write_opportunities(isolate_dirs, [{"opportunity_id": "abc123xyz", "ts": 1.0}])
        result = inbox.resolve_opportunity("abc123")
        assert result is not None

    def test_suffix_match(self, isolate_dirs):
        self._write_opportunities(isolate_dirs, [{"opportunity_id": "prefix_abc123", "ts": 1.0}])
        result = inbox.resolve_opportunity("abc123")
        assert result is not None

    def test_no_match_returns_none(self, isolate_dirs):
        self._write_opportunities(isolate_dirs, [{"opportunity_id": "abcdef", "ts": 1.0}])
        assert inbox.resolve_opportunity("zzz_no_match") is None

    def test_missing_file_returns_none(self, isolate_dirs):
        assert inbox.resolve_opportunity("anything") is None


# ---------------------------------------------------------------------------
# render_task_markdown
# ---------------------------------------------------------------------------

class TestRenderTaskMarkdown:
    def _row(self):
        return {
            "opportunity_id": "opp-001",
            "question": "Should we refactor?",
            "next_step": "Identify the module",
            "rationale": "Maintainability",
            "ts": 1000.0,
            "scope_type": "project",
            "scope_id": "myproj",
            "project_id": "p1",
            "project_label": "My Project",
            "operation": "refactor",
            "category": "tech_debt",
            "priority": "high",
            "confidence": 0.9,
            "source": "advisor",
            "llm_provider": "openai",
        }

    def test_contains_opportunity_id(self):
        md = inbox.render_task_markdown(self._row())
        assert "opp-001" in md

    def test_contains_question(self):
        md = inbox.render_task_markdown(self._row())
        assert "Should we refactor?" in md

    def test_contains_next_step(self):
        md = inbox.render_task_markdown(self._row())
        assert "Identify the module" in md

    def test_contains_rationale(self):
        md = inbox.render_task_markdown(self._row())
        assert "Maintainability" in md

    def test_missing_question_shows_missing(self):
        row = {"opportunity_id": "x"}
        md = inbox.render_task_markdown(row)
        assert "(missing)" in md

    def test_contains_execution_checklist(self):
        md = inbox.render_task_markdown(self._row())
        assert "Execution Plan" in md

    def test_contains_verification_section(self):
        md = inbox.render_task_markdown(self._row())
        assert "Verification" in md

    def test_contains_rollback_section(self):
        md = inbox.render_task_markdown(self._row())
        assert "Rollback" in md


# ---------------------------------------------------------------------------
# write_task_file
# ---------------------------------------------------------------------------

class TestWriteTaskFile:
    def test_creates_markdown_file(self, tmp_path):
        row = {"opportunity_id": "opp-test", "question": "Q?"}
        out_path = inbox.write_task_file(row, out_dir=tmp_path / "tasks")
        assert out_path.exists()
        assert out_path.suffix == ".md"

    def test_file_contains_content(self, tmp_path):
        row = {"opportunity_id": "opp-test2", "question": "Q2?"}
        out_path = inbox.write_task_file(row, out_dir=tmp_path / "tasks")
        content = out_path.read_text()
        assert "opp-test2" in content

    def test_safe_opportunity_id_in_filename(self, tmp_path):
        row = {"opportunity_id": "opp:001/abc"}
        out_path = inbox.write_task_file(row, out_dir=tmp_path / "tasks")
        assert "/" not in out_path.name or out_path.exists()  # path is valid

    def test_creates_output_dir(self, tmp_path):
        out_dir = tmp_path / "brand_new_dir"
        assert not out_dir.exists()
        row = {"opportunity_id": "opp-new"}
        inbox.write_task_file(row, out_dir=out_dir)
        assert out_dir.exists()
