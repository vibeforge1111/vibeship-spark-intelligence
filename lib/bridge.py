#!/usr/bin/env python3
"""
Spark Bridge - Connect learnings to operational context

The missing link: learnings that actually influence behavior.
"""

import json
import os
from datetime import datetime
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from lib.memory_banks import infer_project_key, retrieve as bank_retrieve
from lib.tastebank import infer_domain as taste_infer_domain, retrieve as taste_retrieve
from lib.diagnostics import log_debug
from lib.clawdbot_files import daily_memory_path, user_md

# Paths
SPARK_DIR = Path(__file__).parent.parent
WORKSPACE = Path(os.environ.get("SPARK_WORKSPACE", str(Path.home() / "clawd"))).expanduser()
MEMORY_FILE = WORKSPACE / "MEMORY.md"
SPARK_CONTEXT_FILE = WORKSPACE / "SPARK_CONTEXT.md"


def get_high_value_insights(min_reliability: float = 0.7, min_validations: int = 2) -> List[Dict]:
    """Get insights that have proven reliable enough to act on."""
    from lib.cognitive_learner import CognitiveLearner
    
    cognitive = CognitiveLearner()
    valuable = []
    
    for key, insight in cognitive.insights.items():
        if insight.reliability >= min_reliability and insight.times_validated >= min_validations:
            valuable.append({
                "category": insight.category.value,
                "insight": insight.insight,
                "reliability": insight.reliability,
                "validations": insight.times_validated,
                "promoted": insight.promoted,
            })
    
    # Sort by reliability * validations (confidence score)
    valuable.sort(key=lambda x: x["reliability"] * x["validations"], reverse=True)
    return valuable


def get_recent_lessons() -> List[Dict]:
    """Get lessons extracted from surprises - these are gold."""
    from lib.aha_tracker import AhaTracker
    
    aha = AhaTracker()
    lessons = []
    
    for surprise in aha.get_recent_surprises(20):
        if surprise.lesson_extracted:
            lessons.append({
                "lesson": surprise.lesson_extracted,
                "from_prediction": surprise.predicted_outcome[:50],
                "actual": surprise.actual_outcome[:50],
                "type": surprise.surprise_type,
            })
    
    return lessons[:10]  # Top 10 lessons


def get_strong_opinions() -> List[Dict]:
    """Get opinions that are forming strongly."""
    from lib.spark_voice import SparkVoice
    
    voice = SparkVoice()
    return [
        {"topic": o.topic, "preference": o.preference, "strength": o.strength}
        for o in voice.get_strong_opinions()
    ]


def get_growth_moments() -> List[Dict]:
    """Get recorded growth moments."""
    from lib.spark_voice import SparkVoice
    
    voice = SparkVoice()
    return [
        {"before": g.before, "after": g.after, "trigger": g.trigger}
        for g in voice.get_recent_growth(5)
    ]


def infer_current_focus(max_events: int = 25) -> str:
    """Infer current focus from recent Spark events.

    Works across runtimes as long as events are being ingested into Spark.
    """
    try:
        from lib.queue import read_recent_events, EventType

        events = read_recent_events(max_events)
        texts = []
        for e in reversed(events):
            if e.event_type == EventType.USER_PROMPT:
                # sparkd stores structured data under data.payload
                payload = (e.data or {}).get("payload") or {}
                t = payload.get("text")
                if t:
                    texts.append(str(t))

        # Fall back: use tool names as a weak signal
        if not texts:
            for e in reversed(events):
                if e.tool_name:
                    texts.append(str(e.tool_name))

        joined = "\n".join(texts).strip()
        return joined[:800]
    except Exception as e:
        log_debug("bridge", "infer_current_focus failed", e)
        return ""


