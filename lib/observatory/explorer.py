"""Generate browsable detail pages for individual items in each data store.

Generates:
  explore/
    cognitive/     _index.md + per-insight pages
    distillations/ _index.md + per-distillation pages
    episodes/      _index.md + per-episode pages (with steps)
    advisory/      _index.md (source breakdown + recent advice)
    helpfulness/   _index.md (calibrated helpfulness progress tracking)
    promotions/    _index.md + per-batch pages
    verdicts/      _index.md + per-verdict pages
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ObservatoryConfig, spark_dir
from .linker import flow_link, fmt_num, fmt_ts
from .readers import _count_jsonl, _load_json, _tail_jsonl

_SD = spark_dir()


_MOJIBAKE_REPLACEMENTS = {
    "\u00e2\u20ac\u201d": "-",
    "\u00e2\u20ac\u201c": "-",
    "\u00e2\u20ac\u02dc": "'",
    "\u00e2\u20ac\u2122": "'",
    "\u00e2\u20ac\u0153": '"',
    "\u00e2\u20ac\u009d": '"',
    "\u00e2\u20ac\u00a6": "...",
    "\u00c2 ": " ",
    "\u00c2": "",
}

_UNICODE_PUNCT_TRANSLATE = str.maketrans({
    "\u2014": "-",
    "\u2013": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
})


def _parse_ts(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return float(text)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def _clean_text_preview(value: Any, max_len: int = 200) -> str:
    text = str(value or "").replace("\n", " ").replace("\r", " ").strip()
    if not text:
        return ""
    # Attempt to repair classic UTF-8/latin-1 mojibake first.
    if any(tok in text for tok in ("\u00c3", "\u00c2", "\u00e2")):
        try:
            repaired = text.encode("latin-1").decode("utf-8")
            if repaired:
                text = repaired
        except Exception:
            pass
    for bad, good in _MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(bad, good)
    text = text.translate(_UNICODE_PUNCT_TRANSLATE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _collapse_recent_advice(entries: list[dict[str, Any]], max_items: int = 50) -> tuple[list[dict[str, Any]], int]:
    collapsed: dict[str, dict[str, Any]] = {}
    considered = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        texts = entry.get("advice_texts") or []
        if not isinstance(texts, list) or not texts:
            continue
        sources = entry.get("sources") or []
        if not isinstance(sources, list):
            sources = []
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for idx, raw_text in enumerate(texts[:5]):
            txt = _clean_text_preview(raw_text, max_len=200)
            if not txt:
                continue
            src = _clean_text_preview(sources[idx] if idx < len(sources) else "?", max_len=40) or "?"
            pair = (src, txt)
            if pair in seen:
                continue
            seen.add(pair)
            pairs.append(pair)
        if not pairs:
            continue
        tool = _clean_text_preview(entry.get("tool", "?"), max_len=40) or "?"
        ts_raw = entry.get("timestamp")
        ts = _parse_ts(ts_raw if ts_raw is not None else entry.get("ts"))
        ts_text = str(ts_raw if ts_raw is not None else entry.get("ts") or "?")[:19]
        signature = json.dumps({"tool": tool.lower(), "pairs": pairs}, ensure_ascii=True, sort_keys=True)
        considered += 1
        agg = collapsed.get(signature)
        if agg is None:
            collapsed[signature] = {
                "tool": tool,
                "pairs": pairs,
                "ts": ts,
                "ts_text": ts_text,
                "count": 1,
            }
            continue
        agg["count"] = int(agg.get("count", 0)) + 1
        if ts >= float(agg.get("ts", 0.0)):
            agg["ts"] = ts
            agg["ts_text"] = ts_text
            agg["tool"] = tool
            agg["pairs"] = pairs

    rows = sorted(
        collapsed.values(),
        key=lambda r: (float(r.get("ts", 0.0)), int(r.get("count", 0))),
        reverse=True,
    )[:max_items]
    duplicates_collapsed = max(0, considered - len(rows))
    return rows, duplicates_collapsed


def _slug(text: str, max_len: int = 60) -> str:
    """Convert text to a safe filename slug."""
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9_\-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:max_len] if s else "unnamed"


def _frontmatter(meta: dict) -> str:
    """Generate YAML frontmatter block."""
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, str):
            # Escape quotes in strings
            v_safe = v.replace('"', '\\"')
            lines.append(f'{k}: "{v_safe}"')
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k}: {v}")
        elif isinstance(v, list):
            lines.append(f"{k}: {json.dumps(v)}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---\n")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
#  COGNITIVE INSIGHTS
# ═══════════════════════════════════════════════════════════════════════

def _export_cognitive(explore_dir: Path, limit: int) -> int:
    """Export cognitive insights as individual pages + index."""
    out = explore_dir / "cognitive"
    out.mkdir(parents=True, exist_ok=True)
    ci = _load_json(_SD / "cognitive_insights.json") or {}
    if not isinstance(ci, dict):
        return 0

    # Sort by reliability * validations (descending)
    items = []
    for key, val in ci.items():
        if not isinstance(val, dict):
            continue
        items.append((key, val))
    items.sort(key=lambda x: (-x[1].get("reliability", 0), -x[1].get("times_validated", 0)))
    items = items[:limit]

    # Generate detail pages
    for key, val in items:
        slug = _slug(key)
        insight = val.get("insight", "")
        meta = {
            "type": "spark-cognitive-insight",
            "key": key,
            "category": val.get("category", "?"),
            "reliability": round(val.get("reliability", 0), 3),
            "validations": val.get("times_validated", 0),
            "contradictions": val.get("times_contradicted", 0),
            "confidence": round(val.get("confidence", 0), 3),
            "promoted": val.get("promoted", False),
            "promoted_to": val.get("promoted_to") or "none",
            "source": val.get("source", "?"),
            "created_at": val.get("created_at", "?"),
        }
        body = [_frontmatter(meta)]
        body.append(f"# {key[:80]}\n")
        body.append(f"> Back to [[_index|Cognitive Index]] | {flow_link()}\n")
        body.append(f"## Insight\n\n{insight}\n")
        body.append("## Metadata\n")
        body.append("| Field | Value |")
        body.append("|-------|-------|")
        body.append(f"| Category | {val.get('category', '?')} |")
        body.append(f"| Reliability | {val.get('reliability', 0):.0%} |")
        body.append(f"| Validations | {val.get('times_validated', 0)} |")
        body.append(f"| Contradictions | {val.get('times_contradicted', 0)} |")
        body.append(f"| Confidence | {val.get('confidence', 0):.3f} |")
        body.append(f"| Source | {val.get('source', '?')} |")
        body.append(f"| Promoted | {'yes' if val.get('promoted') else 'no'} |")
        if val.get("promoted_to"):
            body.append(f"| Promoted to | {val['promoted_to']} |")
        body.append(f"| Advisory readiness | {val.get('advisory_readiness', 0):.3f} |")
        body.append(f"| Created | {val.get('created_at', '?')} |")
        body.append(f"| Last validated | {val.get('last_validated_at', 'never')} |")
        body.append("")

        # Evidence
        evidence = val.get("evidence", [])
        if evidence:
            body.append(f"## Evidence ({len(evidence)} items)\n")
            for i, e in enumerate(evidence[:10], 1):
                e_text = str(e)[:200].replace("\n", " ").replace("\r", "")
                body.append(f"{i}. `{e_text}`")
            if len(evidence) > 10:
                body.append(f"\n*... and {len(evidence) - 10} more*")
            body.append("")

        # Counter-examples
        counters = val.get("counter_examples", [])
        if counters:
            body.append(f"## Counter-Examples ({len(counters)})\n")
            for i, c in enumerate(counters[:5], 1):
                body.append(f"{i}. `{str(c)[:200]}`")
            body.append("")

        (out / f"{slug}.md").write_text("\n".join(body), encoding="utf-8")

    # Generate index
    index = [_frontmatter({
        "type": "spark-cognitive-index",
        "total": len(ci),
        "exported": len(items),
        "limit": limit,
    })]
    index.append(f"# Cognitive Insights ({len(items)}/{len(ci)})\n")
    index.append(f"> {flow_link()} | [[../stages/06-cognitive-learner|Stage 6: Cognitive Learner]]\n")
    if len(items) < len(ci):
        index.append(f"*Showing top {len(items)} by reliability. Increase `explore_cognitive_max` in tuneables to see more.*\n")

    index.append("| Key | Category | Reliability | Validations | Promoted | Link |")
    index.append("|-----|----------|-------------|-------------|----------|------|")
    for key, val in items:
        slug = _slug(key)
        rel = f"{val.get('reliability', 0):.0%}"
        vld = val.get("times_validated", 0)
        promoted = "yes" if val.get("promoted") else "—"
        cat = val.get("category", "?")
        index.append(f"| `{key[:50]}` | {cat} | {rel} | {vld} | {promoted} | [[{slug}]] |")
    index.append("")
    (out / "_index.md").write_text("\n".join(index), encoding="utf-8")
    return len(items) + 1  # detail pages + index


# ═══════════════════════════════════════════════════════════════════════
#  EIDOS DISTILLATIONS
# ═══════════════════════════════════════════════════════════════════════

def _export_distillations(explore_dir: Path, limit: int) -> int:
    """Export EIDOS distillations as individual pages + index."""
    out = explore_dir / "distillations"
    out.mkdir(parents=True, exist_ok=True)
    db_path = _SD / "eidos.db"
    if not db_path.exists():
        (out / "_index.md").write_text("# Distillations\n\neidos.db not found.\n", encoding="utf-8")
        return 1

    try:
        conn = sqlite3.connect(str(db_path), timeout=2)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM distillations")
        total = cur.fetchone()[0]

        cur.execute("""
            SELECT * FROM distillations
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    except Exception as e:
        (out / "_index.md").write_text(f"# Distillations\n\nError reading eidos.db: {e}\n", encoding="utf-8")
        return 1

    for row in rows:
        did = row["distillation_id"]
        slug = _slug(did)
        meta = {
            "type": "spark-eidos-distillation",
            "distillation_id": did,
            "distillation_type": row.get("type", "?"),
            "confidence": round(row.get("confidence", 0), 3),
            "validation_count": row.get("validation_count", 0),
            "contradiction_count": row.get("contradiction_count", 0),
            "times_retrieved": row.get("times_retrieved", 0),
            "times_used": row.get("times_used", 0),
            "times_helped": row.get("times_helped", 0),
            "created_at": fmt_ts(row.get("created_at")),
        }
        body = [_frontmatter(meta)]
        body.append(f"# Distillation: {did[:20]}\n")
        body.append(f"> Back to [[_index|Distillations Index]] | {flow_link()} | [[../stages/07-eidos|Stage 7: EIDOS]]\n")
        body.append(f"**Type:** {row.get('type', '?')} | **Confidence:** {row.get('confidence', 0):.2f}\n")
        body.append(f"## Statement\n\n{row.get('statement', '(empty)')}\n")
        body.append("## Metrics\n")
        body.append("| Field | Value |")
        body.append("|-------|-------|")
        body.append(f"| Validated | {row.get('validation_count', 0)} times |")
        body.append(f"| Contradicted | {row.get('contradiction_count', 0)} times |")
        body.append(f"| Retrieved | {row.get('times_retrieved', 0)} times |")
        body.append(f"| Used | {row.get('times_used', 0)} times |")
        body.append(f"| Helped | {row.get('times_helped', 0)} times |")
        body.append(f"| Created | {fmt_ts(row.get('created_at'))} |")
        revalidate = row.get("revalidate_by")
        if revalidate:
            body.append(f"| Revalidate by | {fmt_ts(revalidate)} |")
        body.append("")

        # Domains & triggers
        for field, label in [("domains", "Domains"), ("triggers", "Triggers"), ("anti_triggers", "Anti-Triggers")]:
            raw = row.get(field)
            if raw:
                try:
                    items = json.loads(raw) if isinstance(raw, str) else raw
                    if items:
                        body.append(f"## {label}\n")
                        for item in items:
                            body.append(f"- `{item}`")
                        body.append("")
                except Exception:
                    pass

        # Source steps
        raw_steps = row.get("source_steps")
        if raw_steps:
            try:
                step_ids = json.loads(raw_steps) if isinstance(raw_steps, str) else raw_steps
                if step_ids:
                    body.append(f"## Source Steps ({len(step_ids)})\n")
                    for sid in step_ids[:10]:
                        body.append(f"- `{sid}`")
                    body.append("")
            except Exception:
                pass

        (out / f"{slug}.md").write_text("\n".join(body), encoding="utf-8")

    # Index
    index = [_frontmatter({
        "type": "spark-distillations-index",
        "total": total,
        "exported": len(rows),
        "limit": limit,
    })]
    index.append(f"# EIDOS Distillations ({len(rows)}/{total})\n")
    index.append(f"> {flow_link()} | [[../stages/07-eidos|Stage 7: EIDOS]]\n")
    if len(rows) < total:
        index.append(f"*Showing most recent {len(rows)}. Increase `explore_distillations_max` in tuneables to see more.*\n")

    index.append("| ID | Type | Statement | Confidence | Validated | Retrieved | Link |")
    index.append("|----|------|-----------|------------|-----------|-----------|------|")
    for row in rows:
        did = row["distillation_id"]
        slug = _slug(did)
        stmt = (row.get("statement", "")[:80] + "...") if len(row.get("statement", "")) > 80 else row.get("statement", "")
        stmt = stmt.replace("|", "/").replace("\n", " ")
        index.append(f"| `{did[:12]}` | {row.get('type','?')} | {stmt} | {row.get('confidence',0):.2f} | {row.get('validation_count',0)} | {row.get('times_retrieved',0)} | [[{slug}]] |")
    index.append("")
    (out / "_index.md").write_text("\n".join(index), encoding="utf-8")
    return len(rows) + 1


