from __future__ import annotations

from lib import runtime_intent_taxonomy as taxonomy


def test_intent_mapping_is_deterministic():
    prompt = "Harden JWT auth and redact tokens from logs."
    one = taxonomy.map_intent(prompt, tool_name="Edit")
    two = taxonomy.map_intent(prompt, tool_name="Edit")
    assert one == two
    assert one["intent_family"] == "auth_security"
    assert one["task_plane"] == "build_delivery"


def test_intent_mapping_fallback():
    result = taxonomy.map_intent("do the thing maybe", tool_name="Read")
    assert result["intent_family"] in {"knowledge_alignment", "emergent_other"}
    assert result["task_plane"] in {
        "build_delivery",
        "team_management",
        "orchestration_execution",
        "research_decision",
    }


def test_intent_mapping_returns_ranked_planes_max_two():
    prompt = "Compare benchmark options and coordinate team handoff next."
    result = taxonomy.map_intent(prompt, tool_name="WebSearch")
    planes = result["task_planes"]
    assert 1 <= len(planes) <= 2
    assert all("task_plane" in row and "confidence" in row for row in planes)


def test_session_context_key_changes_with_recent_tools():
    a = taxonomy.build_session_context_key(
        task_phase="implementation",
        intent_family="auth_security",
        tool_name="Edit",
        recent_tools=["Read", "Edit"],
    )
    b = taxonomy.build_session_context_key(
        task_phase="implementation",
        intent_family="auth_security",
        tool_name="Edit",
        recent_tools=["Read", "Bash"],
    )
    assert a != b
