"""Tests for lib/cognitive_signals.py — domain detection and pattern matching."""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from lib.cognitive_signals import (
    COGNITIVE_PATTERNS,
    DOMAIN_TRIGGERS,
    detect_domain,
)


# ---------------------------------------------------------------------------
# DOMAIN_TRIGGERS – structure tests
# ---------------------------------------------------------------------------

def test_domain_triggers_is_dict():
    assert isinstance(DOMAIN_TRIGGERS, dict)


def test_domain_triggers_not_empty():
    assert len(DOMAIN_TRIGGERS) > 0


def test_domain_triggers_has_expected_domains():
    expected = {"game_dev", "fintech", "marketing", "product", "architecture", "debugging"}
    assert expected.issubset(set(DOMAIN_TRIGGERS.keys()))


def test_domain_triggers_values_are_lists():
    for domain, triggers in DOMAIN_TRIGGERS.items():
        assert isinstance(triggers, list), f"{domain} triggers should be a list"


def test_domain_triggers_lists_not_empty():
    for domain, triggers in DOMAIN_TRIGGERS.items():
        assert len(triggers) > 0, f"{domain} triggers list should not be empty"


def test_domain_triggers_values_are_strings():
    for domain, triggers in DOMAIN_TRIGGERS.items():
        for t in triggers:
            assert isinstance(t, str), f"{domain} trigger {t!r} should be a string"


def test_game_dev_has_player_trigger():
    assert "player" in DOMAIN_TRIGGERS["game_dev"]


def test_fintech_has_payment_trigger():
    assert "payment" in DOMAIN_TRIGGERS["fintech"]


def test_marketing_has_campaign_trigger():
    assert "campaign" in DOMAIN_TRIGGERS["marketing"]


def test_debugging_has_error_trigger():
    assert "error" in DOMAIN_TRIGGERS["debugging"]


# ---------------------------------------------------------------------------
# COGNITIVE_PATTERNS – structure tests
# ---------------------------------------------------------------------------

def test_cognitive_patterns_is_dict():
    assert isinstance(COGNITIVE_PATTERNS, dict)


def test_cognitive_patterns_has_expected_keys():
    expected = {"remember", "preference", "decision", "correction", "reasoning"}
    assert expected.issubset(set(COGNITIVE_PATTERNS.keys()))


def test_cognitive_patterns_values_are_lists():
    for cat, patterns in COGNITIVE_PATTERNS.items():
        assert isinstance(patterns, list)


def test_cognitive_patterns_are_valid_regex():
    for cat, patterns in COGNITIVE_PATTERNS.items():
        for p in patterns:
            re.compile(p)  # should not raise


# ---------------------------------------------------------------------------
# detect_domain – returns None cases
# ---------------------------------------------------------------------------

def test_detect_domain_empty_string_returns_none():
    assert detect_domain("") is None


def test_detect_domain_no_triggers_returns_none():
    assert detect_domain("xyzzyx gibberish nonsense") is None


# ---------------------------------------------------------------------------
# detect_domain – correct domain detection
# ---------------------------------------------------------------------------

def test_detect_domain_game_dev():
    text = "The player spawns with full health, dealing damage on collision"
    result = detect_domain(text)
    assert result == "game_dev"


def test_detect_domain_fintech():
    text = "Payment processing requires KYC and AML compliance for all transactions"
    result = detect_domain(text)
    assert result == "fintech"


def test_detect_domain_marketing():
    text = "The campaign conversion rate dropped, affecting our audience segmentation ROI"
    result = detect_domain(text)
    assert result == "marketing"


def test_detect_domain_debugging():
    text = "Got a stacktrace and crash. Need to reproduce the error and find root cause"
    result = detect_domain(text)
    assert result == "debugging"


def test_detect_domain_architecture():
    text = "We need to refactor this monolith into microservices and improve scalability"
    result = detect_domain(text)
    assert result == "architecture"


def test_detect_domain_product():
    text = "The sprint backlog has user stories for the MVP feature launch"
    result = detect_domain(text)
    assert result == "product"


def test_detect_domain_ui_ux():
    text = "The component needs better accessibility and responsive layout for mobile"
    result = detect_domain(text)
    assert result == "ui_ux"


def test_detect_domain_returns_string():
    result = detect_domain("player spawn game collision enemy")
    assert isinstance(result, str)


def test_detect_domain_case_insensitive():
    result_lower = detect_domain("payment transaction compliance")
    result_upper = detect_domain("PAYMENT TRANSACTION COMPLIANCE")
    assert result_lower == result_upper == "fintech"


def test_detect_domain_returns_max_scoring():
    # Strong fintech signal vs weak game_dev
    text = ("payment transaction compliance risk audit kyc aml pci ledger "
            "settlement fraud reconciliation player")
    result = detect_domain(text)
    assert result == "fintech"


def test_detect_domain_orchestration():
    text = "The workflow pipeline has parallel tasks in a DAG with scheduler"
    result = detect_domain(text)
    assert result == "orchestration"


def test_detect_domain_team_management():
    text = "We need a postmortem after the incident; deploy was blocked by the PR merge conflict"
    result = detect_domain(text)
    assert result == "team_management"


def test_detect_domain_single_trigger():
    result = detect_domain("payment transfer request")
    assert result == "fintech"


def test_detect_domain_agent_coordination():
    text = "The agent uses RAG with memory and retrieval for chain-of-thought reasoning"
    result = detect_domain(text)
    assert result == "agent_coordination"


def test_detect_domain_mixed_domains_picks_one():
    text = "player payment campaign user error"
    result = detect_domain(text)
    assert result is None or isinstance(result, str)


def test_detect_domain_very_long_text():
    text = " ".join(["payment", "transaction", "compliance"] * 100)
    result = detect_domain(text)
    assert result == "fintech"


def test_detect_domain_returns_none_for_whitespace_only():
    assert detect_domain("   ") is None


# ---------------------------------------------------------------------------
# extract_cognitive_signals – smoke tests (short-circuit paths only)
# ---------------------------------------------------------------------------

def test_extract_signals_short_text_returns_early():
    """Texts shorter than 10 chars should return immediately."""
    from lib.cognitive_signals import extract_cognitive_signals
    result = extract_cognitive_signals("hi", "sess-1")
    assert result is None


def test_extract_signals_pipeline_test_returns_early():
    from lib.cognitive_signals import extract_cognitive_signals
    result = extract_cognitive_signals("[PIPELINE_TEST] long enough text here for the guard", "sess-1")
    assert result is None


def test_extract_signals_empty_text_returns_early():
    from lib.cognitive_signals import extract_cognitive_signals
    result = extract_cognitive_signals("", "sess-1")
    assert result is None
