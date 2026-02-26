"""Central LLM dispatch for all configurable LLM-assisted areas.

Every area in the system (30 total) calls through this module.
Each area is individually enable/disable with its own provider,
timeout, and max output length — all configured in tuneables.json
under the ``llm_areas`` section.

Usage::

    from lib.llm_dispatch import llm_area_call

    result = llm_area_call("archive_rewrite", prompt, fallback=original_text)
    if result.used_llm:
        improved = result.text
    else:
        improved = result.text  # fallback returned unchanged
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config_authority import resolve_section
from .diagnostics import log_debug

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LLMAreaResult:
    """Outcome of an LLM area call."""

    text: str
    used_llm: bool
    provider: str
    latency_ms: float
    area_id: str


# ---------------------------------------------------------------------------
# Area registry — canonical list of all 30 area IDs
# ---------------------------------------------------------------------------

LEARNING_AREAS = (
    "archive_rewrite",
    "archive_rescue",
    "system28_reformulate",
    "conflict_resolve",
    "evidence_compress",
    "novelty_score",
    "missed_signal_detect",
    "retrieval_rewrite",
    "retrieval_explain",
    "generic_demotion",
    "meta_ralph_remediate",
    "actionability_boost",
    "specificity_augment",
    "reasoning_patch",
    "unsuppression_score",
    "soft_promotion_triage",
    "outcome_link_reconstruct",
    "implicit_feedback_interpret",
    "curriculum_gap_summarize",
    "policy_autotuner_recommend",
)

ARCHITECTURE_AREAS = (
    "suppression_triage",
    "dedupe_optimize",
    "packet_rerank",
    "operator_now_synth",
    "drift_diagnose",
    "dead_widget_plan",
    "error_translate",
    "config_advise",
    "canary_decide",
    "canvas_enrich",
)

ALL_AREAS = LEARNING_AREAS + ARCHITECTURE_AREAS

# ---------------------------------------------------------------------------
# Default config per area (provider + timeout + max_chars)
# All areas default to enabled=False (opt-in)
# ---------------------------------------------------------------------------

_AREA_DEFAULTS: Dict[str, Dict[str, Any]] = {
    # --- Learning system ---
    "archive_rewrite":              {"provider": "minimax",   "timeout_s": 6.0,  "max_chars": 300},
    "archive_rescue":               {"provider": "minimax",   "timeout_s": 8.0,  "max_chars": 400},
    "system28_reformulate":         {"provider": "minimax",   "timeout_s": 6.0,  "max_chars": 300},
    "conflict_resolve":             {"provider": "minimax",   "timeout_s": 10.0, "max_chars": 500},
    "evidence_compress":            {"provider": "minimax",   "timeout_s": 6.0,  "max_chars": 300},
    "novelty_score":                {"provider": "minimax",   "timeout_s": 4.0,  "max_chars": 100},
    "missed_signal_detect":         {"provider": "minimax",   "timeout_s": 8.0,  "max_chars": 400},
    "retrieval_rewrite":            {"provider": "minimax",   "timeout_s": 4.0,  "max_chars": 200},
    "retrieval_explain":            {"provider": "minimax",   "timeout_s": 4.0,  "max_chars": 200},
    "generic_demotion":             {"provider": "minimax",   "timeout_s": 4.0,  "max_chars": 100},
    "meta_ralph_remediate":         {"provider": "minimax",   "timeout_s": 8.0,  "max_chars": 400},
    "actionability_boost":          {"provider": "minimax",   "timeout_s": 6.0,  "max_chars": 300},
    "specificity_augment":          {"provider": "minimax",   "timeout_s": 6.0,  "max_chars": 300},
    "reasoning_patch":              {"provider": "minimax",   "timeout_s": 8.0,  "max_chars": 400},
    "unsuppression_score":          {"provider": "minimax",   "timeout_s": 6.0,  "max_chars": 200},
    "soft_promotion_triage":        {"provider": "minimax",   "timeout_s": 8.0,  "max_chars": 400},
    "outcome_link_reconstruct":     {"provider": "minimax",   "timeout_s": 8.0,  "max_chars": 400},
    "implicit_feedback_interpret":  {"provider": "minimax",   "timeout_s": 8.0,  "max_chars": 400},
    "curriculum_gap_summarize":     {"provider": "minimax",   "timeout_s": 10.0, "max_chars": 600},
    "policy_autotuner_recommend":   {"provider": "minimax",   "timeout_s": 10.0, "max_chars": 600},
    # --- Architecture ---
    "suppression_triage":           {"provider": "minimax",   "timeout_s": 6.0,  "max_chars": 200},
    "dedupe_optimize":              {"provider": "minimax",   "timeout_s": 8.0,  "max_chars": 400},
    "packet_rerank":                {"provider": "minimax",   "timeout_s": 4.0,  "max_chars": 200},
    "operator_now_synth":           {"provider": "minimax",   "timeout_s": 10.0, "max_chars": 600},
    "drift_diagnose":               {"provider": "minimax",   "timeout_s": 10.0, "max_chars": 500},
    "dead_widget_plan":             {"provider": "minimax",   "timeout_s": 8.0,  "max_chars": 400},
    "error_translate":              {"provider": "minimax",   "timeout_s": 6.0,  "max_chars": 300},
    "config_advise":                {"provider": "minimax",   "timeout_s": 8.0,  "max_chars": 400},
    "canary_decide":                {"provider": "minimax",   "timeout_s": 10.0, "max_chars": 400},
    "canvas_enrich":                {"provider": "minimax",   "timeout_s": 8.0,  "max_chars": 400},
}

_VALID_PROVIDERS = {"auto", "minimax", "ollama", "gemini", "openai", "anthropic", "claude"}


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

def _load_area_config(area_id: str) -> Dict[str, Any]:
    """Load config for a single area from the ``llm_areas`` tuneable section."""
    try:
        section = resolve_section("llm_areas").data
    except Exception:
        section = {}
    if not isinstance(section, dict):
        section = {}

    defaults = _AREA_DEFAULTS.get(area_id, {"provider": "minimax", "timeout_s": 6.0, "max_chars": 300})

    enabled = section.get(f"{area_id}_enabled", False)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
    else:
        enabled = bool(enabled)

    provider = str(section.get(f"{area_id}_provider", defaults["provider"]) or "").strip().lower()
    if provider not in _VALID_PROVIDERS:
        provider = defaults["provider"]

    try:
        timeout_s = max(0.5, min(120.0, float(section.get(f"{area_id}_timeout_s", defaults["timeout_s"]))))
    except (ValueError, TypeError):
        timeout_s = defaults["timeout_s"]

    try:
        max_chars = max(50, min(5000, int(section.get(f"{area_id}_max_chars", defaults["max_chars"]))))
    except (ValueError, TypeError):
        max_chars = defaults["max_chars"]

    return {
        "enabled": enabled,
        "provider": provider,
        "timeout_s": timeout_s,
        "max_chars": max_chars,
    }


def get_area_config(area_id: str) -> Dict[str, Any]:
    """Public accessor for area config (used by tests and observatory)."""
    if area_id not in ALL_AREAS:
        return {"enabled": False, "provider": "minimax", "timeout_s": 6.0, "max_chars": 300}
    return _load_area_config(area_id)


def get_all_area_configs() -> Dict[str, Dict[str, Any]]:
    """Return config for every registered area."""
    return {area_id: _load_area_config(area_id) for area_id in ALL_AREAS}


# ---------------------------------------------------------------------------
# Provider dispatch (delegates to advisory_synthesizer._query_provider)
# ---------------------------------------------------------------------------

_timeout_lock = __import__("threading").Lock()


def _dispatch_provider(provider: str, prompt: str, timeout_s: float) -> Optional[str]:
    """Call the LLM provider. Wraps advisory_synthesizer._query_provider.

    Uses a lock to protect the module-level AI_TIMEOUT_S mutation so
    concurrent calls from different threads don't clobber each other's
    timeout.
    """
    try:
        # "claude" provider uses ask_claude via CLI — has its own timeout param
        if provider == "claude":
            from .llm import ask_claude
            return ask_claude(prompt, timeout_s=int(timeout_s))

        from .advisory_synthesizer import _query_provider
        import lib.advisory_synthesizer as _synth_mod

        with _timeout_lock:
            original_timeout = _synth_mod.AI_TIMEOUT_S
            _synth_mod.AI_TIMEOUT_S = timeout_s
            try:
                result = _query_provider(provider, prompt)
                return result
            finally:
                _synth_mod.AI_TIMEOUT_S = original_timeout
    except Exception as exc:
        log_debug("llm_dispatch", f"provider dispatch failed: {provider}", exc)
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def llm_area_call(
    area_id: str,
    prompt: str,
    *,
    fallback: str = "",
) -> LLMAreaResult:
    """Call an LLM for a specific area, respecting per-area config.

    Args:
        area_id: One of the 30 registered area IDs.
        prompt: The fully-formed prompt to send to the LLM.
        fallback: Text to return if the area is disabled or the LLM fails.

    Returns:
        LLMAreaResult with the response (or fallback).
    """
    if area_id not in ALL_AREAS:
        log_debug("llm_dispatch", f"unknown area_id: {area_id}", None)
        return LLMAreaResult(
            text=fallback, used_llm=False, provider="none",
            latency_ms=0.0, area_id=area_id,
        )

    cfg = _load_area_config(area_id)

    if not cfg["enabled"]:
        return LLMAreaResult(
            text=fallback, used_llm=False, provider="none",
            latency_ms=0.0, area_id=area_id,
        )

    provider = cfg["provider"]
    timeout_s = cfg["timeout_s"]
    max_chars = cfg["max_chars"]

    # Resolve "auto" to minimax (cheapest/fastest default)
    if provider == "auto":
        provider = "minimax"

    t0 = time.monotonic()
    raw = _dispatch_provider(provider, prompt, timeout_s)
    latency_ms = (time.monotonic() - t0) * 1000.0

    if raw is None or not str(raw).strip():
        log_debug("llm_dispatch", f"area={area_id} provider={provider} returned empty", None)
        return LLMAreaResult(
            text=fallback, used_llm=True, provider=provider,
            latency_ms=latency_ms, area_id=area_id,
        )

    text = str(raw).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0]

    return LLMAreaResult(
        text=text, used_llm=True, provider=provider,
        latency_ms=latency_ms, area_id=area_id,
    )


# ---------------------------------------------------------------------------
# Hot-reload registration
# ---------------------------------------------------------------------------

def _reload_llm_areas_from(_section_data) -> None:
    """Hot-reload callback for llm_areas config.

    Config is read fresh from resolve_section() on every llm_area_call(),
    so there's no cached state to invalidate. This callback exists to
    ensure the tuneables_reload framework recognises 'llm_areas' as a
    live section (used by Observatory diagnostics and the deep-dive page).
    """
    log_debug("llm_dispatch", "llm_areas config reloaded", None)


try:
    from .tuneables_reload import register_reload as _llm_areas_register
    _llm_areas_register(
        "llm_areas", _reload_llm_areas_from, label="llm_dispatch.reload_from"
    )
except Exception:
    pass
