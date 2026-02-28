"""Advisory Engine Alpha: compact vertical-slice advisory path.

Scope:
- Minimal pre-tool loop: retrieve -> gate -> synthesize -> emit
- Strong trace binding on all emitted advice
- Context/text repeat suppression on hot path
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .diagnostics import log_debug
from .jsonl_utils import append_jsonl_capped as _append_jsonl_capped
from .jsonl_utils import tail_jsonl_objects as _tail_jsonl_objects

ALPHA_ENABLED = os.getenv("SPARK_ADVISORY_ALPHA_ENABLED", "1") != "0"
ALPHA_PROGRAMMATIC_SYNTH_ONLY = os.getenv("SPARK_ADVISORY_ALPHA_SYNTH_PROGRAMMATIC", "1") != "0"
ALPHA_TEXT_REPEAT_COOLDOWN_S = max(
    30.0,
    float(os.getenv("SPARK_ADVISORY_TEXT_REPEAT_COOLDOWN_S", "600") or 600),
)
ALPHA_GLOBAL_DEDUPE_COOLDOWN_S = max(
    0.0,
    float(os.getenv("SPARK_ADVISORY_GLOBAL_DEDUPE_COOLDOWN_S", "600") or 600),
)
ALPHA_PREFETCH_QUEUE_ENABLED = os.getenv("SPARK_ADVISORY_PREFETCH_QUEUE", "1") != "0"
ALPHA_INLINE_PREFETCH_ENABLED = os.getenv("SPARK_ADVISORY_PREFETCH_INLINE", "1") != "0"
try:
    _alpha_inline_jobs = int(os.getenv("SPARK_ADVISORY_PREFETCH_INLINE_MAX_JOBS", "1") or 1)
except Exception:
    _alpha_inline_jobs = 1
ALPHA_INLINE_PREFETCH_MAX_JOBS = max(1, min(20, _alpha_inline_jobs))
JSONL_EXT = ".jsonl"
ALPHA_LOG = Path.home() / ".spark" / f"advisory_engine_alpha{JSONL_EXT}"
ALPHA_LOG_MAX_LINES = 2000
ADVISORY_DECISION_LEDGER_FILE = Path.home() / ".spark" / f"advisory_decision_ledger{JSONL_EXT}"
ADVISORY_DECISION_LEDGER_MAX_LINES = 12000
ADVISORY_GLOBAL_DEDUPE_FILE = Path.home() / ".spark" / f"advisory_global_dedupe{JSONL_EXT}"
ADVISORY_GLOBAL_DEDUPE_MAX_LINES = 5000
_QUESTION_START_RE = re.compile(
    r"^\s*(what|why|how|when|where|who|do|does|did|should|would|could|can|is|are|am|will)\b",
    re.I,
)
_CONVERSATIONAL_RE = re.compile(
    r"\b(can you|could you|would you|should we|do we|i('?| a)?m not sure|not sure about)\b",
    re.I,
)
_DECISION_OUTCOME_BY_EVENT = {
    "emitted": "emitted",
    "gate_no_emit": "blocked",
    "dedupe_empty": "blocked",
    "dedupe_gate_empty": "blocked",
    "question_like_blocked": "blocked",
    "context_repeat_blocked": "blocked",
    "text_repeat_blocked": "blocked",
    "global_dedupe_suppressed": "blocked",
    "emit_suppressed": "blocked",
    "no_advice": "blocked",
    "engine_error": "blocked",
}


def _parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _load_alpha_config(path: Optional[Path] = None) -> Dict[str, Any]:
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
    from .config_authority import env_bool, env_float, env_int, resolve_section

    cfg = resolve_section(
        "advisory_engine",
        runtime_path=tuneables,
        env_overrides={
            "enabled": env_bool("SPARK_ADVISORY_ALPHA_ENABLED"),
            "force_programmatic_synth": env_bool("SPARK_ADVISORY_ALPHA_SYNTH_PROGRAMMATIC"),
            "advisory_text_repeat_cooldown_s": env_float("SPARK_ADVISORY_TEXT_REPEAT_COOLDOWN_S"),
            "global_dedupe_cooldown_s": env_float("SPARK_ADVISORY_GLOBAL_DEDUPE_COOLDOWN_S"),
            "prefetch_queue_enabled": env_bool("SPARK_ADVISORY_PREFETCH_QUEUE"),
            "prefetch_inline_enabled": env_bool("SPARK_ADVISORY_PREFETCH_INLINE"),
            "prefetch_inline_max_jobs": env_int("SPARK_ADVISORY_PREFETCH_INLINE_MAX_JOBS"),
        },
    ).data
    return cfg if isinstance(cfg, dict) else {}


def apply_alpha_config(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    global ALPHA_ENABLED
    global ALPHA_PROGRAMMATIC_SYNTH_ONLY
    global ALPHA_TEXT_REPEAT_COOLDOWN_S
    global ALPHA_GLOBAL_DEDUPE_COOLDOWN_S
    global ALPHA_PREFETCH_QUEUE_ENABLED
    global ALPHA_INLINE_PREFETCH_ENABLED
    global ALPHA_INLINE_PREFETCH_MAX_JOBS

    applied: List[str] = []
    warnings: List[str] = []
    if not isinstance(cfg, dict):
        return {"applied": applied, "warnings": warnings}

    if "enabled" in cfg:
        ALPHA_ENABLED = _parse_bool(cfg.get("enabled"), ALPHA_ENABLED)
        applied.append("enabled")

    if "force_programmatic_synth" in cfg:
        ALPHA_PROGRAMMATIC_SYNTH_ONLY = _parse_bool(
            cfg.get("force_programmatic_synth"),
            ALPHA_PROGRAMMATIC_SYNTH_ONLY,
        )
        applied.append("force_programmatic_synth")

    if "advisory_text_repeat_cooldown_s" in cfg:
        try:
            ALPHA_TEXT_REPEAT_COOLDOWN_S = max(
                30.0,
                min(86400.0, float(cfg.get("advisory_text_repeat_cooldown_s") or 600.0)),
            )
            applied.append("advisory_text_repeat_cooldown_s")
        except Exception:
            warnings.append("invalid_advisory_text_repeat_cooldown_s")

    if "global_dedupe_cooldown_s" in cfg:
        try:
            ALPHA_GLOBAL_DEDUPE_COOLDOWN_S = max(
                0.0,
                min(86400.0, float(cfg.get("global_dedupe_cooldown_s") or 600.0)),
            )
            applied.append("global_dedupe_cooldown_s")
        except Exception:
            warnings.append("invalid_global_dedupe_cooldown_s")

    if "prefetch_queue_enabled" in cfg:
        ALPHA_PREFETCH_QUEUE_ENABLED = _parse_bool(
            cfg.get("prefetch_queue_enabled"),
            ALPHA_PREFETCH_QUEUE_ENABLED,
        )
        applied.append("prefetch_queue_enabled")

    if "prefetch_inline_enabled" in cfg:
        ALPHA_INLINE_PREFETCH_ENABLED = _parse_bool(
            cfg.get("prefetch_inline_enabled"),
            ALPHA_INLINE_PREFETCH_ENABLED,
        )
        applied.append("prefetch_inline_enabled")

    if "prefetch_inline_max_jobs" in cfg:
        try:
            ALPHA_INLINE_PREFETCH_MAX_JOBS = max(
                1,
                min(20, int(cfg.get("prefetch_inline_max_jobs") or 1)),
            )
            applied.append("prefetch_inline_max_jobs")
        except Exception:
            warnings.append("invalid_prefetch_inline_max_jobs")

    return {"applied": applied, "warnings": warnings}


def get_alpha_config() -> Dict[str, Any]:
    return {
        "enabled": bool(ALPHA_ENABLED),
        "force_programmatic_synth": bool(ALPHA_PROGRAMMATIC_SYNTH_ONLY),
        "advisory_text_repeat_cooldown_s": float(ALPHA_TEXT_REPEAT_COOLDOWN_S),
        "global_dedupe_cooldown_s": float(ALPHA_GLOBAL_DEDUPE_COOLDOWN_S),
        "prefetch_queue_enabled": bool(ALPHA_PREFETCH_QUEUE_ENABLED),
        "prefetch_inline_enabled": bool(ALPHA_INLINE_PREFETCH_ENABLED),
        "prefetch_inline_max_jobs": int(ALPHA_INLINE_PREFETCH_MAX_JOBS),
    }


def get_alpha_status() -> Dict[str, Any]:
    return {
        "enabled": bool(ALPHA_ENABLED),
        "config": get_alpha_config(),
        "alpha_log": str(ALPHA_LOG),
    }


def _reload_alpha_from_section(cfg: Dict[str, Any]) -> None:
    apply_alpha_config(cfg)


_BOOT_ALPHA_CFG = _load_alpha_config()
if _BOOT_ALPHA_CFG:
    apply_alpha_config(_BOOT_ALPHA_CFG)

try:
    from .tuneables_reload import register_reload as _alpha_register

    _alpha_register("advisory_engine", _reload_alpha_from_section, label="advisory_engine_alpha.apply_config")
except Exception as exc:
    log_debug("advisory_engine_alpha", f"hot-reload registration failed: {exc}", None)


def _hash_text(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _advice_text_sig(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text.startswith("[") and "]" in text[:40]:
        text = text.split("]", 1)[-1].strip()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    return hashlib.sha1(text[:240].encode("utf-8", errors="ignore")).hexdigest()[:16]


def _is_question_like_advice(text: str) -> bool:
    sample = str(text or "").strip().lower()
    if not sample:
        return False
    if sample.endswith("?"):
        return True
    if _QUESTION_START_RE.match(sample):
        return True
    if _CONVERSATIONAL_RE.search(sample) and len(sample.split()) <= 28:
        return True
    return False


def _first_non_question_text(emitted_items: List[Any]) -> str:
    for item in emitted_items or []:
        candidate = str(getattr(item, "text", "") or "").strip()
        if candidate and (not _is_question_like_advice(candidate)):
            return candidate
    return ""


def _sanitize_emission_text(*, text: str, emitted_items: List[Any], tool_name: str) -> Tuple[str, str]:
    sample = str(text or "").strip()
    if not sample:
        return "", "empty"
    if not _is_question_like_advice(sample):
        return sample, "as_is"
    fallback = _first_non_question_text(emitted_items)
    if fallback:
        return fallback, "fallback_item_text"
    tool = str(tool_name or "").strip() or "the next tool call"
    rewritten = f"Run one concrete pre-flight check for {tool} and proceed with the safest next step."
    return rewritten, "rewritten_from_question_like"


def _safe_ts(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _should_bypass_global_dedupe(session_id: str, trace_id: str) -> bool:
    sid = str(session_id or "").strip().lower()
    tid = str(trace_id or "").strip().lower()
    if sid.startswith("advisory-bench-"):
        return True
    if tid.startswith("bench:"):
        return True
    if tid.startswith("arena:"):
        return True
    if tid.startswith("delta-"):
        return True
    return False


def _load_recent_global_dedupe_snapshot(
    *,
    cooldown_s: float,
    limit: int = 1200,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    by_advice_id: Dict[str, float] = {}
    by_text_sig: Dict[str, float] = {}
    if cooldown_s <= 0.0:
        return by_advice_id, by_text_sig
    rows = _tail_jsonl_objects(ADVISORY_GLOBAL_DEDUPE_FILE, max(1, int(limit)))
    if not rows:
        return by_advice_id, by_text_sig
    now = time.time()
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _safe_ts(row.get("ts") or row.get("timestamp") or row.get("created_at"))
        if ts <= 0.0:
            continue
        age_s = now - ts
        if age_s < 0.0 or age_s > cooldown_s:
            continue
        advice_id = str(row.get("advice_id") or "").strip()
        if advice_id and advice_id not in by_advice_id:
            by_advice_id[advice_id] = age_s
        text_sig = str(row.get("text_sig") or "").strip()
        if not text_sig:
            text_sig = _advice_text_sig(str(row.get("text") or row.get("advice_text") or ""))
        if text_sig and text_sig not in by_text_sig:
            by_text_sig[text_sig] = age_s
    return by_advice_id, by_text_sig


def _record_global_dedupe_rows(
    *,
    emitted_items: List[Any],
    effective_text: str,
    session_id: str,
    tool_name: str,
    trace_id: str,
) -> None:
    now = time.time()
    written_sigs: set[str] = set()
    for item in emitted_items or []:
        advice_id = str(getattr(item, "advice_id", "") or "").strip()
        advice_text = str(getattr(item, "text", "") or "").strip()
        text_sig = _advice_text_sig(advice_text)
        if not advice_id and not text_sig:
            continue
        _append_jsonl_capped(
            ADVISORY_GLOBAL_DEDUPE_FILE,
            {
                "ts": now,
                "session_id": str(session_id or "").strip(),
                "tool_name": str(tool_name or "").strip(),
                "trace_id": str(trace_id or "").strip(),
                "advice_id": advice_id,
                "text_sig": text_sig,
                "text": advice_text[:300],
                "source": str(getattr(item, "source", "") or "").strip(),
            },
            ADVISORY_GLOBAL_DEDUPE_MAX_LINES,
            ensure_ascii=True,
        )
        if text_sig:
            written_sigs.add(text_sig)
    effective_sig = _advice_text_sig(effective_text)
    if effective_sig and effective_sig not in written_sigs:
        _append_jsonl_capped(
            ADVISORY_GLOBAL_DEDUPE_FILE,
            {
                "ts": now,
                "session_id": str(session_id or "").strip(),
                "tool_name": str(tool_name or "").strip(),
                "trace_id": str(trace_id or "").strip(),
                "advice_id": "",
                "text_sig": effective_sig,
                "text": str(effective_text or "").strip()[:300],
                "source": "alpha_synth",
            },
            ADVISORY_GLOBAL_DEDUPE_MAX_LINES,
            ensure_ascii=True,
        )


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
    _log_decision_ledger(row)


def _decision_outcome_for_row(row: Dict[str, Any]) -> str:
    outcome = str(row.get("outcome") or "").strip().lower()
    if outcome:
        return outcome
    event = str(row.get("event") or "").strip().lower()
    mapped = _DECISION_OUTCOME_BY_EVENT.get(event)
    if mapped:
        return mapped
    if bool(row.get("emitted")):
        return "emitted"
    return ""


def _log_decision_ledger(row: Dict[str, Any]) -> None:
    try:
        outcome = _decision_outcome_for_row(row)
        if outcome not in {"emitted", "blocked"}:
            return

        event = str(row.get("event") or "").strip().lower()
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        gate_reason = ""
        if isinstance(extra, dict):
            gate_reason = str(extra.get("gate_reason") or extra.get("reason") or "").strip()
        if not gate_reason and outcome == "blocked":
            gate_reason = event

        ledger_row: Dict[str, Any] = {
            "ts": float(row.get("ts") or time.time()),
            "event": event,
            "outcome": outcome,
            "session_id": str(row.get("session_id") or "").strip(),
            "tool_name": str(row.get("tool_name") or "").strip(),
            "tool": str(row.get("tool_name") or row.get("tool") or "").strip(),
            "trace_id": str(row.get("trace_id") or "").strip(),
            "route": str(row.get("route") or "alpha").strip() or "alpha",
            "emitted": bool(row.get("emitted")) if outcome == "emitted" else False,
            "elapsed_ms": round(max(0.0, float(row.get("elapsed_ms") or 0.0)), 2),
        }
        if gate_reason:
            ledger_row["gate_reason"] = gate_reason
        if isinstance(extra, dict) and extra:
            ledger_row["extra"] = extra

        _append_jsonl_capped(
            ADVISORY_DECISION_LEDGER_FILE,
            ledger_row,
            ADVISORY_DECISION_LEDGER_MAX_LINES,
            ensure_ascii=True,
        )
    except Exception as exc:
        log_debug("advisory_engine_alpha", "decision ledger write failed", exc)


def _dedupe_advice_items(advice_items: List[Any]) -> List[Any]:
    """Drop repeated text variants so alpha emits one coherent signal."""
    out: List[Any] = []
    seen: set[str] = set()
    for item in list(advice_items or []):
        sig = _advice_text_sig(getattr(item, "text", ""))
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
        from .runtime_intent_taxonomy import map_intent

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


def _feedback_prompt_settings() -> Dict[str, Any]:
    enabled = str(os.environ.get("SPARK_ADVICE_FEEDBACK", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    try:
        min_interval_s = max(60, int(float(os.environ.get("SPARK_ADVICE_FEEDBACK_MIN_S", "600") or 600.0)))
    except Exception:
        min_interval_s = 600
    try:
        from .config_authority import resolve_section

        cfg = resolve_section("observe_hook").data
        if isinstance(cfg, dict):
            enabled = _parse_bool(cfg.get("advice_feedback_enabled"), enabled)
            try:
                min_interval_s = max(60, int(float(cfg.get("advice_feedback_min_s", min_interval_s) or min_interval_s)))
            except Exception:
                pass
    except Exception:
        pass
    return {"enabled": bool(enabled), "min_interval_s": int(min_interval_s)}


def _derive_delivery_run_id(
    *,
    tool_name: str,
    trace_id: str,
    advice_ids: List[str],
) -> str:
    ordered_ids = sorted(str(x or "").strip() for x in (advice_ids or []) if str(x or "").strip())
    run_seed = f"{str(tool_name or '').strip()}|{str(trace_id or '').strip()}|{','.join(ordered_ids)}"
    return hashlib.sha1(run_seed.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _record_feedback_request(
    *,
    session_id: str,
    tool_name: str,
    trace_id: str,
    advice_ids: List[str],
    advice_texts: List[str],
    sources: List[str],
    route: str,
    packet_id: str = "",
) -> Dict[str, Any]:
    settings = _feedback_prompt_settings()
    run_id = _derive_delivery_run_id(
        tool_name=tool_name,
        trace_id=trace_id,
        advice_ids=advice_ids,
    )
    result = {
        "enabled": bool(settings.get("enabled", True)),
        "requested": False,
        "min_interval_s": int(settings.get("min_interval_s", 600) or 600),
        "run_id": run_id,
    }
    if (not result["enabled"]) or (not trace_id) or (not advice_ids):
        return result

    from .advice_feedback import record_advice_request

    requested = record_advice_request(
        session_id=str(session_id or "").strip(),
        tool=str(tool_name or "").strip(),
        advice_ids=[str(x) for x in advice_ids[:20] if str(x).strip()],
        advice_texts=[str(x or "")[:240] for x in advice_texts[:20]],
        sources=[str(x or "")[:80] for x in sources[:20]],
        trace_id=str(trace_id or "").strip(),
        run_id=run_id,
        route=str(route or "alpha")[:80],
        packet_id=(str(packet_id or "")[:120] or None),
        min_interval_s=int(result["min_interval_s"]),
    )
    result["requested"] = bool(requested)
    return result


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
        from .emitter import emit_advisory
        from .advisory_gate import evaluate, get_tool_cooldown_s
        from .runtime_session_state import (
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
        bypass_global_dedupe = _should_bypass_global_dedupe(session_id, resolved_trace_id)
        recent_global_by_id: Dict[str, float] = {}
        recent_global_by_text_sig: Dict[str, float] = {}
        if (not bypass_global_dedupe) and float(ALPHA_GLOBAL_DEDUPE_COOLDOWN_S) > 0.0:
            recent_global_by_id, recent_global_by_text_sig = _load_recent_global_dedupe_snapshot(
                cooldown_s=float(ALPHA_GLOBAL_DEDUPE_COOLDOWN_S),
            )

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

        gate_result = evaluate(
            advice_items,
            state,
            tool_name,
            tool_payload,
            recent_global_emissions=(recent_global_by_id if recent_global_by_id else None),
        )
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
        raw_effective_text = str(synth_text or getattr(emitted_items[0], "text", "") or "").strip()
        effective_text, sanitize_mode = _sanitize_emission_text(
            text=raw_effective_text,
            emitted_items=emitted_items,
            tool_name=str(tool_name or ""),
        )
        if not effective_text:
            save_state(state)
            _log_alpha(
                "question_like_blocked",
                session_id=session_id,
                tool_name=tool_name,
                trace_id=resolved_trace_id,
                emitted=False,
                elapsed_ms=(time.time() - start) * 1000.0,
            )
            return None
        synth_text = effective_text
        text_fingerprint = _hash_text(effective_text)
        global_text_sig = _advice_text_sig(effective_text)
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
        if (not bypass_global_dedupe) and global_text_sig and recent_global_by_text_sig:
            age_s = recent_global_by_text_sig.get(global_text_sig)
            if age_s is not None:
                save_state(state)
                _log_alpha(
                    "global_dedupe_suppressed",
                    session_id=session_id,
                    tool_name=tool_name,
                    trace_id=resolved_trace_id,
                    emitted=False,
                    elapsed_ms=(time.time() - start) * 1000.0,
                    extra={
                        "cooldown_s": float(ALPHA_GLOBAL_DEDUPE_COOLDOWN_S),
                        "age_s": round(float(age_s), 1),
                    },
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
        state.last_advisory_tool = str(tool_name or "")
        state.last_advisory_advice_ids = emitted_ids_ordered[:8]
        state.last_advisory_at = time.time()
        state.last_advisory_text_fingerprint = text_fingerprint
        state.last_advisory_context_fingerprint = context_fingerprint
        save_state(state)
        if (not bypass_global_dedupe) and float(ALPHA_GLOBAL_DEDUPE_COOLDOWN_S) > 0.0:
            try:
                _record_global_dedupe_rows(
                    emitted_items=emitted_items,
                    effective_text=effective_text,
                    session_id=session_id,
                    tool_name=tool_name,
                    trace_id=resolved_trace_id,
                )
            except Exception as exc:
                log_debug("advisory_engine_alpha", "global dedupe write failed", exc)

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

        feedback_request_meta: Dict[str, Any] = {
            "enabled": False,
            "requested": False,
            "run_id": "",
            "min_interval_s": 0,
        }
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

        try:
            feedback_request_meta = _record_feedback_request(
                session_id=session_id,
                tool_name=tool_name,
                trace_id=resolved_trace_id,
                advice_ids=emitted_ids_ordered,
                advice_texts=[str(getattr(a, "text", "") or "") for a in emitted_items],
                sources=[str(getattr(a, "source", "") or "") for a in emitted_items],
                route="alpha",
                packet_id=str(state.last_advisory_packet_id or ""),
            )
        except Exception as exc:
            log_debug("advisory_engine_alpha", "record feedback request failed", exc)

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
                "sanitize_mode": str(sanitize_mode),
                "feedback_request_enabled": bool(feedback_request_meta.get("enabled")),
                "feedback_request_requested": bool(feedback_request_meta.get("requested")),
                "feedback_request_run_id": str(feedback_request_meta.get("run_id") or ""),
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
        from .runtime_session_state import load_state, record_tool_call, resolve_recent_trace_id, save_state

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
                record_implicit_feedback(state, tool_name, bool(success), resolved_trace_id)
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
        from .runtime_session_state import load_state, record_user_intent, save_state

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
                    from .prefetch_worker import process_prefetch_queue

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
