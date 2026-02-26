"""Advisory Engine Alpha: compact vertical-slice advisory path.

Scope:
- Minimal pre-tool loop: retrieve -> gate -> synthesize -> emit
- Strong trace binding on all emitted advice
- Context/text repeat suppression on hot path
- Keep post-tool and user-prompt paths delegated to legacy engine for now
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .diagnostics import log_debug

ALPHA_ENABLED = os.getenv("SPARK_ADVISORY_ALPHA_ENABLED", "1") != "0"
ALPHA_PROGRAMMATIC_SYNTH_ONLY = os.getenv("SPARK_ADVISORY_ALPHA_SYNTH_PROGRAMMATIC", "1") != "0"
ALPHA_TEXT_REPEAT_COOLDOWN_S = max(
    30.0,
    float(os.getenv("SPARK_ADVISORY_TEXT_REPEAT_COOLDOWN_S", "600") or 600),
)
ALPHA_LOG = Path.home() / ".spark" / "advisory_engine_alpha.jsonl"
ALPHA_LOG_MAX_LINES = 2000


def _hash_text(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _append_jsonl_capped(path: Path, row: Dict[str, Any], max_lines: int) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")
    except Exception:
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > max_lines:
            path.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def _log_alpha(
    event: str,
    *,
    session_id: str,
    tool_name: str,
    trace_id: str,
    emitted: bool,
    route: str = "alpha",
    elapsed_ms: float = 0.0,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    row = {
        "ts": time.time(),
        "event": str(event or "").strip() or "unknown",
        "session_id": str(session_id or "").strip(),
        "tool_name": str(tool_name or "").strip(),
        "trace_id": str(trace_id or "").strip(),
        "route": str(route or "alpha"),
        "emitted": bool(emitted),
        "elapsed_ms": round(max(0.0, float(elapsed_ms or 0.0)), 2),
    }
    if isinstance(extra, dict):
        row["extra"] = extra
    _append_jsonl_capped(ALPHA_LOG, row, ALPHA_LOG_MAX_LINES)


def _dedupe_advice_items(advice_items: List[Any]) -> List[Any]:
    """Drop repeated text variants so alpha emits one coherent signal."""
    out: List[Any] = []
    seen: set[str] = set()
    for item in list(advice_items or []):
        sig = _hash_text(getattr(item, "text", ""))
        if not sig or sig in seen:
            continue
        seen.add(sig)
        out.append(item)
    return out


def _is_repeat_blocked(state: Any, tool_name: str, text_fingerprint: str, context_fingerprint: str) -> bool:
    if not state:
        return False
    now = time.time()
    last_ts = float(getattr(state, "last_advisory_at", 0.0) or 0.0)
    if last_ts <= 0.0:
        return False
    age_s = now - last_ts
    if age_s < 0 or age_s >= float(ALPHA_TEXT_REPEAT_COOLDOWN_S):
        return False
    same_tool = str(getattr(state, "last_advisory_tool", "") or "").strip().lower() == str(tool_name or "").strip().lower()
    same_ctx = str(getattr(state, "last_advisory_context_fingerprint", "") or "") == context_fingerprint
    same_text = str(getattr(state, "last_advisory_text_fingerprint", "") or "") == text_fingerprint
    return bool(same_tool and (same_ctx or same_text))


def on_pre_tool(
    session_id: str,
    tool_name: str,
    tool_input: Optional[dict] = None,
    trace_id: Optional[str] = None,
) -> Optional[str]:
    if not ALPHA_ENABLED:
        return None
    start = time.time()
    resolved_trace_id = str(trace_id or "").strip()
    tool_payload = tool_input or {}

    try:
        from .advisor import advise_on_tool, record_recent_delivery
        from .advisory_emitter import emit_advisory
        from .advisory_gate import evaluate, get_tool_cooldown_s
        from .advisory_state import (
            load_state,
            mark_advice_shown,
            record_tool_call,
            resolve_recent_trace_id,
            save_state,
            suppress_tool_advice,
        )
        from .advisory_synthesizer import synthesize
        from .meta_ralph import get_meta_ralph

        state = load_state(session_id)
        if not resolved_trace_id:
            resolved_trace_id = str(resolve_recent_trace_id(state, tool_name) or "").strip()
        if not resolved_trace_id:
            resolved_trace_id = f"spark-alpha-{session_id[:16]}-{tool_name.lower()}-{int(time.time() * 1000)}"

        record_tool_call(state, tool_name, tool_payload, success=None, trace_id=resolved_trace_id)
        user_intent = str(getattr(state, "user_intent", "") or "").strip()
        context_fingerprint = _hash_text(f"{tool_name}|{user_intent}")

        advice_items = advise_on_tool(
            tool_name,
            tool_payload,
            context=user_intent,
            include_mind=True,
            track_retrieval=False,
            log_recent=False,
            trace_id=resolved_trace_id,
        )
        if not advice_items:
            save_state(state)
            _log_alpha(
                "no_advice",
                session_id=session_id,
                tool_name=tool_name,
                trace_id=resolved_trace_id,
                emitted=False,
                elapsed_ms=(time.time() - start) * 1000.0,
            )
            return None

        gate_result = evaluate(advice_items, state, tool_name, tool_payload)
        if not gate_result.emitted:
            save_state(state)
            _log_alpha(
                "gate_no_emit",
                session_id=session_id,
                tool_name=tool_name,
                trace_id=resolved_trace_id,
                emitted=False,
                elapsed_ms=(time.time() - start) * 1000.0,
                extra={"retrieved": len(advice_items)},
            )
            return None

        advice_by_id = {str(getattr(a, "advice_id", "") or ""): a for a in advice_items}
        emitted_items = []
        for decision in list(gate_result.emitted or []):
            item = advice_by_id.get(str(getattr(decision, "advice_id", "") or ""))
            if item is not None:
                emitted_items.append(item)
        emitted_items = _dedupe_advice_items(emitted_items)
        if not emitted_items:
            save_state(state)
            _log_alpha(
                "dedupe_empty",
                session_id=session_id,
                tool_name=tool_name,
                trace_id=resolved_trace_id,
                emitted=False,
                elapsed_ms=(time.time() - start) * 1000.0,
            )
            return None

        emitted_ids = {str(getattr(a, "advice_id", "") or "") for a in emitted_items}
        gate_result.emitted = [
            d for d in list(gate_result.emitted or [])
            if str(getattr(d, "advice_id", "") or "") in emitted_ids
        ]
        if not gate_result.emitted:
            save_state(state)
            _log_alpha(
                "dedupe_gate_empty",
                session_id=session_id,
                tool_name=tool_name,
                trace_id=resolved_trace_id,
                emitted=False,
                elapsed_ms=(time.time() - start) * 1000.0,
            )
            return None

        synth_text = synthesize(
            emitted_items,
            phase=str(getattr(state, "task_phase", "") or "implementation"),
            user_intent=user_intent,
            tool_name=tool_name,
            force_mode="programmatic" if ALPHA_PROGRAMMATIC_SYNTH_ONLY else None,
        )
        effective_text = str(synth_text or getattr(emitted_items[0], "text", "") or "").strip()
        text_fingerprint = _hash_text(effective_text)
        if _is_repeat_blocked(state, tool_name, text_fingerprint, context_fingerprint):
            save_state(state)
            _log_alpha(
                "context_repeat_blocked",
                session_id=session_id,
                tool_name=tool_name,
                trace_id=resolved_trace_id,
                emitted=False,
                elapsed_ms=(time.time() - start) * 1000.0,
                extra={"cooldown_s": float(ALPHA_TEXT_REPEAT_COOLDOWN_S)},
            )
            return None

        emitted = emit_advisory(
            gate_result,
            synth_text,
            emitted_items,
            trace_id=resolved_trace_id,
            tool_name=tool_name,
            route="alpha",
            task_plane=str(getattr(state, "task_plane", "") or "build_delivery"),
        )
        if not emitted:
            save_state(state)
            _log_alpha(
                "emit_suppressed",
                session_id=session_id,
                tool_name=tool_name,
                trace_id=resolved_trace_id,
                emitted=False,
                elapsed_ms=(time.time() - start) * 1000.0,
            )
            return None

        emitted_ids_ordered = [str(getattr(a, "advice_id", "") or "") for a in emitted_items if str(getattr(a, "advice_id", "") or "").strip()]
        mark_advice_shown(
            state,
            emitted_ids_ordered,
            tool_name=tool_name,
            task_phase=str(getattr(state, "task_phase", "") or "implementation"),
        )
        suppress_tool_advice(state, tool_name, duration_s=float(get_tool_cooldown_s()))
        state.last_advisory_packet_id = ""
        state.last_advisory_route = "alpha"
        state.last_advisory_tool = str(tool_name or "")
        state.last_advisory_advice_ids = emitted_ids_ordered[:8]
        state.last_advisory_at = time.time()
        state.last_advisory_text_fingerprint = text_fingerprint
        state.last_advisory_context_fingerprint = context_fingerprint
        save_state(state)

        try:
            ralph = get_meta_ralph()
            for item in emitted_items[:8]:
                aid = str(getattr(item, "advice_id", "") or "").strip()
                if not aid:
                    continue
                ralph.track_retrieval(
                    aid,
                    str(getattr(item, "text", "") or ""),
                    insight_key=str(getattr(item, "insight_key", "") or ""),
                    source=str(getattr(item, "source", "") or "alpha"),
                    trace_id=resolved_trace_id,
                )
        except Exception as exc:
            log_debug("advisory_engine_alpha", "meta ralph retrieval tracking failed", exc)

        try:
            record_recent_delivery(
                tool=tool_name,
                advice_list=emitted_items,
                trace_id=resolved_trace_id,
                route="alpha",
                delivered=True,
                categories=[str(getattr(a, "category", "general") or "general") for a in emitted_items],
                advisory_readiness=[float(getattr(a, "advisory_readiness", 0.0) or 0.0) for a in emitted_items],
                advisory_quality=[getattr(a, "advisory_quality", None) or {} for a in emitted_items],
            )
        except Exception as exc:
            log_debug("advisory_engine_alpha", "record_recent_delivery failed", exc)

        _log_alpha(
            "emitted",
            session_id=session_id,
            tool_name=tool_name,
            trace_id=resolved_trace_id,
            emitted=True,
            elapsed_ms=(time.time() - start) * 1000.0,
            extra={
                "retrieved": len(advice_items),
                "emitted_count": len(emitted_items),
                "task_phase": str(getattr(state, "task_phase", "") or ""),
                "task_plane": str(getattr(state, "task_plane", "") or ""),
            },
        )
        return effective_text if effective_text else None
    except Exception as exc:
        log_debug("advisory_engine_alpha", "on_pre_tool failed", exc)
        _log_alpha(
            "engine_error",
            session_id=session_id,
            tool_name=tool_name,
            trace_id=resolved_trace_id,
            emitted=False,
            elapsed_ms=(time.time() - start) * 1000.0,
            extra={"error": str(exc)[:240]},
        )
        return None


def on_post_tool(
    session_id: str,
    tool_name: str,
    success: bool,
    tool_input: Optional[dict] = None,
    trace_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Delegate to legacy post-tool handler while alpha pretool is being validated."""
    try:
        from .advisory_engine import on_post_tool as _legacy_on_post_tool

        _legacy_on_post_tool(
            session_id=session_id,
            tool_name=tool_name,
            success=bool(success),
            tool_input=tool_input,
            trace_id=trace_id,
            error=error,
        )
    except Exception as exc:
        log_debug("advisory_engine_alpha", "on_post_tool delegate failed", exc)


def on_user_prompt(
    session_id: str,
    prompt_text: str,
    trace_id: Optional[str] = None,
) -> None:
    """Delegate to legacy user-prompt handler while alpha pretool is being validated."""
    try:
        from .advisory_engine import on_user_prompt as _legacy_on_user_prompt

        _legacy_on_user_prompt(
            session_id=session_id,
            prompt_text=prompt_text,
            trace_id=trace_id,
        )
    except Exception as exc:
        log_debug("advisory_engine_alpha", "on_user_prompt delegate failed", exc)

