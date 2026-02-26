#!/usr/bin/env python3
"""Interactive setup for runtime LLM usage across intelligence subsystems."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.intelligence_llm_preferences import (  # noqa: E402
    apply_runtime_llm_preferences,
    detect_local_ollama,
    get_current_preferences,
)


def _ask_bool(question: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{question} [{suffix}]: ").strip().lower()
        if not raw:
            return bool(default)
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer y or n.")


def _pick_provider(default_provider: str) -> str:
    options = ["auto", "ollama", "minimax", "openai", "anthropic", "gemini", "claude"]
    print("\nChoose runtime LLM provider:")
    for idx, provider in enumerate(options, start=1):
        mark = " (default)" if provider == default_provider else ""
        print(f"{idx}. {provider}{mark}")
    while True:
        raw = input(f"Select [default {default_provider}]: ").strip().lower()
        if not raw:
            return default_provider
        if raw.isdigit():
            i = int(raw)
            if 1 <= i <= len(options):
                return options[i - 1]
        if raw in options:
            return raw
        print("Invalid provider selection.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure runtime LLM usage for Spark intelligence systems.")
    parser.add_argument("--show", action="store_true", help="Show current runtime LLM preferences and exit")
    parser.add_argument("--provider", default=None, help="Provider override (auto/ollama/minimax/openai/anthropic/gemini/claude)")
    parser.add_argument("--enable-all", action="store_true", help="Enable all runtime LLM assists")
    parser.add_argument("--disable-all", action="store_true", help="Disable all runtime LLM assists")
    parser.add_argument("--source", default="intelligence_llm_setup", help="Source label written to tuneables metadata")
    args = parser.parse_args()

    current = get_current_preferences()
    if args.show:
        print(json.dumps(current, indent=2))
        return 0

    if args.enable_all and args.disable_all:
        raise SystemExit("Cannot use --enable-all and --disable-all together.")

    local_ollama = detect_local_ollama()
    suggested_provider = "ollama" if local_ollama else "auto"
    provider = str(args.provider or suggested_provider).strip().lower()

    print("Runtime LLM Setup")
    print(f"- Local Ollama detected: {'yes' if local_ollama else 'no'}")
    print(f"- Suggested provider: {suggested_provider}")

    if args.enable_all:
        eidos = True
        meta = True
        scanner = True
        packet = True
    elif args.disable_all:
        eidos = False
        meta = False
        scanner = False
        packet = False
    else:
        provider = _pick_provider(provider)
        eidos = _ask_bool(
            "Enable runtime LLM refinement for EIDOS distillation transformations?",
            default=True,
        )
        meta = _ask_bool(
            "Enable runtime LLM refinement for Meta-Ralph NEEDS_WORK learnings?",
            default=True,
        )
        scanner = _ask_bool(
            "Enable LLM assistance in Opportunity Scanner?",
            default=bool(current.get("opportunity_scanner_llm_enabled", True)),
        )
        packet = _ask_bool(
            "Enable LLM rerank for advisory packet lookup (higher latency)?",
            default=False,
        )

    result = apply_runtime_llm_preferences(
        eidos_runtime_llm=eidos,
        meta_ralph_runtime_llm=meta,
        opportunity_scanner_llm=scanner,
        packet_lookup_llm=packet,
        provider=provider,
        source=args.source,
    )
    print("\nUpdated runtime LLM preferences:")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

