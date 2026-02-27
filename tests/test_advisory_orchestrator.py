import lib.advisory_orchestrator as orch
import pytest


def test_route_for_session_defaults_to_alpha(monkeypatch):
    monkeypatch.delenv("SPARK_ADVISORY_ROUTE", raising=False)
    assert orch.route_for_session("s1", "Read") == "alpha"


def test_route_for_session_ignores_canary_mode_and_stays_alpha(monkeypatch):
    monkeypatch.setenv("SPARK_ADVISORY_ROUTE", "canary")
    assert orch.route_for_session("s1", "Read") == "alpha"


def test_on_pre_tool_dispatches_alpha(monkeypatch):
    monkeypatch.setattr(orch, "_alpha_on_pre_tool", lambda *_a, **_k: "alpha_emitted")
    out = orch.on_pre_tool("s1", "Read", {}, "t1")
    assert out == "alpha_emitted"


def test_on_pre_tool_alpha_error_does_not_fallback_to_engine(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("alpha_fail")

    monkeypatch.setattr(orch, "_alpha_on_pre_tool", _boom)
    with pytest.raises(RuntimeError, match="alpha_fail"):
        orch.on_pre_tool("s1", "Read", {}, "t1")
