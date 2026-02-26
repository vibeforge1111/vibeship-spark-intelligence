"""
Unified entry point for storing cognitive insights.

ALL paths that write to the cognitive store MUST go through
validate_and_store_insight(). This ensures every insight is:
1. Roasted by Meta-Ralph (quality gate)
2. Checked by cognitive noise filter
3. Quarantined on exception (fail-open)

Bypass paths closed (Batch 2 + review fixes):
- memory_capture.py commit_learning()
- feedback_loop.py _process_decision/outcome/preference()
- chip_merger.py distillation
- cognitive_signals.py extract_cognitive_signals()
- pipeline.py store_deep_learnings() floor
- hypothesis_tracker.py _promote_to_belief()
- pattern_detection/aggregator.py promote_pattern()
- curiosity_engine.py (deprecated)

Intentional direct add_insight() bypasses (documented):
- pipeline.py:672 — already runs Meta-Ralph before write (would double-roast)
- depth_trainer.py — batch mode training system (66x speedup, separate domain)

Rollback: Set flow.validate_and_store_enabled=false in tuneables.json
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, TypedDict, Union

from .diagnostics import log_debug

# Tuneable rollback switch (reset to None on hot-reload via reset_enabled_cache)
_ENABLED: Optional[bool] = None


def reset_enabled_cache() -> None:
    """Clear the cached enabled flag so next call re-reads tuneables."""
    global _ENABLED
    _ENABLED = None


TELEMETRY_FILE = Path.home() / ".spark" / "validate_and_store_telemetry.json"

# Telemetry counters (flushed periodically)
_counters: Dict[str, int] = {}
_flush_counter = 0
_FLUSH_INTERVAL = 20


class StoreDetails(TypedDict):
    stored: bool
    insight_key: str
    stored_text: str


StoreResult = Union[bool, StoreDetails]


def _is_enabled() -> bool:
    """Check if unified validation is enabled (cached)."""
    global _ENABLED
    if _ENABLED is not None:
        return _ENABLED
    try:
        from .config_authority import resolve_section, env_bool
        cfg = resolve_section(
            "flow",
            env_overrides={
                "validate_and_store_enabled": env_bool("SPARK_VALIDATE_AND_STORE"),
            },
        ).data
        _ENABLED = bool(cfg.get("validate_and_store_enabled", True))
    except Exception:
        # Fallback: check env var, then tuneables_reload
        env = os.getenv("SPARK_VALIDATE_AND_STORE", "")
        if env == "0":
            _ENABLED = False
        elif env == "1":
            _ENABLED = True
        else:
            try:
                from .tuneables_reload import get_section
                flow_cfg = get_section("flow")
                _ENABLED = bool(flow_cfg.get("validate_and_store_enabled", True))
            except Exception:
                _ENABLED = True
    return _ENABLED


def _record(counter: str) -> None:
    """Increment a telemetry counter, flush periodically."""
    global _flush_counter
    _counters[counter] = _counters.get(counter, 0) + 1
    _flush_counter += 1
    if _flush_counter >= _FLUSH_INTERVAL:
        _flush_counter = 0
        try:
            existing: Dict[str, Any] = {}
            if TELEMETRY_FILE.exists():
                existing = json.loads(TELEMETRY_FILE.read_text(encoding="utf-8"))
            for k, v in _counters.items():
                existing[k] = existing.get(k, 0) + v
            existing["_last_flush"] = time.time()
            TELEMETRY_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")
            _counters.clear()
        except Exception:
            pass


def validate_and_store_insight(
    text: str,
    category,  # CognitiveCategory
    context: str = "",
    confidence: float = 0.7,
    source: str = "unknown",
    *,
    record_exposure: bool = True,
    return_details: bool = False,
    roast_context: Optional[Dict[str, Any]] = None,
) -> StoreResult:
    """
    Validate an insight through Meta-Ralph and store in cognitive learner.

    This is the ONLY sanctioned entry point for cognitive insight writes.

    Pipeline:
        1. Meta-Ralph roast (quality gate)
        2. Cognitive add_insight (has built-in noise filter)
        3. On Meta-Ralph exception → quarantine (fail-open)

    Returns:
        Default: bool stored flag.
        If return_details=True: dict with {stored, insight_key, stored_text}.
        On Meta-Ralph exception: quarantines for diagnostics AND stores (fail-open).
    """
    def _result(stored: bool, *, insight_key: str = "", stored_text: str = "") -> StoreResult:
        if not return_details:
            return bool(stored)
        return {
            "stored": bool(stored),
            "insight_key": str(insight_key or ""),
            "stored_text": str(stored_text or ""),
        }

    def _derive_key(cog: Any, final_text: str) -> str:
        try:
            key_part = str(final_text or "")[:40].replace(" ", "_").lower()
            return str(cog._generate_key(category, key_part) or "")
        except Exception:
            return ""

    if not text or not str(text).strip():
        return _result(False)

    # Rollback switch: bypass validation, direct write
    if not _is_enabled():
        try:
            from .cognitive_learner import get_cognitive_learner
            cog = get_cognitive_learner()
            result = cog.add_insight(
                category=category,
                insight=text,
                context=context,
                confidence=confidence,
                source=source,
                record_exposure=record_exposure,
            )
            if result is None:
                return _result(False, stored_text=text)
            final_text = str(getattr(result, "insight", text) or text)
            return _result(True, insight_key=_derive_key(cog, final_text), stored_text=final_text)
        except Exception as e:
            log_debug("validate_and_store", "bypass_write_failed", e)
            return _result(False)

    _record("total_attempted")

    # Step 1: Meta-Ralph quality gate
    try:
        from .meta_ralph import get_meta_ralph, RoastVerdict
        ralph = get_meta_ralph()
        roast_result = ralph.roast(text, source=source, context=roast_context)
        verdict = roast_result.verdict

        if verdict == RoastVerdict.PRIMITIVE:
            _record("roast_primitive")
            return False

        if verdict == RoastVerdict.DUPLICATE:
            _record("roast_duplicate")
            return False

        if verdict == RoastVerdict.NEEDS_WORK:
            # Use refined version if available, otherwise try original
            text = roast_result.refined_version or text
            _record("roast_needs_work")

        if verdict == RoastVerdict.QUALITY:
            # Use refined version if Meta-Ralph improved it
            text = roast_result.refined_version or text
            _record("roast_quality")

    except Exception as e:
        # Fail-open: quarantine the insight for diagnostics, then continue to storage
        _record("quarantined")
        try:
            from .advisory_quarantine import record_quarantine_item
            record_quarantine_item(
                text=text,
                reason=f"meta_ralph_exception: {e}",
                source=source,
                stage="validate_and_store",
                extras={"category": str(category), "confidence": confidence},
            )
        except Exception:
            pass
        log_debug("validate_and_store", "meta_ralph_failed_quarantined_continuing", e)
        # Fall through to cognitive storage (true fail-open)

    # Step 2: Store through cognitive learner (has built-in noise filter)
    try:
        from .cognitive_learner import get_cognitive_learner
        cog = get_cognitive_learner()
        result = cog.add_insight(
            category=category,
            insight=text,
            context=context,
            confidence=confidence,
            source=source,
            record_exposure=record_exposure,
        )
        if result is not None:
            _record("stored")
            final_text = str(getattr(result, "insight", text) or text)
            return _result(True, insight_key=_derive_key(cog, final_text), stored_text=final_text)
        else:
            _record("noise_filtered")
            return _result(False, stored_text=text)
    except Exception as e:
        _record("storage_failed")
        log_debug("validate_and_store", "cognitive_store_failed", e)
        return _result(False, stored_text=text)


# Wire reload: reset cached _ENABLED when flow section changes in tuneables
def _apply_flow_config(cfg: Dict[str, Any]) -> None:
    """Hot-reload callback: clear _ENABLED cache so next call re-reads tuneables."""
    reset_enabled_cache()


try:
    from .tuneables_reload import register_reload as _vs_register
    _vs_register("flow", _apply_flow_config, label="validate_and_store.reset_enabled")
except ImportError:
    pass
