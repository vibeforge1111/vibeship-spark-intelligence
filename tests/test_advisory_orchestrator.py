import lib.advisory_orchestrator as orch
import pytest


def test_get_route_status_is_alpha_only():
    status = orch.get_route_status()
    assert status["mode"] == "alpha"
    assert "decision_log" in status


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
