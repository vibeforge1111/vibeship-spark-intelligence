from __future__ import annotations

from lib.doctor import DoctorResult, _check_alpha_env_contract


_ALPHA_ENV_KEYS = [
    "SPARK_ADVISORY_ROUTE",
    "SPARK_ADVISORY_ALPHA_ENABLED",
    "SPARK_MEMORY_SPINE_CANONICAL",
    "SPARK_VALIDATE_AND_STORE",
    "SPARK_BRIDGE_LLM_ADVISORY_SIDECAR_ENABLED",
    "SPARK_BRIDGE_LLM_EIDOS_SIDECAR_ENABLED",
    "SPARK_EMBED_BACKEND",
]


def _clear_alpha_env(monkeypatch) -> None:
    for key in _ALPHA_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _get_contract_check(result: DoctorResult):
    for check in result.checks:
        if check.id == "alpha_env_contract":
            return check
    raise AssertionError("alpha_env_contract check not found")


def test_alpha_env_contract_pass_defaults(monkeypatch):
    _clear_alpha_env(monkeypatch)
    result = DoctorResult()
    _check_alpha_env_contract(result)
    check = _get_contract_check(result)
    assert check.status == "pass"
    assert "stable" in check.message.lower()


def test_alpha_env_contract_warns_experimental_mode(monkeypatch):
    _clear_alpha_env(monkeypatch)
    monkeypatch.setenv("SPARK_ADVISORY_ROUTE", "engine")
    monkeypatch.setenv("SPARK_BRIDGE_LLM_ADVISORY_SIDECAR_ENABLED", "1")
    monkeypatch.setenv("SPARK_EMBED_BACKEND", "tfidf")
    result = DoctorResult()
    _check_alpha_env_contract(result)
    check = _get_contract_check(result)
    assert check.status == "warn"
    assert "experimental mode" in check.message.lower()
    assert "route=engine" in check.details


def test_alpha_env_contract_fails_hard_conflicts(monkeypatch):
    _clear_alpha_env(monkeypatch)
    monkeypatch.setenv("SPARK_ADVISORY_ROUTE", "alpha")
    monkeypatch.setenv("SPARK_ADVISORY_ALPHA_ENABLED", "0")
    monkeypatch.setenv("SPARK_MEMORY_SPINE_CANONICAL", "0")
    monkeypatch.setenv("SPARK_EMBED_BACKEND", "none")
    result = DoctorResult()
    _check_alpha_env_contract(result)
    check = _get_contract_check(result)
    assert check.status == "fail"
    assert "violated" in check.message.lower()
    assert "SPARK_MEMORY_SPINE_CANONICAL=0" in check.details
    assert "SPARK_EMBED_BACKEND disables semantic retrieval" in check.details
