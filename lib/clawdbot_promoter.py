"""Clawdbot file-based promotion helpers.

Design:
- Default to *proposals* (patch files), not direct edits.
- Make applying explicit with `--apply`.

Patches are written to:
  <workspace>/.spark/proposals/*.patch

This keeps Spark compatible with Clawdbot's constitution + memory model.
"""

from __future__ import annotations

import os
import time
import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


def get_workspace() -> Path:
    return Path(os.environ.get("SPARK_WORKSPACE", str(Path.home() / "clawd"))).expanduser()


def proposals_dir(workspace: Optional[Path] = None) -> Path:
    ws = workspace or get_workspace()
    out = ws / ".spark" / "proposals"
    out.mkdir(parents=True, exist_ok=True)
    return out


@dataclass
class PromotionResult:
    patch_path: Optional[str]
    applied: bool
    reason: str = ""


def _write_patch(path: Path, before: str, after: str, filename: str) -> None:
    diff = difflib.unified_diff(
        before.splitlines(True),
        after.splitlines(True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    path.write_text("".join(diff), encoding="utf-8")


def propose_or_apply_file_edit(
    file_path: Path,
    new_content: str,
    apply: bool = False,
    patch_name_hint: str = "edit",
) -> PromotionResult:
    if not file_path.exists():
        return PromotionResult(patch_path=None, applied=False, reason=f"missing:{file_path}")

    before = file_path.read_text(encoding="utf-8")
    after = new_content

    if before == after:
        return PromotionResult(patch_path=None, applied=False, reason="no_change")

    if apply:
        file_path.write_text(after, encoding="utf-8")
        return PromotionResult(patch_path=None, applied=True, reason="applied")

    ts = time.strftime("%Y%m%d-%H%M%S")
    patch_path = proposals_dir() / f"{ts}-{patch_name_hint}.patch"
    _write_patch(patch_path, before=before, after=after, filename=file_path.name)
    return PromotionResult(patch_path=str(patch_path), applied=False, reason="proposed")


def _extract_topic_key(text: str) -> Optional[str]:
    # Heuristic: treat `topic: preference` as a topic key.
    if ":" in text:
        left = text.split(":", 1)[0].strip().lower()
        if 2 <= len(left) <= 64:
            return left
    return None


def _detect_conflict(existing_lines: List[str], new_text: str) -> Optional[str]:
    key = _extract_topic_key(new_text)
    if not key:
        return None

    for ln in existing_lines:
        if ":" not in ln:
            continue
        left = ln.split(":", 1)[0].strip().lower()
        if left == key and ln.strip() != new_text.strip():
            return ln.strip()
    return None


def inject_into_memory_md(
    memory_path: Path,
    bullet_line: str,
    section_header: str = "## Spark Learnings",
    apply: bool = False,
) -> Tuple[PromotionResult, Optional[str]]:
    """Propose (or apply) a single bullet insertion into MEMORY.md.

    Returns (result, conflict_line).
    """

    if not memory_path.exists():
        return PromotionResult(None, False, reason=f"missing:{memory_path}"), None

    before = memory_path.read_text(encoding="utf-8")

    if bullet_line.strip() in before:
        return PromotionResult(None, False, reason="already_present"), None

    lines = before.splitlines()
    conflict = _detect_conflict(existing_lines=lines, new_text=bullet_line)

    if section_header not in before:
        after = before.rstrip() + f"\n\n{section_header}\n" + bullet_line.rstrip() + "\n"
    else:
        parts = before.split(section_header)
        # Insert right after the header
        after = parts[0] + section_header + "\n" + bullet_line.rstrip() + "\n" + parts[1].lstrip("\n")

    res = propose_or_apply_file_edit(
        file_path=memory_path,
        new_content=after,
        apply=apply,
        patch_name_hint="memory",
    )
    return res, conflict
