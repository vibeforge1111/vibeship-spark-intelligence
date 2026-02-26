"""
Outcome log helpers for prediction validation.

Phase 3: Outcome-Driven Learning
- Link outcomes to specific insights for validation
- Support chip-scoped outcomes (per domain)
- Track outcome -> insight attribution for learning
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .file_lock import file_lock_for

OUTCOMES_FILE = Path.home() / ".spark" / "outcomes.jsonl"
OUTCOMES_FILE_MAX = 3000
OUTCOME_LINKS_FILE = Path.home() / ".spark" / "outcome_links.jsonl"
OUTCOME_LINKS_FILE_MAX = 3000


def _rotate_jsonl(path: Path, max_lines: int) -> None:
    """Trim a JSONL file to its last *max_lines* lines.

    Uses atomic temp-write + os.replace to avoid partial-write corruption.
    Callers should hold the per-file lock across append+rotate.
    """
    try:
        if not path.exists():
            return
        if path.stat().st_size // 250 <= max_lines:
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= max_lines:
            return
        keep = "\n".join(lines[-max_lines:]) + "\n"
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
        tmp.write_text(keep, encoding="utf-8")
        os.replace(str(tmp), str(path))
    except Exception:
        pass


def _hash_id(*parts: str) -> str:
    raw = "|".join(p or "" for p in parts).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def make_outcome_id(*parts: str) -> str:
    return _hash_id(*parts)


def _ensure_trace_id(row: Dict[str, Any]) -> None:
    if row.get("trace_id"):
        return
    try:
        from .exposure_tracker import infer_latest_trace_id
        trace_id = infer_latest_trace_id(row.get("session_id"))
        if trace_id:
            row["trace_id"] = trace_id
            return
    except Exception:
        pass
    # Fallback: deterministic trace_id so binding is never empty
    try:
        seed = f"{row.get('outcome_id','')}|{row.get('event_type','')}|{row.get('created_at','')}"
        row["trace_id"] = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return


def append_outcomes(rows: Iterable[Dict[str, Any]]) -> int:
    """Append outcome rows to the shared outcomes log. Returns count written."""
    if not rows:
        return 0
    OUTCOMES_FILE.parent.mkdir(parents=True, exist_ok=True)
    to_write: List[str] = []
    written = 0
    for row in rows:
        if not row:
            continue
        _ensure_trace_id(row)
        to_write.append(json.dumps(row, ensure_ascii=False) + "\n")
        written += 1
    if not to_write:
        return 0
    with file_lock_for(OUTCOMES_FILE, fail_open=False):
        with OUTCOMES_FILE.open("a", encoding="utf-8") as f:
            f.writelines(to_write)
        _rotate_jsonl(OUTCOMES_FILE, OUTCOMES_FILE_MAX)
    return written


def append_outcome(row: Dict[str, Any]) -> int:
    return append_outcomes([row] if row else [])


def build_explicit_outcome(
    result: str,
    text: str = "",
    *,
    tool: Optional[str] = None,
    created_at: Optional[float] = None,
    trace_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """Build an explicit outcome row from a user check-in."""
    res = (result or "").strip().lower()
    if res in {"yes", "y", "success", "ok", "good", "worked"}:
        polarity = "pos"
    elif res in {"partial", "mixed", "some", "meh", "unclear"}:
        polarity = "neutral"
    else:
        polarity = "neg"
    now = float(created_at or time.time())
    clean_text = (text or "").strip()
    if not clean_text:
        clean_text = f"explicit check-in: {res or 'unknown'}"
    row = {
        "outcome_id": make_outcome_id(str(now), res, clean_text[:120]),
        "event_type": "explicit_checkin",
        "tool": tool,
        "text": clean_text,
        "polarity": polarity,
        "result": res or "unknown",
        "created_at": now,
    }
    if trace_id:
        row["trace_id"] = trace_id
    return row, polarity


# =============================================================================
# Phase 3: Outcome-Insight Linking
# =============================================================================

def link_outcome_to_insight(
    outcome_id: str,
    insight_key: str,
    *,
    chip_id: Optional[str] = None,
    confidence: float = 1.0,
    notes: str = "",
) -> Dict[str, Any]:
    """
    Link an outcome to a specific insight for validation.

    This creates an explicit attribution between:
    - An outcome (something that happened - success/failure)
    - An insight (something Spark learned)

    The validation loop uses these links to validate/contradict insights.
    """
    link = {
        "link_id": _hash_id(outcome_id, insight_key, str(time.time())),
        "outcome_id": outcome_id,
        "insight_key": insight_key,
        "chip_id": chip_id,
        "confidence": confidence,
        "notes": notes,
        "created_at": time.time(),
        "validated": False,
    }

    OUTCOME_LINKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with file_lock_for(OUTCOME_LINKS_FILE, fail_open=False):
        with OUTCOME_LINKS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(link, ensure_ascii=False) + "\n")
        _rotate_jsonl(OUTCOME_LINKS_FILE, OUTCOME_LINKS_FILE_MAX)

    return link


def get_outcome_links(
    insight_key: Optional[str] = None,
    outcome_id: Optional[str] = None,
    chip_id: Optional[str] = None,
    limit: Optional[int] = 100,
) -> List[Dict[str, Any]]:
    """Get outcome-insight links, optionally filtered."""
    if not OUTCOME_LINKS_FILE.exists():
        return []

    links = []
    with OUTCOME_LINKS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                link = json.loads(line.strip())
                if insight_key and link.get("insight_key") != insight_key:
                    continue
                if outcome_id and link.get("outcome_id") != outcome_id:
                    continue
                if chip_id and link.get("chip_id") != chip_id:
                    continue
                links.append(link)
            except Exception:
                pass

    if limit is None or limit <= 0:
        return links
    return links[-limit:]


def read_outcomes(
    limit: Optional[int] = 100,
    polarity: Optional[str] = None,
    chip_id: Optional[str] = None,
    since: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Read outcomes from the log, optionally filtered."""
    if not OUTCOMES_FILE.exists():
        return []

    outcomes = []
    with OUTCOMES_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                outcome = json.loads(line.strip())
                if polarity and outcome.get("polarity") != polarity:
                    continue
                if chip_id and outcome.get("chip_id") != chip_id:
                    continue
                if since and (outcome.get("created_at", 0) < since):
                    continue
                outcomes.append(outcome)
            except Exception:
                pass

    if limit is None or limit <= 0:
        return outcomes
    return outcomes[-limit:]


