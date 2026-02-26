"""
Advisory Emitter: The stdout bridge between Spark and Claude.

THIS IS THE MISSING LINK.

Claude Code hooks can output to stdout. That output is visible to Claude
as additional context. The emitter formats advisory content and writes it
to stdout so Claude actually receives the guidance.

Design principles:
- Brief. Claude's context is precious. Every word must earn its place.
- Structured. Use consistent formatting Claude can parse.
- Graduated. Authority level determines visibility and urgency.
- Budgeted. Never emit more than a few lines per tool call.

Output format:
  Stdout text from hooks appears in Claude's context as hook feedback.
  We use a lightweight structured format that's informative but concise.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Dict, Any

from .diagnostics import log_debug

# ============= Configuration =============

# Defaults — overridden by config-authority resolution below.
EMIT_ENABLED: bool = True
MAX_EMIT_CHARS: int = 500
MIN_EMIT_SCORE = 0.4
EMIT_LOG = Path.home() / ".spark" / "advisory_emit.jsonl"
EMIT_LOG_MAX_LINES = 500
FORMAT_STYLE: str = "inline"


def _load_emitter_config() -> None:
    """Resolve emitter knobs from the advisory_engine section via config-authority."""
    global EMIT_ENABLED, MAX_EMIT_CHARS, FORMAT_STYLE
    try:
        from .config_authority import resolve_section, env_bool, env_int, env_str

        cfg = resolve_section(
            "advisory_engine",
            env_overrides={
                "emit_enabled": env_bool("SPARK_ADVISORY_EMIT"),
                "emit_max_chars": env_int("SPARK_ADVISORY_MAX_CHARS"),
                "emit_format": env_str("SPARK_ADVISORY_FORMAT"),
            },
        ).data
        EMIT_ENABLED = bool(cfg.get("emit_enabled", True))
        MAX_EMIT_CHARS = int(cfg.get("emit_max_chars", 500))
        FORMAT_STYLE = str(cfg.get("emit_format", "inline"))
    except Exception:
        pass


_load_emitter_config()

try:
    from .tuneables_reload import register_reload as _emitter_register

    _emitter_register(
        "advisory_engine",
        lambda _cfg: _load_emitter_config(),
        label="advisory_emitter.reload",
    )
except ImportError:
    pass


# ============= Emission Formatting =============

def format_advisory(
    synthesized_text: str,
    authority: str,
    phase: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Format advisory text for stdout emission.

    Different authority levels get different formatting:
    - WARNING: [SPARK WARNING] prominent header
    - NOTE: [SPARK] clean inline note
    - WHISPER: (very brief, parenthetical)
    """
    if not synthesized_text or not synthesized_text.strip():
        return ""

    text = synthesized_text.strip()

    # Enforce character budget
    if len(text) > MAX_EMIT_CHARS:
        text = text[:MAX_EMIT_CHARS - 3] + "..."

    if authority == "warning":
        return f"[SPARK ADVISORY] {text}"
    elif authority == "note":
        return f"[SPARK] {text}"
    elif authority == "whisper":
        # Whispers are very brief
        if len(text) > 150:
            text = text[:147] + "..."
        return f"(spark: {text})"
    else:
        return ""  # Silent items don't get formatted


def format_from_gate_result(
    gate_result,  # GateResult from advisory_gate
    synthesized_text: str,
) -> str:
    """
    Format the final output from gate decisions + synthesis.

    If synthesis produced text, use that (AI-composed).
    If not, fall back to formatting individual items.
    """
    if not gate_result or not gate_result.emitted:
        return ""

    # Determine highest authority among emitted items
    authority_order = ["block", "warning", "note", "whisper", "silent"]
    highest_authority = "silent"
    for d in gate_result.emitted:
        if authority_order.index(d.authority) < authority_order.index(highest_authority):
            highest_authority = d.authority

    if synthesized_text and synthesized_text.strip():
        return format_advisory(synthesized_text, highest_authority, gate_result.phase)

    # No synthesis: format individual items
    parts = []
    for d in gate_result.emitted[:3]:  # Max 3 items
        text = d.advice_id  # We need the actual text, not just ID
        # The gate decision only has advice_id; we need to look up text
        # This is handled by the engine which passes both
        parts.append(format_advisory(str(d.reason), d.authority, gate_result.phase))

    return "\n".join(p for p in parts if p)


# ============= Stdout Emission =============

