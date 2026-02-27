"""Alpha advisory runtime compatibility shim.

Runtime routing has been collapsed to alpha-only. Keep this module as a stable
import surface for scripts/tests that still call orchestrator entrypoints.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .advisory_engine_alpha import on_post_tool, on_pre_tool, on_user_prompt


def get_route_status() -> Dict[str, Any]:
    return {
        "mode": "alpha",
        # Kept for callers expecting this key in status payloads.
        "decision_log": str(Path.home() / ".spark" / "advisory_engine_alpha.jsonl"),
    }


__all__ = ["on_pre_tool", "on_post_tool", "on_user_prompt", "get_route_status"]

