"""
Advisory Synthesizer: Compose coherent guidance from raw advice items.

Two tiers:
- Tier 1 (No AI): Programmatic composition using templates and priority rules.
  Works immediately, zero dependencies. Always available.

- Tier 2 (AI-Enhanced): Uses local LLM (Ollama) or cloud APIs to synthesize
  multiple insights into coherent, contextual guidance. Falls back to Tier 1.

The synthesizer takes ranked, gate-filtered advice items and produces
a single coherent advisory block suitable for injection into Claude's context.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from .config_authority import env_float, env_str, resolve_section
from .diagnostics import log_debug
from .soul_upgrade import fetch_soul_state, guidance_preface, soul_kernel_pass
from .soul_metrics import record_metric

try:
    import httpx as _httpx
except Exception:
    _httpx = None

# ============= Configuration =============

SYNTH_CONFIG_FILE = Path.home() / ".spark" / "tuneables.json"
_REPO_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_repo_env_value(*keys: str) -> Optional[str]:
    """Read KEY from process env first, then fallback to repo-level .env."""
    names = [str(k or "").strip() for k in keys if str(k or "").strip()]
    if not names:
        return None

    for name in names:
        val = os.getenv(name)
        if val:
            return str(val)

    try:
        if not _REPO_ENV_FILE.exists():
            return None
        with _REPO_ENV_FILE.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key not in names:
                    continue
                value = value.strip().strip('"').strip("'")
                if value:
                    return value
    except Exception:
        return None
    return None

# LLM provider config (reuses existing Pulse patterns)
OLLAMA_API = os.getenv("SPARK_OLLAMA_API", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("SPARK_OLLAMA_MODEL", "phi4-mini")  # Default quality-first local model; override via SPARK_OLLAMA_MODEL

# Cloud fallback (only used if local unavailable and keys present)
OPENAI_API_KEY = _load_repo_env_value("OPENAI_API_KEY", "CODEX_API_KEY")
OPENAI_MODEL = os.getenv("SPARK_OPENAI_MODEL", "gpt-4o-mini")  # Cost-efficient

MINIMAX_API_KEY = _load_repo_env_value("MINIMAX_API_KEY", "SPARK_MINIMAX_API_KEY")
MINIMAX_BASE_URL = os.getenv("SPARK_MINIMAX_BASE_URL", "https://api.minimax.io/v1").rstrip("/")
MINIMAX_MODEL = os.getenv("SPARK_MINIMAX_MODEL", "MiniMax-M2.5")

ANTHROPIC_API_KEY = _load_repo_env_value("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")
ANTHROPIC_MODEL = os.getenv("SPARK_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

GEMINI_API_KEY = _load_repo_env_value("GEMINI_API_KEY", "GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("SPARK_GEMINI_MODEL", "gemini-2.0-flash")

# Synthesis mode: "auto" (try AI -> fall back to programmatic), "ai_only", "programmatic"
SYNTH_MODE = os.getenv("SPARK_SYNTH_MODE", "auto")

# Optional soul-upgrade context injection (disabled by default for safety/perf)
SOUL_UPGRADE_PROMPT_ENABLED = os.getenv("SPARK_SOUL_UPGRADE_PROMPT", "0") in {"1", "true", "yes", "on"}

# Max time for AI synthesis (fail fast - hooks must be quick)
# MiniMax M2.5 extended thinking needs 5-15s; default bumped from 3.0 to 8.0
AI_TIMEOUT_S = float(os.getenv("SPARK_SYNTH_TIMEOUT", "8.0"))
PREFERRED_PROVIDER_ENV = os.getenv("SPARK_SYNTH_PREFERRED_PROVIDER", "")

# Cache synthesized results (same inputs -> same output)
_synth_cache: Dict[str, tuple] = {}  # key -> (result, timestamp)
CACHE_TTL_S = 120
MAX_CACHE_ENTRIES = 50
PREFERRED_PROVIDER: Optional[str] = None
_CONFIG_MTIME_S: Optional[float] = None
_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def _sanitize_mode(raw: Any) -> str:
    mode = str(raw or "").strip().lower()
    return mode if mode in {"auto", "ai_only", "programmatic"} else "auto"


def _sanitize_provider(raw: Any) -> Optional[str]:
    provider = str(raw or "").strip().lower()
    if provider in {"", "auto", "none"}:
        return None
    return provider if provider in {"ollama", "gemini", "openai", "anthropic", "minimax"} else None


def _strip_thinking_tags(text: Optional[str]) -> str:
    """Strip provider reasoning blocks like <think>...</think> from output."""
    if not text:
        return ""
    return _THINK_TAG_RE.sub("", text).strip()


def _get_emotion_decision_hooks() -> Dict[str, Any]:
    """Best-effort fetch of live SparkEmotions decision hooks.

    This must never break advisory runtime flow. If emotions are unavailable,
    malformed, or throw, we return {} and continue unchanged.
    """
    try:
        from .spark_emotions import SparkEmotions

        hooks = SparkEmotions().decision_hooks()
        if not isinstance(hooks, dict):
            return {}
        strategy = hooks.get("strategy")
        if not isinstance(strategy, dict):
            return {}
        return {
            "current_emotion": str(hooks.get("current_emotion") or "").strip(),
            "response_pace": str(strategy.get("response_pace") or "").strip(),
            "verbosity": str(strategy.get("verbosity") or "").strip(),
            "tone_shape": str(strategy.get("tone_shape") or "").strip(),
            "ask_clarifying_question": bool(strategy.get("ask_clarifying_question")),
        }
    except Exception:
        return {}


def _emotion_shaping_prompt_block(hooks: Dict[str, Any]) -> str:
    """Render concise style constraints for synthesis prompts."""
    if not hooks:
        return ""
    pace = hooks.get("response_pace") or "balanced"
    verbosity = hooks.get("verbosity") or "medium"
    tone_shape = hooks.get("tone_shape") or "grounded_warm"
    current_emotion = hooks.get("current_emotion") or "steady"
    ask_q = "yes" if hooks.get("ask_clarifying_question") else "no"
    return (
        "\nLive response-shaping hints (Spark Emotions):\n"
        f"- Current emotion: {current_emotion}\n"
        f"- Pace: {pace}\n"
        f"- Verbosity: {verbosity}\n"
        f"- Tone shape: {tone_shape}\n"
        f"- Ask a clarifying question if uncertainty remains: {ask_q}\n"
    )


PREFERRED_PROVIDER = _sanitize_provider(PREFERRED_PROVIDER_ENV)


def _apply_synth_config(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    """Apply synthesizer config dict to module-level runtime settings."""
    global SYNTH_MODE, AI_TIMEOUT_S, CACHE_TTL_S, MAX_CACHE_ENTRIES, PREFERRED_PROVIDER, MINIMAX_MODEL
    applied: List[str] = []
    warnings: List[str] = []
    if not isinstance(cfg, dict):
        return {"applied": applied, "warnings": warnings}

    if "mode" in cfg:
        SYNTH_MODE = _sanitize_mode(cfg.get("mode"))
        applied.append("mode")

    if "ai_timeout_s" in cfg:
        try:
            AI_TIMEOUT_S = max(0.2, float(cfg.get("ai_timeout_s")))
            applied.append("ai_timeout_s")
        except Exception:
            warnings.append("invalid_ai_timeout_s")

    if "cache_ttl_s" in cfg:
        try:
            CACHE_TTL_S = max(0, int(cfg.get("cache_ttl_s")))
            applied.append("cache_ttl_s")
        except Exception:
            warnings.append("invalid_cache_ttl_s")

    if "max_cache_entries" in cfg:
        try:
            MAX_CACHE_ENTRIES = max(1, int(cfg.get("max_cache_entries")))
            applied.append("max_cache_entries")
            while len(_synth_cache) > MAX_CACHE_ENTRIES:
                oldest = min(_synth_cache, key=lambda k: _synth_cache[k][1])
                _synth_cache.pop(oldest, None)
        except Exception:
            warnings.append("invalid_max_cache_entries")

    if "preferred_provider" in cfg:
        PREFERRED_PROVIDER = _sanitize_provider(cfg.get("preferred_provider"))
        applied.append("preferred_provider")

    if "minimax_model" in cfg:
        model = str(cfg.get("minimax_model") or "").strip()
        if model:
            MINIMAX_MODEL = model
            applied.append("minimax_model")
        else:
            warnings.append("invalid_minimax_model")

    env_provider = _sanitize_provider(PREFERRED_PROVIDER_ENV)
    if env_provider is not None:
        PREFERRED_PROVIDER = env_provider
        applied.append("preferred_provider_env")

    return {"applied": applied, "warnings": warnings}


def apply_synth_config(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    """Public runtime hook so Pulse can hot-apply synthesizer tuneables."""
    return _apply_synth_config(cfg)


def _load_synth_config(path: Optional[Path] = None) -> dict:
    """Load synthesis config via ConfigAuthority from the 'synthesizer' section."""
    tuneables = path or SYNTH_CONFIG_FILE
    return resolve_section(
        "synthesizer",
        runtime_path=tuneables,
        env_overrides={
            "mode": env_str("SPARK_SYNTH_MODE", lower=True),
            "ai_timeout_s": env_float("SPARK_SYNTH_TIMEOUT", lo=0.2, hi=120.0),
            "preferred_provider": env_str("SPARK_SYNTH_PREFERRED_PROVIDER", lower=True),
            "minimax_model": env_str("SPARK_MINIMAX_MODEL"),
        },
    ).data

def _refresh_synth_config(force: bool = False) -> None:
    """Reload config from tuneables when file changes."""
    global _CONFIG_MTIME_S
    try:
        mtime = SYNTH_CONFIG_FILE.stat().st_mtime if SYNTH_CONFIG_FILE.exists() else None
    except Exception:
        mtime = None
    if not force and mtime == _CONFIG_MTIME_S:
        return
    _CONFIG_MTIME_S = mtime
    cfg = _load_synth_config()
    _apply_synth_config(cfg if isinstance(cfg, dict) else {})


_refresh_synth_config(force=True)


DEFAULT_DECISION_STRATEGY = {
    "response_pace": "balanced",
    "verbosity": "medium",
    "tone_shape": "grounded_warm",
    "ask_clarifying_question": False,
}


def _resolve_local_emotion_hooks() -> Optional[Dict[str, Any]]:
    """Resolve local SparkEmotions hooks (secondary fallback)."""
    try:
        from .spark_emotions import SparkEmotions

        hooks = SparkEmotions().decision_hooks()
    except Exception:
        return None

    if not isinstance(hooks, dict):
        return None

    strategy = hooks.get("strategy") if isinstance(hooks.get("strategy"), dict) else {}
    guardrails = hooks.get("guardrails") if isinstance(hooks.get("guardrails"), dict) else {}
    if not (guardrails.get("user_guided") and guardrails.get("no_autonomous_objectives")):
        return None

    merged = dict(DEFAULT_DECISION_STRATEGY)
    merged.update({k: v for k, v in strategy.items() if k in merged})
    return {
        "current_emotion": str(hooks.get("current_emotion") or "steady"),
        "strategy": merged,
        "guardrails": {
            "user_guided": True,
            "no_autonomous_objectives": True,
            "no_manipulative_affect": bool(guardrails.get("no_manipulative_affect", True)),
        },
        "source": "spark_emotions",
    }


def _resolve_bridge_strategy() -> Dict[str, Any]:
    """Resolve bridge.v1 strategy override (primary source when valid)."""
    try:
        from .consciousness_bridge import resolve_strategy

        payload = resolve_strategy()
    except Exception as exc:
        log_debug("advisory_synth", "consciousness_bridge=fallback (error)", exc)
        return {}

    if not isinstance(payload, dict):
        log_debug("advisory_synth", "consciousness_bridge=fallback (invalid_payload)")
        return {}

    source = str(payload.get("source") or "").strip()
    if source != "consciousness_bridge_v1":
        log_debug("advisory_synth", "consciousness_bridge=fallback")
        return {}

    strategy = payload.get("strategy") if isinstance(payload.get("strategy"), dict) else {}
    strategy = {k: v for k, v in strategy.items() if k in DEFAULT_DECISION_STRATEGY}
    if not strategy:
        log_debug("advisory_synth", "consciousness_bridge=fallback (empty_strategy)")
        return {}

    try:
        influence = float(payload.get("max_influence", 0.0))
    except Exception:
        influence = 0.0
    influence = max(0.0, min(0.35, influence))

    log_debug("advisory_synth", f"consciousness_bridge=ok influence={influence:.2f}")
    return {
        "strategy": strategy,
        "max_influence": influence,
        "source": "consciousness_bridge_v1",
    }


def _emotion_decision_hooks() -> Dict[str, Any]:
    """Resolve Emotions V2 decision hooks safely for runtime response shaping."""
    resolved = {
        "current_emotion": "steady",
        "strategy": dict(DEFAULT_DECISION_STRATEGY),
        "guardrails": {
            "user_guided": True,
            "no_autonomous_objectives": True,
            "no_manipulative_affect": True,
        },
        "strategy_source": "default",
        "source_chain": ["default"],
        "bridge": {"applied": False, "source": "fallback", "max_influence": 0.0},
    }
    source_chain: List[str] = []

    # Secondary source: local emotions runtime.
    local_hooks = _resolve_local_emotion_hooks()
    if local_hooks:
        resolved["current_emotion"] = str(local_hooks.get("current_emotion") or "steady")
        local_strategy = local_hooks.get("strategy") if isinstance(local_hooks.get("strategy"), dict) else {}
        resolved["strategy"].update({k: v for k, v in local_strategy.items() if k in resolved["strategy"]})
        source_chain.append("spark_emotions")

    # Primary source: bridge.v1 override when valid and safe.
    bridge_override = _resolve_bridge_strategy()
    if bridge_override:
        bridge_strategy = (
            bridge_override.get("strategy")
            if isinstance(bridge_override.get("strategy"), dict)
            else {}
        )
        resolved["strategy"].update({k: v for k, v in bridge_strategy.items() if k in resolved["strategy"]})
        source_chain.append("consciousness_bridge_v1")
        resolved["bridge"] = {
            "applied": True,
            "source": "consciousness_bridge_v1",
            "max_influence": float(bridge_override.get("max_influence", 0.0)),
        }

    if source_chain:
        resolved["source_chain"] = source_chain
        resolved["strategy_source"] = source_chain[-1]

    return resolved


# ============= Tier 1: Programmatic Synthesis =============

def synthesize_programmatic(
    advice_items: list,
    phase: str = "implementation",
    user_intent: str = "",
    tool_name: str = "",
) -> str:
    """
    Compose a coherent advisory block from advice items WITHOUT any AI.

    Uses structured templates that group insights by type and priority.
    This is the always-available baseline.
    """
    if not advice_items:
        return ""

    hooks = _emotion_decision_hooks()
    strategy = hooks.get("strategy") if isinstance(hooks.get("strategy"), dict) else {}
    verbosity = str(strategy.get("verbosity") or "medium").strip().lower()
    response_pace = str(strategy.get("response_pace") or "balanced").strip().lower()
    tone_shape = str(strategy.get("tone_shape") or "grounded_warm").strip().lower()
    ask_clarifying_question = bool(strategy.get("ask_clarifying_question"))

    sections: List[str] = []

    # Group by authority/type
    warnings = []
    notes = []

    for item in advice_items:
        authority = getattr(item, "_authority", "note")  # Set by gate
        text = getattr(item, "text", str(item))
        confidence = getattr(item, "confidence", 0.5)
        reason = getattr(item, "reason", "")
        source = getattr(item, "source", "")

        entry = {
            "text": text,
            "confidence": confidence,
            "reason": reason,
            "source": source,
        }

        if authority == "warning":
            warnings.append(entry)
        elif authority != "whisper":
            notes.append(entry)

    # Sort by confidence descending so highest-signal items surface first
    warnings.sort(key=lambda e: e["confidence"], reverse=True)
    notes.sort(key=lambda e: e["confidence"], reverse=True)

    max_warnings = 1 if verbosity == "concise" else 2
    max_notes = 1 if verbosity == "concise" else (4 if verbosity == "structured" else 3)

    if response_pace == "slow":
        max_warnings = max(1, max_warnings - 1)
        max_notes = max(1, max_notes - 1)
    elif response_pace == "lively":
        max_notes = min(5, max_notes + 1)

    tone_openers = {
        "reassuring_and_clear": "Steady path:",
        "calm_focus": "Calm focus:",
        "encouraging": "You're on the right track:",
        "grounded_warm": "Grounded take:",
    }
    if verbosity != "concise":
        opener = tone_openers.get(tone_shape)
        if opener:
            sections.append(opener)

    # Build the block
    if warnings:
        if verbosity == "concise":
            w = warnings[0]
            conf = f" ({w['confidence']:.0%})" if w["confidence"] >= 0.7 else ""
            sections.append(f"Caution: {w['text']}{conf}")
        else:
            sections.append("Cautions:")
            for w in warnings[:max_warnings]:
                conf = f" ({w['confidence']:.0%})" if w["confidence"] >= 0.7 else ""
                sections.append(f"- {w['text']}{conf}")

    if notes:
        if warnings and verbosity != "concise":
            sections.append("")
        if verbosity != "concise":
            sections.append("Relevant context:")
        for n in notes[:max_notes]:
            # Strip leading tags like [Caution], [Past Failure] for cleaner display
            text = n["text"]
            text = text.lstrip("[").split("]", 1)[-1].strip() if text.startswith("[") else text
            if verbosity == "concise":
                sections.append(text)
            else:
                # Add source hint for non-obvious provenance
                source_hint = ""
                src = n.get("source", "")
                if src and verbosity == "structured":
                    # Short provenance tag helps user gauge relevance
                    src_label = src.split(":")[-1].strip() if ":" in src else src
                    if src_label and src_label not in ("unknown", ""):
                        source_hint = f" [{src_label}]"
                sections.append(f"- {text}{source_hint}")

    if ask_clarifying_question:
        sections.append("If this doesn't match your intent, what outcome matters most for this step?")

    if not sections:
        return ""

    return "\n".join(sections)


# ============= Tier 2: AI-Enhanced Synthesis =============

def synthesize_with_ai(
    advice_items: list,
    phase: str = "implementation",
    user_intent: str = "",
    tool_name: str = "",
    provider: Optional[str] = None,
) -> Optional[str]:
    """
    Use LLM to synthesize advice into coherent contextual guidance.

    Returns None if AI is unavailable (Tier 1 fallback should be used).
    """
    if not advice_items:
        return None

    # Build the synthesis prompt
    prompt = _build_synthesis_prompt(advice_items, phase, user_intent, tool_name)

    # Try providers in order: local first, then configured cloud fallbacks.
    providers = _get_provider_chain(provider)

    for prov in providers:
        try:
            result = _strip_thinking_tags(_query_provider(prov, prompt))
            if result and len(result) > 10:
                return result
        except Exception as e:
            log_debug("advisory_synth", f"Provider {prov} failed", e)
            continue

    return None  # All providers failed


def _build_synthesis_prompt(
    advice_items: list,
    phase: str,
    user_intent: str,
    tool_name: str,
) -> str:
    """Build the prompt for AI synthesis."""
    items_text = ""
    for i, item in enumerate(advice_items, 1):
        text = getattr(item, "text", str(item))
        conf = getattr(item, "confidence", 0.5)
        source = getattr(item, "source", "unknown")
        items_text += f"  {i}. [{source}, {conf:.0%}] {text}\n"

    hooks = _emotion_decision_hooks()
    strategy = hooks.get("strategy") if isinstance(hooks.get("strategy"), dict) else {}
    guardrails = hooks.get("guardrails") if isinstance(hooks.get("guardrails"), dict) else {}
    emotion_block = (
        "\nResponse shaping strategy (Emotions V2):\n"
        f"- current_emotion: {hooks.get('current_emotion', 'steady')}\n"
        f"- response_pace: {strategy.get('response_pace', 'balanced')}\n"
        f"- verbosity: {strategy.get('verbosity', 'medium')}\n"
        f"- tone_shape: {strategy.get('tone_shape', 'grounded_warm')}\n"
        f"- ask_clarifying_question: {bool(strategy.get('ask_clarifying_question', False))}\n"
        "- safety: user_guided="
        f"{bool(guardrails.get('user_guided', True))}, "
        "no_autonomous_objectives="
        f"{bool(guardrails.get('no_autonomous_objectives', True))}\n"
    )

    soul_block = ""
    if SOUL_UPGRADE_PROMPT_ENABLED:
        try:
            soul = fetch_soul_state(session_id="default")
            soul_block = (
                "\nSoul context (v1):\n"
                f"- Guidance preface: {guidance_preface(soul) or 'Respond direct and action-first.'}\n"
                f"- Soul kernel pass: {'yes' if soul_kernel_pass(soul) else 'no'}\n"
                "- Mission anchor: serve humanity and the light through helpful, ethical, grounded intelligence.\n"
            )
        except Exception:
            soul_block = ""

    return f"""You are a concise coding advisor. Synthesize these learnings into 1-3 sentences of actionable guidance for the developer.