def get_unlinked_outcomes(limit: int = 50) -> List[Dict[str, Any]]:
    """Get outcomes that haven't been linked to any insight yet."""
    outcomes = read_outcomes(limit=limit * 2)
    links = get_outcome_links(limit=None)

    linked_ids = {link.get("outcome_id") for link in links}
    unlinked = [o for o in outcomes if o.get("outcome_id") not in linked_ids]

    return unlinked[-limit:]


def build_chip_outcome(
    chip_id: str,
    outcome_type: str,
    result: str,
    *,
    insight: str = "",
    data: Optional[Dict] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build an outcome row for a chip-specific event.

    Args:
        chip_id: Which chip this outcome belongs to
        outcome_type: "positive", "negative", or "neutral"
        result: Description of what happened
        insight: The insight this validates/contradicts
        data: Additional outcome data (metrics, etc.)
    """
    polarity_map = {"positive": "pos", "negative": "neg", "neutral": "neutral"}
    polarity = polarity_map.get(outcome_type, "neutral")

    now = time.time()
    row = {
        "outcome_id": make_outcome_id(chip_id, str(now), result[:100]),
        "event_type": f"chip_{outcome_type}",
        "chip_id": chip_id,
        "text": result,
        "insight": insight,
        "polarity": polarity,
        "data": data or {},
        "created_at": now,
    }

    if session_id:
        row["session_id"] = session_id
    if trace_id:
        row["trace_id"] = trace_id

    return row


def get_outcome_stats(chip_id: Optional[str] = None) -> Dict[str, Any]:
    """Get outcome statistics, optionally filtered by chip (full-file scan)."""
    by_polarity = {"pos": 0, "neg": 0, "neutral": 0}
    total_outcomes = 0
    total_links = 0
    validated_links = 0
    linked_ids = set()

    if OUTCOME_LINKS_FILE.exists():
        with OUTCOME_LINKS_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    link = json.loads(line.strip())
                except Exception:
                    continue
                if chip_id and link.get("chip_id") != chip_id:
                    continue
                total_links += 1
                if link.get("validated"):
                    validated_links += 1
                oid = link.get("outcome_id")
                if oid:
                    linked_ids.add(oid)

    unlinked_count = 0
    if OUTCOMES_FILE.exists():
        with OUTCOMES_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    outcome = json.loads(line.strip())
                except Exception:
                    continue
                if chip_id and outcome.get("chip_id") != chip_id:
                    continue
                total_outcomes += 1
                pol = outcome.get("polarity", "neutral")
                by_polarity[pol] = by_polarity.get(pol, 0) + 1
                oid = outcome.get("outcome_id")
                if not oid or oid not in linked_ids:
                    unlinked_count += 1

    return {
        "total_outcomes": total_outcomes,
        "by_polarity": by_polarity,
        "total_links": total_links,
        "validated_links": validated_links,
        "unlinked": unlinked_count,
    }


# =============================================================================
# Phase 3.5: Auto-Linking Outcomes to Insights
# =============================================================================

def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords from text for matching."""
    import re
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "shall", "can", "need", "dare",
        "ought", "used", "to", "of", "in", "for", "on", "with", "at", "by",
        "from", "as", "into", "through", "during", "before", "after", "above",
        "below", "between", "under", "again", "further", "then", "once", "here",
        "there", "when", "where", "why", "how", "all", "each", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "and", "but", "if", "or",
        "because", "until", "while", "this", "that", "these", "those", "it",
        "its", "user", "prefers", "likes", "tool", "worked", "failed",
    }
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    return [w for w in words if w not in stopwords][:10]


