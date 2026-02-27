from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from lib.cognitive_learner import CognitiveCategory
from lib.context_sync import _select_insights
from lib.promoter import Promoter


@dataclass
class _FakeInsight:
    insight: str
    category: CognitiveCategory
    reliability: float
    times_validated: int
    times_contradicted: int
    promoted: bool = False
    promoted_to: str | None = None
    confidence: float = 0.95
    created_at: str = ""
    context: str = "test"


class _FakeCognitive:
    def __init__(self, insights_map: dict[str, _FakeInsight], ranked: list[_FakeInsight]):
        self.insights = insights_map
        self._ranked = ranked

    def get_ranked_insights(self, **_kwargs):
        return list(self._ranked)

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


def test_context_sync_high_validation_override_respects_reliability():
    low_rel = _FakeInsight(
        insight="low reliability insight",
        category=CognitiveCategory.WISDOM,
        reliability=0.4,
        times_validated=80,
        times_contradicted=60,
    )
    high_rel = _FakeInsight(
        insight="high reliability insight",
        category=CognitiveCategory.WISDOM,
        reliability=0.9,
        times_validated=80,
        times_contradicted=0,
    )
    fake = _FakeCognitive({"low": low_rel, "high": high_rel}, ranked=[])

    selected = _select_insights(
        min_reliability=0.7,
        min_validations=3,
        limit=10,
        high_validation_override=50,
        cognitive=fake,
        project_context=None,
    )

    texts = [s.insight for s in selected]
    assert "high reliability insight" in texts
    assert "low reliability insight" not in texts


def test_promoter_confidence_track_requires_validations_and_positive_record():
    promoter = Promoter(project_dir=Path("."), reliability_threshold=0.7, min_validations=3, confidence_floor=0.9)
    now = datetime.now()

    # High confidence but too few validations.
    too_few = _FakeInsight(
        insight="too few validations",
        category=CognitiveCategory.WISDOM,
        reliability=1.0,
        times_validated=1,
        times_contradicted=0,
        confidence=0.98,
        created_at=(now - timedelta(hours=4)).isoformat(),
    )
    assert promoter._passes_confidence_track(too_few) is False

    # Enough validations but contradicted at parity.
    contradicted = _FakeInsight(
        insight="parity contradiction",
        category=CognitiveCategory.WISDOM,
        reliability=0.5,
        times_validated=3,
        times_contradicted=3,
        confidence=0.98,
        created_at=(now - timedelta(hours=4)).isoformat(),
    )
    assert promoter._passes_confidence_track(contradicted) is False


def test_promoter_demotes_stale_promotions(tmp_path, monkeypatch):
    project_dir = tmp_path
    claude = project_dir / "CLAUDE.md"
    claude.write_text(
        "# CLAUDE\n\n## Spark Learnings\n\n*Auto-promoted insights from Spark*\n\n"
        "- stale rule (40% reliable, 10 validations)\n",
        encoding="utf-8",
    )

    stale = _FakeInsight(
        insight="stale rule",
        category=CognitiveCategory.WISDOM,
        reliability=0.4,
        times_validated=10,
        times_contradicted=8,
        promoted=True,
        promoted_to="CLAUDE.md",
        confidence=0.95,
        created_at=(datetime.now() - timedelta(hours=6)).isoformat(),
    )
    fake = _FakeCognitive({"k1": stale}, ranked=[])
    monkeypatch.setattr("lib.promoter.get_cognitive_learner", lambda: fake)

    promoter = Promoter(project_dir=project_dir, reliability_threshold=0.7, min_validations=3)
    stats = promoter.demote_stale_promotions()

    updated = claude.read_text(encoding="utf-8")
    assert stats["demoted"] == 1
    assert stats["doc_removed"] == 1
    assert "stale rule" not in updated
    assert fake.insights["k1"].promoted is False


def test_promoter_blocks_question_like_direct_promotion(tmp_path, monkeypatch):
    project_dir = tmp_path
    claude = project_dir / "CLAUDE.md"
    claude.write_text(
        "# CLAUDE\n\n## Spark Learnings\n\n*Auto-promoted insights from Spark*\n\n",
        encoding="utf-8",
    )
    question_like = _FakeInsight(
        insight="What would be your best recommendation so this system works right?",
        category=CognitiveCategory.WISDOM,
        reliability=1.0,
        times_validated=12,
        times_contradicted=0,
        confidence=0.99,
        created_at=(datetime.now() - timedelta(hours=12)).isoformat(),
    )
    fake = _FakeCognitive({"q1": question_like}, ranked=[])
    log_file = tmp_path / "promotion_log.jsonl"
    monkeypatch.setattr("lib.promoter.get_cognitive_learner", lambda: fake)
    monkeypatch.setattr("lib.promoter.PROMOTION_LOG_FILE", log_file)

    promoter = Promoter(project_dir=project_dir, reliability_threshold=0.7, min_validations=3)
    target = promoter._get_target_for_category(question_like.category)
    assert target is not None

    promoted = promoter.promote_insight(question_like, "q1", target)
    updated = claude.read_text(encoding="utf-8")

    assert promoted is False
    assert "What would be your best recommendation" not in updated
    assert fake.insights["q1"].promoted is False
    rows = [line for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows
    assert "question_or_conversational" in rows[-1]