# ═══════════════════════════════════════════════════════════════════════
#  EIDOS EPISODES
# ═══════════════════════════════════════════════════════════════════════

def _export_episodes(explore_dir: Path, limit: int) -> int:
    """Export EIDOS episodes with their steps as individual pages + index."""
    out = explore_dir / "episodes"
    out.mkdir(parents=True, exist_ok=True)
    db_path = _SD / "eidos.db"
    if not db_path.exists():
        (out / "_index.md").write_text("# Episodes\n\neidos.db not found.\n", encoding="utf-8")
        return 1

    try:
        conn = sqlite3.connect(str(db_path), timeout=2)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM episodes")
        total = cur.fetchone()[0]

        cur.execute("""
            SELECT * FROM episodes
            ORDER BY start_ts DESC
            LIMIT ?
        """, (limit,))
        episodes = [dict(r) for r in cur.fetchall()]

        # Prefetch steps for these episodes
        if episodes:
            eids = [e["episode_id"] for e in episodes]
            cur.execute("DROP TABLE IF EXISTS _episode_filter")
            cur.execute("CREATE TEMP TABLE _episode_filter (episode_id TEXT PRIMARY KEY)")
            cur.executemany(
                "INSERT INTO _episode_filter(episode_id) VALUES (?)",
                [(eid,) for eid in eids],
            )
            cur.execute("""
                SELECT * FROM steps
                WHERE episode_id IN (SELECT episode_id FROM _episode_filter)
                ORDER BY created_at ASC
            """)
            all_steps = [dict(r) for r in cur.fetchall()]
        else:
            all_steps = []
        conn.close()
    except Exception as e:
        (out / "_index.md").write_text(f"# Episodes\n\nError reading eidos.db: {e}\n", encoding="utf-8")
        return 1

    # Group steps by episode
    steps_by_ep: dict[str, list[dict]] = {}
    for s in all_steps:
        eid = s.get("episode_id", "")
        steps_by_ep.setdefault(eid, []).append(s)

    for ep in episodes:
        eid = ep["episode_id"]
        slug = _slug(eid)
        goal = ep.get("goal", "")[:120]
        steps = steps_by_ep.get(eid, [])

        meta = {
            "type": "spark-eidos-episode",
            "episode_id": eid,
            "outcome": ep.get("outcome", "?"),
            "phase": ep.get("phase", "?"),
            "step_count": ep.get("step_count", 0),
            "started": fmt_ts(ep.get("start_ts")),
            "ended": fmt_ts(ep.get("end_ts")),
        }
        body = [_frontmatter(meta)]
        body.append(f"# Episode: {eid[:16]}\n")
        body.append(f"> Back to [[_index|Episodes Index]] | {flow_link()} | [[../stages/07-eidos|Stage 7: EIDOS]]\n")

        body.append(f"## Goal\n\n{goal}\n")
        body.append("## Summary\n")
        body.append("| Field | Value |")
        body.append("|-------|-------|")
        body.append(f"| Outcome | **{ep.get('outcome', '?')}** |")
        body.append(f"| Phase | {ep.get('phase', '?')} |")
        body.append(f"| Steps | {ep.get('step_count', 0)} |")
        body.append(f"| Started | {fmt_ts(ep.get('start_ts'))} |")
        body.append(f"| Ended | {fmt_ts(ep.get('end_ts'))} |")
        if ep.get("final_evaluation"):
            body.append(f"| Evaluation | {ep['final_evaluation'][:100]} |")
        body.append("")

        # Steps
        if steps:
            body.append(f"## Steps ({len(steps)})\n")
            for i, s in enumerate(steps, 1):
                eval_icon = {"success": "pass", "failure": "FAIL", "unknown": "?"}.get(s.get("evaluation", ""), "?")
                body.append(f"### Step {i}: {s.get('intent', '?')[:80]}\n")
                body.append(f"- **Decision:** {s.get('decision', '?')[:120]}")
                body.append(f"- **Action:** {s.get('action_type', '?')}")
                if s.get("prediction"):
                    body.append(f"- **Prediction:** {s['prediction'][:120]}")
                body.append(f"- **Evaluation:** {eval_icon}")
                if s.get("surprise_level", 0) > 0.1:
                    body.append(f"- **Surprise:** {s['surprise_level']:.2f}")
                if s.get("lesson"):
                    body.append(f"- **Lesson:** {s['lesson'][:150]}")
                body.append("")
        else:
            body.append("## Steps\n\nNo steps recorded for this episode.\n")

        (out / f"{slug}.md").write_text("\n".join(body), encoding="utf-8")

    # Index
    index = [_frontmatter({
        "type": "spark-episodes-index",
        "total": total,
        "exported": len(episodes),
        "limit": limit,
    })]
    index.append(f"# EIDOS Episodes ({len(episodes)}/{total})\n")
    index.append(f"> {flow_link()} | [[../stages/07-eidos|Stage 7: EIDOS]]\n")
    if len(episodes) < total:
        index.append(f"*Showing most recent {len(episodes)}. Increase `explore_episodes_max` in tuneables to see more.*\n")

    index.append("| ID | Goal | Outcome | Phase | Steps | Started | Link |")
    index.append("|----|------|---------|-------|-------|---------|------|")
    for ep in episodes:
        eid = ep["episode_id"]
        slug = _slug(eid)
        goal = ep.get("goal", "")[:60].replace("|", "/").replace("\n", " ")
        index.append(f"| `{eid[:12]}` | {goal} | **{ep.get('outcome','?')}** | {ep.get('phase','?')} | {ep.get('step_count',0)} | {fmt_ts(ep.get('start_ts'))} | [[{slug}]] |")
    index.append("")
    (out / "_index.md").write_text("\n".join(index), encoding="utf-8")
    return len(episodes) + 1


