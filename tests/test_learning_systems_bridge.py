import json

import lib.learning_systems_bridge as lsb


def test_store_external_insight_routes_through_validate_and_store(monkeypatch, tmp_path):
    monkeypatch.setenv("SPARK_LEARNING_BRIDGE_ENABLED", "1")
    monkeypatch.setattr(lsb, "INSIGHT_AUDIT_FILE", tmp_path / "insight_ingest_audit.jsonl")

    calls = {}

    def _fake_validate_and_store_insight(**kwargs):
        calls.update(kwargs)
        return {
            "stored": True,
            "insight_key": "reasoning:test_key",
            "stored_text": kwargs.get("text", ""),
        }

    import lib.validate_and_store as vas

    monkeypatch.setattr(vas, "validate_and_store_insight", _fake_validate_and_store_insight)

    out = lsb.store_external_insight(
        text="Use retries for flaky network calls",
        category="reasoning",
        source="system_04",
        context="retrieval_gauntlet",
        confidence=0.82,
    )

    assert out["stored"] is True
    assert calls["source"] == "system_04"
    assert calls["return_details"] is True

    rows = lsb.INSIGHT_AUDIT_FILE.read_text(encoding="utf-8").splitlines()
    row = json.loads(rows[-1])
    assert row["stored"] is True
    assert row["source"] == "system_04"
    assert row["insight_key"] == "reasoning:test_key"


def test_store_external_insight_rejects_invalid_category(monkeypatch, tmp_path):
    monkeypatch.setenv("SPARK_LEARNING_BRIDGE_ENABLED", "1")
    monkeypatch.setattr(lsb, "INSIGHT_AUDIT_FILE", tmp_path / "insight_ingest_audit.jsonl")

    out = lsb.store_external_insight(
        text="Anything",
        category="not_a_real_category",
        source="system_99",
    )
    assert out["stored"] is False
    assert out["reason"] == "invalid_category"


def test_propose_tuneable_change_and_list(monkeypatch, tmp_path):
    monkeypatch.setenv("SPARK_LEARNING_BRIDGE_ENABLED", "1")
    monkeypatch.setattr(lsb, "TUNEABLE_PROPOSALS_FILE", tmp_path / "tuneable_proposals.jsonl")

    out = lsb.propose_tuneable_change(
        system_id="04",
        section="advisor",
        key="min_rank_score",
        new_value=0.52,
        reasoning="Improve precision in retrieval gauntlet scenarios",
        confidence=0.73,
        metadata={"experiment": "rg-2026-02-24"},
    )
    assert out["queued"] is True
    assert out["proposal_id"]

    proposals = lsb.list_tuneable_proposals(limit=10)
    assert len(proposals) == 1
    assert proposals[0]["section"] == "advisor"
    assert proposals[0]["key"] == "min_rank_score"


def test_store_external_insight_falls_back_when_return_details_unsupported(monkeypatch, tmp_path):
    monkeypatch.setenv("SPARK_LEARNING_BRIDGE_ENABLED", "1")
    monkeypatch.setattr(lsb, "INSIGHT_AUDIT_FILE", tmp_path / "insight_ingest_audit.jsonl")

    def _legacy_validate_and_store_insight(**kwargs):
        if "return_details" in kwargs:
            raise TypeError("validate_and_store_insight() got an unexpected keyword argument 'return_details'")
        return True

    import lib.validate_and_store as vas
    monkeypatch.setattr(vas, "validate_and_store_insight", _legacy_validate_and_store_insight)

    out = lsb.store_external_insight(
        text="Legacy compatibility insight",
        category="reasoning",
        source="system_legacy",
    )

    assert out["stored"] is True