def get_contextual_insights(query: str, limit: int = 6) -> List[Dict[str, Any]]:
    """Pull the most relevant insights for the *current task*.

    This is the key improvement: instead of always showing generic 'top' insights,
    we show what's relevant to what we're doing now.
    """
    if not query:
        return []

    out: List[Dict[str, Any]] = []

    # 1) Cognitive insights (fast, local)
    try:
        from lib.cognitive_learner import CognitiveLearner

        cog = CognitiveLearner()
        for ins in cog.get_insights_for_context(query, limit=limit):
            out.append({
                "source": "cognitive",
                "category": ins.category.value,
                "text": ins.insight,
                "reliability": ins.reliability,
                "validations": ins.times_validated,
            })
    except Exception as e:
        log_debug("bridge", "get_contextual_insights: cognitive failed", e)
        pass

    # 2) Layered memory banks (project + global)
    try:
        pk = infer_project_key()
        for m in bank_retrieve(query, project_key=pk, limit=limit):
            out.append({
                "source": "bank",
                "category": m.get("category") or "memory",
                "text": (m.get("text") or "")[:240],
                "reliability": None,
                "validations": None,
            })
    except Exception as e:
        log_debug("bridge", "get_contextual_insights: bank failed", e)
        pass

    # 3) TasteBank retrieval (lightweight taste references)
    try:
        dom = taste_infer_domain(query)
        if dom in ("social_posts", "ui_design", "art"):
            for it in taste_retrieve(dom, query, limit=3):
                out.append({
                    "source": "taste",
                    "category": f"taste:{dom}",
                    "text": f"{it.get('label') or ''} | {it.get('source') or ''}"[:240],
                    "reliability": None,
                    "validations": None,
                })
    except Exception as e:
        log_debug("bridge", "get_contextual_insights: taste failed", e)
        pass

    # 4) Mind retrieval (if available)
    try:
        from lib.mind_bridge import MindBridge

        mind = MindBridge()
        mems = mind.retrieve_relevant(query, limit=limit)
        for m in mems:
            out.append({
                "source": "mind",
                "category": m.get("content_type") or "memory",
                "text": (m.get("content") or "").splitlines()[0][:240],
                "reliability": None,
                "validations": None,
            })
    except Exception as e:
        log_debug("bridge", "get_contextual_insights: mind failed", e)
        pass

    # De-dupe by text
    seen = set()
    deduped = []
    for item in out:
        key = item.get("text") or ""
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)

    return deduped[:limit]