# ═══════════════════════════════════════════════════════════════════════
#  META-RALPH VERDICTS
# ═══════════════════════════════════════════════════════════════════════

def _export_verdicts(explore_dir: Path, limit: int) -> int:
    """Export recent Meta-Ralph roast verdicts as a browsable index."""
    out = explore_dir / "verdicts"
    out.mkdir(parents=True, exist_ok=True)

    rh = _load_json(_SD / "meta_ralph" / "roast_history.json") or {}
    history = rh.get("history", []) if isinstance(rh, dict) else []
    total = len(history)
    if isinstance(rh, dict):
        try:
            total = max(total, int(rh.get("total_roasted", total) or total))
        except Exception:
            total = total
    recent = history[-limit:] if history else []

    # Verdict distribution
    verdicts: dict[str, int] = {}
    for entry in history:
        v = entry.get("result", {}).get("verdict", "unknown")
        verdicts[v] = verdicts.get(v, 0) + 1

    # Generate per-verdict detail pages grouped by batch (same timestamp)
    pages_written = 0
    for i, entry in enumerate(recent):
        idx = total - limit + i if total > limit else i
        slug = f"verdict_{idx:05d}"
        result = entry.get("result", {})
        score = result.get("score", {})

        meta = {
            "type": "spark-metaralph-verdict",
            "verdict": result.get("verdict", "?"),
            "total_score": score.get("total", 0) if isinstance(score, dict) else 0,
            "source": entry.get("source", "?"),
            "timestamp": entry.get("timestamp", "?"),
        }
        body = [_frontmatter(meta)]
        body.append(f"# Verdict #{idx}: {result.get('verdict', '?')}\n")
        body.append(f"> Back to [[_index|Verdicts Index]] | {flow_link()} | [[../stages/05-meta-ralph|Stage 5: Meta-Ralph]]\n")

        # Original text (truncated for readability)
        original = result.get("original", "")
        if original:
            display = original[:500]
            if len(original) > 500:
                display += f"\n\n*... ({len(original)} chars total)*"
            body.append(f"## Input Text\n\n{display}\n")

        # Score breakdown
        if isinstance(score, dict):
            body.append("## Score Breakdown\n")
            body.append("| Dimension | Score |")
            body.append("|-----------|-------|")
            for dim in ["actionability", "novelty", "reasoning", "specificity", "outcome_linked", "ethics"]:
                body.append(f"| {dim} | {score.get(dim, 0)} |")
            body.append(f"| **Total** | **{score.get('total', 0)}** |")
            body.append(f"| Verdict | **{score.get('verdict', result.get('verdict', '?'))}** |")
            body.append("")

        # Issues
        issues = result.get("issues_found", [])
        if issues:
            body.append("## Issues Found\n")
            for issue in issues:
                body.append(f"- {issue}")
            body.append("")

        # Refinement
        refined = result.get("refined_version")
        if refined:
            body.append(f"## Refined Version\n\n{refined[:300]}\n")

        (out / f"{slug}.md").write_text("\n".join(body), encoding="utf-8")
        pages_written += 1

    # Index
    index = [_frontmatter({
        "type": "spark-verdicts-index",
        "total": total,
        "exported": len(recent),
        "limit": limit,
    })]
    index.append(f"# Meta-Ralph Verdicts ({len(recent)}/{total})\n")
    index.append(f"> {flow_link()} | [[../stages/05-meta-ralph|Stage 5: Meta-Ralph]]\n")
    if len(recent) < total:
        index.append(f"*Showing most recent {len(recent)}. Increase `explore_verdicts_max` in tuneables to see more.*\n")

    # Distribution
    if verdicts:
        index.append("## Verdict Distribution (all time)\n")
        index.append("| Verdict | Count | % |")
        index.append("|---------|-------|---|")
        for v, count in sorted(verdicts.items(), key=lambda x: -x[1]):
            pct = round(count / max(total, 1) * 100, 1)
            index.append(f"| {v} | {count} | {pct}% |")
        index.append("")

    # Recent table
    index.append("## Recent Verdicts\n")
    index.append("| # | Time | Source | Verdict | Score | Link |")
    index.append("|---|------|--------|---------|-------|------|")
    for i, entry in enumerate(recent):
        idx = total - limit + i if total > limit else i
        slug = f"verdict_{idx:05d}"
        result = entry.get("result", {})
        score = result.get("score", {})
        total_score = score.get("total", 0) if isinstance(score, dict) else 0
        ts = entry.get("timestamp", "?")[:19]
        index.append(f"| {idx} | {ts} | {entry.get('source','?')} | **{result.get('verdict','?')}** | {total_score} | [[{slug}]] |")
    index.append("")
    (out / "_index.md").write_text("\n".join(index), encoding="utf-8")
    return pages_written + 1


# ═══════════════════════════════════════════════════════════════════════
#  PROMOTIONS
# ═══════════════════════════════════════════════════════════════════════

