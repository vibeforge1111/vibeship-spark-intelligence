#!/usr/bin/env python3
"""
Spark Bridge - Connect learnings to operational context

The missing link: learnings that actually influence behavior.
"""

import json
import os
import re
from datetime import datetime
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from lib.memory_banks import infer_project_key, retrieve as bank_retrieve
from lib.tastebank import infer_domain as taste_infer_domain, retrieve as taste_retrieve
from lib.diagnostics import log_debug
from lib.exposure_tracker import record_exposures, infer_latest_session_id, infer_latest_trace_id
from lib.project_profile import load_profile, get_suggested_questions
from lib.opportunity_scanner import get_recent_self_opportunities
from lib.outcome_checkin import list_checkins

# Paths
SPARK_DIR = Path(__file__).parent.parent
WORKSPACE = Path(os.environ.get("SPARK_WORKSPACE", str(Path.home() / "clawd"))).expanduser()
MEMORY_FILE = WORKSPACE / "MEMORY.md"
SPARK_CONTEXT_FILE = WORKSPACE / "SPARK_CONTEXT.md"
HIGH_VALIDATION_OVERRIDE = 50


def _normalize_insight_text(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s*\(\d+\s*calls?\)", "", t)
    t = re.sub(r"\(\s*recovered\s*\d+%?\s*\)", "", t)
    t = re.sub(r"\brecovered\s*\d+%?\b", "recovered", t)
    t = re.sub(r"\s+\d+$", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _is_low_value_insight(text: str) -> bool:
    t = (text or "").lower()
    try:
        from lib.promoter import is_operational_insight
        if is_operational_insight(t):
            return True
    except ImportError:
        pass
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
    if "use " in t or "prefer" in t or "verify" in t or "check" in t:
        score += 1
    if "->" in t:
        score += 1
    return score


def get_high_value_insights(
    min_reliability: float = 0.7,
    min_validations: int = 2,
    high_validation_override: int = HIGH_VALIDATION_OVERRIDE,
) -> List[Dict]:
    """Get insights that have proven reliable enough to act on."""
    from lib.cognitive_learner import CognitiveLearner
    
    cognitive = CognitiveLearner()
    valuable = []
    
    for key, insight in cognitive.insights.items():
        if _is_low_value_insight(insight.insight):
            continue
        if (
            (insight.reliability >= min_reliability and insight.times_validated >= min_validations)
            or (high_validation_override and insight.times_validated >= high_validation_override)
        ):
            valuable.append({
                "insight_key": key,
                "category": insight.category.value,
                "insight": insight.insight,
                "reliability": insight.reliability,
                "validations": insight.times_validated,
                "promoted": insight.promoted,
            })
    
    # De-dupe by normalized insight text
    seen = set()
    deduped = []
    for item in valuable:
        key = _normalize_insight_text(item.get("insight") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    # Sort by actionability, then reliability * validations
    deduped.sort(
        key=lambda x: (_actionability_score(x.get("insight") or ""), x["reliability"] * x["validations"]),
        reverse=True,
    )
    return deduped


def get_recent_lessons() -> List[Dict]:
    """Get lessons extracted from surprises - these are gold."""
    from lib.aha_tracker import AhaTracker
    
    aha = AhaTracker()
    lessons = []
    
    for surprise in aha.get_recent_surprises(20):
        if isinstance(surprise, dict):
            lesson = surprise.get("lesson_extracted")
            if not lesson:
                continue
            lessons.append({
                "lesson": lesson,
                "from_prediction": (surprise.get("predicted_outcome") or "")[:50],
                "actual": (surprise.get("actual_outcome") or "")[:50],
                "type": surprise.get("surprise_type"),
            })
            continue
        if surprise.lesson_extracted:
            lessons.append({
                "lesson": surprise.lesson_extracted,
                "from_prediction": surprise.predicted_outcome[:50],
                "actual": surprise.actual_outcome[:50],
                "type": surprise.surprise_type,
            })
    
    return lessons[:10]  # Top 10 lessons


def get_failure_warnings(
    limit: int = 3,
    min_validations: int = 3,
    high_validation_override: int = HIGH_VALIDATION_OVERRIDE,
) -> List[Dict[str, Any]]:
    """Get high-signal failure patterns with short fixes."""
    from lib.cognitive_learner import CognitiveLearner

    cog = CognitiveLearner()
    warnings = []

    key_by_id = {id(v): k for k, v in cog.insights.items()}
    for ins in cog.get_self_awareness_insights():
        text = ins.insight or ""
        tl = text.lower()
        if _is_low_value_insight(text):
            continue
        if not (("fail" in tl) or ("error" in tl) or ("fix:" in tl) or ("timeout" in tl)):
            continue
        if not (
            ins.times_validated >= min_validations
            or (high_validation_override and ins.times_validated >= high_validation_override)
        ):
            continue
        warnings.append({
            "insight_key": key_by_id.get(id(ins)),
            "category": ins.category.value,
            "text": text,
            "reliability": ins.reliability,
            "validations": ins.times_validated,
        })

    # De-dupe variants (recovered X%)
    seen = set()
    deduped = []
    for item in warnings:
        key = _normalize_insight_text(item.get("text") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    deduped.sort(
        key=lambda x: (_actionability_score(x.get("text") or ""), x["validations"], x["reliability"]),
        reverse=True,
    )
    return deduped[: max(0, int(limit or 0))]


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
            if _is_low_value_insight(ins.insight):
                continue
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
                "entry_id": m.get("entry_id"),
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
                "memory_id": m.get("memory_id"),
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

    session_id = infer_latest_session_id()
    trace_id = infer_latest_trace_id(session_id)
    contextual = get_contextual_insights(query, limit=6) if query else []
    skills = get_relevant_skills(query, limit=3) if query else []
    insights = get_high_value_insights()
    warnings = get_failure_warnings()
    lessons = get_recent_lessons()
    opinions = get_strong_opinions()
    growth = get_growth_moments()
    project_profile = None
    try:
        project_profile = load_profile(Path.cwd())
    except Exception:
        project_profile = None
    advisor_block = ""
    if query:
        try:
            from lib.advisor import get_advisor
            advisor_block = get_advisor().generate_context_block("task", query, include_mind=False)
        except Exception as e:
            log_debug("bridge", "advisor block failed", e)

    # Record non-cognitive contextual exposures for prediction loop
    if contextual:
        try:
            exposures = []
            for item in contextual:
                if item.get("source") == "cognitive":
                    continue
                text = (item.get("text") or "").strip()
                if not text:
                    continue
                key = item.get("entry_id") or item.get("memory_id") or ""
                insight_key = f"{item.get('source')}:{key}" if key else None
                cat = item.get("category") or "memory"
                exposures.append({
                    "insight_key": insight_key,
                    "category": f"{item.get('source')}:{cat}",
                    "text": text[:240],
                })
            record_exposures("spark_context:contextual", exposures, session_id=session_id, trace_id=trace_id)
        except Exception:
            pass

    # Record skill exposures so prediction loop can validate skill outcomes
    if skills:
        try:
            q_snip = (query or "").replace("\n", " ").strip()
            if len(q_snip) > 120:
                q_snip = q_snip[:120] + "..."
            exposures = []
            for s in skills:
                sid = s.get("skill_id") or s.get("name") or "unknown-skill"
                desc = (s.get("description") or "").strip()
                if q_snip:
                    text = f"Skill {sid} for task {q_snip}: {desc}"
                else:
                    text = f"Skill {sid}: {desc}"
                exposures.append({
                    "insight_key": f"skill:{sid}",
                    "category": "skill",
                    "text": text[:240],
                })
            record_exposures("spark_context:skills", exposures, session_id=session_id, trace_id=trace_id)
        except Exception:
            pass
    
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

    if project_profile:
        lines.append("## Project Focus")
        phase = project_profile.get("phase") or ""
        done = project_profile.get("done") or ""
        if phase:
            lines.append(f"- Phase: {phase}")
        if done:
            lines.append(f"- Done means: {done}")
        goals = project_profile.get("goals") or []
        for g in goals[:3]:
            lines.append(f"- Goal: {g.get('text') or g}")
        milestones = project_profile.get("milestones") or []
        for m in milestones[:3]:
            status = (m.get("meta") or {}).get("status") or ""
            tag = f" [{status}]" if status else ""
            lines.append(f"- Milestone: {m.get('text')}{tag}")
        references = project_profile.get("references") or []
        for r in references[:2]:
            lines.append(f"- Reference: {r.get('text') or r}")
        transfers = project_profile.get("transfers") or []
        for t in transfers[:2]:
            lines.append(f"- Transfer: {t.get('text') or t}")
        lines.append("")

        questions = get_suggested_questions(project_profile, limit=3)
        if questions:
            lines.append("## Project Questions")
            for q in questions:
                lines.append(f"- {q.get('question')}")
            lines.append("")

        checkins = list_checkins(limit=2)
        if checkins:
            lines.append("## Outcome Check-in")
            for item in checkins:
                reason = item.get("reason") or item.get("event") or "check-in"
                lines.append(f"- {reason}")
            lines.append("")

    # Opportunity Scanner: self-Socratic path (Spark questions itself)
    self_ops = []
    try:
        self_ops = get_recent_self_opportunities(limit=2)
    except Exception as e:
        log_debug("bridge", "recent self opportunities failed", e)
    if self_ops:
        lines.append("## Opportunity Scanner")
        for row in self_ops[:2]:
            question = str(row.get("question") or "").strip()
            next_step = str(row.get("next_step") or "").strip()
            if not question:
                continue
            if next_step:
                lines.append(f"- [Spark] {question} -> {next_step}")
            else:
                lines.append(f"- [Spark] {question}")
        lines.append("")

    if contextual:
        lines.append("## Relevant Right Now")
        for item in contextual:
            src = (item.get("source") or "memory").strip().lower()
            cat = item.get("category") or "memory"
            txt = item.get("text")
            if src == "cognitive":
                lines.append(f"- [{cat}] {txt}")
            else:
                lines.append(f"- [{src}:{cat}] {txt}")
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

    if warnings:
        lines.append("## Warnings (avoid failures)")
        for w in warnings:
            lines.append(f"- [{w['category']}] {w['text']}")
        lines.append("")
        try:
            record_exposures(
                "spark_context:warnings",
                [
                    {"insight_key": w.get("insight_key"), "category": w.get("category"), "text": w.get("text")}
                    for w in warnings
                ],
                session_id=session_id,
                trace_id=trace_id,
            )
        except Exception:
            pass

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
        try:
            record_exposures(
                "spark_context:proven",
                [
                    {"insight_key": i.get("insight_key"), "category": i.get("category"), "text": i.get("insight")}
                    for i in insights[:5]
                ],
                session_id=session_id,
                trace_id=trace_id,
            )
        except Exception:
            pass
    
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
    SPARK_CONTEXT_FILE.write_text(context, encoding="utf-8")
    return context


def inject_to_memory(insight: str, category: str = "spark") -> bool:
    """Inject a high-value insight into MEMORY.md."""
    if not MEMORY_FILE.exists():
        return False
    
    content = MEMORY_FILE.read_text(encoding="utf-8")
    timestamp = datetime.now().strftime("%Y-%m-%d")
    
    # Find or create Spark Learnings section
    marker = "## Spark Learnings"
    if marker not in content:
        content += f"\n\n{marker}\n"
    
    # Add the insight
    new_line = f"- [{timestamp}] [{category}] {insight}\n"
    
    # Insert after the marker
    parts = content.split(marker)
    if len(parts) == 2:
        content = parts[0] + marker + "\n" + new_line + parts[1].lstrip("\n")
    
    MEMORY_FILE.write_text(content, encoding="utf-8")
    return True


def auto_promote_insights(min_reliability: float = 0.8, min_validations: int = 3):
    """Auto-promote highly reliable insights to MEMORY.md."""
    from lib.cognitive_learner import CognitiveLearner
    
    cognitive = CognitiveLearner()
    promoted_count = 0
    
    for key, insight in cognitive.insights.items():
        # Check if meets threshold and not already promoted
        if (insight.reliability >= min_reliability and 
            insight.times_validated >= min_validations and 
            not insight.promoted):
            
            # Inject to memory
            if inject_to_memory(insight.insight, insight.category.value):
                # Mark as promoted
                insight.promoted = True
                cognitive._save_insights()
                promoted_count += 1
    
    return promoted_count


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
            count = auto_promote_insights()
            print(f"OK Promoted {count} insights to MEMORY.md")
        
        elif cmd == "status":
            status = bridge_status()
            print(json.dumps(status, indent=2))
        
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: bridge.py [context|update|promote|status]")
    else:
        # Default: show status
        print(generate_active_context())
