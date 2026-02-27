"""Canary assistant: deterministic canary decision helper."""

from __future__ import annotations

from typing import Any, Dict


def canary_decide(
    metrics: Dict[str, Any],
    *,
    threshold: float = 0.8,
    context: str = "",
) -> Dict[str, Any]:
    """Decide whether to promote or rollback a canary deployment."""
    success_rate = float(metrics.get("success_rate", 0.0) or 0.0)
    _ = context
    return {
        "decision": "promote" if success_rate >= threshold else "rollback",
        "confidence": success_rate,
        "reason": f"Success rate {success_rate:.1%} {'meets' if success_rate >= threshold else 'below'} threshold {threshold:.1%}",
    }
