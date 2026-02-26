"""
PatternDistiller: Convert detected patterns into EIDOS Distillations.

This is the bridge between pattern detection and durable intelligence.
Instead of storing raw "User persistently asking about X" insights,
we distill patterns into actionable rules:

- HEURISTIC: "When X, do Y" (from successful patterns)
- ANTI_PATTERN: "Never do X because..." (from failed patterns)
- SHARP_EDGE: "Watch out for X in context Y" (from surprises)
- PLAYBOOK: Step-by-step procedure (from repeated sequences)

Only patterns that pass the memory gate become Distillations.
"""

import hashlib
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..eidos.models import (
    Step, Distillation, DistillationType, Evaluation, ActionType
)
from ..eidos.store import get_store
from ..primitive_filter import is_primitive_text
from ..promoter import is_operational_insight


@dataclass
class DistillationCandidate:
    """A potential distillation before memory gate scoring."""
    distillation: Distillation
    source_steps: List[Step]
    gate_score: float = 0.0
    gate_reasons: List[str] = None

    def __post_init__(self):
        if self.gate_reasons is None:
            self.gate_reasons = []


class PatternDistiller:
    """
    Analyze completed Steps and extract Distillations.

    This transforms the pattern detection output from noise into intelligence:
    - Groups similar steps by intent
    - Identifies successful vs failed patterns
    - Extracts generalizable rules
    - Applies memory gate to filter low-value distillations

    The key insight: We don't store "User wanted X" - we store
    "When user wants X, approach Y works because Z"
    """

    def __init__(
        self,
        min_occurrences: int = 2,  # Lowered from 3 for faster learning
        min_occurrences_critical: int = 1,  # CRITICAL tier: learn from single occurrence
        min_confidence: float = 0.6,
        gate_threshold: float = 0.5
    ):
        """
        Initialize the distiller.

        Args:
            min_occurrences: Minimum times a pattern must occur (default)
            min_occurrences_critical: Minimum for CRITICAL importance (fast-track)
            min_confidence: Minimum confidence for a distillation
            gate_threshold: Memory gate score threshold
        """
        self.min_occurrences = min_occurrences
        self.min_occurrences_critical = min_occurrences_critical
        self.min_confidence = min_confidence
        self.gate_threshold = gate_threshold
        self.store = get_store()

        # Statistics
        self._stats = {
            "steps_analyzed": 0,
            "candidates_generated": 0,
            "distillations_created": 0,
            "gate_rejections": 0,
            "critical_fast_tracked": 0,  # CRITICAL tier fast-track count
        }
        self._tool_patterns_enabled = self._get_tool_pattern_flag()

    def _get_tool_pattern_flag(self) -> bool:
        """Return True when tool-pattern distillation is enabled."""
        # DISABLE wins if set explicitly
        disable = os.environ.get("SPARK_DISABLE_TOOL_DISTILLATION", "").strip().lower()
        if disable in {"1", "true", "yes", "on"}:
            return False
        try:
            from lib.config_authority import resolve_section, env_bool
            cfg = resolve_section(
                "eidos",
                env_overrides={
                    "tool_distillation_enabled": env_bool("SPARK_ENABLE_TOOL_DISTILLATION"),
                },
            ).data
            return bool(cfg.get("tool_distillation_enabled", True))
        except Exception:
            enable = os.environ.get("SPARK_ENABLE_TOOL_DISTILLATION", "").strip().lower()
            if enable in {"1", "true", "yes", "on"}:
                return True
            return True

    def distill_from_steps(self, steps: List[Step]) -> List[Distillation]:
        """
        Analyze completed Steps and extract Distillations.

        This is the main entry point. It:
        1. Groups steps by similar intent
        2. Analyzes success/failure patterns
        3. Generates distillation candidates
        4. Applies memory gate
        5. Saves passing distillations

        Args:
            steps: Completed Steps to analyze

        Returns:
            List of created Distillations
        """
        self._stats["steps_analyzed"] += len(steps)

        # Filter to only evaluated steps
        evaluated = [s for s in steps if s.evaluation != Evaluation.UNKNOWN]
        if len(evaluated) < self.min_occurrences:
            return []

        distillations = []

        # Strategy 1: User request patterns (heuristics/anti-patterns)
        user_distillations = self._distill_user_patterns(evaluated)
        distillations.extend(user_distillations)

        # Strategy 2: Tool effectiveness patterns
        if self._tool_patterns_enabled:
            tool_distillations = self._distill_tool_patterns(evaluated)
            distillations.extend(tool_distillations)

        # Strategy 3: Surprise patterns (sharp edges)
        surprise_distillations = self._distill_surprises(evaluated)
        distillations.extend(surprise_distillations)

        # Strategy 4: Lesson consolidation
        lesson_distillations = self._distill_lessons(evaluated)
        distillations.extend(lesson_distillations)

        return distillations

    # ==================== Strategy 1: User Patterns ====================

    def _distill_user_patterns(self, steps: List[Step]) -> List[Distillation]:
        """
        Distill patterns from user request handling.

        Groups steps by normalized intent and extracts:
        - HEURISTIC when success rate is high
        - ANTI_PATTERN when failure rate is high
        """
        distillations = []

        # Group by normalized intent
        intent_groups = self._group_by_intent(steps)

        for intent_key, group_steps in intent_groups.items():
            if len(group_steps) < self.min_occurrences:
                continue

            candidate = self._analyze_intent_group(intent_key, group_steps)
            if candidate and self._apply_memory_gate(candidate):
                # Save to store
                self.store.save_distillation(candidate.distillation)
                distillations.append(candidate.distillation)
                self._stats["distillations_created"] += 1
            elif candidate:
                self._stats["gate_rejections"] += 1

        return distillations

    def _group_by_intent(self, steps: List[Step]) -> Dict[str, List[Step]]:
        """Group steps by normalized intent for pattern analysis."""
        groups: Dict[str, List[Step]] = {}

        for step in steps:
            key = self._normalize_intent(step.intent)
            if key not in groups:
                groups[key] = []
            groups[key].append(step)

        return groups

    def _normalize_intent(self, intent: str) -> str:
        """Normalize intent for grouping similar requests."""
        if not intent:
            return "unknown"

        intent_lower = intent.lower()

        # Remove common prefixes
        for prefix in ["fulfill user request:", "user wants:", "request:"]:
            if intent_lower.startswith(prefix):
                intent_lower = intent_lower[len(prefix):].strip()

        # Extract action verbs
        action_keywords = {
            "push": "git_operations",
            "commit": "git_operations",
            "fix": "bug_fixing",
            "bug": "bug_fixing",
            "add": "feature_addition",
            "create": "feature_addition",
            "remove": "deletion",
            "delete": "deletion",
            "clean": "cleanup",
            "refactor": "refactoring",
            "test": "testing",
            "deploy": "deployment",
            "update": "modification",
            "change": "modification",
        }

        for keyword, category in action_keywords.items():
            if keyword in intent_lower:
                return f"intent:{category}"

        # Fallback: first 30 chars normalized
        normalized = re.sub(r'\s+', '_', intent_lower[:30])
        normalized = re.sub(r'[^a-z0-9_]', '', normalized)
        return f"intent:{normalized}"

    def _analyze_intent_group(
        self,
        intent_key: str,
        steps: List[Step]
    ) -> Optional[DistillationCandidate]:
        """Analyze a group of similar-intent steps and create distillation."""
        successes = [s for s in steps if s.evaluation == Evaluation.PASS]
        failures = [s for s in steps if s.evaluation == Evaluation.FAIL]

        total = len(successes) + len(failures)
        if total == 0:
            return None

        success_rate = len(successes) / total

        if success_rate >= self.min_confidence:
            # Create HEURISTIC from successful pattern
            return self._create_heuristic_candidate(intent_key, successes, success_rate)
        elif success_rate <= (1 - self.min_confidence):
            # Create ANTI_PATTERN from failure pattern
            return self._create_anti_pattern_candidate(intent_key, failures, 1 - success_rate)
        elif total >= 4 and 0.30 <= success_rate <= 0.70:
            # Mixed pattern: inconsistent results → SHARP_EDGE
            return self._create_sharp_edge_from_mixed(intent_key, steps, success_rate)

        # No clear pattern
        return None

    def _create_heuristic_candidate(
        self,
        intent_key: str,
        successes: List[Step],
        confidence: float
    ) -> DistillationCandidate:
        """Create a HEURISTIC distillation from successful patterns."""
        # Find most common successful approach
        decisions = [s.decision for s in successes if s.decision and s.decision != "pending"]
        if not decisions:
            return None

        best_decision = Counter(decisions).most_common(1)[0][0]

        # Extract the intent category
        intent_desc = intent_key.replace("intent:", "").replace("_", " ")

        # Extract reasoning from lessons (Improvement #7: Distillation Quality)
        lessons = [s.lesson for s in successes if s.lesson and len(s.lesson) > 10]
        reasoning = self._extract_reasoning(lessons)

        # Create actionable statement with reasoning
        if reasoning:
            statement = f"When {intent_desc}, use {best_decision[:100]} because {reasoning}"
        else:
            statement = f"When {intent_desc}, use {best_decision[:120]}. This approach succeeded {len(successes)} times."

        distillation = Distillation(
            distillation_id="",  # Auto-generated
            type=DistillationType.HEURISTIC,
            statement=statement[:250],  # Cap length but keep reasoning
            domains=["user_interaction", intent_desc],
            triggers=[intent_key, intent_desc],
            source_steps=[s.step_id for s in successes[:10]],
            confidence=min(0.4, confidence),  # Start low, earn trust
        )

        self._stats["candidates_generated"] += 1

        return DistillationCandidate(
            distillation=distillation,
            source_steps=successes,
        )

    def _create_anti_pattern_candidate(
        self,
        intent_key: str,
        failures: List[Step],
        confidence: float
    ) -> DistillationCandidate:
        """Create an ANTI_PATTERN distillation from failure patterns."""
        # Find most common failed approach
        decisions = [s.decision for s in failures if s.decision and s.decision != "pending"]
        if not decisions:
            return None

        worst_decision = Counter(decisions).most_common(1)[0][0]

        # Extract the intent category
        intent_desc = intent_key.replace("intent:", "").replace("_", " ")

        # Extract failure reasons from lessons (Improvement #7: Distillation Quality)
        lessons = [s.lesson for s in failures if s.lesson and len(s.lesson) > 10]
        failure_reason = self._extract_failure_reason(lessons)

        # Create anti-pattern with explanation
        if failure_reason:
            statement = f"When {intent_desc}, avoid {worst_decision[:80]} because {failure_reason}"
        else:
            statement = f"When {intent_desc}, avoid {worst_decision[:100]}. This approach failed {len(failures)} times."

        distillation = Distillation(
            distillation_id="",
            type=DistillationType.ANTI_PATTERN,
            statement=statement[:250],
            domains=["user_interaction", intent_desc],
            anti_triggers=[intent_key],
            source_steps=[s.step_id for s in failures[:10]],
            confidence=min(0.35, confidence),  # Start low, earn trust
        )

        self._stats["candidates_generated"] += 1

        return DistillationCandidate(
            distillation=distillation,
            source_steps=failures,
        )

    def _create_sharp_edge_from_mixed(
        self,
        intent_key: str,
        steps: List[Step],
        success_rate: float
    ) -> DistillationCandidate:
        """Create a SHARP_EDGE from mixed success/failure patterns.

        When a pattern has 4+ samples but inconsistent results (30-70% success),
        this indicates context-dependent behavior worth documenting.
        """
        intent_desc = intent_key.replace("intent:", "").replace("_", " ")
        successes = [s for s in steps if s.evaluation == Evaluation.PASS]
        failures = [s for s in steps if s.evaluation == Evaluation.FAIL]

        pct = int(success_rate * 100)
        statement = (
            f"Inconsistent results for {intent_desc}: "
            f"{pct}% success across {len(successes) + len(failures)} attempts. "
            f"Context matters — verify assumptions before proceeding."
        )

        distillation = Distillation(
            distillation_id="",
            type=DistillationType.SHARP_EDGE,
            statement=statement[:250],
            domains=["inconsistency", intent_desc],
            triggers=[intent_key, "mixed_results"],
            source_steps=[s.step_id for s in steps[:10]],
            confidence=0.35,  # Start low, earn trust
        )

        self._stats["candidates_generated"] += 1

        return DistillationCandidate(
            distillation=distillation,
            source_steps=steps,
        )

    def _extract_reasoning(self, lessons: List[str]) -> Optional[str]:
        """Extract reasoning from lessons for actionable distillations."""
        if not lessons:
            return None

        # Look for explicit reasoning patterns
        reasoning_patterns = [
            (r"because\s+(.{20,100})", 1),
            (r"this\s+(?:works|worked|helps?)\s+(?:because\s+)?(.{20,80})", 1),
            (r"(?:it|this)\s+(?:prevents?|avoids?|ensures?)\s+(.{15,80})", 1),
            (r"resolved\s+by[:\s]+(.{20,80})", 1),
        ]

        for lesson in lessons:
            lesson_lower = lesson.lower()
            for pattern, group in reasoning_patterns:
                match = re.search(pattern, lesson_lower, re.I)
                if match:
                    reason = match.group(group).strip()
                    # Clean up the reason
                    reason = re.sub(r'\s+', ' ', reason)
                    if len(reason) > 15:
                        return reason[:100]

        # Fallback: extract actionable verbs
        action_keywords = ["verify", "check", "ensure", "validate", "confirm", "use", "avoid"]
        for lesson in lessons:
            for keyword in action_keywords:
                if keyword in lesson.lower():
                    # Extract the action clause
                    idx = lesson.lower().find(keyword)
                    action = lesson[idx:idx+80].strip()
                    if len(action) > 20:
                        return f"it's important to {action.lower()}"

        return None

    def _extract_failure_reason(self, lessons: List[str]) -> Optional[str]:
        """Extract failure reason from lessons."""
        if not lessons:
            return None

        # Look for failure explanation patterns
        failure_patterns = [
            (r"failed\s+(?:because|due to)\s+(.{20,100})", 1),
            (r"(?:error|issue|problem)[:\s]+(.{20,80})", 1),
            (r"(?:didn't|doesn't|won't)\s+work\s+(?:because\s+)?(.{15,80})", 1),
            (r"(?:causes?|leads?\s+to)\s+(.{20,80})", 1),
        ]

        for lesson in lessons:
            lesson_lower = lesson.lower()
            for pattern, group in failure_patterns:
                match = re.search(pattern, lesson_lower, re.I)
                if match:
                    reason = match.group(group).strip()
                    reason = re.sub(r'\s+', ' ', reason)
                    if len(reason) > 15:
                        # Clean up grammar: remove leading articles
                        reason = re.sub(r'^(the|a|an|it)\s+', '', reason.lower())
                        return reason[:100]

        # Fallback: just note it's unreliable
        return "it tends to fail in this context"

    # ==================== Strategy 2: Tool Patterns ====================

    def _distill_tool_patterns(self, steps: List[Step]) -> List[Distillation]:
        """
        Distill patterns about tool effectiveness.

        Identifies which tools work well for which intents.
        """
        distillations = []

        # Group by tool used
        tool_groups: Dict[str, List[Step]] = {}
        for step in steps:
            tool = step.action_details.get("tool_used", "")
            if not tool:
                continue
            if tool not in tool_groups:
                tool_groups[tool] = []
            tool_groups[tool].append(step)

        for tool, tool_steps in tool_groups.items():
            if len(tool_steps) < self.min_occurrences:
                continue

            successes = [s for s in tool_steps if s.evaluation == Evaluation.PASS]
            if len(successes) < 2:
                continue

            # What intents does this tool succeed at?
            success_intents = Counter(
                self._normalize_intent(s.intent) for s in successes
            ).most_common(2)

            if not success_intents:
                continue

            best_intent, count = success_intents[0]
            if count < 2:
                continue

            intent_desc = best_intent.replace("intent:", "").replace("_", " ")

            # Extract reasoning from successful uses (Improvement #7)
            tool_lessons = [s.lesson for s in successes if s.lesson and len(s.lesson) > 10]
            reasoning = self._extract_reasoning(tool_lessons)
            if not reasoning:
                # Avoid telemetry-style statements like success rates without reasoning.
                continue

            statement = f"For {intent_desc}, use {tool} because {reasoning}"

            distillation = Distillation(
                distillation_id="",
                type=DistillationType.HEURISTIC,
                statement=statement[:250],
                domains=["tool_usage", tool.lower()],
                triggers=[f"tool:{tool}", intent_desc],
                source_steps=[s.step_id for s in successes[:5]],
                confidence=count / len(tool_steps),
            )

            candidate = DistillationCandidate(
                distillation=distillation,
                source_steps=successes,
            )

            if self._apply_memory_gate(candidate):
                self.store.save_distillation(distillation)
                distillations.append(distillation)
                self._stats["distillations_created"] += 1

        return distillations

    # ==================== Strategy 3: Surprises ====================

    def _distill_surprises(self, steps: List[Step]) -> List[Distillation]:
        """
        Distill SHARP_EDGE patterns from surprising outcomes.

        High surprise = prediction didn't match reality.
        These are valuable learning opportunities.
        """
        distillations = []

        # Find high-surprise steps
        surprises = [s for s in steps if s.surprise_level >= 0.5]
        if len(surprises) < 2:
            return []

        # Group surprises by intent
        intent_surprises: Dict[str, List[Step]] = {}
        for step in surprises:
            key = self._normalize_intent(step.intent)
            if key not in intent_surprises:
                intent_surprises[key] = []
            intent_surprises[key].append(step)

        for intent_key, surprise_steps in intent_surprises.items():
            if len(surprise_steps) < 2:
                continue

            intent_desc = intent_key.replace("intent:", "").replace("_", " ")

            # Extract what was surprising (Improvement #7: Better sharp edge quality)
            lessons = [s.lesson for s in surprise_steps if s.lesson and len(s.lesson) > 10]
            predictions = [s.prediction for s in surprise_steps if s.prediction]
            results = [s.result for s in surprise_steps if s.result]

            # Create actionable sharp edge with context
            if lessons:
                # Extract the key insight from lessons
                key_lesson = self._extract_reasoning(lessons)
                if key_lesson:
                    edge_description = f"Watch out when {intent_desc}: {key_lesson}"
                else:
                    edge_description = f"Watch out when {intent_desc}: {lessons[0][:100]}"
            elif predictions and results:
                edge_description = f"When {intent_desc}, expected {predictions[0][:40]}... but got {results[0][:40]}..."
            else:
                edge_description = f"Unexpected behavior when {intent_desc}. Check assumptions before proceeding."

            distillation = Distillation(
                distillation_id="",
                type=DistillationType.SHARP_EDGE,
                statement=edge_description[:250],
                domains=["gotchas", intent_desc],
                triggers=[intent_key],
                source_steps=[s.step_id for s in surprise_steps[:5]],
                confidence=0.7,  # Surprises are inherently uncertain
            )

            candidate = DistillationCandidate(
                distillation=distillation,
                source_steps=surprise_steps,
            )

            if self._apply_memory_gate(candidate):
                self.store.save_distillation(distillation)
                distillations.append(distillation)
                self._stats["distillations_created"] += 1

        return distillations

    # ==================== Strategy 4: Lesson Consolidation ====================

    def _distill_lessons(self, steps: List[Step]) -> List[Distillation]:
        """
        Consolidate similar lessons into policy distillations.

        When multiple steps produce similar lessons, consolidate
        into a reusable policy.
        """
        distillations = []

        # Extract and normalize lessons
        lessons = [(s, s.lesson) for s in steps if s.lesson and len(s.lesson) > 20]
        if len(lessons) < self.min_occurrences:
            return []

        # Simple clustering by keyword overlap
        lesson_clusters = self._cluster_lessons(lessons)

        for cluster_key, cluster_steps in lesson_clusters.items():
            if len(cluster_steps) < self.min_occurrences:
                continue

            # Synthesize a general policy from the cluster
            lessons_text = [s.lesson for s in cluster_steps]
            synthesized = self._synthesize_policy(lessons_text)

            if not synthesized:
                continue

            distillation = Distillation(
                distillation_id="",
                type=DistillationType.POLICY,
                statement=synthesized,
                domains=["learned_policy"],
                triggers=[cluster_key],
                source_steps=[s.step_id for s in cluster_steps[:5]],
                confidence=len(cluster_steps) / len(steps),  # More occurrences = higher confidence
            )

            candidate = DistillationCandidate(
                distillation=distillation,
                source_steps=cluster_steps,
            )

            if self._apply_memory_gate(candidate):
                self.store.save_distillation(distillation)
                distillations.append(distillation)
                self._stats["distillations_created"] += 1

        return distillations

    def _cluster_lessons(
        self,
        lessons: List[Tuple[Step, str]]
    ) -> Dict[str, List[Step]]:
        """Cluster lessons by keyword similarity."""
        clusters: Dict[str, List[Step]] = {}

        # Extract keywords from each lesson
        stop_words = {
            "the", "a", "an", "and", "or", "but", "if", "then", "so", "to",
            "of", "in", "on", "for", "with", "by", "is", "are", "was", "were",
            "be", "been", "being", "request", "user", "resolved", "failed"
        }

        for step, lesson in lessons:
            words = re.findall(r'\b[a-z]+\b', lesson.lower())
            keywords = [w for w in words if w not in stop_words and len(w) > 3]
            if not keywords:
                continue

            # Use first 3 keywords as cluster key
            cluster_key = "_".join(sorted(keywords[:3]))
            if cluster_key not in clusters:
                clusters[cluster_key] = []
            clusters[cluster_key].append(step)

        return clusters

    def _synthesize_policy(self, lessons: List[str]) -> Optional[str]:
        """Synthesize a general policy from multiple lessons (Improvement #7)."""
        if not lessons:
            return None

        # Extract common reasoning
        reasoning = self._extract_reasoning(lessons)

        # Find common action patterns
        action_verbs = Counter()
        for lesson in lessons:
            for verb in ["verify", "check", "ensure", "validate", "confirm", "use", "avoid", "always", "never"]:
                if verb in lesson.lower():
                    # Extract the action clause
                    idx = lesson.lower().find(verb)
                    action = lesson[idx:idx+60].strip()
                    if len(action) > 10:
                        action_verbs[action] += 1

        if action_verbs:
            best_action, count = action_verbs.most_common(1)[0]
            if reasoning:
                return f"Always {best_action} because {reasoning}"
            else:
                return f"Always {best_action} (validated {count} times)"

        # Fallback: extract from request pattern
        for lesson in lessons:
            if "resolved by:" in lesson.lower():
                parts = lesson.split("resolved by:", 1)
                if len(parts) > 1:
                    action = parts[1].strip()[:100]
                    if reasoning:
                        return f"When facing similar issues, {action} because {reasoning}"
                    return f"When facing similar issues, {action}"

        # Last fallback
        shortest = min(lessons, key=len)
        if len(shortest) > 30:
            return f"Learned pattern: {shortest[:150]}"

        return None

    # ==================== Memory Gate ====================

    def _apply_memory_gate(self, candidate: DistillationCandidate) -> bool:
        """
        Apply memory gate to determine if distillation should persist.

        Scoring:
        - Impact (unblocked progress): +0.3
        - Novelty (new pattern): +0.2
        - Surprise (prediction != outcome): +0.3
        - Recurrence (3+ times): +0.2
        - Irreversible (high stakes): +0.4

        Threshold: score > 0.5
        """
        score = 0.0
        reasons = []

        steps = candidate.source_steps
        distillation = candidate.distillation
        statement = distillation.statement or ""

        if is_primitive_text(statement) or is_operational_insight(statement):
            candidate.gate_score = 0.0
            candidate.gate_reasons = ["operational_or_primitive"]
            return False

        # Impact: Did these steps make progress?
        progress_steps = [s for s in steps if s.progress_made]
        if len(progress_steps) > len(steps) * 0.5:
            score += 0.3
            reasons.append("impact:progress_made")

        # Novelty: Is this a new pattern?
        existing = self._find_similar_distillation(distillation)
        if not existing:
            score += 0.2
            reasons.append("novelty:new_pattern")
        else:
            # Update existing instead of creating new
            candidate.distillation = existing
            score += 0.1
            reasons.append("novelty:updates_existing")

        # Surprise: Were outcomes unexpected?
        surprises = [s for s in steps if s.surprise_level > 0.3]
        if len(surprises) > len(steps) * 0.3:
            score += 0.3
            reasons.append(f"surprise:{len(surprises)}_steps")

        # Recurrence: Multiple occurrences
        if len(steps) >= self.min_occurrences:
            score += 0.2
            reasons.append(f"recurrence:{len(steps)}_occurrences")

        # High stakes: Security, deployment, deletion
        high_stakes_keywords = ["deploy", "delete", "security", "auth", "payment", "production"]
        statement_lower = distillation.statement.lower()
        if any(kw in statement_lower for kw in high_stakes_keywords):
            score += 0.4
            reasons.append("high_stakes")

        # Evidence quality: Has validation
        validated = [s for s in steps if s.validated]
        if len(validated) > len(steps) * 0.5:
            score += 0.1
            reasons.append("evidence:validated")

        candidate.gate_score = score
        candidate.gate_reasons = reasons

        return score >= self.gate_threshold

    def _find_similar_distillation(self, candidate: Distillation) -> Optional[Distillation]:
        """Check if a similar distillation already exists."""
        # Get existing distillations of same type
        existing = self.store.get_distillations_by_type(candidate.type, limit=100)

        # Simple similarity check based on triggers and statement
        candidate_triggers = set(candidate.triggers)
        candidate_words = set(candidate.statement.lower().split())

        for dist in existing:
            dist_triggers = set(dist.triggers)
            dist_words = set(dist.statement.lower().split())

            # Check trigger overlap
            if candidate_triggers & dist_triggers:
                return dist

            # Check statement similarity
            overlap = len(candidate_words & dist_words) / max(len(candidate_words | dist_words), 1)
            if overlap > 0.6:
                return dist

        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get distiller statistics."""
        return {
            **self._stats,
            "min_occurrences": self.min_occurrences,
            "min_occurrences_critical": self.min_occurrences_critical,
            "min_confidence": self.min_confidence,
            "gate_threshold": self.gate_threshold,
        }

    def get_effective_min_occurrences(self, importance_tier: str = "medium") -> int:
        """
        Get the effective minimum occurrences based on importance tier.

        CRITICAL tier items are fast-tracked with lower occurrence requirement.
        """
        if importance_tier.lower() == "critical":
            return self.min_occurrences_critical
        return self.min_occurrences


# Singleton instance
_distiller: Optional[PatternDistiller] = None


def get_pattern_distiller() -> PatternDistiller:
    """Get the global pattern distiller instance."""
    global _distiller
    if _distiller is None:
        _distiller = PatternDistiller()
    return _distiller
