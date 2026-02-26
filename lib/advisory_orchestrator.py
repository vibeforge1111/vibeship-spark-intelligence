"""Advisory route orchestrator (engine vs alpha, with canary support)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .diagnostics import log_debug

ROUTE_DECISION_LOG = Path.home() / ".spark" / "advisory_route_decisions.jsonl"
ROUTE_DECISION_MAX_LINES = 3000


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


def _stable_bucket(seed: str) -> int:
    digest = hashlib.sha1(str(seed or "").encode("utf-8", errors="ignore")).hexdigest()
    return int(digest[:8], 16) % 100


def _route_mode() -> str:
    mode = str(os.getenv("SPARK_ADVISORY_ROUTE", "engine") or "engine").strip().lower()
    if mode in {"legacy"}:
        return "engine"
    if mode not in {"engine", "alpha", "canary"}:
        return "engine"
    return mode


def _canary_percent() -> int:
    try:
        raw = int(os.getenv("SPARK_ADVISORY_ALPHA_CANARY_PERCENT", "0") or 0)
    except Exception:
        raw = 0
    return max(0, min(100, raw))


def route_for_session(session_id: str, tool_name: str, trace_id: Optional[str] = None) -> str:
    mode = _route_mode()
    if mode != "canary":
        return mode
    percent = _canary_percent()
    if percent <= 0:
        return "engine"
    if percent >= 100:
        return "alpha"
    seed = f"{session_id}|{tool_name}|{str(trace_id or '').strip()}"
    return "alpha" if _stable_bucket(seed) < percent else "engine"


def _engine_on_pre_tool(
    session_id: str,
    tool_name: str,
    tool_input: Optional[dict],
    trace_id: Optional[str],
) -> Optional[str]:
    from .advisory_engine import on_pre_tool as _fn

    return _fn(session_id=session_id, tool_name=tool_name, tool_input=tool_input, trace_id=trace_id)


def _alpha_on_pre_tool(
    session_id: str,
    tool_name: str,
    tool_input: Optional[dict],
    trace_id: Optional[str],
) -> Optional[str]:
    from .advisory_engine_alpha import on_pre_tool as _fn

    return _fn(session_id=session_id, tool_name=tool_name, tool_input=tool_input, trace_id=trace_id)


def _engine_on_post_tool(
    session_id: str,
    tool_name: str,
    success: bool,
    tool_input: Optional[dict],
    trace_id: Optional[str],
    error: Optional[str],
) -> None:
    from .advisory_engine import on_post_tool as _fn

    _fn(
        session_id=session_id,
        tool_name=tool_name,
        success=bool(success),
        tool_input=tool_input,
        trace_id=trace_id,
        error=error,
    )


def _alpha_on_post_tool(
    session_id: str,
    tool_name: str,
    success: bool,
    tool_input: Optional[dict],
    trace_id: Optional[str],
    error: Optional[str],
) -> None:
    from .advisory_engine_alpha import on_post_tool as _fn

    _fn(
        session_id=session_id,
        tool_name=tool_name,
        success=bool(success),
        tool_input=tool_input,
        trace_id=trace_id,
        error=error,
    )


def _engine_on_user_prompt(session_id: str, prompt_text: str, trace_id: Optional[str]) -> None:
    from .advisory_engine import on_user_prompt as _fn

    _fn(session_id=session_id, prompt_text=prompt_text, trace_id=trace_id)


def _alpha_on_user_prompt(session_id: str, prompt_text: str, trace_id: Optional[str]) -> None:
    from .advisory_engine_alpha import on_user_prompt as _fn

    _fn(session_id=session_id, prompt_text=prompt_text, trace_id=trace_id)


def _log_route_decision(
    *,
    phase: str,
    route: str,
    session_id: str,
    tool_name: str,
    trace_id: Optional[str],
    fallback_used: bool,
    ok: bool,
    elapsed_ms: float,
    error: str = "",
) -> None:
    _append_jsonl_capped(
        ROUTE_DECISION_LOG,
        {
            "ts": time.time(),
            "phase": str(phase or ""),
            "route": str(route or ""),
            "mode": _route_mode(),
            "canary_percent": _canary_percent(),
            "session_id": str(session_id or ""),
            "tool_name": str(tool_name or ""),
            "trace_id": str(trace_id or ""),
            "fallback_used": bool(fallback_used),
            "ok": bool(ok),
            "elapsed_ms": round(max(0.0, float(elapsed_ms or 0.0)), 2),
            "error": str(error or "")[:240],
        },
        ROUTE_DECISION_MAX_LINES,
    )


def on_pre_tool(
    session_id: str,
    tool_name: str,
    tool_input: Optional[dict] = None,
    trace_id: Optional[str] = None,
) -> Optional[str]:
    start = time.time()
    route = route_for_session(session_id, tool_name, trace_id)
    fallback_used = False
    try:
        if route == "alpha":
            try:
                out = _alpha_on_pre_tool(session_id, tool_name, tool_input, trace_id)
                _log_route_decision(
                    phase="pre_tool",
                    route=route,
                    session_id=session_id,
                    tool_name=tool_name,
                    trace_id=trace_id,
                    fallback_used=False,
                    ok=True,
                    elapsed_ms=(time.time() - start) * 1000.0,
                )
                return out
            except Exception as exc:
                fallback_used = True
                log_debug("advisory_orchestrator", "alpha pre-tool failed, falling back to engine", exc)
                out = _engine_on_pre_tool(session_id, tool_name, tool_input, trace_id)
                _log_route_decision(
                    phase="pre_tool",
                    route=route,
                    session_id=session_id,
                    tool_name=tool_name,
                    trace_id=trace_id,
                    fallback_used=True,
                    ok=True,
                    elapsed_ms=(time.time() - start) * 1000.0,
                    error=str(exc),
                )
                return out

        out = _engine_on_pre_tool(session_id, tool_name, tool_input, trace_id)
        _log_route_decision(
            phase="pre_tool",
            route=route,
            session_id=session_id,
            tool_name=tool_name,
            trace_id=trace_id,
            fallback_used=fallback_used,
            ok=True,
            elapsed_ms=(time.time() - start) * 1000.0,
        )
        return out
    except Exception as exc:
        _log_route_decision(
            phase="pre_tool",
            route=route,
            session_id=session_id,
            tool_name=tool_name,
            trace_id=trace_id,
            fallback_used=fallback_used,
            ok=False,
            elapsed_ms=(time.time() - start) * 1000.0,
            error=str(exc),
        )
        raise


def on_post_tool(
    session_id: str,
    tool_name: str,
    success: bool,
    tool_input: Optional[dict] = None,
    trace_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    start = time.time()
    route = route_for_session(session_id, tool_name, trace_id)
    fallback_used = False
    try:
        if route == "alpha":
            try:
                _alpha_on_post_tool(session_id, tool_name, success, tool_input, trace_id, error)
                _log_route_decision(
                    phase="post_tool",
                    route=route,
                    session_id=session_id,
                    tool_name=tool_name,
                    trace_id=trace_id,
                    fallback_used=False,
                    ok=True,
                    elapsed_ms=(time.time() - start) * 1000.0,
                )
                return
            except Exception as exc:
                fallback_used = True
                log_debug("advisory_orchestrator", "alpha post-tool failed, falling back to engine", exc)
                _engine_on_post_tool(session_id, tool_name, success, tool_input, trace_id, error)
                _log_route_decision(
                    phase="post_tool",
                    route=route,
                    session_id=session_id,
                    tool_name=tool_name,
                    trace_id=trace_id,
                    fallback_used=True,
                    ok=True,
                    elapsed_ms=(time.time() - start) * 1000.0,
                    error=str(exc),
                )
                return
        _engine_on_post_tool(session_id, tool_name, success, tool_input, trace_id, error)
        _log_route_decision(
            phase="post_tool",
            route=route,
            session_id=session_id,
            tool_name=tool_name,
            trace_id=trace_id,
            fallback_used=fallback_used,
            ok=True,
            elapsed_ms=(time.time() - start) * 1000.0,
        )
    except Exception as exc:
        _log_route_decision(
            phase="post_tool",
            route=route,
            session_id=session_id,
            tool_name=tool_name,
            trace_id=trace_id,
            fallback_used=fallback_used,
            ok=False,
            elapsed_ms=(time.time() - start) * 1000.0,
            error=str(exc),
        )
        raise


def on_user_prompt(
    session_id: str,
    prompt_text: str,
    trace_id: Optional[str] = None,
) -> None:
    start = time.time()
    route = route_for_session(session_id, "*", trace_id)
    fallback_used = False
    try:
        if route == "alpha":
            try:
                _alpha_on_user_prompt(session_id, prompt_text, trace_id)
                _log_route_decision(
                    phase="user_prompt",
                    route=route,
                    session_id=session_id,
                    tool_name="*",
                    trace_id=trace_id,
                    fallback_used=False,
                    ok=True,
                    elapsed_ms=(time.time() - start) * 1000.0,
                )
                return
            except Exception as exc:
                fallback_used = True
                log_debug("advisory_orchestrator", "alpha user-prompt failed, falling back to engine", exc)
                _engine_on_user_prompt(session_id, prompt_text, trace_id)
                _log_route_decision(
                    phase="user_prompt",
                    route=route,
                    session_id=session_id,
                    tool_name="*",
                    trace_id=trace_id,
                    fallback_used=True,
                    ok=True,
                    elapsed_ms=(time.time() - start) * 1000.0,
                    error=str(exc),
                )
                return
        _engine_on_user_prompt(session_id, prompt_text, trace_id)
        _log_route_decision(
            phase="user_prompt",
            route=route,
            session_id=session_id,
            tool_name="*",
            trace_id=trace_id,
            fallback_used=fallback_used,
            ok=True,
            elapsed_ms=(time.time() - start) * 1000.0,
        )
    except Exception as exc:
        _log_route_decision(
            phase="user_prompt",
            route=route,
            session_id=session_id,
            tool_name="*",
            trace_id=trace_id,
            fallback_used=fallback_used,
            ok=False,
            elapsed_ms=(time.time() - start) * 1000.0,
            error=str(exc),
        )
        raise


def get_route_status() -> Dict[str, Any]:
    return {
        "mode": _route_mode(),
        "canary_percent": _canary_percent(),
        "decision_log": str(ROUTE_DECISION_LOG),
    }