Current context:
- Task phase: {phase}
- Tool about to use: {tool_name}
- Developer intent: {user_intent or 'not specified'}{emotion_block}{soul_block}

Raw insights:
{items_text}
Rules:
- Be direct and specific, no filler
- If insights conflict, note the tension briefly
- Prioritize warnings and failure patterns
- Follow the Emotions V2 response shaping strategy for pace/verbosity/tone
- Never introduce autonomous goals; stay user-guided
- Max 3 sentences. If only 1 insight, 1 sentence is fine
- If ask_clarifying_question=true, end with one short clarifying question
- Do NOT say "based on past learnings" or "according to insights" - just give the guidance
- Format: plain text, no markdown headers"""


def _get_provider_chain(preferred: Optional[str] = None) -> List[str]:
    """Get ordered list of LLM providers to try."""
    chain = []
    preferred_provider = _sanitize_provider(preferred) or PREFERRED_PROVIDER
    if preferred_provider:
        chain.append(preferred_provider)

    # Local first (no cost, no latency to external API)
    if "ollama" not in chain:
        chain.append("ollama")
    # Then cloud fallbacks (by cost: cheapest first)
    if GEMINI_API_KEY and "gemini" not in chain:
        chain.append("gemini")
    if MINIMAX_API_KEY and "minimax" not in chain:
        chain.append("minimax")
    if OPENAI_API_KEY and "openai" not in chain:
        chain.append("openai")
    if ANTHROPIC_API_KEY and "anthropic" not in chain:
        chain.append("anthropic")

    return chain


def _query_provider(provider: str, prompt: str) -> Optional[str]:
    """Query a specific LLM provider. Must be fast (< AI_TIMEOUT_S)."""
    if provider == "ollama":
        return _query_ollama(prompt)
    elif provider == "openai":
        return _query_openai(prompt)
    elif provider == "minimax":
        return _query_minimax(prompt)
    elif provider == "anthropic":
        return _query_anthropic(prompt)
    elif provider == "gemini":
        return _query_gemini(prompt)
    return None


def _query_ollama(prompt: str) -> Optional[str]:
    """Query local Ollama instance via chat API.

    Uses /api/chat (not /api/generate) because Qwen3 models route all
    output to a 'thinking' field with the generate API, producing empty
    responses.  The chat API with think=False avoids this.
    """
    try:
        if _httpx is None:
            log_debug("advisory_synth", "HTTPX_MISSING_OLLAMA", None)
            return None
        with _httpx.Client(timeout=AI_TIMEOUT_S) as client:
            resp = client.post(
                f"{OLLAMA_API}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "think": False,  # Disable thinking for Qwen3 models
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 100,  # 1-3 sentences ~ 40-80 tokens
                    },
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("message", {})
                return msg.get("content", "").strip()
    except Exception as e:
        log_debug("advisory_synth", "Ollama query failed", e)
    return None


def _query_openai(prompt: str) -> Optional[str]:
    """Query OpenAI API."""
    if not OPENAI_API_KEY:
        return None
    try:
        if _httpx is None:
            log_debug("advisory_synth", "HTTPX_MISSING_OPENAI", None)
            return None
        with _httpx.Client(timeout=AI_TIMEOUT_S) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": OPENAI_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0.3,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log_debug("advisory_synth", "OpenAI query failed", e)
    return None


def _query_minimax(
    prompt: str, *, model: Optional[str] = None, timeout_s: Optional[float] = None
) -> Optional[str]:
    """Query MiniMax OpenAI-compatible API."""
    if not MINIMAX_API_KEY:
        return None
    try:
        if _httpx is None:
            log_debug("advisory_synth", "HTTPX_MISSING_MINIMAX", None)
            return None
        chosen_model = str(model).strip() if str(model or "").strip() else MINIMAX_MODEL
        try:
            timeout = float(timeout_s)
            if timeout <= 0:
                timeout = AI_TIMEOUT_S
        except Exception:
            timeout = AI_TIMEOUT_S

        with _httpx.Client(timeout=timeout) as client:
            want_json = "return only json" in str(prompt or "").strip().lower()
            resp = client.post(
                f"{MINIMAX_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {MINIMAX_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": chosen_model,
                    "messages": [{"role": "user", "content": prompt}],
                    # MiniMax M2.5 uses extended thinking that consumes ~1000 tokens
                    # before the actual response; budget must accommodate both.
                    "max_tokens": 2000 if want_json else 1500,
                    "temperature": 0.2 if want_json else 0.3,
                    **({"response_format": {"type": "json_object"}} if want_json else {}),
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        return content.strip()
    except Exception as e:
        log_debug("advisory_synth", "MiniMax query failed", e)
    return None


def _query_anthropic(prompt: str) -> Optional[str]:
    """Query Anthropic API."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        if _httpx is None:
            log_debug("advisory_synth", "HTTPX_MISSING_ANTHROPIC", None)
            return None
        with _httpx.Client(timeout=AI_TIMEOUT_S) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": ANTHROPIC_MODEL,
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("content", [])
                if content:
                    return content[0].get("text", "").strip()
    except Exception as e:
        log_debug("advisory_synth", "Anthropic query failed", e)
    return None


