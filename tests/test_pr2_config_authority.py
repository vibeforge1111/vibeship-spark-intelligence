"""Tests for PR 2 config-authority migrations.

Covers: opportunity_scanner (22 keys), prediction (7 keys).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tuneables(tmp_path: Path, sections: Dict[str, Any]) -> Path:
    """Write a minimal tuneables.json and return its path."""
    p = tmp_path / "tuneables.json"
    p.write_text(json.dumps(sections), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# opportunity_scanner
# ---------------------------------------------------------------------------

class TestOpportunityScannerConfig:

    def test_scanner_defaults(self, tmp_path, monkeypatch):
        """Scanner resolves schema defaults when no config exists."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        for var in ("SPARK_OPPORTUNITY_SCANNER", "SPARK_OPPORTUNITY_SELF_MAX",
                     "SPARK_OPPORTUNITY_USER_MAX", "SPARK_OPPORTUNITY_HISTORY_MAX",
                     "SPARK_OPPORTUNITY_SELF_DEDUP_WINDOW_S", "SPARK_OPPORTUNITY_SELF_RECENT_LOOKBACK",
                     "SPARK_OPPORTUNITY_SELF_CATEGORY_CAP", "SPARK_OPPORTUNITY_USER_SCAN",
                     "SPARK_OPPORTUNITY_SCAN_EVENT_LIMIT",
                     "SPARK_OPPORTUNITY_OUTCOME_WINDOW_S", "SPARK_OPPORTUNITY_OUTCOME_LOOKBACK",
                     "SPARK_OPPORTUNITY_PROMOTION_MIN_SUCCESSES",
                     "SPARK_OPPORTUNITY_PROMOTION_MIN_EFFECTIVENESS",
                     "SPARK_OPPORTUNITY_PROMOTION_LOOKBACK",
                     "SPARK_OPPORTUNITY_LLM_ENABLED", "SPARK_OPPORTUNITY_LLM_PROVIDER",
                     "SPARK_OPPORTUNITY_LLM_TIMEOUT_S", "SPARK_OPPORTUNITY_LLM_MAX_ITEMS",
                     "SPARK_OPPORTUNITY_LLM_MIN_CONTEXT_CHARS", "SPARK_OPPORTUNITY_LLM_COOLDOWN_S",
                     "SPARK_OPPORTUNITY_DECISION_LOOKBACK", "SPARK_OPPORTUNITY_DISMISS_TTL_S"):
            monkeypatch.delenv(var, raising=False)
        import lib.opportunity_scanner as osc
        osc._load_scanner_config()
        assert osc.SCANNER_ENABLED is True
        assert osc.SELF_MAX_ITEMS == 3
        assert osc.USER_MAX_ITEMS == 2
        assert osc.USER_SCAN_ENABLED is False
        assert osc.LLM_ENABLED is True

    def test_scanner_env_overrides(self, tmp_path, monkeypatch):
        """Env vars override scanner file values."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        monkeypatch.setenv("SPARK_OPPORTUNITY_SCANNER", "0")
        monkeypatch.setenv("SPARK_OPPORTUNITY_SELF_MAX", "10")
        monkeypatch.setenv("SPARK_OPPORTUNITY_USER_SCAN", "1")
        monkeypatch.setenv("SPARK_OPPORTUNITY_LLM_ENABLED", "false")
        import lib.opportunity_scanner as osc
        osc._load_scanner_config()
        assert osc.SCANNER_ENABLED is False
        assert osc.SELF_MAX_ITEMS == 10
        assert osc.USER_SCAN_ENABLED is True
        assert osc.LLM_ENABLED is False

    def test_scanner_file_values(self, tmp_path, monkeypatch):
        """Scanner reads values from config file."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        spark_dir = tmp_path / ".spark"
        spark_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", spark_dir / "tuneables.json")
        for var in ("SPARK_OPPORTUNITY_SCANNER", "SPARK_OPPORTUNITY_SELF_MAX",
                     "SPARK_OPPORTUNITY_LLM_TIMEOUT_S", "SPARK_OPPORTUNITY_DECISION_LOOKBACK",
                     "SPARK_OPPORTUNITY_DISMISS_TTL_S"):
            monkeypatch.delenv(var, raising=False)
        _make_tuneables(spark_dir, {
            "opportunity_scanner": {
                "enabled": False,
                "self_max_items": 7,
                "llm_timeout_s": 5.0,
                "decision_lookback": 200,
                "dismiss_ttl_s": 86400.0,
            }
        })
        import lib.opportunity_scanner as osc
        osc._load_scanner_config()
        assert osc.SCANNER_ENABLED is False
        assert osc.SELF_MAX_ITEMS == 7
        assert osc.LLM_TIMEOUT_S == 5.0
        assert osc._DECISION_LOOKBACK == 200
        assert osc._DISMISS_TTL_S == 86400.0


