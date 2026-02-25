"""
EIDOS Distillation Engine: Where Intelligence Crystallizes

Runs after every episode to extract reusable rules from experience.

The distillation process:
1. Post-episode reflection (what happened? why?)
2. Pattern identification (what's generalizable?)
3. Rule generation (if X, then Y)
4. Evidence linking (which steps prove this?)
5. Confidence assignment (how sure are we?)
6. Revalidation scheduling (when to re-check?)

Types of distillations:
- HEURISTIC: "If X, then Y"
- SHARP_EDGE: Gotcha / pitfall
- ANTI_PATTERN: "Never do X because..."
- PLAYBOOK: Step-by-step procedure
- POLICY: Operating constraint
"""

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    Episode, Step, Distillation, DistillationType,
    Outcome, Evaluation, Phase
)
from ..elevation import elevate
from ..distillation_transformer import transform_for_advisory
from ..distillation_refiner import refine_distillation
from ..noise_patterns import is_session_boilerplate


@dataclass
class ReflectionResult:
    """Results of post-episode reflection."""
    bottleneck: str = ""           # What was the real bottleneck?
    wrong_assumption: str = ""     # Which assumption was wrong?
    preventive_check: str = ""     # What check would have prevented this?
    new_rule: str = ""             # What rule should we adopt?
    stop_doing: str = ""           # What should we stop doing?
    key_insight: str = ""          # Most important learning
    confidence: float = 0.5


@dataclass
class DistillationCandidate:
    """A candidate distillation before validation."""
    type: DistillationType
    statement: str
    domains: List[str]
    triggers: List[str]
    source_steps: List[str]
    confidence: float
    rationale: str