def _query_gemini(prompt: str) -> Optional[str]:
    """Query Google Gemini API."""
    if not GEMINI_API_KEY:
        return None
    try:
        if _httpx is None:
            log_debug("advisory_synth", "HTTPX_MISSING_GEMINI", None)
            return None
        with _httpx.Client(timeout=AI_TIMEOUT_S) as client:
            resp = client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 200,
                    },
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
    except Exception as e:
        log_debug("advisory_synth", "Gemini query failed", e)
    return None


# ============= Main Synthesis Entry Point =============

def synthesize(
    advice_items: list,
    phase: str = "implementation",
    user_intent: str = "",
    tool_name: str = "",
    force_mode: Optional[str] = None,
) -> str:
    """
    Main entry point: synthesize advice into coherent guidance.

    Respects SPARK_SYNTH_MODE:
    - "auto": Try AI first, fall back to programmatic
    - "ai_only": AI only, return empty if unavailable
    - "programmatic": Skip AI entirely (fastest, zero network)

    Args:
        advice_items: Gate-filtered advice objects
        phase: Current task phase
        user_intent: What the user is trying to do
        tool_name: Tool about to be used
        force_mode: Override SYNTH_MODE for this call

    Returns:
        Synthesized advisory text (may be empty if nothing to say)
    """
    _refresh_synth_config()

    if not advice_items:
        return ""

    mode = _sanitize_mode(force_mode) if force_mode else SYNTH_MODE

    # Check cache first
    cache_key = _make_cache_key(advice_items, phase, user_intent, tool_name)
    cached = _synth_cache.get(cache_key)
    if cached:
        result, ts = cached
        if time.time() - ts < CACHE_TTL_S:
            return result

    result = ""

    if mode == "programmatic":
        result = synthesize_programmatic(advice_items, phase, user_intent, tool_name)
    elif mode == "ai_only":
        ai_result = synthesize_with_ai(advice_items, phase, user_intent, tool_name)
        result = ai_result or ""
    else:  # "auto"
        # Try AI synthesis (fast timeout protects hook speed)
        ai_result = synthesize_with_ai(advice_items, phase, user_intent, tool_name)
        if ai_result:
            result = ai_result
        else:
            # Fall back to programmatic
            result = synthesize_programmatic(advice_items, phase, user_intent, tool_name)

    # Cache result
    if result:
        _synth_cache[cache_key] = (result, time.time())
        # Keep cache bounded
        if len(_synth_cache) > MAX_CACHE_ENTRIES:
            oldest = min(_synth_cache, key=lambda k: _synth_cache[k][1])
            _synth_cache.pop(oldest, None)

    # Soul-upgrade metrics hook (lightweight, best-effort)
    try:
        soul = fetch_soul_state(session_id="default") if SOUL_UPGRADE_PROMPT_ENABLED else None
        record_metric("advisory_synthesis", {
            "mode": mode,
            "result_nonempty": bool(result),
            "items": len(advice_items),
            "tool": tool_name or "",
            "phase": phase or "",
            "soul_enabled": bool(SOUL_UPGRADE_PROMPT_ENABLED),
            "soul_kernel_pass": bool(soul_kernel_pass(soul)) if soul else None,
        })
    except Exception:
        pass

    return result


