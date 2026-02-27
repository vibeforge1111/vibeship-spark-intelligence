"""Shared implicit-feedback loop used by advisory engine routes."""

from __future__ import annotations

from typing import Any, List, Optional

from .diagnostics import log_debug


def _llm_area_implicit_feedback_interpret(
    tool_name: str,
    success: bool,
    advice_texts: List[str],
    trace_id: Optional[str],
) -> None:
    """LLM area: extract deeper semantic feedback signals from session outcomes."""
    try:
        from .llm_area_prompts import format_prompt
        from .llm_dispatch import llm_area_call

        advice_summary = "; ".join(str(t)[:100] for t in (advice_texts or [])[:3])
        prompt = format_prompt(
            "implicit_feedback_interpret",
            tool_name=tool_name,
            success=str(success),
            advice_texts=advice_summary[:500],
        )
        result = llm_area_call("implicit_feedback_interpret", prompt, fallback="")
        if result.used_llm and result.text:
            import json as _json

            try:
                data = _json.loads(result.text)
                if isinstance(data, dict) and data.get("insight"):
                    from .cognitive_learner import CognitiveCategory, get_cognitive_learner

                    learner = get_cognitive_learner()
                    learner.add_insight(
                        CognitiveCategory.META_LEARNING,
                        str(data["insight"]),
                        context=f"implicit_feedback:{tool_name}",
                        confidence=0.6,
                        source="implicit_feedback_interpret",
                    )
            except (ValueError, TypeError):
                pass
    except Exception:
        pass


def record_implicit_feedback(
    state: Any,
    tool_name: str,
    success: bool,
    trace_id: Optional[str],
) -> None:
    """Record implicit advisory feedback from post-tool outcomes."""
    try:
        from .advisor import get_advisor

        advisor = get_advisor()
        recent = advisor._get_recent_advice_entry(
            tool_name,
            trace_id=trace_id,
            allow_task_fallback=False,
        )
        if not recent or not recent.get("advice_ids"):
            return
        recent_trace_id = str(recent.get("trace_id") or "").strip()
        feedback_trace_id = recent_trace_id or str(trace_id or "").strip() or None

        shown_ids = set(state.shown_advice_ids.keys()) if isinstance(state.shown_advice_ids, dict) else set(state.shown_advice_ids or [])
        matching_ids = [aid for aid in recent.get("advice_ids", []) if aid in shown_ids]
        if not matching_ids:
            return

        try:
            from .implicit_outcome_tracker import get_implicit_tracker

            tracker = get_implicit_tracker()
            tracker.record_advice(
                tool_name=tool_name,
                advice_texts=[str(x or "").strip() for x in (recent.get("advice_texts") or []) if str(x or "").strip()],
                advice_sources=(recent.get("sources") or [])[:5],
                trace_id=feedback_trace_id,
            )
        except Exception:
            tracker = None

        for aid in matching_ids[:3]:
            advisor.report_outcome(
                aid,
                was_followed=True,
                was_helpful=success,
                notes=f"implicit_feedback:{'success' if success else 'failure'}:{tool_name}",
                trace_id=feedback_trace_id,
            )
        if tracker:
            tracker.record_outcome(
                tool_name=tool_name,
                success=success,
                trace_id=feedback_trace_id,
            )

        _llm_area_implicit_feedback_interpret(
            tool_name=tool_name,
            success=success,
            advice_texts=recent.get("advice_texts") or [],
            trace_id=feedback_trace_id,
        )

        log_debug(
            "advisory_feedback",
            f"Implicit feedback: {len(matching_ids)} items, {'positive' if success else 'negative'} for {tool_name}",
            None,
        )
    except Exception as exc:
        log_debug("advisory_feedback", "implicit feedback failed", exc)
