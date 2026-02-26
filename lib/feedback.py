"""Lightweight feedback loop to improve skills + self-awareness reliability."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .cognitive_learner import get_cognitive_learner
from .skills_router import recommend_skills
from .outcome_log import append_outcomes, make_outcome_id


SKILLS_EFFECTIVENESS_FILE = Path.home() / ".spark" / "skills_effectiveness.json"


def _load_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(path: Path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def update_skill_effectiveness(query: str, success: bool, limit: int = 2) -> None:
    """Update skill effectiveness counters for top-matched skills."""
    q = (query or "").strip()
    if not q:
        return

    skills = recommend_skills(q, limit=limit)
    if not skills:
        return

    trace_id = None
    try:
        from .exposure_tracker import infer_latest_trace_id
        trace_id = infer_latest_trace_id()
    except Exception:
        trace_id = None

    outcomes = []
    now = time.time()
    data = _load_json(SKILLS_EFFECTIVENESS_FILE)
    for s in skills:
        sid = s.get("skill_id") or s.get("name")
        if not sid:
            continue
        stats = data.get(sid, {"success": 0, "fail": 0})
        if success:
            stats["success"] = int(stats.get("success", 0)) + 1
        else:
            stats["fail"] = int(stats.get("fail", 0)) + 1
        data[sid] = stats
        outcomes.append({
            "outcome_id": make_outcome_id(str(now), "skill", sid, q[:120]),
            "event_type": "skill_result",
            "tool": None,
            "text": f"skill {sid} {'succeeded' if success else 'failed'} for {q[:120]}",
            "polarity": "pos" if success else "neg",
            "created_at": now,
            "domain": "skills",
            "skill_id": sid,
            "query": q[:200],
            "trace_id": trace_id,
        })

    _save_json(SKILLS_EFFECTIVENESS_FILE, data)
    append_outcomes(outcomes)


def update_self_awareness_reliability(tool_name: str, success: bool) -> None:
    """Increment reliability counters for self-awareness insights about a tool.

    Rate-limited: updates at most ONE insight per call to prevent
    contradiction-bombing where every successful tool call contradicts
    all self-awareness insights that mention the tool name.

    Only matches insights where the tool name appears in the insight KEY
    (not just anywhere in the text) for precision.
    """
    t = (tool_name or "").lower().strip()
    if not t:
        return

    cog = get_cognitive_learner()
    # Find the MOST relevant insight by matching tool name in the key
    best_key = None
    best_insight = None
    for key, insight in cog.insights.items():
        if insight.category.value != "self_awareness":
            continue
        # Match on key for precision (keys contain the tool name explicitly)
        if t in key.lower():
            if best_insight is None or insight.times_validated > best_insight.times_validated:
                best_key = key
                best_insight = insight

    if best_insight is None:
        return

    if success:
        best_insight.times_validated += 1
    else:
        best_insight.times_contradicted += 1
    best_insight.last_validated_at = datetime.now().isoformat()
    cog._save_insights()