def _export_promotions(explore_dir: Path, limit: int) -> int:
    """Export promotion log as a browsable index (no individual pages — log entries are small)."""
    out = explore_dir / "promotions"
    out.mkdir(parents=True, exist_ok=True)
    path = _SD / "promotion_log.jsonl"
    total = _count_jsonl(path)
    recent = _tail_jsonl(path, limit)

    # Target + result distribution from recent
    targets: dict[str, int] = {}
    results: dict[str, int] = {}
    for entry in recent:
        t = entry.get("target", "?")
        r = entry.get("result", "?")
        targets[t] = targets.get(t, 0) + 1
        results[r] = results.get(r, 0) + 1

    index = [_frontmatter({
        "type": "spark-promotions-index",
        "total": total,
        "exported": len(recent),
        "limit": limit,
    })]
    index.append(f"# Promotion Log ({len(recent)}/{total})\n")
    index.append(f"> {flow_link()} | [[../stages/09-promotion|Stage 9: Promotion]]\n")
    if len(recent) < total:
        index.append(f"*Showing most recent {len(recent)}. Increase `explore_promotions_max` in tuneables to see more.*\n")

    if targets:
        index.append("## Target Distribution (recent)\n")
        index.append("| Target | Count |")
        index.append("|--------|-------|")
        for t, c in sorted(targets.items(), key=lambda x: -x[1]):
            index.append(f"| {t} | {c} |")
        index.append("")

    if results:
        index.append("## Result Distribution (recent)\n")
        index.append("| Result | Count |")
        index.append("|--------|-------|")
        for r, c in sorted(results.items(), key=lambda x: -x[1]):
            index.append(f"| {r} | {c} |")
        index.append("")

    index.append("## Recent Activity\n")
    index.append("| Time | Key | Target | Result | Reason |")
    index.append("|------|-----|--------|--------|--------|")
    for entry in reversed(recent):  # Most recent first
        ts = entry.get("ts", "?")[:19]
        key = entry.get("key", "?")[:50]
        target = entry.get("target", "?")
        result = entry.get("result", "?")
        reason = entry.get("reason", "")[:40].replace("|", "/")
        index.append(f"| {ts} | `{key}` | {target} | {result} | {reason} |")
    index.append("")
    (out / "_index.md").write_text("\n".join(index), encoding="utf-8")
    return 1


# ═══════════════════════════════════════════════════════════════════════
#  ADVISORY SOURCE EFFECTIVENESS
# ═══════════════════════════════════════════════════════════════════════

def _export_advisory(explore_dir: Path, advice_limit: int) -> int:
    """Export advisory effectiveness breakdown + recent advice as a browsable index."""
    out = explore_dir / "advisory"
    out.mkdir(parents=True, exist_ok=True)

    eff = _load_json(_SD / "advisor" / "effectiveness.json") or {}
    metrics = _load_json(_SD / "advisor" / "metrics.json") or {}
    helpfulness_summary = _load_json(_SD / "advisor" / "helpfulness_summary.json") or {}
    recent = _tail_jsonl(_SD / "advisor" / "advice_log.jsonl", advice_limit)

    total_given = eff.get("total_advice_given", 0)
    total_followed = eff.get("total_followed", 0)
    total_helpful = eff.get("total_helpful", 0)

    index = [_frontmatter({
        "type": "spark-advisory-index",
        "total_given": total_given,
        "total_followed": total_followed,
        "total_helpful": total_helpful,
        "followed_rate": round(total_followed / max(total_given, 1) * 100, 1),
    })]
    index.append("# Advisory Effectiveness\n")
    index.append(f"> {flow_link()} | [[../stages/08-advisory|Stage 8: Advisory]]\n")
    index.append("> For calibrated event-level progress tracking: [[../helpfulness/_index|Helpfulness Calibration]].\n")

    index.append("## Overall\n")
    index.append("| Metric | Value |")
    index.append("|--------|-------|")
    index.append(f"| Total advice given | {fmt_num(total_given)} |")
    index.append(f"| Followed | {fmt_num(total_followed)} ({total_followed/max(total_given,1)*100:.1f}%) |")
    index.append(f"| Helpful | {fmt_num(total_helpful)} |")
    cognitive_helpful_rate = metrics.get('cognitive_helpful_rate')
    try:
        cognitive_helpful_rate = float(cognitive_helpful_rate) if cognitive_helpful_rate is not None else 0.0
    except (TypeError, ValueError):
        cognitive_helpful_rate = 0.0
    index.append(f"| Cognitive helpful rate | {cognitive_helpful_rate:.1%} |")
    index.append("")

    if isinstance(helpfulness_summary, dict) and helpfulness_summary:
        labels = helpfulness_summary.get("labels", {}) if isinstance(helpfulness_summary.get("labels"), dict) else {}
        index.append("## Calibrated Helpfulness (Watcher)\n")
        index.append("| Metric | Value |")
        index.append("|--------|-------|")
        index.append(f"| Total events | {fmt_num(helpfulness_summary.get('total_events', 0))} |")
        index.append(f"| Known helpfulness events | {fmt_num(helpfulness_summary.get('known_helpfulness_total', 0))} |")
        index.append(f"| Helpful rate | {helpfulness_summary.get('helpful_rate_pct', 0.0)}% |")
        index.append(f"| Unknown rate | {helpfulness_summary.get('unknown_rate_pct', 0.0)}% |")
        index.append(f"| Conflict rate | {helpfulness_summary.get('conflict_rate_pct', 0.0)}% |")
        index.append(f"| LLM review queue | {fmt_num(helpfulness_summary.get('llm_review_queue_count', 0))} |")
        index.append(f"| LLM review applied | {fmt_num(helpfulness_summary.get('llm_review_applied_count', 0))} |")
        index.append("")
        if labels:
            index.append("### Label Distribution\n")
            index.append("| Label | Count |")
            index.append("|-------|-------|")
            for label, count in sorted(labels.items(), key=lambda x: -x[1]):
                index.append(f"| {label} | {fmt_num(count)} |")
            index.append("")

    by_source = eff.get("by_source", {})
    if by_source:
        index.append("## Source Effectiveness\n")
        index.append("| Source | Total | Helpful | Rate |")
        index.append("|--------|-------|---------|------|")
        for src, stats in sorted(by_source.items(), key=lambda x: -x[1].get("total", 0)):
            t = stats.get("total", 0)
            h = stats.get("helpful", 0)
            rate = f"{h/max(t,1)*100:.1f}%" if t > 0 else "-"
            index.append(f"| **{src}** | {fmt_num(t)} | {fmt_num(h)} | {rate} |")
        index.append("")

    # Recent advice entries
    advice_entries = [r for r in recent if "advice_texts" in r]
    collapsed_entries, collapsed_dupes = _collapse_recent_advice(advice_entries, max_items=50)
    if collapsed_entries:
        header = f"## Recent Advice ({len(collapsed_entries)} entries)"
        if collapsed_dupes > 0:
            header += f" - {collapsed_dupes} duplicates collapsed"
        index.append(header + "\n")
        for i, entry in enumerate(collapsed_entries, 1):
            tool = entry.get("tool", "?")
            ts = str(entry.get("ts_text", "?"))[:19]
            repeat_note = f", repeated {int(entry.get('count', 1))}x" if int(entry.get("count", 1)) > 1 else ""
            index.append(f"### {i}. {tool} ({ts}{repeat_note})\n")
            for src, txt in (entry.get("pairs") or []):
                index.append(f"- **[{src}]** {txt}")
            index.append("")

    (out / "_index.md").write_text("\n".join(index), encoding="utf-8")
    return 1


# ═══════════════════════════════════════════════════════════════════════
#  RETRIEVAL ROUTING DECISIONS
# ═══════════════════════════════════════════════════════════════════════

def _export_routing(explore_dir: Path, limit: int) -> int:
    """Export retrieval routing decisions as a browsable index (no detail pages)."""
    out = explore_dir / "routing"
    out.mkdir(parents=True, exist_ok=True)
    path = _SD / "advisor" / "retrieval_router.jsonl"
    total = _count_jsonl(path)
    recent = _tail_jsonl(path, limit)

    # Aggregate distributions
    routes: dict[str, int] = {}
    reasons: dict[str, int] = {}
    tools: dict[str, int] = {}
    routed_count = 0
    for entry in recent:
        r = entry.get("route", "?")
        routes[r] = routes.get(r, 0) + 1
        reason = entry.get("reason", "?")
        reasons[reason] = reasons.get(reason, 0) + 1
        tool = entry.get("tool", "?")
        tools[tool] = tools.get(tool, 0) + 1
        if entry.get("routed"):
            routed_count += 1

    routed_pct = round(routed_count / max(len(recent), 1) * 100, 1)

    index = [_frontmatter({
        "type": "spark-routing-index",
        "total": total,
        "exported": len(recent),
        "limit": limit,
        "routed_rate": routed_pct,
    })]
    index.append(f"# Retrieval Routing Decisions ({len(recent)}/{total})\n")
    index.append(f"> {flow_link()} | [[../stages/08-advisory|Stage 8: Advisory]]\n")
    index.append(f"**Routed rate (recent):** {routed_pct}% ({routed_count}/{len(recent)})\n")
    if len(recent) < total:
        index.append(f"*Showing most recent {len(recent)}. Increase `explore_routing_max` in tuneables to see more.*\n")

    # Route distribution
    if routes:
        index.append("## Route Distribution\n")
        index.append("| Route | Count | % |")
        index.append("|-------|-------|---|")
        for r, c in sorted(routes.items(), key=lambda x: -x[1]):
            pct = round(c / max(len(recent), 1) * 100, 1)
            index.append(f"| `{r}` | {c} | {pct}% |")
        index.append("")

    # Reason distribution
    if reasons:
        index.append("## Reason Distribution\n")
        index.append("| Reason | Count | % |")
        index.append("|--------|-------|---|")
        for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
            pct = round(c / max(len(recent), 1) * 100, 1)
            index.append(f"| `{r}` | {c} | {pct}% |")
        index.append("")

    # Tool distribution
    if tools:
        index.append("## Tool Distribution\n")
        index.append("| Tool | Count |")
        index.append("|------|-------|")
        for t, c in sorted(tools.items(), key=lambda x: -x[1]):
            index.append(f"| {t} | {c} |")
        index.append("")

    # Recent decisions table
    index.append("## Recent Decisions\n")
    index.append("| Time | Tool | Route | Routed | Reason | Complexity |")
    index.append("|------|------|-------|--------|--------|------------|")
    for entry in reversed(recent[-50:]):
        ts_val = entry.get("ts", 0)
        ts = fmt_ts(ts_val) if ts_val else "?"
        tool = entry.get("tool", "?")
        route = entry.get("route", "?")
        routed = "yes" if entry.get("routed") else "no"
        reason = entry.get("reason", "")
        complexity = entry.get("complexity_score", "?")
        index.append(f"| {ts} | {tool} | `{route}` | {routed} | {reason} | {complexity} |")
    index.append("")
    (out / "_index.md").write_text("\n".join(index), encoding="utf-8")
    return 1


