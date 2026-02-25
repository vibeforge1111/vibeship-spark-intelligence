"""
Advisory Engine: orchestrator for direct-path advisory and predictive packets.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .advisory_quarantine import record_quarantine_item
from .diagnostics import log_debug
from .error_taxonomy import build_error_fields

ENGINE_ENABLED = os.getenv("SPARK_ADVISORY_ENGINE", "1") != "0"
ENGINE_LOG = Path.home() / ".spark" / "advisory_engine.jsonl"
ENGINE_LOG_MAX = 500
ADVISORY_DECISION_LEDGER_FILE = Path.home() / ".spark" / "advisory_decision_ledger.jsonl"
ADVISORY_DECISION_LEDGER_ENABLED = True
ADVISORY_DECISION_LEDGER_MAX = 1500
MAX_ENGINE_MS = float(os.getenv("SPARK_ADVISORY_MAX_MS", "4000"))
INCLUDE_MIND_IN_MEMORY = os.getenv("SPARK_ADVISORY_INCLUDE_MIND", "0") == "1"
ENABLE_PREFETCH_QUEUE = os.getenv("SPARK_ADVISORY_PREFETCH_QUEUE", "1") != "0"
ENABLE_INLINE_PREFETCH_WORKER = os.getenv("SPARK_ADVISORY_PREFETCH_INLINE", "1") != "0"
PACKET_FALLBACK_EMIT_ENABLED = os.getenv("SPARK_ADVISORY_PACKET_FALLBACK_EMIT", "0") == "1"

# When live advisory is running out of budget, emit a cheap deterministic hint
# instead of returning no advice (increases real-time advisory delivery).
LIVE_QUICK_FALLBACK_ENABLED = os.getenv("SPARK_ADVISORY_LIVE_QUICK_FALLBACK", "0") == "1"
LIVE_QUICK_FALLBACK_MIN_REMAINING_MS = float(
    os.getenv("SPARK_ADVISORY_LIVE_QUICK_MIN_REMAINING_MS", "900")
)

FALLBACK_RATE_GUARD_ENABLED = os.getenv("SPARK_ADVISORY_FALLBACK_RATE_GUARD", "1") != "0"
FALLBACK_RATE_GUARD_MAX_RATIO = float(
    os.getenv("SPARK_ADVISORY_FALLBACK_RATE_MAX_RATIO", "0.55")
)
try:
    FALLBACK_RATE_GUARD_WINDOW = max(
        10, int(os.getenv("SPARK_ADVISORY_FALLBACK_RATE_WINDOW", "80") or 80)
    )
except Exception:
    FALLBACK_RATE_GUARD_WINDOW = 80
# Per-window budget cap for fallback emissions (complementary to ratio guard).
# Max N fallback emits per WINDOW tool calls. Resets when window is exhausted.
FALLBACK_BUDGET_CAP = int(os.getenv("SPARK_ADVISORY_FALLBACK_BUDGET_CAP", "1"))
FALLBACK_BUDGET_WINDOW = int(os.getenv("SPARK_ADVISORY_FALLBACK_BUDGET_WINDOW", "5"))
_fallback_budget: Dict[str, int] = {"calls": 0, "quick_emits": 0, "packet_emits": 0}

MEMORY_SCOPE_DEFAULT = str(os.getenv("SPARK_MEMORY_SCOPE_DEFAULT", "session") or "session").strip() or "session"
ACTIONABILITY_ENFORCE = os.getenv("SPARK_ADVISORY_REQUIRE_ACTION", "1") != "0"

# Action-first formatting: move the actionable "Next check" command to the first line.
ACTION_FIRST_ENABLED = os.getenv("SPARK_ADVISORY_ACTION_FIRST", "0") == "1"

# Advisory speed lever: force programmatic synthesis (no AI/network) on the hot path.
# Default: ON (Carmack-style: deterministic + fast). Override via env or tuneable.
FORCE_PROGRAMMATIC_SYNTH = os.getenv("SPARK_ADVISORY_FORCE_PROGRAMMATIC_SYNTH", "1") == "1"
# Mixed policy: allow AI synthesis selectively even when programmatic forcing is enabled.
# Default: ON — selective AI synthesis for high-authority advice improves delivery quality.
SELECTIVE_AI_SYNTH_ENABLED = os.getenv("SPARK_ADVISORY_SELECTIVE_AI_SYNTH", "1") == "1"
SELECTIVE_AI_MIN_REMAINING_MS = float(
    os.getenv("SPARK_ADVISORY_SELECTIVE_AI_MIN_REMAINING_MS", "1800")
)
SELECTIVE_AI_MIN_AUTHORITY = str(
    os.getenv("SPARK_ADVISORY_SELECTIVE_AI_MIN_AUTHORITY", "note") or "note"
).strip().lower()

_AUTHORITY_RANK = {
    "silent": 0,
    "whisper": 1,
    "note": 2,
    "warning": 3,
    "block": 4,
}

# Self-evolution speed lever: stable exact-keying for packets. When enabled, the session key includes
# the recent tool sequence (higher specificity, lower cache hit rate). Default: OFF.
SESSION_KEY_INCLUDE_RECENT_TOOLS = (
    os.getenv("SPARK_ADVISORY_SESSION_KEY_INCLUDE_RECENT_TOOLS", "0") == "1"
)

DELIVERY_STALE_SECONDS = float(os.getenv("SPARK_ADVISORY_STALE_S", "900"))
ADVISORY_TEXT_REPEAT_COOLDOWN_S = float(
    os.getenv("SPARK_ADVISORY_TEXT_REPEAT_COOLDOWN_S", "600")
)

# Cross-session dedupe for any emitted advice_id. This reduces high-frequency spam
# like "Always Read..." when session_id churns and per-session cooldowns can't help.
GLOBAL_DEDUPE_ENABLED = os.getenv("SPARK_ADVISORY_GLOBAL_DEDUPE", "1") != "0"
GLOBAL_DEDUPE_TEXT_ENABLED = os.getenv("SPARK_ADVISORY_GLOBAL_DEDUPE_BY_TEXT", "1") != "0"
try:
    GLOBAL_DEDUPE_COOLDOWN_S = float(os.getenv("SPARK_ADVISORY_GLOBAL_DEDUPE_COOLDOWN_S", "600"))
except Exception:
    GLOBAL_DEDUPE_COOLDOWN_S = 600.0
GLOBAL_DEDUPE_LOG = Path.home() / ".spark" / "advisory_global_dedupe.jsonl"
GLOBAL_DEDUPE_LOG_MAX = 5000
# Dedupe scope: global (all sessions) or tree (main + subagents under same agent tree).
GLOBAL_DEDUPE_SCOPE = str(os.getenv("SPARK_ADVISORY_GLOBAL_DEDUPE_SCOPE", "global") or "global").strip().lower()

# (pytest hygiene handled in *_recently_emitted helpers)

# ── Rejection telemetry ──────────────────────────────────────────────
# Lightweight in-memory counters for each early-exit / rejection path.
# Flushed to disk every 50 increments to avoid hot-path I/O.
REJECTION_TELEMETRY_FILE = Path.home() / ".spark" / "advisory_rejection_telemetry.json"
_rejection_counts: Dict[str, int] = {}
_rejection_flush_interval = 50
_rejection_flush_counter = 0


def _record_rejection(reason: str) -> None:
    """Increment a rejection reason counter. Flushes to disk periodically."""
    global _rejection_flush_counter
    _rejection_counts[reason] = _rejection_counts.get(reason, 0) + 1
    _rejection_flush_counter += 1
    if _rejection_flush_counter >= _rejection_flush_interval:
        _rejection_flush_counter = 0
        try:
            existing: Dict[str, int] = {}
            if REJECTION_TELEMETRY_FILE.exists():
                existing = json.loads(REJECTION_TELEMETRY_FILE.read_text(encoding="utf-8"))
            for k, v in _rejection_counts.items():
                existing[k] = existing.get(k, 0) + v
            existing["_last_flush"] = time.time()
            REJECTION_TELEMETRY_FILE.write_text(
                json.dumps(existing, indent=2), encoding="utf-8"
            )
            _rejection_counts.clear()
        except Exception:
            pass


try:
    INLINE_PREFETCH_MAX_JOBS = max(
        1, int(os.getenv("SPARK_ADVISORY_PREFETCH_INLINE_MAX_JOBS", "1") or 1)
    )
except Exception:
    INLINE_PREFETCH_MAX_JOBS = 1


def _tail_jsonl(path: Path, count: int) -> List[Dict[str, Any]]:
    if count <= 0 or not path.exists():
        return []
    chunk_size = 64 * 1024
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            buffer = b""
            lines: List[bytes] = []
            while pos > 0 and len(lines) <= count:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                data = f.read(read_size)
                buffer = data + buffer
                if b"\n" in buffer:
                    parts = buffer.split(b"\n")
                    buffer = parts[0]
                    lines = parts[1:] + lines
            if buffer:
                lines = [buffer] + lines
        out: List[Dict[str, Any]] = []
        for ln in lines[-count:]:
            ln = ln.strip()
            if not ln:
                continue
            try:
                row = json.loads(ln.decode("utf-8", errors="ignore"))
            except Exception:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out
    except Exception:
        return []


def _append_jsonl_capped(path: Path, entry: Dict[str, Any], max_lines: int) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        if max_lines <= 0:
            return
        probe = _tail_jsonl(path, max_lines + 1)
        if len(probe) <= max_lines:
            return
        path.write_text("\n".join(json.dumps(r) for r in probe[-max_lines:]) + "\n", encoding="utf-8")
    except Exception:
        return


def _emit_advisory_compat(
    emit_fn,
    gate_result,
    synthesized_text: str,
    advice_items: List[Any],
    *,
    trace_id: Optional[str],
    tool_name: str,
    route: str,
    task_plane: str,
) -> bool:
    try:
        return bool(
            emit_fn(
                gate_result,
                synthesized_text,
                advice_items,
                trace_id=trace_id,
                tool_name=tool_name,
                route=route,
                task_plane=task_plane,
            )
        )
    except TypeError as exc:
        msg = str(exc)
        if "unexpected keyword argument" not in msg and "positional arguments but" not in msg:
            raise
        # Backward-compatible call shape used by older tests/helpers.
        return bool(emit_fn(gate_result, synthesized_text, advice_items))


def _global_recently_emitted(
    *,
    tool_name: str,
    advice_id: str,
    now_ts: float,
    cooldown_s: float,
    scope_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    # Keep tests hermetic: don't consult the user's real ~/.spark dedupe logs.
    # (Allow tests that monkeypatch the log path to still exercise the logic.)
    if os.getenv("PYTEST_CURRENT_TEST"):
        try:
            default_log = (Path.home() / ".spark" / "advisory_global_dedupe.jsonl").resolve()
            if GLOBAL_DEDUPE_LOG.resolve() == default_log:
                return None
        except Exception:
            return None
    aid = str(advice_id or "").strip()
    if not aid:
        return None
    try:
        rows = _tail_jsonl(GLOBAL_DEDUPE_LOG, 400)
    except Exception:
        return None
    scope = str(scope_key or "").strip()
    for row in reversed(rows):
        try:
            if str(row.get("advice_id") or "").strip() != aid:
                continue
            if scope and str(row.get("scope_key") or "").strip() not in {"", scope}:
                continue
            ts = float(row.get("ts") or 0.0)
        except Exception:
            continue
        if ts <= 0:
            continue
        age_s = now_ts - ts
        if age_s < 0:
            continue
        if age_s <= max(0.0, float(cooldown_s)):
            return {"age_s": age_s, "cooldown_s": cooldown_s, "row": row}
        break
    return None


def _global_recently_emitted_text_sig(
    *,
    text_sig: str,
    now_ts: float,
    cooldown_s: float,
    scope_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    # Keep tests hermetic: don't consult the user's real ~/.spark dedupe logs.
    # (Allow tests that monkeypatch the log path to still exercise the logic.)
    if os.getenv("PYTEST_CURRENT_TEST"):
        try:
            default_log = (Path.home() / ".spark" / "advisory_global_dedupe.jsonl").resolve()
            if GLOBAL_DEDUPE_LOG.resolve() == default_log:
                return None
        except Exception:
            return None
    sig = str(text_sig or "").strip()
    if not sig:
        return None
    try:
        rows = _tail_jsonl(GLOBAL_DEDUPE_LOG, 400)
    except Exception:
        return None
    scope = str(scope_key or "").strip()
    for row in reversed(rows):
        try:
            if str(row.get("text_sig") or "").strip() != sig:
                continue
            if scope and str(row.get("scope_key") or "").strip() not in {"", scope}:
                continue
            ts = float(row.get("ts") or 0.0)
        except Exception:
            continue
        if ts <= 0:
            continue
        age_s = now_ts - ts
        if age_s < 0:
            continue
        if age_s <= max(0.0, float(cooldown_s)):
            return {"age_s": age_s, "cooldown_s": cooldown_s, "row": row}
        break
    return None


def _load_engine_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load advisory engine tuneables via config_authority resolve_section."""
    tuneables = path or (Path.home() / ".spark" / "tuneables.json")
    if (
        path is None
        and "pytest" in sys.modules
        and str(os.environ.get("SPARK_TEST_ALLOW_HOME_TUNEABLES", "")).strip().lower()
        not in {"1", "true", "yes", "on"}
    ):
        try:
            if tuneables.resolve() == (Path.home() / ".spark" / "tuneables.json").resolve():
                return {}
        except Exception:
            return {}
    if not tuneables.exists():
        return {}
    from .config_authority import resolve_section
    cfg = resolve_section("advisory_engine", runtime_path=tuneables).data
    return cfg if isinstance(cfg, dict) else {}


