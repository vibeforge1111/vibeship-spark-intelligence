from __future__ import annotations

import json
from types import SimpleNamespace

import lib.advisory_engine_alpha as advisory_alpha_mod
import spark.cli as spark_cli


def _args(**kwargs):
    defaults = {
        "advisory_cmd": "show",
        "json": False,
        "source": "test",
        "memory_mode": None,
        "guidance_style": None,
        "profile": "enhanced",
        "provider": "auto",
        "minimax_model": "MiniMax-M2.5",
        "ai_timeout_s": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_cmd_advisory_show_json(monkeypatch, capsys):
    monkeypatch.setattr(
        spark_cli,
        "get_current_advisory_preferences",
        lambda: {
            "memory_mode": "standard",
            "guidance_style": "balanced",
            "effective": {"replay_enabled": True},
        },
    )
    monkeypatch.setattr(
        spark_cli,
        "_get_advisory_runtime_state",
        lambda: {"available": True, "engine_enabled": True, "emitter_enabled": True},
    )

    spark_cli.cmd_advisory(_args(advisory_cmd="show", json=True))
    payload = json.loads(capsys.readouterr().out)

    assert payload["memory_mode"] == "standard"
    assert payload["guidance_style"] == "balanced"
    assert payload["effective"]["replay_enabled"] is True
    assert payload["runtime"]["available"] is True


def test_cmd_advisory_setup_applies_current_when_non_interactive(monkeypatch):
    monkeypatch.setattr(
        spark_cli,
        "get_current_advisory_preferences",
        lambda: {
            "memory_mode": "standard",
            "guidance_style": "balanced",
            "effective": {"replay_enabled": True},
        },
    )
    monkeypatch.setattr(
        spark_cli,
        "get_advisory_setup_questions",
        lambda current: {
            "current": current,
            "questions": [
                {
                    "id": "memory_mode",
                    "question": "Q1",
                    "options": [{"value": "standard"}, {"value": "off"}, {"value": "replay"}],
                },
                {
                    "id": "guidance_style",
                    "question": "Q2",
                    "options": [{"value": "balanced"}, {"value": "concise"}, {"value": "coach"}],
                },
            ],
        },
    )

    calls = {}

    def _fake_apply(memory_mode=None, guidance_style=None, source=""):
        calls["memory_mode"] = memory_mode
        calls["guidance_style"] = guidance_style
        calls["source"] = source
        return {
            "memory_mode": memory_mode,
            "guidance_style": guidance_style,
            "effective": {"replay_enabled": memory_mode != "off"},
        }

    monkeypatch.setattr(spark_cli, "apply_advisory_preferences", _fake_apply)

    spark_cli.cmd_advisory(_args(advisory_cmd="setup", source="spark_cli_setup"))

    assert calls["memory_mode"] == "standard"
    assert calls["guidance_style"] == "balanced"
    assert calls["source"] == "spark_cli_setup"


def test_cmd_advisory_set_defaults_to_on_when_empty(monkeypatch):
    calls = {}

    def _fake_apply(memory_mode=None, guidance_style=None, source=""):
        calls["memory_mode"] = memory_mode
        calls["guidance_style"] = guidance_style
        calls["source"] = source
        return {
            "memory_mode": memory_mode,
            "guidance_style": guidance_style,
            "effective": {"replay_enabled": True},
        }

    monkeypatch.setattr(spark_cli, "apply_advisory_preferences", _fake_apply)

    spark_cli.cmd_advisory(_args(advisory_cmd="set", source="spark_cli_set"))

    assert calls["memory_mode"] == "standard"
    assert calls["guidance_style"] == "balanced"
    assert calls["source"] == "spark_cli_set"


def test_cmd_advisory_off_forces_memory_mode_off(monkeypatch):
    calls = {}

    def _fake_apply(memory_mode=None, guidance_style=None, source=""):
        calls["memory_mode"] = memory_mode
        calls["guidance_style"] = guidance_style
        calls["source"] = source
        return {
            "memory_mode": memory_mode,
            "guidance_style": guidance_style,
            "effective": {"replay_enabled": False},
        }

    monkeypatch.setattr(spark_cli, "apply_advisory_preferences", _fake_apply)

    spark_cli.cmd_advisory(
        _args(advisory_cmd="off", guidance_style="coach", source="spark_cli_off")
    )

    assert calls["memory_mode"] == "off"
    assert calls["guidance_style"] == "coach"
    assert calls["source"] == "spark_cli_off"


def test_print_advisory_preferences_uses_runtime_for_true_on_state(capsys):
    spark_cli._print_advisory_preferences(
        {
            "memory_mode": "standard",
            "guidance_style": "balanced",
            "effective": {"replay_enabled": True},
            "runtime": {
                "available": True,
                "engine_enabled": False,
                "emitter_enabled": True,
                "synth_tier": "Programmatic",
            },
            "drift": {"has_drift": True, "count": 2, "overrides": []},
        }
    )
    out = capsys.readouterr().out

    assert "advisory_on: no" in out
    assert "advisory_runtime: down" in out
    assert "replay_advisory: on" in out
    assert "profile_drift: yes (2 overrides)" in out


def test_cmd_advisory_quality_calls_uplift(monkeypatch, capsys):
    calls = {}

    def _fake_quality(
        profile="enhanced",
        preferred_provider="auto",
        minimax_model=None,
        ai_timeout_s=None,
        source="",
    ):
        calls["profile"] = profile
        calls["preferred_provider"] = preferred_provider
        calls["minimax_model"] = minimax_model
        calls["ai_timeout_s"] = ai_timeout_s
        calls["source"] = source
        return {
            "profile": profile,
            "preferred_provider": preferred_provider,
            "minimax_model": minimax_model,
            "ai_timeout_s": ai_timeout_s or 6.0,
            "runtime": {"synthesizer": {"tier_label": "AI-Enhanced", "ai_available": True}},
            "warnings": [],
        }

    monkeypatch.setattr(spark_cli, "apply_advisory_quality_uplift", _fake_quality)

    spark_cli.cmd_advisory(
        _args(
            advisory_cmd="quality",
            profile="max",
            provider="openai",
            minimax_model="MiniMax-M2.5",
            ai_timeout_s=7.5,
            source="spark_cli_quality",
        )
    )
    out = capsys.readouterr().out

    assert calls["profile"] == "max"
    assert calls["preferred_provider"] == "openai"
    assert calls["minimax_model"] == "MiniMax-M2.5"
    assert calls["ai_timeout_s"] == 7.5
    assert calls["source"] == "spark_cli_quality"
    assert "Advisory Quality Uplift" in out
    assert "synth_tier: AI-Enhanced" in out


def test_cmd_advisory_doctor_json(monkeypatch, capsys):
    monkeypatch.setattr(
        spark_cli,
        "_advisory_doctor_snapshot",
        lambda: {"ok": True, "advisory_on": True, "recommendations": ["No action needed"]},
    )

    spark_cli.cmd_advisory(_args(advisory_cmd="doctor", json=True))
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["advisory_on"] is True


def test_cmd_advisory_repair_uses_preference_repair(monkeypatch, capsys):
    calls = {}

    def _fake_repair(source=""):
        calls["source"] = source
        return {
            "before_drift": {"has_drift": True, "count": 2},
            "after_drift": {"has_drift": False, "count": 0},
            "applied": {
                "memory_mode": "standard",
                "guidance_style": "balanced",
                "effective": {"replay_enabled": True},
            },
        }

    monkeypatch.setattr(spark_cli, "repair_advisory_profile_drift", _fake_repair)
    monkeypatch.setattr(
        spark_cli,
        "_get_advisory_runtime_state",
        lambda: {"available": True, "engine_enabled": True, "emitter_enabled": True},
    )

    spark_cli.cmd_advisory(_args(advisory_cmd="repair", source="spark_cli_repair"))
    out = capsys.readouterr().out

    assert calls["source"] == "spark_cli_repair"
    assert "before_drift: yes (2 overrides)" in out
    assert "after_drift: no (0 overrides)" in out


def test_get_advisory_runtime_state_uses_alpha_engine(monkeypatch):
    monkeypatch.setattr(
        advisory_alpha_mod,
        "get_alpha_status",
        lambda: {
            "enabled": True,
            "config": {"force_programmatic_synth": True},
            "alpha_log": "tmp/advisory_engine_alpha.jsonl",
        },
    )

    state = spark_cli._get_advisory_runtime_state()

    assert state["available"] is True
    assert state["engine_enabled"] is True
    assert state["emitter_enabled"] is True
    assert state["synth_tier"] == "Programmatic"
