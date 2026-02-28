"""Observatory report center and Claude analysis helpers."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPORT_DIRS = ("docs/reports", "reports")
_DEFAULT_PATTERNS = ("*.md", "*.json", "*.jsonl")
_ANALYSIS_INDEX = "_index.json"


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _fmt_ts(ts: float) -> str:
    if ts <= 0:
        return "unknown"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _slug_for_path(path: Path, *, repo_root: Path) -> str:
    try:
        rel = str(path.resolve().relative_to(repo_root.resolve()))
    except Exception:
        rel = str(path.resolve())
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", rel).strip("-").lower()
    return slug or "report"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            try:
                return path.read_text(encoding="latin-1")
            except Exception:
                return ""


def _preview_text(path: Path, *, max_chars: int = 9000) -> str:
    text = _read_text(path)
    if not text:
        return ""
    return text[:max_chars]


def _load_analysis_index(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_analysis_index(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{time.time_ns()}")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def discover_reports(
    *,
    repo_root: Optional[Path] = None,
    max_reports: int = 400,
    patterns: Sequence[str] = _DEFAULT_PATTERNS,
) -> List[Dict[str, Any]]:
    root = repo_root or _REPO_ROOT
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for rel_dir in _REPORT_DIRS:
        base = root / rel_dir
        if not base.exists():
            continue
        for pattern in patterns:
            for path in base.rglob(pattern):
                if not path.is_file():
                    continue
                resolved = str(path.resolve())
                if resolved in seen:
                    continue
                seen.add(resolved)
                try:
                    st = path.stat()
                except Exception:
                    continue
                rel = ""
                try:
                    rel = str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
                except Exception:
                    rel = str(path).replace("\\", "/")
                slug = _slug_for_path(path, repo_root=root)
                out.append(
                    {
                        "path": str(path.resolve()),
                        "relative_path": rel,
                        "name": path.name,
                        "suffix": path.suffix.lower(),
                        "slug": slug,
                        "mtime": float(st.st_mtime),
                        "size": int(st.st_size),
                    }
                )
    out.sort(key=lambda r: float(r.get("mtime") or 0.0), reverse=True)
    return out[: max(1, int(max_reports))]


def _report_stub_page(
    report: Dict[str, Any],
    *,
    analysis_entry: Dict[str, Any],
    source_path: Path,
    analysis_page_name: str,
) -> str:
    preview = _preview_text(source_path, max_chars=9000)
    preview_type = "markdown"
    suffix = _norm_text(report.get("suffix")).lower()
    if suffix in {".json", ".jsonl"}:
        preview_type = "json"
    lines = [
        "---",
        f"title: Report Source - {_norm_text(report.get('name'))}",
        "tags:",
        "  - observatory",
        "  - reports",
        "  - source",
        "---",
        "",
        f"# Report Source: `{_norm_text(report.get('name'))}`",
        "",
        f"- Relative path: `{_norm_text(report.get('relative_path'))}`",
        f"- Absolute path: `{_norm_text(report.get('path'))}`",
        f"- Last modified (UTC): `{_fmt_ts(float(report.get('mtime') or 0.0))}`",
        f"- Size bytes: `{int(report.get('size') or 0)}`",
        "",
        "## Claude Analysis",
        "",
    ]
    if analysis_entry:
        lines.append(
            f"- Status: `{_norm_text(analysis_entry.get('status') or 'unknown')}` | "
            f"Updated: `{_fmt_ts(float(analysis_entry.get('generated_at') or 0.0))}` | "
            f"Model/provider: `{_norm_text(analysis_entry.get('provider') or 'claude')}`"
        )
        lines.append(f"- Analysis page: [[reports/claude_analysis/{analysis_page_name}|Open Claude Analysis]]")
    else:
        lines.append("- Status: `not_analyzed`")
        lines.append(
            f"- Run: `python scripts/claude_observatory_report_analyzer.py --report \"{_norm_text(report.get('relative_path'))}\"`"
        )
    lines.extend(["", "## Source Preview", ""])
    if not preview:
        lines.append("_Unable to read source content._")
    elif preview_type == "markdown":
        lines.append(preview)
    else:
        lines.append(f"```{preview_type}")
        lines.append(preview)
        lines.append("```")
    if len(preview) >= 9000:
        lines.extend(["", "_Preview truncated. Open source path for full content._"])
    lines.append("")
    return "\n".join(lines)


def generate_report_center(
    *,
    obs_dir: Path,
    repo_root: Optional[Path] = None,
    max_reports: int = 300,
) -> Dict[str, Any]:
    root = repo_root or _REPO_ROOT
    reports = discover_reports(repo_root=root, max_reports=max_reports)
    reports_dir = obs_dir / "reports"
    source_dir = reports_dir / "source"
    analysis_dir = reports_dir / "claude_analysis"
    source_dir.mkdir(parents=True, exist_ok=True)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    analysis_index_path = analysis_dir / _ANALYSIS_INDEX
    analysis_index = _load_analysis_index(analysis_index_path)
    analysis_entries = analysis_index.get("entries") if isinstance(analysis_index.get("entries"), dict) else {}
    analysis_entries = analysis_entries if isinstance(analysis_entries, dict) else {}

    files_written = 0
    rows: List[str] = []
    for report in reports:
        slug = _norm_text(report.get("slug"))
        if not slug:
            continue
        source_page_name = f"{slug}.md"
        source_page_path = source_dir / source_page_name
        analysis_page_name = f"{slug}.md"
        source_path = Path(_norm_text(report.get("path")))
        analysis_entry = analysis_entries.get(slug) if isinstance(analysis_entries.get(slug), dict) else {}
        source_page = _report_stub_page(
            report,
            analysis_entry=analysis_entry,
            source_path=source_path,
            analysis_page_name=analysis_page_name,
        )
        source_page_path.write_text(source_page, encoding="utf-8")
        files_written += 1
        analysis_status = _norm_text((analysis_entry or {}).get("status") or "not_analyzed")
        rows.append(
            f"| [[reports/source/{source_page_name}|{_norm_text(report.get('name'))}]] | "
            f"`{_norm_text(report.get('relative_path'))}` | "
            f"{_fmt_ts(float(report.get('mtime') or 0.0))} | "
            f"{int(report.get('size') or 0)} | "
            f"{analysis_status} | "
            f"[[reports/claude_analysis/{analysis_page_name}|analysis]] |"
        )

    lines = [
        "---",
        "title: Report Center",
        "tags:",
        "  - observatory",
        "  - reports",
        "  - claude",
        "---",
        "",
        "# Report Center",
        "",
        "> Reach every report and open its Claude analysis directly from Observatory.",
        "",
        "## Quick Actions",
        "",
        "- Refresh report hub only: `python scripts/generate_observatory.py --force`",
        "- Analyze recent reports with Claude: `python scripts/claude_observatory_report_analyzer.py --max-reports 20`",
        "- Analyze one report: `python scripts/claude_observatory_report_analyzer.py --report \"docs/reports/<file>.md\"`",
        "",
        "## Report Index",
        "",
        f"- Reports indexed: `{len(reports)}`",
        f"- Source stub pages: `{files_written}`",
        f"- Claude analyses tracked: `{len(analysis_entries)}`",
        "",
        "| Report | Source Path | Last Modified (UTC) | Size (B) | Claude Status | Claude Page |",
        "|---|---|---|---:|---|---|",
    ]
    if rows:
        lines.extend(rows)
    else:
        lines.append("| _none_ | - | - | - | - | - |")
    lines.append("")
    index_path = obs_dir / "report_center.md"
    index_path.write_text("\n".join(lines), encoding="utf-8")
    files_written += 1

    return {
        "reports_indexed": len(reports),
        "analysis_index_entries": len(analysis_entries),
        "files_written": files_written,
        "index_path": str(index_path),
        "analysis_index_path": str(analysis_index_path),
    }


def _analysis_prompt(*, report: Dict[str, Any], report_text: str) -> str:
    context = report_text[:28000]
    return (
        "You are a world-class Systems Architect, QA Lead, and AGI Engineer.\n\n"
        "Task:\n"
        "Analyze this Spark report with rigorous, falsifiable reasoning.\n"
        "Focus on: reliability risks, signal quality, missing evidence, and concrete remediation loops.\n\n"
        "Output format (strict markdown):\n"
        "1. Executive Verdict (max 8 bullets)\n"
        "2. What Is Proven vs Assumed\n"
        "3. High-Risk Findings (ranked, with evidence references)\n"
        "4. Missing Telemetry/Tests Needed\n"
        "5. 4-Hour Next Actions (owner + metric + gate)\n"
        "6. Failure Modes That Could Still Surprise Us\n\n"
        f"Report file: {_norm_text(report.get('relative_path'))}\n"
        f"Report modified: {_fmt_ts(float(report.get('mtime') or 0.0))}\n\n"
        "Report content:\n"
        f"{context}\n"
    )


def analyze_reports_with_claude(
    *,
    obs_dir: Path,
    repo_root: Optional[Path] = None,
    max_reports: int = 20,
    timeout_s: int = 180,
    overwrite: bool = False,
    report_paths: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    root = repo_root or _REPO_ROOT
    reports_dir = obs_dir / "reports"
    analysis_dir = reports_dir / "claude_analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    index_path = analysis_dir / _ANALYSIS_INDEX
    index_payload = _load_analysis_index(index_path)
    entries = index_payload.get("entries") if isinstance(index_payload.get("entries"), dict) else {}
    entries = dict(entries) if isinstance(entries, dict) else {}

    reports: List[Dict[str, Any]]
    if report_paths:
        reports = []
        for raw in report_paths:
            p = Path(str(raw))
            path = p if p.is_absolute() else (root / p)
            if not path.exists() or not path.is_file():
                continue
            st = path.stat()
            rel = str(path.resolve())
            try:
                rel = str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
            except Exception:
                rel = str(path).replace("\\", "/")
            reports.append(
                {
                    "path": str(path.resolve()),
                    "relative_path": rel,
                    "name": path.name,
                    "suffix": path.suffix.lower(),
                    "slug": _slug_for_path(path, repo_root=root),
                    "mtime": float(st.st_mtime),
                    "size": int(st.st_size),
                }
            )
    else:
        reports = discover_reports(repo_root=root, max_reports=max_reports)

    reports = reports[: max(1, int(max_reports))]
    attempted = 0
    written = 0
    errors: List[Dict[str, Any]] = []

    from lib.llm import ask_claude

    for report in reports:
        slug = _norm_text(report.get("slug"))
        if not slug:
            continue
        attempted += 1
        out_path = analysis_dir / f"{slug}.md"
        existing = entries.get(slug) if isinstance(entries.get(slug), dict) else {}
        if out_path.exists() and not overwrite:
            entries[slug] = {
                "status": _norm_text(existing.get("status") or "analyzed"),
                "generated_at": float(existing.get("generated_at") or out_path.stat().st_mtime),
                "report_path": _norm_text(report.get("relative_path")),
                "provider": _norm_text(existing.get("provider") or "claude"),
                "analysis_page": out_path.name,
            }
            continue

        source_path = Path(_norm_text(report.get("path")))
        report_text = _read_text(source_path)
        if not report_text:
            err = {"report": _norm_text(report.get("relative_path")), "error": "empty_or_unreadable_report"}
            errors.append(err)
            entries[slug] = {
                "status": "error",
                "generated_at": time.time(),
                "report_path": _norm_text(report.get("relative_path")),
                "provider": "claude",
                "error": _norm_text(err.get("error")),
                "analysis_page": out_path.name,
            }
            continue

        prompt = _analysis_prompt(report=report, report_text=report_text)
        response = ask_claude(
            prompt,
            system_prompt=(
                "You are an uncompromising reliability reviewer. "
                "Prefer precise, falsifiable claims and explicit uncertainty."
            ),
            max_tokens=2800,
            timeout_s=max(30, int(timeout_s)),
        )
        cleaned = _norm_text(response)
        if not cleaned:
            err = {"report": _norm_text(report.get("relative_path")), "error": "no_claude_response"}
            errors.append(err)
            entries[slug] = {
                "status": "error",
                "generated_at": time.time(),
                "report_path": _norm_text(report.get("relative_path")),
                "provider": "claude",
                "error": _norm_text(err.get("error")),
                "analysis_page": out_path.name,
            }
            continue

        page = [
            "---",
            f"title: Claude Analysis - {_norm_text(report.get('name'))}",
            "tags:",
            "  - observatory",
            "  - reports",
            "  - claude",
            "  - analysis",
            "---",
            "",
            f"# Claude Analysis: `{_norm_text(report.get('name'))}`",
            "",
            f"- Source report: `{_norm_text(report.get('relative_path'))}`",
            f"- Source last modified (UTC): `{_fmt_ts(float(report.get('mtime') or 0.0))}`",
            f"- Analysis generated (UTC): `{_fmt_ts(time.time())}`",
            "",
            "## Analysis",
            "",
            cleaned,
            "",
        ]
        out_path.write_text("\n".join(page), encoding="utf-8")
        written += 1
        entries[slug] = {
            "status": "analyzed",
            "generated_at": time.time(),
            "report_path": _norm_text(report.get("relative_path")),
            "provider": "claude",
            "analysis_page": out_path.name,
        }

    payload = {
        "generated_at": time.time(),
        "entries": entries,
    }
    _save_analysis_index(index_path, payload)
    return {
        "ok": True,
        "attempted": attempted,
        "written": written,
        "errors": errors,
        "analysis_index_path": str(index_path),
        "analysis_dir": str(analysis_dir),
    }