# ═══════════════════════════════════════════════════════════════════════
#  TUNEABLE EVOLUTION HISTORY
# ═══════════════════════════════════════════════════════════════════════

def _export_tuning(explore_dir: Path, limit: int) -> int:
    """Export auto-tuner parameter change history as a browsable index."""
    out = explore_dir / "tuning"
    out.mkdir(parents=True, exist_ok=True)
    path = _SD / "auto_tune_log.jsonl"
    total = _count_jsonl(path)
    recent = _tail_jsonl(path, limit)

    # Aggregate by section and by parameter
    sections: dict[str, int] = {}
    params: dict[str, int] = {}
    confidence_sum = 0.0
    confidence_count = 0
    for entry in recent:
        sec = entry.get("section", "?")
        sections[sec] = sections.get(sec, 0) + 1
        key = f"{sec}.{entry.get('key', '?')}"
        params[key] = params.get(key, 0) + 1
        conf = entry.get("confidence", 0)
        if conf:
            confidence_sum += conf
            confidence_count += 1

    avg_confidence = round(confidence_sum / max(confidence_count, 1), 2)

    index = [_frontmatter({
        "type": "spark-tuning-index",
        "total": total,
        "exported": len(recent),
        "limit": limit,
        "avg_confidence": avg_confidence,
    })]
    index.append(f"# Tuneable Evolution History ({len(recent)}/{total})\n")
    index.append(f"> {flow_link()} | [[../stages/12-tuneables|Stage 12: Tuneables]]\n")
    index.append(f"**Average confidence:** {avg_confidence} | **Total changes:** {total}\n")
    if len(recent) < total:
        index.append(f"*Showing most recent {len(recent)}. Increase `explore_tuning_max` in tuneables to see more.*\n")

    # Section distribution
    if sections:
        index.append("## Changes by Section\n")
        index.append("| Section | Changes |")
        index.append("|---------|---------|")
        for sec, c in sorted(sections.items(), key=lambda x: -x[1]):
            index.append(f"| **{sec}** | {c} |")
        index.append("")

    # Most-changed parameters
    if params:
        index.append("## Most-Changed Parameters\n")
        index.append("| Parameter | Changes |")
        index.append("|-----------|---------|")
        for p, c in sorted(params.items(), key=lambda x: -x[1])[:20]:
            index.append(f"| `{p}` | {c} |")
        index.append("")

    # Tuneable impact correlation
    # Cross-reference parameter changes with advisory effectiveness snapshots
    eff = _load_json(_SD / "advisor" / "effectiveness.json") or {}
    feedback_path = _SD / "advisor" / "implicit_feedback.jsonl"
    feedback_entries = _tail_jsonl(feedback_path, 500) if feedback_path.exists() else []
    if recent and (eff or feedback_entries):
        index.append("## Tuneable Impact Analysis\n")
        index.append("*Cross-referencing parameter changes with nearby feedback signals*\n")

        # Group feedback by 1-hour windows
        def _feedback_window(entries: list, center_ts: float, window_s: float = 3600) -> dict:
            before_followed = before_total = after_followed = after_total = 0
            for fb in entries:
                try:
                    fb_ts = float(fb.get("timestamp", 0))
                except (ValueError, TypeError):
                    continue
                if center_ts - window_s <= fb_ts < center_ts:
                    before_total += 1
                    if fb.get("signal") == "followed":
                        before_followed += 1
                elif center_ts <= fb_ts <= center_ts + window_s:
                    after_total += 1
                    if fb.get("signal") == "followed":
                        after_followed += 1
            return {
                "before_rate": round(before_followed / max(before_total, 1) * 100, 1),
                "before_n": before_total,
                "after_rate": round(after_followed / max(after_total, 1) * 100, 1),
                "after_n": after_total,
            }

        # Find unique change timestamps (grouped within 5s)
        change_groups: list[tuple[float, list[dict]]] = []
        for entry in recent:
            ts_val = entry.get("ts", 0)
            if not ts_val:
                continue
            if change_groups and abs(ts_val - change_groups[-1][0]) < 5:
                change_groups[-1][1].append(entry)
            else:
                change_groups.append((ts_val, [entry]))

        # Show impact for last 10 change groups
        impact_rows = []
        for ts_val, group in change_groups[-10:]:
            window = _feedback_window(feedback_entries, ts_val)
            if window["before_n"] < 2 and window["after_n"] < 2:
                continue  # Not enough data
            changes_desc = ", ".join(
                f"`{e.get('section','')}.{e.get('key','')}`={e.get('old','?')}->{e.get('new','?')}"
                for e in group[:3]
            )
            delta = window["after_rate"] - window["before_rate"]
            delta_str = f"+{delta:.1f}%" if delta >= 0 else f"{delta:.1f}%"
            impact_rows.append((
                fmt_ts(ts_val), changes_desc,
                f"{window['before_rate']}% (n={window['before_n']})",
                f"{window['after_rate']}% (n={window['after_n']})",
                delta_str,
            ))

        if impact_rows:
            index.append("| When | Changes | Follow Rate Before | Follow Rate After | Delta |")
            index.append("|------|---------|-------------------|------------------|-------|")
            for row in impact_rows:
                index.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} |")
            index.append("")
            index.append("*Window: 1 hour before vs 1 hour after each change. 'n' = feedback signals in window.*\n")
        else:
            index.append("*Not enough feedback data near parameter changes to show impact. Need more advisory cycles.*\n")

    # Recent changes table
    index.append("## Recent Changes\n")
    index.append("| Time | Section | Key | Old | New | Reason | Confidence |")
    index.append("|------|---------|-----|-----|-----|--------|------------|")
    for entry in reversed(recent[-50:]):
        ts_val = entry.get("ts", 0)
        ts = fmt_ts(ts_val) if ts_val else "?"
        sec = entry.get("section", "?")
        key = entry.get("key", "?")
        old = str(entry.get("old", "?"))[:20]
        new = str(entry.get("new", "?"))[:20]
        reason = entry.get("reason", "")[:60].replace("|", "/")
        conf = entry.get("confidence", "?")
        index.append(f"| {ts} | {sec} | `{key}` | {old} | {new} | {reason} | {conf} |")
    index.append("")
    (out / "_index.md").write_text("\n".join(index), encoding="utf-8")
    return 1


# ═══════════════════════════════════════════════════════════════════════
#  ADVISORY DECISION LEDGER
# ═══════════════════════════════════════════════════════════════════════

