"""
Deterministic intent taxonomy mapper for advisory routing.

Phase 1 scope:
- Stable intent families (no free-form drift)
- Deterministic task-plane mapping
- Session context key helper for packet lookups
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Tuple


INTENT_KEYWORDS: Dict[str, List[str]] = {
    "auth_security": [
        "auth", "jwt", "token", "secret", "credential", "oauth", "permission",
        "secure", "security", "redact", "sanitize",
    ],
    "deployment_ops": [
        "deploy", "release", "ship", "prod", "production", "rollback",
        "migration", "infra", "docker", "kubernetes", "ci", "cd",
    ],
    "testing_validation": [
        "test", "pytest", "unit test", "integration test", "validate",
        "assert", "coverage", "regression",
    ],
    "schema_contracts": [
        "schema", "contract", "interface", "api", "payload", "json",
        "protobuf", "migration",
    ],
    "performance_latency": [
        "latency", "performance", "slow", "optimize", "throughput",
        "budget", "timeout", "p95", "cache",
    ],
    "tool_reliability": [
        "error", "failing", "failed", "flake", "retry", "debug",
        "crash", "bug", "stability",
    ],
    "knowledge_alignment": [
        "document", "docs", "guideline", "knowledge", "memory",
        "alignment", "consistency", "playbook",
    ],
    "team_coordination": [
        "team", "handoff", "owner", "coordination", "delegate", "staffing",
        "manager", "sync", "collaboration",
    ],
    "orchestration_execution": [
        "orchestrate", "workflow", "pipeline", "dependency", "sequence",
        "scheduler", "queue", "milestone",
    ],
    "stakeholder_alignment": [
        "stakeholder", "customer", "roadmap", "priority", "expectation",
        "status update", "reporting",
    ],
    "research_decision_support": [
        "research", "evaluate", "compare", "benchmark", "analysis",
        "tradeoff", "decision", "option",
    ],
}

TASK_PLANE_BY_INTENT = {
    "auth_security": "build_delivery",
    "deployment_ops": "build_delivery",
    "testing_validation": "build_delivery",
    "schema_contracts": "build_delivery",
    "performance_latency": "build_delivery",
    "tool_reliability": "build_delivery",
    "knowledge_alignment": "build_delivery",
    "team_coordination": "team_management",
    "orchestration_execution": "orchestration_execution",
    "stakeholder_alignment": "team_management",
    "research_decision_support": "research_decision",
    "emergent_other": "build_delivery",
}

TOOL_INTENT_HINTS = {
    "Edit": "tool_reliability",
    "Write": "tool_reliability",
    "Bash": "orchestration_execution",
    "Read": "knowledge_alignment",
    "Grep": "knowledge_alignment",
    "Glob": "knowledge_alignment",
    "WebSearch": "research_decision_support",
    "WebFetch": "research_decision_support",
}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _match_count(text: str, keywords: List[str]) -> int:
    count = 0
    for kw in keywords:
        token = kw.lower().strip()
        if not token:
            continue
        if token in text:
            count += 1
    return count


def _rank_intents(text: str, tool_name: str) -> List[Tuple[str, int]]:
    ranked: List[Tuple[str, int]] = []
    for intent, keywords in INTENT_KEYWORDS.items():
        score = _match_count(text, keywords)
        ranked.append((intent, score))

    tool_hint = TOOL_INTENT_HINTS.get((tool_name or "").strip(), "")
    if tool_hint:
        ranked = [
            (intent, score + (1 if intent == tool_hint else 0))
            for intent, score in ranked
        ]

    ranked.sort(key=lambda pair: (pair[1], pair[0]), reverse=True)
    return ranked


def _confidence_from_score(score: int) -> float:
    if score <= 0:
        return 0.2
    return min(0.95, 0.3 + (0.12 * float(score)))


def map_intent(prompt_text: str, tool_name: str = "") -> Dict[str, Any]:
    """
    Deterministically map free text into fixed intent family + planes.
    """
    text = _normalize_text(prompt_text)
    ranked = _rank_intents(text, tool_name)
    best_intent, best_score = ranked[0] if ranked else ("emergent_other", 0)
    if best_score <= 0:
        best_intent = "emergent_other"

    families = []
    for intent, score in ranked[:3]:
        if score <= 0:
            continue
        families.append(
            {
                "intent_family": intent,
                "score": score,
                "confidence": round(_confidence_from_score(score), 3),
                "task_plane": TASK_PLANE_BY_INTENT.get(intent, "build_delivery"),
            }
        )

    if not families:
        families = [
            {
                "intent_family": "emergent_other",
                "score": 0,
                "confidence": 0.2,
                "task_plane": "build_delivery",
            }
        ]

    plane_scores: Dict[str, int] = {}
    for row in families:
        plane = str(row["task_plane"])
        plane_scores[plane] = plane_scores.get(plane, 0) + int(row["score"])

    sorted_planes = sorted(plane_scores.items(), key=lambda x: (x[1], x[0]), reverse=True)
    top_planes = []
    for plane, score in sorted_planes[:2]:
        top_planes.append(
            {
                "task_plane": plane,
                "confidence": round(_confidence_from_score(score), 3),
            }
        )

    primary_plane = top_planes[0]["task_plane"] if top_planes else "build_delivery"
    best_conf = round(_confidence_from_score(best_score), 3)

    reason = "keyword_match" if best_score > 0 else "fallback"
    return {
        "intent_family": best_intent,
        "confidence": best_conf,
        "reason": reason,
        "task_plane": primary_plane,
        "task_planes": top_planes or [{"task_plane": "build_delivery", "confidence": 0.2}],
        "candidates": families,
    }


def map_intent_to_task_plane(intent_family: str) -> str:
    return TASK_PLANE_BY_INTENT.get((intent_family or "").strip(), "build_delivery")


def build_session_context_key(
    *,
    task_phase: str,
    intent_family: str,
    tool_name: str,
    recent_tools: List[str],
) -> str:
    """
    Stable-ish volatile context signature for packet keying.
    """
    phase = (task_phase or "exploration").strip()
    intent = (intent_family or "emergent_other").strip()
    tool = (tool_name or "*").strip()
    recent = ",".join((recent_tools or [])[-5:])
    raw = f"{phase}|{intent}|{tool}|{recent}"
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:12]

