from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


TRAITS = ("warmth", "directness", "playfulness", "pacing", "assertiveness")
DEFAULT_TRAIT_VALUE = 0.5
MIN_TRAIT_VALUE = 0.0
MAX_TRAIT_VALUE = 1.0
DEFAULT_STEP_SIZE = 0.04
STATE_VERSION = 1


@dataclass(frozen=True)
class EvolutionConfig:
    """Configuration for personality evolution update behavior."""

    step_size: float = DEFAULT_STEP_SIZE
    min_value: float = MIN_TRAIT_VALUE
    max_value: float = MAX_TRAIT_VALUE


class PersonalityEvolver:
    """User-guided, bounded personality evolution state manager.

    Guardrails:
    - Feature-gated (disabled by default)
    - Applies updates only when explicit `user_guided` signal is present
    - Uses bounded incremental deltas with clamps
    - No autonomous objective logic (state-only style adaptation)
    """

    def __init__(
        self,
        *,
        state_path: Optional[Path] = None,
        enabled: Optional[bool] = None,
        observer_mode: Optional[bool] = None,
        config: EvolutionConfig = EvolutionConfig(),
    ) -> None:
        self.config = config
        self.state_path = Path(state_path) if state_path else default_state_path()
        self.enabled = feature_enabled() if enabled is None else bool(enabled)
        self.observer_mode = observer_mode_enabled() if observer_mode is None else bool(observer_mode)
        self.state = self.load_state()

    def load_state(self) -> Dict[str, Any]:
        if self.state_path.exists():
            try:
                raw = json.loads(self.state_path.read_text(encoding="utf-8"))
                return self._normalize_state(raw)
            except Exception:
                pass
        return self._default_state()

    def save_state(self) -> Dict[str, Any]:
        self.state["updated_at"] = time.time()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        return self.state

    def reset_state(self, *, persist: bool = True) -> Dict[str, Any]:
        self.state = self._default_state()
        if persist:
            self.save_state()
        return self.state

    def ingest_signals(self, signals: Mapping[str, Any], *, persist: bool = True) -> Dict[str, Any]:
        """Apply user-guided interaction signals to trait state.

        Accepted signals:
        - user_guided: bool (required True for updates)
        - trait_deltas: {trait: float in [-1, 1]} (preferred)
        - <trait>_up / <trait>_down scalar hints (fallback)
        """
        payload = dict(signals or {})

        if not self.enabled:
            return {
                "applied": False,
                "reason": "feature_disabled",
                "state": self.state,
                "style_profile": self.emit_style_profile(),
            }

        if not bool(payload.get("user_guided", False)):
            return {
                "applied": False,
                "reason": "missing_user_guided_signal",
                "state": self.state,
                "style_profile": self.emit_style_profile(),
            }

        proposed = dict(self.state)
        proposed_traits = dict(proposed.get("traits", {}))

        for trait, delta in self._extract_trait_deltas(payload).items():
            current = float(proposed_traits.get(trait, DEFAULT_TRAIT_VALUE))
            bounded = self._bounded_delta(delta)
            proposed_traits[trait] = self._clamp(current + bounded)

        proposed["traits"] = proposed_traits
        proposed["interaction_count"] = int(proposed.get("interaction_count", 0)) + 1
        proposed["last_signals"] = payload
        proposed["updated_at"] = time.time()

        if not self.observer_mode:
            self.state = self._normalize_state(proposed)
            if persist:
                self.save_state()
            applied = True
            reason = "applied"
        else:
            applied = False
            reason = "observer_mode"

        return {
            "applied": applied,
            "reason": reason,
            "state": self.state,
            "proposed_state": self._normalize_state(proposed),
            "style_profile": self.emit_style_profile(),
        }

    def emit_style_profile(self) -> Dict[str, Any]:
        traits = self.state.get("traits", {})
        return {
            "version": self.state.get("version", STATE_VERSION),
            "updated_at": self.state.get("updated_at"),
            "interaction_count": int(self.state.get("interaction_count", 0)),
            "traits": {k: round(float(traits.get(k, DEFAULT_TRAIT_VALUE)), 3) for k in TRAITS},
            "style_labels": {
                "warmth": self._label(traits.get("warmth", DEFAULT_TRAIT_VALUE), low="reserved", high="warm"),
                "directness": self._label(traits.get("directness", DEFAULT_TRAIT_VALUE), low="gentle", high="direct"),
                "playfulness": self._label(traits.get("playfulness", DEFAULT_TRAIT_VALUE), low="serious", high="playful"),
                "pacing": self._label(traits.get("pacing", DEFAULT_TRAIT_VALUE), low="deliberate", high="fast"),
                "assertiveness": self._label(traits.get("assertiveness", DEFAULT_TRAIT_VALUE), low="deferential", high="assertive"),
            },
        }

    def _extract_trait_deltas(self, payload: Dict[str, Any]) -> Dict[str, float]:
        deltas: Dict[str, float] = {trait: 0.0 for trait in TRAITS}

        provided = payload.get("trait_deltas")
        if isinstance(provided, Mapping):
            for trait in TRAITS:
                if trait in provided:
                    deltas[trait] += self._to_float(provided.get(trait))

        for trait in TRAITS:
            up_key = f"{trait}_up"
            down_key = f"{trait}_down"
            if up_key in payload:
                deltas[trait] += self._to_float(payload.get(up_key))
            if down_key in payload:
                deltas[trait] -= self._to_float(payload.get(down_key))

        return deltas

    def _default_state(self) -> Dict[str, Any]:
        now = time.time()
        return {
            "version": STATE_VERSION,
            "updated_at": now,
            "interaction_count": 0,
            "traits": {k: DEFAULT_TRAIT_VALUE for k in TRAITS},
            "last_signals": {},
        }

    def _normalize_state(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        base = self._default_state()
        if not isinstance(raw, dict):
            return base
        base["version"] = int(raw.get("version", STATE_VERSION))
        base["updated_at"] = float(raw.get("updated_at", base["updated_at"]))
        base["interaction_count"] = int(raw.get("interaction_count", 0))
        base["last_signals"] = raw.get("last_signals") if isinstance(raw.get("last_signals"), dict) else {}

        raw_traits = raw.get("traits") if isinstance(raw.get("traits"), dict) else {}
        traits = {}
        for trait in TRAITS:
            traits[trait] = self._clamp(self._to_float(raw_traits.get(trait, DEFAULT_TRAIT_VALUE)))
        base["traits"] = traits
        return base

    def _bounded_delta(self, value: float) -> float:
        step = abs(float(self.config.step_size or DEFAULT_STEP_SIZE))
        return max(-step, min(step, self._to_float(value) * step))

    def _clamp(self, value: float) -> float:
        return max(self.config.min_value, min(self.config.max_value, float(value)))

    def _to_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _label(self, value: float, *, low: str, high: str) -> str:
        val = float(value)
        if val <= 0.35:
            return low
        if val >= 0.65:
            return high
        return "balanced"


def feature_enabled() -> bool:
    try:
        from lib.config_authority import resolve_section, env_bool
        cfg = resolve_section(
            "feature_gates",
            env_overrides={"personality_evolution": env_bool("SPARK_PERSONALITY_EVOLUTION_V1")},
        ).data
        return bool(cfg.get("personality_evolution", False))
    except Exception:
        return str(os.environ.get("SPARK_PERSONALITY_EVOLUTION_V1", "")).strip().lower() in {"1", "true", "yes", "on"}


def observer_mode_enabled() -> bool:
    try:
        from lib.config_authority import resolve_section, env_bool
        cfg = resolve_section(
            "feature_gates",
            env_overrides={"personality_observer": env_bool("SPARK_PERSONALITY_EVOLUTION_OBSERVER")},
        ).data
        return bool(cfg.get("personality_observer", False))
    except Exception:
        return str(os.environ.get("SPARK_PERSONALITY_EVOLUTION_OBSERVER", "")).strip().lower() in {"1", "true", "yes", "on"}


def default_state_path() -> Path:
    # Keep state in the same root convention as other runtime JSONL files.
    return Path.home() / ".spark" / "personality_evolution_v1.json"


def load_personality_evolver(
    *,
    state_path: Optional[Path] = None,
    enabled: Optional[bool] = None,
    observer_mode: Optional[bool] = None,
) -> PersonalityEvolver:
    return PersonalityEvolver(
        state_path=state_path,
        enabled=enabled,
        observer_mode=observer_mode,
    )
