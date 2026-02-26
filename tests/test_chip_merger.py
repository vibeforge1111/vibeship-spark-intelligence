import json
from datetime import datetime, timedelta, timezone

from lib import chip_merger as cm


class _DummyCog:
    def __init__(self):
        self.calls = []

    def add_insight(self, **_kwargs):
        self.calls.append(dict(_kwargs))
        return {"ok": True}

    def _generate_key(self, category, text):
        return f"{category.value}:{text[:10]}"


def _write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_hash_is_stable_across_timestamps():
    first = cm._hash_insight("bench_core", "Prefer stable contracts in integrations")
    second = cm._hash_insight("bench_core", "Prefer stable contracts in integrations")
    assert first == second


def test_merge_skips_duplicate_content_in_same_run(tmp_path, monkeypatch):
    chip_dir = tmp_path / "chip_insights"
    state_file = tmp_path / "chip_merge_state.json"
    monkeypatch.setattr(cm, "CHIP_INSIGHTS_DIR", chip_dir)
    monkeypatch.setattr(cm, "MERGE_STATE_FILE", state_file)
    cog = _DummyCog()
    monkeypatch.setattr(cm, "get_cognitive_learner", lambda: cog)
    monkeypatch.setattr(cm, "record_exposures", lambda *args, **kwargs: 0)

    now = datetime.now(timezone.utc)
    rows = [
        {
                "chip_id": "marketing",
                "content": "Use contract tests before broad refactors",
                "confidence": 0.9,
                "timestamp": (now - timedelta(seconds=1)).isoformat(),
                "captured_data": {
                    "quality_score": {
                        "total": 0.95,
                        "cognitive_value": 0.7,
                        "actionability": 0.7,
                        "transferability": 0.6,
                    }
                },
            },
            {
                "chip_id": "marketing",
                "content": "Use contract tests before broad refactors",
                "confidence": 0.92,
                "timestamp": now.isoformat(),
                "captured_data": {
                    "quality_score": {
                        "total": 0.96,
                        "cognitive_value": 0.72,
                        "actionability": 0.7,
                        "transferability": 0.6,
                    }
                },
            },
    ]
    _write_rows(chip_dir / "marketing.jsonl", rows)

    stats = cm.merge_chip_insights(limit=20, dry_run=False)

    assert stats["merged"] == 1
    assert stats["skipped_duplicate"] == 1


def test_low_quality_cooldown_suppresses_repeat_churn(tmp_path, monkeypatch):
    chip_dir = tmp_path / "chip_insights"
    state_file = tmp_path / "chip_merge_state.json"
    monkeypatch.setattr(cm, "CHIP_INSIGHTS_DIR", chip_dir)
    monkeypatch.setattr(cm, "MERGE_STATE_FILE", state_file)
    monkeypatch.setattr(cm, "get_cognitive_learner", lambda: _DummyCog())
    monkeypatch.setattr(cm, "record_exposures", lambda *args, **kwargs: 0)

    row = {
        "chip_id": "bench_core",
        "content": "vague weak note",
        "confidence": 0.9,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "captured_data": {"quality_score": {"total": 0.2}},
    }
    _write_rows(chip_dir / "bench_core.jsonl", [row])

    first = cm.merge_chip_insights(min_confidence=0.5, min_quality_score=0.7, limit=5, dry_run=False)
    second = cm.merge_chip_insights(min_confidence=0.5, min_quality_score=0.7, limit=5, dry_run=False)

    assert first["skipped_low_quality"] == 1
    assert second["skipped_low_quality"] == 0
    assert second["skipped_low_quality_cooldown"] == 1


