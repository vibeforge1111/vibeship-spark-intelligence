from __future__ import annotations

from lib.keepability_gate import evaluate_structural_keepability


def test_rejects_operational_chunk_telemetry() -> None:
    out = evaluate_structural_keepability("exec_command failed: Chunk ID: 344775")
    assert out["passed"] is False
    assert "operational_chunk_telemetry" in out["reasons"]


def test_rejects_conversational_question_fragments() -> None:
    out = evaluate_structural_keepability("can we now run the localhost?")
    assert out["passed"] is False
    assert "question_without_resolution" in out["reasons"]


def test_passes_actionable_transferable_statement() -> None:
    out = evaluate_structural_keepability(
        "Always validate payload schema before merge because malformed payloads break deploys."
    )
    assert out["passed"] is True
    assert out["reasons"] == []

