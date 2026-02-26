"""Distillation refinement loop for advisory readiness.

Improves low-scoring distillation statements using deterministic rewrites:
1) score raw statement
2) elevation transforms
3) structure-driven rewrite
4) component composition
5) optional runtime LLM refinement (gated/tuneable)
The best-scoring candidate is persisted with advisory quality metadata.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .distillation_transformer import transform_for_advisory
from .elevation import elevate

_TUNEABLES_FILE = Path.home() / ".spark" / "tuneables.json"
_ALLOWED_PROVIDERS = {"auto", "minimax", "ollama", "gemini", "openai", "anthropic", "claude"}
_DEFAULT_RUNTIME_REFINER_CFG: Dict[str, Any] = {
    "runtime_refiner_llm_enabled": False,
    "runtime_refiner_llm_min_unified_score": 0.45,
    "runtime_refiner_llm_timeout_s": 6.0,
    "runtime_refiner_llm_max_chars": 280,
    "runtime_refiner_llm_provider": "auto",
}


def _safe_float(value: Any, default: float, *, lo: float, hi: float) -> float:
    try:
        out = float(value)
    except Exception:
        out = float(default)
    return max(float(lo), min(float(hi), out))


def _safe_int(value: Any, default: int, *, lo: int, hi: int) -> int:
    try:
        out = int(value)
    except Exception:
        out = int(default)
    return max(int(lo), min(int(hi), out))


def _sanitize_runtime_refiner_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    raw = cfg if isinstance(cfg, dict) else {}
    provider = str(
        raw.get(
            "runtime_refiner_llm_provider",
            _DEFAULT_RUNTIME_REFINER_CFG["runtime_refiner_llm_provider"],
        )
        or ""
    ).strip().lower()
    if provider not in _ALLOWED_PROVIDERS:
        provider = str(_DEFAULT_RUNTIME_REFINER_CFG["runtime_refiner_llm_provider"])

    return {
        "runtime_refiner_llm_enabled": bool(
            raw.get(
                "runtime_refiner_llm_enabled",
                _DEFAULT_RUNTIME_REFINER_CFG["runtime_refiner_llm_enabled"],
            )
        ),
        "runtime_refiner_llm_min_unified_score": _safe_float(
            raw.get(
                "runtime_refiner_llm_min_unified_score",
                _DEFAULT_RUNTIME_REFINER_CFG["runtime_refiner_llm_min_unified_score"],
            ),
            _DEFAULT_RUNTIME_REFINER_CFG["runtime_refiner_llm_min_unified_score"],
            lo=0.0,
            hi=1.0,
        ),
        "runtime_refiner_llm_timeout_s": _safe_float(
            raw.get(
                "runtime_refiner_llm_timeout_s",
                _DEFAULT_RUNTIME_REFINER_CFG["runtime_refiner_llm_timeout_s"],
            ),
            _DEFAULT_RUNTIME_REFINER_CFG["runtime_refiner_llm_timeout_s"],
            lo=0.5,
            hi=60.0,
        ),
        "runtime_refiner_llm_max_chars": _safe_int(
            raw.get(
                "runtime_refiner_llm_max_chars",
                _DEFAULT_RUNTIME_REFINER_CFG["runtime_refiner_llm_max_chars"],
            ),
            _DEFAULT_RUNTIME_REFINER_CFG["runtime_refiner_llm_max_chars"],
            lo=80,
            hi=2000,
        ),
        "runtime_refiner_llm_provider": provider,
    }


def _load_runtime_refiner_cfg() -> Dict[str, Any]:
    try:
        from .config_authority import env_bool, env_float, env_int, env_str, resolve_section

        cfg = resolve_section(
            "eidos",
            runtime_path=_TUNEABLES_FILE,
            env_overrides={
                "runtime_refiner_llm_enabled": env_bool("SPARK_EIDOS_RUNTIME_REFINER_LLM_ENABLED"),
                "runtime_refiner_llm_min_unified_score": env_float(
                    "SPARK_EIDOS_RUNTIME_REFINER_LLM_MIN_SCORE", lo=0.0, hi=1.0
                ),
                "runtime_refiner_llm_timeout_s": env_float(
                    "SPARK_EIDOS_RUNTIME_REFINER_LLM_TIMEOUT_S", lo=0.5, hi=60.0
                ),
                "runtime_refiner_llm_max_chars": env_int(
                    "SPARK_EIDOS_RUNTIME_REFINER_LLM_MAX_CHARS", lo=80, hi=2000
                ),
                "runtime_refiner_llm_provider": env_str(
                    "SPARK_EIDOS_RUNTIME_REFINER_LLM_PROVIDER", lower=True
                ),
            },
        ).data
        return _sanitize_runtime_refiner_cfg(cfg)
    except Exception:
        return dict(_DEFAULT_RUNTIME_REFINER_CFG)


_RUNTIME_REFINER_CFG: Dict[str, Any] = _load_runtime_refiner_cfg()


def reload_runtime_refiner_from(cfg: Dict[str, Any]) -> None:
    """Hot-reload runtime LLM refiner knobs from the eidos section."""
    global _RUNTIME_REFINER_CFG
    _RUNTIME_REFINER_CFG = _sanitize_runtime_refiner_cfg(cfg)


try:
    from .tuneables_reload import register_reload as _register_reload

    _register_reload("eidos", reload_runtime_refiner_from, label="distillation_refiner.reload_from")
except Exception:
    pass


def _rank_key(quality: Dict[str, Any]) -> Tuple[int, float, float, float]:
    """Sort key for candidate quality preference."""
    suppressed = bool(quality.get("suppressed", False))
    unified = float(quality.get("unified_score", 0.0) or 0.0)
    actionability = float(quality.get("actionability", 0.0) or 0.0)
    reasoning = float(quality.get("reasoning", 0.0) or 0.0)
    specificity = float(quality.get("specificity", 0.0) or 0.0)
    return (
        0 if suppressed else 1,
        unified,
        actionability + reasoning + specificity,
        -len(str(quality.get("advisory_text", "") or "")),
    )


def _rewrite_from_structure(structure: Dict[str, Any], fallback: str) -> str:
    condition = str(structure.get("condition") or "").strip()
    action = str(structure.get("action") or "").strip()
    reasoning = str(structure.get("reasoning") or "").strip()
    outcome = str(structure.get("outcome") or "").strip()

    if not action:
        return fallback

    chunks = []
    if condition:
        chunks.append(f"When {condition}: {action}")
    else:
        chunks.append(action[0].upper() + action[1:] if len(action) > 1 else action)

    if reasoning:
        chunks.append(f"because {reasoning}")
    if outcome:
        chunks.append(f"to {outcome}")

    rewritten = " ".join(chunks).strip()
    return rewritten if len(rewritten) >= 20 else fallback


def _compose_from_structure(structure: Dict[str, Any]) -> str:
    condition = str(structure.get("condition") or "").strip()
    action = str(structure.get("action") or "").strip()
    reasoning = str(structure.get("reasoning") or "").strip()
    outcome = str(structure.get("outcome") or "").strip()

    if not action:
        return ""

    if condition:
        text = f"When {condition}: {action}"
    else:
        text = action[0].upper() + action[1:] if len(action) > 1 else action

    if reasoning:
        text = f"{text} because {reasoning}"
    if outcome:
        text = f"{text} ({outcome})"
    return text.strip()


def _provider_chain(provider: str) -> Tuple[str, ...]:
    preferred = str(provider or "auto").strip().lower()
    if preferred == "claude":
        return ("claude",)

    ordered = []
    for p in (preferred, "minimax", "ollama", "gemini", "openai", "anthropic"):
        if p and p != "auto" and p not in ordered:
            ordered.append(p)
    return tuple(ordered)


def _strip_fence(text: str) -> str:
    raw = str(text or "").strip()
    if not raw.startswith("```"):
        return raw
    lines = raw.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_llm_refinement(raw: str, *, max_chars: int) -> str:
    text = _strip_fence(raw)
    candidate = ""

    if text.startswith("{"):
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                for key in ("refined", "refinement", "advisory_text", "text"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        candidate = value.strip()
                        break
        except Exception:
            candidate = ""

    if not candidate:
        first_line = text.splitlines()[0] if text else ""
        candidate = first_line.strip()

    candidate = re.sub(r"^\s*(?:\d+[.):\-]|\-|\*)\s*", "", candidate).strip()
    candidate = re.sub(r"\s+", " ", candidate).strip()

    if len(candidate) > max_chars:
        candidate = candidate[:max_chars].rstrip(" ,.;:")

    return candidate if len(candidate) >= 20 else ""


def _llm_refine_candidate(
    statement: str,
    *,
    source: str,
    context: Dict[str, Any],
    timeout_s: float,
    max_chars: int,
    provider: str,
) -> str:
    prompt = (
        "Rewrite this distillation into ONE concise, action-first advisory sentence.\n"
        "Rules:\n"
        "- Keep original meaning and constraints.\n"
        "- Do not invent facts.\n"
        "- Prefer format: 'When <condition>: <action> because <reason>'.\n"
        "- 20 to 220 chars.\n"
        "- Output JSON only: {\"refined\": \"...\"}\n\n"
        f"Source: {source}\n"
        f"Context: {json.dumps(context or {}, ensure_ascii=False)}\n"
        f"Input: {statement}"
    )

    raw = None
    try:
        if provider == "claude":
            from .llm import ask_claude

            raw = ask_claude(
                prompt,
                system_prompt="Return JSON only.",
                timeout_s=max(1, int(round(timeout_s))),
                max_tokens=300,
            )
        else:
            try:
                from .advisory_synthesizer import _query_provider  # type: ignore

                for p in _provider_chain(provider):
                    resp = _query_provider(p, prompt)
                    if resp and str(resp).strip():
                        raw = str(resp).strip()
                        break
            except Exception:
                raw = None

            if not raw:
                from .llm import ask_claude

                raw = ask_claude(
                    prompt,
                    system_prompt="Return JSON only.",
                    timeout_s=max(1, int(round(timeout_s))),
                    max_tokens=300,
                )
    except Exception:
        raw = None

    if not raw:
        return ""
    return _extract_llm_refinement(str(raw), max_chars=max_chars)


# ---------------------------------------------------------------------------
# LLM area hooks (opt-in via llm_areas tuneable section)
# ---------------------------------------------------------------------------

def _llm_area_archive_rewrite(statement: str, quality: Dict[str, Any]) -> str:
    """LLM area: rewrite a suppressed/low-score statement (archive_rewrite)."""
    try:
        from .llm_area_prompts import format_prompt
        from .llm_dispatch import llm_area_call

        prompt = format_prompt(
            "archive_rewrite",
            statement=statement,
            reason=str(quality.get("suppression_reason", "low score")),
            score=str(quality.get("unified_score", "0.0")),
        )
        result = llm_area_call("archive_rewrite", prompt, fallback=statement)
        return result.text
    except Exception:
        return statement


def _llm_area_archive_rescue(statement: str, quality: Dict[str, Any], source: str) -> str:
    """LLM area: rescue a suppressed item if it has genuine insight (archive_rescue).

    Returns the rewritten text from the LLM if rescue is recommended,
    otherwise returns the original statement (no-op for the consider() call).
    """
    try:
        from .llm_area_prompts import format_prompt
        from .llm_dispatch import llm_area_call

        prompt = format_prompt(
            "archive_rescue",
            statement=statement,
            unified_score=str(quality.get("unified_score", "0.0")),
            reason=str(quality.get("suppression_reason", "")),
            domain=source,
        )
        result = llm_area_call("archive_rescue", prompt, fallback="")
        if not result.used_llm or not result.text:
            return statement

        # Parse JSON response for rescue decision
        import json as _json
        try:
            data = _json.loads(result.text)
        except (ValueError, TypeError):
            return statement

        if data.get("rescue") and data.get("rewrite"):
            return str(data["rewrite"]).strip()
        return statement
    except Exception:
        return statement


def refine_distillation(
    statement: str,
    *,
    source: str = "eidos",
    context: Optional[Dict[str, Any]] = None,
    min_unified_score: float = 0.60,
) -> Tuple[str, Dict[str, Any]]:
    """Refine a distillation statement and return best text + advisory quality."""
    base = (statement or "").strip()
    if not base:
        aq = transform_for_advisory(base, source=source).to_dict()
        return "", aq

    best_text = base
    best_quality = transform_for_advisory(best_text, source=source).to_dict()

    def consider(candidate_text: str) -> None:
        nonlocal best_text, best_quality
        candidate = (candidate_text or "").strip()
        if not candidate:
            return
        quality = transform_for_advisory(candidate, source=source).to_dict()
        if _rank_key(quality) > _rank_key(best_quality):
            best_text = candidate
            best_quality = quality

    if float(best_quality.get("unified_score", 0.0) or 0.0) < min_unified_score:
        elevated = elevate(base, context or {})
        consider(elevated)

    if float(best_quality.get("unified_score", 0.0) or 0.0) < min_unified_score:
        rewrite = _rewrite_from_structure(best_quality.get("structure") or {}, best_text)
        consider(rewrite)

    if float(best_quality.get("unified_score", 0.0) or 0.0) < min_unified_score:
        composed = _compose_from_structure(best_quality.get("structure") or {})
        consider(composed)

    llm_enabled = bool(_RUNTIME_REFINER_CFG.get("runtime_refiner_llm_enabled", False))
    llm_floor = float(_RUNTIME_REFINER_CFG.get("runtime_refiner_llm_min_unified_score", 0.45) or 0.45)
    current_score = float(best_quality.get("unified_score", 0.0) or 0.0)
    is_suppressed = bool(best_quality.get("suppressed", False))
    if llm_enabled and (is_suppressed or current_score < llm_floor):
        llm_candidate = _llm_refine_candidate(
            best_text,
            source=source,
            context=context or {},
            timeout_s=float(_RUNTIME_REFINER_CFG.get("runtime_refiner_llm_timeout_s", 6.0) or 6.0),
            max_chars=int(_RUNTIME_REFINER_CFG.get("runtime_refiner_llm_max_chars", 280) or 280),
            provider=str(_RUNTIME_REFINER_CFG.get("runtime_refiner_llm_provider", "auto") or "auto"),
        )
        consider(llm_candidate)

    # LLM area: archive_rewrite — rewrite suppressed items via llm_areas config
    if is_suppressed or current_score < min_unified_score:
        consider(_llm_area_archive_rewrite(best_text, best_quality))

    # LLM area: archive_rescue — rescue low-unified items via llm_areas config
    if is_suppressed and current_score < 0.35:
        consider(_llm_area_archive_rescue(best_text, best_quality, source))

    return best_text, best_quality

