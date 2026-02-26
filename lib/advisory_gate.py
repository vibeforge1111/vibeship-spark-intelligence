"""
Advisory Gate: Decides IF and WHEN to surface advice.

The gate is the critical intelligence layer between "we have advice" and
"we should show it." Most advisory systems fail because they show too much,
too often, at the wrong time. The gate prevents that.

Principles:
1. Suppress what's already obvious from context
2. Only surface at decision points or error-prone moments
3. Graduate authority: whisper → note → warning → block
4. Respect fatigue: don't repeat, don't flood
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ============= Authority Levels =============

class AuthorityLevel:
    """Graduated authority for advisory output."""
    SILENT = "silent"       # Log only, never emit (low confidence, tangential)
    WHISPER = "whisper"     # Available if asked, very brief
    NOTE = "note"           # Include in context block, non-blocking
    WARNING = "warning"     # Prominently shown, caution header
    BLOCK = "block"         # EIDOS blocks action (already exists)

# Score thresholds for authority assignment
# NOTE threshold tuned via scoring benchmark (2026-02-22): 0.42→0.48 cuts noise
# from 36%→23% with zero recall loss on 50-case ground truth.
# Noisy primitives are also blocked by _is_primitive_noise().
AUTHORITY_THRESHOLDS = {
    AuthorityLevel.BLOCK: 0.95,     # Only proven critical safety issues
    AuthorityLevel.WARNING: 0.80,   # High confidence + proven failure history
    AuthorityLevel.NOTE: 0.48,      # Moderate confidence + relevant (was 0.42)
    AuthorityLevel.WHISPER: 0.30,   # Low confidence or tangential
    # Below 0.30 → SILENT
}

# ============= Gate Configuration =============

# Agreement-gated escalation ("show more hints, shout only when sure")
AGREEMENT_GATE_ENABLED = os.getenv("SPARK_ADVISORY_AGREEMENT_GATE", "0") == "1"
try:
    AGREEMENT_MIN_SOURCES = max(
        1, min(5, int(os.getenv("SPARK_ADVISORY_AGREEMENT_MIN_SOURCES", "2") or 2))
    )
except Exception:
    AGREEMENT_MIN_SOURCES = 2

# Max advice items to emit per tool call (prevent flooding)
MAX_EMIT_PER_CALL = 2

# Cooldown: don't emit for same tool within N seconds
TOOL_COOLDOWN_S = 10

# Don't repeat the same advice within N seconds
ADVICE_REPEAT_COOLDOWN_S = 300  # 5 minutes

# Per-category cooldown scales. Keys are normalized lowercase category names.
# Values are multipliers applied to shown/tool cooldown windows.
CATEGORY_COOLDOWN_MULTIPLIERS: Dict[str, float] = {}

# Source-aware TTL multipliers — adjust how long advice from each source
# stays suppressed after being shown.  Lower = re-eligible sooner.
# Evidence: shown_ttl was 69.4% of all suppressions (4194 ledger rows / 24h).
# Baseline/bank/trigger have lower repeat-value than cognitive/eidos.
SOURCE_TTL_MULTIPLIERS: Dict[str, float] = {
    "baseline": 0.5,     # generic advice, low repeat value
    "bank": 0.6,         # user memories, context-dependent
    "trigger": 0.7,      # contextual rules, may need refresh
    "mind": 0.75,        # cross-session, already filtered
    "cognitive": 1.0,    # high quality distilled insights
    "eidos": 1.0,        # pattern distillations
    "semantic": 0.8,     # retrieval-based, context-dependent
    "semantic-agentic": 0.8,
    "default": 1.0,
}

# Per-tool cooldown multipliers — adjust tool suppression window by tool family.
# Exploration tools change context rapidly; implementation tools are slower.
# Evidence: tool_cooldown was 8.9% of suppressions (513 in 24h), hiding
# advice bursts during rapid Read/Grep exploration sequences.
TOOL_COOLDOWN_MULTIPLIERS: Dict[str, float] = {
    "Read": 0.5,         # fast context change during exploration
    "Grep": 0.5,
    "Glob": 0.5,
    "Task": 0.6,
    "Bash": 0.7,
    "Edit": 1.2,         # slower context change during implementation
    "Write": 1.2,
    "default": 1.0,
}

# Whether WHISPER-level advice should be emitted at all.
# Default: off (whispers are high-noise in real operations).
EMIT_WHISPERS = os.getenv("SPARK_ADVISORY_EMIT_WHISPERS", "1") == "1"

# Phase-based relevance boosts
PHASE_RELEVANCE = {
    "exploration": {
        "context": 1.3,        # Architecture insights valuable here
        "wisdom": 1.0,
        "reasoning": 1.2,
        "user_understanding": 1.0,  # was 0.8 — crushed scores below whisper threshold
        "self_awareness": 0.9,     # was 0.6 — same issue, kept slightly below 1.0
    },
    "planning": {
        "reasoning": 1.4,      # Past decisions very relevant
        "context": 1.2,
        "wisdom": 1.3,
        "user_understanding": 1.1,
        "self_awareness": 0.7,
    },
    "implementation": {
        "self_awareness": 1.4,  # "You struggle with X" is critical here
        "context": 1.2,
        "reasoning": 1.1,
        "wisdom": 0.9,
        "user_understanding": 1.0,
    },
    "testing": {
        "self_awareness": 1.3,
        "context": 1.0,
        "reasoning": 1.0,
        "wisdom": 0.8,
        "user_understanding": 0.7,
    },
    "debugging": {
        "self_awareness": 1.5,  # Past failure patterns extremely relevant
        "reasoning": 1.4,
        "context": 1.2,
        "wisdom": 1.0,
        "user_understanding": 0.8,
    },
    "deployment": {
        "wisdom": 1.5,         # Safety principles matter most
        "context": 1.3,
        "self_awareness": 1.2,
        "reasoning": 1.0,
        "user_understanding": 0.8,
    },
}


def _clamp_float(value: Any, default: float, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = float(default)
    return max(min_value, min(max_value, parsed))


def _normalize_category_name(category: Any) -> str:
    return str(category or "").strip().lower()


def _parse_category_cooldowns(raw: Any) -> Tuple[Dict[str, float], List[str]]:
    parsed: Dict[str, float] = {}
    warnings: List[str] = []
    if not isinstance(raw, dict):
        return parsed, ["invalid_category_cooldown_multipliers"]
    for key, value in raw.items():
        category = _normalize_category_name(key)
        if not category:
            continue
        try:
            parsed[category] = max(0.1, min(10.0, float(value)))
        except Exception:
            warnings.append(f"invalid_category_cooldown_multiplier:{category}")
    return parsed, warnings


def _cooldown_scale_for_category(category: str) -> float:
    cat = _normalize_category_name(category)
    if cat and cat in CATEGORY_COOLDOWN_MULTIPLIERS:
        return float(CATEGORY_COOLDOWN_MULTIPLIERS[cat])
    for fallback in ("default", "*"):
        if fallback in CATEGORY_COOLDOWN_MULTIPLIERS:
            return float(CATEGORY_COOLDOWN_MULTIPLIERS[fallback])
    return 1.0


def _source_ttl_scale(source: str) -> float:
    """Return TTL multiplier for a given advisory source."""
    src = str(source or "").strip().lower()
    if src and src in SOURCE_TTL_MULTIPLIERS:
        return float(SOURCE_TTL_MULTIPLIERS[src])
    for fallback in ("default", "*"):
        if fallback in SOURCE_TTL_MULTIPLIERS:
            return float(SOURCE_TTL_MULTIPLIERS[fallback])
    return 1.0


def _tool_cooldown_scale(tool_name: str) -> float:
    """Return cooldown multiplier for a given tool family."""
    tool = str(tool_name or "").strip()
    if tool and tool in TOOL_COOLDOWN_MULTIPLIERS:
        return float(TOOL_COOLDOWN_MULTIPLIERS[tool])
    for fallback in ("default", "*"):
        if fallback in TOOL_COOLDOWN_MULTIPLIERS:
            return float(TOOL_COOLDOWN_MULTIPLIERS[fallback])
    return 1.0


def _shown_ttl_for_advice(category: str, source: str = "") -> Tuple[int, float]:
    """Compute shown-TTL for an advice item using category + source multipliers.

    Returns (effective_ttl_seconds, combined_scale).
    """
    cat_scale = _cooldown_scale_for_category(category)
    src_scale = _source_ttl_scale(source)
    combined = cat_scale * src_scale
    base_ttl = int(ADVICE_REPEAT_COOLDOWN_S)
    try:
        from .advisory_state import get_shown_advice_ttl_s

        base_ttl = int(get_shown_advice_ttl_s())
    except Exception:
        pass
    ttl = max(5, int(round(base_ttl * combined)))
    return ttl, combined


def apply_gate_config(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    """Apply advisory gate runtime tuneables."""
    global MAX_EMIT_PER_CALL
    global TOOL_COOLDOWN_S
    global ADVICE_REPEAT_COOLDOWN_S
    global CATEGORY_COOLDOWN_MULTIPLIERS
    global SOURCE_TTL_MULTIPLIERS
    global TOOL_COOLDOWN_MULTIPLIERS
    global EMIT_WHISPERS

    applied: List[str] = []
    warnings: List[str] = []
    if not isinstance(cfg, dict):
        return {"applied": applied, "warnings": warnings}

    if "max_emit_per_call" in cfg:
        try:
            MAX_EMIT_PER_CALL = max(1, min(10, int(cfg.get("max_emit_per_call") or 1)))
            applied.append("max_emit_per_call")
        except Exception:
            warnings.append("invalid_max_emit_per_call")

    if "tool_cooldown_s" in cfg:
        try:
            TOOL_COOLDOWN_S = max(1, min(3600, int(cfg.get("tool_cooldown_s") or 1)))
            applied.append("tool_cooldown_s")
        except Exception:
            warnings.append("invalid_tool_cooldown_s")

    if "advice_repeat_cooldown_s" in cfg:
        try:
            ADVICE_REPEAT_COOLDOWN_S = max(
                5, min(86400, int(cfg.get("advice_repeat_cooldown_s") or 5))
            )
            applied.append("advice_repeat_cooldown_s")
        except Exception:
            warnings.append("invalid_advice_repeat_cooldown_s")

    if "category_cooldown_multipliers" in cfg:
        parsed, parse_warnings = _parse_category_cooldowns(cfg.get("category_cooldown_multipliers"))
        CATEGORY_COOLDOWN_MULTIPLIERS = parsed
        applied.append("category_cooldown_multipliers")
        warnings.extend(parse_warnings)

    if "source_ttl_multipliers" in cfg:
        parsed, parse_warnings = _parse_category_cooldowns(cfg.get("source_ttl_multipliers"))
        SOURCE_TTL_MULTIPLIERS.update(parsed)
        applied.append("source_ttl_multipliers")
        warnings.extend(parse_warnings)

    if "tool_cooldown_multipliers" in cfg:
        raw_tool = cfg.get("tool_cooldown_multipliers")
        if isinstance(raw_tool, dict):
            for key, value in raw_tool.items():
                tool_key = str(key or "").strip()
                if not tool_key:
                    continue
                try:
                    TOOL_COOLDOWN_MULTIPLIERS[tool_key] = max(0.1, min(10.0, float(value)))
                except Exception:
                    warnings.append(f"invalid_tool_cooldown_multiplier:{tool_key}")
            applied.append("tool_cooldown_multipliers")
        else:
            warnings.append("invalid_tool_cooldown_multipliers")

    if "emit_whispers" in cfg:
        raw_emit = cfg.get("emit_whispers")
        if isinstance(raw_emit, bool):
            EMIT_WHISPERS = raw_emit
            applied.append("emit_whispers")
        else:
            text = str(raw_emit).strip().lower()
            if text in {"1", "true", "yes", "on"}:
                EMIT_WHISPERS = True
                applied.append("emit_whispers")
            elif text in {"0", "false", "no", "off"}:
                EMIT_WHISPERS = False
                applied.append("emit_whispers")
            else:
                warnings.append("invalid_emit_whispers")

    warning_threshold = _clamp_float(
        cfg.get("warning_threshold", AUTHORITY_THRESHOLDS.get(AuthorityLevel.WARNING, 0.8)),
        AUTHORITY_THRESHOLDS.get(AuthorityLevel.WARNING, 0.8),
        0.2,
        0.99,
    )
    note_threshold = _clamp_float(
        cfg.get("note_threshold", AUTHORITY_THRESHOLDS.get(AuthorityLevel.NOTE, 0.5)),
        AUTHORITY_THRESHOLDS.get(AuthorityLevel.NOTE, 0.5),
        0.1,
        0.95,
    )
    whisper_threshold = _clamp_float(
        cfg.get("whisper_threshold", AUTHORITY_THRESHOLDS.get(AuthorityLevel.WHISPER, 0.35)),
        AUTHORITY_THRESHOLDS.get(AuthorityLevel.WHISPER, 0.35),
        0.01,
        0.9,
    )

    if "warning_threshold" in cfg:
        applied.append("warning_threshold")
    if "note_threshold" in cfg:
        applied.append("note_threshold")
    if "whisper_threshold" in cfg:
        applied.append("whisper_threshold")

    # Keep threshold ordering sane: warning > note > whisper.
    if warning_threshold <= note_threshold:
        note_threshold = max(0.1, warning_threshold - 0.05)
        warnings.append("note_threshold_auto_adjusted")
    if note_threshold <= whisper_threshold:
        whisper_threshold = max(0.01, note_threshold - 0.05)
        warnings.append("whisper_threshold_auto_adjusted")

    AUTHORITY_THRESHOLDS[AuthorityLevel.WARNING] = warning_threshold
    AUTHORITY_THRESHOLDS[AuthorityLevel.NOTE] = note_threshold
    AUTHORITY_THRESHOLDS[AuthorityLevel.WHISPER] = whisper_threshold

    # Keep advisory_state TTL in sync with gate tuneables.
    # Explicit shown_advice_ttl_s wins; otherwise repeat cooldown acts as alias.
    state_cfg: Dict[str, Any] = {}
    if "shown_advice_ttl_s" in cfg:
        state_cfg["shown_advice_ttl_s"] = cfg.get("shown_advice_ttl_s")
    elif "advice_repeat_cooldown_s" in cfg:
        state_cfg["advice_repeat_cooldown_s"] = cfg.get("advice_repeat_cooldown_s")
    if state_cfg:
        try:
            from .advisory_state import apply_state_gate_config

            state_result = apply_state_gate_config(state_cfg)
            applied.extend(
                key for key in list(state_result.get("applied") or [])
                if key not in applied
            )
            warnings.extend(list(state_result.get("warnings") or []))
        except Exception:
            warnings.append("state_gate_config_sync_failed")

    return {"applied": applied, "warnings": warnings}


def get_gate_config() -> Dict[str, Any]:
    shown_ttl = int(ADVICE_REPEAT_COOLDOWN_S)
    try:
        from .advisory_state import get_shown_advice_ttl_s

        shown_ttl = int(get_shown_advice_ttl_s())
    except Exception:
        pass
    return {
        "max_emit_per_call": int(MAX_EMIT_PER_CALL),
        "tool_cooldown_s": int(TOOL_COOLDOWN_S),
        "advice_repeat_cooldown_s": int(ADVICE_REPEAT_COOLDOWN_S),
        "shown_advice_ttl_s": int(shown_ttl),
        "category_cooldown_multipliers": dict(CATEGORY_COOLDOWN_MULTIPLIERS),
        "source_ttl_multipliers": dict(SOURCE_TTL_MULTIPLIERS),
        "tool_cooldown_multipliers": dict(TOOL_COOLDOWN_MULTIPLIERS),
        "emit_whispers": bool(EMIT_WHISPERS),
        "warning_threshold": float(AUTHORITY_THRESHOLDS.get(AuthorityLevel.WARNING, 0.8)),
        "note_threshold": float(AUTHORITY_THRESHOLDS.get(AuthorityLevel.NOTE, 0.5)),
        "whisper_threshold": float(AUTHORITY_THRESHOLDS.get(AuthorityLevel.WHISPER, 0.35)),
    }


def get_tool_cooldown_s() -> int:
    return max(1, int(TOOL_COOLDOWN_S))


def _load_gate_config(path: Optional[Path] = None) -> Dict[str, Any]:
    from .config_authority import resolve_section
    tuneables = path or (Path.home() / ".spark" / "tuneables.json")
    cfg = resolve_section("advisory_gate", runtime_path=tuneables).data
    return cfg if isinstance(cfg, dict) else {}


_BOOT_GATE_CFG = _load_gate_config()
if _BOOT_GATE_CFG:
    apply_gate_config(_BOOT_GATE_CFG)

try:
    from .tuneables_reload import register_reload as _gate_register
    _gate_register("advisory_gate", apply_gate_config, label="advisory_gate.apply_config")
except ImportError:
    pass


@dataclass
class GateDecision:
    """Result of the gate evaluation for a single advice item."""
    advice_id: str
    authority: str
    emit: bool
    reason: str
    adjusted_score: float
    original_score: float


@dataclass
class GateResult:
    """Aggregate gate result for all advice items."""
    decisions: List[GateDecision]
    emitted: List[GateDecision]      # Only items with emit=True
    suppressed: List[GateDecision]   # Items filtered out
    phase: str
    total_retrieved: int


def _normalize_advice_signature(text: str) -> str:
    """Normalize advice text into a grouping signature.

    Used for agreement gating. We intentionally keep it cheap and robust:
    remove bracket tags and punctuation, lowercase, and collapse whitespace.
    """
    t = str(text or "").strip().lower()
    # Drop leading tags like [Caution]
    if t.startswith("[") and "]" in t[:40]:
        t = t.split("]", 1)[-1].strip()
    t = re.sub(r"[^a-z0-9\s]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Keep signature bounded
    return t[:180]


def _agreement_map(advice_items: list) -> Dict[str, Dict[str, Any]]:
    """Build agreement metadata for each advice item in this retrieval batch."""
    by_sig: Dict[str, Dict[str, Any]] = {}
    # First pass: group by normalized signature
    for item in advice_items or []:
        aid = str(getattr(item, "advice_id", "") or "")
        text = str(getattr(item, "text", "") or "")
        source = str(getattr(item, "source", "unknown") or "unknown").strip().lower() or "unknown"
        sig = _normalize_advice_signature(text)
        if not sig:
            continue
        bucket = by_sig.setdefault(sig, {"sources": set(), "advice_ids": []})
        bucket["sources"].add(source)
        if aid:
            bucket["advice_ids"].append(aid)

    # Second pass: assign per advice_id
    out: Dict[str, Dict[str, Any]] = {}
    for sig, bucket in by_sig.items():
        sources = sorted(list(bucket.get("sources") or []))
        for aid in bucket.get("advice_ids") or []:
            out[aid] = {
                "agreement_sources": sources,
                "agreement_count": len(sources),
                "signature": sig,
            }
    return out


def evaluate(
    advice_items: list,
    state,  # SessionState
    tool_name: str,
    tool_input: Optional[dict] = None,
    recent_global_emissions: Optional[Dict[str, float]] = None,
) -> GateResult:
    """
    Evaluate all advice items through the gate.

    Args:
        advice_items: List of Advice objects from advisor.py
        state: SessionState from advisory_state
        tool_name: Current tool being invoked
        tool_input: Tool input dict
        recent_global_emissions: Dict of {advice_id: age_s} for recently emitted
            advice IDs (from global dedupe log). If present, gate absorbs
            advice_id dedupe so post-gate only needs text_sig dedupe.

    Returns:
        GateResult with decisions on what to emit
    """
    decisions = []
    phase = state.task_phase if state else "implementation"

    agreement = _agreement_map(advice_items) if AGREEMENT_GATE_ENABLED else {}

    for advice in advice_items:
        aid = str(getattr(advice, "advice_id", "") or "")
        decision = _evaluate_single(
            advice,
            state,
            tool_name,
            tool_input,
            phase,
            agreement_meta=(agreement.get(aid) if aid else None),
            recent_global_emissions=recent_global_emissions,
        )
        decisions.append(decision)

    # Sort by adjusted score descending
    decisions.sort(key=lambda d: d.adjusted_score, reverse=True)

    # Dynamic emission budget: increase when high-authority items are present
    # or confidence spread justifies more emissions.
    # Evidence: budget_exhausted was 8.1% of suppressions (466 in 24h).
    effective_budget = int(MAX_EMIT_PER_CALL)
    emit_eligible = [d for d in decisions if d.emit]
    has_warning = any(d.authority == AuthorityLevel.WARNING for d in emit_eligible)
    if has_warning:
        effective_budget += 1
    if (
        len(emit_eligible) >= 2
        and emit_eligible[0].adjusted_score >= 0.75
        and emit_eligible[1].adjusted_score >= 0.60
    ):
        effective_budget += 1
    # Hard cap: never exceed base + 2
    effective_budget = min(effective_budget, MAX_EMIT_PER_CALL + 2)

    # Apply emission budget
    emitted = []
    suppressed = []
    emit_count = 0

    for d in decisions:
        if not d.emit:
            suppressed.append(d)
            continue

        if emit_count >= effective_budget:
            d.emit = False
            d.reason = f"budget exhausted ({effective_budget} effective, {MAX_EMIT_PER_CALL} base)"
            suppressed.append(d)
            continue

        emitted.append(d)
        emit_count += 1

    return GateResult(
        decisions=decisions,
        emitted=emitted,
        suppressed=suppressed,
        phase=phase,
        total_retrieved=len(advice_items),
    )


def _tool_phase_shown_key(advice_id: str, tool_name: str, phase: str) -> str:
    aid = str(advice_id or "").strip()
    if not aid:
        return ""
    tool = str(tool_name or "").strip().lower() or "*"
    phase_name = str(phase or "").strip().lower() or "*"
    return f"{aid}|{tool}|{phase_name}"


def _evaluate_single(
    advice,
    state,
    tool_name: str,
    tool_input: Optional[dict],
    phase: str,
    *,
    agreement_meta: Optional[Dict[str, Any]] = None,
    recent_global_emissions: Optional[Dict[str, float]] = None,
) -> GateDecision:
    """Evaluate a single advice item through all gate filters."""
    from .advisory_state import is_tool_suppressed

    advice_id = getattr(advice, "advice_id", "") or ""
    text = getattr(advice, "text", "") or ""
    confidence = getattr(advice, "confidence", 0.5) or 0.5
    source = getattr(advice, "source", "unknown") or "unknown"
    context_match = getattr(advice, "context_match", 0.5) or 0.5
    insight_key = getattr(advice, "insight_key", "") or ""

    # Additive base score (aligned with advisor's 3-factor model).
    # Items reaching the gate already passed Meta-Ralph + cognitive filter + advisor ranking,
    # so the 0.15 floor reflects that quality is pre-validated (0.30 * 0.50 quality default).
    base_score = 0.45 * min(1.0, context_match) + 0.25 * min(1.0, confidence) + 0.15

    # Infer category early: it drives category-aware cooldown windows.
    category = _infer_category(insight_key, source)
    shown_ttl_s, cooldown_scale = _shown_ttl_for_advice(category, source)

    # ---- Filter 1: Already shown recently? (TTL-based) ----
    shown_ids = state.shown_advice_ids if state else {}
    shown_scope_key = _tool_phase_shown_key(advice_id, tool_name, phase)
    if isinstance(shown_ids, dict) and advice_id in shown_ids:
        shown_at = float(shown_ids.get(advice_id, 0.0) or 0.0)
        if shown_at > 0 and (time.time() - shown_at) < shown_ttl_s:
            return GateDecision(
                advice_id=advice_id,
                authority=AuthorityLevel.SILENT,
                emit=False,
                reason=(
                    f"shown {int(time.time() - shown_at)}s ago "
                    f"(TTL {shown_ttl_s}s, category={category})"
                ),
                adjusted_score=0.0,
                original_score=base_score,
            )
    if shown_scope_key and isinstance(shown_ids, dict) and shown_scope_key in shown_ids:
        shown_at = float(shown_ids.get(shown_scope_key, 0.0) or 0.0)
        if shown_at > 0 and (time.time() - shown_at) < shown_ttl_s:
            return GateDecision(
                advice_id=advice_id,
                authority=AuthorityLevel.SILENT,
                emit=False,
                reason=f"shown for {str(tool_name or '?').strip()}/{str(phase or '?')} "
                f"recently ({int(time.time() - shown_at)}s ago, TTL {shown_ttl_s}s, category={category})",
                adjusted_score=0.0,
                original_score=base_score,
            )
    elif isinstance(shown_ids, list) and advice_id in shown_ids:
        # Backwards compat: old list format, treat as permanently shown
        return GateDecision(
            advice_id=advice_id,
            authority=AuthorityLevel.SILENT,
            emit=False,
            reason="already shown this session (legacy)",
            adjusted_score=0.0,
            original_score=base_score,
        )

    # ---- Filter 2: Tool suppressed? ----
    # Combine category-based and tool-family-based cooldown scales.
    tool_scale = _tool_cooldown_scale(tool_name)
    effective_cooldown_scale = cooldown_scale * tool_scale
    if state and is_tool_suppressed(state, tool_name, cooldown_scale=effective_cooldown_scale):
        cooldown_note = (
            f" (category={category}, cat_scale={cooldown_scale:.2f},"
            f" tool_scale={tool_scale:.2f}, effective={effective_cooldown_scale:.2f})"
            if abs(effective_cooldown_scale - 1.0) > 1e-9
            else ""
        )
        return GateDecision(
            advice_id=advice_id,
            authority=AuthorityLevel.SILENT,
            emit=False,
            reason=f"tool {tool_name} on cooldown{cooldown_note}",
            adjusted_score=0.0,
            original_score=base_score,
        )

    # ---- Filter 2b: Global dedupe (advice_id) — absorbed from post-gate ----
    # Previously ran as a separate pass after the gate. Now checked per-item
    # inside the gate, so post-gate only needs text_sig dedupe.
    if recent_global_emissions and advice_id:
        age_s = recent_global_emissions.get(advice_id)
        if age_s is not None:
            return GateDecision(
                advice_id=advice_id,
                authority=AuthorityLevel.SILENT,
                emit=False,
                reason=f"global_dedupe: advice_id emitted {age_s:.0f}s ago",
                adjusted_score=0.0,
                original_score=base_score,
            )

    # ---- Filter 3: Obvious-from-context suppression ----
    suppressed, suppression_reason = _check_obvious_suppression(
        text, tool_name, tool_input, state
    )
    if suppressed:
        return GateDecision(
            advice_id=advice_id,
            authority=AuthorityLevel.SILENT,
            emit=False,
            reason=suppression_reason,
            adjusted_score=0.0,
            original_score=base_score,
        )

    # ---- Score Adjustment: Phase relevance ----
    phase_boosts = PHASE_RELEVANCE.get(phase, {})
    phase_multiplier = phase_boosts.get(category, 1.0)
    adjusted_score = base_score * phase_multiplier

    # ---- Score Adjustment: Emotional priority from pipeline distillation ----
    # Bridge emotional salience into gate scoring (capped +15% to avoid dominance).
    ep = float(getattr(advice, "emotional_priority", 0.0) or 0.0)
    if ep > 0.0:
        adjusted_score *= (1.0 + min(0.15, ep * 0.15))

    # ---- Score Adjustment: Negative advisory boost ----
    # Advice about what NOT to do is more valuable than advice about what to do
    if _is_negative_advisory(text):
        adjusted_score *= 1.3

    # ---- Score Adjustment: Failure-context boost ----
    # If we're debugging, cautions get a big boost
    if state and state.consecutive_failures >= 1 and _is_caution(text):
        adjusted_score *= 1.5

    # ---- Score Adjustment: outcome risk boost (world-model-lite) ----
    # When we predict this tool call is likely to fail, boost cautionary advice.
    risk_note = ""
    try:
        from .outcome_predictor import PREDICTOR_ENABLED, predict

        if PREDICTOR_ENABLED and state and (_is_caution(text) or _is_negative_advisory(text)):
            pred = predict(
                tool_name=tool_name,
                intent_family=getattr(state, "intent_family", "") or "emergent_other",
                phase=phase,
            )
            # Only act when we have some evidence or high risk.
            if pred.samples >= 5 or pred.p_fail >= 0.6:
                adjusted_score *= (1.0 + (0.45 * float(pred.p_fail)))
                risk_note = f", risk={pred.p_fail:.2f} n={pred.samples}"
    except Exception:
        pass

    # ---- Agreement gating (escalation only when corroborated) ----
    agreement_count = 1
    agreement_sources: List[str] = []
    if isinstance(agreement_meta, dict):
        try:
            agreement_count = int(agreement_meta.get("agreement_count") or 1)
        except Exception:
            agreement_count = 1
        raw_sources = agreement_meta.get("agreement_sources")
        if isinstance(raw_sources, list):
            agreement_sources = [str(s) for s in raw_sources if str(s).strip()]

    # ---- Determine authority level ----
    authority = _assign_authority(adjusted_score, confidence, text, source)

    # If we're about to WARN but we don't have corroboration, downgrade to NOTE.
    # This implements: "whisper/note freely; warnings require agreement".
    if AGREEMENT_GATE_ENABLED and authority == AuthorityLevel.WARNING:
        if agreement_count < AGREEMENT_MIN_SOURCES:
            authority = AuthorityLevel.NOTE

    # ---- Final emit decision ----
    # WHISPER (0.35-0.49) was previously dead code — classified but never emitted.
    # Now included so low-confidence advice still reaches the user as a gentle hint.
    emit = authority in (AuthorityLevel.NOTE, AuthorityLevel.WARNING) or (
        authority == AuthorityLevel.WHISPER and bool(EMIT_WHISPERS)
    )

    agreement_note = ""
    if AGREEMENT_GATE_ENABLED:
        agreement_note = f", agree={agreement_count} ({','.join(agreement_sources[:3])})" if agreement_sources else f", agree={agreement_count}"

    return GateDecision(
        advice_id=advice_id,
        authority=authority,
        emit=emit,
        reason=f"phase={phase}, score={adjusted_score:.2f}, authority={authority}{agreement_note}{risk_note}",
        adjusted_score=adjusted_score,
        original_score=base_score,
    )


def _check_obvious_suppression(
    text: str,
    tool_name: str,
    tool_input: Optional[dict],
    state,
) -> Tuple[bool, str]:
    """Check if advice is obvious from context and should be suppressed."""
    from .advisory_state import had_recent_read

    text_lower = text.lower()

    # Suppress tool-mismatch "Read before Edit" advice on tools where it adds noise.
    # It's still relevant while Reading (as a reminder before you Edit), so allow Read/Edit/Write.
    if any(
        k in text_lower
        for k in (
            "read before edit",
            "read a file before edit",
            "read file before edit",
            "before edit to verify",
        )
    ):
        if tool_name not in {"Read", "Edit", "Write"}:
            return True, "read-before-edit advice on unrelated tool"

    # "Read before Edit" suppression: if the file was recently Read, don't say it
    if tool_name == "Edit" and "read before edit" in text_lower:
        file_path = ""
        if isinstance(tool_input, dict):
            file_path = str(tool_input.get("file_path", ""))
        if state and file_path and had_recent_read(state, file_path, within_s=120):
            return True, "file was recently Read, advice redundant"

    # Suppress generic tool advice when tool is being used correctly
    if tool_name == "Read" and "read" in text_lower and "before" not in text_lower:
        return True, "generic Read advice while already Reading"

    # Suppress tool-specific struggle cautions unless we're in that tool family.
    # (WebFetch/WebSearch are where this is actionable; elsewhere it tends to be spam.)
    if "webfetch" in text_lower and tool_name not in {"WebFetch", "WebSearch"}:
        return True, "WebFetch caution on non-web tool"

    # Suppress telemetry-heavy struggle cautions (tool_X_error style).
    # These labels are low-signal and usually reflect instrumentation artifacts,
    # not actionable guidance for the current step.
    if re.search(r"\bi struggle with\s+(?:tool[_\s-]*)?\d+[_\s-]*error\s+tasks\b", text_lower):
        return True, "telemetry struggle caution"
    if "i struggle with" in text_lower and "_error" in text_lower:
        return True, "telemetry struggle caution"

    # Suppress meta-constraints unless we're in planning/control tools.
    if text_lower.startswith("constraint:") and "one state" in text_lower:
        if tool_name not in {"Task", "EnterPlanMode", "ExitPlanMode"}:
            return True, "meta constraint on non-planning tool"

    # Suppress deployment warnings during exploration phase
    if state and state.task_phase == "exploration":
        if any(w in text_lower for w in ("deploy", "push to prod", "release")):
            return True, "deployment advice during exploration phase"

    return False, ""


def _is_negative_advisory(text: str) -> bool:
    """Check if advice is about what NOT to do (higher value)."""
    negative_patterns = [
        r"\bdon'?t\b", r"\bavoid\b", r"\bnever\b", r"\bwatch out\b",
        r"\bcaution\b", r"\bwarning\b", r"\bcareful\b", r"\bdanger\b",
        r"\bpast failure\b", r"\bfailed when\b", r"\bbroke\b",
    ]
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in negative_patterns)


def _is_caution(text: str) -> bool:
    """Check if advice is a caution/warning."""
    return bool(re.search(
        r"\[caution\]|\[past failure\]|\[warning\]|⚠|❗",
        text, re.IGNORECASE
    ))


def _infer_category(insight_key: str, source: str) -> str:
    """Infer insight category from key or source."""
    if not insight_key:
        return source or "unknown"

    # insight_key format: "category:specific_key" or "prefix:key"
    parts = insight_key.split(":", 1)
    if len(parts) >= 1:
        prefix = parts[0].lower()
        category_map = {
            "self_awareness": "self_awareness",
            "struggle": "self_awareness",
            "user_understanding": "user_understanding",
            "user_pref": "user_understanding",
            "comm_style": "user_understanding",
            "reasoning": "reasoning",
            "context": "context",
            "wisdom": "wisdom",
            "meta_learning": "meta_learning",
            "creativity": "creativity",
            "communication": "communication",
        }
        return category_map.get(prefix, source or "unknown")
    return source or "unknown"


def _is_primitive_noise(text: str) -> bool:
    """Detect primitive/noisy insights that should stay SILENT even with relaxed thresholds.

    These are low-information insights that add no actionable value:
    generic tool labels, operational metrics, or content-free statements.
    """
    tl = text.lower().strip()
    # Very short text is almost always noise
    if len(tl) < 15:
        return True
    # Pure tool-name / telemetry patterns
    _NOISE_PATTERNS = [
        r"^(?:bash|edit|read|write|task|tool)\s*→?\s*(?:bash|edit|read|write|task|tool)(?:\s*→?\s*(?:bash|edit|read|write|task|tool))*$",
        r"^\d+\s*(?:calls?|invocations?|runs?|times?)\b",
        r"^(?:okay|ok|got it|sure|yes|no|fine|done|thanks)\.?$",
        r"^(?:success|error|failure)\s*(?:rate|count|ratio)\b",
        r"\btool[_\s-]*\d+[_\s-]*error\b",
        r"^for\s+\w+\s+tasks?,?\s*use\s+standard\s+approach",
        r"^cycle\s+summary:",
        # Timing observation noise: "took 4.2s", "operation took 350ms"
        r"\btook\s+\d[\d.]*\s*(?:ms|s|sec|second|minute)",
        r"^(?:total\s+)?(?:operation|execution|processing|run)\s+t(?:ime|ook)",
        # Generic platitudes with no actionable specifics
        r"^always\s+consider\s+the\s+trade",
        r"^(?:it'?s?\s+)?(?:important|essential|crucial|key|critical)\s+to\s+(?:always\s+)?(?:consider|remember|keep)\b",
    ]
    for pat in _NOISE_PATTERNS:
        if re.search(pat, tl):
            return True
    return False


def _has_actionable_content(text: str) -> bool:
    """Quick check: does this advisory contain actionable guidance?

    Used as a micro-boost signal in authority assignment so that
    substantive advice is less likely to be gated as WHISPER/SILENT.
    """
    tl = text.lower()
    return bool(re.search(
        r"\b(?:check|verify|ensure|use|avoid|prefer|run|test|validate|consider|try|set|add|remove|read before)\b",
        tl,
    ))


def _assign_authority(
    score: float,
    confidence: float,
    text: str,
    source: str,
) -> str:
    """Assign authority level based on score, confidence, and content."""
    # Block level is handled by EIDOS, not here

    # Hard floor: primitive noise stays SILENT regardless of score
    if _is_primitive_noise(text):
        return AuthorityLevel.SILENT

    # Warning: high score + proven pattern
    if score >= AUTHORITY_THRESHOLDS[AuthorityLevel.WARNING]:
        if _is_caution(text) or _is_negative_advisory(text):
            return AuthorityLevel.WARNING
        # High score but not a caution → still a note (don't over-warn)
        return AuthorityLevel.NOTE

    if score >= AUTHORITY_THRESHOLDS[AuthorityLevel.NOTE]:
        return AuthorityLevel.NOTE

    # Actionable-content micro-boost: if the score is close to NOTE threshold
    # and the text contains actionable guidance, promote to NOTE.
    note_threshold = AUTHORITY_THRESHOLDS[AuthorityLevel.NOTE]
    if score >= (note_threshold - 0.08) and _has_actionable_content(text):
        return AuthorityLevel.NOTE

    if score >= AUTHORITY_THRESHOLDS[AuthorityLevel.WHISPER]:
        return AuthorityLevel.WHISPER

    return AuthorityLevel.SILENT
