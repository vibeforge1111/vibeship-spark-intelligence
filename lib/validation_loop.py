"""
Lightweight validation loop for user preference + communication insights.

Phase 3: Outcome-Driven Learning
- Validates insights using explicit outcomes (not just prompt analysis)
- Links outcomes to insights for attribution
- Supports chip-scoped validation
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib.queue import read_events, count_events, EventType
from lib.cognitive_learner import get_cognitive_learner, CognitiveCategory, _boost_confidence
from lib.aha_tracker import get_aha_tracker, SurpriseType
from lib.diagnostics import log_debug
from lib.outcome_log import (
    get_outcome_links,
    read_outcomes,
    OUTCOME_LINKS_FILE,
)


STATE_FILE = Path.home() / ".spark" / "validation_state.json"

# Words that do not carry preference meaning for matching.
STOPWORDS = {
    "user", "prefers", "prefer", "likes", "like", "love", "loves", "hates", "hate",
    "dislike", "dislikes", "dont", "don't", "do", "not", "no", "never", "avoid",
    "please", "use", "using", "for", "to", "and", "the", "a", "an", "of", "in", "on",
    "with", "this", "that", "these", "those", "is", "are", "be", "as", "it", "its",
    "when", "about", "need", "want", "should", "must",
}

POS_TRIGGERS = {
    "prefer", "like", "love", "want", "need", "please", "use", "using", "require",
    "should", "must", "explain", "examples", "example", "brief", "short", "detailed",
    "step", "steps", "walk", "show",
    # Implicit validation words (added 2026-02-21 pipeline audit)
    "good", "great", "perfect", "works", "better", "best", "correct", "right",
    "always", "keep", "continue", "thanks", "exactly", "yes",
}

NEG_TRIGGERS = {
    "no", "not", "never", "avoid", "dont", "stop", "without", "hate", "dislike",
    # Implicit contradiction words (added 2026-02-21 pipeline audit)
    "wrong", "bad", "broken", "fix", "change", "instead", "rather", "redo", "failed",
}

NEG_PREF_WORDS = {"hate", "dislike", "don't like", "dont like", "avoid", "never"}
POS_PREF_WORDS = {"prefer", "like", "love", "want", "need"}


def _load_state() -> Dict:
    if not STATE_FILE.exists():
        return {"offset": 0}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"offset": 0}


def _save_state(state: Dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=STATE_FILE.parent, suffix=".tmp")
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, STATE_FILE)


def _normalize_text(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("don't", "dont").replace("do not", "dont")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _tokenize(text: str) -> List[str]:
    return _normalize_text(text).split()


def _extract_keywords(text: str, max_terms: int = 3) -> List[str]:
    tokens = _tokenize(text)
    out: List[str] = []
    for tok in tokens:
        if tok in STOPWORDS:
            continue
        if tok not in out:
            out.append(tok)
        if len(out) >= max_terms:
            break
    return out


def _insight_polarity(insight_text: str) -> Optional[str]:
    t = _normalize_text(insight_text)
    if any(p in t for p in POS_PREF_WORDS):
        return "pos"
    if any(p in t for p in NEG_PREF_WORDS):
        return "neg"
    return None


def _prompt_polarity(tokens: List[str], keyword_positions: List[int]) -> Optional[str]:
    if not keyword_positions:
        return None
    has_pos = False
    has_neg = False
    for idx in keyword_positions:
        start = max(0, idx - 3)
        end = min(len(tokens), idx + 4)
        window = tokens[start:end]
        if any(w in NEG_TRIGGERS for w in window):
            has_neg = True
        if any(w in POS_TRIGGERS for w in window):
            has_pos = True

    if has_neg and not has_pos:
        return "neg"
    if has_pos and not has_neg:
        return "pos"
    if has_neg and has_pos:
        return "neg"
    return None


def _match_insight(prompt_tokens: List[str], insight_text: str) -> Tuple[bool, Optional[str]]:
    """Return (matched, polarity) where polarity is 'pos'/'neg'/None."""
    keywords = _extract_keywords(insight_text, max_terms=3)
    if not keywords:
        return False, None

    positions = []
    token_set = set(prompt_tokens)
    for kw in keywords:
        if kw not in token_set:
            continue
        # record the first occurrence position for polarity window checks
        try:
            positions.append(prompt_tokens.index(kw))
        except Exception:
            continue

    if not positions:
        return False, None

    polarity = _prompt_polarity(prompt_tokens, positions)
    return True, polarity


def _apply_validation(
    insight_key: str,
    insight,
    polarity: str,
    prompt_text: str,
    *,
    stats: Dict[str, int],
) -> None:
    cog = get_cognitive_learner()
    insight_polarity = _insight_polarity(insight.insight)

    validated = False
    contradicted = False

    if polarity == "pos":
        if insight_polarity == "neg":
            contradicted = True
        else:
            validated = True
    elif polarity == "neg":
        if insight_polarity == "pos":
            contradicted = True
        else:
            validated = True

    if validated:
        cog._touch_validation(insight, validated_delta=1)
        insight.confidence = _boost_confidence(insight.confidence, 1)
        insight.evidence.append(prompt_text[:200])
        insight.evidence = insight.evidence[-10:]
        stats["validated"] += 1
    elif contradicted:
        cog._touch_validation(insight, contradicted_delta=1)
        insight.counter_examples.append(prompt_text[:200])
        insight.counter_examples = insight.counter_examples[-10:]
        stats["contradicted"] += 1

        # Capture surprise if a previously reliable insight gets contradicted
        if insight.reliability >= 0.7 and insight.times_validated >= 2:
            try:
                tracker = get_aha_tracker()
                tracker.capture_surprise(
                    surprise_type=SurpriseType.UNEXPECTED_FAILURE,
                    predicted=f"Expected: {insight.insight}",
                    actual=f"User said: {prompt_text[:120]}",
                    confidence_gap=min(1.0, insight.reliability),
                    context={"tool": "validation", "insight": insight.insight},
                    lesson=f"Preference may have changed: {insight.insight[:60]}",
                )
                stats["surprises"] += 1
            except Exception as e:
                log_debug("validation", "surprise capture failed", e)

    if validated or contradicted:
        cog.insights[insight_key] = insight


def process_validation_events(limit: int = 200) -> Dict[str, int]:
    """Process queued user prompts and validate preference/communication insights."""
    state = _load_state()
    offset = int(state.get("offset", 0))

    total = count_events()
    if total < offset:
        offset = max(0, total - limit)

    events = read_events(limit=limit, offset=offset)
    if not events:
        return {"processed": 0, "validated": 0, "contradicted": 0, "surprises": 0}

    cog = get_cognitive_learner()
    # Validate all insight categories, not just preference/communication.
    # Reasoning, wisdom, meta_learning, context, and self_awareness insights
    # also benefit from validation against user prompts.
    candidates = {k: v for k, v in cog.insights.items()}

    stats = {"processed": 0, "validated": 0, "contradicted": 0, "surprises": 0}

    for ev in events:
        stats["processed"] += 1
        if ev.event_type != EventType.USER_PROMPT:
            continue

        payload = (ev.data or {}).get("payload") or {}
        role = payload.get("role") or "user"
        if role != "user":
            continue

        text = str(payload.get("text") or "").strip()
        if not text:
            continue

        tokens = _tokenize(text)
        if not tokens:
            continue

        token_set = set(tokens)
        has_pref_language = bool(token_set & POS_TRIGGERS or token_set & NEG_TRIGGERS)

        for key, insight in candidates.items():
            # For user_understanding/communication: require preference language
            if insight.category in (CognitiveCategory.USER_UNDERSTANDING, CognitiveCategory.COMMUNICATION):
                if not has_pref_language:
                    continue
            matched, polarity = _match_insight(tokens, insight.insight)
            if not matched:
                continue
            # For non-preference insights, keyword match with no polarity
            # is a soft positive validation (topic relevance).
            if not polarity:
                if insight.category in (CognitiveCategory.USER_UNDERSTANDING, CognitiveCategory.COMMUNICATION):
                    continue  # preference insights need explicit polarity
                polarity = "pos"
            _apply_validation(key, insight, polarity, text, stats=stats)

    if stats["validated"] or stats["contradicted"]:
        cog._save_insights()

    state["offset"] = offset + len(events)
    state["last_run_ts"] = time.time()
    state["last_stats"] = stats
    _save_state(state)

    return stats


def get_validation_backlog() -> int:
    """Return the count of queued events not yet processed by validation."""
    state = _load_state()
    try:
        offset = int(state.get("offset", 0))
    except Exception:
        offset = 0
    total = count_events()
    if total < offset:
        offset = total
    return max(0, total - offset)


def get_validation_state() -> Dict:
    """Return last validation run stats and timestamp."""
    state = _load_state()
    return {
        "last_run_ts": state.get("last_run_ts"),
        "last_stats": state.get("last_stats") or {},
        "offset": state.get("offset", 0),
    }


# =============================================================================
# Phase 3: Outcome-Driven Validation
# =============================================================================

def process_outcome_validation(limit: int = 100) -> Dict[str, int]:
    """
    Validate insights using explicit outcome links.

    This is different from process_validation_events which uses prompt analysis.
    This function uses explicit outcome -> insight links to validate.
    """
    cog = get_cognitive_learner()
    links = get_outcome_links(limit=limit)

    # Filter to unvalidated links
    unvalidated = [link for link in links if not link.get("validated")]

    if not unvalidated:
        return {"processed": 0, "validated": 0, "contradicted": 0, "surprises": 0}

    # Get outcomes for these links
    outcomes = read_outcomes(limit=limit * 2)
    outcome_map = {o.get("outcome_id"): o for o in outcomes}

    stats = {"processed": 0, "validated": 0, "contradicted": 0, "surprises": 0}
    updated_links = []

    for link in unvalidated:
        outcome_id = link.get("outcome_id")
        insight_key = link.get("insight_key")

        if not outcome_id or not insight_key:
            continue

        outcome = outcome_map.get(outcome_id)
        if not outcome:
            continue

        insight = cog.insights.get(insight_key)
        if not insight:
            continue

        stats["processed"] += 1
        polarity = outcome.get("polarity", "neutral")

        # Apply validation based on outcome polarity
        if polarity == "pos":
            cog._touch_validation(insight, validated_delta=1)
            insight.confidence = _boost_confidence(insight.confidence, 1)
            insight.evidence.append(f"Outcome: {outcome.get('text', '')[:150]}")
            insight.evidence = insight.evidence[-10:]
            stats["validated"] += 1
            link["validated"] = True
            link["validation_result"] = "validated"

        elif polarity == "neg":
            cog._touch_validation(insight, contradicted_delta=1)
            insight.counter_examples.append(f"Outcome: {outcome.get('text', '')[:150]}")
            insight.counter_examples = insight.counter_examples[-10:]
            stats["contradicted"] += 1
            link["validated"] = True
            link["validation_result"] = "contradicted"

            # Capture surprise if reliable insight contradicted
            if insight.reliability >= 0.7 and insight.times_validated >= 2:
                try:
                    tracker = get_aha_tracker()
                    tracker.capture_surprise(
                        surprise_type=SurpriseType.UNEXPECTED_FAILURE,
                        predicted=f"Expected: {insight.insight[:100]}",
                        actual=f"Outcome: {outcome.get('text', '')[:100]}",
                        confidence_gap=min(1.0, insight.reliability),
                        context={"tool": "outcome_validation", "chip_id": link.get("chip_id")},
                        lesson=f"Insight may need revision: {insight.insight[:60]}",
                    )
                    stats["surprises"] += 1
                except Exception as e:
                    log_debug("outcome_validation", "surprise capture failed", e)

        else:
            # Neutral - mark as processed but no validation effect
            link["validated"] = True
            link["validation_result"] = "neutral"

        cog.insights[insight_key] = insight
        updated_links.append(link)

    # Save updated insights
    if stats["validated"] or stats["contradicted"]:
        cog._save_insights()

    # Rewrite outcome links with validation status
    if updated_links:
        _update_outcome_links(updated_links)

    return stats


def _update_outcome_links(updated_links: List[Dict]) -> None:
    """Update outcome links file with validation results."""
    if not OUTCOME_LINKS_FILE.exists():
        return

    # Read all links
    all_links = []
    with OUTCOME_LINKS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                all_links.append(json.loads(line.strip()))
            except Exception:
                pass

    # Update the validated links
    updated_map = {link.get("link_id"): link for link in updated_links}
    for i, link in enumerate(all_links):
        if link.get("link_id") in updated_map:
            all_links[i] = updated_map[link.get("link_id")]

    # Rewrite file atomically.
    tmp = OUTCOME_LINKS_FILE.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for link in all_links:
            f.write(json.dumps(link, ensure_ascii=False) + "\n")
    tmp.replace(OUTCOME_LINKS_FILE)


def get_insight_outcome_coverage() -> Dict[str, Any]:
    """
    Calculate what percentage of insights have outcome evidence.

    This is a key metric for outcome-driven learning:
    - Higher coverage = more validated insights
    - Lower coverage = more speculation
    """
    cog = get_cognitive_learner()
    links = get_outcome_links(limit=5000)

    # Count insights with at least one outcome link
    linked_insights = set()
    validated_insights = set()

    for link in links:
        insight_key = link.get("insight_key")
        if insight_key:
            linked_insights.add(insight_key)
            if link.get("validated"):
                validated_insights.add(insight_key)

    total_insights = len(cog.insights)
    linked_count = len(linked_insights)
    validated_count = len(validated_insights)

    coverage = linked_count / total_insights if total_insights > 0 else 0
    validation_rate = validated_count / linked_count if linked_count > 0 else 0

    return {
        "total_insights": total_insights,
        "insights_with_outcomes": linked_count,
        "insights_validated": validated_count,
        "outcome_coverage": round(coverage, 3),
        "validation_rate": round(validation_rate, 3),
    }