def _export_decisions(explore_dir: Path, limit: int) -> int:
    """Export advisory decision ledger showing emit/suppress/block decisions."""
    out = explore_dir / "decisions"
    out.mkdir(parents=True, exist_ok=True)
    path = _SD / "advisory_decision_ledger.jsonl"
    total = _count_jsonl(path)
    recent = _tail_jsonl(path, limit)

    # Aggregate distributions
    outcomes: dict[str, int] = {}
    stages: dict[str, int] = {}
    routes: dict[str, int] = {}
    tools: dict[str, int] = {}
    suppression_reasons: dict[str, int] = {}
    source_totals: dict[str, int] = {}
    emitted = 0
    blocked = 0

    for entry in recent:
        outcome = entry.get("outcome", "?")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if outcome == "emitted":
            emitted += 1
        elif outcome == "blocked":
            blocked += 1
        stage = entry.get("stage", "?")
        stages[stage] = stages.get(stage, 0) + 1
        route = entry.get("route", "?")
        routes[route] = routes.get(route, 0) + 1
        tool = entry.get("tool", "?")
        tools[tool] = tools.get(tool, 0) + 1

        # Parse suppression reasons
        sup_reasons = entry.get("suppressed_reasons", "[]")
        if isinstance(sup_reasons, str):
            try:
                import ast
                sup_reasons = ast.literal_eval(sup_reasons)
            except Exception:
                sup_reasons = []
        for sr in (sup_reasons or []):
            reason = sr.get("reason", "?") if isinstance(sr, dict) else str(sr)
            reason = reason[:60]
            suppression_reasons[reason] = suppression_reasons.get(reason, 0) + 1

        # Source counts
        sc = entry.get("source_counts", "{}")
        if isinstance(sc, str):
            try:
                import ast
                sc = ast.literal_eval(sc)
            except Exception:
                sc = {}
        for src, cnt in (sc or {}).items():
            source_totals[src] = source_totals.get(src, 0) + int(cnt)

    emit_rate = round(emitted / max(len(recent), 1) * 100, 1)

    index = [_frontmatter({
        "type": "spark-decisions-index",
        "total": total,
        "exported": len(recent),
        "limit": limit,
        "emit_rate": emit_rate,
    })]
    index.append(f"# Advisory Decision Ledger ({len(recent)}/{total})\n")
    index.append(f"> {flow_link()} | [[../stages/08-advisory|Stage 8: Advisory]]\n")
    index.append(f"**Emit rate (recent):** {emit_rate}% ({emitted}/{len(recent)}) | **Blocked:** {blocked}\n")
    if len(recent) < total:
        index.append(f"*Showing most recent {len(recent)}. Increase `explore_decisions_max` in tuneables to see more.*\n")

    # Outcome distribution
    if outcomes:
        index.append("## Decision Outcomes\n")
        index.append("| Outcome | Count | % |")
        index.append("|---------|-------|---|")
        for o, c in sorted(outcomes.items(), key=lambda x: -x[1]):
            pct = round(c / max(len(recent), 1) * 100, 1)
            index.append(f"| **{o}** | {c} | {pct}% |")
        index.append("")

    # Route distribution
    if routes:
        index.append("## Delivery Routes\n")
        index.append("| Route | Count |")
        index.append("|-------|-------|")
        for r, c in sorted(routes.items(), key=lambda x: -x[1]):
            index.append(f"| `{r}` | {c} |")
        index.append("")

    # Source distribution
    if source_totals:
        index.append("## Advisory Sources Used\n")
        index.append("| Source | Items Retrieved |")
        index.append("|--------|----------------|")
        for s, c in sorted(source_totals.items(), key=lambda x: -x[1]):
            index.append(f"| **{s}** | {c} |")
        index.append("")

    # Suppression reasons
    if suppression_reasons:
        index.append("## Suppression Reasons\n")
        index.append("*Why advice was blocked from delivery*\n")
        index.append("| Reason | Count |")
        index.append("|--------|-------|")
        for r, c in sorted(suppression_reasons.items(), key=lambda x: -x[1]):
            index.append(f"| {r} | {c} |")
        index.append("")

    # Tool distribution
    if tools:
        index.append("## Decisions by Tool\n")
        index.append("| Tool | Decisions |")
        index.append("|------|-----------|")
        for t, c in sorted(tools.items(), key=lambda x: -x[1]):
            index.append(f"| {t} | {c} |")
        index.append("")

    # Recent decisions table
    index.append("## Recent Decisions\n")
    index.append("| Time | Tool | Outcome | Route | Selected | Suppressed | Sources |")
    index.append("|------|------|---------|-------|----------|------------|---------|")
    for entry in reversed(recent[-50:]):
        ts_val = entry.get("ts", 0)
        ts = fmt_ts(float(ts_val)) if ts_val else "?"
        tool = entry.get("tool", "?")
        outcome = entry.get("outcome", "?")
        route = entry.get("route", "?")
        selected = entry.get("selected_count", 0)
        suppressed = entry.get("suppressed_count", 0)
        sc = entry.get("source_counts", "{}")
        if isinstance(sc, str):
            try:
                import ast
                sc = ast.literal_eval(sc)
            except Exception:
                sc = {}
        sources = ", ".join(f"{k}:{v}" for k, v in (sc or {}).items())
        index.append(f"| {ts} | {tool} | **{outcome}** | `{route}` | {selected} | {suppressed} | {sources} |")
    index.append("")
    (out / "_index.md").write_text("\n".join(index), encoding="utf-8")
    return 1


# ═══════════════════════════════════════════════════════════════════════
#  IMPLICIT FEEDBACK LOOP
# ═══════════════════════════════════════════════════════════════════════

def _event_ts(event: dict[str, Any]) -> float:
    """Best-effort event timestamp for sorting/trends."""
    try:
        ts = float(event.get("request_ts") or 0.0)
        if ts > 0:
            return ts
    except Exception:
        pass
    try:
        ts = float(event.get("resolved_at") or 0.0)
        if ts > 0:
            return ts
    except Exception:
        pass
    return 0.0