def _parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def apply_engine_config(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    """Apply advisory engine runtime tuneables."""
    global ENGINE_ENABLED
    global MAX_ENGINE_MS
    global INCLUDE_MIND_IN_MEMORY
    global ENABLE_PREFETCH_QUEUE
    global ENABLE_INLINE_PREFETCH_WORKER
    global PACKET_FALLBACK_EMIT_ENABLED
    global LIVE_QUICK_FALLBACK_ENABLED
    global LIVE_QUICK_FALLBACK_MIN_REMAINING_MS
    global FALLBACK_RATE_GUARD_ENABLED
    global FALLBACK_RATE_GUARD_MAX_RATIO
    global FALLBACK_RATE_GUARD_WINDOW
    global FALLBACK_BUDGET_CAP
    global FALLBACK_BUDGET_WINDOW
    global INLINE_PREFETCH_MAX_JOBS
    global ACTIONABILITY_ENFORCE
    global DELIVERY_STALE_SECONDS
    global ADVISORY_TEXT_REPEAT_COOLDOWN_S
    global GLOBAL_DEDUPE_COOLDOWN_S
    global FORCE_PROGRAMMATIC_SYNTH
    global SELECTIVE_AI_SYNTH_ENABLED
    global SELECTIVE_AI_MIN_REMAINING_MS
    global SELECTIVE_AI_MIN_AUTHORITY
    global SESSION_KEY_INCLUDE_RECENT_TOOLS

    applied: List[str] = []
    warnings: List[str] = []
    if not isinstance(cfg, dict):
        return {"applied": applied, "warnings": warnings}

    if "enabled" in cfg:
        ENGINE_ENABLED = _parse_bool(cfg.get("enabled"), ENGINE_ENABLED)
        applied.append("enabled")

    if "max_ms" in cfg:
        try:
            MAX_ENGINE_MS = max(250.0, min(20000.0, float(cfg.get("max_ms"))))
            applied.append("max_ms")
        except Exception:
            warnings.append("invalid_max_ms")

    if "include_mind" in cfg:
        INCLUDE_MIND_IN_MEMORY = _parse_bool(cfg.get("include_mind"), INCLUDE_MIND_IN_MEMORY)
        applied.append("include_mind")

    if "prefetch_queue_enabled" in cfg:
        ENABLE_PREFETCH_QUEUE = _parse_bool(cfg.get("prefetch_queue_enabled"), ENABLE_PREFETCH_QUEUE)
        applied.append("prefetch_queue_enabled")

    if "prefetch_inline_enabled" in cfg:
        ENABLE_INLINE_PREFETCH_WORKER = _parse_bool(
            cfg.get("prefetch_inline_enabled"),
            ENABLE_INLINE_PREFETCH_WORKER,
        )
        applied.append("prefetch_inline_enabled")

    if "packet_fallback_emit_enabled" in cfg:
        PACKET_FALLBACK_EMIT_ENABLED = _parse_bool(
            cfg.get("packet_fallback_emit_enabled"),
            PACKET_FALLBACK_EMIT_ENABLED,
        )
        applied.append("packet_fallback_emit_enabled")

    if "live_quick_fallback_enabled" in cfg:
        LIVE_QUICK_FALLBACK_ENABLED = _parse_bool(
            cfg.get("live_quick_fallback_enabled"),
            LIVE_QUICK_FALLBACK_ENABLED,
        )
        applied.append("live_quick_fallback_enabled")

    if "live_quick_min_remaining_ms" in cfg:
        try:
            LIVE_QUICK_FALLBACK_MIN_REMAINING_MS = max(
                100.0, min(5000.0, float(cfg.get("live_quick_min_remaining_ms")))
            )
            applied.append("live_quick_min_remaining_ms")
        except Exception:
            warnings.append("invalid_live_quick_min_remaining_ms")

    if "fallback_rate_guard_enabled" in cfg:
        FALLBACK_RATE_GUARD_ENABLED = _parse_bool(
            cfg.get("fallback_rate_guard_enabled"),
            FALLBACK_RATE_GUARD_ENABLED,
        )
        applied.append("fallback_rate_guard_enabled")

    if "fallback_rate_max_ratio" in cfg:
        try:
            FALLBACK_RATE_GUARD_MAX_RATIO = max(
                0.0,
                min(1.0, float(cfg.get("fallback_rate_max_ratio") or FALLBACK_RATE_GUARD_MAX_RATIO)),
            )
            applied.append("fallback_rate_max_ratio")
        except Exception:
            warnings.append("invalid_fallback_rate_max_ratio")

    if "fallback_rate_window" in cfg:
        try:
            FALLBACK_RATE_GUARD_WINDOW = max(
                10, min(500, int(cfg.get("fallback_rate_window") or FALLBACK_RATE_GUARD_WINDOW))
            )
            applied.append("fallback_rate_window")
        except Exception:
            warnings.append("invalid_fallback_rate_window")

    if "fallback_budget_cap" in cfg:
        try:
            raw = cfg["fallback_budget_cap"]
            FALLBACK_BUDGET_CAP = max(0, int(raw if raw is not None else FALLBACK_BUDGET_CAP))
            applied.append("fallback_budget_cap")
        except Exception:
            warnings.append("invalid_fallback_budget_cap")

    if "fallback_budget_window" in cfg:
        try:
            raw = cfg["fallback_budget_window"]
            FALLBACK_BUDGET_WINDOW = max(1, int(raw if raw is not None else FALLBACK_BUDGET_WINDOW))
            applied.append("fallback_budget_window")
        except Exception:
            warnings.append("invalid_fallback_budget_window")

    if "prefetch_inline_max_jobs" in cfg:
        try:
            INLINE_PREFETCH_MAX_JOBS = max(1, min(20, int(cfg.get("prefetch_inline_max_jobs") or 1)))
            applied.append("prefetch_inline_max_jobs")
        except Exception:
            warnings.append("invalid_prefetch_inline_max_jobs")

    if "actionability_enforce" in cfg:
        ACTIONABILITY_ENFORCE = _parse_bool(
            cfg.get("actionability_enforce"),
            ACTIONABILITY_ENFORCE,
        )
        applied.append("actionability_enforce")

    if "force_programmatic_synth" in cfg:
        FORCE_PROGRAMMATIC_SYNTH = _parse_bool(
            cfg.get("force_programmatic_synth"),
            FORCE_PROGRAMMATIC_SYNTH,
        )
        applied.append("force_programmatic_synth")

    if "selective_ai_synth_enabled" in cfg:
        SELECTIVE_AI_SYNTH_ENABLED = _parse_bool(
            cfg.get("selective_ai_synth_enabled"),
            SELECTIVE_AI_SYNTH_ENABLED,
        )
        applied.append("selective_ai_synth_enabled")

    if "selective_ai_min_remaining_ms" in cfg:
        try:
            SELECTIVE_AI_MIN_REMAINING_MS = max(
                100.0,
                min(8000.0, float(cfg.get("selective_ai_min_remaining_ms") or SELECTIVE_AI_MIN_REMAINING_MS)),
            )
            applied.append("selective_ai_min_remaining_ms")
        except Exception:
            warnings.append("invalid_selective_ai_min_remaining_ms")

    if "selective_ai_min_authority" in cfg:
        auth = str(cfg.get("selective_ai_min_authority") or "").strip().lower()
        if auth in _AUTHORITY_RANK:
            SELECTIVE_AI_MIN_AUTHORITY = auth
            applied.append("selective_ai_min_authority")
        else:
            warnings.append("invalid_selective_ai_min_authority")

    if "session_key_include_recent_tools" in cfg:
        SESSION_KEY_INCLUDE_RECENT_TOOLS = _parse_bool(
            cfg.get("session_key_include_recent_tools"),
            SESSION_KEY_INCLUDE_RECENT_TOOLS,
        )
        applied.append("session_key_include_recent_tools")

    if "delivery_stale_s" in cfg:
        try:
            DELIVERY_STALE_SECONDS = max(
                30.0,
                min(86400.0, float(cfg.get("delivery_stale_s") or DELIVERY_STALE_SECONDS)),
            )
            applied.append("delivery_stale_s")
        except Exception:
            warnings.append("invalid_delivery_stale_s")

    if "advisory_text_repeat_cooldown_s" in cfg:
        try:
            ADVISORY_TEXT_REPEAT_COOLDOWN_S = max(
                0.0,
                min(86400.0, float(cfg.get("advisory_text_repeat_cooldown_s") or 0.0)),
            )
            applied.append("advisory_text_repeat_cooldown_s")
        except Exception:
            warnings.append("invalid_advisory_text_repeat_cooldown_s")

    if "global_dedupe_cooldown_s" in cfg:
        try:
            GLOBAL_DEDUPE_COOLDOWN_S = max(
                0.0,
                min(86400.0, float(cfg.get("global_dedupe_cooldown_s") or 0.0)),
            )
            applied.append("global_dedupe_cooldown_s")
        except Exception:
            warnings.append("invalid_global_dedupe_cooldown_s")
    return {"applied": applied, "warnings": warnings}


def get_engine_config() -> Dict[str, Any]:
    return {
        "enabled": bool(ENGINE_ENABLED),
        "max_ms": float(MAX_ENGINE_MS),
        "include_mind": bool(INCLUDE_MIND_IN_MEMORY),
        "prefetch_queue_enabled": bool(ENABLE_PREFETCH_QUEUE),
        "prefetch_inline_enabled": bool(ENABLE_INLINE_PREFETCH_WORKER),
        "packet_fallback_emit_enabled": bool(PACKET_FALLBACK_EMIT_ENABLED),
        "fallback_rate_guard_enabled": bool(FALLBACK_RATE_GUARD_ENABLED),
        "fallback_rate_max_ratio": float(FALLBACK_RATE_GUARD_MAX_RATIO),
        "fallback_rate_window": int(FALLBACK_RATE_GUARD_WINDOW),
        "fallback_budget_cap": int(FALLBACK_BUDGET_CAP),
        "fallback_budget_window": int(FALLBACK_BUDGET_WINDOW),
        "prefetch_inline_max_jobs": int(INLINE_PREFETCH_MAX_JOBS),
        "actionability_enforce": bool(ACTIONABILITY_ENFORCE),
        "force_programmatic_synth": bool(FORCE_PROGRAMMATIC_SYNTH),
        "selective_ai_synth_enabled": bool(SELECTIVE_AI_SYNTH_ENABLED),
        "selective_ai_min_remaining_ms": float(SELECTIVE_AI_MIN_REMAINING_MS),
        "selective_ai_min_authority": str(SELECTIVE_AI_MIN_AUTHORITY),
        "session_key_include_recent_tools": bool(SESSION_KEY_INCLUDE_RECENT_TOOLS),
        "delivery_stale_s": float(DELIVERY_STALE_SECONDS),
        "advisory_text_repeat_cooldown_s": float(ADVISORY_TEXT_REPEAT_COOLDOWN_S),
        "global_dedupe_cooldown_s": float(GLOBAL_DEDUPE_COOLDOWN_S),
    }


_BOOT_ENGINE_CFG = _load_engine_config()
if _BOOT_ENGINE_CFG:
    apply_engine_config(_BOOT_ENGINE_CFG)

# Register for hot-reload so tuneables.json changes apply without restart
try:
    from .tuneables_reload import register_reload as _engine_register
    _engine_register("advisory_engine", apply_engine_config, label="advisory_engine.apply_config")
except Exception:
    pass


def _project_key() -> str:
    try:
        from .memory_banks import infer_project_key

        key = infer_project_key()
        if key:
            return str(key)
    except Exception:
        pass
    return "unknown_project"


def _intent_context(state, tool_name: str) -> Dict[str, Any]:
    from .advisory_intent_taxonomy import map_intent

    prompt = state.user_intent or ""
    intent = map_intent(prompt, tool_name=tool_name)
    state.intent_family = intent.get("intent_family", "emergent_other")
    state.intent_confidence = float(intent.get("confidence", 0.0) or 0.0)
    state.task_plane = intent.get("task_plane", "build_delivery")
    state.intent_reason = intent.get("reason", "fallback")
    return intent


def _session_context_key(state, tool_name: str) -> str:
    from .advisory_intent_taxonomy import build_session_context_key
    from .advisory_state import get_recent_tool_sequence

    # Default: stable session key so prefetched packets and exact lookups hit reliably.
    # Opt-in volatility via recent tool inclusion when you want higher specificity.
    if not SESSION_KEY_INCLUDE_RECENT_TOOLS:
        raw = f"{state.session_id}|{(state.intent_family or 'emergent_other').strip()}"
        return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:12]

    recent_tools = get_recent_tool_sequence(state, n=5)
    return build_session_context_key(
        # Tool/phase are already represented elsewhere in the exact key; keep the session key focused on
        # the volatile recency signal when this mode is enabled.
        task_phase="any",
        intent_family=state.intent_family,
        tool_name="*",
        recent_tools=recent_tools,
    )


