#!/usr/bin/env python3
# ruff: noqa: S603
"""Clawdbot Memory Search Setup (lightweight)

Goal: make it dead-simple to switch memorySearch embedding providers.

We support these modes:
  - off
  - local (GGUF via node-llama-cpp; user supplies modelPath)
  - openai (requires OPENAI_API_KEY or memorySearch.remote.apiKey)
  - gemini (requires GEMINI_API_KEY or memorySearch.remote.apiKey)
  - remote (OpenAI-compatible endpoint; requires baseUrl + apiKey)

This edits ~/.clawdbot/clawdbot.json directly (safe JSON patch) and restarts the
Gateway (SIGUSR1) via `clawdbot gateway restart`.

NOTE: Codex OAuth does NOT provide embeddings; that's why this exists.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


CLAWDBOT_BIN = Path.home() / ".npm-global" / "bin" / "clawdbot"
CONFIG_PATH = Path.home() / ".clawdbot" / "clawdbot.json"


def _load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing config: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _save_config(cfg: Dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _ensure_path(cfg: Dict[str, Any], path: str) -> Dict[str, Any]:
    cur = cfg
    for part in path.split("."):
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    return cur


def _restart_gateway() -> None:
    if not CLAWDBOT_BIN.exists():
        return
    # Best-effort restart (emits SIGUSR1 to the service)
    try:
        subprocess.run([str(CLAWDBOT_BIN), "gateway", "restart"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def get_current_memory_search(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or _load_config()
    ms = (cfg.get("agents", {})
            .get("defaults", {})
            .get("memorySearch", {}))
    return ms


@dataclass
class MemoryMode:
    provider: str
    model: Optional[str] = None
    fallback: Optional[str] = None
    local_model_path: Optional[str] = None
    remote_base_url: Optional[str] = None
    remote_api_key: Optional[str] = None


def apply_memory_mode(mode: str, *, local_model_path: Optional[str] = None,
                      remote_base_url: Optional[str] = None,
                      remote_api_key: Optional[str] = None,
                      model: Optional[str] = None,
                      fallback: Optional[str] = None,
                      restart: bool = True) -> Dict[str, Any]:
    """Apply a memorySearch mode into Clawdbot config."""

    cfg = _load_config()
    defaults = _ensure_path(cfg, "agents.defaults")

    if mode == "off":
        # Turn off semantic tools (memory still exists as files).
        defaults["memorySearch"] = {"enabled": False, "provider": "none"}

    elif mode == "local":
        if not local_model_path:
            raise ValueError("local mode requires local_model_path")
        defaults["memorySearch"] = {
            "enabled": True,
            "provider": "local",
            "fallback": fallback or "none",
            "local": {"modelPath": local_model_path},
        }

    elif mode == "openai":
        defaults["memorySearch"] = {
            "enabled": True,
            "provider": "openai",
            "model": model or "text-embedding-3-small",
            "fallback": fallback or "none",
        }

    elif mode == "gemini":
        defaults["memorySearch"] = {
            "enabled": True,
            "provider": "gemini",
            "model": model or "gemini-embedding-001",
            "fallback": fallback or "none",
        }

    elif mode == "remote":
        if not remote_base_url or not remote_api_key:
            raise ValueError("remote mode requires remote_base_url and remote_api_key")
        defaults["memorySearch"] = {
            "enabled": True,
            "provider": "openai",
            "model": model or "text-embedding-3-small",
            "fallback": fallback or "none",
            "remote": {
                "baseUrl": remote_base_url,
                "apiKey": remote_api_key,
            },
        }

    else:
        raise ValueError(f"Unknown mode: {mode}")

    _save_config(cfg)
    if restart:
        _restart_gateway()
    return defaults["memorySearch"]


def run_memory_status(agent: str = "main") -> str:
    if not CLAWDBOT_BIN.exists():
        return "clawdbot binary not found"
    try:
        out = subprocess.check_output([str(CLAWDBOT_BIN), "memory", "status", "--deep", "--agent", agent], stderr=subprocess.STDOUT, text=True)
        return out
    except subprocess.CalledProcessError as e:
        return e.output or str(e)


def recommended_modes() -> Dict[str, Dict[str, str]]:
    return {
        "off": {"cost": "free", "privacy": "max", "setup": "none"},
        "local": {"cost": "free", "privacy": "max", "setup": "download model"},
        "remote": {"cost": "cheap", "privacy": "low", "setup": "baseUrl+apiKey"},
        "openai": {"cost": "$$", "privacy": "low", "setup": "OPENAI_API_KEY"},
        "gemini": {"cost": "$$", "privacy": "low", "setup": "GEMINI_API_KEY"},
    }
