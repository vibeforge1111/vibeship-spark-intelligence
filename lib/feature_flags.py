"""Shared feature flags resolved through config-authority.

Cross-module boolean flags that multiple consumers read.  Resolving
them in one place eliminates duplicate os.environ.get() calls
scattered across advisor.py, bridge_cycle.py, cognitive_learner.py,
and chips/runtime.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Resolved values — importable by consumers.
# ---------------------------------------------------------------------------
PREMIUM_TOOLS: bool = False
CHIPS_ENABLED: bool = False
ADVISORY_DISABLE_CHIPS: bool = False


def _load_feature_flags() -> None:
    global PREMIUM_TOOLS, CHIPS_ENABLED, ADVISORY_DISABLE_CHIPS
    try:
        from .config_authority import resolve_section, env_bool

        cfg = resolve_section(
            "feature_flags",
            env_overrides={
                "premium_tools": env_bool("SPARK_PREMIUM_TOOLS"),
                "chips_enabled": env_bool("SPARK_CHIPS_ENABLED"),
                "advisory_disable_chips": env_bool("SPARK_ADVISORY_DISABLE_CHIPS"),
            },
        ).data
        PREMIUM_TOOLS = bool(cfg.get("premium_tools", False))
        CHIPS_ENABLED = bool(cfg.get("chips_enabled", False))
        ADVISORY_DISABLE_CHIPS = bool(cfg.get("advisory_disable_chips", False))
    except Exception:
        pass


_load_feature_flags()

try:
    from .tuneables_reload import register_reload as _ff_register

    _ff_register(
        "feature_flags",
        lambda _cfg: _load_feature_flags(),
        label="feature_flags.reload",
    )
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Convenience helpers (mirror the old per-module logic).
# ---------------------------------------------------------------------------

def is_premium_tools_enabled() -> bool:
    return PREMIUM_TOOLS


def chips_active() -> bool:
    """True when chip insights should be processed/emitted."""
    return CHIPS_ENABLED and PREMIUM_TOOLS and not ADVISORY_DISABLE_CHIPS
