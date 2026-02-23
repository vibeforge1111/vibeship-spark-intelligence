"""User-facing advisory preference setup helpers.

Designed for a 1-2 question setup flow:
1) Memory mode: off / standard / replay
2) Guidance style: concise / balanced / coach
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


TUNEABLES_PATH = Path.home() / ".spark" / "tuneables.json"
VALID_MEMORY_MODES = {"off", "standard", "replay"}
VALID_GUIDANCE_STYLES = {"concise", "balanced", "coach"}
WRITE_LOCK_TIMEOUT_S = 5.0
WRITE_LOCK_POLL_S = 0.05
WRITE_LOCK_STALE_S = 30.0
DRIFT_KEYS = (
    "replay_enabled",
    "replay_min_strict",
    "replay_min_delta",
    "replay_max_age_s",
    "replay_strict_window_s",
    "replay_min_context",
    "replay_max_records",
    "max_items",
    "min_rank_score",
)
QUALITY_PROFILES = {
    "balanced": {
        "force_programmatic_synth": True,
        "synth_mode": "programmatic",
        "ai_timeout_s": 3.0,
    },
    "enhanced": {
        "force_programmatic_synth": False,
        "synth_mode": "auto",
        "ai_timeout_s": 6.0,
    },
    "max": {
        "force_programmatic_synth": False,
        "synth_mode": "ai_only",
        "ai_timeout_s": 8.0,
    },
}
VALID_SYNTH_PROVIDERS = {"auto", "ollama", "openai", "minimax", "anthropic", "gemini"}


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    except Exception:
        return {}


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_fd = _acquire_file_lock(lock_path)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        _release_file_lock(lock_fd, lock_path)


def _acquire_file_lock(lock_path: Path, timeout_s: float = WRITE_LOCK_TIMEOUT_S) -> int:
    deadline = time.time() + max(0.1, float(timeout_s))
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, f"{os.getpid()} {time.time()}".encode("utf-8"))
            return fd
        except FileExistsError:
            try:
                age_s = time.time() - float(lock_path.stat().st_mtime)
                if age_s > WRITE_LOCK_STALE_S:
                    lock_path.unlink(missing_ok=True)
                    continue
            except Exception:
                pass
            if time.time() >= deadline:
                raise TimeoutError(f"timed out acquiring lock: {lock_path}")
            time.sleep(WRITE_LOCK_POLL_S)


def _release_file_lock(fd: int, lock_path: Path) -> None:
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        pass


def _normalize_memory_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode in VALID_MEMORY_MODES:
        return mode
    return "standard"


def _normalize_guidance_style(value: Any) -> str:
    style = str(value or "").strip().lower()
    if style in VALID_GUIDANCE_STYLES:
        return style
    return "balanced"


def _value_differs(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return bool(actual) != bool(expected)
    try:
        if isinstance(actual, (int, float)) or isinstance(expected, (int, float)):
            return abs(float(actual) - float(expected)) > 1e-9
    except Exception:
        pass
    return actual != expected


def _detect_profile_drift(advisor_cfg: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
    overrides = []
    for key in DRIFT_KEYS:
        if key not in advisor_cfg:
            continue
        actual = advisor_cfg.get(key)
        expected = baseline.get(key)
        if _value_differs(actual, expected):
            overrides.append({"key": key, "actual": actual, "expected": expected})
    return {
        "has_drift": bool(overrides),
        "count": len(overrides),
        "overrides": overrides,
    }


def _derived_overrides(memory_mode: str, guidance_style: str) -> Dict[str, Any]:
    # Replay sensitivity profile
    replay_defaults = {
        "off": {
            "replay_enabled": False,
            "replay_min_strict": 8,
            "replay_min_delta": 0.40,
            "replay_max_age_s": 7 * 86400,
            "replay_strict_window_s": 1200,
            "replay_min_context": 0.35,
            "replay_max_records": 1200,
        },
        "standard": {
            "replay_enabled": True,
            "replay_min_strict": 5,
            "replay_min_delta": 0.25,
            "replay_max_age_s": 14 * 86400,
            "replay_strict_window_s": 1200,
            "replay_min_context": 0.18,
            "replay_max_records": 2500,
        },
        "replay": {
            "replay_enabled": True,
            "replay_min_strict": 3,
            "replay_min_delta": 0.15,
            "replay_max_age_s": 30 * 86400,
            "replay_strict_window_s": 1200,
            "replay_min_context": 0.10,
            "replay_max_records": 4500,
        },
    }[memory_mode]

    # General advisory intensity profile
    style_defaults = {
        "concise": {
            "max_items": 5,
            "min_rank_score": 0.60,
        },
        "balanced": {
            "max_items": 8,
            "min_rank_score": 0.55,
        },
        "coach": {
            "max_items": 10,
            "min_rank_score": 0.50,
        },
    }[guidance_style]

    out = dict(replay_defaults)
    out.update(style_defaults)
    out["replay_mode"] = memory_mode
    out["guidance_style"] = guidance_style
    return out


def setup_questions(current: Dict[str, Any] | None = None) -> Dict[str, Any]:
    now = current or {}
    return {
        "current": {
            "memory_mode": _normalize_memory_mode(now.get("memory_mode")),
            "guidance_style": _normalize_guidance_style(now.get("guidance_style")),
        },
        "questions": [
            {
                "id": "memory_mode",
                "question": "How much should Spark use past outcomes to suggest alternatives?",
                "options": [
                    {
                        "value": "standard",
                        "label": "Standard (Recommended)",
                        "description": "Shows replay alternatives only when evidence is strong.",
                    },
                    {
                        "value": "off",
                        "label": "Off",
                        "description": "Disables replay/counterfactual advisories.",
                    },
                    {
                        "value": "replay",
                        "label": "Replay-heavy",
                        "description": "Surfaces more historical alternatives with lower trigger threshold.",
                    },
                ],
            },
            {
                "id": "guidance_style",
                "question": "How verbose should advisory guidance be?",
                "options": [
                    {
                        "value": "balanced",
                        "label": "Balanced (Recommended)",
                        "description": "Mix of concise warnings and deeper actionable guidance.",
                    },
                    {
                        "value": "concise",
                        "label": "Concise",
                        "description": "Fewer advisories, higher rank threshold.",
                    },
                    {
                        "value": "coach",
                        "label": "Coach",
                        "description": "More guidance depth and alternatives per step.",
                    },
                ],
            },
        ],
    }


def get_current_preferences(path: Path = TUNEABLES_PATH) -> Dict[str, Any]:
    data = _read_json(path)
    advisor = data.get("advisor") if isinstance(data.get("advisor"), dict) else {}
    memory_mode = _normalize_memory_mode(advisor.get("replay_mode"))
    guidance_style = _normalize_guidance_style(advisor.get("guidance_style"))
    baseline = _derived_overrides(memory_mode, guidance_style)
    effective = dict(baseline)
    drift = _detect_profile_drift(advisor, baseline)
    # Keep explicit overrides visible if present.
    for key in DRIFT_KEYS:
        if key in advisor:
            effective[key] = advisor.get(key)
    return {
        "memory_mode": memory_mode,
        "guidance_style": guidance_style,
        "effective": effective,
        "drift": drift,
    }


def apply_preferences(
    *,
    memory_mode: Any = None,
    guidance_style: Any = None,
    path: Path = TUNEABLES_PATH,
    source: str = "manual",
) -> Dict[str, Any]:
    existing = get_current_preferences(path=path)
    resolved_mode = _normalize_memory_mode(memory_mode or existing.get("memory_mode"))
    resolved_style = _normalize_guidance_style(guidance_style or existing.get("guidance_style"))

    data = _read_json(path)
    advisor = data.setdefault("advisor", {})
    if not isinstance(advisor, dict):
        advisor = {}
        data["advisor"] = advisor

    derived = _derived_overrides(resolved_mode, resolved_style)
    for key, value in derived.items():
        advisor[key] = value

    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["advisory_preferences"] = {
        "memory_mode": resolved_mode,
        "guidance_style": resolved_style,
        "source": str(source or "manual"),
        "updated_at": data["updated_at"],
    }
    try:
        _write_json_atomic(path, data)
    except TimeoutError as exc:
        raise RuntimeError(f"tuneables update is busy, retry shortly: {path}") from exc

    # Best effort hot-reload for active process.
    try:
        from .advisor import reload_advisor_config

        runtime = reload_advisor_config()
    except Exception:
        runtime = {}

    return {
        "ok": True,
        "memory_mode": resolved_mode,
        "guidance_style": resolved_style,
        "effective": derived,
        "runtime": runtime,
        "path": str(path),
    }


def apply_quality_uplift(
    *,
    profile: Any = "enhanced",
    preferred_provider: Any = "auto",
    minimax_model: Any = None,
    ai_timeout_s: Any = None,
    path: Path = TUNEABLES_PATH,
    source: str = "manual",
) -> Dict[str, Any]:
    profile_key = str(profile or "enhanced").strip().lower()
    if profile_key not in QUALITY_PROFILES:
        profile_key = "enhanced"
    base = QUALITY_PROFILES[profile_key]

    provider = str(preferred_provider or "auto").strip().lower()
    if provider not in VALID_SYNTH_PROVIDERS:
        provider = "auto"

    timeout_value = base["ai_timeout_s"]
    if ai_timeout_s is not None:
        try:
            timeout_value = max(0.2, float(ai_timeout_s))
        except Exception:
            timeout_value = base["ai_timeout_s"]

    data = _read_json(path)
    advisory_engine_cfg = data.setdefault("advisory_engine", {})
    if not isinstance(advisory_engine_cfg, dict):
        advisory_engine_cfg = {}
        data["advisory_engine"] = advisory_engine_cfg
    synthesizer_cfg = data.setdefault("synthesizer", {})
    if not isinstance(synthesizer_cfg, dict):
        synthesizer_cfg = {}
        data["synthesizer"] = synthesizer_cfg

    advisory_engine_cfg["enabled"] = True
    advisory_engine_cfg["force_programmatic_synth"] = bool(base["force_programmatic_synth"])
    synthesizer_cfg["mode"] = str(base["synth_mode"])
    synthesizer_cfg["preferred_provider"] = provider
    synthesizer_cfg["ai_timeout_s"] = timeout_value
    if provider == "minimax":
        resolved_minimax_model = str(minimax_model or synthesizer_cfg.get("minimax_model") or "MiniMax-M2.5").strip()
        if resolved_minimax_model:
            synthesizer_cfg["minimax_model"] = resolved_minimax_model

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["updated_at"] = now_iso
    data["advisory_quality"] = {
        "profile": profile_key,
        "preferred_provider": provider,
        "ai_timeout_s": timeout_value,
        "minimax_model": synthesizer_cfg.get("minimax_model") if provider == "minimax" else None,
        "source": str(source or "manual"),
        "updated_at": now_iso,
    }
    try:
        _write_json_atomic(path, data)
    except TimeoutError as exc:
        raise RuntimeError(f"tuneables update is busy, retry shortly: {path}") from exc

    runtime: Dict[str, Any] = {}
    try:
        from .advisory_engine import apply_engine_config, get_engine_status

        apply_engine_config(advisory_engine_cfg)
        runtime["engine"] = get_engine_status()
    except Exception:
        runtime["engine"] = {}

    try:
        from .advisory_synthesizer import apply_synth_config, get_synth_status

        apply_synth_config(synthesizer_cfg)
        runtime["synthesizer"] = get_synth_status()
    except Exception:
        runtime["synthesizer"] = {}

    synth = runtime.get("synthesizer") if isinstance(runtime.get("synthesizer"), dict) else {}
    warnings = []
    if not bool(synth.get("ai_available")) and str(base["synth_mode"]) != "programmatic":
        warnings.append("no_ai_provider_available")

    return {
        "ok": True,
        "profile": profile_key,
        "preferred_provider": provider,
        "ai_timeout_s": timeout_value,
        "minimax_model": synthesizer_cfg.get("minimax_model") if provider == "minimax" else None,
        "warnings": warnings,
        "runtime": runtime,
        "path": str(path),
    }


def repair_profile_drift(
    *,
    path: Path = TUNEABLES_PATH,
    source: str = "manual",
) -> Dict[str, Any]:
    before = get_current_preferences(path=path)
    mode = before.get("memory_mode")
    style = before.get("guidance_style")
    applied = apply_preferences(
        memory_mode=mode,
        guidance_style=style,
        path=path,
        source=source,
    )
    after = get_current_preferences(path=path)
    return {
        "ok": True,
        "memory_mode": mode,
        "guidance_style": style,
        "before_drift": before.get("drift", {}),
        "after_drift": after.get("drift", {}),
        "applied": applied,
    }
