from __future__ import annotations

import json

import lib.noise_classifier as noise_classifier
from lib.promoter import is_operational_insight


def test_promoter_operational_shadow_mode_uses_legacy_when_enforce_disabled(monkeypatch, tmp_path):
    shadow_log = tmp_path / "noise_shadow.jsonl"
    monkeypatch.setattr(noise_classifier, "SHADOW_LOG", shadow_log)
    monkeypatch.setenv("SPARK_NOISE_CLASSIFIER_ENFORCE", "0")

    # Legacy promoter filter allows this; unified marks it as markdown telemetry.
    result = is_operational_insight("## Session History")

    assert result is False
    rows = [json.loads(line) for line in shadow_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["module"] == "promoter.is_operational_insight"
    assert rows[0]["legacy_is_noise"] is False
    assert rows[0]["unified_is_noise"] is True


def test_promoter_operational_enforce_uses_unified(monkeypatch, tmp_path):
    shadow_log = tmp_path / "noise_shadow.jsonl"
    monkeypatch.setattr(noise_classifier, "SHADOW_LOG", shadow_log)
    monkeypatch.setenv("SPARK_NOISE_CLASSIFIER_ENFORCE", "1")

    result = is_operational_insight("## Session History")

    assert result is True


def test_promoter_operational_default_enforces_unified(monkeypatch, tmp_path):
    shadow_log = tmp_path / "noise_shadow.jsonl"
    monkeypatch.setattr(noise_classifier, "SHADOW_LOG", shadow_log)
    monkeypatch.delenv("SPARK_NOISE_CLASSIFIER_ENFORCE", raising=False)

    result = is_operational_insight("## Session History")

    assert result is True


def test_promoter_operational_agreement_does_not_log(monkeypatch, tmp_path):
    shadow_log = tmp_path / "noise_shadow.jsonl"
    monkeypatch.setattr(noise_classifier, "SHADOW_LOG", shadow_log)
    monkeypatch.setenv("SPARK_NOISE_CLASSIFIER_ENFORCE", "0")

    result = is_operational_insight("Sequence 'Bash -> Edit -> Read' worked well")

    assert result is True
    assert not shadow_log.exists()


def test_promoter_treats_user_question_as_operational(monkeypatch, tmp_path):
    shadow_log = tmp_path / "noise_shadow.jsonl"
    monkeypatch.setattr(noise_classifier, "SHADOW_LOG", shadow_log)
    monkeypatch.setenv("SPARK_NOISE_CLASSIFIER_ENFORCE", "0")

    result = is_operational_insight("What would be your best recommendation here?")

    assert result is True