def _latest_reviews_by_event(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            continue
        prior = latest.get(event_id)
        try:
            ts = float(row.get("reviewed_at") or 0.0)
        except Exception:
            ts = 0.0
        if prior is None:
            latest[event_id] = row
            continue
        try:
            prior_ts = float(prior.get("reviewed_at") or 0.0)
        except Exception:
            prior_ts = 0.0
        if ts >= prior_ts:
            latest[event_id] = row
    return latest


def _export_helpfulness(explore_dir: Path, limit: int) -> int:
    """Export a human-readable helpfulness calibration progress page."""
    out = explore_dir / "helpfulness"
    out.mkdir(parents=True, exist_ok=True)

    summary = _load_json(_SD / "advisor" / "helpfulness_summary.json") or {}
    events = _tail_jsonl(_SD / "advisor" / "helpfulness_events.jsonl", limit)
    queue = _tail_jsonl(_SD / "advisor" / "helpfulness_llm_queue.jsonl", limit)
    reviews = _tail_jsonl(_SD / "advisor" / "helpfulness_llm_reviews.jsonl", max(limit * 4, limit))

    # Derived fallback metrics when summary is missing or partial.
    labels: dict[str, int] = {}
    judge_sources: dict[str, int] = {}
    conflicts = 0
    llm_applied = 0
    for row in events:
        label = str(row.get("helpful_label") or "unknown").strip().lower()
        labels[label] = labels.get(label, 0) + 1
        judge = str(row.get("judge_source") or "unknown").strip() or "unknown"
        judge_sources[judge] = judge_sources.get(judge, 0) + 1
        if bool(row.get("conflict")):
            conflicts += 1
        if bool(row.get("llm_review_applied")):
            llm_applied += 1

    total_events = int(summary.get("total_events", len(events)) or len(events))
    known_helpfulness = int(
        summary.get(
            "known_helpfulness_total",
            labels.get("helpful", 0) + labels.get("unhelpful", 0) + labels.get("harmful", 0),
        ) or 0
    )
    helpful_rate = float(
        summary.get(
            "helpful_rate_pct",
            round((100.0 * labels.get("helpful", 0) / max(known_helpfulness, 1)), 2) if known_helpfulness > 0 else 0.0,
        ) or 0.0
    )
    unknown_rate = float(
        summary.get(
            "unknown_rate_pct",
            round((100.0 * labels.get("unknown", 0) / max(total_events, 1)), 2) if total_events > 0 else 0.0,
        ) or 0.0
    )
    conflict_count = int(summary.get("conflict_count", conflicts) or conflicts)
    conflict_rate = float(
        summary.get(
            "conflict_rate_pct",
            round((100.0 * conflict_count / max(total_events, 1)), 2) if total_events > 0 else 0.0,
        ) or 0.0
    )
    queue_count = int(summary.get("llm_review_queue_count", len(queue)) or len(queue))
    llm_applied_count = int(summary.get("llm_review_applied_count", llm_applied) or llm_applied)
    follow_rate = float(summary.get("follow_rate_pct", 0.0) or 0.0)

    if isinstance(summary.get("labels"), dict):
        labels = dict(summary.get("labels", {}))
    if isinstance(summary.get("judge_source"), dict):
        judge_sources = dict(summary.get("judge_source", {}))

    # LLM review queue status.
    reviews_by_event = _latest_reviews_by_event(reviews)
    queue_ids = {str(r.get("event_id") or "").strip() for r in queue}
    queue_ids.discard("")
    review_status_counts: dict[str, int] = {}
    unresolved_queue = 0
    for event_id in queue_ids:
        status = str((reviews_by_event.get(event_id) or {}).get("status") or "").strip().lower()
        if status:
            review_status_counts[status] = review_status_counts.get(status, 0) + 1
        if status not in {"ok", "abstain"}:
            unresolved_queue += 1

    # Trend: last 7 calendar days in local timezone.
    daily: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "total": 0,
            "known": 0,
            "helpful": 0,
            "unknown": 0,
            "conflicts": 0,
            "queued": 0,
            "llm_applied": 0,
        }
    )
    for row in events:
        ts = _event_ts(row)
        if ts <= 0:
            continue
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        slot = daily[day]
        slot["total"] += 1
        label = str(row.get("helpful_label") or "unknown").strip().lower()
        if label in {"helpful", "unhelpful", "harmful"}:
            slot["known"] += 1
        if label == "helpful":
            slot["helpful"] += 1
        if label == "unknown":
            slot["unknown"] += 1
        if bool(row.get("conflict")):
            slot["conflicts"] += 1
        if bool(row.get("llm_review_required")):
            slot["queued"] += 1
        if bool(row.get("llm_review_applied")):
            slot["llm_applied"] += 1

    conflict_events = [r for r in events if bool(r.get("conflict"))]
    conflict_events.sort(key=_event_ts)
    recent_conflicts = conflict_events[-20:]

    latest_reviews = sorted(reviews, key=lambda r: float(r.get("reviewed_at") or 0.0))
    recent_reviews = latest_reviews[-40:]

    index = [_frontmatter({
        "type": "spark-helpfulness-index",
        "events": len(events),
        "queue": queue_count,
        "reviews": len(reviews),
        "helpful_rate_pct": round(helpful_rate, 2),
        "unknown_rate_pct": round(unknown_rate, 2),
        "conflict_rate_pct": round(conflict_rate, 2),
    })]
    index.append("# Helpfulness Calibration\n")
    index.append(f"> {flow_link()} | [[../stages/08-advisory|Stage 8: Advisory]] | [[../advisory/_index|Advisory Effectiveness]]\n")
    index.append(f"**Event window:** latest {len(events)} events (limit: {limit})\n")
    index.append("")

    index.append("## Current Scoreboard\n")
    index.append("| Metric | Value |")
    index.append("|--------|-------|")
    index.append(f"| Total events | {fmt_num(total_events)} |")
    index.append(f"| Known helpfulness events | {fmt_num(known_helpfulness)} |")
    index.append(f"| Helpful rate | {helpful_rate:.2f}% |")
    index.append(f"| Unknown rate | {unknown_rate:.2f}% |")
    index.append(f"| Conflict count | {fmt_num(conflict_count)} ({conflict_rate:.2f}%) |")
    index.append(f"| LLM review queue | {fmt_num(queue_count)} |")
    index.append(f"| LLM review applied | {fmt_num(llm_applied_count)} |")
    index.append(f"| Follow rate (explicit/implicit where known) | {follow_rate:.2f}% |")
    index.append("")

    index.append("## LLM Queue Health\n")
    index.append("| Metric | Value |")
    index.append("|--------|-------|")
    index.append(f"| Queue items in current window | {fmt_num(len(queue_ids))} |")
    index.append(f"| Unresolved queue items | {fmt_num(unresolved_queue)} |")
    index.append(f"| Total review records in window | {fmt_num(len(reviews))} |")
    index.append("")
    if review_status_counts:
        index.append("| Review status | Count |")
        index.append("|--------------|-------|")
        for status, count in sorted(review_status_counts.items(), key=lambda x: (-x[1], x[0])):
            index.append(f"| {status} | {fmt_num(count)} |")
        index.append("")

    day_keys = sorted(daily.keys())[-7:]
    if day_keys:
        index.append("## 7-Day Trend\n")
        index.append("| Day | Events | Known | Helpful | Helpful Rate | Unknown | Conflicts | Queued | LLM Applied |")
        index.append("|-----|--------|-------|---------|--------------|---------|-----------|--------|-------------|")
        for day in day_keys:
            row = daily[day]
            helpful_pct = round((100.0 * row["helpful"] / max(row["known"], 1)), 1) if row["known"] > 0 else 0.0
            index.append(
                f"| {day} | {row['total']} | {row['known']} | {row['helpful']} | {helpful_pct}% | "
                f"{row['unknown']} | {row['conflicts']} | {row['queued']} | {row['llm_applied']} |"
            )
        index.append("")

    if labels:
        index.append("## Label Distribution\n")
        index.append("| Label | Count |")
        index.append("|-------|-------|")
        for label, count in sorted(labels.items(), key=lambda x: (-x[1], x[0])):
            index.append(f"| {label} | {fmt_num(count)} |")
        index.append("")

    if judge_sources:
        index.append("## Judge Sources\n")
        index.append("| Judge source | Count |")
        index.append("|--------------|-------|")
        for source, count in sorted(judge_sources.items(), key=lambda x: (-x[1], x[0])):
            index.append(f"| {source} | {fmt_num(count)} |")
        index.append("")

    if recent_conflicts:
        index.append("## Recent Conflict Events\n")
        index.append("| Time | Tool | Label | Confidence | Needs Review | Judge Source |")
        index.append("|------|------|-------|------------|--------------|--------------|")
        for row in reversed(recent_conflicts):
            ts = _event_ts(row)
            tool = str(row.get("tool") or "?")
            label = str(row.get("helpful_label") or "unknown")
            confidence = float(row.get("confidence") or 0.0)
            need_review = "yes" if bool(row.get("llm_review_required")) else "no"
            judge = str(row.get("judge_source") or "?")
            index.append(f"| {fmt_ts(ts) if ts > 0 else '?'} | {tool} | {label} | {confidence:.3f} | {need_review} | {judge} |")
        index.append("")

    if recent_reviews:
        index.append("## Recent LLM Reviews\n")
        index.append("| Reviewed | Event ID | Provider | Status | Label | Confidence |")
        index.append("|----------|----------|----------|--------|-------|------------|")
        for row in reversed(recent_reviews):
            reviewed_ts = float(row.get("reviewed_at") or 0.0)
            event_id = str(row.get("event_id") or "")[:14]
            provider = str(row.get("provider") or "?")
            status = str(row.get("status") or "?")
            label = str(row.get("label") or "-")
            confidence = float(row.get("confidence") or 0.0)
            index.append(
                f"| {fmt_ts(reviewed_ts) if reviewed_ts > 0 else '?'} | `{event_id}` | "
                f"{provider} | {status} | {label} | {confidence:.3f} |"
            )
        index.append("")

    (out / "_index.md").write_text("\n".join(index), encoding="utf-8")
    return 1


