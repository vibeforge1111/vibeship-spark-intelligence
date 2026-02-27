"""Legacy advisory engine compatibility module.

Runtime ownership has moved to `lib.advisory_engine_alpha`.
This module keeps compatibility helpers/config APIs and forwards runtime entrypoints.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .advisory_implicit_feedback import record_implicit_feedback as _record_implicit_feedback
from .diagnostics import log_debug
from .error_taxonomy import build_error_fields

ENGINE_ENABLED = os.getenv("SPARK_ADVISORY_ENGINE", "1") != "0"
ENGINE_LOG = Path.home() / ".spark" / "advisory_engine.jsonl"
ENGINE_LOG_MAX = 500
MAX_ENGINE_MS = float(os.getenv("SPARK_ADVISORY_MAX_MS", "4000"))
INCLUDE_MIND_IN_MEMORY = os.getenv("SPARK_ADVISORY_INCLUDE_MIND", "0") == "1"
ACTIONABILITY_ENFORCE = os.getenv("SPARK_ADVISORY_REQUIRE_ACTION", "1") != "0"
DELIVERY_STALE_SECONDS = float(os.getenv("SPARK_ADVISORY_STALE_S", "900"))
ADVISORY_TEXT_REPEAT_COOLDOWN_S = float(
    os.getenv("SPARK_ADVISORY_TEXT_REPEAT_COOLDOWN_S", "600")
)
try:
    GLOBAL_DEDUPE_COOLDOWN_S = float(
        os.getenv("SPARK_ADVISORY_GLOBAL_DEDUPE_COOLDOWN_S", "600")
    )
except Exception:
    GLOBAL_DEDUPE_COOLDOWN_S = 600.0
GLOBAL_DEDUPE_SCOPE = str(
    os.getenv("SPARK_ADVISORY_GLOBAL_DEDUPE_SCOPE", "global") or "global"
).strip().lower()

REJECTION_TELEMETRY_FILE = Path.home() / ".spark" / "advisory_rejection_telemetry.json"
_rejection_counts: Dict[str, int] = {}
_rejection_flush_interval = 50
_rejection_flush_counter = 0


def _flush_rejection_telemetry() -> None:
    existing: Dict[str, int] = {}
    if REJECTION_TELEMETRY_FILE.exists():
        try:
            loaded = json.loads(REJECTION_TELEMETRY_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            existing = {}
    for key, value in _rejection_counts.items():
        existing[key] = int(existing.get(key, 0)) + int(value)
    existing["_last_flush"] = time.time()
    REJECTION_TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REJECTION_TELEMETRY_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    _rejection_counts.clear()


def _record_rejection(reason: str) -> None:
    global _rejection_flush_counter
    key = str(reason or "unknown").strip() or "unknown"
    _rejection_counts[key] = int(_rejection_counts.get(key, 0)) + 1
    _rejection_flush_counter += 1
    should_flush = (
        _rejection_flush_counter >= _rejection_flush_interval
        or key == "global_dedupe_suppressed"
        or not REJECTION_TELEMETRY_FILE.exists()
    )
    if should_flush:
        _rejection_flush_counter = 0
        try:
            _flush_rejection_telemetry()
        except Exception as exc:
            log_debug("advisory_engine", f"rejection telemetry flush failed: {exc}", None)


def _load_engine_config(path: Optional[Path] = None) -> Dict[str, Any]:
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

    from .config_authority import env_bool, env_float, env_int, env_str, resolve_section

    cfg = resolve_section(
        "advisory_engine",
        runtime_path=tuneables,
        env_overrides={
            "enabled": env_bool("SPARK_ADVISORY_ENGINE"),
            "max_ms": env_float("SPARK_ADVISORY_MAX_MS"),
            "include_mind": env_bool("SPARK_ADVISORY_INCLUDE_MIND"),
            "actionability_enforce": env_bool("SPARK_ADVISORY_REQUIRE_ACTION"),
            "delivery_stale_s": env_float("SPARK_ADVISORY_STALE_S"),
            "advisory_text_repeat_cooldown_s": env_float("SPARK_ADVISORY_TEXT_REPEAT_COOLDOWN_S"),
            "global_dedupe_cooldown_s": env_float("SPARK_ADVISORY_GLOBAL_DEDUPE_COOLDOWN_S"),
            "global_dedupe_scope": env_str("SPARK_ADVISORY_GLOBAL_DEDUPE_SCOPE", lower=True),
            "prefetch_queue_enabled": env_bool("SPARK_ADVISORY_PREFETCH_QUEUE"),
            "prefetch_inline_enabled": env_bool("SPARK_ADVISORY_PREFETCH_INLINE"),
            "prefetch_inline_max_jobs": env_int("SPARK_ADVISORY_PREFETCH_INLINE_MAX_JOBS"),
        },
    ).data
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
    global ENGINE_ENABLED
    global MAX_ENGINE_MS
    global INCLUDE_MIND_IN_MEMORY
    global ACTIONABILITY_ENFORCE
    global DELIVERY_STALE_SECONDS
    global ADVISORY_TEXT_REPEAT_COOLDOWN_S
    global GLOBAL_DEDUPE_COOLDOWN_S
    global GLOBAL_DEDUPE_SCOPE

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
    if "actionability_enforce" in cfg:
        ACTIONABILITY_ENFORCE = _parse_bool(cfg.get("actionability_enforce"), ACTIONABILITY_ENFORCE)
        applied.append("actionability_enforce")
    if "delivery_stale_s" in cfg:
        try:
            DELIVERY_STALE_SECONDS = max(30.0, min(86400.0, float(cfg.get("delivery_stale_s"))))
            applied.append("delivery_stale_s")
        except Exception:
            warnings.append("invalid_delivery_stale_s")
    if "advisory_text_repeat_cooldown_s" in cfg:
        try:
            ADVISORY_TEXT_REPEAT_COOLDOWN_S = max(
                0.0,
                min(86400.0, float(cfg.get("advisory_text_repeat_cooldown_s"))),
            )
            applied.append("advisory_text_repeat_cooldown_s")
        except Exception:
            warnings.append("invalid_advisory_text_repeat_cooldown_s")
    if "global_dedupe_cooldown_s" in cfg:
        try:
            GLOBAL_DEDUPE_COOLDOWN_S = max(
                0.0,
                min(86400.0, float(cfg.get("global_dedupe_cooldown_s"))),
            )
            applied.append("global_dedupe_cooldown_s")
        except Exception:
            warnings.append("invalid_global_dedupe_cooldown_s")
    if "global_dedupe_scope" in cfg:
        scope = str(cfg.get("global_dedupe_scope") or "").strip().lower()
        if scope in {"global", "tree", "contextual"}:
            GLOBAL_DEDUPE_SCOPE = scope
            applied.append("global_dedupe_scope")
        else:
            warnings.append("invalid_global_dedupe_scope")

    return {"applied": applied, "warnings": warnings}


def get_engine_config() -> Dict[str, Any]:
    return {
        "enabled": bool(ENGINE_ENABLED),
        "max_ms": float(MAX_ENGINE_MS),
        "include_mind": bool(INCLUDE_MIND_IN_MEMORY),
        "actionability_enforce": bool(ACTIONABILITY_ENFORCE),
        "delivery_stale_s": float(DELIVERY_STALE_SECONDS),
        "advisory_text_repeat_cooldown_s": float(ADVISORY_TEXT_REPEAT_COOLDOWN_S),
        "global_dedupe_cooldown_s": float(GLOBAL_DEDUPE_COOLDOWN_S),
        "global_dedupe_scope": str(GLOBAL_DEDUPE_SCOPE),
    }


_BOOT_ENGINE_CFG = _load_engine_config()
if _BOOT_ENGINE_CFG:
    apply_engine_config(_BOOT_ENGINE_CFG)

try:
    from .tuneables_reload import register_reload as _engine_register

    _engine_register("advisory_engine", apply_engine_config, label="advisory_engine.apply_config")
except Exception as exc:
    log_debug("advisory_engine", f"hot-reload registration failed: {exc}", None)


def _proof_refs_for_advice(item: Any, trace_id: Optional[str]) -> Dict[str, Any]:
    proof = {
        "advice_id": str(getattr(item, "advice_id", "") or ""),
        "insight_key": str(getattr(item, "insight_key", "") or ""),
        "source": str(getattr(item, "source", "") or "unknown"),
    }
    tid = str(trace_id or "").strip()
    if tid:
        proof["trace_id"] = tid
    return proof


def _evidence_hash_for_row(*, advice_text: str, proof_refs: Dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(advice_text or "").strip().lower(),
            str(proof_refs.get("advice_id") or "").strip(),
            str(proof_refs.get("insight_key") or "").strip(),
            str(proof_refs.get("source") or "").strip(),
            str(proof_refs.get("trace_id") or "").strip(),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:20]


def _advice_to_rows_with_proof(
    advice_items: List[Any],
    trace_id: Optional[str],
    max_rows: int = 6,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in list(advice_items or [])[: max(0, int(max_rows))]:
        text = str(getattr(item, "text", "") or "").strip()
        proof_refs = _proof_refs_for_advice(item, trace_id)
        out.append(
            {
                "advice_id": str(getattr(item, "advice_id", "") or ""),
                "insight_key": str(getattr(item, "insight_key", "") or ""),
                "text": text,
                "confidence": float(getattr(item, "confidence", 0.0) or 0.0),
                "source": str(getattr(item, "source", "") or "unknown"),
                "context_match": float(getattr(item, "context_match", 0.0) or 0.0),
                "reason": str(getattr(item, "reason", "") or ""),
                "proof_refs": proof_refs,
                "evidence_hash": _evidence_hash_for_row(
                    advice_text=text,
                    proof_refs=proof_refs,
                ),
            }
        )
    return out


def _advice_to_rows(advice_items: List[Any], max_rows: int = 6) -> List[Dict[str, Any]]:
    return _advice_to_rows_with_proof(advice_items, trace_id=None, max_rows=max_rows)


def _advice_source_counts(advice_items: Optional[List[Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in list(advice_items or []):
        source = str(getattr(item, "source", "") or "unknown").strip() or "unknown"
        counts[source] = int(counts.get(source, 0)) + 1
    return counts


def _session_lineage(session_id: str) -> Dict[str, Any]:
    raw = str(session_id or "").strip()
    parts = [p for p in raw.split(":") if p]

    base = raw
    if len(parts) >= 2 and parts[0] == "agent":
        base = f"{parts[0]}:{parts[1]}"

    is_subagent = "subagent" in parts
    if is_subagent:
        kind = "subagent"
    elif len(parts) >= 2 and parts[0] == "agent":
        kind = "agent"
    else:
        kind = "session"

    return {
        "session_id": raw,
        "session_tree_key": base,
        "session_kind": kind,
        "is_subagent": bool(is_subagent),
        "depth_hint": max(1, len(parts) - 2) if len(parts) > 2 else 1,
    }


def _dedupe_scope_key(
    session_id: str,
    intent_family: Optional[str] = None,
    task_phase: Optional[str] = None,
) -> str:
    lineage = _session_lineage(session_id)
    tree = str(lineage.get("session_tree_key") or "")
    scope = str(GLOBAL_DEDUPE_SCOPE or "global").strip().lower()
    if scope == "tree":
        return tree
    if scope == "contextual":
        phase = str(task_phase or "implementation").strip().lower() or "implementation"
        intent = str(intent_family or "emergent_other").strip().lower() or "emergent_other"
        return f"{tree}:{phase}:{intent}"
    return "global"


def _diagnostics_envelope(
    *,
    session_id: str,
    trace_id: Optional[str] = None,
    session_context_key: Optional[str] = None,
    scope: str = "session",
    memory_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    bundle = memory_bundle if isinstance(memory_bundle, dict) else {}
    sources = bundle.get("sources") if isinstance(bundle.get("sources"), dict) else {}

    source_counts: Dict[str, int] = {}
    for name, payload in sources.items():
        if isinstance(payload, dict):
            source_counts[str(name)] = int(payload.get("count", 0) or 0)

    return {
        "session_id": str(session_id or ""),
        "trace_id": str(trace_id or "").strip(),
        "session_context_key": str(session_context_key or ""),
        "scope": str(scope or "session"),
        "memory_absent_declared": bool(bundle.get("memory_absent_declared", False)),
        "source_counts": source_counts,
        "missing_sources": [str(x) for x in list(bundle.get("missing_sources") or [])],
    }


def _default_action_command(tool_name: str, task_plane: str) -> str:
    if str(tool_name or "").strip().lower() in {"edit", "write"}:
        return "python -m pytest -q"
    if str(task_plane or "").strip().lower() == "testing_validation":
        return "python -m pytest -q"
    return "python -m pytest -q"


def _has_actionable_command(text: str) -> bool:
    sample = str(text or "")
    return "`" in sample and any(tok in sample for tok in ("pytest", "python -m", "git ", "bash "))


def _ensure_actionability(text: str, tool_name: str, task_plane: str) -> Dict[str, Any]:
    out = str(text or "").strip()
    if not ACTIONABILITY_ENFORCE:
        return {"text": out, "added": False, "command": ""}
    if _has_actionable_command(out):
        return {"text": out, "added": False, "command": ""}
    command = _default_action_command(tool_name, task_plane)
    if out:
        out = f"{out} Next check: `{command}`."
    else:
        out = f"Next check: `{command}`."
    return {"text": out, "added": True, "command": command}


def _derive_delivery_badge(
    recent_events: List[Dict[str, Any]],
    *,
    now_ts: Optional[float] = None,
    stale_after_s: Optional[float] = None,
) -> Dict[str, Any]:
    events = list(recent_events or [])
    now = float(now_ts if now_ts is not None else time.time())
    stale_s = float(stale_after_s if stale_after_s is not None else DELIVERY_STALE_SECONDS)

    last_emit = 0.0
    last_mode = "none"
    for row in events:
        event = str(row.get("event") or "").strip().lower()
        if event != "emitted":
            continue
        try:
            ts = float(row.get("ts") or 0.0)
        except Exception:
            ts = 0.0
        if ts >= last_emit:
            last_emit = ts
            last_mode = str(row.get("delivery_mode") or "live").strip().lower() or "live"

    if last_emit <= 0:
        return {"state": "idle", "age_s": None, "delivery_mode": "none"}

    age_s = max(0.0, now - last_emit)
    state = "live" if age_s <= stale_s else "stale"
    return {
        "state": state,
        "age_s": round(age_s, 2),
        "delivery_mode": last_mode,
        "stale_after_s": float(stale_s),
        "last_emit_ts": float(last_emit),
    }


def on_pre_tool(
    session_id: str,
    tool_name: str,
    tool_input: Optional[dict] = None,
    trace_id: Optional[str] = None,
) -> Optional[str]:
    if not ENGINE_ENABLED:
        return None

    start_ms = time.time() * 1000.0
    try:
        from .advisory_engine_alpha import on_pre_tool as _alpha_on_pre_tool

        return _alpha_on_pre_tool(
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            trace_id=trace_id,
        )
    except Exception as exc:
        log_debug("advisory_engine", "compat shim pre_tool forward failed", exc)
        _log_engine_event(
            "compat_forward_error",
            tool_name,
            0,
            0,
            start_ms,
            extra=build_error_fields(str(exc), "AE_COMPAT_FORWARD_PRE_TOOL"),
        )
        _record_rejection("compat_forward_error_pre_tool")
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
    try:
        from .advisory_engine_alpha import on_post_tool as _alpha_on_post_tool

        _alpha_on_post_tool(
            session_id=session_id,
            tool_name=tool_name,
            success=bool(success),
            tool_input=tool_input,
            trace_id=trace_id,
            error=error,
        )
    except Exception as exc:
        log_debug("advisory_engine", "compat shim post_tool forward failed", exc)
        _log_engine_event(
            "compat_forward_error",
            tool_name,
            0,
            0,
            start_ms,
            extra=build_error_fields(str(exc), "AE_COMPAT_FORWARD_POST_TOOL"),
        )
        _record_rejection("compat_forward_error_post_tool")


def on_user_prompt(
    session_id: str,
    prompt_text: str,
    trace_id: Optional[str] = None,
) -> None:
    if not ENGINE_ENABLED:
        return

    start_ms = time.time() * 1000.0
    try:
        from .advisory_engine_alpha import on_user_prompt as _alpha_on_user_prompt

        _alpha_on_user_prompt(
            session_id=session_id,
            prompt_text=prompt_text,
            trace_id=trace_id,
        )
    except Exception as exc:
        log_debug("advisory_engine", "compat shim user_prompt forward failed", exc)
        _log_engine_event(
            "compat_forward_error",
            "*",
            0,
            0,
            start_ms,
            extra=build_error_fields(str(exc), "AE_COMPAT_FORWARD_USER_PROMPT"),
        )
        _record_rejection("compat_forward_error_user_prompt")


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
            "retrieved": int(advice_count or 0),
            "emitted": int(emitted_count or 0),
            "elapsed_ms": round(elapsed_ms, 1),
        }
        if isinstance(extra, dict):
            entry.update(extra)
        with ENGINE_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        _rotate_engine_log()
    except Exception as exc:
        log_debug("advisory_engine", f"engine log write failed: {exc}", None)


def _rotate_engine_log() -> None:
    try:
        if not ENGINE_LOG.exists():
            return
        lines = ENGINE_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > ENGINE_LOG_MAX:
            keep = lines[-ENGINE_LOG_MAX:]
            ENGINE_LOG.write_text("\n".join(keep) + "\n", encoding="utf-8")
    except Exception as exc:
        log_debug("advisory_engine", f"engine log rotation failed: {exc}", None)


def get_engine_status() -> Dict[str, Any]:
    status = {
        "enabled": bool(ENGINE_ENABLED),
        "max_ms": float(MAX_ENGINE_MS),
        "config": get_engine_config(),
        "compat_mode": "legacy_shim",
    }

    try:
        from .advisory_engine_alpha import get_alpha_status

        status["alpha"] = get_alpha_status()
        status["active_runtime"] = "alpha"
    except Exception:
        status["alpha"] = {"error": "unavailable"}
        status["active_runtime"] = "legacy_shim"

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

    try:
        rows: List[Dict[str, Any]] = []
        if ENGINE_LOG.exists():
            lines = ENGINE_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
            status["total_events"] = len(lines)
            for line in lines[-100:]:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        rows.append(row)
                except Exception:
                    continue
        else:
            status["total_events"] = 0

        status["recent_events"] = rows[-10:]
        emitted = sum(1 for row in rows if str(row.get("event") or "").strip().lower() == "emitted")
        status["emission_rate"] = round(emitted / max(len(rows), 1), 3) if rows else 0.0
        status["delivery_badge"] = _derive_delivery_badge(rows)
    except Exception:
        status["recent_events"] = []
        status["emission_rate"] = 0.0
        status["delivery_badge"] = _derive_delivery_badge([])

    return status