def test_duplicate_churn_throttle_skips_repeated_cycles(tmp_path, monkeypatch):
    chip_dir = tmp_path / "chip_insights"
    state_file = tmp_path / "chip_merge_state.json"
    monkeypatch.setattr(cm, "CHIP_INSIGHTS_DIR", chip_dir)
    monkeypatch.setattr(cm, "MERGE_STATE_FILE", state_file)
    monkeypatch.setattr(cm, "get_cognitive_learner", lambda: _DummyCog())
    monkeypatch.setattr(cm, "record_exposures", lambda *args, **kwargs: 0)

    text = "Use contract tests before broad refactors"
    sig = cm._hash_insight("marketing", text)
    state_file.write_text(
        json.dumps(
            {
                "merged_hashes": [sig],
                "last_merge": None,
                "rejected_low_quality": {},
                "duplicate_churn_until": 0.0,
            }
        ),
        encoding="utf-8",
    )
    rows = []
    now = datetime.now(timezone.utc)
    for i in range(12):
        rows.append(
                {
                    "chip_id": "marketing",
                    "content": text,
                    "confidence": 0.95,
                    "timestamp": (now - timedelta(seconds=i)).isoformat(),
                    "captured_data": {
                        "quality_score": {
                            "total": 0.95,
                            "cognitive_value": 0.7,
                            "actionability": 0.7,
                            "transferability": 0.6,
                        }
                    },
                }
            )
    _write_rows(chip_dir / "marketing.jsonl", rows)

    first = cm.merge_chip_insights(limit=20, dry_run=False)
    second = cm.merge_chip_insights(limit=20, dry_run=False)

    assert first["processed"] >= 10
    assert first["merged"] == 0
    assert first["throttle_active"] is True
    assert second["throttled_duplicate_churn"] == 1
    assert second["processed"] == 0


def test_chip_merge_loads_duplicate_churn_tuneables(tmp_path, monkeypatch):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "chip_merge": {
                    "duplicate_churn_ratio": 0.9,
                    "duplicate_churn_min_processed": 25,
                    "duplicate_churn_cooldown_s": 900,
                    "min_cognitive_value": 0.52,
                    "min_actionability": 0.41,
                    "min_transferability": 0.33,
                    "min_statement_len": 44,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cm, "TUNEABLES_FILE", tuneables)

    loaded = cm._load_merge_tuneables()
    assert loaded["duplicate_churn_ratio"] == 0.9
    assert loaded["duplicate_churn_min_processed"] == 25
    assert loaded["duplicate_churn_cooldown_s"] == 900
    assert loaded["min_cognitive_value"] == 0.52
    assert loaded["min_actionability"] == 0.41
    assert loaded["min_transferability"] == 0.33
    assert loaded["min_statement_len"] == 44


def test_merge_skips_telemetry_non_learning_rows(tmp_path, monkeypatch):
    chip_dir = tmp_path / "chip_insights"
    state_file = tmp_path / "chip_merge_state.json"
    learning_file = tmp_path / "chip_learning_distillations.jsonl"
    cog = _DummyCog()
    monkeypatch.setattr(cm, "CHIP_INSIGHTS_DIR", chip_dir)
    monkeypatch.setattr(cm, "MERGE_STATE_FILE", state_file)
    monkeypatch.setattr(cm, "LEARNING_DISTILLATIONS_FILE", learning_file)
    monkeypatch.setattr(cm, "get_cognitive_learner", lambda: cog)
    monkeypatch.setattr(cm, "record_exposures", lambda *args, **kwargs: 0)

    row = {
        "chip_id": "spark-core",
        "content": "[Spark Core Intelligence] post_tool: tool_name: Read, event_type: post_tool",
        "confidence": 0.95,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "captured_data": {"quality_score": {"total": 0.9, "cognitive_value": 0.7, "actionability": 0.6, "transferability": 0.6}},
    }
    _write_rows(chip_dir / "spark-core.jsonl", [row])

    stats = cm.merge_chip_insights(min_confidence=0.5, min_quality_score=0.5, limit=5, dry_run=False)
    assert stats["merged"] == 0
    assert stats["skipped_non_learning"] >= 1
    assert cog.calls == []


def test_merge_distills_from_structured_fields(tmp_path, monkeypatch):
    chip_dir = tmp_path / "chip_insights"
    state_file = tmp_path / "chip_merge_state.json"
    learning_file = tmp_path / "chip_learning_distillations.jsonl"
    cog = _DummyCog()
    monkeypatch.setattr(cm, "CHIP_INSIGHTS_DIR", chip_dir)
    monkeypatch.setattr(cm, "MERGE_STATE_FILE", state_file)
    monkeypatch.setattr(cm, "LEARNING_DISTILLATIONS_FILE", learning_file)
    monkeypatch.setattr(cm, "get_cognitive_learner", lambda: cog)
    monkeypatch.setattr(cm, "record_exposures", lambda *args, **kwargs: 0)

    # Track calls to validate_and_store_insight (replaces direct cog.add_insight)
    vas_calls = []
    def _fake_validate_and_store(**kwargs):
        vas_calls.append(kwargs)
        return True

    import lib.validate_and_store as vas_mod
    monkeypatch.setattr(vas_mod, "validate_and_store_insight", _fake_validate_and_store)

    row = {
        "chip_id": "engagement-pulse",
        "content": "",
        "confidence": 0.92,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "captured_data": {
            "fields": {"topic": "agent payments", "likes": 31, "replies": 4, "retweets": 6},
            "quality_score": {"total": 0.81, "cognitive_value": 0.7, "actionability": 0.6, "transferability": 0.5},
        },
    }
    _write_rows(chip_dir / "engagement-pulse.jsonl", [row])

    stats = cm.merge_chip_insights(min_confidence=0.5, min_quality_score=0.5, limit=5, dry_run=False)
    assert stats["merged"] == 1
    assert stats["merged_distilled"] == 1
    assert len(vas_calls) == 1
    merged_text = str(vas_calls[0].get("text") or "").lower()
    assert "engagement evidence" in merged_text
    assert "agent payments" in merged_text
    assert "source" in vas_calls[0]


