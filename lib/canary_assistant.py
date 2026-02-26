"""Canary assistant: LLM-assisted deployment canary decision maker.

Helps decide whether to promote or rollback canary deployments
based on system health metrics and evolution outcomes.
Uses the llm_areas `canary_decide` hook (opt-in, disabled by default).
"""

from __future__ import annotations

from typing import Any, Dict


def canary_decide(
    metrics: Dict[str, Any],
    *,
    threshold: float = 0.8,
    context: str = "",
) -> Dict[str, Any]:
    """Decide whether to promote or rollback a canary deployment.

    When the LLM area is disabled (default), returns a simple threshold-based decision.

    Args:
        metrics: Dict with health metrics (success_rate, error_rate, latency_p50, etc.)
        threshold: Minimum success_rate to promote (default 0.8).
        context: Optional context about what changed.

    Returns:
        Dict with keys: decision ("promote"|"rollback"|"hold"), confidence, reason
    """
    success_rate = float(metrics.get("success_rate", 0.0) or 0.0)

    # Default heuristic decision
    default = {
        "decision": "promote" if success_rate >= threshold else "rollback",
        "confidence": success_rate,
        "reason": f"Success rate {success_rate:.1%} {'meets' if success_rate >= threshold else 'below'} threshold {threshold:.1%}",
    }

    try:
        import json

        from .llm_area_prompts import format_prompt
        from .llm_dispatch import llm_area_call

        prompt = format_prompt(
            "canary_decide",
            metrics=str(metrics),
            threshold=str(threshold),
            context=context[:300],
        )
        result = llm_area_call("canary_decide", prompt, fallback="")
        if result.used_llm and result.text:
            try:
                data = json.loads(result.text)
                if isinstance(data, dict) and data.get("decision"):
                    return {
                        "decision": str(data["decision"]),
                        "confidence": float(data.get("confidence", success_rate)),
                        "reason": str(data.get("reason", "")),
                        "llm_assisted": True,
                    }
            except (ValueError, TypeError):
                pass
        return default
    except Exception:
        return default
