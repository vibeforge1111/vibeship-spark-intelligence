"""Advisory Engine Alpha: compact vertical-slice advisory path.

Scope:
- Minimal pre-tool loop: retrieve -> gate -> synthesize -> emit
- Strong trace binding on all emitted advice
- Context/text repeat suppression on hot path
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .diagnostics import log_debug
from .jsonl_utils import append_jsonl_capped as _append_jsonl_capped

ALPHA_ENABLED = os.getenv("SPARK_ADVISORY_ALPHA_ENABLED", "1") != "0"
ALPHA_PROGRAMMATIC_SYNTH_ONLY = os.getenv("SPARK_ADVISORY_ALPHA_SYNTH_PROGRAMMATIC", "1") != "0"
ALPHA_TEXT_REPEAT_COOLDOWN_S = max(
    30.0,
    float(os.getenv("SPARK_ADVISORY_TEXT_REPEAT_COOLDOWN_S", "600") or 600),
)
ALPHA_PREFETCH_QUEUE_ENABLED = os.getenv("SPARK_ADVISORY_PREFETCH_QUEUE", "1") != "0"
ALPHA_INLINE_PREFETCH_ENABLED = os.getenv("SPARK_ADVISORY_PREFETCH_INLINE", "1") != "0"
try:
    _alpha_inline_jobs = int(os.getenv("SPARK_ADVISORY_PREFETCH_INLINE_MAX_JOBS", "1") or 1)
except Exception:
    _alpha_inline_jobs = 1
ALPHA_INLINE_PREFETCH_MAX_JOBS = max(1, min(20, _alpha_inline_jobs))
ALPHA_LOG = Path.home() / ".spark" / "advisory_engine_alpha.jsonl"
ALPHA_LOG_MAX_LINES = 2000


def _hash_text(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


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
    _append_jsonl_capped(ALPHA_LOG, row, ALPHA_LOG_MAX_LINES, ensure_ascii=True)


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


def _project_key() -> str:
    try:
        from .memory_banks import infer_project_key

        key = infer_project_key()
        if key:
            return str(key)
    except Exception:
        pass
    return "unknown_project"


def _resolve_intent(prompt: str, tool_name: str = "*") -> Dict[str, Any]:
    try:
        from .advisory_intent_taxonomy import map_intent

        return map_intent(prompt or "", tool_name=tool_name)
    except Exception:
        return {
            "intent_family": "emergent_other",
            "task_plane": "build_delivery",
            "confidence": 0.0,
            "reason": "fallback",
        }


def _session_context_key(session_id: str, intent_family: str) -> str:
    seed = f"{session_id}|{intent_family or 'emergent_other'}"
    return hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _baseline_text(intent_family: str) -> str:
    defaults = {
        "auth_security": "Validate auth inputs and keep sensitive values out of logs before editing.",
        "deployment_ops": "Use reversible deployment steps and verify rollback before release actions.",
        "testing_validation": "Run focused tests after edits and confirm failing cases are reproducible.",
        "schema_contracts": "Check contract compatibility before changing payload shapes or interfaces.",
        "performance_latency": "Keep hot-path edits measurable and compare latency before and after.",
        "emergent_other": "Use conservative, test-backed edits and verify assumptions before irreversible actions.",
    }
    return defaults.get(intent_family, defaults["emergent_other"])


def _proof_hash(advice_text: str, advice_id: str, insight_key: str, source: str, trace_id: str) -> str:
    raw = f"{advice_text.strip().lower()}|{advice_id}|{insight_key}|{source}|{trace_id}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


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
    if not ALPHA_ENABLED:
        return
    start = time.time()
    resolved_trace_id = str(trace_id or "").strip()
    try:
        from .advisory_state import load_state, record_tool_call, resolve_recent_trace_id, save_state

        state = load_state(session_id)
        if not resolved_trace_id:
            resolved_trace_id = str(resolve_recent_trace_id(state, tool_name) or "").strip()
        if not resolved_trace_id:
            resolved_trace_id = f"spark-alpha-{session_id[:16]}-{tool_name.lower()}-post-{int(time.time() * 1000)}"

        record_tool_call(
            state,
            tool_name,
            tool_input,
            success=bool(success),
            trace_id=resolved_trace_id,
        )

        try:
            from .outcome_predictor import record_outcome

            record_outcome(
                tool_name=tool_name,
                intent_family=state.intent_family or "emergent_other",
                phase=state.task_phase or "implementation",
                success=bool(success),
            )
        except Exception as exc:
            log_debug("advisory_engine_alpha", "post-tool outcome predictor failed", exc)

        if state.shown_advice_ids:
            try:
                from .advisory_engine import _record_implicit_feedback

                _record_implicit_feedback(state, tool_name, bool(success), resolved_trace_id)
            except Exception as exc:
                log_debug("advisory_engine_alpha", "post-tool implicit feedback failed", exc)

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
                    source="alpha_implicit_post_tool",
                    count_effectiveness=True,
                )
        except Exception as exc:
            log_debug("advisory_engine_alpha", "post-tool packet outcome failed", exc)

        if tool_name in {"Edit", "Write"}:
            try:
                from .advisory_packet_store import invalidate_packets

                file_hint = (tool_input or {}).get("file_path", "")
                if file_hint:
                    invalidate_packets(
                        project_key=_project_key(),
                        reason=f"post_tool_{str(tool_name or '').lower()}",
                        file_hint=file_hint,
                    )
                else:
                    invalidate_packets(
                        project_key=_project_key(),
                        reason=f"post_tool_{str(tool_name or '').lower()}",
                    )
            except Exception as exc:
                log_debug("advisory_engine_alpha", "post-tool packet invalidate failed", exc)

        save_state(state)
        _log_alpha(
            "post_tool_recorded",
            session_id=session_id,
            tool_name=tool_name,
            trace_id=resolved_trace_id,
            emitted=False,
            elapsed_ms=(time.time() - start) * 1000.0,
            extra={"success": bool(success)},
        )
    except Exception as exc:
        log_debug("advisory_engine_alpha", "on_post_tool failed", exc)
        _log_alpha(
            "post_tool_error",
            session_id=session_id,
            tool_name=tool_name,
            trace_id=resolved_trace_id,
            emitted=False,
            elapsed_ms=(time.time() - start) * 1000.0,
            extra={"error": str(exc)[:240]},
        )


def on_user_prompt(
    session_id: str,
    prompt_text: str,
    trace_id: Optional[str] = None,
) -> None:
    if not ALPHA_ENABLED:
        return
    start = time.time()
    resolved_trace_id = str(trace_id or "").strip() or f"spark-alpha-{session_id[:16]}-user-{int(time.time() * 1000)}"
    try:
        from .advisory_packet_store import build_packet, enqueue_prefetch_job, save_packet
        from .advisory_state import load_state, record_user_intent, save_state

        state = load_state(session_id)
        record_user_intent(state, prompt_text)
        intent = _resolve_intent(state.user_intent or prompt_text, tool_name="*")
        state.intent_family = str(intent.get("intent_family") or "emergent_other")
        state.intent_confidence = float(intent.get("confidence", 0.0) or 0.0)
        state.task_plane = str(intent.get("task_plane") or "build_delivery")
        state.intent_reason = str(intent.get("reason") or "fallback")

        project_key = _project_key()
        session_ctx = _session_context_key(state.session_id, state.intent_family)
        save_state(state)

        baseline_text = _baseline_text(state.intent_family)
        baseline_advice_id = f"baseline_{state.intent_family}"
        baseline_insight_key = f"intent:{state.intent_family}"
        proof_refs = {
            "advice_id": baseline_advice_id,
            "insight_key": baseline_insight_key,
            "source": "baseline",
            "trace_id": resolved_trace_id,
        }
        baseline_packet = build_packet(
            project_key=project_key,
            session_context_key=session_ctx,
            tool_name="*",
            intent_family=state.intent_family,
            task_plane=state.task_plane,
            advisory_text=baseline_text,
            source_mode="baseline_deterministic_alpha",
            advice_items=[
                {
                    "advice_id": baseline_advice_id,
                    "insight_key": baseline_insight_key,
                    "text": baseline_text,
                    "confidence": max(0.75, float(state.intent_confidence or 0.75)),
                    "source": "baseline",
                    "context_match": 0.8,
                    "reason": "alpha_session_baseline",
                    "proof_refs": proof_refs,
                    "evidence_hash": _proof_hash(
                        baseline_text,
                        baseline_advice_id,
                        baseline_insight_key,
                        "baseline",
                        resolved_trace_id,
                    ),
                }
            ],
            lineage={"sources": ["baseline"], "memory_absent_declared": False, "trace_id": resolved_trace_id},
            trace_id=resolved_trace_id,
        )
        save_packet(baseline_packet)

        if ALPHA_PREFETCH_QUEUE_ENABLED:
            enqueue_prefetch_job(
                {
                    "session_id": session_id,
                    "project_key": project_key,
                    "intent_family": state.intent_family,
                    "task_plane": state.task_plane,
                    "session_context_key": session_ctx,
                    "prompt_excerpt": str(prompt_text or "")[:180],
                    "trace_id": resolved_trace_id,
                    "alpha_route": True,
                }
            )
            if ALPHA_INLINE_PREFETCH_ENABLED:
                try:
                    from .advisory_prefetch_worker import process_prefetch_queue

                    process_prefetch_queue(
                        max_jobs=ALPHA_INLINE_PREFETCH_MAX_JOBS,
                        max_tools_per_job=3,
                    )
                except Exception as exc:
                    log_debug("advisory_engine_alpha", "inline prefetch worker failed", exc)

        _log_alpha(
            "user_prompt_prefetch",
            session_id=session_id,
            tool_name="*",
            trace_id=resolved_trace_id,
            emitted=False,
            elapsed_ms=(time.time() - start) * 1000.0,
            extra={
                "intent_family": state.intent_family,
                "task_plane": state.task_plane,
                "packet_id": str(baseline_packet.get("packet_id") or ""),
                "prefetch_queue_enabled": bool(ALPHA_PREFETCH_QUEUE_ENABLED),
            },
        )
    except Exception as exc:
        log_debug("advisory_engine_alpha", "on_user_prompt failed", exc)
        _log_alpha(
            "user_prompt_error",
            session_id=session_id,
            tool_name="*",
            trace_id=resolved_trace_id,
            emitted=False,
            elapsed_ms=(time.time() - start) * 1000.0,
            extra={"error": str(exc)[:240]},
        )
