"""
Central configuration resolver with deterministic precedence.

Precedence per key:
1) schema default
2) versioned baseline (config/tuneables.json)
3) runtime override (~/.spark/tuneables.json)
4) explicit env override mapping (opt-in per key)
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

DEFAULT_BASELINE_PATH = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
DEFAULT_RUNTIME_PATH = Path.home() / ".spark" / "tuneables.json"

ParserFn = Callable[[str], Any]


@dataclass(frozen=True)
class EnvOverride:
    env_name: str
    parser: ParserFn


@dataclass
class ResolvedSection:
    data: Dict[str, Any]
    sources: Dict[str, str]
    warnings: List[str] = field(default_factory=list)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _section(data: Dict[str, Any], section_name: str) -> Dict[str, Any]:
    row = data.get(section_name, {})
    return dict(row) if isinstance(row, dict) else {}


def _parse_bool(raw: str) -> bool:
    text = str(raw or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid bool: {raw!r}")


def env_bool(name: str) -> EnvOverride:
    return EnvOverride(name, _parse_bool)


def env_str(name: str, *, lower: bool = False) -> EnvOverride:
    def _parse(raw: str) -> str:
        out = str(raw or "").strip()
        return out.lower() if lower else out

    return EnvOverride(name, _parse)


def env_int(name: str, *, lo: Optional[int] = None, hi: Optional[int] = None) -> EnvOverride:
    def _parse(raw: str) -> int:
        value = int(raw)
        if lo is not None:
            value = max(int(lo), value)
        if hi is not None:
            value = min(int(hi), value)
        return value

    return EnvOverride(name, _parse)


def env_float(name: str, *, lo: Optional[float] = None, hi: Optional[float] = None) -> EnvOverride:
    def _parse(raw: str) -> float:
        value = float(raw)
        if lo is not None:
            value = max(float(lo), value)
        if hi is not None:
            value = min(float(hi), value)
        return value

    return EnvOverride(name, _parse)


def resolve_section(
    section_name: str,
    *,
    baseline_path: Optional[Path] = None,
    runtime_path: Optional[Path] = None,
    env_overrides: Optional[Dict[str, EnvOverride]] = None,
    include_schema_defaults: bool = True,
) -> ResolvedSection:
    """Resolve a tuneables section with source attribution."""
    baseline = baseline_path or DEFAULT_BASELINE_PATH
    runtime = runtime_path or DEFAULT_RUNTIME_PATH

    merged: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    warnings: List[str] = []

    if include_schema_defaults:
        try:
            from .tuneables_schema import get_section_defaults

            defaults = get_section_defaults(section_name)
            if isinstance(defaults, dict):
                for key, value in defaults.items():
                    merged[key] = deepcopy(value)
                    sources[key] = "schema"
        except Exception as exc:
            warnings.append(f"schema_load_failed:{section_name}:{exc!r}")

    baseline_section = _section(_read_json(baseline), section_name)
    for key, value in baseline_section.items():
        merged[key] = deepcopy(value)
        sources[key] = "baseline"

    runtime_section = _section(_read_json(runtime), section_name)
    for key, value in runtime_section.items():
        merged[key] = deepcopy(value)
        sources[key] = "runtime"

    for key, override in dict(env_overrides or {}).items():
        raw = os.getenv(override.env_name)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            merged[key] = deepcopy(override.parser(raw))
            sources[key] = f"env:{override.env_name}"
        except Exception:
            warnings.append(f"invalid_env_override:{override.env_name}")

    return ResolvedSection(data=merged, sources=sources, warnings=warnings)