def _make_cache_key(items: list, phase: str, intent: str, tool: str) -> str:
    """Generate cache key from inputs."""
    import hashlib
    parts = [phase, intent[:100], tool]
    for item in items[:5]:
        aid = getattr(item, "advice_id", str(item))
        parts.append(str(aid))
    payload = "|".join(parts)
    return hashlib.sha1(payload.encode("utf-8", errors="replace")).hexdigest()[:16]


# ============= AI Availability Check =============

def check_ai_available() -> Dict[str, bool]:
    """Check which AI providers are available. Useful for diagnostics."""
    available = {
        "ollama": False,
        "openai": bool(OPENAI_API_KEY),
        "minimax": bool(MINIMAX_API_KEY),
        "anthropic": bool(ANTHROPIC_API_KEY),
        "gemini": bool(GEMINI_API_KEY),
    }

    # Quick Ollama check
    try:
        if _httpx is not None:
            with _httpx.Client(timeout=1.5) as client:
                resp = client.get(f"{OLLAMA_API}/api/tags")
                available["ollama"] = resp.status_code == 200
    except Exception:
        pass

    return available


def get_synth_status() -> Dict[str, Any]:
    """Get synthesis system status for diagnostics."""
    _refresh_synth_config()
    ai = check_ai_available()
    any_ai = any(ai.values())
    return {
        "mode": SYNTH_MODE,
        "ai_timeout_s": AI_TIMEOUT_S,
        "cache_ttl_s": CACHE_TTL_S,
        "max_cache_entries": MAX_CACHE_ENTRIES,
        "preferred_provider": PREFERRED_PROVIDER or "auto",
        "httpx_available": _httpx is not None,
        "warning": "httpx_missing" if _httpx is None else None,
        "ai_available": any_ai,
        "providers": ai,
        "tier": 2 if any_ai else 1,
        "tier_label": "AI-Enhanced" if any_ai else "Programmatic",
        "cache_size": len(_synth_cache),
        "ollama_model": OLLAMA_MODEL if ai.get("ollama") else None,
        "minimax_model": MINIMAX_MODEL,
    }


def _reload_synth_from(_cfg):
    """Hot-reload callback — re-reads config through config_authority."""
    _refresh_synth_config(force=True)


try:
    from .tuneables_reload import register_reload as _synth_register

    _synth_register("synthesizer", _reload_synth_from, label="advisory_synthesizer.reload")
except Exception:
    pass

