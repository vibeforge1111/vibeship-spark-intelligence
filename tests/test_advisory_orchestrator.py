import lib.advisory_orchestrator as orch
import lib.advisory_engine_alpha as alpha_engine


def test_get_route_status_is_alpha_only():
    status = orch.get_route_status()
    assert status["mode"] == "alpha"
    assert "decision_log" in status


def test_orchestrator_exports_alpha_entrypoints():
    assert orch.on_pre_tool is alpha_engine.on_pre_tool
    assert orch.on_post_tool is alpha_engine.on_post_tool
    assert orch.on_user_prompt is alpha_engine.on_user_prompt


def test_orchestrator_status_log_points_to_alpha_log():
    status = orch.get_route_status()
    assert str(status.get("decision_log") or "").endswith("advisory_engine_alpha.jsonl")
