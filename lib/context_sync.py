"""Session bootstrap sync: write high-confidence learnings to platform targets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import json
import os
import re

from .cognitive_learner import CognitiveLearner, CognitiveInsight
from .diagnostics import log_debug
from .output_adapters import (
    write_claude_code,
    write_cursor,
    write_windsurf,
    write_clawdbot,
    write_openclaw,
    write_codex,
    write_exports,
)
from .project_context import get_project_context, filter_insights_for_context
from .project_profile import load_profile, get_suggested_questions
from .exposure_tracker import record_exposures, infer_latest_session_id, infer_latest_trace_id
from .sync_tracker import get_sync_tracker
from .outcome_checkin import list_checkins
from .queue import _tail_lines


DEFAULT_MIN_RELIABILITY = 0.7
DEFAULT_MIN_VALIDATIONS = 3
DEFAULT_MAX_ITEMS = 12
DEFAULT_MAX_PROMOTED = 6
DEFAULT_HIGH_VALIDATION_OVERRIDE = 50
DEFAULT_MAX_CHIP_HIGHLIGHTS = 4
CHIP_INSIGHTS_DIR = Path.home() / ".spark" / "chip_insights"
TUNEABLES_FILE = Path.home() / ".spark" / "tuneables.json"

CORE_SYNC_ADAPTERS = ("openclaw", "exports")
OPTIONAL_SYNC_ADAPTERS = ("claude_code", "cursor", "windsurf", "clawdbot", "codex")
ALL_SYNC_ADAPTERS = CORE_SYNC_ADAPTERS + OPTIONAL_SYNC_ADAPTERS


@dataclass
class SyncStats:
    targets: Dict[str, str]
    selected: int
    promoted_selected: int
    diagnostics: Optional[Dict] = None


def _parse_adapter_list(raw: Any) -> List[str]:
    if isinstance(raw, str):
        items = [p.strip().lower() for p in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        items = [str(p).strip().lower() for p in raw]
    else:
        return []
    seen = set()
    out: List[str] = []
    for name in items:
        if name in ALL_SYNC_ADAPTERS and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _load_sync_adapter_policy() -> Dict[str, Any]:
    mode = str(os.getenv("SPARK_SYNC_MODE", "") or "").strip().lower()
    env_targets = _parse_adapter_list(os.getenv("SPARK_SYNC_TARGETS", ""))
    env_disabled = set(_parse_adapter_list(os.getenv("SPARK_SYNC_DISABLE_TARGETS", "")))
    cfg: Dict[str, Any] = {}

    try:
        if TUNEABLES_FILE.exists():
            # Accept UTF-8 with BOM (common on Windows).
            data = json.loads(TUNEABLES_FILE.read_text(encoding="utf-8-sig"))
            raw = data.get("sync") or {}
            if isinstance(raw, dict):
                cfg = raw
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        log_debug("context_sync", "failed to load sync config from tuneables.json", e)
        cfg = {}

    cfg_mode = str(cfg.get("mode") or "").strip().lower()
    if not mode:
        mode = cfg_mode or "core"
    if mode not in {"core", "all"}:
        mode = "core"

    enabled = set(ALL_SYNC_ADAPTERS if mode == "all" else CORE_SYNC_ADAPTERS)

    cfg_enabled = _parse_adapter_list(cfg.get("adapters_enabled"))
    if cfg_enabled:
        enabled = set(cfg_enabled)

    cfg_disabled = set(_parse_adapter_list(cfg.get("adapters_disabled")))
    enabled -= cfg_disabled

    if env_targets:
        enabled = set(env_targets)
    elif os.getenv("SPARK_CODEX_CMD") or os.getenv("CODEX_CMD"):
        # If a Codex command is configured and no explicit targets were set,
        # keep Codex in sync automatically (backward-compatible default).
        enabled.add("codex")

    enabled -= env_disabled

    return {
        "mode": mode,
        "enabled": sorted(enabled),
        "disabled": sorted(set(ALL_SYNC_ADAPTERS) - set(enabled)),
    }


def _normalize_text(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s*\(\d+\s*calls?\)", "", t)
    t = re.sub(r"\s*\(\d+\)", "", t)
    t = re.sub(r"\(\s*recovered\s*\d+%?\s*\)", "", t)
    t = re.sub(r"\brecovered\s*\d+%?\b", "recovered", t)
    t = re.sub(r"\s+\d+$", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _is_low_value(insight_text: str) -> bool:
    t = (insight_text or "").lower()
    try:
        from .promoter import is_operational_insight
        if is_operational_insight(t):
            return True
    except Exception:
        pass
    # Skip raw code snippets stored as insights
    if "```" in t or "def " in t[:20] or "class " in t[:20] or "import " in t[:20]:
        return True
    # Skip raw JSON/data fragments
    if t.strip().startswith("{") or t.strip().startswith("["):
        return True
    # Skip quality test markers
    if "quality_test" in t or "QUALITY_TEST" in t:
        return True
    # Skip raw tweet/social data
    if '"tweet_id"' in t or '"username"' in t or '"user_id"' in t:
        return True
    # Skip very long insights (likely raw data, not distilled wisdom)
    if len(t) > 500:
        return True
    # Skip insights that are mostly code (high ratio of special chars)
    special = sum(1 for c in t if c in '{}[]()=<>;:')
    if len(t) > 50 and special / len(t) > 0.15:
        return True
    if "indicates task type" in t:
        return True
    if "heavy " in t and " usage" in t:
        return True
    return False


def _actionability_score(text: str) -> int:
    t = (text or "").lower()
    score = 0
    if "fix:" in t:
        score += 3
    if "avoid" in t or "never" in t:
        score += 2
    if "do " in t or "don't" in t or "should" in t or "must" in t:
        score += 1
    if "use " in t or "prefer" in t or "verify" in t or "check" in t:
        score += 1
    return score


def _build_advisory_payload(
    *,
    insights: List[CognitiveInsight],
    promoted: List[str],
    chip_highlights: List[Dict[str, Any]],
    project_profile: Optional[Dict[str, Any]],
    key_by_id: Dict[int, str],
    effective_reliability,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema_version": "spark_advisory_payload_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "context_sync",
        "counts": {
            "insights": len(insights),
            "promoted": len(promoted),
            "chip_highlights": len(chip_highlights),
        },
        "insights": [],
        "project": {},
    }
    if project_profile:
        payload["project"] = {
            "project_key": project_profile.get("project_key"),
            "phase": project_profile.get("phase"),
            "done": project_profile.get("done"),
        }

    for ins in insights:
        if not ins:
            continue
        payload["insights"].append({
            "insight_key": key_by_id.get(id(ins)),
            "text": ins.insight,
            "category": getattr(ins.category, "value", str(ins.category)),
            "source": getattr(ins, "source", "cognitive"),
            "reliability": round(effective_reliability(ins), 3),
            "confidence": round(ins.confidence, 3),
            "validations": ins.times_validated,
            "advisory_readiness": round(_advisory_readiness_score(ins), 3),
            "advisory_quality": getattr(ins, "advisory_quality", {}) or {},
        })

    if chip_highlights:
        payload["chip_highlights"] = [
            {
                "chip_id": item.get("chip_id"),
                "observer": item.get("observer"),
                "score": item.get("score"),
                "confidence": item.get("confidence"),
                "text": item.get("content"),
            }
            for item in chip_highlights
        ]
    if promoted:
        payload["promoted"] = [{"text": p} for p in promoted[:3]]
    if diagnostics is not None:
        payload["diagnostics"] = {k: v for k, v in diagnostics.items()}
    return payload


def _advisory_readiness_score(insight: CognitiveInsight) -> float:
    """Readiness score for advisory-ready sync ordering."""
    if insight is None:
        return 0.0
    ready = float(getattr(insight, "advisory_readiness", 0.0) or 0.0)
    if ready:
        return max(0.0, min(1.0, ready))
    adv_q = getattr(insight, "advisory_quality", None) or {}
    if isinstance(adv_q, dict):
        return max(0.0, min(1.0, float(adv_q.get("unified_score", 0.0) or 0.0)))
    return 0.0


def _category_weight(category) -> int:
    order = {
        "wisdom": 7,
        "reasoning": 6,
        "meta_learning": 5,
        "communication": 4,
        "user_understanding": 4,
        "self_awareness": 5,
        "context": 2,
        "creativity": 1,
    }
    return int(order.get(getattr(category, "value", str(category)), 1))


def _select_insights(
    *,
    min_reliability: float = DEFAULT_MIN_RELIABILITY,
    min_validations: int = DEFAULT_MIN_VALIDATIONS,
    limit: int = DEFAULT_MAX_ITEMS,
    high_validation_override: int = DEFAULT_HIGH_VALIDATION_OVERRIDE,
    diagnostics: Optional[Dict] = None,
    cognitive: Optional[CognitiveLearner] = None,
    project_context: Optional[Dict] = None,
) -> List[CognitiveInsight]:
    cognitive = cognitive or CognitiveLearner()

    # Pull a larger ranked set to allow filtering without starving the output.
    raw = cognitive.get_ranked_insights(
        min_reliability=min_reliability,
        min_validations=min_validations,
        limit=max(int(limit or 0) * 3, int(limit or 0)),
        resolve_conflicts=True,
    )
    if diagnostics is not None:
        diagnostics.update({
            "min_reliability": min_reliability,
            "min_validations": min_validations,
            "limit": limit,
            "high_validation_override": high_validation_override,
            "raw_ranked": len(raw),
        })

    picked = [i for i in raw if not _is_low_value(i.insight)]
    if diagnostics is not None:
        diagnostics["filtered_low_value"] = max(0, len(raw) - len(picked))

    if high_validation_override and high_validation_override > 0:
        override_candidates = 0
        for ins in cognitive.insights.values():
            if ins.times_validated < high_validation_override:
                continue
            if cognitive.effective_reliability(ins) < min_reliability:
                continue
            if _is_low_value(ins.insight):
                continue
            picked.append(ins)
            override_candidates += 1
        if diagnostics is not None:
            diagnostics["override_candidates"] = override_candidates

    if project_context is not None:
        before = len(picked)
        picked = filter_insights_for_context(picked, project_context)
        if diagnostics is not None:
            diagnostics["filtered_context"] = max(0, before - len(picked))

    picked.sort(
        key=lambda i: (
            _advisory_readiness_score(i),
            _actionability_score(i.insight),
            _category_weight(i.category),
            cognitive.effective_reliability(i),
            i.times_validated,
            i.confidence,
        ),
        reverse=True,
    )

    # De-dupe by normalized insight text
    seen = set()
    deduped: List[CognitiveInsight] = []
    duplicates = 0
    for ins in picked:
        key = _normalize_text(ins.insight)
        if not key or key in seen:
            duplicates += 1
            continue
        seen.add(key)
        deduped.append(ins)
        if len(deduped) >= max(0, int(limit or 0)):
            break

    if diagnostics is not None:
        diagnostics.update({
            "deduped_unique": len(deduped),
            "duplicates_dropped": duplicates,
            "selected": [
                {
                    "category": i.category.value,
                    "insight": i.insight,
                    "reliability": round(cognitive.effective_reliability(i), 3),
                    "advisory_readiness": round(_advisory_readiness_score(i), 3),
                    "validations": i.times_validated,
                    "actionability": _actionability_score(i.insight),
                }
                for i in deduped[: min(5, len(deduped))]
            ],
        })

    return deduped


def _load_promoted_lines(project_dir: Path) -> List[str]:
    lines: List[str] = []
    for name in ("CLAUDE.md", "AGENTS.md", "TOOLS.md", "SOUL.md"):
        path = project_dir / name
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        idx = content.find("## Spark Learnings")
        if idx == -1:
            continue
        tail = content[idx + len("## Spark Learnings") :]
        # Stop at next section header
        next_idx = tail.find("\n## ")
        block = tail if next_idx == -1 else tail[:next_idx]
        for raw in block.splitlines():
            s = raw.strip()
            if s.startswith("- "):
                entry = s[2:].strip()
                if entry and not _is_low_value(entry):
                    lines.append(entry)
    # De-dupe
    seen = set()
    out: List[str] = []
    for s in lines:
        key = _normalize_text(s)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _load_chip_highlights(
    *,
    min_score: float = 0.7,
    min_confidence: float = 0.7,
    limit: int = DEFAULT_MAX_CHIP_HIGHLIGHTS,
) -> List[Dict[str, Any]]:
    """Load recent high-value chip insights for context injection."""
    highlights: List[Dict[str, Any]] = []
    if not CHIP_INSIGHTS_DIR.exists():
        return highlights

    files = sorted(
        CHIP_INSIGHTS_DIR.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )[:8]

    for file_path in files:
        for raw in _tail_lines(file_path, 40):
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            text = str(row.get("content") or "").strip()
            if not text or _is_low_value(text):
                continue
            captured = row.get("captured_data") or {}
            quality = captured.get("quality_score") or {}
            score = float(quality.get("total", 0.0) or 0.0)
            conf = float(row.get("confidence", 0.0) or 0.0)
            if score < min_score or conf < min_confidence:
                continue
            highlights.append(
                {
                    "chip_id": row.get("chip_id") or file_path.stem,
                    "observer": row.get("observer_name") or "observer",
                    "content": text,
                    "score": score,
                    "confidence": conf,
                    "timestamp": row.get("timestamp") or "",
                }
            )

    highlights.sort(key=lambda h: (h["score"], h["confidence"], h["timestamp"]), reverse=True)
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in highlights:
        key = _normalize_text(item["content"][:220])
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= max(0, int(limit)):
            break

    return deduped


def _format_context(
    insights: List[CognitiveInsight],
    promoted: List[str],
    chip_highlights: Optional[List[Dict[str, Any]]] = None,
    project_profile: Optional[Dict[str, Any]] = None,
) -> str:
    lines = [
        "## Spark Bootstrap",
        "Auto-loaded high-confidence learnings from ~/.spark/cognitive_insights.json",
        f"Last updated: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]

    if not insights and not promoted:
        lines.append("No validated insights yet.")
        return "\n".join(lines).strip()

    for ins in insights:
        rel = f"{ins.reliability:.0%}"
        lines.append(
            f"- [{ins.category.value}] {ins.insight} ({rel} reliable, {ins.times_validated} validations)"
        )

    if project_profile:
        done = project_profile.get("done") or ""
        goals = project_profile.get("goals") or []
        milestones = project_profile.get("milestones") or []
        phase = project_profile.get("phase") or ""
        references = project_profile.get("references") or []
        transfers = project_profile.get("transfers") or []
        lines.append("")
        lines.append("## Project Focus")
        if phase:
            lines.append(f"- Phase: {phase}")
        if done:
            lines.append(f"- Done means: {done}")
        if goals:
            for g in goals[:3]:
                lines.append(f"- Goal: {g.get('text') or g}")
        if milestones:
            for m in milestones[:3]:
                status = (m.get("meta") or {}).get("status") or ""
                tag = f" [{status}]" if status else ""
                lines.append(f"- Milestone: {m.get('text')}{tag}")
        if references:
            for r in references[:2]:
                lines.append(f"- Reference: {r.get('text') or r}")
        if transfers:
            for t in transfers[:2]:
                lines.append(f"- Transfer: {t.get('text') or t}")

        questions = get_suggested_questions(project_profile, limit=3)
        if questions:
            lines.append("")
            lines.append("## Project Questions")
            for q in questions:
                lines.append(f"- {q.get('question')}")

        checkins = list_checkins(limit=2)
        if checkins:
            lines.append("")
            lines.append("## Outcome Check-in")
            for item in checkins:
                reason = item.get("reason") or item.get("event") or "check-in"
                lines.append(f"- {reason}")

    if promoted:
        lines.append("")
        lines.append("## Promoted Learnings (Docs)")
        for s in promoted[:DEFAULT_MAX_PROMOTED]:
            lines.append(f"- {s}")

    if chip_highlights:
        lines.append("")
        lines.append("## Chip Intelligence")
        for item in chip_highlights:
            chip = item.get("chip_id") or "chip"
            observer = item.get("observer") or "observer"
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            lines.append(f"- [{chip}/{observer}] {content[:220]}")

    return "\n".join(lines).strip()


def build_compact_context(
    *,
    project_dir: Optional[Path] = None,
    min_reliability: float = DEFAULT_MIN_RELIABILITY,
    min_validations: int = DEFAULT_MIN_VALIDATIONS,
    limit: int = 3,
    high_validation_override: int = DEFAULT_HIGH_VALIDATION_OVERRIDE,
) -> Tuple[str, int]:
    """Build a compact context block for agent prompt injection."""
    cognitive = CognitiveLearner()
    root = project_dir or Path.cwd()
    project_context = None
    try:
        project_context = get_project_context(root)
    except Exception:
        project_context = None

    insights = _select_insights(
        min_reliability=min_reliability,
        min_validations=min_validations,
        limit=limit,
        high_validation_override=high_validation_override,
        cognitive=cognitive,
        project_context=project_context,
    )
    return cognitive.format_for_injection(insights), len(insights)


def sync_context(
    *,
    project_dir: Optional[Path] = None,
    min_reliability: float = DEFAULT_MIN_RELIABILITY,
    min_validations: int = DEFAULT_MIN_VALIDATIONS,
    limit: int = DEFAULT_MAX_ITEMS,
    high_validation_override: int = DEFAULT_HIGH_VALIDATION_OVERRIDE,
    include_promoted: bool = True,
    diagnose: bool = False,
) -> SyncStats:
    cognitive = CognitiveLearner()
    # Prune stale insights (conservative defaults)
    cognitive.prune_stale(max_age_days=180.0, min_effective=0.2)

    root = project_dir or Path.cwd()
    project_context = None
    try:
        project_context = get_project_context(root)
    except Exception:
        project_context = None

    diagnostics: Optional[Dict] = {} if diagnose else None
    insights = _select_insights(
        min_reliability=min_reliability,
        min_validations=min_validations,
        limit=limit,
        high_validation_override=high_validation_override,
        diagnostics=diagnostics,
        cognitive=cognitive,
        project_context=project_context,
    )
    key_by_id = {id(v): k for k, v in cognitive.insights.items()}
    advisory_payload: Optional[Dict[str, Any]] = None
    project_profile_for_payload: Optional[Dict[str, Any]] = None
    try:
        project_profile_for_payload = load_profile(root)
    except Exception:
        project_profile_for_payload = None

    try:
        session_id = infer_latest_session_id()
        trace_id = infer_latest_trace_id(session_id)
        exposures = []
        for ins in insights:
            exposures.append({
                "insight_key": key_by_id.get(id(ins)),
                "category": ins.category.value,
                "text": ins.insight,
            })
        record_exposures("sync_context", exposures, session_id=session_id, trace_id=trace_id)
    except Exception:
        pass

    try:
        profile = load_profile(root)
        p_exposures = []
        if profile.get("done"):
            p_exposures.append({
                "insight_key": f"project:done:{profile.get('project_key')}",
                "category": "project_done",
                "text": profile.get("done"),
            })
        for m in profile.get("milestones") or []:
            p_exposures.append({
                "insight_key": f"project:milestone:{profile.get('project_key')}:{m.get('entry_id')}",
                "category": "project_milestone",
                "text": m.get("text"),
            })
            if p_exposures:
                session_id = infer_latest_session_id()
                trace_id = infer_latest_trace_id(session_id)
                record_exposures("sync_context:project", p_exposures, session_id=session_id, trace_id=trace_id)
    except Exception:
        pass

    promoted = _load_promoted_lines(root) if include_promoted else []
    chip_highlights = _load_chip_highlights()
    if diagnostics is not None:
        diagnostics["chip_highlights"] = len(chip_highlights)
    # De-dupe promoted vs selected insights
    seen = {_normalize_text(i.insight) for i in insights}
    promoted = [p for p in promoted if _normalize_text(p) not in seen]

    profile = None
    profile = project_profile_for_payload

    advisory_payload = _build_advisory_payload(
        insights=insights,
        promoted=promoted,
        chip_highlights=chip_highlights,
        project_profile=project_profile_for_payload,
        key_by_id=key_by_id,
        effective_reliability=cognitive.effective_reliability,
        diagnostics=diagnostics,
    )
    context = _format_context(
        insights,
        promoted,
        chip_highlights=chip_highlights,
        project_profile=profile,
    )
    adapter_policy = _load_sync_adapter_policy()
    enabled_adapters = set(adapter_policy.get("enabled") or [])
    if diagnostics is not None:
        diagnostics["sync_policy"] = adapter_policy

    targets: Dict[str, str] = {}

    if "claude_code" in enabled_adapters:
        try:
            write_claude_code(context, project_dir=root, advisory_payload=advisory_payload)
            targets["claude_code"] = "written"
        except Exception:
            targets["claude_code"] = "error"
    else:
        targets["claude_code"] = "disabled"

    if "cursor" in enabled_adapters:
        try:
            write_cursor(context, project_dir=root, advisory_payload=advisory_payload)
            targets["cursor"] = "written"
        except Exception:
            targets["cursor"] = "error"
    else:
        targets["cursor"] = "disabled"

    if "windsurf" in enabled_adapters:
        try:
            write_windsurf(context, project_dir=root, advisory_payload=advisory_payload)
            targets["windsurf"] = "written"
        except Exception:
            targets["windsurf"] = "error"
    else:
        targets["windsurf"] = "disabled"

    if "clawdbot" in enabled_adapters:
        try:
            ok = write_clawdbot(context, advisory_payload=advisory_payload)
            targets["clawdbot"] = "written" if ok else "skipped"
        except Exception:
            targets["clawdbot"] = "error"
    else:
        targets["clawdbot"] = "disabled"

    if "openclaw" in enabled_adapters:
        try:
            ok = write_openclaw(context, advisory_payload=advisory_payload)
            targets["openclaw"] = "written" if ok else "skipped"
        except Exception:
            targets["openclaw"] = "error"
    else:
        targets["openclaw"] = "disabled"

    if "codex" in enabled_adapters:
        try:
            ok = write_codex(context, project_dir=root, advisory_payload=advisory_payload)
            targets["codex"] = "written" if ok else "skipped"
        except Exception:
            targets["codex"] = "error"
    else:
        targets["codex"] = "disabled"

    if "exports" in enabled_adapters:
        try:
            write_exports(context, advisory_payload=advisory_payload)
            targets["exports"] = "written"
        except Exception:
            targets["exports"] = "error"
    else:
        targets["exports"] = "disabled"

    # Record sync stats for dashboard tracking
    try:
        tracker = get_sync_tracker()
        tracker.record_full_sync(targets, items_per_adapter=len(insights))
    except Exception:
        pass

    return SyncStats(
        targets=targets,
        selected=len(insights),
        promoted_selected=len(promoted),
        diagnostics=diagnostics,
    )


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Sync Spark bootstrap context to platforms")
    ap.add_argument("--project", "-p", default=None, help="Project root for file-based outputs")
    ap.add_argument("--min-reliability", type=float, default=DEFAULT_MIN_RELIABILITY)
    ap.add_argument("--min-validations", type=int, default=DEFAULT_MIN_VALIDATIONS)
    ap.add_argument("--limit", type=int, default=DEFAULT_MAX_ITEMS)
    ap.add_argument("--no-promoted", action="store_true", help="Skip promoted learnings from docs")
    args = ap.parse_args(argv)

    project_dir = Path(args.project).expanduser() if args.project else None
    stats = sync_context(
        project_dir=project_dir,
        min_reliability=args.min_reliability,
        min_validations=args.min_validations,
        limit=args.limit,
        include_promoted=(not args.no_promoted),
    )
    print(json.dumps({
        "selected": stats.selected,
        "promoted_selected": stats.promoted_selected,
        "targets": stats.targets,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
