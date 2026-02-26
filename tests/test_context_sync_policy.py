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