def emit(text: str, *, metadata: Optional[Dict[str, Any]] = None) -> bool:
    """
    Write advisory text to stdout so Claude Code reads it.

    This is the critical bridge function.

    Returns True if text was emitted, False if suppressed.
    """
    if not EMIT_ENABLED:
        return False

    if not text or not text.strip():
        return False

    # Enforce budget
    output = text.strip()
    if len(output) > MAX_EMIT_CHARS:
        output = output[:MAX_EMIT_CHARS - 3] + "..."

    # Write to stdout (Claude Code reads this)
    try:
        sys.stdout.write(output + "\n")
        sys.stdout.flush()
    except Exception as e:
        log_debug("advisory_emit", "stdout write failed", e)
        return False

    # Log emission for diagnostics
    _log_emission(output, metadata=metadata)

    return True


def emit_advisory(
    gate_result,
    synthesized_text: str,
    advice_items: Optional[list] = None,
    *,
    trace_id: Optional[str] = None,
    tool_name: str = "",
    route: str = "",
    task_plane: str = "",
) -> bool:
    """
    High-level emission: format and emit advisory from gate + synthesis.

    Args:
        gate_result: GateResult from advisory_gate
        synthesized_text: Output from advisory_synthesizer
        advice_items: Original advice items (for text lookup)

    Returns:
        True if anything was emitted
    """
    if not gate_result or not gate_result.emitted:
        return False

    # Determine authority
    highest = _highest_authority(gate_result.emitted)

    if synthesized_text and synthesized_text.strip():
        formatted = format_advisory(synthesized_text, highest, gate_result.phase)
        return emit(
            formatted,
            metadata={
                "trace_id": str(trace_id or "").strip() or None,
                "tool_name": (tool_name or "").strip() or None,
                "route": (route or "").strip() or None,
                "task_plane": (task_plane or "").strip() or None,
                "authority": highest,
                "phase": getattr(gate_result, "phase", "") or None,
            },
        )

    # Fallback: emit individual items from advice list
    if advice_items:
        # Match emitted advice_ids to actual text
        advice_by_id = {}
        for item in advice_items:
            aid = getattr(item, "advice_id", "")
            if aid:
                advice_by_id[aid] = item

        parts = []
        for d in gate_result.emitted[:3]:
            item = advice_by_id.get(d.advice_id)
            if item:
                text = getattr(item, "text", "")
                if text:
                    parts.append(format_advisory(text, d.authority, gate_result.phase))

        if parts:
            combined = "\n".join(p for p in parts if p)
            # Enforce total budget
            if len(combined) > MAX_EMIT_CHARS:
                combined = combined[:MAX_EMIT_CHARS - 3] + "..."
            return emit(
                combined,
                metadata={
                    "trace_id": str(trace_id or "").strip() or None,
                    "tool_name": (tool_name or "").strip() or None,
                    "route": (route or "").strip() or None,
                    "task_plane": (task_plane or "").strip() or None,
                    "authority": highest,
                    "phase": getattr(gate_result, "phase", "") or None,
                },
            )

    return False


def _highest_authority(decisions: list) -> str:
    """Find the highest authority level among decisions."""
    order = {"block": 0, "warning": 1, "note": 2, "whisper": 3, "silent": 4}
    best = "silent"
    for d in decisions:
        auth = getattr(d, "authority", "silent")
        if order.get(auth, 4) < order.get(best, 4):
            best = auth
    return best


# ============= Diagnostics =============

def _log_emission(text: str, *, metadata: Optional[Dict[str, Any]] = None) -> None:
    """Log what was emitted for diagnostics and feedback tracking."""
    try:
        EMIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "text": text[:300],
            "chars": len(text),
        }
        if metadata:
            entry.update({k: v for k, v in metadata.items() if v is not None and v != ""})
        with open(EMIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        # Rotate log if too large
        _rotate_log()
    except Exception:
        pass


def _rotate_log() -> None:
    """Keep emission log bounded."""
    try:
        if not EMIT_LOG.exists():
            return
        lines = EMIT_LOG.read_text(encoding="utf-8").strip().split("\n")
        if len(lines) > EMIT_LOG_MAX_LINES:
            keep = lines[-EMIT_LOG_MAX_LINES:]
            EMIT_LOG.write_text("\n".join(keep) + "\n", encoding="utf-8")
    except Exception:
        pass


def get_emission_stats() -> Dict[str, Any]:
    """Get emission statistics for diagnostics."""
    stats = {
        "enabled": EMIT_ENABLED,
        "max_chars": MAX_EMIT_CHARS,
        "format": FORMAT_STYLE,
        "total_emissions": 0,
        "recent_emissions": [],
    }
    try:
        if EMIT_LOG.exists():
            lines = EMIT_LOG.read_text(encoding="utf-8").strip().split("\n")
            stats["total_emissions"] = len(lines)
            # Last 5 emissions
            for line in lines[-5:]:
                try:
                    entry = json.loads(line)
                    stats["recent_emissions"].append({
                        "text": entry.get("text", "")[:100],
                        "chars": entry.get("chars", 0),
                    })
                except Exception:
                    pass
    except Exception:
        pass
    return stats
