"""
PatternAggregator: Combines all detectors and routes to EIDOS.

Responsibilities:
1. Run all detectors on each event
2. Wrap user requests in EIDOS Step envelopes (RequestTracker)
3. Aggregate patterns when multiple detectors corroborate
4. Trigger distillation when patterns accumulate (PatternDistiller)
5. Apply memory gate to filter low-value items
6. Route high-value patterns to EIDOS store

The key shift (Pattern → EIDOS Integration):
- User requests become trackable decision packets (Steps)
- Patterns become distilled rules (Distillations)
- Memory gate filters noise before storage
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import re

from .base import DetectedPattern, PatternType
from .correction import CorrectionDetector
from .sentiment import SentimentDetector
from .repetition import RepetitionDetector
from .semantic import SemanticIntentDetector
from .why import WhyDetector
from .engagement_surprise import EngagementSurpriseDetector
from .request_tracker import RequestTracker, get_request_tracker
from .distiller import PatternDistiller, get_pattern_distiller
from .memory_gate import MemoryGate, get_memory_gate
from ..primitive_filter import is_primitive_text
from ..importance_scorer import get_importance_scorer, ImportanceTier
from ..eidos.store import get_store


# Confidence threshold to trigger learning
# Lowered from 0.7 to let importance scorer do quality filtering
CONFIDENCE_THRESHOLD = 0.6

# Patterns log file
PATTERNS_LOG = Path.home() / ".spark" / "detected_patterns.jsonl"
DEDUPE_TTL_SECONDS = 600
MAX_TRACKED_SESSIONS = 300


def _normalize_text(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*\(\d+\s*calls?\)", "", t)
    t = re.sub(r"\s*\(\d+\)", "", t)
    return t.strip()


def _log_pattern(pattern: DetectedPattern):
    """Append pattern to log file."""
    try:
        PATTERNS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(PATTERNS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(pattern.to_dict()) + "\n")
    except Exception:
        pass


def _is_operational_insight(text: str) -> bool:
    """Return True for tool-telemetry or sequence-style insights."""
    try:
        from ..promoter import is_operational_insight
        return is_operational_insight(text)
    except Exception:
        return False


class PatternAggregator:
    """
    Aggregates patterns from all detectors and routes to EIDOS.

    Flow (Updated for Pattern → EIDOS Integration):
    1. Event comes in
    2. If user message: wrap in EIDOS Step envelope (RequestTracker)
    3. Each detector processes the event
    4. Patterns above threshold trigger learning
    5. Corroborated patterns get boosted
    6. Periodically distill completed Steps into Distillations
    7. Memory gate filters before persistence
    """

    # How often to run distillation (in events processed)
    DISTILLATION_INTERVAL = 20

    def __init__(self):
        self.detectors = [
            CorrectionDetector(),
            SentimentDetector(),
            RepetitionDetector(),
            SemanticIntentDetector(),
            WhyDetector(),  # Phase 4: Capture reasoning and principles
            EngagementSurpriseDetector(),  # Engagement Pulse: tweet over/underperform
        ]
        self._patterns_count = 0
        self._session_patterns: Dict[str, List[DetectedPattern]] = {}
        self._recent_pattern_keys: Dict[str, Dict[str, float]] = {}

        # EIDOS Integration components
        self._request_tracker = get_request_tracker()
        self._distiller = get_pattern_distiller()
        self._memory_gate = get_memory_gate()
        self._store = get_store()
        self._events_since_distillation = 0

        # Session → active step_id mapping.
        # When a user message creates a Step, we store its step_id here
        # so subsequent tool-use events in the same session can be linked.
        self._session_step_ids: Dict[str, str] = {}

        # Importance scoring stats
        self._importance_stats = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "ignored": 0,
        }

        # EIDOS integration stats
        self._eidos_stats = {
            "steps_created": 0,
            "steps_completed": 0,
            "steps_persisted": 0,
            "step_persist_failures": 0,
            "distillations_created": 0,
            "gate_rejections": 0,
        }

    def process_event(self, event: Dict) -> List[DetectedPattern]:
        """
        Process event through all detectors.

        Enhanced with EIDOS integration:
        - User messages become Step envelopes
        - Actions update pending Steps
        - Outcomes complete Steps
        - Periodic distillation of completed Steps

        Returns list of detected patterns.
        """
        all_patterns: List[DetectedPattern] = []

        # === EIDOS INTEGRATION: Handle user requests ===
        event_type = event.get("type", "")
        session_id = event.get("session_id", "")
        trace_id = event.get("trace_id")
        if not trace_id:
            payload = event.get("payload") or {}
            if isinstance(payload, dict):
                trace_id = payload.get("trace_id")
        step_id = event.get("step_id")

        # Auto-resolve step_id from session tracking when not in event.
        # This bridges the gap: user_message creates a Step with a step_id,
        # but subsequent tool-use events don't carry it.  We propagate it
        # via the session → step_id mapping.
        if not step_id and session_id:
            step_id = self._session_step_ids.get(session_id)

        # If user message, wrap in Step envelope
        if event_type == "user_message" and event.get("content"):
            # Auto-complete previous step for this session (implicit SUCCESS).
            # If the user sent a new message, the previous action was
            # satisfactory enough that they moved on.
            prev_step_id = self._session_step_ids.get(session_id)
            if prev_step_id and prev_step_id in self._request_tracker.pending:
                completed = self._request_tracker.on_outcome(
                    step_id=prev_step_id,
                    result="User moved to next request (implicit success)",
                    success=True,
                )
                if completed:
                    self._eidos_stats["steps_completed"] += 1
                    try:
                        self._store.save_step(completed)
                        self._eidos_stats["steps_persisted"] += 1
                    except Exception:
                        self._eidos_stats["step_persist_failures"] += 1

            step = self._request_tracker.on_user_message(
                message=event["content"],
                episode_id=event.get("episode_id", "default"),
                context={
                    "project": event.get("project"),
                    "phase": event.get("phase"),
                    "prior_actions": event.get("prior_actions", []),
                    "session_id": session_id,
                },
                trace_id=trace_id
            )
            event["step_id"] = step.step_id
            # Track this session's active step_id
            if session_id:
                self._session_step_ids[session_id] = step.step_id
                # Bound the mapping to prevent unbounded growth
                if len(self._session_step_ids) > MAX_TRACKED_SESSIONS:
                    oldest = next(iter(self._session_step_ids))
                    del self._session_step_ids[oldest]
            self._eidos_stats["steps_created"] += 1
            try:
                self._store.save_step(step)
                self._eidos_stats["steps_persisted"] += 1
            except Exception:
                self._eidos_stats["step_persist_failures"] += 1

        # If action completed, update pending Step
        elif event_type == "action_complete" and step_id:
            self._request_tracker.on_action_taken(
                step_id=step_id,
                decision=event.get("action") or event.get("tool_name") or "",
                tool_used=event.get("tool") or event.get("tool_name") or "",
                alternatives_considered=event.get("alternatives"),
            )

        # If outcome observed, complete the Step
        elif event_type in ("success", "failure", "user_feedback") and step_id:
            completed = self._request_tracker.on_outcome(
                step_id=step_id,
                result=event.get("result") or event.get("error") or "",
                success=event_type != "failure",
                validation_evidence=event.get("evidence", ""),
                user_feedback=event.get("feedback"),
            )
            if completed:
                self._eidos_stats["steps_completed"] += 1
                # Clear session tracking since step is done
                if session_id and self._session_step_ids.get(session_id) == step_id:
                    del self._session_step_ids[session_id]
                try:
                    self._store.save_step(completed)
                    self._eidos_stats["steps_persisted"] += 1
                except Exception:
                    self._eidos_stats["step_persist_failures"] += 1

        # Time out stale pending requests using configured max age.
        timed_out_steps = self._request_tracker.timeout_pending()
        if timed_out_steps:
            self._eidos_stats["steps_completed"] += len(timed_out_steps)
            for step in timed_out_steps:
                try:
                    self._store.save_step(step)
                    self._eidos_stats["steps_persisted"] += 1
                except Exception:
                    self._eidos_stats["step_persist_failures"] += 1

        # === Run all pattern detectors ===
        for detector in self.detectors:
            try:
                patterns = detector.process_event(event)
                all_patterns.extend(patterns)
            except Exception as e:
                # Log but don't fail
                pass

        # Aggregate corroborating patterns
        all_patterns = self._boost_corroborated(all_patterns)

        # Track patterns by session
        session_id = event.get("session_id", "unknown")
        if session_id not in self._session_patterns:
            self._session_patterns[session_id] = []

        # De-dupe patterns within a TTL window to avoid spammy insights.
        all_patterns = self._dedupe_patterns(session_id, all_patterns)

        # Drop primitive/operational suggestions early.
        filtered: List[DetectedPattern] = []
        for pattern in all_patterns:
            suggested = pattern.suggested_insight or ""
            if suggested and is_primitive_text(suggested):
                continue
            filtered.append(pattern)
        all_patterns = filtered

        for pattern in all_patterns:
            self._patterns_count += 1
            self._session_patterns[session_id].append(pattern)
            _log_pattern(pattern)

        # Trim session patterns
        if len(self._session_patterns[session_id]) > 100:
            self._session_patterns[session_id] = self._session_patterns[session_id][-100:]

        self._prune_session_state()

        # === EIDOS INTEGRATION: Periodic distillation ===
        self._events_since_distillation += 1
        if self._events_since_distillation >= self.DISTILLATION_INTERVAL:
            self._run_distillation()
            self._events_since_distillation = 0

        return all_patterns

    def _prune_session_state(self) -> None:
        """Bound per-session tracking maps to prevent unbounded growth."""
        while len(self._session_patterns) > MAX_TRACKED_SESSIONS:
            oldest_session_id = next(iter(self._session_patterns))
            self._session_patterns.pop(oldest_session_id, None)
            self._recent_pattern_keys.pop(oldest_session_id, None)
            self._session_step_ids.pop(oldest_session_id, None)

        while len(self._recent_pattern_keys) > MAX_TRACKED_SESSIONS:
            oldest_session_id = next(iter(self._recent_pattern_keys))
            self._recent_pattern_keys.pop(oldest_session_id, None)

    def _run_distillation(self):
        """Run distillation on completed Steps to create Distillations."""
        completed_steps = self._request_tracker.get_completed_steps(limit=50)
        if len(completed_steps) < 3:
            return

        try:
            distillations = self._distiller.distill_from_steps(completed_steps)
            self._eidos_stats["distillations_created"] += len(distillations)
        except Exception as e:
            # Log but don't fail
            pass

    def force_distillation(self) -> int:
        """Force immediate distillation. Returns count of distillations created."""
        completed_steps = self._request_tracker.get_completed_steps(limit=100)
        if len(completed_steps) < 3:
            return 0

        try:
            distillations = self._distiller.distill_from_steps(completed_steps)
            self._eidos_stats["distillations_created"] += len(distillations)
            return len(distillations)
        except Exception:
            return 0

    def _pattern_key(self, pattern: DetectedPattern) -> str:
        base = pattern.suggested_insight or " ".join(pattern.evidence[:1]) or ""
        return f"{pattern.pattern_type.value}:{_normalize_text(base)}"

    def _dedupe_patterns(self, session_id: str, patterns: List[DetectedPattern]) -> List[DetectedPattern]:
        now = time.time()
        if session_id not in self._recent_pattern_keys:
            self._recent_pattern_keys[session_id] = {}

        recent = self._recent_pattern_keys[session_id]
        # Prune expired keys
        for k, ts in list(recent.items()):
            if now - ts > DEDUPE_TTL_SECONDS:
                del recent[k]

        out: List[DetectedPattern] = []
        for p in patterns:
            key = self._pattern_key(p)
            if not key or key in recent:
                continue
            recent[key] = now
            out.append(p)
        return out

    def _boost_corroborated(self, patterns: List[DetectedPattern]) -> List[DetectedPattern]:
        """
        Boost confidence when multiple patterns support the same insight.

        For example:
        - Correction + Frustration = stronger signal
        - Repetition + Frustration = user really wants this
        """
        if len(patterns) < 2:
            return patterns

        # Check for corroborating combinations
        pattern_types = {p.pattern_type for p in patterns}

        # Frustration + Correction = very strong signal
        if PatternType.CORRECTION in pattern_types and PatternType.FRUSTRATION in pattern_types:
            for p in patterns:
                if p.pattern_type in (PatternType.CORRECTION, PatternType.FRUSTRATION):
                    p.confidence = min(0.99, p.confidence + 0.15)
                    p.evidence.append("CORROBORATED: Correction + Frustration detected together")

        # Repetition + Frustration = persistent issue
        if PatternType.REPETITION in pattern_types and PatternType.FRUSTRATION in pattern_types:
            for p in patterns:
                if p.pattern_type in (PatternType.REPETITION, PatternType.FRUSTRATION):
                    p.confidence = min(0.99, p.confidence + 0.1)
                    p.evidence.append("CORROBORATED: Repetition + Frustration detected together")

        return patterns

    def trigger_learning(self, patterns: List[DetectedPattern]) -> List[Dict]:
        """
        Route patterns to CognitiveLearner for insight creation.

        Uses ImportanceScorer to assess importance at INGESTION time.
        This is the key improvement: importance != repetition.
        """
        from ..cognitive_learner import get_cognitive_learner, CognitiveCategory

        learner = get_cognitive_learner()
        scorer = get_importance_scorer()
        insights_created = []

        for pattern in patterns:
            if not pattern.suggested_insight:
                continue
            if is_primitive_text(pattern.suggested_insight):
                continue
            if _is_operational_insight(pattern.suggested_insight):
                continue

            # NEW: Score importance at ingestion, not just confidence
            importance = scorer.score(
                pattern.suggested_insight,
                context={
                    "source": pattern.pattern_type.value,
                    "has_outcome": bool(pattern.context.get("outcome")),
                }
            )

            # Combine pattern confidence with importance score
            # Critical/High importance can bypass low confidence threshold
            effective_confidence = pattern.confidence

            if importance.tier == ImportanceTier.CRITICAL:
                # Critical importance always learns, even with lower confidence
                effective_confidence = max(pattern.confidence, 0.85)
            elif importance.tier == ImportanceTier.HIGH:
                # High importance gets boosted
                effective_confidence = max(pattern.confidence, importance.score)
            elif importance.tier == ImportanceTier.IGNORE:
                # Ignore tier never learns
                self._importance_stats["ignored"] = self._importance_stats.get("ignored", 0) + 1
                continue

            # Apply original confidence threshold, but with importance-adjusted confidence
            if effective_confidence < CONFIDENCE_THRESHOLD:
                continue

            # Map pattern type to cognitive category (override if detector suggests one)
            category_map = {
                PatternType.CORRECTION: CognitiveCategory.USER_UNDERSTANDING,
                PatternType.SATISFACTION: CognitiveCategory.USER_UNDERSTANDING,
                PatternType.FRUSTRATION: CognitiveCategory.SELF_AWARENESS,
                PatternType.REPETITION: CognitiveCategory.USER_UNDERSTANDING,
                PatternType.STYLE: CognitiveCategory.USER_UNDERSTANDING,
                PatternType.ENGAGEMENT_SURPRISE: CognitiveCategory.REASONING,
            }

            category = category_map.get(pattern.pattern_type, CognitiveCategory.CONTEXT)
            if pattern.suggested_category:
                try:
                    category = CognitiveCategory(pattern.suggested_category)
                except Exception:
                    pass

            # Create insight through unified validation
            from lib.validate_and_store import validate_and_store_insight
            insight = validate_and_store_insight(
                text=pattern.suggested_insight,
                category=category,
                context=f"Detected from {pattern.pattern_type.value} pattern (importance: {importance.tier.value})",
                confidence=effective_confidence,
                source="pattern_aggregator",
            )

            # Track importance distribution
            self._importance_stats[importance.tier.value] = (
                self._importance_stats.get(importance.tier.value, 0) + 1
            )

            insight_info = {
                "pattern_type": pattern.pattern_type.value,
                "insight": pattern.suggested_insight,
                "confidence": effective_confidence,
                "importance_tier": importance.tier.value,
                "importance_score": importance.score,
                "importance_reasons": importance.reasons,
            }

            # === INTELLIGENCE SYSTEM INTEGRATION ===

            # 1. Check for contradictions with existing beliefs
            try:
                from ..contradiction_detector import check_for_contradiction
                contradiction = check_for_contradiction(pattern.suggested_insight)
                if contradiction:
                    insight_info["contradiction_detected"] = {
                        "existing": contradiction.existing_text[:100],
                        "type": contradiction.contradiction_type.value,
                        "confidence": contradiction.confidence,
                    }
            except Exception:
                pass

            # 2. Knowledge gaps (DEPRECATED: curiosity_engine never wired to production)
            # Kept as no-op for reference; curiosity_engine may be revisited.
            # try:
            #     from ..curiosity_engine import identify_knowledge_gaps
            #     gaps = identify_knowledge_gaps(pattern.suggested_insight)
            #     if gaps:
            #         insight_info["knowledge_gaps"] = [
            #             {"type": g.gap_type.value, "question": g.question}
            #             for g in gaps[:2]
            #         ]
            # except Exception:
            #     pass

            # 3. Feed to hypothesis tracker (pattern -> hypothesis)
            try:
                from ..hypothesis_tracker import observe_for_hypothesis
                hypothesis = observe_for_hypothesis(
                    pattern.suggested_insight,
                    domain=pattern.context.get("domain", "")
                )
                if hypothesis:
                    insight_info["hypothesis_generated"] = {
                        "id": hypothesis.hypothesis_id,
                        "statement": hypothesis.statement[:100],
                        "confidence": hypothesis.confidence,
                    }
            except Exception:
                pass

            insights_created.append(insight_info)

        return insights_created

    def get_session_patterns(self, session_id: str) -> List[DetectedPattern]:
        """Get all patterns detected for a session."""
        return self._session_patterns.get(session_id, [])

    def _get_logged_patterns_count(self) -> int:
        """Get count of patterns from persistent log file."""
        if not PATTERNS_LOG.exists():
            return 0
        try:
            lines = PATTERNS_LOG.read_text(encoding="utf-8").strip().split("\n")
            return len([l for l in lines if l.strip()])
        except Exception:
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregator statistics."""
        # Include both in-memory (session) and persistent (all-time) counts
        logged_count = self._get_logged_patterns_count()
        return {
            "total_patterns_detected": self._patterns_count,
            "total_patterns_logged": logged_count,  # Persistent count from log file
            "active_sessions": len(self._session_patterns),
            "detectors": [d.get_stats() for d in self.detectors],
            "importance_distribution": self._importance_stats,
            # EIDOS integration stats
            "eidos": {
                **self._eidos_stats,
                "request_tracker": self._request_tracker.get_stats(),
                "distiller": self._distiller.get_stats(),
                "memory_gate": self._memory_gate.get_stats(),
            },
        }


# Singleton instance
_aggregator: Optional[PatternAggregator] = None


def get_aggregator() -> PatternAggregator:
    """Get the global pattern aggregator instance."""
    global _aggregator
    if _aggregator is None:
        _aggregator = PatternAggregator()
    return _aggregator
