"""Advisory route orchestrator (alpha-only runtime path)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from .jsonl_utils import append_jsonl_capped as _append_jsonl_capped

ROUTE_DECISION_LOG = Path.home() / ".spark" / "advisory_route_decisions.jsonl"
ROUTE_DECISION_MAX_LINES = 3000


def _alpha_on_pre_tool(
    session_id: str,
    tool_name: str,
    tool_input: Optional[dict],
    trace_id: Optional[str],
) -> Optional[str]:
    from .advisory_engine_alpha import on_pre_tool as _fn

    return _fn(session_id=session_id, tool_name=tool_name, tool_input=tool_input, trace_id=trace_id)


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
            "session_id": str(session_id or ""),
            "tool_name": str(tool_name or ""),
            "trace_id": str(trace_id or ""),
            "ok": bool(ok),
            "elapsed_ms": round(max(0.0, float(elapsed_ms or 0.0)), 2),
            "error": str(error or "")[:240],
        },
        ROUTE_DECISION_MAX_LINES,
        ensure_ascii=True,
    )


def on_pre_tool(
    session_id: str,
    tool_name: str,
    tool_input: Optional[dict] = None,
    trace_id: Optional[str] = None,
) -> Optional[str]:
    start = time.time()
    route = "alpha"
    try:
        out = _alpha_on_pre_tool(session_id, tool_name, tool_input, trace_id)
        _log_route_decision(
            phase="pre_tool",
            route=route,
            session_id=session_id,
            tool_name=tool_name,
            trace_id=trace_id,
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
    route = "alpha"
    try:
        _alpha_on_post_tool(session_id, tool_name, success, tool_input, trace_id, error)
        _log_route_decision(
            phase="post_tool",
            route=route,
            session_id=session_id,
            tool_name=tool_name,
            trace_id=trace_id,
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
    route = "alpha"
    try:
        _alpha_on_user_prompt(session_id, prompt_text, trace_id)
        _log_route_decision(
            phase="user_prompt",
            route=route,
            session_id=session_id,
            tool_name="*",
            trace_id=trace_id,
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
            ok=False,
            elapsed_ms=(time.time() - start) * 1000.0,
            error=str(exc),
        )
        raise


def get_route_status() -> Dict[str, Any]:
    return {
        "mode": "alpha",
        "decision_log": str(ROUTE_DECISION_LOG),
    }
