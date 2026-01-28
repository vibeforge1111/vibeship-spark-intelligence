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

from lib.clawdbot_files import daily_memory_path, user_md


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
    # Back-compat wrapper (older callers pass a single filename).
    diff = difflib.unified_diff(
        before.splitlines(True),
        after.splitlines(True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    path.write_text("".join(diff), encoding="utf-8")


def _patch_relpath(file_path: Path, ws: Optional[Path] = None) -> str:
    """Return a stable, workspace-relative path for patch headers.

    Important: patch headers must include the relative directory (e.g. `memory/2026-01-28.md`)
    otherwise applying the patch will create files in the wrong place.
    """

    ws = ws or get_workspace()
    try:
        rel = file_path.resolve().relative_to(ws.resolve())
        return str(rel).replace("\\", "/")
    except Exception:
        return file_path.name


def _write_patch_paths(path: Path, before: str, after: str, relpath: str) -> None:
    diff = difflib.unified_diff(
        before.splitlines(True),
        after.splitlines(True),
        fromfile=f"a/{relpath}",
        tofile=f"b/{relpath}",
    )
    path.write_text("".join(diff), encoding="utf-8")


def _replace_md_section(before: str, header: str, body: str) -> str:
    """Replace (or append) a markdown section by exact header line.

    - If `header` exists, replace everything from that header until the next `## ` header.
    - If not, append the section at the end.

    Idempotent: if the resulting content equals `before`, caller can treat as no-op.
    """

    before = before or ""
    header_line = header.strip()
    body = (body or "").rstrip() + "\n"

    lines = before.splitlines(True)  # keepends

    # Find header line index
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == header_line:
            start = i
            break

    if start is None:
        # append new section
        base = before.rstrip() + "\n\n" if before.strip() else ""
        return base + header_line + "\n" + body

    # Find end of section (next '## ' header)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## ") and lines[j].strip() != header_line:
            end = j
            break

    # Rebuild
    out = []
    out.extend(lines[: start + 1])
    # Ensure exactly one newline after header
    if out and not out[-1].endswith("\n"):
        out[-1] = out[-1] + "\n"
    out.append(body)
    out.extend(lines[end:])
    return "".join(out)


def propose_or_apply_file_edit(
    file_path: Path,
    new_content: str,
    apply: bool = False,
    patch_name_hint: str = "edit",
) -> PromotionResult:
    after = new_content

    ws = get_workspace()
    relpath = _patch_relpath(file_path, ws=ws)

    # Missing file handling
    if not file_path.exists():
        if apply:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(after, encoding="utf-8")
            return PromotionResult(patch_path=None, applied=True, reason="created")

        # Proposal: create a patch that represents a new file
        ts = time.strftime("%Y%m%d-%H%M%S")
        patch_path = proposals_dir() / f"{ts}-{patch_name_hint}.patch"
        diff = difflib.unified_diff(
            [],
            after.splitlines(True),
            fromfile="/dev/null",
            tofile=f"b/{relpath}",
        )
        patch_path.write_text("".join(diff), encoding="utf-8")
        return PromotionResult(patch_path=str(patch_path), applied=False, reason=f"proposed_create:{file_path}")

    before = file_path.read_text(encoding="utf-8")

    if before == after:
        return PromotionResult(patch_path=None, applied=False, reason="no_change")

    if apply:
        file_path.write_text(after, encoding="utf-8")
        return PromotionResult(patch_path=None, applied=True, reason="applied")

    ts = time.strftime("%Y%m%d-%H%M%S")
    patch_path = proposals_dir() / f"{ts}-{patch_name_hint}.patch"
    _write_patch_paths(patch_path, before=before, after=after, relpath=relpath)
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


def inject_into_daily_md(
    date_ymd: str,
    lines_to_add: List[str],
    section_header: str = "## Spark Digest",
    apply: bool = False,
) -> PromotionResult:
    """Propose (or apply) appending a small digest section into today's daily memory file.

    - If the file doesn't exist, return missing (we avoid creating files silently).
    - Insert directly after the section header if present; otherwise append a new section.
    """

    # parse date string is intentionally minimal; we trust caller format YYYY-MM-DD
    from datetime import datetime

    try:
        d = datetime.strptime(date_ymd, "%Y-%m-%d")
    except Exception:
        return PromotionResult(None, False, reason=f"bad_date:{date_ymd}")

    path = daily_memory_path(d)

    before = path.read_text(encoding="utf-8") if path.exists() else ""

    block = "\n".join([ln.rstrip() for ln in lines_to_add if (ln or "").strip()]).rstrip() + "\n"
    if not block.strip():
        return PromotionResult(None, False, reason="empty")

    after = _replace_md_section(before, header=section_header, body=block)

    return propose_or_apply_file_edit(
        file_path=path,
        new_content=after,
        apply=apply,
        patch_name_hint="daily",
    )


def inject_into_user_md(
    bullet_lines: List[str],
    section_header: str = "## Preferences (Spark)",
    apply: bool = False,
) -> PromotionResult:
    """Propose (or apply) adding preference bullets to USER.md.

    We only ever *add* a dedicated section to avoid reshaping the user's doc.
    """

    path = user_md()
    if not path.exists():
        return PromotionResult(None, False, reason=f"missing:{path}")

    before = path.read_text(encoding="utf-8")

    # Deduplicate existing bullets
    new_lines = []
    for b in bullet_lines:
        b = (b or "").rstrip()
        if not b.strip():
            continue
        if b.strip() in before:
            continue
        new_lines.append(b)

    if not new_lines:
        return PromotionResult(None, False, reason="no_new_lines")

    block = "\n".join(new_lines).rstrip() + "\n"

    if section_header not in before:
        after = before.rstrip() + f"\n\n{section_header}\n" + block
    else:
        parts = before.split(section_header)
        after = parts[0] + section_header + "\n" + block + parts[1].lstrip("\n")

    return propose_or_apply_file_edit(
        file_path=path,
        new_content=after,
        apply=apply,
        patch_name_hint="user",
    )