def _packet_to_advice(packet: Dict[str, Any]) -> List[Any]:
    from .advisor import Advice

    advice_rows = packet.get("advice_items") or []
    out: List[Any] = []
    stable_key_sources = {
        "cognitive",
        "bank",
        "mind",
        "chip",
        "skill",
        "niche",
        "convo",
        "eidos",
        "engagement",
        "replay",
        "opportunity",
    }
    for row in advice_rows[:8]:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        source = str(row.get("source") or "packet")
        canonical_source = source.strip().lower()
        if canonical_source.startswith("semantic") or canonical_source == "trigger":
            canonical_source = "cognitive"

        quality_raw = row.get("advisory_quality")
        if not isinstance(quality_raw, dict):
            quality_raw = {}
        readiness_raw = row.get("advisory_readiness")
        try:
            readiness_value = float(readiness_raw)
        except Exception:
            readiness_value = 0.0

        category_raw = row.get("category") or quality_raw.get("domain") or row.get("domain")
        category = str(category_raw or canonical_source or "general")
        category = category.replace(":", "_").strip().lower()[:64]

        insight_key_raw = row.get("insight_key")
        insight_key = str(insight_key_raw or "").strip()
        advice_id = str(
            row.get("advice_id") or f"{packet.get('packet_id', 'pkt')}_item_{len(out)}"
        )
        # Migrate legacy/random packet advice_ids to stable IDs when we have a durable key.
        if insight_key_raw and insight_key and canonical_source in stable_key_sources:
            advice_id = f"{canonical_source}:{insight_key}"
        out.append(
            Advice(
                advice_id=advice_id,
                insight_key=insight_key or str(packet.get("packet_id") or ""),
                text=text,
                confidence=float(row.get("confidence") or 0.6),
                source=source,
                context_match=float(row.get("context_match") or 0.8),
                reason=str(row.get("reason") or ""),
                category=category,
                advisory_quality=quality_raw,
                advisory_readiness=readiness_value,
            )
        )
    if out:
        return out

    text = str(packet.get("advisory_text") or "").strip()
    if not text:
        return []
    return [
        Advice(
            advice_id=f"{packet.get('packet_id', 'pkt')}_fallback",
            insight_key=str(packet.get("packet_id") or "packet"),
            text=text,
            confidence=0.7,
            source="packet",
            context_match=0.8,
            reason="packet_cached_advisory",
        )
    ]


def _advice_to_rows(advice_items: List[Any], max_rows: int = 6) -> List[Dict[str, Any]]:
    return _advice_to_rows_with_proof(advice_items, trace_id=None, max_rows=max_rows)


def _proof_refs_for_advice(item: Any, trace_id: Optional[str]) -> Dict[str, Any]:
    advice_id = str(getattr(item, "advice_id", "") or "")
    insight_key = str(getattr(item, "insight_key", "") or "")
    source = str(getattr(item, "source", "advisor") or "advisor")
    reason = str(getattr(item, "reason", "") or "").strip()
    refs: Dict[str, Any] = {
        "advice_id": advice_id,
        "insight_key": insight_key,
        "source": source,
    }
    if trace_id:
        refs["trace_id"] = str(trace_id)
    if reason:
        refs["reason"] = reason[:240]
    return refs


