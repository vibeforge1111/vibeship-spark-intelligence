from __future__ import annotations

import json

from lib import context_sync


def test_default_sync_policy_is_core(monkeypatch):
    monkeypatch.delenv("SPARK_SYNC_MODE", raising=False)
    monkeypatch.delenv("SPARK_SYNC_TARGETS", raising=False)
    monkeypatch.delenv("SPARK_SYNC_DISABLE_TARGETS", raising=False)
    monkeypatch.setattr(context_sync, "TUNEABLES_FILE", context_sync.Path("/nonexistent/tuneables.json"))
    monkeypatch.setattr(context_sync, "BASELINE_TUNEABLES_FILE", context_sync.Path("/nonexistent/baseline.json"))

    policy = context_sync._load_sync_adapter_policy()
    assert set(policy["enabled"]) == {"openclaw", "exports"}
    assert "cursor" in policy["disabled"]


def test_sync_policy_allows_explicit_targets_env(monkeypatch):
    monkeypatch.setenv("SPARK_SYNC_TARGETS", "openclaw,exports,cursor")
    monkeypatch.delenv("SPARK_SYNC_DISABLE_TARGETS", raising=False)
    monkeypatch.delenv("SPARK_SYNC_MODE", raising=False)
    monkeypatch.setattr(context_sync, "TUNEABLES_FILE", context_sync.Path("/nonexistent/tuneables.json"))
    monkeypatch.setattr(context_sync, "BASELINE_TUNEABLES_FILE", context_sync.Path("/nonexistent/baseline.json"))

    policy = context_sync._load_sync_adapter_policy()
    assert set(policy["enabled"]) == {"openclaw", "exports", "cursor"}


def test_sync_policy_reads_tuneables(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps(
            {
                "sync": {
                    "mode": "all",
                    "adapters_disabled": ["windsurf", "clawdbot"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("SPARK_SYNC_MODE", raising=False)
    monkeypatch.delenv("SPARK_SYNC_TARGETS", raising=False)
    monkeypatch.delenv("SPARK_SYNC_DISABLE_TARGETS", raising=False)
    monkeypatch.setattr(context_sync, "TUNEABLES_FILE", tuneables)
    monkeypatch.setattr(context_sync, "BASELINE_TUNEABLES_FILE", context_sync.Path("/nonexistent/baseline.json"))

    policy = context_sync._load_sync_adapter_policy()
    assert "claude_code" in policy["enabled"]
    assert "windsurf" in policy["disabled"]
    assert "clawdbot" in policy["disabled"]


def test_mind_limit_reads_sync_section_and_env(monkeypatch, tmp_path):
    tuneables = tmp_path / "tuneables.json"
    tuneables.write_text(
        json.dumps({"sync": {"mind_limit": 4}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(context_sync, "TUNEABLES_FILE", tuneables)
    monkeypatch.setattr(context_sync, "BASELINE_TUNEABLES_FILE", context_sync.Path("/nonexistent/baseline.json"))
    monkeypatch.delenv("SPARK_SYNC_MIND_LIMIT", raising=False)

    assert context_sync._mind_limit_from_env() == 4

    monkeypatch.setenv("SPARK_SYNC_MIND_LIMIT", "6")
    assert context_sync._mind_limit_from_env() == 6


def test_periodic_compaction_respects_disabled_env(monkeypatch):
    class _DummyCognitive:
        def dedupe_signals(self):
            raise AssertionError("should not run when disabled")

        def dedupe_struggles(self):
            raise AssertionError("should not run when disabled")

        def promote_to_wisdom(self):
            raise AssertionError("should not run when disabled")

    monkeypatch.setenv("SPARK_COGNITIVE_COMPACTION_ENABLED", "0")
    out = context_sync._run_periodic_compaction(_DummyCognitive())
    assert out["ran"] is False
    assert out["reason"] == "disabled"


def test_periodic_compaction_writes_state_and_obeys_cooldown(monkeypatch, tmp_path):
    class _DummyCognitive:
        def __init__(self):
            self.calls = 0

        def dedupe_signals(self):
            self.calls += 1
            return {"a": 2}

        def dedupe_struggles(self):
            self.calls += 1
            return {}

        def promote_to_wisdom(self):
            self.calls += 1
            return {"promoted": 1}

    state_path = tmp_path / "state.json"
    monkeypatch.setattr(context_sync, "COMPACTION_STATE_FILE", state_path)
    monkeypatch.setenv("SPARK_COGNITIVE_COMPACTION_ENABLED", "1")
    monkeypatch.setenv("SPARK_COGNITIVE_COMPACTION_COOLDOWN_S", "3600")

    cog = _DummyCognitive()
    first = context_sync._run_periodic_compaction(cog)
    assert first["ran"] is True
    assert state_path.exists()
    assert cog.calls == 3

    second = context_sync._run_periodic_compaction(cog)
    assert second["ran"] is False
    assert second["reason"] == "cooldown"