def test_merge_uses_refined_store_result_for_exposure_key(tmp_path, monkeypatch):
    chip_dir = tmp_path / "chip_insights"
    state_file = tmp_path / "chip_merge_state.json"
    learning_file = tmp_path / "chip_learning_distillations.jsonl"
    monkeypatch.setattr(cm, "CHIP_INSIGHTS_DIR", chip_dir)
    monkeypatch.setattr(cm, "MERGE_STATE_FILE", state_file)
    monkeypatch.setattr(cm, "LEARNING_DISTILLATIONS_FILE", learning_file)
    monkeypatch.setattr(cm, "get_cognitive_learner", lambda: _DummyCog())

    captured_exposures = {}

    def _fake_record_exposures(*, source, items, session_id=None, trace_id=None):
        captured_exposures["source"] = source
        captured_exposures["items"] = list(items or [])
        return len(items or [])

    monkeypatch.setattr(cm, "record_exposures", _fake_record_exposures)

    def _fake_validate_and_store(**kwargs):
        return {
            "stored": True,
            "insight_key": "reasoning:refined_key",
            "stored_text": "Refined learning statement from Meta-Ralph",
        }

    import lib.validate_and_store as vas_mod
    monkeypatch.setattr(vas_mod, "validate_and_store_insight", _fake_validate_and_store)

    row = {
        "chip_id": "engagement-pulse",
        "content": "",
        "confidence": 0.92,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "captured_data": {
            "fields": {"topic": "agent payments", "likes": 31, "replies": 4, "retweets": 6},
            "quality_score": {"total": 0.81, "cognitive_value": 0.7, "actionability": 0.6, "transferability": 0.5},
        },
    }
    _write_rows(chip_dir / "engagement-pulse.jsonl", [row])

    stats = cm.merge_chip_insights(min_confidence=0.5, min_quality_score=0.5, limit=5, dry_run=False)
    assert stats["merged"] == 1
    assert captured_exposures["source"] == "chip_merge"
    assert captured_exposures["items"][0]["insight_key"] == "reasoning:refined_key"
    assert captured_exposures["items"][0]["text"] == "Refined learning statement from Meta-Ralph"

    distillation_row = json.loads(learning_file.read_text(encoding="utf-8").splitlines()[0])
    assert distillation_row["stored_statement"] == "Refined learning statement from Meta-Ralph"


def test_distill_skips_telemetry_observer_rows():
    out = cm._distill_learning_statement(
        chip_id="vibecoding",
        content="Use tests before deploy",
        captured_data={},
        min_len=20,
        observer_name="post_tool_use",
    )
    assert out == ""


def test_distill_prefers_valid_learning_payload():
    out = cm._distill_learning_statement(
        chip_id="social-convo",
        content="[Social] tool_name: Read, event_type: post_tool",
        captured_data={
            "learning_payload": {
                "schema_version": "v1",
                "decision": "Prefer conversation hooks with observed reciprocity signals.",
                "rationale": "Because multi-turn threads with reciprocity and low barrier produced better engagement.",
                "evidence": ["reciprocity_signal=high", "barrier_level=low", "turn_taking=balanced"],
                "expected_outcome": "Increase reply quality and sustained conversations.",
            }
        },
        min_len=24,
        observer_name="conversation_psychology",
    )
    assert "Prefer conversation hooks" in out
    assert "Expected outcome:" in out
    assert "reciprocity_signal=high" in out
