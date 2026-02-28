from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import lib.memory_capture as memory_capture
from lib.cognitive_learner import CognitiveCategory
from lib.promoter import Promoter
from lib.queue import EventType


@dataclass
class _FakeInsight:
    insight: str
    category: CognitiveCategory
    reliability: float
    times_validated: int
    times_contradicted: int
    promoted: bool = False
    promoted_to: str | None = None
    confidence: float = 0.99
    created_at: str = ""
    context: str = "test"


class _FakeCognitive:
    def __init__(self, insights_map: dict[str, _FakeInsight]):
        self.insights = insights_map

    def get_ranked_insights(self, **_kwargs):
        return list(self.insights.values())

    def effective_reliability(self, insight: _FakeInsight) -> float:
        return float(insight.reliability)

    def is_noise_insight(self, _text: str) -> bool:
        return False

    def mark_unpromoted(self, key: str):
        if key in self.insights:
            self.insights[key].promoted = False
            self.insights[key].promoted_to = None

    def mark_promoted(self, key: str, promoted_to: str):
        if key in self.insights:
            self.insights[key].promoted = True
            self.insights[key].promoted_to = promoted_to


def test_memory_capture_skips_user_question_prompts(monkeypatch, spark_home):
    calls: list[str] = []

    def _fake_commit(
        text: str,
        category: CognitiveCategory,
        context: str = "",
        session_id: str = "",
        trace_id: str | None = None,
    ) -> bool:
        calls.append(text)
        return True

    question_evt = SimpleNamespace(
        event_type=EventType.USER_PROMPT,
        timestamp=time.time(),
        session_id="s-question",
        data={
            "payload": {
                "role": "user",
                "text": "What should we do so this system works better?",
            }
        },
    )
    statement_evt = SimpleNamespace(
        event_type=EventType.USER_PROMPT,
        timestamp=time.time() + 1,
        session_id="s-statement",
        data={
            "payload": {
                "role": "user",
                "text": "Verify contracts before changing payload shapes.",
            }
        },
    )

    monkeypatch.setattr(memory_capture, "read_recent_events", lambda _limit: [question_evt, statement_evt])
    monkeypatch.setattr(memory_capture, "commit_learning", _fake_commit)
    monkeypatch.setattr(memory_capture, "AUTO_SAVE_THRESHOLD", 0.70)
    monkeypatch.setattr(memory_capture, "SUGGEST_THRESHOLD", 0.55)
    monkeypatch.setattr(memory_capture, "_state", lambda: {"last_ts": 0.0})
    monkeypatch.setattr(memory_capture, "_save_state", lambda _state: None)
    monkeypatch.setattr(memory_capture, "_load_pending", lambda: {"items": []})
    monkeypatch.setattr(memory_capture, "_save_pending", lambda _pending: None)
    monkeypatch.setattr(
        memory_capture,
        "importance_score",
        lambda text: (0.95, {"test": 1.0}) if "verify contracts before changing payload shapes" in str(text).lower() else (0.0, {}),
    )

    stats = memory_capture.process_recent_memory_events(limit=10)

    assert calls
    assert len(calls) == 1
    assert calls[0] == "Verify contracts before changing payload shapes."
    assert stats["auto_saved"] == 1
    assert stats["suggested"] == 0


def test_promote_all_blocks_question_like_for_claude_and_agents(tmp_path, monkeypatch):
    project_dir = tmp_path
    claude = project_dir / "CLAUDE.md"
    agents = project_dir / "AGENTS.md"

    claude.write_text(
        "# CLAUDE\n\n## Spark Learnings\n\n*Auto-promoted insights from Spark*\n\n",
        encoding="utf-8",
    )
    agents.write_text(
        "# AGENTS\n\n## Spark Learnings\n\n*Auto-promoted insights from Spark*\n\n",
        encoding="utf-8",
    )

    created_at = (datetime.now() - timedelta(hours=12)).isoformat()
    fake = _FakeCognitive(
        {
            "q_claude": _FakeInsight(
                insight="What should we do so this important system runs right?",
                category=CognitiveCategory.WISDOM,
                reliability=1.0,
                times_validated=15,
                times_contradicted=0,
                created_at=created_at,
            ),
            "q_agents": _FakeInsight(
                insight="Can you check if we should use another path here?",
                category=CognitiveCategory.META_LEARNING,
                reliability=1.0,
                times_validated=12,
                times_contradicted=0,
                created_at=created_at,
            ),
            "ok_claude": _FakeInsight(
                insight="Verify contracts before changing payload shapes.",
                category=CognitiveCategory.WISDOM,
                reliability=0.96,
                times_validated=10,
                times_contradicted=0,
                created_at=created_at,
            ),
            "ok_agents": _FakeInsight(
                insight="Use apply_patch for focused single-file edits.",
                category=CognitiveCategory.META_LEARNING,
                reliability=0.95,
                times_validated=9,
                times_contradicted=0,
                created_at=created_at,
            ),
        }
    )

    log_file = tmp_path / "promotion_log.jsonl"
    monkeypatch.setattr("lib.promoter.get_cognitive_learner", lambda: fake)
    monkeypatch.setattr("lib.promoter.PROMOTION_LOG_FILE", log_file)
    monkeypatch.setattr(Promoter, "_llm_area_soft_promotion_triage", lambda self, insight, target: True)

    promoter = Promoter(project_dir=project_dir, reliability_threshold=0.7, min_validations=3)
    stats = promoter.promote_all(dry_run=False, include_project=False, include_chip_merge=False)

    claude_text = claude.read_text(encoding="utf-8")
    agents_text = agents.read_text(encoding="utf-8")

    assert "What should we do so this important system runs right?" not in claude_text
    assert "Can you check if we should use another path here?" not in agents_text
    assert "Verify contracts before changing payload shapes." in claude_text
    assert "Use apply_patch for focused single-file edits." in agents_text

    assert stats["promoted"] == 2
    assert fake.insights["q_claude"].promoted is False
    assert fake.insights["q_agents"].promoted is False
    assert fake.insights["ok_claude"].promoted is True
    assert fake.insights["ok_agents"].promoted is True

    rows = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    filtered_question_rows = [r for r in rows if r.get("result") == "filtered" and r.get("reason") == "question_or_conversational"]
    assert len(filtered_question_rows) >= 2
