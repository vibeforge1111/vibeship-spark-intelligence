#!/usr/bin/env python3
"""Interactive 2-question setup for Spark advisory preferences."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.preferences import (  # noqa: E402
    apply_preferences,
    get_current_preferences,
    setup_questions,
)


def _pick_option(question: Dict[str, Any], current_value: str) -> str:
    options: List[Dict[str, Any]] = question.get("options") or []
    if not options:
        return current_value

    current = str(current_value or "").strip().lower()
    default_idx = 1
    for idx, opt in enumerate(options, start=1):
        if str(opt.get("value") or "").strip().lower() == current:
            default_idx = idx
            break

    print()
    print(question.get("question") or "Choose an option:")
    for idx, opt in enumerate(options, start=1):
        mark = " (current)" if idx == default_idx else ""
        label = str(opt.get("label") or opt.get("value") or f"Option {idx}")
        desc = str(opt.get("description") or "").strip()
        print(f"{idx}. {label}{mark}")
        if desc:
            print(f"   {desc}")

    while True:
        raw = input(f"Select [default {default_idx}]: ").strip()
        if not raw:
            return str(options[default_idx - 1].get("value") or current_value)
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(options):
                return str(options[choice - 1].get("value") or current_value)
        print("Invalid selection. Enter the option number.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Set Spark advisory preferences in 1-2 questions.")
    parser.add_argument("--memory-mode", choices=["off", "standard", "replay"], help="Memory usage mode.")
    parser.add_argument(
        "--guidance-style",
        choices=["concise", "balanced", "coach"],
        help="Advisory verbosity/depth style.",
    )
    parser.add_argument("--show", action="store_true", help="Show current preferences and exit.")
    parser.add_argument("--source", default="cli_setup", help="Source label stored in tuneables metadata.")
    args = parser.parse_args()

    current = get_current_preferences()
    if args.show:
        print(json.dumps(current, indent=2))
        return 0

    memory_mode = args.memory_mode
    guidance_style = args.guidance_style
    if not memory_mode or not guidance_style:
        setup = setup_questions(current=current)
        questions = setup.get("questions") or []
        if not memory_mode and questions:
            memory_mode = _pick_option(questions[0], current.get("memory_mode", "standard"))
        if not guidance_style and len(questions) > 1:
            guidance_style = _pick_option(questions[1], current.get("guidance_style", "balanced"))

    result = apply_preferences(
        memory_mode=memory_mode,
        guidance_style=guidance_style,
        source=args.source,
    )
    print()
    print("Updated advisory preferences:")
    print(f"  memory_mode: {result.get('memory_mode')}")
    print(f"  guidance_style: {result.get('guidance_style')}")
    print(f"  tuneables: {result.get('path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