def _evidence_hash_for_row(*, advice_text: str, proof_refs: Dict[str, Any]) -> str:
    raw = {
        "text": str(advice_text or "").strip().lower(),
        "advice_id": str(proof_refs.get("advice_id") or ""),
        "insight_key": str(proof_refs.get("insight_key") or ""),
        "source": str(proof_refs.get("source") or ""),
        "trace_id": str(proof_refs.get("trace_id") or ""),
    }
    blob = json.dumps(raw, sort_keys=True, ensure_ascii=True)
    return hashlib.sha1(blob.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _advice_to_rows_with_proof(
    advice_items: List[Any],
    *,
    trace_id: Optional[str],
    max_rows: int = 6,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in advice_items[:max_rows]:
        text = str(getattr(item, "text", "") or "")
        proof_refs = _proof_refs_for_advice(item, trace_id=trace_id)
        rows.append(
            {
                "advice_id": str(getattr(item, "advice_id", "") or f"aid_{len(rows)}"),
                "insight_key": str(getattr(item, "insight_key", "") or ""),
                "text": text,
                "confidence": float(getattr(item, "confidence", 0.5) or 0.5),
                "source": str(getattr(item, "source", "advisor") or "advisor"),
                "context_match": float(getattr(item, "context_match", 0.5) or 0.5),
                "reason": str(getattr(item, "reason", "") or ""),
                "proof_refs": proof_refs,
                "evidence_hash": _evidence_hash_for_row(advice_text=text, proof_refs=proof_refs),
            }
        )
    return rows


def _baseline_text(intent_family: str) -> str:
    defaults = {
        "auth_security": "Validate auth inputs server-side and redact sensitive tokens from logs before changes.",
        "deployment_ops": "Prefer reversible deployment steps and verify rollback path before release actions.",
        "testing_validation": "Run focused tests after edits and confirm failures are reproducible before broad changes.",
        "schema_contracts": "Check schema or contract compatibility before editing interfaces or payload shapes.",
        "performance_latency": "Preserve response-time budget while editing and measure before and after hot-path changes.",
        "tool_reliability": "Review target files before edits and keep changes minimal when failure risk is high.",
        "knowledge_alignment": "Align edits with existing project patterns and docs before changing behavior.",
        "team_coordination": "Clarify ownership and next action before delegating or switching tracks.",
        "orchestration_execution": "Respect dependency order and unblock critical path items before low-priority work.",
        "stakeholder_alignment": "Prioritize changes that match agreed outcomes and surface tradeoffs early.",
        "research_decision_support": "Compare options against constraints and record decision rationale explicitly.",
        "emergent_other": "Use conservative, test-backed edits and verify assumptions before irreversible actions.",
    }
    return defaults.get(intent_family, defaults["emergent_other"])


def _fallback_synth_text_from_emitted(
    emitted_advice: List[Any],
    *,
    intent_family: str,
    max_chars: int = 320,
) -> str:
    """Derive deterministic synthesis text when LLM/programmatic synth is empty."""
    for item in list(emitted_advice or [])[:3]:
        text = str(getattr(item, "text", "") or "").strip()
        if not text:
            continue
        compact = re.sub(r"\s+", " ", text).strip()
        if not compact:
            continue
        if len(compact) > max(60, int(max_chars)):
            compact = compact[: max(60, int(max_chars)) - 3].rstrip() + "..."
        return compact
    return _baseline_text(intent_family).strip()


def _text_fingerprint(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not cleaned:
        return ""
    return hashlib.sha1(cleaned.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _duplicate_repeat_state(state, advisory_text: str) -> Dict[str, Any]:
    now = time.time()
    fingerprint = _text_fingerprint(advisory_text)
    last_fingerprint = str(getattr(state, "last_advisory_text_fingerprint", "") or "")
    last_at = float(getattr(state, "last_advisory_at", 0.0) or 0.0)
    age_s = max(0.0, now - last_at) if last_at > 0 else None
    repeat = bool(
        fingerprint
        and ADVISORY_TEXT_REPEAT_COOLDOWN_S > 0
        and fingerprint == last_fingerprint
        and age_s is not None
        and age_s < ADVISORY_TEXT_REPEAT_COOLDOWN_S
    )
    return {
        "repeat": repeat,
        "fingerprint": fingerprint,
        "age_s": round(age_s, 2) if age_s is not None else None,
        "cooldown_s": float(ADVISORY_TEXT_REPEAT_COOLDOWN_S),
    }


def _provider_path_from_route(route: str) -> str:
    value = str(route or "").strip().lower()
    if value.startswith("packet"):
        return "packet_store"
    if value.startswith("live"):
        return "live_direct"
    if "fallback" in value:
        return "deterministic_fallback"
    if value == "post_tool":
        return "post_tool_feedback"
    if value == "user_prompt":
        return "prompt_prefetch"
    return "unknown"


def _session_lineage(session_id: str) -> Dict[str, Any]:
    sid = str(session_id or "").strip()
    if not sid:
        return {
            "session_kind": "unknown",
            "is_subagent": False,
            "depth_hint": 0,
            "session_tree_key": "",
            "root_session_hint": "",
            "parent_session_hint": "",
        }

    if ":subagent:" in sid:
        head = sid.split(":subagent:", 1)[0]
        return {
            "session_kind": "subagent",
            "is_subagent": True,
            "depth_hint": 2,
            "session_tree_key": head,
            "root_session_hint": f"{head}:main",
            "parent_session_hint": f"{head}:main",
        }
    if ":cron:" in sid:
        head = sid.split(":cron:", 1)[0]
        return {
            "session_kind": "cron",
            "is_subagent": False,
            "depth_hint": 1,
            "session_tree_key": head,
            "root_session_hint": sid,
            "parent_session_hint": "",
        }
    if sid.endswith(":main"):
        return {
            "session_kind": "main",
            "is_subagent": False,
            "depth_hint": 1,
            "session_tree_key": sid.rsplit(":main", 1)[0],
            "root_session_hint": sid,
            "parent_session_hint": "",
        }

    return {
        "session_kind": "other",
        "is_subagent": False,
        "depth_hint": 1,
        "session_tree_key": sid,
        "root_session_hint": sid,
        "parent_session_hint": "",
    }


def _dedupe_scope_key(session_id: str) -> str:
    scope = str(GLOBAL_DEDUPE_SCOPE or "global").strip().lower()
    if scope == "tree":
        lineage = _session_lineage(session_id)
        key = str(lineage.get("session_tree_key") or "").strip()
        return key or str(session_id or "")
    return "global"


def _diagnostics_envelope(
    *,
    session_id: str,
    trace_id: Optional[str],
    route: str,
    session_context_key: str = "",
    scope: Optional[str] = None,
    memory_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    bundle = memory_bundle if isinstance(memory_bundle, dict) else {}
    sources = bundle.get("sources") if isinstance(bundle.get("sources"), dict) else {}
    source_counts: Dict[str, int] = {}
    for name, meta in sources.items():
        if isinstance(meta, dict):
            source_counts[str(name)] = int(meta.get("count", 0) or 0)

    missing_sources = bundle.get("missing_sources")
    if not isinstance(missing_sources, list):
        missing_sources = [name for name, count in source_counts.items() if count <= 0]

    resolved_scope = str(scope or bundle.get("scope") or MEMORY_SCOPE_DEFAULT).strip() or "session"
    lineage = _session_lineage(session_id)
    envelope: Dict[str, Any] = {
        "session_id": str(session_id or ""),
        "trace_id": str(trace_id or ""),
        "session_context_key": str(session_context_key or ""),
        "scope": resolved_scope,
        "provider_path": _provider_path_from_route(route),
        "source_counts": source_counts,
        "missing_sources": missing_sources,
        "session_kind": lineage.get("session_kind"),
        "is_subagent": bool(lineage.get("is_subagent")),
        "depth_hint": int(lineage.get("depth_hint") or 0),
        "session_tree_key": str(lineage.get("session_tree_key") or ""),
        "root_session_hint": str(lineage.get("root_session_hint") or ""),
        "parent_session_hint": str(lineage.get("parent_session_hint") or ""),
    }
    if "memory_absent_declared" in bundle:
        envelope["memory_absent_declared"] = bool(bundle.get("memory_absent_declared"))
    return envelope


def _advice_source_counts(advice_items: Optional[List[Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in advice_items or []:
        try:
            source = str(getattr(item, "source", "") or "").strip().lower()
        except Exception:
            source = ""
        if not source:
            continue
        counts[source] = counts.get(source, 0) + 1
    return counts


def _authority_rank(authority: str) -> int:
    return int(_AUTHORITY_RANK.get(str(authority or "").strip().lower(), -1))


def _should_use_selective_ai_synth(*, gate_result: Any, remaining_ms: float) -> bool:
    if not FORCE_PROGRAMMATIC_SYNTH:
        return False
    if not SELECTIVE_AI_SYNTH_ENABLED:
        return False
    if float(remaining_ms) < float(SELECTIVE_AI_MIN_REMAINING_MS):
        return False
    emitted = list(getattr(gate_result, "emitted", []) or [])
    if not emitted:
        return False
    top_authority = str(getattr(emitted[0], "authority", "") or "").strip().lower()
    min_auth = str(SELECTIVE_AI_MIN_AUTHORITY or "warning").strip().lower()
    return _authority_rank(top_authority) >= _authority_rank(min_auth)


def _record_advisory_gate_drop(
    *,
    stage: str,
    reason: str,
    tool_name: str,
    intent_family: str,
    task_plane: str,
    route: str,
    packet_id: Optional[str],
    advice_items: Optional[List[Any]] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> None:
    sample = None
    for item in advice_items or []:
        txt = str(getattr(item, "text", "") or "").strip()
        if txt:
            sample = item
            break
    if sample is None and advice_items:
        sample = advice_items[0]

    sample_quality = getattr(sample, "advisory_quality", None) if sample is not None else None
    sample_readiness = getattr(sample, "advisory_readiness", None) if sample is not None else None
    sample_text = str(getattr(sample, "text", "") or "") if sample is not None else ""
    if not sample_text and extras:
        sample_text = str(extras.get("text") or "")

    extra_payload: Dict[str, Any] = {
        "stage": stage,
        "tool_name": str(tool_name or ""),
        "intent_family": str(intent_family or ""),
        "task_plane": str(task_plane or ""),
        "route": str(route or ""),
        "packet_id": str(packet_id or ""),
    }
    if extras:
        extra_payload.update({k: v for k, v in extras.items() if v is not None})

    record_quarantine_item(
        source="advisory_engine",
        stage=stage,
        reason=reason,
        text=sample_text,
        advisory_quality=sample_quality if isinstance(sample_quality, dict) else None,
        advisory_readiness=sample_readiness,
        meta=extra_payload,
    )


def _snapshot_gate_decisions(gate_result: Any) -> List[Dict[str, Any]]:
    decisions = list(getattr(gate_result, "decisions", []) or [])
    out: List[Dict[str, Any]] = []
    for decision in decisions:
        try:
            out.append({
                "advice_id": str(getattr(decision, "advice_id", "") or ""),
                "authority": str(getattr(decision, "authority", "") or ""),
                "emit": bool(getattr(decision, "emit", False)),
                "score": float(getattr(decision, "adjusted_score", 0.0) or 0.0),
                "reason": str(getattr(decision, "reason", "") or ""),
                "original_score": float(getattr(decision, "original_score", 0.0) or 0.0),
            })
        except Exception:
            continue
    return out


def _record_advisory_decision_ledger(
    *,
    stage: str,
    outcome: str,
    tool_name: str,
    intent_family: str,
    task_plane: str,
    route: str,
    packet_id: Optional[str],
    advice_items: Optional[List[Any]],
    gate_result: Optional[Any],
    session_id: str,
    trace_id: Optional[str] = None,
    extras: Optional[Dict[str, Any]] = None,
    suppressed_reasons: Optional[Dict[str, int]] = None,
) -> None:
    if not ADVISORY_DECISION_LEDGER_ENABLED:
        return
    try:
        snapshot = _snapshot_gate_decisions(gate_result)
        suppressed = []
        emitted = []
        for row in snapshot:
            if row.get("emit"):
                emitted.append(row)
            else:
                suppressed.append(row)

        suppressed_summary: List[Dict[str, Any]] = []
        reason_counts = dict(suppressed_reasons or {})
        if not reason_counts and suppressed:
            for row in suppressed:
                reason = str(row.get("reason", "") or "unspecified").strip()
                reason_counts[reason] = int(reason_counts.get(reason, 0) + 1)
        for reason, count in sorted(reason_counts.items(), key=lambda kv: kv[1], reverse=True):
            suppressed_summary.append({"reason": str(reason), "count": int(count)})
        selected_ids = [str(row.get("advice_id", "") or "").strip() for row in emitted]
        suppressed_ids = [str(row.get("advice_id", "") or "").strip() for row in suppressed]
        route_clean = str(route or "").strip()

        entry: Dict[str, Any] = {
            "ts": time.time(),
            "stage": str(stage or "").strip(),
            "outcome": str(outcome or "").strip(),
            "session_id": str(session_id or ""),
            "trace_id": str(trace_id or ""),
            "tool": str(tool_name or ""),
            "intent_family": str(intent_family or ""),
            "task_plane": str(task_plane or ""),
            "route": route_clean,
            "packet_id": str(packet_id or ""),
            "route_hint": str(route_clean or ""),
            "selected_count": int(len(selected_ids)),
            "suppressed_count": int(len(suppressed_ids)),
            "selected_ids": selected_ids[:12],
            "suppressed_ids": suppressed_ids[:12],
            "suppressed_reasons": suppressed_summary[:12],
            "decision_count": len(snapshot),
        }
        if extras:
            entry.update({k: v for k, v in extras.items() if v is not None})

        if isinstance(advice_items, list):
            entry["retrieved_count"] = len(advice_items)
            entry["source_counts"] = _advice_source_counts(advice_items)
        _append_jsonl_capped(
            ADVISORY_DECISION_LEDGER_FILE,
            entry,
            max_lines=ADVISORY_DECISION_LEDGER_MAX,
        )
    except Exception:
        pass


def _gate_suppression_metadata(gate_result: Any) -> Dict[str, Any]:
    suppressed = list(getattr(gate_result, "suppressed", []) or [])
    if not suppressed:
        return {}
    reason_counts: Dict[str, int] = {}
    for decision in suppressed:
        reason = str(getattr(decision, "reason", "") or "").strip() or "unspecified"
        reason_counts[reason] = int(reason_counts.get(reason, 0) + 1)
    ranked = sorted(reason_counts.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "gate_reason": str(ranked[0][0]),
        "suppressed_count": int(len(suppressed)),
        "suppressed_reasons": [
            {"reason": str(reason), "count": int(count)}
            for reason, count in ranked[:8]
        ],
    }


_NON_MEMORY_ADVICE_SOURCES = {"quick", "baseline", "prefetch"}


def _infer_memory_absent_declared(source_counts: Dict[str, int]) -> bool:
    """Heuristic: declare memory-absent when advice came only from deterministic/non-memory sources."""
    if not source_counts:
        return True
    for name, count in (source_counts or {}).items():
        if int(count or 0) <= 0:
            continue
        if str(name or "").strip().lower() not in _NON_MEMORY_ADVICE_SOURCES:
            return False
    return True


def _default_action_command(tool_name: str, task_plane: str) -> str:
    tool = str(tool_name or "").strip().lower()
    plane = str(task_plane or "").strip().lower()
    if tool in {"edit", "write", "notebookedit"}:
        return "python -m pytest -q"
    if tool in {"read", "glob", "grep"}:
        return 'rg -n "TODO|FIXME" .'
    if tool == "bash":
        return "python scripts/status_local.py"
    if plane in {"build_delivery", "execution"}:
        return "python -m pytest -q"
    return "python scripts/status_local.py"


def _has_actionable_command(text: str) -> bool:
    body = str(text or "")
    if not body.strip():
        return False
    if re.search(r"`[^`]{3,}`", body):
        return True
    lowered = body.lower()
    if "next check:" in lowered or "next command:" in lowered:
        return True
    return False


def _ensure_actionability(text: str, tool_name: str, task_plane: str) -> Dict[str, Any]:
    original = str(text or "").strip()
    if not original:
        return {"text": "", "added": False, "command": ""}
    if not ACTIONABILITY_ENFORCE:
        return {"text": original, "added": False, "command": ""}
    if _has_actionable_command(original):
        return {"text": original, "added": False, "command": ""}

    command = _default_action_command(tool_name, task_plane)
    suffix = f" Next check: `{command}`."
    updated = f"{original}{suffix}"
    return {"text": updated, "added": True, "command": command}


def _action_first_format(text: str) -> str:
    """Move the `Next check: ` command to the first line.

    This keeps the same content but makes the action visible instantly, which
    tends to improve follow-through.

    If no `Next check: ...` is present, returns the input unchanged.
    """
    body = str(text or "").strip()
    if not body:
        return ""

    # Already action-first.
    if body.lower().startswith("next check:"):
        return body

    m = re.search(r"\bnext check:\s*`([^`]{3,})`\.?", body, flags=re.IGNORECASE)
    if not m:
        return body

    cmd = str(m.group(1) or "").strip()
    if not cmd:
        return body

    # Remove the inline clause and clean punctuation.
    cleaned = re.sub(r"\s*\bnext check:\s*`[^`]{3,}`\.?\s*", " ", body, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return f"Next check: `{cmd}`.\n{cleaned}".strip()


def _derive_delivery_badge(
    events: List[Dict[str, Any]],
    *,
    now_ts: Optional[float] = None,
    stale_after_s: Optional[float] = None,
) -> Dict[str, Any]:
    now = float(now_ts if now_ts is not None else time.time())
    stale_s = float(stale_after_s if stale_after_s is not None else DELIVERY_STALE_SECONDS)
    relevant_events = {
        "emitted",
        "fallback_emit",
        "fallback_emit_failed",
        "no_emit",
        "no_advice",
        "duplicate_suppressed",
        "synth_empty",
        "engine_error",
        "post_tool_error",
        "user_prompt_error",
    }
    latest: Optional[Dict[str, Any]] = None
    for row in events:
        if not isinstance(row, dict):
            continue
        if str(row.get("event") or "") not in relevant_events:
            continue
        ts = float(row.get("ts") or 0.0)
        if latest is None or ts >= float(latest.get("ts") or 0.0):
            latest = row

    if latest is None:
        return {"state": "stale", "reason": "no_delivery_events", "age_s": None, "event": None}

    ts = float(latest.get("ts") or 0.0)
    age_s = max(0.0, now - ts) if ts > 0 else None
    if age_s is not None and age_s > stale_s:
        return {
            "state": "stale",
            "reason": "last_event_too_old",
            "age_s": round(age_s, 1),
            "event": latest.get("event"),
            "delivery_mode": latest.get("delivery_mode"),
        }

    event = str(latest.get("event") or "")
    mode = str(latest.get("delivery_mode") or "")
    if event == "emitted" and mode == "live":
        state = "live"
    elif event == "fallback_emit" or mode == "fallback":
        state = "fallback"
    else:
        state = "blocked"
    return {
        "state": state,
        "reason": event,
        "age_s": round(age_s, 1) if age_s is not None else None,
        "event": event,
        "delivery_mode": mode,
    }


def _decision_ledger_status() -> Dict[str, Any]:
    status: Dict[str, Any] = {
        "enabled": bool(ADVISORY_DECISION_LEDGER_ENABLED),
        "path": str(ADVISORY_DECISION_LEDGER_FILE),
        "exists": bool(ADVISORY_DECISION_LEDGER_FILE.exists()),
        "total_entries": 0,
        "recent_count": 0,
        "recent_emitted_count": 0,
        "recent_emission_rate": 0.0,
    }

    if not status["exists"]:
        return status

    try:
        lines = ADVISORY_DECISION_LEDGER_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return status

    parsed: List[Dict[str, Any]] = []
    status["total_entries"] = int(len(lines))
    for line in lines[-120:]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            parsed.append(row)

    status["recent_count"] = int(len(parsed))
    status["recent_emitted_count"] = int(sum(1 for row in parsed if str(row.get("outcome", "")).strip().lower() == "emitted"))
    if status["recent_count"]:
        status["recent_emission_rate"] = round(status["recent_emitted_count"] / max(status["recent_count"], 1), 3)
    return status


def _fallback_guard_allows() -> Dict[str, Any]:
    if not FALLBACK_RATE_GUARD_ENABLED:
        return {
            "allowed": True,
            "reason": "guard_disabled",
            "ratio": None,
            "limit": float(FALLBACK_RATE_GUARD_MAX_RATIO),
            "delivered_recent": 0,
            "window": int(FALLBACK_RATE_GUARD_WINDOW),
        }
    if FALLBACK_RATE_GUARD_WINDOW <= 0:
        return {
            "allowed": True,
            "reason": "invalid_window",
            "ratio": None,
            "limit": float(FALLBACK_RATE_GUARD_MAX_RATIO),
            "delivered_recent": 0,
            "window": int(FALLBACK_RATE_GUARD_WINDOW),
        }

    fallback_count = 0
    emitted_count = 0
    try:
        rows = _tail_jsonl(ENGINE_LOG, FALLBACK_RATE_GUARD_WINDOW)
        for row in rows:
            event = str(row.get("event") or "")
            if event == "fallback_emit":
                fallback_count += 1
            elif event == "emitted":
                emitted_count += 1
    except Exception:
        return {
            "allowed": True,
            "reason": "read_failed",
            "ratio": None,
            "limit": float(FALLBACK_RATE_GUARD_MAX_RATIO),
            "delivered_recent": 0,
            "window": int(FALLBACK_RATE_GUARD_WINDOW),
        }

    delivered = fallback_count + emitted_count
    min_sample = max(10, int(FALLBACK_RATE_GUARD_WINDOW * 0.25))
    if delivered < min_sample:
        return {
            "allowed": True,
            "reason": "insufficient_sample",
            "ratio": None,
            "limit": float(FALLBACK_RATE_GUARD_MAX_RATIO),
            "delivered_recent": int(delivered),
            "window": int(FALLBACK_RATE_GUARD_WINDOW),
        }

    ratio = float(fallback_count) / float(max(delivered, 1))
    allowed = ratio <= float(FALLBACK_RATE_GUARD_MAX_RATIO)
    return {
        "allowed": allowed,
        "reason": "ok" if allowed else "ratio_exceeded",
        "ratio": ratio,
        "limit": float(FALLBACK_RATE_GUARD_MAX_RATIO),
        "delivered_recent": int(delivered),
        "window": int(FALLBACK_RATE_GUARD_WINDOW),
    }


def _fallback_budget_allows(kind: str) -> bool:
    """Check if a fallback emission is allowed under the per-window budget cap.

    Resets counters when FALLBACK_BUDGET_WINDOW tool calls are exhausted.
    ``kind`` should be ``"quick"`` or ``"packet"``.
    """
    if FALLBACK_BUDGET_CAP <= 0:
        return True  # 0 = unlimited (old behaviour)
    key = f"{kind}_emits"
    if _fallback_budget.get(key, 0) < FALLBACK_BUDGET_CAP:
        return True
    return False


def _fallback_budget_record(kind: str) -> None:
    """Record a fallback emission against the per-window budget."""
    key = f"{kind}_emits"
    _fallback_budget[key] = _fallback_budget.get(key, 0) + 1


def _fallback_budget_tick() -> None:
    """Increment the call counter and reset the window when exhausted.

    Window semantics: with FALLBACK_BUDGET_WINDOW=5, calls 1-5 are in one window.
    Reset happens *after* the window is full (call > window), so the Nth call
    is still inside the window it started in.
    """
    _fallback_budget["calls"] = _fallback_budget.get("calls", 0) + 1
    if _fallback_budget["calls"] > FALLBACK_BUDGET_WINDOW:
        _fallback_budget["calls"] = 1
        _fallback_budget["quick_emits"] = 0
        _fallback_budget["packet_emits"] = 0


def on_pre_tool(
    session_id: str,
    tool_name: str,
    tool_input: Optional[dict] = None,
    trace_id: Optional[str] = None,
) -> Optional[str]:
    if not ENGINE_ENABLED:
        return None

    start_ms = time.time() * 1000.0
    resolved_trace_id = trace_id
    route = "live"
    packet_id = None
    stage_ms: Dict[str, float] = {}
    session_context_key = ""
    memory_bundle: Dict[str, Any] = {}
    intent_family = "emergent_other"
    task_plane = "build_delivery"
    advice_source_counts: Dict[str, int] = {}
    emitted_advice_source_counts: Dict[str, int] = {}
    synth_policy = "none"

    def _mark(stage: str, t0: float) -> None:
        try:
            stage_ms[stage] = round((time.time() * 1000.0) - t0, 1)
        except Exception:
            pass

    def _diag(current_route: str) -> Dict[str, Any]:
        return _diagnostics_envelope(
            session_id=session_id,
            trace_id=resolved_trace_id,
            route=current_route,
            session_context_key=session_context_key,
            scope="session",
            memory_bundle=memory_bundle,
        )

    try:
        from .advisor import advise_on_tool
        from .advisory_emitter import emit_advisory
        from .advisory_gate import evaluate, get_tool_cooldown_s
        from .advisory_packet_store import (
            build_packet,
            record_packet_usage,
            resolve_advisory_packet_for_context,
            save_packet,
        )
        from .advisory_state import (
            load_state,
            mark_advice_shown,
            record_tool_call,
            resolve_recent_trace_id,
            save_state,
            suppress_tool_advice,
        )
        from .advisory_synthesizer import synthesize

        state = load_state(session_id)
        resolved_trace_id = trace_id or resolve_recent_trace_id(state, tool_name)
        if not resolved_trace_id:
            try:
                from .exposure_tracker import infer_latest_trace_id

                resolved_trace_id = infer_latest_trace_id(session_id)
            except Exception:
                resolved_trace_id = None
        if not resolved_trace_id:
            # Keep engine events trace-bound even when upstream did not provide a trace.
            resolved_trace_id = f"spark-auto-{session_id[:16]}-{tool_name.lower()}-{int(time.time()*1000)}"

        record_tool_call(state, tool_name, tool_input, success=None, trace_id=resolved_trace_id)
        # Use tool-agnostic intent for packet keying/prefetch alignment.
        # (Carmack-style: stability > hyper-specificity on the hot path.)
        intent_info = _intent_context(state, tool_name="*")
        project_key = _project_key()
        session_context_key = _session_context_key(state, tool_name)
        intent_family = state.intent_family or "emergent_other"
        task_plane = state.task_plane or "build_delivery"

        _fallback_budget_tick()

        # Early-exit: if same tool+context as last emission and within cooldown,
        # skip the entire retrieval → gate → synthesis path. (Batch 1 optimization.)
        context_fp = _text_fingerprint(f"{tool_name}:{session_context_key}")
        last_context_fp = str(getattr(state, "last_advisory_context_fingerprint", "") or "")
        last_at = float(getattr(state, "last_advisory_at", 0.0) or 0.0)
        if (
            context_fp
            and context_fp == last_context_fp
            and last_at > 0
            and (time.time() - last_at) < ADVISORY_TEXT_REPEAT_COOLDOWN_S
        ):
            _record_advisory_decision_ledger(
                stage="early_exit_context_repeat",
                outcome="blocked",
                tool_name=tool_name,
                intent_family=intent_family,
                task_plane=task_plane,
                route="none",
                packet_id=None,
                advice_items=None,
                gate_result=None,
                session_id=session_id,
                trace_id=resolved_trace_id,
                extras={
                    "error_kind": "policy",
                    "error_code": "AE_CONTEXT_REPEAT",
                    "context_fp": context_fp,
                    "age_s": round(time.time() - last_at, 1),
                    "cooldown_s": float(ADVISORY_TEXT_REPEAT_COOLDOWN_S),
                },
            )
            _record_rejection("early_exit_context_repeat")
            save_state(state)
            return None

        t_lookup = time.time() * 1000.0
        packet, packet_route = resolve_advisory_packet_for_context(
            project_key=project_key,
            session_context_key=session_context_key,
            tool_name=tool_name,
            intent_family=intent_family,
            task_plane=task_plane,
            context_text=str(getattr(state, "user_intent", "") or ""),
        )
        if packet_route in {"packet_exact", "packet_relaxed"}:
            route = packet_route

        _mark("packet_lookup", t_lookup)

        if packet:
            packet_id = str(packet.get("packet_id") or "")
            advice_items = _packet_to_advice(packet)
        else:
            # If we're low on remaining budget, skip heavy retrieval and emit a
            # cheap deterministic hint instead. This improves real-time advisory
            # delivery (better than returning None due to slow paths).
            elapsed_ms_pre = (time.time() * 1000.0) - start_ms
            remaining_ms_pre = MAX_ENGINE_MS - elapsed_ms_pre
            if (LIVE_QUICK_FALLBACK_ENABLED
                    and remaining_ms_pre < float(LIVE_QUICK_FALLBACK_MIN_REMAINING_MS)
                    and _fallback_budget_allows("quick")):
                try:
                    from .advisor import Advice, get_quick_advice

                    quick_text = (get_quick_advice(tool_name) or "").strip()
                    if not quick_text:
                        quick_text = _baseline_text(intent_family).strip()
                    advice_items = [
                        Advice(
                            advice_id=f"quick_{tool_name.lower()}_0",
                            insight_key="quick_fallback",
                            text=quick_text,
                            confidence=0.78,
                            source="quick",
                            context_match=0.78,
                            reason=f"quick_fallback remaining_ms={int(remaining_ms_pre)}",
                        )
                    ]
                    route = "live_quick"
                    _fallback_budget_record("quick")
                except Exception:
                    # Quick fallback failed — fall through to full retrieval below
                    t_live = time.time() * 1000.0
                    advice_items = advise_on_tool(
                        tool_name,
                        tool_input or {},
                        context=state.user_intent,
                        include_mind=INCLUDE_MIND_IN_MEMORY,
                        track_retrieval=False,
                        log_recent=False,
                        trace_id=resolved_trace_id,
                    )
                    _mark("advisor_retrieval", t_live)
                    route = "live"
            else:
                t_live = time.time() * 1000.0
                advice_items = advise_on_tool(
                    tool_name,
                    tool_input or {},
                    context=state.user_intent,
                    include_mind=INCLUDE_MIND_IN_MEMORY,
                    track_retrieval=False,  # track retrieval only for *delivered* advice (after gating)
                    log_recent=False,  # recent_advice should reflect *delivered* advice, not retrieval fanout
                    trace_id=resolved_trace_id,
                )
                _mark("advisor_retrieval", t_live)
                route = "live"
        advice_source_counts = _advice_source_counts(advice_items)

        if not advice_items:
            save_state(state)
            _record_advisory_decision_ledger(
                stage="no_advice",
                outcome="none",
                tool_name=tool_name,
                intent_family=intent_family,
                task_plane=task_plane,
                route=route,
                packet_id=packet_id,
                advice_items=advice_items,
                gate_result=None,
                session_id=session_id,
                trace_id=resolved_trace_id,
                extras={
                    "event": "no_advice",
                    "error_kind": "no_hit",
                    "error_code": "AE_NO_ADVICE",
                    "stage": "no_advice",
                },
            )
            _log_engine_event(
                "no_advice",
                tool_name,
                0,
                0,
                start_ms,
                extra={
                    **_diag(route),
                    "route": route,
                    "intent_family": intent_family,
                    "task_plane": task_plane,
                    "stage_ms": stage_ms,
                    "delivery_mode": "none",
                "advice_source_counts": advice_source_counts,
                "error_kind": "no_hit",
                "error_code": "AE_NO_ADVICE",
                },
            )
            _record_rejection("no_advice")
            return None

        # Pre-read global dedupe log once so the gate can absorb advice_id dedupe
        # (avoids per-item I/O in the post-gate dedupe pass).
        recent_global_emissions: Dict[str, float] = {}
        if (
            GLOBAL_DEDUPE_ENABLED
            and not str(session_id or "").startswith("advisory-bench-")
        ):
            try:
                _dedupe_now = time.time()
                _dedupe_cooldown = float(GLOBAL_DEDUPE_COOLDOWN_S)
                _dedupe_scope = _dedupe_scope_key(session_id)
                for row in reversed(_tail_jsonl(GLOBAL_DEDUPE_LOG, 400)):
                    try:
                        aid = str(row.get("advice_id") or "").strip()
                        if not aid:
                            continue
                        ts = float(row.get("ts") or 0.0)
                        if ts <= 0:
                            continue
                        age_s = _dedupe_now - ts
                        if age_s < 0 or age_s >= _dedupe_cooldown:
                            continue
                        scope = str(row.get("scope_key") or "").strip()
                        if _dedupe_scope and scope and scope != _dedupe_scope:
                            continue
                        if aid not in recent_global_emissions:
                            recent_global_emissions[aid] = age_s
                    except Exception:
                        continue
            except Exception:
                pass

        t_gate = time.time() * 1000.0
        gate_result = evaluate(
            advice_items, state, tool_name, tool_input,
            recent_global_emissions=recent_global_emissions or None,
        )
        _mark("gate", t_gate)
        if not gate_result.emitted:
            if packet_id:
                try:
                    record_packet_usage(
                        packet_id,
                        emitted=False,
                        route=route,
                        trace_id=resolved_trace_id,
                        tool_name=tool_name,
                    )
                except Exception as e:
                    log_debug("advisory_engine", "AE_PKT_USAGE_NO_EMIT", e)

            # --- NO-EMIT FALLBACK ---
            # If the packet path failed the gate, try a bounded deterministic
            # fallback using baseline text for this intent family, instead of
            # returning None (which wastes the entire advisory opportunity).
            # Budget-capped (Batch 3): max FALLBACK_BUDGET_CAP per window.
            fallback_text = ""
            if (PACKET_FALLBACK_EMIT_ENABLED
                    and route and route.startswith("packet")
                    and _fallback_budget_allows("packet")):
                elapsed_fb = (time.time() * 1000.0) - start_ms
                if elapsed_fb < MAX_ENGINE_MS - 200:  # only if budget remains
                    fallback_text = _baseline_text(intent_family).strip()
                    if fallback_text:
                        route = f"{route}_fallback"
                        _fallback_budget_record("packet")

            if not fallback_text:
                suppression_meta = _gate_suppression_metadata(gate_result)
                _record_advisory_gate_drop(
                    stage="gate_no_emit",
                    reason="AE_GATE_SUPPRESSED",
                    tool_name=tool_name,
                    intent_family=intent_family,
                    task_plane=task_plane,
                    route=route,
                    packet_id=packet_id,
                    advice_items=advice_items,
                    extras={
                        **suppression_meta,
                        "fallback_candidate_blocked": bool(
                            route and route.startswith("packet") and not PACKET_FALLBACK_EMIT_ENABLED
                        ),
                    },
                )
                _record_advisory_decision_ledger(
                    stage="gate_no_emit",
                    outcome="blocked",
                    tool_name=tool_name,
                    intent_family=intent_family,
                    task_plane=task_plane,
                    route=route,
                    packet_id=packet_id,
                    advice_items=advice_items,
                    gate_result=gate_result,
                    session_id=session_id,
                    trace_id=resolved_trace_id,
                    extras={
                        "error_kind": "policy",
                        "error_code": "AE_GATE_SUPPRESSED",
                        "suppressed_reasons": suppression_meta.get("suppressed_reasons", []),
                    },
                )
                save_state(state)
                _log_engine_event(
                    "no_emit",
                    tool_name,
                    len(advice_items),
                    0,
                    start_ms,
                    extra={
                        **_diag(route),
                        "route": route,
                        "intent_family": intent_family,
                        "task_plane": task_plane,
                        "packet_id": packet_id,
                        "stage_ms": stage_ms,
                        "delivery_mode": "none",
                        "advice_source_counts": advice_source_counts,
                        "fallback_candidate_blocked": bool(route and route.startswith("packet") and not PACKET_FALLBACK_EMIT_ENABLED),
                        "error_kind": "policy",
                        "error_code": "AE_GATE_SUPPRESSED",
                        **suppression_meta,
                    },
                )
                _record_rejection("gate_no_emit")
                return None

            # Emit the fallback deterministic text
            action_meta = _ensure_actionability(fallback_text, tool_name, task_plane)
            fallback_text = str(action_meta.get("text") or fallback_text)
            if ACTION_FIRST_ENABLED:
                fallback_text = _action_first_format(fallback_text)
            fallback_guard = _fallback_guard_allows()
            if not fallback_guard.get("allowed"):
                _record_advisory_gate_drop(
                    stage="fallback_rate_limit",
                    reason="AE_FALLBACK_RATE_LIMIT",
                    tool_name=tool_name,
                    intent_family=intent_family,
                    task_plane=task_plane,
                    route=route,
                    packet_id=packet_id,
                    advice_items=advice_items,
                    extras={
                        "route": route,
                        "fallback_rate_recent": fallback_guard.get("ratio"),
                        "fallback_rate_limit": fallback_guard.get("limit"),
                        "fallback_delivered_recent": fallback_guard.get("delivered_recent"),
                        "fallback_window": fallback_guard.get("window"),
                    },
                )
                _record_advisory_decision_ledger(
                    stage="fallback_rate_limit",
                    outcome="blocked",
                    tool_name=tool_name,
                    intent_family=intent_family,
                    task_plane=task_plane,
                    route=route,
                    packet_id=packet_id,
                    advice_items=advice_items,
                    gate_result=gate_result,
                    session_id=session_id,
                    trace_id=resolved_trace_id,
                    extras={
                        "error_kind": "policy",
                        "error_code": "AE_FALLBACK_RATE_LIMIT",
                        "fallback_rate_recent": fallback_guard.get("ratio"),
                        "fallback_rate_limit": fallback_guard.get("limit"),
                    },
                )
                save_state(state)
                _log_engine_event(
                    "no_emit",
                    tool_name,
                    len(advice_items),
                    0,
                    start_ms,
                    extra={
                        **_diag(route),
                        "route": route,
                        "intent_family": intent_family,
                        "task_plane": task_plane,
                        "packet_id": packet_id,
                        "stage_ms": stage_ms,
                        "delivery_mode": "none",
                        "advice_source_counts": advice_source_counts,
                        "error_kind": "policy",
                        "error_code": "AE_FALLBACK_RATE_LIMIT",
                        "fallback_guard_blocked": True,
                        "fallback_rate_recent": fallback_guard.get("ratio"),
                        "fallback_rate_limit": fallback_guard.get("limit"),
                        "fallback_delivered_recent": fallback_guard.get("delivered_recent"),
                        "fallback_window": fallback_guard.get("window"),
                    },
                )
                _record_rejection("fallback_rate_limit")
                return None
            repeat_meta = _duplicate_repeat_state(state, fallback_text)
            if repeat_meta["repeat"]:
                _record_advisory_gate_drop(
                    stage="fallback_duplicate",
                    reason="AE_DUPLICATE_SUPPRESSED",
                    tool_name=tool_name,
                    intent_family=intent_family,
                    task_plane=task_plane,
                    route=route,
                    packet_id=packet_id,
                    advice_items=[None] if not advice_items else advice_items,
                    extras={
                        "advisory_fingerprint": repeat_meta["fingerprint"],
                        "repeat_age_s": repeat_meta["age_s"],
                        "repeat_cooldown_s": repeat_meta["cooldown_s"],
                        "actionability_added": bool(action_meta.get("added")),
                        "actionability_command": action_meta.get("command"),
                    },
                )
                _record_advisory_decision_ledger(
                    stage="fallback_duplicate",
                    outcome="blocked",
                    tool_name=tool_name,
                    intent_family=intent_family,
                    task_plane=task_plane,
                    route=route,
                    packet_id=packet_id,
                    advice_items=[None] if not advice_items else advice_items,
                    gate_result=gate_result,
                    session_id=session_id,
                    trace_id=resolved_trace_id,
                    extras={
                        "error_kind": "policy",
                        "error_code": "AE_DUPLICATE_SUPPRESSED",
                        "advisory_fingerprint": repeat_meta["fingerprint"],
                        "repeat_age_s": repeat_meta["age_s"],
                        "repeat_cooldown_s": repeat_meta["cooldown_s"],
                        "actionability_added": bool(action_meta.get("added")),
                        "actionability_command": action_meta.get("command"),
                    },
                )
                save_state(state)
                _log_engine_event(
                    "duplicate_suppressed",
                    tool_name,
                    len(advice_items),
                    0,
                    start_ms,
                    extra={
                        **_diag(route),
                        "route": route,
                        "intent_family": intent_family,
                        "task_plane": task_plane,
                        "packet_id": packet_id,
                        "stage_ms": stage_ms,
                        "delivery_mode": "none",
                        "advice_source_counts": advice_source_counts,
                        "error_kind": "policy",
                        "error_code": "AE_DUPLICATE_SUPPRESSED",
                        "advisory_fingerprint": repeat_meta["fingerprint"],
                        "repeat_age_s": repeat_meta["age_s"],
                        "repeat_cooldown_s": repeat_meta["cooldown_s"],
                        "actionability_added": bool(action_meta.get("added")),
                        "actionability_command": action_meta.get("command"),
                    },
                )
                return None

            fallback_emitted = False
            fallback_error: Optional[Dict[str, Any]] = None
            # Safety check on fallback text before emit
            try:
                from .promoter import is_unsafe_insight as _is_unsafe
                if fallback_text and _is_unsafe(fallback_text):
                    log_debug("advisory_engine", f"SAFETY_BLOCK: unsafe fallback blocked for {tool_name}", None)
                    _record_rejection("safety_blocked_fallback")
                    save_state(state)
                    return None
            except Exception as _sfb_err:
                log_debug("advisory_engine", "SAFETY_CHECK_FALLBACK_fail_open", _sfb_err)
            try:
                from .advisory_emitter import emit_advisory
                fallback_emitted = _emit_advisory_compat(
                    emit_advisory,
                    gate_result,
                    fallback_text,
                    advice_items,
                    trace_id=resolved_trace_id,
                    tool_name=tool_name,
                    route=route,
                    task_plane=task_plane,
                )
                if fallback_emitted:
                    state.last_advisory_packet_id = ""
                    state.last_advisory_route = str(route or "")
                    state.last_advisory_tool = str(tool_name or "")
                    state.last_advisory_advice_ids = []
                    state.last_advisory_at = time.time()
                    state.last_advisory_text_fingerprint = repeat_meta["fingerprint"]
                    state.last_advisory_context_fingerprint = context_fp
            except Exception as e:
                log_debug("advisory_engine", "AE_FALLBACK_EMIT_FAILED", e)
                fallback_error = build_error_fields(str(e), "AE_FALLBACK_EMIT_FAILED")
            save_state(state)
            _log_engine_event(
                "fallback_emit" if fallback_emitted else "fallback_emit_failed",
                tool_name,
                len(advice_items),
                1 if fallback_emitted else 0,
                start_ms,
                extra={
                    **_diag(route),
                    "route": route,
                    "intent_family": intent_family,
                    "packet_id": packet_id,
                    "stage_ms": stage_ms,
                    "delivery_mode": "fallback" if fallback_emitted else "none",
                    "route_type": "fallback",
                    "emitted_text_preview": fallback_text[:220],
                    "advice_source_counts": advice_source_counts,
                    "actionability_added": bool(action_meta.get("added")),
                    "actionability_command": action_meta.get("command"),
                    **(fallback_error or {}),
                },
            )
            _record_advisory_decision_ledger(
                stage="fallback_emit" if fallback_emitted else "fallback_emit_failed",
                outcome="emitted" if fallback_emitted else "blocked",
                tool_name=tool_name,
                intent_family=intent_family,
                task_plane=task_plane,
                route=route,
                packet_id=packet_id,
                advice_items=advice_items,
                gate_result=gate_result,
                session_id=session_id,
                trace_id=resolved_trace_id,
                extras={
                    "event": "fallback_emit" if fallback_emitted else "fallback_emit_failed",
                    "advice_text_preview": fallback_text[:140],
                },
            )
            return fallback_text

        advice_by_id = {str(getattr(item, "advice_id", "")): item for item in advice_items}
        emitted_advice = []
        for decision in gate_result.emitted:
            item = advice_by_id.get(decision.advice_id)
            if item is None:
                continue
            item._authority = decision.authority
            emitted_advice.append(item)
        emitted_advice_source_counts = _advice_source_counts(emitted_advice)

        # Cross-session dedupe: text_sig only (advice_id dedupe absorbed into gate).
        try:
            if (
                GLOBAL_DEDUPE_ENABLED
                and GLOBAL_DEDUPE_TEXT_ENABLED
                and gate_result.emitted
                and not str(session_id or "").startswith("advisory-bench-")
            ):
                now_ts = time.time()
                cooldown = float(GLOBAL_DEDUPE_COOLDOWN_S)
                dedupe_scope = _dedupe_scope_key(session_id)
                kept = []
                suppressed: List[Dict[str, Any]] = []
                for decision in list(gate_result.emitted or []):
                    aid = str(getattr(decision, "advice_id", "") or "").strip()
                    if not aid:
                        continue
                    try:
                        item = advice_by_id.get(aid)
                        sig = _text_fingerprint(str(getattr(item, "text", "") or "")) if item else ""
                    except Exception:
                        sig = ""
                    if sig:
                        hit_sig = _global_recently_emitted_text_sig(
                            text_sig=sig,
                            now_ts=now_ts,
                            cooldown_s=cooldown,
                            scope_key=dedupe_scope,
                        )
                        if hit_sig:
                            suppressed.append(
                                {
                                    "advice_id": aid,
                                    "reason": "text_sig",
                                    "repeat_age_s": round(float(hit_sig.get("age_s") or 0.0), 2),
                                    "repeat_cooldown_s": round(float(hit_sig.get("cooldown_s") or cooldown), 2),
                                }
                            )
                            continue
                    kept.append(decision)

                if suppressed:
                    _record_advisory_gate_drop(
                        stage="global_dedupe_suppressed",
                        reason="AE_GLOBAL_DEDUPE_SUPPRESSED",
                        tool_name=tool_name,
                        intent_family=intent_family,
                        task_plane=task_plane,
                        route=route,
                        packet_id=packet_id,
                        advice_items=advice_items,
                        extras={
                            "suppressed_count": len(suppressed),
                            "suppressed": suppressed[:8],
                            "cooldown_s": round(float(cooldown), 2),
                            "dedupe_scope": dedupe_scope,
                        },
                    )
                    _record_advisory_decision_ledger(
                        stage="global_dedupe_suppressed",
                        outcome="blocked",
                        tool_name=tool_name,
                        intent_family=intent_family,
                        task_plane=task_plane,
                        route=route,
                        packet_id=packet_id,
                        advice_items=advice_items,
                        gate_result=gate_result,
                        session_id=session_id,
                        trace_id=resolved_trace_id,
                        extras={
                            "error_kind": "policy",
                            "error_code": "AE_GLOBAL_DEDUPE_SUPPRESSED",
                            "suppressed": suppressed[:8],
                            "cooldown_s": round(float(cooldown), 2),
                            "dedupe_scope": dedupe_scope,
                        },
                    )
                    if not kept:
                        save_state(state)
                        _log_engine_event(
                            "global_dedupe_suppressed",
                            tool_name,
                            len(advice_items),
                            0,
                            start_ms,
                            extra={
                                **_diag(route),
                                "route": route,
                                "intent_family": intent_family,
                                "task_plane": task_plane,
                                "packet_id": packet_id,
                                "stage_ms": stage_ms,
                                "delivery_mode": "none",
                                "advice_source_counts": advice_source_counts,
                                "error_kind": "policy",
                                "error_code": "AE_GLOBAL_DEDUPE_SUPPRESSED",
                                "suppressed_count": len(suppressed),
                                "suppressed": suppressed[:8],
                                "cooldown_s": round(float(cooldown), 2),
                                "dedupe_scope": dedupe_scope,
                            },
                        )
                        _record_rejection("global_dedupe_suppressed")
                        return None

                    gate_result.emitted = kept
                    emitted_advice = []
                    for decision in gate_result.emitted:
                        item = advice_by_id.get(decision.advice_id)
                        if item is None:
                            continue
                        item._authority = decision.authority
                        emitted_advice.append(item)
                    emitted_advice_source_counts = _advice_source_counts(emitted_advice)
        except Exception:
            pass

        elapsed_ms = (time.time() * 1000.0) - start_ms
        remaining_ms = MAX_ENGINE_MS - elapsed_ms

        t_synth = time.time() * 1000.0
        synth_text = ""
        selective_ai_eligible = False
        if packet and str(packet.get("advisory_text") or "").strip():
            synth_text = str(packet.get("advisory_text") or "").strip()
            synth_policy = "packet_cached"
        elif FORCE_PROGRAMMATIC_SYNTH:
            selective_ai_eligible = _should_use_selective_ai_synth(
                gate_result=gate_result,
                remaining_ms=remaining_ms,
            )
            if selective_ai_eligible:
                synth_text = synthesize(
                    emitted_advice,
                    phase=gate_result.phase,
                    user_intent=state.user_intent,
                    tool_name=tool_name,
                )
                synth_policy = "selective_ai_auto"
            else:
                synth_text = synthesize(
                    emitted_advice,
                    phase=gate_result.phase,
                    user_intent=state.user_intent,
                    tool_name=tool_name,
                    force_mode="programmatic",
                )
                synth_policy = "programmatic_forced"
        elif remaining_ms > 500:
            synth_text = synthesize(
                emitted_advice,
                phase=gate_result.phase,
                user_intent=state.user_intent,
                tool_name=tool_name,
            )
            synth_policy = "auto"
        else:
            synth_text = synthesize(
                emitted_advice,
                phase=gate_result.phase,
                user_intent=state.user_intent,
                tool_name=tool_name,
                force_mode="programmatic",
            )
            synth_policy = "programmatic_budget_fallback"
        synth_fallback_used = False
        if not str(synth_text or "").strip():
            synth_text = _fallback_synth_text_from_emitted(
                emitted_advice,
                intent_family=intent_family,
            )
            synth_fallback_used = bool(str(synth_text or "").strip())
        _mark("synth", t_synth)

        action_meta = _ensure_actionability(synth_text, tool_name, task_plane)
        synth_text = str(action_meta.get("text") or synth_text)
        if ACTION_FIRST_ENABLED:
            synth_text = _action_first_format(synth_text)
        repeat_meta = _duplicate_repeat_state(state, synth_text)
        if repeat_meta["repeat"]:
            if packet_id:
                try:
                    record_packet_usage(
                        packet_id,
                        emitted=False,
                        route=f"{route}_repeat_suppressed",
                        trace_id=resolved_trace_id,
                        tool_name=tool_name,
                    )
                except Exception as e:
                    log_debug("advisory_engine", "AE_PKT_USAGE_REPEAT_SUPPRESS_FAILED", e)
            _record_advisory_gate_drop(
                stage="duplicate_suppressed",
                reason="AE_DUPLICATE_SUPPRESSED",
                tool_name=tool_name,
                intent_family=intent_family,
                task_plane=task_plane,
                route=route,
                packet_id=packet_id,
                advice_items=advice_items,
                extras={
                    "advisory_fingerprint": repeat_meta["fingerprint"],
                    "repeat_age_s": repeat_meta["age_s"],
                    "repeat_cooldown_s": repeat_meta["cooldown_s"],
                    "actionability_added": bool(action_meta.get("added")),
                    "actionability_command": action_meta.get("command"),
                    "top_advice_id": str(getattr(gate_result.emitted[0], "advice_id", "")) if gate_result.emitted else "",
                    "top_authority": str(getattr(gate_result.emitted[0], "authority", "")) if gate_result.emitted else "",
                },
            )
            _record_advisory_decision_ledger(
                stage="duplicate_suppressed",
                outcome="blocked",
                tool_name=tool_name,
                intent_family=intent_family,
                task_plane=task_plane,
                route=route,
                packet_id=packet_id,
                advice_items=advice_items,
                gate_result=gate_result,
                session_id=session_id,
                trace_id=resolved_trace_id,
                extras={
                    "error_kind": "policy",
                    "error_code": "AE_DUPLICATE_SUPPRESSED",
                    "advisory_fingerprint": repeat_meta["fingerprint"],
                    "repeat_age_s": repeat_meta["age_s"],
                    "repeat_cooldown_s": repeat_meta["cooldown_s"],
                    "actionability_added": bool(action_meta.get("added")),
                    "actionability_command": action_meta.get("command"),
                    "top_advice_id": str(getattr(gate_result.emitted[0], "advice_id", "")) if gate_result.emitted else "",
                    "top_authority": str(getattr(gate_result.emitted[0], "authority", "")) if gate_result.emitted else "",
                },
            )
            save_state(state)
            _log_engine_event(
                "duplicate_suppressed",
                tool_name,
                len(advice_items),
                len(gate_result.emitted),
                start_ms,
                extra={
                    **_diag(route),
                    "route": route,
                    "intent_family": intent_family,
                    "task_plane": task_plane,
                    "packet_id": packet_id,
                    "stage_ms": stage_ms,
                    "delivery_mode": "none",
                    "advice_source_counts": advice_source_counts,
                    "error_kind": "policy",
                    "error_code": "AE_DUPLICATE_SUPPRESSED",
                    "advisory_fingerprint": repeat_meta["fingerprint"],
                    "repeat_age_s": repeat_meta["age_s"],
                    "repeat_cooldown_s": repeat_meta["cooldown_s"],
                    "actionability_added": bool(action_meta.get("added")),
                    "actionability_command": action_meta.get("command"),
                },
            )
            _record_rejection("duplicate_suppressed")
            return None

        # Safety gate: block unsafe content BEFORE emit (pre-emit position).
        try:
            from .promoter import is_unsafe_insight
            if synth_text and is_unsafe_insight(synth_text):
                log_debug("advisory_engine", f"SAFETY_BLOCK: unsafe content blocked for {tool_name}", None)
                _record_advisory_decision_ledger(
                    stage="safety_blocked",
                    outcome="blocked",
                    tool_name=tool_name,
                    intent_family=intent_family,
                    task_plane=task_plane,
                    route=route,
                    packet_id=packet_id,
                    advice_items=advice_items,
                    gate_result=gate_result,
                    session_id=session_id,
                    trace_id=resolved_trace_id,
                    extras={
                        "error_kind": "safety",
                        "error_code": "AE_SAFETY_BLOCKED",
                        "emitted_text_preview": (synth_text or "")[:140],
                    },
                )
                _record_rejection("safety_blocked")
                save_state(state)
                return None
        except Exception as safety_err:
            log_debug("advisory_engine", "SAFETY_CHECK_EXCEPTION_fail_open", safety_err)

        t_emit = time.time() * 1000.0
        emitted = _emit_advisory_compat(
            emit_advisory,
            gate_result,
            synth_text,
            advice_items,
            trace_id=resolved_trace_id,
            tool_name=tool_name,
            route=route,
            task_plane=task_plane,
        )
        _mark("emit", t_emit)
        effective_text = str(synth_text or "").strip()
        if emitted and not effective_text:
            fragments: List[str] = []
            for item in emitted_advice[:3]:
                text = str(getattr(item, "text", "") or "").strip()
                if text:
                    fragments.append(text)
            if fragments:
                effective_text = " ".join(fragments)
        effective_action_meta = _ensure_actionability(effective_text, tool_name, task_plane) if emitted else {"text": effective_text, "added": False, "command": ""}
        effective_text = str(effective_action_meta.get("text") or effective_text)

        # Initialize before conditional paths to avoid stale runtime crashes
        # when no advisories are emitted in this pass.
        shown_ids: List[str] = []
        dedupe_scope = _dedupe_scope_key(session_id)
        session_lineage = _session_lineage(session_id)
        if emitted:
            shown_ids = [d.advice_id for d in gate_result.emitted]
            mark_advice_shown(
                state,
                shown_ids,
                tool_name=tool_name,
                task_phase=state.task_phase,
            )
        # Apply tool-family-aware cooldown: exploration tools get shorter suppression.
        try:
            from .advisory_gate import _tool_cooldown_scale
            tool_cd_scale = _tool_cooldown_scale(tool_name)
        except Exception:
            tool_cd_scale = 1.0
        suppress_tool_advice(state, tool_name, duration_s=get_tool_cooldown_s() * tool_cd_scale)
        # Track retrieval only for delivered advice items (strict attribution).
        try:
            from .meta_ralph import get_meta_ralph

            ralph = get_meta_ralph()
            for adv in list(emitted_advice or [])[:4]:
                ralph.track_retrieval(
                    str(getattr(adv, "advice_id", "") or ""),
                    str(getattr(adv, "text", "") or ""),
                    insight_key=str(getattr(adv, "insight_key", "") or "") or None,
                    source=str(getattr(adv, "source", "") or "") or None,
                    trace_id=resolved_trace_id,
                )
        except Exception:
            pass
        # Write delivery-backed recent_advice entry for post-tool outcome linkage.
        try:
            from .advisor import record_recent_delivery

            record_recent_delivery(
                tool=tool_name,
                advice_list=list(emitted_advice or [])[:4],
                trace_id=resolved_trace_id,
                route=route,
                delivered=True,
                categories=[getattr(adv, "category", None) for adv in list(emitted_advice or [])[:4]],
                advisory_readiness=[getattr(adv, "advisory_readiness", 0.0) for adv in list(emitted_advice or [])[:4]],
                advisory_quality=[
                    q if isinstance(q, dict) else {}
                    for q in [getattr(adv, "advisory_quality", None) for adv in list(emitted_advice or [])[:4]]
                ],
            )
        except Exception:
            pass

        # Update global dedupe log on successful emission (any authority).
        try:
            if (
                GLOBAL_DEDUPE_ENABLED
                and gate_result.emitted
                and not str(session_id or "").startswith("advisory-bench-")
            ):
                for d in list(gate_result.emitted or [])[:4]:
                    aid = str(getattr(d, "advice_id", "") or "").strip()
                    if not aid:
                        continue
                    text_sig = ""
                    if GLOBAL_DEDUPE_TEXT_ENABLED:
                        try:
                            item = advice_by_id.get(aid)
                            text_sig = _text_fingerprint(str(getattr(item, "text", "") or "")) if item else ""
                        except Exception:
                            text_sig = ""
                    _append_jsonl_capped(
                        GLOBAL_DEDUPE_LOG,
                        {
                            "ts": time.time(),
                            "tool": tool_name,
                            "advice_id": aid,
                            "authority": str(getattr(d, "authority", "") or ""),
                            "trace_id": resolved_trace_id,
                            "route": route,
                            "scope_key": dedupe_scope,
                            "session_kind": session_lineage.get("session_kind"),
                            "text_sig": text_sig,
                        },
                        max_lines=int(GLOBAL_DEDUPE_LOG_MAX),
                    )
        except Exception:
            pass

        if route == "live":
            lineage_sources = []
            for source_name, cnt in (emitted_advice_source_counts or advice_source_counts).items():
                if int(cnt or 0) > 0:
                    lineage_sources.append(str(source_name))
            packet_payload = build_packet(
                project_key=project_key,
                session_context_key=session_context_key,
                tool_name=tool_name,
                intent_family=intent_family,
                task_plane=task_plane,
                advisory_text=synth_text or _baseline_text(intent_family),
                source_mode="live_ai" if synth_text else "live_deterministic",
                advice_items=_advice_to_rows_with_proof(
                    emitted_advice or advice_items,
                    trace_id=resolved_trace_id,
                ),
                lineage={
                    "sources": lineage_sources,
                    "memory_absent_declared": _infer_memory_absent_declared(
                        emitted_advice_source_counts or advice_source_counts
                    ),
                    "trace_id": resolved_trace_id,
                },
                trace_id=resolved_trace_id,
            )
            packet_id = save_packet(packet_payload)

        try:
            from .advice_feedback import record_advice_request

            record_advice_request(
                session_id=session_id,
                tool=tool_name,
                advice_ids=shown_ids,
                advice_texts=[str(getattr(a, "text", "") or "") for a in emitted_advice],
                sources=[str(getattr(a, "source", "") or "") for a in emitted_advice],
                trace_id=resolved_trace_id,
                route=route,
                packet_id=packet_id,
                min_interval_s=120,
            )
        except Exception as e:
            log_debug("advisory_engine", "AE_ADVICE_FEEDBACK_REQUEST_FAILED", e)

        state.last_advisory_packet_id = str(packet_id or "")
        state.last_advisory_route = str(route or "")
        state.last_advisory_tool = str(tool_name or "")
        state.last_advisory_advice_ids = list(shown_ids[:20])
        state.last_advisory_at = time.time()
        state.last_advisory_text_fingerprint = repeat_meta["fingerprint"]
        state.last_advisory_context_fingerprint = context_fp

        if packet_id:
            try:
                record_packet_usage(
                    packet_id,
                    emitted=bool(emitted),
                    route=route,
                    trace_id=resolved_trace_id,
                    tool_name=tool_name,
                )
            except Exception as e:
                log_debug("advisory_engine", "AE_PKT_USAGE_POST_EMIT_FAILED", e)

        save_state(state)

        _log_engine_event(
            "emitted" if emitted else "synth_empty",
            tool_name,
            len(advice_items),
            len(gate_result.emitted),
            start_ms,
            extra={
                **_diag(route),
                "route": route,
                "intent_family": intent_family,
                "task_plane": task_plane,
                "packet_id": packet_id,
                "intent_confidence": float(intent_info.get("confidence", 0.0) or 0.0),
                "stage_ms": stage_ms,
                "delivery_mode": "live" if emitted else "none",
                "emitted_text_preview": effective_text[:220],
                "advice_source_counts": emitted_advice_source_counts or advice_source_counts,
                "actionability_added": bool(action_meta.get("added")),
                "actionability_command": action_meta.get("command"),
                "effective_actionability_added": bool(effective_action_meta.get("added")),
                "effective_actionability_command": effective_action_meta.get("command"),
                "synth_fallback_used": bool(synth_fallback_used),
                "synth_policy": str(synth_policy),
                "selective_ai_eligible": bool(selective_ai_eligible),
                "selective_ai_min_authority": str(SELECTIVE_AI_MIN_AUTHORITY),
                "selective_ai_min_remaining_ms": float(SELECTIVE_AI_MIN_REMAINING_MS),
                "remaining_ms_before_synth": round(float(remaining_ms), 2),
                "emitted_authorities": [
                    str(getattr(decision, "authority", "") or "").strip().lower()
                for decision in list(getattr(gate_result, "emitted", []) or [])[:4]
                ],
            },
        )
        _record_advisory_decision_ledger(
            stage="emitted" if emitted else "synth_empty",
            outcome="emitted" if emitted else "none",
            tool_name=tool_name,
            intent_family=intent_family,
            task_plane=task_plane,
            route=route,
            packet_id=packet_id,
            advice_items=advice_items,
            gate_result=gate_result,
            session_id=session_id,
            trace_id=resolved_trace_id,
            extras={
                "delivery_mode": "live" if emitted else "none",
                "emitted_text_preview": effective_text[:220],
            },
        )
        return effective_text if emitted else None

    except Exception as e:
        log_debug("advisory_engine", f"on_pre_tool failed for {tool_name}", e)
        _record_advisory_decision_ledger(
            stage="engine_error",
            outcome="error",
            tool_name=tool_name,
            intent_family=intent_family,
            task_plane=task_plane,
            route=route,
            packet_id=packet_id if "packet_id" in locals() else None,
            advice_items=None,
            gate_result=None,
            session_id=session_id,
            trace_id=resolved_trace_id if "resolved_trace_id" in locals() else None,
            extras={
                "event": "engine_error",
                "error": str(e),
            },
        )
        _log_engine_event(
            "engine_error",
            tool_name,
            0,
            0,
            start_ms,
            extra={
                **_diag(route),
                **build_error_fields(str(e), "AE_ON_PRE_TOOL_FAILED"),
            },
        )
        _record_rejection("engine_error")
        return None


def on_post_tool(
    session_id: str,
    tool_name: str,
    success: bool,
    tool_input: Optional[dict] = None,
    trace_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    if not ENGINE_ENABLED:
        return
    start_ms = time.time() * 1000.0
    resolved_trace_id = trace_id

    try:
        from .advisory_state import (
            load_state,
            record_tool_call,
            resolve_recent_trace_id,
            save_state,
        )

        state = load_state(session_id)
        resolved_trace_id = trace_id or resolve_recent_trace_id(state, tool_name)
        record_tool_call(
            state,
            tool_name,
            tool_input,
            success=success,
            trace_id=resolved_trace_id,
        )

        # Outcome predictor (world-model-lite): record outcome for cheap risk scoring.
        try:
            from .outcome_predictor import record_outcome
            record_outcome(
                tool_name=tool_name,
                intent_family=state.intent_family or "emergent_other",
                phase=state.task_phase or "implementation",
                success=bool(success),
            )
        except Exception:
            pass

        if state.shown_advice_ids:
            _record_implicit_feedback(state, tool_name, success, resolved_trace_id)

        try:
            from .advisory_packet_store import record_packet_outcome

            last_packet_id = str(state.last_advisory_packet_id or "").strip()
            last_tool = str(state.last_advisory_tool or "").strip().lower()
            age_s = time.time() - float(state.last_advisory_at or 0.0)
            if (
                last_packet_id
                and last_tool
                and last_tool == str(tool_name or "").strip().lower()
                and age_s <= 900
            ):
                record_packet_outcome(
                    last_packet_id,
                    status=("acted" if bool(success) else "blocked"),
                    tool_name=str(tool_name or ""),
                    trace_id=resolved_trace_id,
                    notes=(str(error or "")[:200] if error else ""),
                    source="implicit_post_tool",
                    count_effectiveness=True,
                )
        except Exception as e:
            log_debug("advisory_engine", "AE_PKT_OUTCOME_POST_TOOL_FAILED", e)

        if tool_name in {"Edit", "Write"}:
            try:
                from .advisory_packet_store import invalidate_packets

                # Scope invalidation to packets matching the edited file,
                # not a blanket project-wide wipe.  Falls back to project
                # invalidation only if no file_path is available.
                file_hint = (tool_input or {}).get("file_path", "")
                if file_hint:
                    invalidate_packets(
                        project_key=_project_key(),
                        reason=f"post_tool_{tool_name.lower()}",
                        file_hint=file_hint,
                    )
                else:
                    invalidate_packets(
                        project_key=_project_key(),
                        reason=f"post_tool_{tool_name.lower()}",
                    )
            except Exception as e:
                log_debug("advisory_engine", "AE_PACKET_INVALIDATE_POST_EDIT_FAILED", e)

        save_state(state)
    except Exception as e:
        log_debug("advisory_engine", f"on_post_tool failed for {tool_name}", e)
        _log_engine_event(
            "post_tool_error",
            tool_name,
            0,
            0,
            start_ms,
            extra={
                **_diagnostics_envelope(
                    session_id=session_id,
                    trace_id=resolved_trace_id,
                    route="post_tool",
                    scope="session",
                ),
                **build_error_fields(str(e), "AE_ON_POST_TOOL_FAILED"),
            },
        )


def on_user_prompt(
    session_id: str,
    prompt_text: str,
    trace_id: Optional[str] = None,
) -> None:
    if not ENGINE_ENABLED:
        return
    start_ms = time.time() * 1000.0

    try:
        from .advisory_packet_store import build_packet, enqueue_prefetch_job, save_packet
        from .advisory_state import load_state, record_user_intent, save_state

        state = load_state(session_id)
        record_user_intent(state, prompt_text)
        resolved_trace_id = str(trace_id or "").strip() or f"spark-auto-{session_id[:16]}-user_prompt-{int(time.time()*1000)}"
        intent_info = _intent_context(state, tool_name="*")
        project_key = _project_key()
        session_context_key = _session_context_key(state, tool_name="*")
        intent_family = state.intent_family or "emergent_other"
        task_plane = state.task_plane or "build_delivery"
        save_state(state)

        baseline_text = _baseline_text(intent_family)
        baseline_action = _ensure_actionability(baseline_text, "*", task_plane)
        baseline_text = str(baseline_action.get("text") or baseline_text)
        baseline_proof = {
            "advice_id": f"baseline_{intent_family}",
            "insight_key": f"intent:{intent_family}",
            "source": "baseline",
        }
        baseline_packet = build_packet(
            project_key=project_key,
            session_context_key=session_context_key,
            tool_name="*",
            intent_family=intent_family,
            task_plane=task_plane,
            advisory_text=baseline_text,
            source_mode="baseline_deterministic",
            advice_items=[
                {
                    "advice_id": f"baseline_{intent_family}",
                    "insight_key": f"intent:{intent_family}",
                    "text": baseline_text,
                    "confidence": max(0.75, float(intent_info.get("confidence", 0.75) or 0.75)),
                    "source": "baseline",
                    "context_match": 0.8,
                    "reason": "session_baseline",
                    "proof_refs": baseline_proof,
                    "evidence_hash": _evidence_hash_for_row(
                        advice_text=baseline_text,
                        proof_refs=baseline_proof,
                    ),
                }
            ],
            lineage={"sources": ["baseline"], "memory_absent_declared": False},
        )
        save_packet(baseline_packet)

        if ENABLE_PREFETCH_QUEUE:
            enqueue_prefetch_job(
                {
                    "session_id": session_id,
                    "project_key": project_key,
                    "intent_family": intent_family,
                    "task_plane": task_plane,
                    "session_context_key": session_context_key,
                    "prompt_excerpt": (prompt_text or "")[:180],
                    "trace_id": resolved_trace_id,
                }
            )
            if ENABLE_INLINE_PREFETCH_WORKER:
                try:
                    from .advisory_prefetch_worker import process_prefetch_queue

                    process_prefetch_queue(
                        max_jobs=INLINE_PREFETCH_MAX_JOBS,
                        max_tools_per_job=3,
                    )
                except Exception as e:
                    log_debug("advisory_engine", "inline prefetch worker failed", e)

        _log_engine_event(
            "user_prompt_prefetch",
            "*",
            1,
            0,
            start_ms,
            extra={
                **_diagnostics_envelope(
                    session_id=session_id,
                    trace_id=resolved_trace_id,
                    route="user_prompt",
                    session_context_key=session_context_key,
                    scope="session",
                ),
                "intent_family": intent_family,
                "task_plane": task_plane,
                "packet_id": baseline_packet.get("packet_id"),
                "prefetch_queue_enabled": bool(ENABLE_PREFETCH_QUEUE),
            },
        )
    except Exception as e:
        log_debug("advisory_engine", "on_user_prompt failed", e)
        _log_engine_event(
            "user_prompt_error",
            "*",
            0,
            0,
            start_ms,
            extra={
                **_diagnostics_envelope(
                    session_id=session_id,
                    trace_id=str(trace_id or "").strip() or None,
                    route="user_prompt",
                    scope="session",
                ),
                **build_error_fields(str(e), "AE_ON_USER_PROMPT_FAILED"),
            },
        )


def _record_implicit_feedback(
    state,
    tool_name: str,
    success: bool,
    trace_id: Optional[str],
) -> None:
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

        shown_ids = set(state.shown_advice_ids.keys()) if isinstance(state.shown_advice_ids, dict) else set(state.shown_advice_ids or [])
        matching_ids = [aid for aid in recent.get("advice_ids", []) if aid in shown_ids]
        if not matching_ids:
            return

        # Record in the standalone implicit tracker so advisory packets can be traced
        # from a dedicated outcome stream.
        try:
            from .implicit_outcome_tracker import get_implicit_tracker

            tracker = get_implicit_tracker()
            tracker.record_advice(
                tool_name=tool_name,
                advice_texts=[str(x or "").strip() for x in (recent.get("advice_texts") or []) if str(x or "").strip()],
                advice_sources=(recent.get("sources") or [])[:5],
                trace_id=trace_id,
            )
        except Exception:
            tracker = None

        for aid in matching_ids[:3]:
            advisor.report_outcome(
                aid,
                was_followed=True,
                was_helpful=success,
                notes=f"implicit_feedback:{'success' if success else 'failure'}:{tool_name}",
                trace_id=trace_id,
            )
        if tracker:
            tracker.record_outcome(
                tool_name=tool_name,
                success=success,
                trace_id=trace_id,
            )

        log_debug(
            "advisory_engine",
            f"Implicit feedback: {len(matching_ids)} items, {'positive' if success else 'negative'} for {tool_name}",
            None,
        )
    except Exception as e:
        log_debug("advisory_engine", "implicit feedback failed", e)


def _log_engine_event(
    event: str,
    tool_name: str,
    advice_count: int,
    emitted_count: int,
    start_ms: float,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        elapsed_ms = (time.time() * 1000.0) - start_ms
        ENGINE_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "event": event,
            "tool": tool_name,
            "retrieved": advice_count,
            "emitted": emitted_count,
            "elapsed_ms": round(elapsed_ms, 1),
        }
        if extra:
            entry.update(extra)
        with open(ENGINE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        _rotate_engine_log()
    except Exception:
        pass


def _rotate_engine_log() -> None:
    try:
        if not ENGINE_LOG.exists():
            return
        lines = ENGINE_LOG.read_text(encoding="utf-8").splitlines()
        if len(lines) > ENGINE_LOG_MAX:
            keep = lines[-ENGINE_LOG_MAX:]
            ENGINE_LOG.write_text("\n".join(keep) + "\n", encoding="utf-8")
    except Exception:
        pass


def get_engine_status() -> Dict[str, Any]:
    status = {
        "enabled": ENGINE_ENABLED,
        "max_ms": MAX_ENGINE_MS,
        "config": get_engine_config(),
    }

    try:
        from .advisory_synthesizer import get_synth_status

        status["synthesizer"] = get_synth_status()
    except Exception:
        status["synthesizer"] = {"error": "unavailable"}

    try:
        from .advisory_emitter import get_emission_stats

        status["emitter"] = get_emission_stats()
    except Exception:
        status["emitter"] = {"error": "unavailable"}

    try:
        from .advisory_packet_store import get_store_status

        status["packet_store"] = get_store_status()
    except Exception:
        status["packet_store"] = {"error": "unavailable"}

    try:
        from .advisory_prefetch_worker import get_worker_status

        status["prefetch_worker"] = get_worker_status()
    except Exception:
        status["prefetch_worker"] = {"error": "unavailable"}

    status["decision_ledger"] = _decision_ledger_status()

    try:
        if ENGINE_LOG.exists():
            lines = ENGINE_LOG.read_text(encoding="utf-8").splitlines()
            parsed_tail: List[Dict[str, Any]] = []
            for line in lines[-100:]:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        parsed_tail.append(row)
                except Exception:
                    continue
            recent = parsed_tail[-10:]
            status["recent_events"] = recent
            status["total_events"] = len(lines)
            emitted = sum(1 for row in parsed_tail if row.get("event") == "emitted")
            total = len(parsed_tail)
            status["emission_rate"] = round(emitted / max(total, 1), 3)
            status["delivery_badge"] = _derive_delivery_badge(parsed_tail)
        else:
            status["recent_events"] = []
            status["total_events"] = 0
            status["emission_rate"] = 0.0
            status["delivery_badge"] = _derive_delivery_badge([])
    except Exception:
        status["delivery_badge"] = _derive_delivery_badge([])

    return status