def get_relevant_skills(query: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Retrieve relevant skills from the skills registry (lightweight)."""
    if not query:
        return []
    try:
        from lib.skills_router import recommend_skills
        return recommend_skills(query, limit=limit)
    except Exception as e:
        log_debug("bridge", "get_relevant_skills failed", e)
        return []


def _recognition_snippet(query: str, contextual: List[Dict[str, Any]], lessons: List[Dict[str, Any]]) -> str:
    """Generate a tiny, optional personalization line.

    This is designed to make Spark feel *present* without being creepy.
    Keep it:
    - 0-2 sentences
    - preference/goal aligned
    - no "I tracked you" language
    """

    user_bits = []
    for item in contextual or []:
        if item.get("source") == "cognitive" and item.get("category") in ("user_understanding", "communication"):
            user_bits.append(item.get("text"))
    user_bit = next((b for b in user_bits if b), "")

    lesson = (lessons[0].get("lesson") if lessons else "")

    lines = []
    if user_bit:
        lines.append(f"Ground this in the user's preferences: {user_bit}")
    if lesson:
        lines.append(f"If relevant, reference a recent lesson: {lesson}")

    return "\n".join(f"- {l}" for l in lines if l)


def generate_active_context(query: Optional[str] = None) -> str:
    """Generate context that's actually useful for operation."""

    query = (query or "").strip()
    if not query:
        query = infer_current_focus()

    contextual = get_contextual_insights(query, limit=6) if query else []
    skills = get_relevant_skills(query, limit=3) if query else []
    insights = get_high_value_insights()
    lessons = get_recent_lessons()
    opinions = get_strong_opinions()
    growth = get_growth_moments()
    advisor_block = ""
    if query:
        try:
            from lib.advisor import get_advisor
            advisor_block = get_advisor().generate_context_block("task", query, include_mind=False)
        except Exception as e:
            log_debug("bridge", "advisor block failed", e)
    
    lines = [
        "=" * 50,
        "  SPARK ACTIVE CONTEXT",
        "  Learnings that should influence behavior",
        "=" * 50,
        "",
    ]
    
    # Current focus (task-relevant)
    if query:
        lines.append("## Current Focus")
        lines.append(query.replace("\n", " ")[:200] + ("..." if len(query) > 200 else ""))
        lines.append("")

    if contextual:
        lines.append("## Relevant Right Now")
        for item in contextual:
            src = item.get("source")
            cat = item.get("category")
            txt = item.get("text")
            if src == "cognitive":
                lines.append(f"- [{cat}] {txt}")
            else:
                lines.append(f"- [mind:{cat}] {txt}")
        lines.append("")

    if skills:
        lines.append("## Relevant Skills")
        for s in skills:
            sid = s.get("skill_id") or s.get("name") or "unknown-skill"
            desc = (s.get("description") or "").strip()
            if len(desc) > 120:
                desc = desc[:117] + "..."
            owns = s.get("owns") or []
            delegates = s.get("delegates") or []
            parts = []
            if owns:
                parts.append(f"owns: {', '.join(owns[:2])}")
            if delegates:
                parts.append(f"delegates: {', '.join(delegates[:2])}")
            suffix = f" ({'; '.join(parts)})" if parts else ""
            lines.append(f"- [{sid}] {desc}{suffix}".rstrip())
        lines.append("")

    if advisor_block:
        lines.append(advisor_block.strip())
        lines.append("")

    # Micro-personalization (optional)
    recog = _recognition_snippet(query=query or "", contextual=contextual, lessons=lessons)
    if recog:
        lines.append("## Recognition (use sparingly in chat)")
        lines.append(recog)
        lines.append("")

    # High-value insights (proven reliable)
    if insights:
        lines.append("## Proven Insights (act on these)")
        for ins in insights[:5]:
            lines.append(f"- [{ins['category']}] {ins['insight']}")
        lines.append("")
    
    # Lessons from surprises (hard-won knowledge)
    if lessons:
        lines.append("## Lessons Learned (don't repeat mistakes)")
        for lesson in lessons[:5]:
            lines.append(f"- {lesson['lesson']}")
        lines.append("")
    
    # Strong opinions (this is who I am)
    if opinions:
        lines.append("## My Opinions (these define me)")
        for op in opinions[:5]:
            lines.append(f"- {op['topic']}: {op['preference']}")
        lines.append("")
    
    # Growth (how I've changed)
    if growth:
        lines.append("## How I've Grown")
        for g in growth[:3]:
            lines.append(f"- Was: {g['before']} -> Now: {g['after']}")
        lines.append("")
    
    lines.append("=" * 50)
    
    return "\n".join(lines)


def update_spark_context(query: Optional[str] = None):
    """Update SPARK_CONTEXT.md with active, useful context.

    If query is provided, we tailor the context to that task.
    """
    context = generate_active_context(query=query)
    SPARK_CONTEXT_FILE.write_text(context)
    return context


def inject_to_memory(insight: str, category: str = "spark", apply: bool = False) -> dict:
    """Propose (or apply) injecting a high-value insight into MEMORY.md.

    Default behavior is SAFE: write a patch proposal instead of mutating files.
    Returns a small result dict.
    """
    from lib.clawdbot_promoter import inject_into_memory_md

    timestamp = datetime.now().strftime("%Y-%m-%d")
    bullet = f"- [{timestamp}] [{category}] {insight}"

    res, conflict = inject_into_memory_md(
        memory_path=MEMORY_FILE,
        bullet_line=bullet,
        section_header="## Spark Learnings",
        apply=apply,
    )

    out = {
        "applied": res.applied,
        "patch_path": res.patch_path,
        "reason": res.reason,
    }
    if conflict:
        out["conflict"] = conflict
    return out


def auto_promote_insights(min_reliability: float = 0.8, min_validations: int = 3, apply: bool = False):
    """Promote highly reliable insights to MEMORY.md.

    Default behavior is proposal-only (no file mutation).

    If apply=True, we edit MEMORY.md directly and mark insights as promoted.
    If apply=False, we generate patch files and do NOT mark promoted.
    """
    from lib.cognitive_learner import CognitiveLearner

    cognitive = CognitiveLearner()
    proposed_or_applied = 0

    for key, insight in cognitive.insights.items():
        if (
            insight.reliability >= min_reliability
            and insight.times_validated >= min_validations
            and not insight.promoted
        ):
            result = inject_to_memory(insight.insight, insight.category.value, apply=apply)

            # Only mark promoted if we actually applied the change
            if apply and result.get("applied"):
                insight.promoted = True
                insight.promoted_to = "MEMORY.md"
                cognitive._save_insights()
                proposed_or_applied += 1
            elif (not apply) and (result.get("patch_path") or result.get("reason") == "already_present"):
                proposed_or_applied += 1

    return proposed_or_applied


def propose_daily_digest(apply: bool = False, max_items: int = 6) -> dict:
    """Propose (or apply) a small "Spark Digest" section into today's daily memory file.

    This is intended to keep Clawdbot fast: daily files hold raw/near-term context,
    while MEMORY.md stays curated.

    Default is proposal-only.
    """
    from datetime import datetime, timedelta
    from lib.cognitive_learner import CognitiveLearner
    from lib.clawdbot_promoter import inject_into_daily_md
    from lib.aha_tracker import AhaTracker

    today = datetime.now()

    cognitive = CognitiveLearner()

    # Recent insights: last 24h
    recent = []
    cutoff = today - timedelta(hours=24)
    for ins in cognitive.insights.values():
        try:
            created = datetime.fromisoformat(ins.created_at)
        except Exception:
            continue
        if created >= cutoff:
            recent.append(ins)

    # Sort: newest first
    recent.sort(key=lambda i: i.created_at, reverse=True)

    aha = AhaTracker()
    lessons = []
    for s in aha.get_recent_surprises(20):
        if s.lesson_extracted:
            lessons.append(s.lesson_extracted)

    lines = []
    lines.append(f"- Updated: {today.strftime('%Y-%m-%d %H:%M')}")

    if recent:
        lines.append("- Insights:")
        for ins in recent[: max_items]:
            lines.append(f"  - [{ins.category.value}] {ins.insight}")

    if lessons:
        lines.append("- Lessons:")
        for l in lessons[:3]:
            lines.append(f"  - {l}")

    res = inject_into_daily_md(
        date_ymd=today.strftime("%Y-%m-%d"),
        lines_to_add=lines,
        section_header="## Spark Digest",
        apply=apply,
    )

    return {"applied": res.applied, "patch_path": res.patch_path, "reason": res.reason}


def propose_user_updates(apply: bool = False, min_reliability: float = 0.8, min_validations: int = 3) -> dict:
    """Propose (or apply) stable preferences into USER.md.

    We only add a dedicated section to avoid reshaping the doc.
    Default is proposal-only.
    """
    from lib.cognitive_learner import CognitiveLearner
    from lib.clawdbot_promoter import inject_into_user_md

    path = user_md()
    if not path.exists():
        return {"applied": False, "patch_path": None, "reason": f"missing:{path}"}

    cognitive = CognitiveLearner()

    bullets = []
    for ins in cognitive.insights.values():
        if ins.category.value not in ("user_understanding", "communication"):
            continue
        if ins.reliability < min_reliability or ins.times_validated < min_validations:
            continue
        bullets.append(f"- {ins.insight} ({ins.reliability:.0%}, {ins.times_validated} validations)")

    # keep short and stable
    bullets = bullets[:8]

    res = inject_into_user_md(
        bullet_lines=bullets,
        section_header="## Preferences (Spark)",
        apply=apply,
    )

    return {"applied": res.applied, "patch_path": res.patch_path, "reason": res.reason}


def bridge_status() -> Dict[str, Any]:
    """Get status of the learning bridge."""
    insights = get_high_value_insights()
    lessons = get_recent_lessons()
    opinions = get_strong_opinions()
    
    return {
        "high_value_insights": len(insights),
        "lessons_learned": len(lessons),
        "strong_opinions": len(opinions),
        "context_file": str(SPARK_CONTEXT_FILE),
        "memory_file": str(MEMORY_FILE),
        "context_exists": SPARK_CONTEXT_FILE.exists(),
        "memory_exists": MEMORY_FILE.exists(),
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "context":
            print(generate_active_context())
        
        elif cmd == "update":
            update_spark_context()
            print("OK Updated SPARK_CONTEXT.md")
        
        elif cmd == "promote":
            count = auto_promote_insights(apply=False)
            print(f"OK Proposed {count} insight promotions (see <workspace>/.spark/proposals)")
        
        elif cmd == "status":
            status = bridge_status()
            print(json.dumps(status, indent=2))
        
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: bridge.py [context|update|promote|status]")
    else:
        # Default: show status
        print(generate_active_context())
