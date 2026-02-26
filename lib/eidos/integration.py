"""
EIDOS Integration: Connect EIDOS to Claude Code Hooks

This module bridges the EIDOS intelligence system with the Claude Code
hook system. It provides functions to:

1. Create Episodes when sessions start
2. Create Steps for each tool call (with prediction/result/evaluation)
3. Run Control Plane checks before tools execute
4. Capture Evidence from tool outputs
5. Run Distillation when sessions end

The Vertical Loop:
Action → Prediction → Outcome → Evaluation → Policy Update → Distillation → Mandatory Reuse
"""

import json
import os
import time
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    Episode, Step, Distillation, Policy,
    Budget, Phase, Outcome, Evaluation, ActionType
)
from .control_plane import get_control_plane, ControlDecision
from .memory_gate import MemoryGate, score_step_importance
from .distillation_engine import get_distillation_engine
from .store import get_store
from .evidence_store import get_evidence_store, Evidence, EvidenceType, create_evidence_from_tool
from .guardrails import GuardrailEngine
from .escalation import build_escalation, EscalationType
from .validation import validate_step, get_deferred_tracker

# Elevated Control Layer
from .elevated_control import (
    get_elevated_control_plane,
    WatcherAlert, EscapeProtocolResult,
    validate_step_envelope
)
from .minimal_mode import get_minimal_mode_controller


# ===== Session/Episode Tracking =====

ACTIVE_EPISODES_FILE = Path.home() / ".spark" / "eidos_active_episodes.json"
ACTIVE_STEPS_FILE = Path.home() / ".spark" / "eidos_active_steps.json"
PENDING_GOALS_FILE = Path.home() / ".spark" / "eidos_pending_goals.json"

# Stale episode threshold: episodes older than 30 min with no end_ts are abandoned
STALE_EPISODE_THRESHOLD_S = 1800


