"""Tests for lib/ports.py

Covers:
- _env_int: default values, valid overrides, invalid/empty env vars
- _host: None fallback and custom host
- build_url: URL format correctness
- Module-level constants: default values and env-override behaviour
"""

import importlib
import os

import pytest

import lib.ports as ports


# ---------------------------------------------------------------------------
# _env_int
# ---------------------------------------------------------------------------

def test_env_int_returns_default_when_var_missing(monkeypatch):
    monkeypatch.delenv("SPARK_TEST_PORT", raising=False)
    assert ports._env_int("SPARK_TEST_PORT", 1234) == 1234


def test_env_int_returns_default_when_var_empty(monkeypatch):
    monkeypatch.setenv("SPARK_TEST_PORT", "")
    assert ports._env_int("SPARK_TEST_PORT", 1234) == 1234


def test_env_int_parses_valid_integer(monkeypatch):
    monkeypatch.setenv("SPARK_TEST_PORT", "9999")
    assert ports._env_int("SPARK_TEST_PORT", 1234) == 9999


def test_env_int_returns_default_for_non_integer(monkeypatch):
    monkeypatch.setenv("SPARK_TEST_PORT", "not_a_number")
    assert ports._env_int("SPARK_TEST_PORT", 1234) == 1234


def test_env_int_returns_default_for_float_string(monkeypatch):
    monkeypatch.setenv("SPARK_TEST_PORT", "80.5")
    assert ports._env_int("SPARK_TEST_PORT", 1234) == 1234


def test_env_int_handles_zero(monkeypatch):
    monkeypatch.setenv("SPARK_TEST_PORT", "0")
    assert ports._env_int("SPARK_TEST_PORT", 1234) == 0


# ---------------------------------------------------------------------------
# _host
# ---------------------------------------------------------------------------

def test_host_defaults_to_localhost():
    assert ports._host(None) == "127.0.0.1"


def test_host_returns_custom_host():
    assert ports._host("0.0.0.0") == "0.0.0.0"


def test_host_returns_hostname():
    assert ports._host("myserver.local") == "myserver.local"


def test_host_empty_string_falls_back_to_localhost():
    # Empty string is falsy — should fall back to default
    assert ports._host("") == "127.0.0.1"


# ---------------------------------------------------------------------------
# build_url
# ---------------------------------------------------------------------------

def test_build_url_default_host():
    assert ports.build_url(8787) == "http://127.0.0.1:8787"


def test_build_url_custom_host():
    assert ports.build_url(8080, host="10.0.0.1") == "http://10.0.0.1:8080"


def test_build_url_none_host_uses_default():
    assert ports.build_url(9000, host=None) == "http://127.0.0.1:9000"


def test_build_url_starts_with_http():
    url = ports.build_url(1234)
    assert url.startswith("http://")


def test_build_url_contains_port():
    url = ports.build_url(5678)
    assert ":5678" in url


# ---------------------------------------------------------------------------
# Module-level default constants
# ---------------------------------------------------------------------------

def test_sparkd_default_port():
    assert ports.SPARKD_PORT == int(os.environ.get("SPARKD_PORT", 8787))


def test_dashboard_default_port():
    assert ports.DASHBOARD_PORT == int(os.environ.get("SPARK_DASHBOARD_PORT", 8585))


def test_pulse_default_port():
    assert ports.PULSE_PORT == int(os.environ.get("SPARK_PULSE_PORT", 8765))


def test_meta_ralph_default_port():
    assert ports.META_RALPH_PORT == int(os.environ.get("SPARK_META_RALPH_PORT", 8586))


def test_mind_default_port():
    assert ports.MIND_PORT == int(os.environ.get("SPARK_MIND_PORT", 8080))


# ---------------------------------------------------------------------------
# Module-level URL constants are well-formed
# ---------------------------------------------------------------------------

def test_sparkd_url_format():
    assert ports.SPARKD_URL.startswith("http://")
    assert str(ports.SPARKD_PORT) in ports.SPARKD_URL


def test_dashboard_url_format():
    assert ports.DASHBOARD_URL.startswith("http://")
    assert str(ports.DASHBOARD_PORT) in ports.DASHBOARD_URL


def test_pulse_url_format():
    assert ports.PULSE_URL.startswith("http://")
    assert str(ports.PULSE_PORT) in ports.PULSE_URL


def test_sparkd_health_url_ends_with_health():
    assert ports.SPARKD_HEALTH_URL.endswith("/health")


def test_dashboard_status_url_ends_with_health():
    assert ports.DASHBOARD_STATUS_URL.endswith("/health")


def test_pulse_status_url_ends_with_api_status():
    assert ports.PULSE_STATUS_URL.endswith("/api/status")


def test_pulse_ui_url_ends_with_slash():
    assert ports.PULSE_UI_URL.endswith("/")


def test_pulse_docs_url_ends_with_docs():
    assert ports.PULSE_DOCS_URL.endswith("/docs")


def test_meta_ralph_health_url():
    assert ports.META_RALPH_HEALTH_URL.endswith("/health")


def test_mind_health_url():
    assert ports.MIND_HEALTH_URL.endswith("/health")