def _export_feedback(explore_dir: Path, limit: int) -> int:
    """Export implicit feedback showing whether advice was followed/ignored."""
    out = explore_dir / "feedback"
    out.mkdir(parents=True, exist_ok=True)
    path = _SD / "advisor" / "implicit_feedback.jsonl"
    total = _count_jsonl(path)
    recent = _tail_jsonl(path, limit)

    # Aggregate
    signals: dict[str, int] = {}
    tools: dict[str, int] = {}
    sources: dict[str, int] = {}
    success_count = 0
    total_latency = 0.0
    latency_count = 0

    for entry in recent:
        sig = entry.get("signal", "?")
        signals[sig] = signals.get(sig, 0) + 1
        tool = entry.get("tool", "?")
        tools[tool] = tools.get(tool, 0) + 1
        if entry.get("success") in (True, "True", "true"):
            success_count += 1
        lat = entry.get("latency_s", 0)
        try:
            lat = float(lat)
            if lat > 0:
                total_latency += lat
                latency_count += 1
        except (ValueError, TypeError):
            pass

        # Parse advice sources
        srcs = entry.get("advice_sources", "[]")
        if isinstance(srcs, str):
            try:
                import ast
                srcs = ast.literal_eval(srcs)
            except Exception:
                srcs = []
        for src in (srcs or []):
            # Extract source type (e.g., "eidos:eidos:heuristic:f145d3b5" -> "eidos")
            src_type = str(src).split(":")[0] if ":" in str(src) else str(src)
            sources[src_type] = sources.get(src_type, 0) + 1

    followed_count = signals.get("followed", 0)
    ignored_count = signals.get("ignored", 0)
    follow_rate = round(followed_count / max(followed_count + ignored_count, 1) * 100, 1)
    success_rate = round(success_count / max(len(recent), 1) * 100, 1)
    avg_latency = round(total_latency / max(latency_count, 1), 2)

    index = [_frontmatter({
        "type": "spark-feedback-index",
        "total": total,
        "exported": len(recent),
        "limit": limit,
        "follow_rate": follow_rate,
        "success_rate": success_rate,
    })]
    index.append(f"# Implicit Feedback Loop ({len(recent)}/{total})\n")
    index.append(f"> {flow_link()} | [[../stages/08-advisory|Stage 8: Advisory]]\n")
    index.append(f"**Follow rate:** {follow_rate}% | **Success rate:** {success_rate}% | **Avg latency:** {avg_latency}s\n")
    if len(recent) < total:
        index.append(f"*Showing most recent {len(recent)}. Increase `explore_feedback_max` in tuneables to see more.*\n")

    # Signal distribution
    if signals:
        index.append("## Signal Distribution\n")
        index.append("*Whether the tool action after receiving advice succeeded (followed) or not (ignored)*\n")
        index.append("| Signal | Count | % |")
        index.append("|--------|-------|---|")
        for s, c in sorted(signals.items(), key=lambda x: -x[1]):
            pct = round(c / max(len(recent), 1) * 100, 1)
            index.append(f"| **{s}** | {c} | {pct}% |")
        index.append("")

    # Per-tool follow rates
    if tools:
        # Compute per-tool follow rate
        tool_followed: dict[str, int] = {}
        tool_total: dict[str, int] = {}
        for entry in recent:
            tool = entry.get("tool", "?")
            tool_total[tool] = tool_total.get(tool, 0) + 1
            if entry.get("signal") == "followed":
                tool_followed[tool] = tool_followed.get(tool, 0) + 1
        index.append("## Follow Rate by Tool\n")
        index.append("| Tool | Followed | Total | Rate |")
        index.append("|------|----------|-------|------|")
        for t, tot in sorted(tool_total.items(), key=lambda x: -x[1]):
            fol = tool_followed.get(t, 0)
            rate = round(fol / max(tot, 1) * 100, 1)
            index.append(f"| {t} | {fol} | {tot} | {rate}% |")
        index.append("")

    # Source effectiveness
    if sources:
        index.append("## Advice Sources (when followed)\n")
        index.append("| Source | Times in Followed Advice |")
        index.append("|--------|-------------------------|")
        for s, c in sorted(sources.items(), key=lambda x: -x[1]):
            index.append(f"| **{s}** | {c} |")
        index.append("")

    # Recent feedback entries
    index.append("## Recent Feedback\n")
    index.append("| Time | Tool | Signal | Success | Sources | Latency |")
    index.append("|------|------|--------|---------|---------|---------|")
    for entry in reversed(recent[-50:]):
        ts_val = entry.get("timestamp", 0)
        ts = fmt_ts(float(ts_val)) if ts_val else "?"
        tool = entry.get("tool", "?")
        signal = entry.get("signal", "?")
        success = "yes" if entry.get("success") in (True, "True", "true") else "no"
        srcs = entry.get("advice_sources", "[]")
        if isinstance(srcs, str):
            try:
                import ast
                srcs = ast.literal_eval(srcs)
            except Exception:
                srcs = []
        src_display = ", ".join(str(s).split(":")[0] for s in (srcs or [])[:3])
        lat = entry.get("latency_s", "?")
        index.append(f"| {ts} | {tool} | **{signal}** | {success} | {src_display} | {lat}s |")
    index.append("")
    (out / "_index.md").write_text("\n".join(index), encoding="utf-8")
    return 1


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

def generate_explorer(cfg: ObservatoryConfig) -> dict[str, int]:
    """Generate all explorer pages. Returns {section: files_written}."""
    vault = Path(cfg.vault_dir).expanduser()
    explore_dir = vault / "_observatory" / "explore"
    explore_dir.mkdir(parents=True, exist_ok=True)

    counts = {}
    counts["cognitive"] = _export_cognitive(explore_dir, cfg.explore_cognitive_max)
    counts["distillations"] = _export_distillations(explore_dir, cfg.explore_distillations_max)
    counts["episodes"] = _export_episodes(explore_dir, cfg.explore_episodes_max)
    counts["verdicts"] = _export_verdicts(explore_dir, cfg.explore_verdicts_max)
    counts["promotions"] = _export_promotions(explore_dir, cfg.explore_promotions_max)
    counts["advisory"] = _export_advisory(explore_dir, cfg.explore_advice_max)
    counts["routing"] = _export_routing(explore_dir, cfg.explore_routing_max)
    counts["tuning"] = _export_tuning(explore_dir, cfg.explore_tuning_max)
    counts["decisions"] = _export_decisions(explore_dir, cfg.explore_decisions_max)
    counts["helpfulness"] = _export_helpfulness(explore_dir, cfg.explore_feedback_max)
    counts["feedback"] = _export_feedback(explore_dir, cfg.explore_feedback_max)

    # Generate master explore index
    _generate_explore_index(explore_dir, counts, cfg)
    return counts


def _generate_explore_index(explore_dir: Path, counts: dict[str, int], cfg: ObservatoryConfig) -> None:
    """Generate the master explore/_index.md that links to all sections."""
    index = [_frontmatter({"type": "spark-explorer-index"})]
    index.append("# Explore Spark Intelligence\n")
    index.append(f"> {flow_link()} | Browse individual items from every stage\n")
    index.append("## Data Stores\n")
    index.append("| Store | Items Exported | Max | Browse |")
    index.append("|-------|---------------|-----|--------|")
    sections = [
        ("cognitive", "Cognitive Insights", cfg.explore_cognitive_max, "explore_cognitive_max"),
        ("distillations", "EIDOS Distillations", cfg.explore_distillations_max, "explore_distillations_max"),
        ("episodes", "EIDOS Episodes", cfg.explore_episodes_max, "explore_episodes_max"),
        ("verdicts", "Meta-Ralph Verdicts", cfg.explore_verdicts_max, "explore_verdicts_max"),
        ("promotions", "Promotion Log", cfg.explore_promotions_max, "explore_promotions_max"),
        ("advisory", "Advisory Effectiveness", cfg.explore_advice_max, "explore_advice_max"),
        ("routing", "Retrieval Routing", cfg.explore_routing_max, "explore_routing_max"),
        ("tuning", "Tuneable Evolution", cfg.explore_tuning_max, "explore_tuning_max"),
        ("decisions", "Advisory Decisions", cfg.explore_decisions_max, "explore_decisions_max"),
        ("helpfulness", "Helpfulness Calibration", cfg.explore_feedback_max, "explore_feedback_max"),
        ("feedback", "Implicit Feedback", cfg.explore_feedback_max, "explore_feedback_max"),
    ]
    for key, label, max_val, tuneable in sections:
        n = counts.get(key, 0)
        index.append(f"| {label} | {n} pages | {max_val} | [[{key}/_index]] |")
    index.append("")
    index.append("## Adjusting Limits\n")
    index.append("All limits are configurable in `~/.spark/tuneables.json` under the `observatory` section:\n")
    index.append("```json")
    index.append('"observatory": {')
    index.append(f'    "explore_cognitive_max": {cfg.explore_cognitive_max},')
    index.append(f'    "explore_distillations_max": {cfg.explore_distillations_max},')
    index.append(f'    "explore_episodes_max": {cfg.explore_episodes_max},')
    index.append(f'    "explore_verdicts_max": {cfg.explore_verdicts_max},')
    index.append(f'    "explore_promotions_max": {cfg.explore_promotions_max},')
    index.append(f'    "explore_advice_max": {cfg.explore_advice_max},')
    index.append(f'    "explore_routing_max": {cfg.explore_routing_max},')
    index.append(f'    "explore_tuning_max": {cfg.explore_tuning_max},')
    index.append(f'    "explore_decisions_max": {cfg.explore_decisions_max},')
    index.append(f'    "explore_feedback_max": {cfg.explore_feedback_max}')
    index.append("}")
    index.append("```\n")
    index.append("Then regenerate: `python scripts/generate_observatory.py --force --verbose`\n")
    (explore_dir / "_index.md").write_text("\n".join(index), encoding="utf-8")
