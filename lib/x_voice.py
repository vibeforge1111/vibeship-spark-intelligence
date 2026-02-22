#!/usr/bin/env python3
"""X-voice compatibility layer for conversation warmth and tone profiles.

This module provides a lightweight OSS-safe implementation used by ConvoAnalyzer
and NicheMapper when the premium/advanced voice state is unavailable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

X_VOICE_DIR = Path.home() / ".spark" / "x_voice"
PROFILES_FILE = X_VOICE_DIR / "profiles.json"


@dataclass
class ToneProfile:
    """Simple tone profile container."""

    tone_markers: List[str] = field(default_factory=list)


TONE_PROFILES: Dict[str, ToneProfile] = {
    "witty": ToneProfile(["funny", "joke", "wink", "humor", "clever", "sarcastic"]),
    "technical": ToneProfile(
        ["architecture", "stack", "implementation", "deploy", "bug", "api", "system"]
    ),
    "conversational": ToneProfile(
        ["hey", "thanks", "feel", "think", "seems", "nice", "cool", "good"]
    ),
    "provocative": ToneProfile(
        ["really", "but", "however", "disagree", "challenge", "unless", "actually"]
    ),
}


_WARMTH_PROGRESS = [
    "cold",
    "cool",
    "warm",
    "hot",
    "ally",
]


class XVoice:
    """Minimal local x_voice state store.

    Stores warmth by handle in a simple JSON file and supports a small
    transition table for `update_warmth`.
    """

    def __init__(self) -> None:
        self._state = self._load()

    def _load(self) -> Dict[str, str]:
        if PROFILES_FILE.exists():
            try:
                payload = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload
            except Exception:
                pass
        return {}

    def _save(self) -> None:
        X_VOICE_DIR.mkdir(parents=True, exist_ok=True)
        PROFILES_FILE.write_text(
            json.dumps(self._state, indent=2, default=str),
            encoding="utf-8",
        )

    def _normalize_handle(self, handle: str) -> str:
        return handle.lstrip("@").lower().strip()

    def _clamp_warmth(self, warmth: int) -> int:
        if warmth < 0:
            return 0
        if warmth >= len(_WARMTH_PROGRESS):
            return len(_WARMTH_PROGRESS) - 1
        return warmth

    def get_user_warmth(self, handle: str) -> str:
        normalized = self._normalize_handle(handle)
        return self._state.get(normalized, "cold")

    def _set_user_warmth(self, handle: str, warmth: str) -> None:
        normalized = self._normalize_handle(handle)
        self._state[normalized] = warmth
        self._save()

    def update_warmth(self, handle: str, event_type: str) -> None:
        normalized = self._normalize_handle(handle)
        warmth = self._state.get(normalized, "cold")
        idx = self._clamp_warmth(_WARMTH_PROGRESS.index(warmth))
        if event_type in {"reply", "like", "mention", "share", "mutual_like"}:
            idx = self._clamp_warmth(idx + 1)
        elif event_type in {"they_mention_us", "reply_received", "sustained_engagement"}:
            idx = self._clamp_warmth(idx + 2)
        elif event_type in {"collaboration", "multi_turn_convo"}:
            idx = self._clamp_warmth(idx + 3)
        elif event_type in {"conflict", "spam"}:
            idx = self._clamp_warmth(idx - 1)
        self._set_user_warmth(normalized, _WARMTH_PROGRESS[idx])


_x_voice: XVoice | None = None


def get_x_voice() -> XVoice:
    """Return singleton x_voice implementation."""
    global _x_voice
    if _x_voice is None:
        _x_voice = XVoice()
    return _x_voice
