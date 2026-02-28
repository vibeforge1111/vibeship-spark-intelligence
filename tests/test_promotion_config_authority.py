from __future__ import annotations

import json

import lib.auto_promote as auto_promote
import lib.promoter as promoter
from lib.cognitive_learner import CognitiveCategory, CognitiveInsight


def test_promoter_load_config_reads_promotion_section(tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "promotion": {"threshold": 0.91, "min_age_hours": 9.0},
            }
        ),
        encoding="utf-8",
    )

    cfg = promoter._load_promotion_config(path=tuneables)

    assert cfg["threshold"] == 0.91
    assert cfg["min_age_hours"] == 9.0


def test_auto_promote_interval_uses_promotion_section(tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps({"promotion": {"auto_interval_s": 1234}}),
        encoding="utf-8",
    )

    interval = auto_promote._load_promotion_config_interval(path=tuneables)

    assert interval == 1234


def test_promoter_blocks_repromotion_after_reliability_demotions(monkeypatch, tmp_path):
    promotion_log = tmp_path / "promotion_log.jsonl"
    key = "wisdom:repeat-noise-key"
    promotion_log.write_text(
        "\n".join(
            [
                json.dumps({"key": key, "result": "demoted", "reason": "reliability_degraded"}),
                json.dumps({"key": key, "result": "demoted", "reason": "reliability_degraded"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    insight = CognitiveInsight(
        category=CognitiveCategory.WISDOM,
        insight="Use Glob to verify files before edits.",
        evidence=["obs"],
        confidence=0.99,
        context="ctx",
        times_validated=12,
        times_contradicted=0,
        promoted=False,
    )

    class _FakeLearner:
        def __init__(self):
            self.insights = {key: insight}

        @staticmethod
        def is_noise_insight(_text: str) -> bool:
            return False

    monkeypatch.setattr(promoter, "PROMOTION_LOG_FILE", promotion_log)
    monkeypatch.setattr(promoter, "get_cognitive_learner", lambda: _FakeLearner())
    monkeypatch.setattr(promoter, "_load_promotion_config", lambda path=None: {"repromotion_demotion_limit": 2})

    p = promoter.Promoter(project_dir=tmp_path)
    promotable = p.get_promotable_insights(include_operational=True)

    assert promotable == []