def _load_active_episodes() -> Dict[str, str]:
    """Load session_id -> episode_id mapping."""
    try:
        if ACTIVE_EPISODES_FILE.exists():
            return json.loads(ACTIVE_EPISODES_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_active_episodes(mapping: Dict[str, str]):
    """Save session_id -> episode_id mapping."""
    try:
        ACTIVE_EPISODES_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACTIVE_EPISODES_FILE.write_text(json.dumps(mapping), encoding="utf-8")
    except Exception:
        pass


def _load_active_step(session_id: str) -> Optional[Dict]:
    """Load the active step for a session (used between pre and post tool)."""
    try:
        if ACTIVE_STEPS_FILE.exists():
            try:
                steps = json.loads(ACTIVE_STEPS_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                return None  # Corrupted file, skip gracefully
            return steps.get(session_id)
    except Exception:
        pass
    return None


def _save_active_step(session_id: str, step_data: Optional[Dict]):
    """Save the active step for a session."""
    try:
        ACTIVE_STEPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        steps = {}
        if ACTIVE_STEPS_FILE.exists():
            try:
                steps = json.loads(ACTIVE_STEPS_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                steps = {}  # Reset on corruption

        if step_data:
            steps[session_id] = step_data
        elif session_id in steps:
            del steps[session_id]

        # Clean old entries (> 10 min)
        cutoff = time.time() - 600
        steps = {k: v for k, v in steps.items()
                 if isinstance(v, dict) and v.get("timestamp", 0) > cutoff}

        # Atomic write to prevent corruption
        tmp = ACTIVE_STEPS_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(steps), encoding="utf-8")
        tmp.replace(ACTIVE_STEPS_FILE)
    except Exception:
        pass


def _load_pending_goals() -> Dict[str, str]:
    """Load session_id -> goal mapping for goals that arrived before episode creation."""
    try:
        if PENDING_GOALS_FILE.exists():
            data = json.loads(PENDING_GOALS_FILE.read_text(encoding="utf-8"))
            # Clean entries older than 10 min
            cutoff = time.time() - 600
            return {k: v for k, v in data.items()
                    if isinstance(v, dict) and v.get("ts", 0) > cutoff}
    except Exception:
        pass
    return {}


def _save_pending_goal(session_id: str, goal: str):
    """Store a goal for a session that doesn't have an episode yet."""
    try:
        PENDING_GOALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        pending = _load_pending_goals()
        pending[session_id] = {"goal": goal, "ts": time.time()}
        PENDING_GOALS_FILE.write_text(json.dumps(pending), encoding="utf-8")
    except Exception:
        pass


def _consume_pending_goal(session_id: str) -> str:
    """Get and remove pending goal for a session. Returns '' if none."""
    try:
        pending = _load_pending_goals()
        if session_id in pending:
            goal = pending[session_id].get("goal", "")
            del pending[session_id]
            PENDING_GOALS_FILE.write_text(json.dumps(pending), encoding="utf-8")
            return goal
    except Exception:
        pass
    return ""


# ===== Episode Management =====

def get_or_create_episode(
    session_id: str,
    goal: str = "",
    cwd: str = ""
) -> Episode:
    """Get existing episode for session or create new one.

    If no goal is provided, a generic placeholder is used and can be
    refined later via ``update_episode_goal``.
    """
    store = get_store()
    mapping = _load_active_episodes()

    if session_id in mapping:
        episode = store.get_episode(mapping[session_id])
        if episode and episode.outcome == Outcome.IN_PROGRESS:
            # Check if episode is stale (no activity for STALE_EPISODE_THRESHOLD_S)
            elapsed = time.time() - episode.start_ts
            if elapsed > STALE_EPISODE_THRESHOLD_S and episode.step_count > 0:
                # Auto-close stale episode with partial outcome
                _auto_close_episode(store, episode)
                del mapping[session_id]
                _save_active_episodes(mapping)
                # Fall through to create a new one
            else:
                return episode

    # Check for pending goal from UserPromptSubmit (arrives before first tool use)
    pending_goal = _consume_pending_goal(session_id)

    # Priority: explicit goal > pending goal from user prompt > cwd-derived
    effective_goal = goal or pending_goal or _derive_goal_from_cwd(cwd)

    # Create new episode
    episode = Episode(
        episode_id="",
        goal=effective_goal,
        success_criteria="Complete user request successfully",
        constraints=[f"Working directory: {cwd}"] if cwd else [],
        budget=Budget(max_steps=50, max_time_seconds=1800)  # 30 min default
    )
    store.save_episode(episode)

    # Save mapping
    mapping[session_id] = episode.episode_id

    # Clean old mappings (keep last 100)
    if len(mapping) > 100:
        mapping = dict(list(mapping.items())[-100:])

    _save_active_episodes(mapping)

    return episode


def _is_generic_goal(goal: str) -> bool:
    """Check if an episode goal is generic/placeholder."""
    if not goal:
        return True
    return (goal.startswith("Session in")
            or goal.startswith("Claude Code session")
            or goal == "unknown")


def update_episode_goal(session_id: str, goal: str):
    """Update the goal of an active episode with a more specific description.

    Called when we get richer context (e.g., from a UserPromptSubmit event).
    If no episode exists yet (UserPromptSubmit arrives before first tool use),
    store the goal as pending for when the episode is created.
    """
    if not goal or len(goal.strip()) < 5:
        return

    clean_goal = goal[:200].replace("\n", " ").strip()

    store = get_store()
    mapping = _load_active_episodes()

    if session_id not in mapping:
        # Episode doesn't exist yet — store goal for later
        _save_pending_goal(session_id, clean_goal)
        return

    episode = store.get_episode(mapping[session_id])
    if not episode or episode.outcome != Outcome.IN_PROGRESS:
        return
    # Only update if current goal is generic
    if not _is_generic_goal(episode.goal):
        return
    episode.goal = clean_goal
    store.save_episode(episode)


def _derive_goal_from_cwd(cwd: str) -> str:
    """Derive a meaningful goal from the working directory."""
    if not cwd:
        return "Session in unknown project"
    # Extract the last directory component
    parts = cwd.replace("\\", "/").rstrip("/").split("/")
    project = parts[-1] if parts else "unknown"
    return f"Session in {project}"


def _auto_close_episode(store, episode: Episode):
    """Auto-close a stale episode and run distillation."""
    steps = store.get_episode_steps(episode.episode_id)
    passed = sum(1 for s in steps if s.evaluation == Evaluation.PASS)
    failed = sum(1 for s in steps if s.evaluation == Evaluation.FAIL)

    if failed > passed:
        outcome = Outcome.FAILURE
    elif passed > 0 and failed == 0:
        outcome = Outcome.SUCCESS  # All-pass episodes are genuine successes
    elif passed > 0:
        outcome = Outcome.PARTIAL  # Mixed pass/fail
    else:
        outcome = Outcome.ESCALATED

    episode.outcome = outcome
    episode.phase = Phase.CONSOLIDATE
    episode.end_ts = time.time()
    episode.final_evaluation = f"Auto-closed: {passed} passed, {failed} failed out of {len(steps)} steps"
    store.save_episode(episode)

    # Run distillation on auto-closed episodes
    if steps:
        _run_distillation(episode, steps)


def complete_episode(
    session_id: str,
    outcome: Outcome = Outcome.SUCCESS,
    final_evaluation: str = ""
) -> Optional[Episode]:
    """
    Complete an episode and run distillation.

    Called when session ends or user explicitly completes a task.
    """
    store = get_store()
    mapping = _load_active_episodes()

    if session_id not in mapping:
        return None

    episode = store.get_episode(mapping[session_id])
    if not episode:
        return None

    # Determine outcome from step data if not explicitly set
    steps = store.get_episode_steps(episode.episode_id)
    if outcome == Outcome.SUCCESS and steps:
        passed = sum(1 for s in steps if s.evaluation == Evaluation.PASS)
        failed = sum(1 for s in steps if s.evaluation == Evaluation.FAIL)
        if failed > 0 and passed == 0:
            outcome = Outcome.FAILURE
        elif failed > passed:
            outcome = Outcome.PARTIAL

    # Build evaluation summary if none provided
    if not final_evaluation and steps:
        passed = sum(1 for s in steps if s.evaluation == Evaluation.PASS)
        failed = sum(1 for s in steps if s.evaluation == Evaluation.FAIL)
        final_evaluation = f"{passed} passed, {failed} failed out of {len(steps)} steps"

    # Update episode
    episode.outcome = outcome
    episode.phase = Phase.CONSOLIDATE
    episode.end_ts = time.time()
    episode.final_evaluation = final_evaluation
    store.save_episode(episode)

    # Run distillation
    if steps:
        _run_distillation(episode, steps)

    # Remove from active
    del mapping[session_id]
    _save_active_episodes(mapping)

    return episode


def _run_distillation(episode: Episode, steps: List[Step]):
    """Run distillation on a completed episode, filtering low-value outputs."""
    store = get_store()
    engine = get_distillation_engine()

    # Prefer evaluated steps with actual outcomes to avoid unknown/pending noise.
    signal_steps = [
        s for s in steps
        if s.evaluation in (Evaluation.PASS, Evaluation.FAIL, Evaluation.PARTIAL)
        and ((s.result or "").strip() or (s.lesson or "").strip())
    ]
    effective_steps = signal_steps or steps

    reflection = engine.reflect_on_episode(episode, effective_steps)
    candidates = engine.generate_distillations(episode, effective_steps, reflection)

    saved = []
    for candidate in candidates:
        # Filter out primitive/low-value distillations before saving
        if _is_primitive_distillation(candidate.statement):
            continue
        # Allow low-start distillations (0.3-0.4) to earn trust via outcomes.
        if candidate.confidence < 0.3:
            continue
        distillation = engine.finalize_distillation(candidate)
        store.save_distillation(distillation)
        saved.append(distillation)

    # Keep retrieval pool clean: archive and purge low-quality legacy distillations.
    try:
        store.archive_and_purge_low_quality_distillations(unified_floor=0.35, dry_run=False, max_preview=0)
    except Exception:
        pass

    # Periodically merge duplicate/similar distillations
    # (the merge function existed but was never called)
    if saved:
        try:
            all_dists = store.get_all_distillations(limit=200)
            if len(all_dists) > 10:
                merged = engine.merge_similar_distillations(all_dists)
                if len(merged) < len(all_dists):
                    keep_ids = {m.distillation_id for m in merged}
                    remove_ids = [d.distillation_id for d in all_dists if d.distillation_id not in keep_ids]
                    if remove_ids:
                        import sqlite3 as _sql
                        with _sql.connect(store.db_path) as conn:
                            for rid in remove_ids:
                                conn.execute("DELETE FROM distillations WHERE distillation_id = ?", (rid,))
        except Exception:
            pass  # Never break the main flow


def _is_primitive_distillation(statement: str) -> bool:
    """Check if a distillation is primitive/operational rather than genuine wisdom.

    The test: would a human find this useful to know next time?

    Rejects:
    - Tool effectiveness statements ("Tool X is effective")
    - Generic approach restating ("use approach: git push")
    - Sequence patterns ("A -> B -> C")
    - Test-result echoes ("test passes")
    - Tautological policy ("for X requests, do X")

    Keeps:
    - Domain decisions ("Use UTC for token timestamps")
    - User preferences ("user prefers iterative fixes")
    - Architecture insights ("why X over Y")
    - Actionable cautions ("Always Read before Edit")
    """
    import re
    s = statement.lower().strip()

    # Too short to be useful
    if len(s) < 20:
        return True

    # Primitive patterns to reject
    primitive_patterns = [
        r"is effective for",
        r"success rate",
        r"over \d+ uses",
        r"sequence.*->",
        r"tool '.*' is effective",
        r"took \d+ steps",
        r"could optimize discovery",
        r"^\w+ integration test",        # "EIDOS integration test passes"
        r"use approach:",                  # "use approach: git push origin main"
        r"for similar requests",           # tautological policy
        r"\(\d+ successes?\)",             # "(3 successes)"
        r"unexpected outcomes when handling",  # too vague
    ]
    for pat in primitive_patterns:
        if re.search(pat, s):
            return True

    # === Semantic checks (catches tautologies and tool-name echoes) ===

    # Tool-name tautology: "When X tool, try: Use X tool"
    tool_names = {"read", "write", "edit", "bash", "grep", "glob",
                  "task", "webfetch", "websearch", "notebookedit"}
    for tn in tool_names:
        # "When Execute Read, try: Use Read tool" = tautology
        if f"use {tn}" in s and (f"execute {tn}" in s or f"when {tn}" in s):
            return True
        # "try: Use X tool" where the only advice is to use the tool
        if re.search(rf"try:?\s*use {tn}\s*tool\b", s):
            return True

    # Mechanical playbook: just tool names chained with arrows
    # e.g. "1. Use Glob tool -> 2. Use Read tool -> 3. Use Grep tool"
    if "playbook" in s:
        # Count unique non-tool words (excluding numbers, arrows, "use", "tool")
        words = re.findall(r'[a-z_]+', s)
        filler = {"use", "tool", "playbook", "for", "session", "in",
                  "unknown", "project", "claude", "code"} | tool_names
        meaningful_words = [w for w in words if w not in filler and len(w) > 2]
        if len(meaningful_words) < 3:
            return True

    # Generic session reference without substance
    if "session in unknown" in s or "session in unknown project" in s:
        return True

    # Condition and action are identical (tautology)
    # Pattern: "When <X>, <action that restates X>"
    m = re.match(r"when\s+(.{5,40}?),?\s+(?:try|do|use):?\s*(.{5,40})", s)
    if m:
        condition = re.sub(r'[^a-z]', '', m.group(1))
        action = re.sub(r'[^a-z]', '', m.group(2))
        # If condition and action share >70% of characters, it's a tautology
        if condition and action:
            overlap = len(set(condition) & set(action))
            total = max(len(set(condition) | set(action)), 1)
            if overlap / total > 0.7 and len(condition) < 30:
                return True

    # Command echo tautology: condition and action contain the same command/path
    # e.g. "When Run command: start X, try: Execute: start X"
    # Catches cases where "Run command:" vs "Execute:" use different prefixes
    # but the actual command payload is the same
    cmd_prefixes = r"(?:run command|execute|modify|inspect|locate|search for|write|read|edit):?\s*"
    m2 = re.match(rf"when\s+{cmd_prefixes}(.{{10,}}?),?\s+try:?\s*{cmd_prefixes}(.{{10,}})", s)
    if m2:
        payload1 = re.sub(r'[^a-z0-9]', '', m2.group(1).lower())
        payload2 = re.sub(r'[^a-z0-9]', '', m2.group(2).lower())
        if payload1 and payload2:
            # If payloads are identical or one contains the other
            if payload1 == payload2 or payload1 in payload2 or payload2 in payload1:
                return True
            # Or high word overlap
            words1 = set(re.findall(r'[a-z]{3,}', m2.group(1).lower()))
            words2 = set(re.findall(r'[a-z]{3,}', m2.group(2).lower()))
            if words1 and words2:
                overlap_ratio = len(words1 & words2) / max(len(words1 | words2), 1)
                if overlap_ratio > 0.6:
                    return True

    return False


# ===== Step Management =====

def create_step_before_action(
    session_id: str,
    tool_name: str,
    tool_input: Dict[str, Any],
    prediction: Dict[str, Any],
    trace_id: Optional[str] = None
) -> Tuple[Optional[Step], Optional[ControlDecision]]:
    """
    Create a step BEFORE the tool executes.

    This implements the EIDOS vertical loop with Elevated Control:
    1. State intent and decision
    2. Make prediction (with hypothesis and stop condition)
    3. Check elevated control plane (watchers, escape protocol)
    4. Return step and control decision

    Returns:
        (Step, ControlDecision) - Step to complete later, control decision
    """
    episode = get_or_create_episode(session_id, cwd=tool_input.get("cwd", ""))
    store = get_store()
    elevated = get_elevated_control_plane()
    guardrails = GuardrailEngine()
    minimal = get_minimal_mode_controller()

    if not trace_id:
        raw = f"{session_id}|{tool_name}|{time.time()}"
        trace_id = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    # Retrieve relevant distillations/memories for this step
    retrieved_memory_ids = []
    memory_cited = False
    memory_absent = True
    try:
        from .retriever import get_retriever
        retriever = get_retriever()
        intent_str = f"{tool_name} {str(tool_input)[:100]}"
        distillations = retriever.retrieve_for_intent(intent_str)
        if distillations:
            retrieved_memory_ids = [d.distillation_id for d in distillations[:5]]
            memory_cited = True
            memory_absent = False
    except Exception:
        pass  # Graceful degradation if retriever fails

    # Create step with FULL Step Envelope
    # Build descriptive intent/decision from tool_input (not templates)
    intent_desc = _describe_intent(tool_name, tool_input)
    decision_desc = _describe_decision(tool_name, tool_input)
    step = Step(
        step_id="",
        episode_id=episode.episode_id,
        trace_id=trace_id,
        intent=intent_desc,
        decision=decision_desc,
        hypothesis=prediction.get("reason", ""),  # Falsifiable hypothesis
        alternatives=[],
        assumptions=_extract_assumptions(tool_name, tool_input),
        prediction=prediction.get("reason", "Tool will succeed"),
        stop_condition=f"If {tool_name} fails twice, diagnose before retry",  # Required
        confidence_before=prediction.get("confidence", 0.5),
        budget_snapshot={
            "step_count": episode.step_count,
            "max_steps": episode.budget.max_steps,
            "percentage_used": episode.budget_percentage_used(),
        },
        action_type=ActionType.TOOL_CALL,
        action_details={
            "tool": tool_name,
            **{k: str(v)[:200] for k, v in tool_input.items() if k != "content"}
        },
        retrieved_memories=retrieved_memory_ids,
        memory_cited=memory_cited,
        memory_absent_declared=memory_absent,
    )

    # Save preliminary step to DB FIRST (before control checks)
    # This ensures steps are tracked even if guardrails advise blocking,
    # since Claude Code runs the tool regardless. Uses INSERT OR REPLACE
    # so post-action save will update this row.
    store.save_step(step)

    # Save to JSON for fast pre/post handoff (includes prediction data)
    _save_active_step(session_id, {
        "step_id": step.step_id,
        "episode_id": episode.episode_id,
        "tool_name": tool_name,
        "prediction": prediction,
        "trace_id": trace_id,
        "timestamp": time.time(),
        "retrieved_distillation_ids": retrieved_memory_ids,
        "intent": step.intent,
        "decision": step.decision,
        "action_details": step.action_details,
    })

    # Update episode step count
    episode.step_count += 1
    store.save_episode(episode)

    # Now run control checks (advisory — Claude Code proceeds regardless)
    # Minimal mode gate
    allowed_mm, mm_reason = minimal.check_action_allowed(tool_name, tool_input)
    if not allowed_mm:
        return step, ControlDecision(
            allowed=False,
            message=mm_reason,
            required_action="diagnostics only until minimal mode exits"
        )

    # Get recent steps for context
    recent_steps = store.get_episode_steps(episode.episode_id)[-10:]

    # Check legacy guardrails
    guard_result = guardrails.is_blocked(episode, step, recent_steps)
    if guard_result:
        return step, ControlDecision(
            allowed=False,
            message=guard_result.message,
            required_action="; ".join(guard_result.required_actions)
        )

    # Check elevated control plane (includes watchers and escape protocol)
    allowed, alerts, escape_result = elevated.check_before_action(
        episode, step, recent_steps, memories_exist=bool(retrieved_memory_ids)
    )

    if not allowed:
        if escape_result:
            message = f"ESCAPE PROTOCOL: {escape_result.reason}\n{escape_result.summary}"
            required = escape_result.discriminating_test
        elif alerts:
            message = "; ".join([a.message for a in alerts])
            required = alerts[0].required_output if alerts else ""
        else:
            message = "Action blocked by control plane"
            required = ""

        return step, ControlDecision(
            allowed=False,
            message=message,
            required_action=required
        )

    return step, ControlDecision(allowed=True, message="")


def complete_step_after_action(
    session_id: str,
    tool_name: str,
    success: bool,
    result: str = "",
    error: str = ""
) -> Optional[Step]:
    """
    Complete a step AFTER the tool executes.

    This implements the EIDOS vertical loop with Elevated Control:
    1. Record result with validation evidence
    2. Evaluate against prediction
    3. Calculate surprise and confidence delta
    4. Extract lesson
    5. Process through elevated control plane
    6. Score for memory persistence
    """
    step_data = _load_active_step(session_id)
    if not step_data or step_data.get("tool_name") != tool_name:
        return None

    episode = get_or_create_episode(session_id)
    store = get_store()
    elevated = get_elevated_control_plane()
    gate = MemoryGate()

    prediction = step_data.get("prediction", {})
    trace_id = step_data.get("trace_id")
    predicted_success = prediction.get("outcome", "success") == "success"
    confidence_before = prediction.get("confidence", 0.5)

    # Calculate evaluation
    if success:
        evaluation = Evaluation.PASS
    else:
        evaluation = Evaluation.FAIL

    # Calculate surprise
    surprise = 0.0
    if predicted_success and not success:
        surprise = confidence_before  # High confidence + failure = surprise
    elif not predicted_success and success:
        surprise = 1 - confidence_before  # Low confidence + success = surprise

    # Extract lesson
    lesson = _extract_lesson(tool_name, success, error, prediction)

    # Update confidence
    confidence_after = confidence_before
    if success:
        confidence_after = min(1.0, confidence_before + 0.1)
    else:
        confidence_after = max(0.1, confidence_before - 0.2)

    confidence_delta = confidence_after - confidence_before

    # Create completed step with FULL envelope
    # Preserve descriptive intent/decision from pre-action step (avoid template overwrite)
    pre_intent = step_data.get("intent", f"Execute {tool_name}")
    pre_decision = step_data.get("decision", f"Use {tool_name} tool")
    pre_action_details = step_data.get("action_details", {"tool": tool_name})
    step = Step(
        step_id=step_data.get("step_id", ""),
        episode_id=episode.episode_id,
        trace_id=trace_id,
        intent=pre_intent,
        decision=pre_decision,
        hypothesis=prediction.get("reason", ""),
        prediction=prediction.get("reason", ""),
        stop_condition=f"If {tool_name} fails twice, diagnose",
        confidence_before=confidence_before,
        action_type=ActionType.TOOL_CALL,
        action_details=pre_action_details,
        result=result[:500] if result else (error[:500] if error else ""),
        validation_evidence=f"exit_code={'0' if success else '1'}; output_length={len(result or error or '')}",
        evaluation=evaluation,
        surprise_level=surprise,
        lesson=lesson,
        confidence_after=confidence_after,
        confidence_delta=confidence_delta,
        validated=True,
        validation_method="test:passed" if success else "test:failed",
        is_valid=True,
        evidence_gathered=bool(result or error),
        progress_made=success,
        memory_absent_declared=True,  # For now
    )

    # Save step
    store.save_step(step)

    # Process through elevated control plane
    new_phase, messages = elevated.process_after_action(episode, step)

    # Close feedback loop: mark retrieved distillations as helped/not-helped
    _update_distillation_feedback(step_data, success)

    # Score for memory persistence
    score = gate.score_step(step, context={"domain": "general"})
    if not score.is_durable:
        gate.set_cache_expiry(step.step_id, hours=24)

    # Capture evidence
    if result or error:
        ev_store = get_evidence_store()
        evidence = create_evidence_from_tool(
            step_id=step.step_id,
            tool_name=tool_name,
            output=error if error else result,
            exit_code=0 if success else 1,
            trace_id=trace_id,
        )
        ev_store.save(evidence)

    # Update episode phase if needed
    if new_phase != episode.phase:
        episode.phase = new_phase
        store.save_episode(episode)

    # Clear active step
    _save_active_step(session_id, None)

    return step


# ===== Helper Functions =====

def _update_distillation_feedback(step_data: Dict, success: bool):
    """Close the feedback loop: mark retrieved distillations as helped/not-helped.

    Only records feedback when there's a meaningful signal:
    - Failures always recorded (something went wrong, distillation didn't prevent it)
    - Successes only recorded if the step had high surprise (unexpected success
      where distillation may have genuinely helped)
    - Routine successes (most tool calls) are skipped to avoid noise
    - Anti-patterns only get feedback if the step is actually doing what the
      anti-pattern warns against (prevents "blame all anti-patterns for everything")

    This prevents the "blame everyone for everything" anti-pattern where
    irrelevant distillations get contradicted just because a Read failed.
    """
    distillation_ids = step_data.get("retrieved_distillation_ids", [])
    if not distillation_ids:
        return

    # Only record feedback for meaningful signals
    prediction = step_data.get("prediction", {})
    predicted_success = prediction.get("outcome", "success") == "success"

    if success and predicted_success:
        # Routine success (predicted and happened) — no learning signal
        # Recording this would just inflate "helped" counts on every Read/Grep
        return

    try:
        from .retriever import get_retriever
        from .store import get_store as _get_store
        retriever = get_retriever()
        store = _get_store()
        step_decision = (step_data.get("decision") or "").lower()

        for did in distillation_ids:
            # For anti-patterns, only record feedback if the step is actually
            # doing what the anti-pattern warns against. Otherwise the
            # anti-pattern accumulates contradictions from unrelated actions.
            dist = store.get_distillation(did)
            if dist and dist.type.value == "anti_pattern":
                if not _is_anti_pattern_relevant(dist.statement, step_decision):
                    continue  # Skip feedback — not relevant to this step

            retriever.record_usage(did, helped=success)
    except Exception:
        pass  # Never break the main flow


def _is_anti_pattern_relevant(anti_statement: str, step_decision: str) -> bool:
    """Check if an anti-pattern is actually about what this step is doing.

    An anti-pattern like "When repeated 'find' commands fail..." should only
    get feedback when the step is actually running a find command, not when
    it's running git push.
    """
    import re
    anti_lower = anti_statement.lower()
    decision_lower = step_decision.lower()

    # Extract quoted content from anti-pattern (the specific thing to avoid)
    quoted = re.findall(r"'([^']+)'", anti_lower)
    if quoted:
        # Check if any quoted term appears in the step decision
        return any(q in decision_lower for q in quoted)

    # Extract key action words from anti-pattern
    anti_words = set(re.findall(r'\b[a-z]{4,}\b', anti_lower))
    decision_words = set(re.findall(r'\b[a-z]{4,}\b', decision_lower))

    # Remove generic words
    generic = {
        "when", "repeated", "attempts", "fail", "without", "progress",
        "step", "back", "different", "approach", "avoid", "repeatedly",
        "attempting", "information", "commands", "operations",
    }
    anti_words -= generic
    decision_words -= generic

    # Need at least 2 meaningful word overlap
    overlap = len(anti_words & decision_words)
    return overlap >= 2


def _describe_intent(tool_name: str, tool_input: Dict) -> str:
    """Build a descriptive intent from tool name and input.

    Instead of generic 'Execute Edit', produce something like
    'Edit lib/meta_ralph.py to fix scoring threshold'.
    """
    ti = tool_input or {}
    try:
        if tool_name == "Edit":
            fp = ti.get("file_path", "")
            short = fp.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if fp else "file"
            old = str(ti.get("old_string", ""))[:40].replace("\n", " ").strip()
            return f"Edit {short} (replace '{old}')" if old else f"Edit {short}"
        if tool_name == "Read":
            fp = ti.get("file_path", "")
            short = fp.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if fp else "file"
            return f"Read {short}"
        if tool_name == "Write":
            fp = ti.get("file_path", "")
            short = fp.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if fp else "file"
            return f"Write {short}"
        if tool_name == "Bash":
            cmd = str(ti.get("command", ""))[:60].split("\n")[0].strip()
            return f"Run command: {cmd}" if cmd else "Run shell command"
        if tool_name == "Glob":
            pat = ti.get("pattern", "")
            return f"Find files matching {pat}" if pat else "Find files"
        if tool_name == "Grep":
            pat = ti.get("pattern", "")
            return f"Search for '{pat[:40]}'" if pat else "Search file contents"
        if tool_name == "Task":
            desc = ti.get("description", "") or ti.get("prompt", "")[:50]
            return f"Delegate: {desc}" if desc else "Delegate subtask"
    except Exception:
        pass
    return f"{tool_name} operation"


def _describe_decision(tool_name: str, tool_input: Dict) -> str:
    """Build a descriptive decision from tool context.

    Instead of 'Use Edit tool', produce something like
    'Modify scoring threshold in meta_ralph.py'.
    """
    ti = tool_input or {}
    try:
        if tool_name == "Edit":
            fp = ti.get("file_path", "")
            short = fp.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if fp else "file"
            new = str(ti.get("new_string", ""))[:40].replace("\n", " ").strip()
            return f"Modify {short}: '{new}'" if new else f"Modify {short}"
        if tool_name == "Write":
            fp = ti.get("file_path", "")
            short = fp.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if fp else "file"
            return f"Create/overwrite {short}"
        if tool_name == "Bash":
            cmd = str(ti.get("command", ""))[:40].split("\n")[0].strip()
            return f"Execute: {cmd}" if cmd else "Execute shell command"
        if tool_name == "Read":
            fp = ti.get("file_path", "")
            short = fp.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if fp else "file"
            return f"Inspect {short}"
        if tool_name == "Grep":
            pat = ti.get("pattern", "")[:30]
            return f"Search codebase for '{pat}'" if pat else "Search codebase"
        if tool_name == "Glob":
            return f"Locate files by pattern"
    except Exception:
        pass
    return f"Apply {tool_name}"


def _extract_assumptions(tool_name: str, tool_input: Dict) -> List[str]:
    """Extract assumptions for a tool call."""
    assumptions = []

    if tool_name == "Edit":
        assumptions.append("File exists at specified path")
        assumptions.append("old_string exists in file content")
    elif tool_name == "Read":
        assumptions.append("File exists and is readable")
    elif tool_name == "Write":
        assumptions.append("Parent directory exists")
        assumptions.append("Have write permissions")
    elif tool_name == "Bash":
        assumptions.append("Command is valid")
        assumptions.append("Required tools are installed")
    elif tool_name == "Glob":
        assumptions.append("Pattern will match files")
    elif tool_name == "Grep":
        assumptions.append("Pattern exists in searched files")

    return assumptions


def _extract_lesson(
    tool_name: str,
    success: bool,
    error: str,
    prediction: Dict
) -> str:
    """Extract a lesson from the tool execution result.

    Only returns non-empty lessons when there is genuine signal:
    - Surprising outcomes (high confidence wrong)
    - Actionable error patterns
    - Skips empty/generic lessons to avoid noise
    """
    confidence = prediction.get("confidence", 0.5)
    error_lower = error.lower() if error else ""

    if success:
        # Only generate lesson for genuinely surprising success
        if confidence < 0.35:
            return f"{tool_name} succeeded at {confidence:.0%} confidence - this pattern is more reliable than expected"
        # Successful as predicted -- no lesson needed, avoid noise
        return ""

    # Failure lessons -- only for actionable patterns
    if "not found in file" in error_lower:
        return "Always Read file before Edit to verify content matches"
    elif "no such file" in error_lower or "does not exist" in error_lower:
        return "Verify file exists with Glob before operating on it"
    elif "permission denied" in error_lower:
        return "Check file permissions before write operations"
    elif "timeout" in error_lower:
        return "Consider breaking into smaller operations or increasing timeout"
    elif "syntax error" in error_lower:
        return "Validate syntax before execution"
    elif "connection refused" in error_lower:
        return "Verify service is running before connecting"

    # Only flag high-confidence failures as lessons
    if confidence > 0.75:
        return f"Overconfident ({confidence:.0%}) on {tool_name} - reassess: {error[:60]}" if error else ""

    # Low/medium confidence failure -- not surprising, skip noise
    return ""


# ===== Convenience Functions =====

def should_block_action(session_id: str, tool_name: str, tool_input: Dict) -> Optional[str]:
    """
    Quick check if action should be blocked.

    Returns blocking message or None if allowed.
    """
    episode = get_or_create_episode(session_id)
    store = get_store()
    control = get_control_plane()
    guardrails = GuardrailEngine()
    minimal = get_minimal_mode_controller()

    allowed_mm, mm_reason = minimal.check_action_allowed(tool_name, tool_input)
    if not allowed_mm:
        return mm_reason

    # Create minimal step for checking
    step = Step(
        step_id="",
        episode_id=episode.episode_id,
        intent=f"Execute {tool_name}",
        decision=f"Use {tool_name}",
        action_type=ActionType.TOOL_CALL,
        action_details={"tool": tool_name, **tool_input}
    )

    recent_steps = store.get_episode_steps(episode.episode_id)[-10:]

    # Check guardrails
    guard_result = guardrails.is_blocked(episode, step, recent_steps)
    if guard_result:
        return guard_result.message

    # Check control plane
    decision = control.check_before_action(episode, step, recent_steps)
    if not decision.allowed:
        return decision.message

    return None


def get_active_episode_stats(session_id: str) -> Dict[str, Any]:
    """Get stats for the active episode."""
    episode = get_or_create_episode(session_id)
    store = get_store()
    steps = store.get_episode_steps(episode.episode_id)

    passed = len([s for s in steps if s.evaluation == Evaluation.PASS])
    failed = len([s for s in steps if s.evaluation == Evaluation.FAIL])

    return {
        "episode_id": episode.episode_id,
        "goal": episode.goal,
        "phase": episode.phase.value,
        "outcome": episode.outcome.value,
        "step_count": len(steps),
        "passed": passed,
        "failed": failed,
        "budget_remaining": episode.budget.max_steps - len(steps),
        "elapsed_seconds": time.time() - episode.start_ts,
    }


def generate_escalation(session_id: str, blocker: str) -> str:
    """Generate an escalation report for the current episode."""
    episode = get_or_create_episode(session_id)
    store = get_store()
    steps = store.get_episode_steps(episode.episode_id)

    # Determine escalation type
    if episode.is_budget_exceeded():
        esc_type = EscalationType.BUDGET
    elif any(c >= 3 for c in episode.error_counts.values()):
        esc_type = EscalationType.LOOP
    else:
        esc_type = EscalationType.BLOCKED

    escalation = build_escalation(episode, steps, esc_type, blocker)
    return escalation.to_yaml()


def get_eidos_health() -> Dict[str, Any]:
    """Get EIDOS system health summary for observability.

    Returns a dict with:
    - episode stats (total, active, completed, success rate)
    - distillation stats (total, used, helped, feedback ratio)
    - step stats (total, pass rate)
    - stale episode count
    """
    store = get_store()
    stats = store.get_stats()

    # Count stale episodes
    now = time.time()
    stale_count = 0
    try:
        recent = store.get_recent_episodes(limit=50)
        for ep in recent:
            if (ep.outcome == Outcome.IN_PROGRESS and
                    now - ep.start_ts > STALE_EPISODE_THRESHOLD_S):
                stale_count += 1
    except Exception:
        pass

    # Distillation feedback ratio
    dist_total = stats.get("distillations", 0)
    dist_used = 0
    dist_helped = 0
    try:
        all_dist = store.get_all_distillations(limit=100)
        dist_used = sum(1 for d in all_dist if d.times_used > 0)
        dist_helped = sum(1 for d in all_dist if d.times_helped > 0)
    except Exception:
        pass

    return {
        "episodes": {
            "total": stats.get("episodes", 0),
            "success_rate": stats.get("success_rate", 0),
            "stale": stale_count,
        },
        "steps": {
            "total": stats.get("steps", 0),
        },
        "distillations": {
            "total": dist_total,
            "used": dist_used,
            "helped": dist_helped,
            "feedback_ratio": dist_helped / max(dist_used, 1),
            "high_confidence": stats.get("high_confidence_distillations", 0),
        },
        "policies": stats.get("policies", 0),
    }


def cleanup_stale_episodes() -> int:
    """Clean up stale in_progress episodes. Returns count cleaned."""
    store = get_store()
    now = time.time()
    cleaned = 0

    try:
        recent = store.get_recent_episodes(limit=100)
        for ep in recent:
            if (ep.outcome == Outcome.IN_PROGRESS and
                    now - ep.start_ts > STALE_EPISODE_THRESHOLD_S and
                    ep.step_count > 0):
                _auto_close_episode(store, ep)
                cleaned += 1
    except Exception:
        pass

    return cleaned