class DistillationEngine:
    """
    Engine that extracts reusable rules from episode experience.

    The engine doesn't just summarize - it crystallizes actionable
    intelligence that can be reused in future episodes.
    """

    def __init__(self):
        # Track patterns across episodes
        self.pattern_counts: Dict[str, int] = {}  # pattern_sig -> count
        self.distillation_history: List[Distillation] = []

        # Revalidation tracking
        self.pending_revalidation: List[str] = []  # distillation_ids
        self._quality_floor = 0.35

    def reflect_on_episode(
        self,
        episode: Episode,
        steps: List[Step]
    ) -> ReflectionResult:
        """
        Perform post-episode reflection to identify key learnings.

        This generates prompts for LLM reflection, but the questions
        are deterministic based on episode outcome.
        """
        result = ReflectionResult()

        if not steps:
            return result

        # Analyze episode outcome
        if episode.outcome == Outcome.SUCCESS:
            result = self._reflect_on_success(episode, steps)
        elif episode.outcome == Outcome.FAILURE:
            result = self._reflect_on_failure(episode, steps)
        elif episode.outcome == Outcome.ESCALATED:
            result = self._reflect_on_escalation(episode, steps)
        else:
            result = self._reflect_on_partial(episode, steps)

        return result

    def _reflect_on_success(self, episode: Episode, steps: List[Step]) -> ReflectionResult:
        """Reflect on successful episode."""
        result = ReflectionResult()

        # Find the breakthrough step
        breakthrough = None
        for step in reversed(steps):
            if step.evaluation == Evaluation.PASS and step.confidence_after > 0.7:
                breakthrough = step
                break

        if breakthrough:
            result.key_insight = f"Success came from: {breakthrough.decision}"
            # Build an actionable rule using descriptive intent/decision
            result.new_rule = f"When {breakthrough.intent}, try: {breakthrough.decision}"

        # Check for initial wrong assumptions that were overcome
        wrong_assumptions = [s for s in steps if s.evaluation == Evaluation.FAIL and s.assumptions]
        if wrong_assumptions:
            first_wrong = wrong_assumptions[0]
            assumption = first_wrong.assumptions[0] if first_wrong.assumptions else "N/A"
            result.wrong_assumption = f"Initially assumed: {assumption}"
            result.preventive_check = f"Validate before proceeding: {assumption}"

        # Identify recovery pattern (failure then success)
        fail_then_success = []
        for i, step in enumerate(steps[:-1]):
            if step.evaluation == Evaluation.FAIL and steps[i + 1].evaluation == Evaluation.PASS:
                fail_then_success.append((step, steps[i + 1]))
        if fail_then_success:
            fail_s, succ_s = fail_then_success[0]
            result.bottleneck = f"Recovery: after '{fail_s.decision[:50]}' failed, '{succ_s.decision[:50]}' succeeded"

        result.confidence = 0.8

        return result

    def _reflect_on_failure(self, episode: Episode, steps: List[Step]) -> ReflectionResult:
        """Reflect on failed episode."""
        result = ReflectionResult()

        # Find repeated errors
        error_steps = [s for s in steps if s.evaluation == Evaluation.FAIL]
        if len(error_steps) >= 2:
            result.bottleneck = f"Repeated failures ({len(error_steps)} times)"

        # Find the first failure
        if error_steps:
            first_fail = error_steps[0]
            result.wrong_assumption = f"First failure: {first_fail.prediction} vs {first_fail.result}"
            if first_fail.assumptions:
                result.preventive_check = f"Validate: {first_fail.assumptions[0]}"

        # Identify anti-pattern
        result.stop_doing = self._identify_anti_pattern(steps)
        result.confidence = 0.6

        return result

    def _reflect_on_escalation(self, episode: Episode, steps: List[Step]) -> ReflectionResult:
        """Reflect on escalated episode."""
        result = ReflectionResult()

        result.bottleneck = "Escalated - exceeded capability or budget"

        # Collect unique approaches that were tried
        approaches = []
        seen = set()
        for step in steps:
            if step.decision and step.decision not in seen:
                seen.add(step.decision)
                approaches.append(step.decision[:60])

        if approaches:
            result.key_insight = f"Tried {len(approaches)} approaches: {', '.join(approaches[:3])}"
            # Build a specific escalation rule based on what was tried
            result.new_rule = f"When '{episode.goal[:40]}' stalls after trying {approaches[0]}, escalate rather than repeat"

        result.confidence = 0.5

        return result

    def _reflect_on_partial(self, episode: Episode, steps: List[Step]) -> ReflectionResult:
        """Reflect on partial success episode."""
        result = ReflectionResult()

        success_steps = [s for s in steps if s.evaluation == Evaluation.PASS]
        fail_steps = [s for s in steps if s.evaluation == Evaluation.FAIL]

        if success_steps and fail_steps:
            # Describe what worked and what didn't
            worked = success_steps[-1].decision[:50]
            failed = fail_steps[-1].decision[:50]
            result.key_insight = f"Partial: '{worked}' succeeded but '{failed}' failed"
            # Generate a rule about what to try first
            result.new_rule = f"When similar to '{episode.goal[:30]}', start with approach like '{worked}'"
        elif success_steps and not fail_steps:
            # All-pass episode: extract the successful pattern
            # These are sessions where everything worked - valuable signal
            unique_decisions = []
            seen = set()
            for s in success_steps:
                d = s.decision[:60]
                if d not in seen and "Use " not in d[:4]:  # Skip template decisions
                    unique_decisions.append(d)
                    seen.add(d)

            if unique_decisions:
                approach = unique_decisions[-1]  # Most recent meaningful decision
                result.key_insight = f"Successful approach: {approach} ({len(success_steps)} steps, all passed)"
                result.new_rule = f"When similar to '{episode.goal[:40]}', the approach '{approach}' worked reliably"
                result.confidence = 0.7  # Higher confidence for all-pass
                return result

        result.confidence = 0.6

        return result

    def _identify_anti_pattern(self, steps: List[Step]) -> str:
        """Identify what should be stopped."""
        # Look for repeated failures with same approach
        decisions = [s.decision for s in steps if s.evaluation == Evaluation.FAIL]

        if len(decisions) >= 2:
            # Simple check for repeated decision
            from collections import Counter
            counts = Counter(decisions)
            most_common = counts.most_common(1)
            if most_common and most_common[0][1] >= 2:
                return f"Stop: {most_common[0][0][:50]}"

        return ""

    @staticmethod
    def _is_quality_distillation(statement: str, dtype: DistillationType) -> bool:
        """Reject tautological, generic, or low-quality distillation statements."""
        s = statement.strip()
        if len(s) < 20:
            return False
        if is_session_boilerplate(s):
            return False

        low = s.lower()

        # Reject known tautology phrases
        _TAUTOLOGY_PHRASES = [
            "try a different approach",
            "step back and reconsider",
            "try something else",
            "try another approach",
            "consider alternatives",
            "without progress",
            "when repeated",
            "always validate assumptions",
            "always verify",
            "be careful when",
            "unknown approach",
            "unknown task",
            "unknown project",
            "session in unknown",
            "request failed for search_query",
            "request failed for image_query",
            "for similar requests",
            "tool is effective",
        ]
        for phrase in _TAUTOLOGY_PHRASES:
            if phrase in low:
                return False

        # Reject placeholder-heavy statements.
        if re.search(r"\b(?:when|if|for)\b.{0,40}\bunknown\b", low):
            return False

        # Reject obvious failure-echo templates.
        if re.search(r"\b(?:watch out|be careful)\b.{0,80}\bunknown\b.{0,40}\bapproach\b", low):
            return False

        # Reject "When X, try: Y" where X ≈ Y (>60% word overlap)
        if "try:" in low and "when " in low:
            parts = low.split("try:", 1)
            if len(parts) == 2:
                when_words = set(parts[0].replace("when ", "").replace(",", "").split())
                try_words = set(parts[1].split())
                if when_words and try_words:
                    overlap = len(when_words & try_words) / max(len(when_words), len(try_words))
                    if overlap > 0.6:
                        return False

        # Reject statements that are mostly file paths or tool names
        path_chars = sum(1 for c in s if c in r'\/:.')
        if path_chars > len(s) * 0.3:
            return False

        return True

    def generate_distillations(
        self,
        episode: Episode,
        steps: List[Step],
        reflection: ReflectionResult
    ) -> List[DistillationCandidate]:
        """
        Generate candidate distillations from episode experience.

        Returns candidates that need validation before becoming
        permanent distillations.
        """
        candidates = []

        # 1. Generate from new_rule (HEURISTIC)
        # Initial confidence capped at 0.4 — must earn trust through usage
        if reflection.new_rule:
            candidates.append(DistillationCandidate(
                type=DistillationType.HEURISTIC,
                statement=reflection.new_rule,
                domains=self._extract_domains(episode, steps),
                triggers=self._extract_triggers(steps),
                source_steps=[s.step_id for s in steps if s.evaluation == Evaluation.PASS],
                confidence=min(0.4, reflection.confidence),
                rationale=f"Derived from successful episode: {episode.goal[:50]}"
            ))

        # 2. Generate from stop_doing (ANTI_PATTERN)
        if reflection.stop_doing:
            candidates.append(DistillationCandidate(
                type=DistillationType.ANTI_PATTERN,
                statement=reflection.stop_doing,
                domains=self._extract_domains(episode, steps),
                triggers=self._extract_triggers(steps),
                source_steps=[s.step_id for s in steps if s.evaluation == Evaluation.FAIL],
                confidence=min(0.35, reflection.confidence * 0.8),
                rationale=f"Derived from failures in: {episode.goal[:50]}"
            ))

        # 3. Generate from preventive_check (SHARP_EDGE)
        if reflection.preventive_check:
            candidates.append(DistillationCandidate(
                type=DistillationType.SHARP_EDGE,
                statement=reflection.preventive_check,
                domains=self._extract_domains(episode, steps),
                triggers=self._extract_triggers(steps),
                source_steps=[s.step_id for s in steps[:3]],
                confidence=min(0.35, reflection.confidence * 0.7),
                rationale=f"Would have prevented issues in: {episode.goal[:50]}"
            ))

        # 4. Generate PLAYBOOK if episode was successful and had clear steps
        if episode.outcome == Outcome.SUCCESS and len(steps) >= 3:
            playbook = self._generate_playbook(episode, steps)
            if playbook:
                candidates.append(playbook)

        # 5. Generate POLICY from constraint-like decisions
        if len(steps) >= 5:
            policy = self._generate_policy(episode, steps)
            if policy:
                candidates.append(policy)

        # Elevation + quality gate: tighten language, then reject weak candidates.
        last_step = steps[-1] if steps else None
        context = {
            "goal": episode.goal,
            "domain": ", ".join(self._extract_domains(episode, steps)),
            "tool": ((last_step.action_details or {}).get("tool", "") if last_step else ""),
            "file_path": ((last_step.action_details or {}).get("file_path", "") if last_step else ""),
            "timestamp": int(episode.end_ts or time.time()),
        }

        filtered: List[DistillationCandidate] = []
        for candidate in candidates:
            if not self._is_quality_distillation(candidate.statement, candidate.type):
                continue

            elevated = elevate(candidate.statement, context)
            if elevated and elevated.strip():
                candidate.statement = elevated.strip()

            aq = transform_for_advisory(candidate.statement, source="eidos")
            if aq.suppressed or aq.unified_score < self._quality_floor:
                continue
            filtered.append(candidate)
        return filtered

    _GENERIC_GOALS = {
        "continue", "continue please", "yes", "ok", "go", "do it",
        "proceed", "next", "go ahead", "keep going", "sure",
    }

    def _generate_playbook(
        self,
        episode: Episode,
        steps: List[Step]
    ) -> Optional[DistillationCandidate]:
        """Generate a playbook from successful episode.

        Improvements over original:
        - Uses full goal text (not truncated to 30 chars)
        - Uses domain keywords as triggers (not just first word)
        - Starts at low confidence (0.3) — must earn trust through usage
        - Requires diverse step types (not just 2 unique decisions)
        """
        # Reject generic goals
        goal_clean = (episode.goal or "").strip().lower().rstrip(".!?")
        if len(goal_clean) < 10 or goal_clean in self._GENERIC_GOALS:
            return None

        # Get successful steps
        success_steps = [s for s in steps if s.evaluation == Evaluation.PASS]

        if len(success_steps) < 2:
            return None

        # Reject playbooks where all steps use the same decision (e.g., "TaskUpdate" 5x)
        unique_decisions = set(s.decision[:60] for s in success_steps[:5])
        if len(unique_decisions) < 2:
            return None

        # Require at least 2 different tools/actions for a meaningful playbook
        tools = set()
        for s in success_steps[:5]:
            details = s.action_details or {}
            tool = details.get("tool", "")
            if tool:
                tools.add(tool.lower())
        if len(tools) < 2 and len(unique_decisions) < 3:
            return None

        # Build step-by-step with full decisions
        playbook_steps = []
        for i, step in enumerate(success_steps[:5], 1):
            decision_text = step.decision[:100] if step.decision else "unknown"
            playbook_steps.append(f"{i}. {decision_text}")

        # Use full goal (capped at 120 chars for readability)
        goal_display = episode.goal[:120] if episode.goal else "unknown task"
        statement = f"Playbook for '{goal_display}': " + "; ".join(playbook_steps)

        # Use domain keywords as triggers instead of first word of goal
        triggers = self._extract_triggers(success_steps)

        return DistillationCandidate(
            type=DistillationType.PLAYBOOK,
            statement=statement,
            domains=self._extract_domains(episode, steps),
            triggers=triggers,
            source_steps=[s.step_id for s in success_steps],
            confidence=0.3,  # Start low — must earn trust
            rationale="Successful step sequence"
        )

    _CONSTRAINT_WORDS = {"always", "must", "never", "ensure", "require", "mandatory", "forbidden", "prohibit"}

    def _generate_policy(
        self,
        episode: Episode,
        steps: List[Step]
    ) -> Optional[DistillationCandidate]:
        """Generate a POLICY from constraint-like decisions.

        Policies capture recurring operating constraints (always/must/never/ensure).
        Requires 2+ constraint-bearing steps in an episode with 5+ total steps.
        """
        constraint_steps = []
        for step in steps:
            decision_lower = (step.decision or "").lower()
            if any(w in decision_lower for w in self._CONSTRAINT_WORDS):
                constraint_steps.append(step)

        if len(constraint_steps) < 2:
            return None

        # Pick the constraint with highest confidence
        best = max(constraint_steps, key=lambda s: s.confidence_after)
        statement = f"Policy: {best.decision[:150]}"

        return DistillationCandidate(
            type=DistillationType.POLICY,
            statement=statement,
            domains=self._extract_domains(episode, steps),
            triggers=self._extract_triggers(constraint_steps),
            source_steps=[s.step_id for s in constraint_steps],
            confidence=min(0.7, best.confidence_after),
            rationale=f"Constraint pattern from {len(constraint_steps)} steps in: {episode.goal[:50]}"
        )

    def _extract_domains(self, episode: Episode, steps: List[Step]) -> List[str]:
        """Extract domains from episode and steps.

        Uses broader keyword matching across goal, intents, decisions,
        and action_details to avoid defaulting to 'general'.
        """
        domains = set()

        domain_keywords = {
            "api": "api", "rest": "api", "endpoint": "api", "route": "api",
            "auth": "auth", "login": "auth", "token": "auth", "oauth": "auth",
            "database": "database", "db": "database", "sql": "database", "query": "database",
            "ui": "ui", "component": "ui", "render": "ui", "css": "ui", "html": "ui",
            "test": "test", "pytest": "test", "unittest": "test", "assert": "test",
            "deploy": "deploy", "ci": "deploy", "docker": "deploy", "build": "deploy",
            "config": "config", "env": "config", "settings": "config", "tuneables": "config",
            "git": "git", "commit": "git", "branch": "git", "merge": "git",
            "debug": "debug", "error": "debug", "fix": "debug", "bug": "debug",
            "refactor": "refactor", "rename": "refactor", "cleanup": "refactor",
            "security": "security", "permission": "security", "encrypt": "security",
            "performance": "performance", "optimize": "performance", "cache": "performance",
        }

        # Collect all text from episode and steps
        all_text = episode.goal.lower()
        for step in steps[:10]:
            all_text += " " + step.intent.lower()
            all_text += " " + step.decision.lower()
            details = step.action_details or {}
            all_text += " " + str(details.get("tool", "")).lower()
            all_text += " " + str(details.get("file_path", "")).lower()
            all_text += " " + str(details.get("command", "")).lower()[:100]

        words = set(all_text.split())
        for word in words:
            # Strip punctuation for matching
            clean = word.strip(".,;:()[]{}'\"-/\\")
            if clean in domain_keywords:
                domains.add(domain_keywords[clean])

        return list(domains)[:5] if domains else ["general"]

    def _extract_triggers(self, steps: List[Step]) -> List[str]:
        """Extract meaningful triggers from steps.

        Uses tool names, file types, and action verbs instead of
        generic 'execute' from the old template intents.
        """
        triggers = set()
        stop_words = {"the", "a", "an", "to", "for", "in", "on", "of", "is", "and", "or"}

        for step in steps:
            # Extract tool name from action_details
            details = step.action_details or {}
            tool = details.get("tool", "")
            if tool:
                triggers.add(tool.lower())

            # Extract meaningful words from intent (skip stop words)
            words = step.intent.lower().split()
            for w in words[:4]:
                clean = w.strip(".,;:()[]{}'\"-/\\")
                if clean and len(clean) > 2 and clean not in stop_words:
                    triggers.add(clean)
                    if len(triggers) >= 8:
                        break
            if len(triggers) >= 8:
                break

        return list(triggers)[:8]

    def finalize_distillation(
        self,
        candidate: DistillationCandidate
    ) -> Distillation:
        """
        Convert a validated candidate into a permanent distillation.
        """
        refine_context = {
            "domain": ", ".join(candidate.domains),
            "tool": candidate.triggers[0] if candidate.triggers else "",
            "reason": candidate.rationale,
            "timestamp": int(time.time()),
        }
        refined_statement, advisory_quality = refine_distillation(
            candidate.statement,
            source="eidos",
            context=refine_context,
            min_unified_score=0.60,
        )
        return Distillation(
            distillation_id="",  # Will be auto-generated
            type=candidate.type,
            statement=candidate.statement,
            refined_statement=refined_statement if refined_statement != candidate.statement else "",
            advisory_quality=advisory_quality,
            domains=candidate.domains,
            triggers=candidate.triggers,
            source_steps=candidate.source_steps,
            confidence=candidate.confidence,
            # Set revalidation for 7 days
            revalidate_by=time.time() + (7 * 86400)
        )

    def schedule_revalidation(self, distillation_id: str, days: int = 7):
        """Schedule a distillation for revalidation."""
        self.pending_revalidation.append(distillation_id)

    def get_due_for_revalidation(self) -> List[str]:
        """Get distillation IDs due for revalidation."""
        due = self.pending_revalidation.copy()
        self.pending_revalidation = []
        return due

    def validate_distillation(
        self,
        distillation: Distillation,
        episode: Episode,
        steps: List[Step],
        helped: bool
    ) -> Distillation:
        """
        Update distillation based on validation outcome.

        Called when a distillation was retrieved and used.
        """
        distillation.times_used += 1

        if helped:
            distillation.times_helped += 1
            distillation.validation_count += 1
            # Increase confidence
            distillation.confidence = min(1.0, distillation.confidence + 0.05)
        else:
            distillation.contradiction_count += 1
            # Decrease confidence
            distillation.confidence = max(0.1, distillation.confidence - 0.1)

        return distillation

    def merge_similar_distillations(
        self,
        distillations: List[Distillation]
    ) -> List[Distillation]:
        """
        Merge distillations that are semantically similar.

        This prevents duplicate rules from accumulating.
        """
        if len(distillations) < 2:
            return distillations

        # Group by type
        by_type: Dict[DistillationType, List[Distillation]] = {}
        for d in distillations:
            if d.type not in by_type:
                by_type[d.type] = []
            by_type[d.type].append(d)

        merged = []
        for dtype, group in by_type.items():
            # Simple text similarity check
            merged.extend(self._merge_group(group))

        return merged

    def _merge_group(self, group: List[Distillation]) -> List[Distillation]:
        """Merge a group of same-type distillations."""
        if len(group) < 2:
            return group

        # Simple merge: keep highest confidence, combine evidence
        result = []
        used = set()

        for i, d1 in enumerate(group):
            if i in used:
                continue

            # Find similar distillations
            similar = [d1]
            for j, d2 in enumerate(group[i+1:], i+1):
                if j in used:
                    continue
                if self._are_similar(d1.statement, d2.statement):
                    similar.append(d2)
                    used.add(j)

            # Merge similar ones
            if len(similar) > 1:
                merged = self._merge_distillations(similar)
                result.append(merged)
            else:
                result.append(d1)

            used.add(i)

        return result

    def _are_similar(self, s1: str, s2: str) -> bool:
        """Check if two statements are similar."""
        # Simple word overlap check
        words1 = set(s1.lower().split())
        words2 = set(s2.lower().split())

        if not words1 or not words2:
            return False

        overlap = len(words1 & words2) / len(words1 | words2)
        return overlap > 0.5

    def _merge_distillations(self, similar: List[Distillation]) -> Distillation:
        """Merge multiple similar distillations into one."""
        # Keep the one with highest confidence as base
        base = max(similar, key=lambda d: d.confidence)

        # Combine evidence
        all_sources = set()
        total_validations = 0
        total_contradictions = 0
        total_used = 0
        total_helped = 0

        for d in similar:
            all_sources.update(d.source_steps)
            total_validations += d.validation_count
            total_contradictions += d.contradiction_count
            total_used += d.times_used
            total_helped += d.times_helped

        # Update base with combined data
        base.source_steps = list(all_sources)
        base.validation_count = total_validations
        base.contradiction_count = total_contradictions
        base.times_used = total_used
        base.times_helped = total_helped

        return base


# Singleton instance
_distillation_engine: Optional[DistillationEngine] = None


def get_distillation_engine() -> DistillationEngine:
    """Get the singleton distillation engine instance."""
    global _distillation_engine
    if _distillation_engine is None:
        _distillation_engine = DistillationEngine()
    return _distillation_engine
