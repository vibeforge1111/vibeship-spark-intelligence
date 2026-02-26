import lib.advisory_orchestrator as orch


def test_route_for_session_defaults_to_alpha(monkeypatch):
    monkeypatch.delenv("SPARK_ADVISORY_ROUTE", raising=False)
    monkeypatch.delenv("SPARK_ADVISORY_ALPHA_CANARY_PERCENT", raising=False)
    assert orch.route_for_session("s1", "Read") == "alpha"


def test_route_for_session_canary_100(monkeypatch):
    monkeypatch.setenv("SPARK_ADVISORY_ROUTE", "canary")
    monkeypatch.setenv("SPARK_ADVISORY_ALPHA_CANARY_PERCENT", "100")
    assert orch.route_for_session("s1", "Read") == "alpha"


def test_route_for_session_canary_0(monkeypatch):
    monkeypatch.setenv("SPARK_ADVISORY_ROUTE", "canary")
    monkeypatch.setenv("SPARK_ADVISORY_ALPHA_CANARY_PERCENT", "0")
    assert orch.route_for_session("s1", "Read") == "engine"


def test_on_pre_tool_dispatches_alpha(monkeypatch):
    monkeypatch.setenv("SPARK_ADVISORY_ROUTE", "alpha")
    monkeypatch.setattr(orch, "_alpha_on_pre_tool", lambda *_a, **_k: "alpha_emitted")
    monkeypatch.setattr(orch, "_engine_on_pre_tool", lambda *_a, **_k: "engine_emitted")
    out = orch.on_pre_tool("s1", "Read", {}, "t1")
    assert out == "alpha_emitted"


def test_on_pre_tool_alpha_fallback_to_engine(monkeypatch):
    monkeypatch.setenv("SPARK_ADVISORY_ROUTE", "alpha")

    def _boom(*_a, **_k):
        raise RuntimeError("alpha_fail")

    monkeypatch.setattr(orch, "_alpha_on_pre_tool", _boom)
    monkeypatch.setattr(orch, "_engine_on_pre_tool", lambda *_a, **_k: "engine_emitted")
    out = orch.on_pre_tool("s1", "Read", {}, "t1")
    assert out == "engine_emitted"
