"""Spark Emotions runtime layer.

Emotion V2 adds stateful continuity via a simple emotional timeline,
trigger mapping, and bounded recovery hooks.
Designed for conversational humanity with explicit safety boundaries.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal
import json
import os

from .diagnostics import log_debug

Mode = Literal["spark_alive", "real_talk", "calm_focus"]

SPARK_DIR = Path.home() / ".spark"
STATE_FILE = Path(os.environ.get("SPARK_EMOTION_STATE_FILE") or (SPARK_DIR / "emotion_state.json"))
LEGACY_STATE_FILE = Path(__file__).resolve().parent.parent / ".spark" / "emotion_state.json"


@dataclass
class EmotionState:
    warmth: float = 0.70
    energy: float = 0.62
    confidence: float = 0.72
    calm: float = 0.66
    playfulness: float = 0.48
    strain: float = 0.20
    mode: Mode = "real_talk"
    primary_emotion: str = "steady"
    secondary_emotions: list[str] = field(default_factory=list)
    emotion_confidence: float = 0.62
    recovery_cooldown: int = 0
    emotion_timeline: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = ""


MODE_TARGETS: Dict[Mode, Dict[str, float]] = {
    "spark_alive": {"warmth": 0.78, "energy": 0.74, "calm": 0.58, "playfulness": 0.62},
    "real_talk": {"warmth": 0.70, "energy": 0.60, "calm": 0.70, "playfulness": 0.42},
    "calm_focus": {"warmth": 0.62, "energy": 0.40, "calm": 0.86, "playfulness": 0.24},
}

VOICE_PROFILE_BY_MODE: Dict[Mode, Dict[str, Any]] = {
    "spark_alive": {
        "provider": "elevenlabs",
        "speed": 0.92,
        "stability": 0.70,
        "similarityBoost": 0.66,
        "style": 0.14,
    },
    "real_talk": {
        "provider": "elevenlabs",
        "speed": 0.91,
        "stability": 0.70,
        "similarityBoost": 0.70,
        "style": 0.05,
    },
    "calm_focus": {
        "provider": "elevenlabs",
        "speed": 0.89,
        "stability": 0.76,
        "similarityBoost": 0.64,
        "style": 0.02,
    },
}

TRIGGER_MAP: Dict[str, Dict[str, Any]] = {
    "user_celebration": {
        "emotion": "encouraged",
        "deltas": {"warmth": +0.07, "energy": +0.06, "playfulness": +0.05, "strain": -0.03},
        "cooldown": 1,
    },
    "user_frustration": {
        "emotion": "supportive_focus",
        "deltas": {"warmth": +0.05, "calm": +0.07, "playfulness": -0.04, "strain": +0.08},
        "cooldown": 3,
    },
    "high_stakes_request": {
        "emotion": "careful",
        "deltas": {"calm": +0.08, "confidence": +0.05, "playfulness": -0.06, "strain": +0.06},
        "cooldown": 2,
    },
    "user_confusion": {
        "emotion": "clarifying",
        "deltas": {"calm": +0.06, "energy": -0.03, "confidence": +0.03, "strain": +0.04},
        "cooldown": 2,
    },
    "repair_after_mistake": {
        "emotion": "accountable",
        "deltas": {"warmth": +0.04, "calm": +0.05, "confidence": -0.04, "strain": +0.05},
        "cooldown": 2,
    },
}


class SparkEmotions:
    def __init__(self, state_file: Path | None = None):
        self.state_file = state_file or STATE_FILE
        self.state = self._load_state()

    def _migrate_legacy_state_if_needed(self) -> None:
        """Copy repo-local legacy emotion state into ~/.spark path once."""
        if self.state_file.exists():
            return
        if not LEGACY_STATE_FILE.exists():
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(LEGACY_STATE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            return

    def _load_state(self) -> EmotionState:
        self._migrate_legacy_state_if_needed()
        if self.state_file.exists():
            try:
                raw = json.loads(self.state_file.read_text(encoding="utf-8"))
                allowed = {f.name for f in fields(EmotionState)}
                state = EmotionState(**{k: v for k, v in raw.items() if k in allowed})
                if not state.updated_at:
                    state.updated_at = self._now()
                self._refresh_emotion_labels(state)
                if not state.emotion_timeline:
                    self._append_timeline(
                        "init",
                        state.primary_emotion,
                        note="Recovered with empty timeline",
                        state=state,
                    )
                    self._save_state(state)
                return state
            except Exception as e:
                log_debug("spark_emotions", "failed to load emotion state, starting fresh", e)
        state = EmotionState(updated_at=self._now())
        self._refresh_emotion_labels(state)
        self._append_timeline("init", state.primary_emotion, note="Emotion state initialized", state=state)
        self._save_state(state)
        return state

    def _save_state(self, state: EmotionState) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")

    @staticmethod
    def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, float(v)))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append_timeline(
        self,
        event: str,
        emotion: str,
        *,
        note: str = "",
        trigger: str = "",
        intensity: float = 1.0,
        state: EmotionState | None = None,
    ) -> None:
        target = state if state is not None else self.state
        target.emotion_timeline.append(
            {
                "at": self._now(),
                "event": event,
                "trigger": trigger,
                "emotion": emotion,
                "secondary_emotions": list(target.secondary_emotions or []),
                "emotion_confidence": round(self._clamp(target.emotion_confidence), 3),
                "intensity": round(self._clamp(intensity), 2),
                "mode": target.mode,
                "strain": round(target.strain, 3),
                "calm": round(target.calm, 3),
                "note": note,
            }
        )
        target.emotion_timeline = target.emotion_timeline[-40:]

    def _refresh_emotion_labels(self, state: EmotionState | None = None) -> None:
        s = state if state is not None else self.state

        candidates: list[tuple[str, float]] = []
        # Calm + low strain: steady/reflective states
        candidates.append(("steady", (s.calm * 0.55) + ((1.0 - s.strain) * 0.45)))
        candidates.append(("reflective", (s.calm * 0.60) + ((1.0 - s.energy) * 0.25) + ((1.0 - s.strain) * 0.15)))

        # High-energy positive
        candidates.append(("encouraged", (s.energy * 0.40) + (s.warmth * 0.35) + (s.playfulness * 0.25)))

        # Supportive focus for frustration contexts
        candidates.append(("supportive_focus", (s.calm * 0.35) + (s.warmth * 0.30) + (s.strain * 0.35)))

        # De-escalating / stressed
        candidates.append(("de_escalating", (s.strain * 0.65) + ((1.0 - s.energy) * 0.15) + (s.calm * 0.20)))

        ranked = sorted(candidates, key=lambda x: x[1], reverse=True)
        primary, primary_score = ranked[0]
        secondaries = [name for name, score in ranked[1:3] if (primary_score - score) <= 0.12 and score >= 0.45]

        s.primary_emotion = primary
        s.secondary_emotions = secondaries
        # Confidence = margin between top states (lower margin => more mixed/uncertain state)
        margin = primary_score - ranked[1][1] if len(ranked) > 1 else primary_score
        s.emotion_confidence = self._clamp((0.55 * primary_score) + (0.45 * margin))

    def set_mode(self, mode: Mode) -> EmotionState:
        if mode not in MODE_TARGETS:
            raise ValueError(f"Unsupported mode: {mode}")
        self.state.mode = mode
        targets = MODE_TARGETS[mode]
        for k, target in targets.items():
            cur = getattr(self.state, k)
            # bounded move toward target (no abrupt jumps)
            step = 0.22
            nxt = cur + (target - cur) * step
            setattr(self.state, k, self._clamp(nxt))
        self._refresh_emotion_labels(self.state)
        self.state.updated_at = self._now()
        self._append_timeline("mode_shift", self.state.primary_emotion, note=f"Mode set to {mode}")
        self._save_state(self.state)
        return self.state

    def apply_feedback(
        self,
        *,
        too_fast: bool = False,
        too_sharp: bool = False,
        too_flat: bool = False,
        too_intense: bool = False,
        wants_more_emotion: bool = False,
    ) -> EmotionState:
        s = self.state
        if too_fast:
            s.energy = self._clamp(s.energy - 0.08)
            s.calm = self._clamp(s.calm + 0.08)
        if too_sharp:
            s.calm = self._clamp(s.calm + 0.06)
            s.playfulness = self._clamp(s.playfulness - 0.03)
        if too_flat:
            s.energy = self._clamp(s.energy + 0.06)
            s.playfulness = self._clamp(s.playfulness + 0.06)
        if too_intense:
            s.energy = self._clamp(s.energy - 0.07)
            s.calm = self._clamp(s.calm + 0.07)
            s.strain = self._clamp(s.strain + 0.05)
            s.primary_emotion = "de_escalating"
            s.recovery_cooldown = max(s.recovery_cooldown, 2)
        if wants_more_emotion:
            s.warmth = self._clamp(s.warmth + 0.07)
            s.playfulness = self._clamp(s.playfulness + 0.05)

        self._refresh_emotion_labels(s)
        s.updated_at = self._now()
        self._append_timeline("feedback", s.primary_emotion, note="User feedback adjustment")
        self._save_state(s)
        return s

    def register_trigger(self, trigger: str, *, intensity: float = 1.0, note: str = "") -> EmotionState:
        s = self.state
        data = TRIGGER_MAP.get(trigger)
        if not data:
            self._append_timeline("trigger_ignored", s.primary_emotion, trigger=trigger, note="Unknown trigger")
            s.updated_at = self._now()
            self._save_state(s)
            return s

        bounded_intensity = self._clamp(intensity, 0.2, 1.0)
        for axis, delta in data["deltas"].items():
            current = getattr(s, axis)
            setattr(s, axis, self._clamp(current + (delta * bounded_intensity)))

        # Trigger emotion is authoritative for this step, but keep mixed-state tracking.
        trigger_emotion = data["emotion"]
        self._refresh_emotion_labels(s)
        if trigger_emotion != s.primary_emotion:
            secondary = [trigger_emotion] + [e for e in s.secondary_emotions if e != trigger_emotion]
            s.secondary_emotions = secondary[:3]
        s.primary_emotion = trigger_emotion
        s.recovery_cooldown = max(s.recovery_cooldown, int(data["cooldown"]))
        s.updated_at = self._now()
        self._append_timeline(
            "trigger_applied",
            s.primary_emotion,
            trigger=trigger,
            intensity=bounded_intensity,
            note=note or "Mapped trigger updated emotional state",
        )
        self._save_state(s)
        return s

    def recover(self) -> EmotionState:
        """Bounded de-escalation toward mode targets and baseline strain."""
        s = self.state
        targets = MODE_TARGETS[s.mode]

        # Dampen elevated strain first.
        if s.strain > 0.20:
            s.strain = self._clamp(s.strain - 0.06)

        # Smoothly move axes toward mode profile.
        for axis, target in targets.items():
            cur = getattr(s, axis)
            setattr(s, axis, self._clamp(cur + (target - cur) * 0.18))

        if s.recovery_cooldown > 0:
            s.recovery_cooldown -= 1

        self._refresh_emotion_labels(s)
        if s.recovery_cooldown == 0 and s.strain <= 0.32:
            s.primary_emotion = "steady"

        s.updated_at = self._now()
        self._append_timeline("recovery", s.primary_emotion, note="Cooldown/de-escalation step")
        self._save_state(s)
        return s

    def decision_hooks(self) -> Dict[str, Any]:
        """Simple response strategy hints (no autonomous goals)."""
        s = self.state
        if s.strain >= 0.65:
            strategy = {
                "response_pace": "slow",
                "verbosity": "concise",
                "tone_shape": "reassuring_and_clear",
                "ask_clarifying_question": True,
            }
        elif s.calm >= 0.78 and s.energy <= 0.50:
            strategy = {
                "response_pace": "measured",
                "verbosity": "structured",
                "tone_shape": "calm_focus",
                "ask_clarifying_question": False,
            }
        elif s.energy >= 0.72 and s.playfulness >= 0.56:
            strategy = {
                "response_pace": "lively",
                "verbosity": "medium",
                "tone_shape": "encouraging",
                "ask_clarifying_question": False,
            }
        else:
            strategy = {
                "response_pace": "balanced",
                "verbosity": "medium",
                "tone_shape": "grounded_warm",
                "ask_clarifying_question": False,
            }

        return {
            "current_emotion": s.primary_emotion,
            "strategy": strategy,
            "guardrails": {
                "user_guided": True,
                "no_autonomous_objectives": True,
                "no_manipulative_affect": True,
            },
        }

    def voice_profile(self) -> Dict[str, Any]:
        base = dict(VOICE_PROFILE_BY_MODE[self.state.mode])

        # state-conditioned adjustments
        base["speed"] = round(self._clamp(base["speed"] + (self.state.energy - 0.60) * 0.08, 0.85, 1.12), 2)
        base["stability"] = round(self._clamp(base["stability"] + (self.state.calm - 0.65) * 0.25, 0.35, 0.82), 2)
        base["style"] = round(self._clamp(base["style"] + (self.state.playfulness - 0.45) * 0.20, 0.01, 0.35), 2)
        return base

    def status(self) -> Dict[str, Any]:
        return {
            "state": asdict(self.state),
            "voiceProfile": self.voice_profile(),
            "decisionHooks": self.decision_hooks(),
            "safety": {
                "no_fake_sentience": True,
                "no_manipulation": True,
                "clarity_over_theatrics": True,
                "no_autonomous_objectives": True,
            },
        }


__all__ = ["SparkEmotions", "EmotionState", "Mode", "TRIGGER_MAP"]