# ---------------------------------------------------------------------------
# prediction — budget
# ---------------------------------------------------------------------------

class TestPredictionBudgetConfig:

    def test_budget_defaults(self, tmp_path, monkeypatch):
        """Budget config returns defaults when no env/file set."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        for var in ("SPARK_PREDICTION_TOTAL_BUDGET", "SPARK_PREDICTION_DEFAULT_SOURCE_BUDGET",
                     "SPARK_PREDICTION_SOURCE_BUDGETS"):
            monkeypatch.delenv(var, raising=False)
        from lib.prediction_loop import _load_prediction_budget_config
        total, default_src, budgets = _load_prediction_budget_config()
        assert total == 50
        assert default_src == 30
        assert "chip_merge" in budgets

    def test_budget_env_overrides(self, tmp_path, monkeypatch):
        """Env vars override prediction budget values."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        monkeypatch.setenv("SPARK_PREDICTION_TOTAL_BUDGET", "100")
        monkeypatch.setenv("SPARK_PREDICTION_DEFAULT_SOURCE_BUDGET", "50")
        monkeypatch.setenv("SPARK_PREDICTION_SOURCE_BUDGETS", "chip_merge=120,sync_context=80")
        from lib.prediction_loop import _load_prediction_budget_config
        total, default_src, budgets = _load_prediction_budget_config()
        assert total == 100
        assert default_src == 50
        assert budgets["chip_merge"] == 120
        assert budgets["sync_context"] == 80

    def test_budget_file_values(self, tmp_path, monkeypatch):
        """Prediction budget reads from config file."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        spark_dir = tmp_path / ".spark"
        spark_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", spark_dir / "tuneables.json")
        for var in ("SPARK_PREDICTION_TOTAL_BUDGET", "SPARK_PREDICTION_DEFAULT_SOURCE_BUDGET",
                     "SPARK_PREDICTION_SOURCE_BUDGETS"):
            monkeypatch.delenv(var, raising=False)
        _make_tuneables(spark_dir, {
            "prediction": {
                "total_budget": 200,
                "default_source_budget": 60,
            }
        })
        from lib.prediction_loop import _load_prediction_budget_config
        total, default_src, budgets = _load_prediction_budget_config()
        assert total == 200
        assert default_src == 60


# ---------------------------------------------------------------------------
# prediction — auto-link
# ---------------------------------------------------------------------------

class TestPredictionAutoLinkConfig:

    def test_autolink_defaults(self, tmp_path, monkeypatch):
        """Auto-link config returns defaults when no env/file set."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        for var in ("SPARK_PREDICTION_AUTO_LINK", "SPARK_PREDICTION_AUTO_LINK_INTERVAL_S",
                     "SPARK_PREDICTION_AUTO_LINK_LIMIT", "SPARK_PREDICTION_AUTO_LINK_MIN_SIM"):
            monkeypatch.delenv(var, raising=False)
        from lib.prediction_loop import _load_auto_link_config
        enabled, interval_s, limit, min_sim = _load_auto_link_config()
        assert enabled is True
        assert interval_s == 60.0
        assert limit == 200
        assert min_sim == pytest.approx(0.20)

    def test_autolink_env_overrides(self, tmp_path, monkeypatch):
        """Env vars override auto-link values."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", tmp_path / ".spark" / "tuneables.json")
        monkeypatch.setenv("SPARK_PREDICTION_AUTO_LINK", "0")
        monkeypatch.setenv("SPARK_PREDICTION_AUTO_LINK_INTERVAL_S", "120")
        monkeypatch.setenv("SPARK_PREDICTION_AUTO_LINK_LIMIT", "500")
        monkeypatch.setenv("SPARK_PREDICTION_AUTO_LINK_MIN_SIM", "0.5")
        from lib.prediction_loop import _load_auto_link_config
        enabled, interval_s, limit, min_sim = _load_auto_link_config()
        assert enabled is False
        assert interval_s == 120.0
        assert limit == 500
        assert min_sim == pytest.approx(0.5)

    def test_autolink_file_values(self, tmp_path, monkeypatch):
        """Auto-link reads from config file."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import lib.config_authority as ca
        spark_dir = tmp_path / ".spark"
        spark_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(ca, "DEFAULT_RUNTIME_PATH", spark_dir / "tuneables.json")
        for var in ("SPARK_PREDICTION_AUTO_LINK", "SPARK_PREDICTION_AUTO_LINK_INTERVAL_S",
                     "SPARK_PREDICTION_AUTO_LINK_LIMIT", "SPARK_PREDICTION_AUTO_LINK_MIN_SIM"):
            monkeypatch.delenv(var, raising=False)
        _make_tuneables(spark_dir, {
            "prediction": {
                "auto_link_enabled": False,
                "auto_link_interval_s": 300.0,
                "auto_link_limit": 50,
                "auto_link_min_sim": 0.40,
            }
        })
        from lib.prediction_loop import _load_auto_link_config
        enabled, interval_s, limit, min_sim = _load_auto_link_config()
        assert enabled is False
        assert interval_s == 300.0
        assert limit == 50
        assert min_sim == pytest.approx(0.40)