def _compute_similarity(text1: str, text2: str) -> float:
    """Compute simple keyword overlap similarity between two texts."""
    kw1 = set(_extract_keywords(text1))
    kw2 = set(_extract_keywords(text2))
    if not kw1 or not kw2:
        return 0.0
    intersection = len(kw1 & kw2)
    union = len(kw1 | kw2)
    return intersection / union if union > 0 else 0.0


def auto_link_outcomes(
    min_similarity: float = 0.25,
    limit: int = 50,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Automatically link unlinked outcomes to relevant insights.

    Uses keyword similarity to match outcomes to insights.
    Only links if similarity exceeds min_similarity threshold.

    Args:
        min_similarity: Minimum similarity score to create a link (0.0-1.0)
        limit: Maximum unlinked outcomes to process
        dry_run: If True, don't create links, just return what would be linked

    Returns:
        Stats about linking: processed, linked, skipped, matches
    """
    from lib.cognitive_learner import get_cognitive_learner

    unlinked = get_unlinked_outcomes(limit=limit)
    if not unlinked:
        return {"processed": 0, "linked": 0, "skipped": 0, "matches": []}

    cog = get_cognitive_learner()
    insights = cog.insights

    stats = {"processed": 0, "linked": 0, "skipped": 0, "matches": []}

    for outcome in unlinked:
        stats["processed"] += 1
        outcome_text = outcome.get("text", "") or outcome.get("insight", "")
        outcome_id = outcome.get("outcome_id")

        if not outcome_text or not outcome_id:
            stats["skipped"] += 1
            continue

        # Find best matching insight
        best_match = None
        best_score = 0.0

        for key, insight in insights.items():
            insight_text = getattr(insight, "insight", "") or str(insight)
            score = _compute_similarity(outcome_text, insight_text)

            if score > best_score and score >= min_similarity:
                best_score = score
                best_match = (key, insight_text[:100])

        if best_match:
            if not dry_run:
                link_outcome_to_insight(
                    outcome_id=outcome_id,
                    insight_key=best_match[0],
                    chip_id=outcome.get("chip_id"),
                    confidence=best_score,
                    notes=f"auto-linked (similarity={best_score:.2f})",
                )
            stats["linked"] += 1
            stats["matches"].append({
                "outcome_id": outcome_id,
                "insight_key": best_match[0],
                "similarity": round(best_score, 3),
                "outcome_preview": outcome_text[:60],
                "insight_preview": best_match[1][:60],
            })
        else:
            stats["skipped"] += 1

    return stats


def get_linkable_candidates(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Preview which outcomes could be auto-linked and to what insights.

    Useful for reviewing before running auto_link_outcomes.
    """
    result = auto_link_outcomes(min_similarity=0.2, limit=limit, dry_run=True)
    return result.get("matches", [])
