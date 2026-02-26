"""Error translator: LLM-assisted error message translation for onboarding/doctor scripts.

Provides human-readable explanations for common Spark errors.
Uses the llm_areas `error_translate` hook (opt-in, disabled by default).
"""

from __future__ import annotations


def translate_error(error_msg: str, *, context: str = "") -> str:
    """Translate a technical error message into a human-readable explanation.

    When the LLM area is disabled (default), returns the original error message.

    Args:
        error_msg: The raw error message or traceback snippet.
        context: Optional context (e.g., which subsystem raised it).

    Returns:
        Human-readable explanation, or original error_msg if LLM is disabled/unavailable.
    """
    if not error_msg or not error_msg.strip():
        return error_msg
    try:
        from .llm_area_prompts import format_prompt
        from .llm_dispatch import llm_area_call

        prompt = format_prompt(
            "error_translate",
            error=error_msg[:500],
            context=context[:200],
        )
        result = llm_area_call("error_translate", prompt, fallback=error_msg)
        if result.used_llm and result.text:
            return result.text
        return error_msg
    except Exception:
        return error_msg


def translate_errors(errors: list, *, context: str = "") -> list:
    """Batch translate multiple error messages."""
    return [translate_error(str(e), context=context) for e in errors]