# ---------------------------------------------------------------------------
# Schema alignment
# ---------------------------------------------------------------------------

class TestPR2SchemaAlignment:

    def test_opportunity_scanner_in_schema(self):
        """opportunity_scanner section exists in schema."""
        from lib.tuneables_schema import SCHEMA
        assert "opportunity_scanner" in SCHEMA
        osc = SCHEMA["opportunity_scanner"]
        for key in ("enabled", "self_max_items", "user_max_items", "max_history_lines",
                     "self_dedup_window_s", "self_recent_lookback", "self_category_cap",
                     "user_scan_enabled", "scan_event_limit",
                     "outcome_window_s", "outcome_lookback",
                     "promotion_min_successes", "promotion_min_effectiveness", "promotion_lookback",
                     "llm_enabled", "llm_provider", "llm_timeout_s", "llm_max_items",
                     "llm_min_context_chars", "llm_cooldown_s",
                     "decision_lookback", "dismiss_ttl_s"):
            assert key in osc, f"Missing key: {key}"

    def test_prediction_in_schema(self):
        """prediction section exists in schema."""
        from lib.tuneables_schema import SCHEMA
        assert "prediction" in SCHEMA
        pred = SCHEMA["prediction"]
        for key in ("total_budget", "default_source_budget", "source_budgets",
                     "auto_link_enabled", "auto_link_interval_s",
                     "auto_link_limit", "auto_link_min_sim"):
            assert key in pred, f"Missing key: {key}"

    def test_section_consumers_complete(self):
        """SECTION_CONSUMERS lists new consumers."""
        from lib.tuneables_schema import SECTION_CONSUMERS
        assert "opportunity_scanner" in SECTION_CONSUMERS
        assert "lib/opportunity_scanner.py" in SECTION_CONSUMERS["opportunity_scanner"]
        assert "prediction" in SECTION_CONSUMERS
        assert "lib/prediction_loop.py" in SECTION_CONSUMERS["prediction"]


# ---------------------------------------------------------------------------
# Config file alignment
# ---------------------------------------------------------------------------

class TestPR2ConfigFileAlignment:

    def test_config_has_opportunity_scanner(self):
        """config/tuneables.json has opportunity_scanner section."""
        config_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        assert "opportunity_scanner" in data
        osc = data["opportunity_scanner"]
        assert osc["enabled"] is True
        assert osc["self_max_items"] == 3
        assert osc["llm_timeout_s"] == 2.5

    def test_config_has_prediction(self):
        """config/tuneables.json has prediction section."""
        config_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        assert "prediction" in data
        pred = data["prediction"]
        assert pred["total_budget"] == 50
        assert pred["auto_link_enabled"] is True
        assert pred["auto_link_min_sim"] == 0.20
