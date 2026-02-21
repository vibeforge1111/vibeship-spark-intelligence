#!/usr/bin/env python3
"""
Spark Observation Hook: Ultra-fast event capture + Surprise Detection + EIDOS Integration

This hook is called by Claude Code to capture tool usage events.
It MUST complete quickly to avoid slowdown.

EIDOS Integration:
- PreToolUse: Create Episode/Step, make prediction, check control plane
- PostToolUse: Complete Step, evaluate prediction, capture evidence
- PostToolUseFailure: Complete Step with error, learn from failure

The Vertical Loop:
Action → Prediction → Outcome → Evaluation → Policy Update → Distillation → Mandatory Reuse

Usage in .claude/settings.json:
{
  "hooks": {
    "PreToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": "python /path/to/spark/hooks/observe.py"}]}],
    "PostToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": "python /path/to/spark/hooks/observe.py"}]}],
    "PostToolUseFailure": [{"matcher": "", "hooks": [{"type": "command", "command": "python /path/to/spark/hooks/observe.py"}]}]
  }
}
"""

import sys
import json
import time
import os
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.queue import quick_capture, EventType
from lib.cognitive_learner import get_cognitive_learner
from lib.feedback import update_skill_effectiveness, update_self_awareness_reliability
from lib.diagnostics import log_debug
from lib.outcome_checkin import record_checkin_request
# EIDOS Integration
EIDOS_ENABLED = os.environ.get("SPARK_EIDOS_ENABLED", "1") == "1"

if EIDOS_ENABLED:
    try:
        from lib.eidos.integration import (
            create_step_before_action,
            complete_step_after_action,
            should_block_action,
            get_or_create_episode,
            complete_episode,
            generate_escalation,
        )
        from lib.eidos.models import Outcome
        EIDOS_AVAILABLE = True
    except ImportError as e:
        log_debug("observe", "EIDOS import failed", e)
        EIDOS_AVAILABLE = False
else:
    EIDOS_AVAILABLE = False

# ===== Prediction Tracking =====
# We track predictions made at PreToolUse to compare at PostToolUse

PREDICTION_FILE = Path.home() / ".spark" / "active_predictions.json"
CHECKIN_MIN_S = int(os.environ.get("SPARK_OUTCOME_CHECKIN_MIN_S", "1800"))
ADVICE_FEEDBACK_ENABLED = os.environ.get("SPARK_ADVICE_FEEDBACK", "1") == "1"
ADVICE_FEEDBACK_PROMPT = os.environ.get("SPARK_ADVICE_FEEDBACK_PROMPT", "1") == "1"
ADVICE_FEEDBACK_MIN_S = int(os.environ.get("SPARK_ADVICE_FEEDBACK_MIN_S", "600"))
PRETOOL_BUDGET_MS = float(os.environ.get("SPARK_OBSERVE_PRETOOL_BUDGET_MS", "2500"))
EIDOS_ENFORCE_BLOCK = os.environ.get("SPARK_EIDOS_ENFORCE_BLOCK", "0") == "1"
HOOK_PAYLOAD_TEXT_LIMIT = int(os.environ.get("SPARK_HOOK_PAYLOAD_TEXT_LIMIT", "3000"))

# ===== Session Failure Tracking =====
# Track which tools failed in this session so we can detect recovery patterns.
# Recovery = tool fails, then succeeds later = advice may have helped.
FAILURE_TRACKING_FILE = Path.home() / ".spark" / "session_failures.json"


def record_session_failure(session_id: str, tool_name: str):
    """Record that a tool failed in this session for recovery detection."""
    try:
        FAILURE_TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)
        failures = {}
        if FAILURE_TRACKING_FILE.exists():
            failures = json.loads(FAILURE_TRACKING_FILE.read_text())

        key = f"{session_id}:{tool_name}"
        failures[key] = {"timestamp": time.time(), "tool": tool_name}

        # Clean entries older than 30 min (session-scoped)
        cutoff = time.time() - 1800
        failures = {
            k: v for k, v in failures.items()
            if v.get("timestamp", 0) > cutoff
        }
        FAILURE_TRACKING_FILE.write_text(json.dumps(failures))
    except Exception as e:
        log_debug("observe", "record_session_failure failed", e)


def had_prior_failure(session_id: str, tool_name: str) -> bool:
    """Check if this tool previously failed in this session (recovery detection)."""
    try:
        if not FAILURE_TRACKING_FILE.exists():
            return False
        failures = json.loads(FAILURE_TRACKING_FILE.read_text())
        key = f"{session_id}:{tool_name}"
        entry = failures.get(key)
        if not entry:
            return False
        # Only count failures within last 30 min
        if time.time() - entry.get("timestamp", 0) > 1800:
            return False
        # Clear the failure record (one-shot recovery detection)
        del failures[key]
        FAILURE_TRACKING_FILE.write_text(json.dumps(failures))
        return True
    except Exception:
        return False


def save_prediction(session_id: str, tool_name: str, prediction: dict):
    """Save a prediction for later comparison."""
    try:
        PREDICTION_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        predictions = {}
        if PREDICTION_FILE.exists():
            predictions = json.loads(PREDICTION_FILE.read_text())
        
        # Key by session + tool
        key = f"{session_id}:{tool_name}"
        predictions[key] = {
            **prediction,
            "timestamp": time.time()
        }
        
        # Clean old predictions (> 5 min old)
        cutoff = time.time() - 300
        predictions = {
            k: v for k, v in predictions.items()
            if v.get("timestamp", 0) > cutoff
        }
        
        PREDICTION_FILE.write_text(json.dumps(predictions))
    except Exception as e:
        log_debug("observe", "save_prediction failed", e)
        pass


def get_prediction(session_id: str, tool_name: str) -> dict:
    """Get prediction made for this tool call."""
    try:
        if not PREDICTION_FILE.exists():
            return {}
        
        predictions = json.loads(PREDICTION_FILE.read_text())
        key = f"{session_id}:{tool_name}"
        pred = predictions.pop(key, {})
        
        # Save without this prediction
        PREDICTION_FILE.write_text(json.dumps(predictions))
        
        return pred
    except Exception as e:
        log_debug("observe", "get_prediction failed", e)
        return {}


def _load_tool_success_rates() -> dict:
    """Load historical tool success rates from EIDOS store.

    Returns a dict of {tool_name: success_rate} based on step data.
    Cached with a 5-minute TTL.
    """
    cache_file = Path.home() / ".spark" / "tool_success_cache.json"
    try:
        if cache_file.exists():
            data = json.loads(cache_file.read_text())
            if time.time() - data.get("ts", 0) < 300:  # 5 min TTL
                return data.get("rates", {})
    except Exception:
        pass

    rates = {}
    try:
        if EIDOS_AVAILABLE:
            from lib.eidos.store import get_store
            store = get_store()
            steps = store.get_recent_steps(limit=200)
            tool_counts = {}
            for s in steps:
                tool = s.action_details.get("tool", "")
                if not tool:
                    continue
                if tool not in tool_counts:
                    tool_counts[tool] = {"total": 0, "pass": 0}
                tool_counts[tool]["total"] += 1
                if s.evaluation.value == "pass":
                    tool_counts[tool]["pass"] += 1
            for tool, counts in tool_counts.items():
                if counts["total"] >= 3:
                    rates[tool] = round(counts["pass"] / counts["total"], 3)

            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({"ts": time.time(), "rates": rates}))
    except Exception:
        pass

    return rates


def make_prediction(tool_name: str, tool_input: dict) -> dict:
    """
    Make a prediction about this tool call.

    Uses EIDOS historical success rates as a Bayesian prior,
    adjusted by input-pattern heuristics.
    """
    historical_rates = _load_tool_success_rates()
    historical_rate = historical_rates.get(tool_name)

    # Default baseline by tool type
    baseline = 0.7
    reason = "default assumption"

    if tool_name == "Edit":
        baseline = 0.6
        reason = "Edit can fail if content doesn't match"
    elif tool_name == "Bash":
        baseline = 0.65
        reason = "Bash command"
        command = str(tool_input.get("command", ""))
        if any(x in command for x in ["rm -rf", "sudo", "chmod"]):
            baseline = 0.4
            reason = "Dangerous command pattern"
        elif command.count("|") > 2:
            baseline = 0.5
            reason = "Complex pipe chain"
        elif any(x in command for x in ["git status", "git log", "ls", "pwd"]):
            baseline = 0.9
            reason = "Safe read-only command"
    elif tool_name == "Write":
        baseline = 0.85
        reason = "Write usually succeeds"
    elif tool_name == "Read":
        baseline = 0.8
        reason = "Read usually succeeds"
    elif tool_name == "Glob":
        baseline = 0.9
        reason = "Glob is reliable"
    elif tool_name == "Grep":
        baseline = 0.85
        reason = "Grep is reliable"

    # Blend historical rate with baseline (trust the data)
    if historical_rate is not None:
        confidence = 0.7 * historical_rate + 0.3 * baseline
        reason = f"Historical: {historical_rate:.0%}, heuristic: {baseline:.0%}"
    else:
        confidence = baseline

    outcome = "success" if confidence >= 0.5 else "failure"

    return {
        "outcome": outcome,
        "confidence": round(confidence, 3),
        "reason": reason,
        "tool": tool_name,
    }


# Domain detection and cognitive signal extraction now live in lib/cognitive_signals.py
from lib.cognitive_signals import detect_domain, DOMAIN_TRIGGERS, extract_cognitive_signals  # noqa: F401


def _estimate_advisory_readiness(text: str, source: str, tool_name: str = "") -> float:
    """Estimate how usable a raw event surface is for downstream advisory transformation.

    This is a lightweight signal for intake prioritization and later ranking.
    """
    t = (text or "").strip()
    if not t:
        return 0.0

    lower = t.lower()
    readiness = 0.05

    # Intent-rich phrasing is usually distillable.
    if 40 <= len(t) <= 6000:
        readiness += 0.30
    elif len(t) >= 20:
        readiness += 0.15

    action_verbs = (
        "use", "avoid", "prefer", "ensure", "check", "verify", "run", "add",
        "remove", "set", "enable", "disable", "configure", "fix", "update",
    )
    if any(v in lower for v in action_verbs):
        readiness += 0.2

    if re.search(r"\b(if|when|before|after|while|unless)\b", lower):
        readiness += 0.2

    if any(t in lower for t in ("because", "since", "due to", "so that", "resulted")):
        readiness += 0.15

    # Tool context helps map the memory; this makes it more likely to be reused.
    if tool_name:
        readiness += 0.15

    if source and source not in {"spark", "claude_code", "unknown", ""}:
        readiness += 0.05

    return max(0.0, min(1.0, round(readiness, 3)))


def _build_advisory_payload_hint(text: str, source: str, tool_name: str = "") -> Dict[str, Any]:
    """Build advisory metadata block attached to each captured event."""
    if not text:
        return {}

    hint_domain = "general"
    try:
        hint_domain = detect_domain(text) or "general"
    except Exception:
        hint_domain = "general"
    return {
        "readiness_hint": _estimate_advisory_readiness(text, source=source, tool_name=tool_name),
        "domain_hint": hint_domain,
        "content_len": len(text),
        "signal_domain": source,
    }


def _normalize_hook_payload_text(raw_text: str) -> Dict[str, Any]:
    """Normalize oversized hook payload text and preserve a stable fingerprint."""
    text = (raw_text or "").strip()
    text_len = len(text)
    if text_len <= HOOK_PAYLOAD_TEXT_LIMIT:
        return {
            "text": text,
            "content_len": text_len,
            "text_truncated": False,
            "text_hash": None,
        }
    digest = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()
    return {
        "text": text[:HOOK_PAYLOAD_TEXT_LIMIT],
        "content_len": text_len,
        "text_truncated": True,
        "text_hash": digest,
    }


def _sanitize_tool_input_for_capture(tool_input: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(tool_input, dict):
        return None

    sanitized: Dict[str, Any] = {}
    for key, value in tool_input.items():
        if isinstance(value, str):
            txt_meta = _normalize_hook_payload_text(value)
            if txt_meta["text_truncated"]:
                sanitized[key] = txt_meta["text"]
                sanitized[f"{key}_truncated"] = True
                sanitized[f"{key}_len"] = txt_meta["content_len"]
                sanitized[f"{key}_hash"] = txt_meta["text_hash"]
                continue
            sanitized[key] = value
            continue
        sanitized[key] = value

    return sanitized


def _make_trace_id(*parts: str) -> str:
    raw = "|".join(str(p or "") for p in parts).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def _resolve_post_trace_id(session_id: str, tool_name: str, trace_id: Optional[str]) -> Optional[str]:
    """Best-effort recovery for trace_id on post-tool hooks."""
    if trace_id:
        return trace_id
    if not tool_name:
        return trace_id
    try:
        from lib.advisory_state import load_state, resolve_recent_trace_id

        state = load_state(session_id)
        resolved = resolve_recent_trace_id(state, tool_name)
        return resolved or trace_id
    except Exception:
        return trace_id


def _normalize_source(raw_source: Any) -> str:
    """Normalize source metadata for reliable downstream schema grouping."""
    source = str(raw_source or "").strip().lower()
    if not source:
        return "claude_code"
    if source in {"unknown", "n/a", "none"}:
        return "claude_code"
    source = re.sub(r"[^a-z0-9._-]+", "-", source)
    source = source.strip("-._")
    if not source:
        return "claude_code"
    if source in {"spark", "spark-hook", "spark-hook-json"}:
        return "spark"
    if source in {"claudecode", "claude-code"}:
        return "claude_code"
    return source[:80]


# ===== Event Type Mapping =====

def get_event_type(hook_event_name: str) -> EventType:
    """Map hook event name to Spark event type."""
    mapping = {
        "SessionStart": EventType.SESSION_START,
        "UserPromptSubmit": EventType.USER_PROMPT,
        "PreToolUse": EventType.PRE_TOOL,
        "PostToolUse": EventType.POST_TOOL,
        "PostToolUseFailure": EventType.POST_TOOL_FAILURE,
        "Stop": EventType.STOP,
        "SessionEnd": EventType.SESSION_END,
    }
    return mapping.get(hook_event_name, EventType.POST_TOOL)


# ===== Learning Functions =====

def learn_from_failure(tool_name: str, error: str, tool_input: dict):
    """Extract learning from a failure event."""
    try:
        cognitive = get_cognitive_learner()
        error_lower = error.lower() if error else ""
        
        if "not found in file" in error_lower:
            cognitive.learn_assumption_failure(
                assumption="File content matches expectations",
                reality="Always Read before Edit to verify current content",
                context=f"Edit failed on {tool_input.get('file_path', 'unknown file')}"
            )
        elif "no such file" in error_lower or "not found" in error_lower:
            cognitive.learn_assumption_failure(
                assumption="File exists at expected path",
                reality="Use Glob to search for files before operating on them",
                context=f"{tool_name} failed: file not found"
            )
        elif "permission denied" in error_lower:
            cognitive.learn_blind_spot(
                what_i_missed="File permissions before operation",
                how_i_discovered=f"{tool_name} failed with permission denied"
            )
        
        cognitive.learn_struggle_area(
            task_type=f"{tool_name}_error",
            failure_reason=error[:200]
        )
    except Exception as e:
        log_debug("observe", "learn_from_failure failed", e)
        pass


def learn_from_success(tool_name: str, tool_input: dict, data: dict):
    """Extract learning from a success event."""
    try:
        cognitive = get_cognitive_learner()
        
        if tool_name == "Edit":
            if data.get("preceded_by_read"):
                cognitive.learn_why(
                    what_worked="Read then Edit sequence",
                    why_it_worked="Verifying content before editing prevents mismatch errors",
                    context="File editing workflow"
                )
    except Exception as e:
        log_debug("observe", "learn_from_success failed", e)
        pass


def check_for_surprise(session_id: str, tool_name: str, success: bool, error: str = None):
    """
    Check if outcome was surprising compared to prediction.
    
    This is where "aha moments" are born!
    """
    try:
        from lib.aha_tracker import get_aha_tracker, SurpriseType
        
        prediction = get_prediction(session_id, tool_name)
        if not prediction:
            return  # No prediction to compare
        
        predicted_success = prediction.get("outcome", "success") == "success"
        confidence = prediction.get("confidence", 0.5)
        
        tracker = get_aha_tracker()
        
        # Unexpected failure (thought it would succeed)
        if predicted_success and not success:
            confidence_gap = confidence  # High confidence + failure = high surprise
            if confidence_gap >= 0.5:
                tracker.capture_surprise(
                    surprise_type=SurpriseType.UNEXPECTED_FAILURE,
                    predicted=f"Success ({confidence:.0%} confident): {prediction.get('reason', '')}",
                    actual=f"Failed: {error[:100] if error else 'unknown error'}",
                    confidence_gap=confidence_gap,
                    context={
                        "tool": tool_name,
                        "prediction_reason": prediction.get("reason"),
                    },
                    lesson=f"Overestimated {tool_name} success likelihood" if confidence > 0.7 else None
                )
        
        # Unexpected success (thought it would fail)
        elif not predicted_success and success:
            confidence_gap = 1 - confidence  # Low confidence + success = high surprise
            if confidence_gap >= 0.5:
                tracker.capture_surprise(
                    surprise_type=SurpriseType.UNEXPECTED_SUCCESS,
                    predicted=f"Failure ({1-confidence:.0%} expected): {prediction.get('reason', '')}",
                    actual="Succeeded!",
                    confidence_gap=confidence_gap,
                    context={
                        "tool": tool_name,
                        "prediction_reason": prediction.get("reason"),
                    },
                    lesson=f"Underestimated {tool_name} - works better than expected" if confidence < 0.4 else None
                )
                
    except Exception as e:
        log_debug("observe", "check_for_surprise failed", e)
        pass


# ===== Main =====

def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        log_debug("observe", "input JSON decode failed", e)
        sys.exit(0)
    
    session_id = input_data.get("session_id", "unknown")
    source_hint = _normalize_source(input_data.get("source") or input_data.get("app"))
    hook_event = input_data.get("hook_event_name", "unknown")
    tool_name = input_data.get("tool_name")
    tool_input = input_data.get("tool_input", {})
    
    event_type = get_event_type(hook_event)
    trace_id = input_data.get("trace_id")
    
    # ===== PreToolUse: Make prediction + Advisory Engine + EIDOS step creation =====
    if event_type == EventType.PRE_TOOL and tool_name:
        pretool_start_ms = time.time() * 1000.0
        trace_id = _make_trace_id(session_id, tool_name, hook_event, time.time())
        prediction = make_prediction(tool_name, tool_input)

        # Advisory Engine: retrieve → gate → synthesize → emit to stdout
        # This replaces the old fire-and-forget advisor call.
        # The engine handles retrieval, filtering, synthesis, and emission.
        try:
            from lib.advisory_engine import on_pre_tool
            emitted_text = on_pre_tool(
                session_id=session_id,
                tool_name=tool_name,
                tool_input=tool_input,
                trace_id=trace_id,
            )
            if emitted_text:
                log_debug("observe", f"Advisory engine emitted for {tool_name}: {len(emitted_text)} chars", None)
                # Record advice for implicit outcome tracking
                try:
                    from lib.implicit_outcome_tracker import get_implicit_tracker
                    get_implicit_tracker().record_advice(
                        tool_name=tool_name,
                        advice_texts=[emitted_text[:500]],
                        tool_input=tool_input,
                    )
                except Exception:
                    pass
            elapsed_ms = (time.time() * 1000.0) - pretool_start_ms
            if elapsed_ms > PRETOOL_BUDGET_MS:
                log_debug("observe", f"OBS_PRETOOL_BUDGET_EXCEEDED:{tool_name}:{elapsed_ms:.1f}ms>{PRETOOL_BUDGET_MS:.0f}ms", None)
        except Exception as e:
            log_debug("observe", "advisory engine failed, considering legacy fallback", e)
            # Fallback: legacy advisor (fire-and-forget, no emission)
            # Fail-open: skip fallback if pretool budget is already exhausted.
            elapsed_ms = (time.time() * 1000.0) - pretool_start_ms
            if elapsed_ms > PRETOOL_BUDGET_MS:
                log_debug("observe", f"OBS_PRETOOL_SKIP_LEGACY_FALLBACK:{tool_name}:{elapsed_ms:.1f}ms", None)
            else:
                try:
                    from lib.advisor import advise_on_tool
                    advice = advise_on_tool(tool_name, tool_input, trace_id=trace_id)
                    if advice:
                        log_debug("observe", f"Legacy advisor: {len(advice)} items for {tool_name}", None)
                        if ADVICE_FEEDBACK_ENABLED:
                            try:
                                from lib.advice_feedback import record_advice_request
                                record_advice_request(
                                    session_id=session_id,
                                    tool=tool_name,
                                    advice_ids=[a.advice_id for a in advice],
                                    min_interval_s=ADVICE_FEEDBACK_MIN_S,
                                )
                            except Exception as feedback_err:
                                log_debug("observe", "OBS_LEGACY_FEEDBACK_RECORD_FAILED", feedback_err)
                except Exception as fallback_err:
                    log_debug("observe", "OBS_LEGACY_FALLBACK_FAILED", fallback_err)
        save_prediction(session_id, tool_name, prediction)

        # EIDOS: Create step and check control plane
        if EIDOS_AVAILABLE:
            try:
                step, decision = create_step_before_action(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    prediction=prediction,
                    trace_id=trace_id
                )
                if step and step.trace_id:
                    trace_id = step.trace_id

                # If EIDOS blocks the action, output blocking message
                if decision and not decision.allowed:
                    # Write to stderr so Claude Code sees it
                    sys.stderr.write(f"[EIDOS] BLOCKED: {decision.message}\n")
                    if decision.required_action:
                        sys.stderr.write(f"[EIDOS] Required: {decision.required_action}\n")
                    # Optional enforcement: if the host supports aborting tool execution on non-zero exit.
                    if EIDOS_ENFORCE_BLOCK:
                        sys.stderr.write("[EIDOS] Enforcement enabled (SPARK_EIDOS_ENFORCE_BLOCK=1). Exiting non-zero.\n")
                        raise SystemExit(2)
            except Exception as e:
                log_debug("observe", "EIDOS pre-action failed", e)
    
    # ===== PostToolUse: Check for surprise + Track outcome + Advisory feedback + EIDOS =====
    if event_type == EventType.POST_TOOL and tool_name:
        trace_id = _resolve_post_trace_id(session_id, tool_name, trace_id)
        check_for_surprise(session_id, tool_name, success=True)
        learn_from_success(tool_name, tool_input, {})

        # Implicit outcome tracking: record success
        try:
            from lib.implicit_outcome_tracker import get_implicit_tracker
            get_implicit_tracker().record_outcome(tool_name=tool_name, success=True, tool_input=tool_input)
        except Exception:
            pass

        # Advisory Engine: record outcome for implicit feedback loop
        try:
            from lib.advisory_engine import on_post_tool
            on_post_tool(
                session_id=session_id,
                tool_name=tool_name,
                success=True,
                tool_input=tool_input,
                trace_id=trace_id,
            )
        except Exception as e:
            log_debug("observe", "advisory engine post-tool failed", e)

        # EIDOS: Complete step with success
        if EIDOS_AVAILABLE:
            try:
                result = input_data.get("tool_result", "")
                if isinstance(result, dict):
                    result = json.dumps(result)[:500]
                elif result:
                    result = str(result)[:500]

                step = complete_step_after_action(
                    session_id=session_id,
                    tool_name=tool_name,
                    success=True,
                    result=result
                )
                if step and step.trace_id:
                    trace_id = step.trace_id
            except Exception as e:
                log_debug("observe", "EIDOS post-action failed", e)

        # Track outcome in Advisor (flows to Meta-Ralph)
        # Recovery detection: if this tool previously FAILED in this session
        # and now succeeds, the advice that was surfaced likely helped.
        # This is a high-confidence positive signal.
        try:
            from lib.advisor import report_outcome
            is_recovery = had_prior_failure(session_id, tool_name)
            if is_recovery:
                # Recovery pattern: fail -> advice surfaced -> succeed = advice helped
                report_outcome(tool_name, success=True, advice_helped=True, trace_id=trace_id)
                log_debug("observe", f"RECOVERY detected for {tool_name} - marking advice as helpful", None)
            else:
                # Normal success: don't auto-attribute to advice
                report_outcome(tool_name, success=True, advice_helped=False, trace_id=trace_id)
        except Exception as e:
            log_debug("observe", "outcome tracking failed", e)

        # Cognitive signal extraction from Write/Edit content moved to
        # bridge_cycle (background) to keep the hook fast.

        try:
            update_self_awareness_reliability(tool_name, success=True)
            query = tool_name
            if isinstance(tool_input, dict):
                for k in ("command", "path", "file_path", "filePath"):
                    v = tool_input.get(k)
                    if isinstance(v, str) and v:
                        query = f"{query} {v[:120]}"
                        break
            update_skill_effectiveness(query, success=True, limit=2)
        except Exception:
            pass
    
    # ===== PostToolUseFailure: Check for surprise + Track outcome + Advisory feedback + learn + EIDOS =====
    if event_type == EventType.POST_TOOL_FAILURE and tool_name:
        trace_id = _resolve_post_trace_id(session_id, tool_name, trace_id)
        # Advisory Engine: record failure outcome for implicit feedback
        try:
            from lib.advisory_engine import on_post_tool
            on_post_tool(
                session_id=session_id,
                tool_name=tool_name,
                success=False,
                tool_input=tool_input,
                trace_id=trace_id,
                error=str(input_data.get("tool_error") or input_data.get("error") or "")[:300],
            )
        except Exception as e:
            log_debug("observe", "advisory engine post-failure failed", e)

        error = (
            input_data.get("tool_error") or
            input_data.get("error") or
            input_data.get("tool_result") or
            ""
        )
        check_for_surprise(session_id, tool_name, success=False, error=str(error))
        learn_from_failure(tool_name, error, tool_input)

        # Implicit outcome tracking: record failure
        try:
            from lib.implicit_outcome_tracker import get_implicit_tracker
            get_implicit_tracker().record_outcome(
                tool_name=tool_name, success=False,
                tool_input=tool_input, error_text=str(error)[:200],
            )
        except Exception:
            pass

        # Record failure for recovery detection (used by PostToolUse handler)
        record_session_failure(session_id, tool_name)

        # Track failure outcome in Advisor (flows to Meta-Ralph).
        # When advice WAS surfaced for this tool and the tool STILL failed,
        # that's a genuine negative signal: the advice wasn't sufficient.
        try:
            from lib.advisor import report_outcome, get_advisor
            advisor = get_advisor()
            recent_advice = advisor._get_recent_advice_entry(
                tool_name,
                trace_id=trace_id,
                allow_task_fallback=False,
            )
            if recent_advice and recent_advice.get("advice_ids"):
                # Advice existed but tool still failed = advice was not helpful
                report_outcome(tool_name, success=False, advice_helped=False, trace_id=trace_id)
                # Also record explicit negative feedback for each advice item
                for aid in recent_advice.get("advice_ids", [])[:5]:
                    advisor.report_outcome(
                        aid,
                        was_followed=True,
                        was_helpful=False,
                        notes=f"Tool {tool_name} failed despite advice: {str(error)[:100]}",
                        trace_id=trace_id,
                    )
                log_debug("observe", f"NEGATIVE outcome: {tool_name} failed with advice present ({len(recent_advice.get('advice_ids', []))} items)", None)
            else:
                # No advice was given, just track the failure normally
                report_outcome(tool_name, success=False, advice_helped=False, trace_id=trace_id)
        except Exception as e:
            log_debug("observe", "failure outcome tracking failed", e)

        # EIDOS: Complete step with failure
        if EIDOS_AVAILABLE:
            try:
                step = complete_step_after_action(
                    session_id=session_id,
                    tool_name=tool_name,
                    success=False,
                    error=str(error)[:500] if error else ""
                )
                if step and step.trace_id:
                    trace_id = step.trace_id
            except Exception as e:
                log_debug("observe", "EIDOS post-failure failed", e)

        try:
            update_self_awareness_reliability(tool_name, success=False)
            query = tool_name
            if isinstance(tool_input, dict):
                for k in ("command", "path", "file_path", "filePath"):
                    v = tool_input.get(k)
                    if isinstance(v, str) and v:
                        query = f"{query} {v[:120]}"
                        break
            update_skill_effectiveness(query, success=False, limit=2)
        except Exception:
            pass
    
    # Queue the event
    data = {
        "hook_event": hook_event,
        "cwd": input_data.get("cwd"),
    }

    # If this is a user prompt submit, try to capture the prompt text in a
    # portable shape that downstream systems expect:
    #   data.payload = { role: "user", text: "..." }
    # This keeps Spark core platform-agnostic and makes memory capture work.
    if hook_event == "UserPromptSubmit":
        txt = (
            input_data.get("prompt") or
            input_data.get("user_prompt") or
            input_data.get("text") or
            input_data.get("message") or
            ""
        )
        if isinstance(txt, dict):
            txt = txt.get("text") or ""
        txt = str(txt).strip()
        if txt:
            txt_meta = _normalize_hook_payload_text(txt)
            trace_id = _make_trace_id(session_id, "user_prompt", txt, time.time())
            data["payload"] = {
                "role": "user",
                "text": txt_meta["text"],
                "text_len": txt_meta["content_len"],
            }
            if txt_meta["text_truncated"]:
                data["payload"]["text_hash"] = txt_meta["text_hash"]
                data["payload"]["text_truncated"] = True
            data["source"] = source_hint or "claude_code"
            data["kind"] = "message"
            data["advisory"] = _build_advisory_payload_hint(
                txt_meta["text"],
                source=data.get("source") or "claude_code",
            )
            data["advisory"]["content_len"] = txt_meta["content_len"]
            if txt_meta["text_truncated"]:
                data["advisory"]["content_hash"] = txt_meta["text_hash"]
                data["advisory"]["truncated"] = True

            # Advisory Engine: capture user intent for contextual retrieval
            try:
                from lib.advisory_engine import on_user_prompt
                on_user_prompt(session_id, txt, trace_id=trace_id)
            except Exception as e:
                log_debug("observe", "advisory engine intent capture failed", e)

            # EIDOS: Update episode goal from user prompt (first meaningful prompt)
            if EIDOS_AVAILABLE and len(txt) > 10:
                try:
                    from lib.eidos.integration import update_episode_goal
                    # Use first 200 chars of user prompt as goal
                    goal = txt[:200].replace("\n", " ").strip()
                    update_episode_goal(session_id, goal)
                except Exception as e:
                    log_debug("observe", "EIDOS goal update failed", e)

            # Cognitive signal extraction moved to bridge_cycle (background)
            # to keep the hook fast.
    
    if trace_id:
        data["trace_id"] = trace_id

    # Ensure source attribution on ALL events (not just UserPromptSubmit)
    tool_input_payload = _sanitize_tool_input_for_capture(tool_input)

    if "source" not in data:
        data["source"] = source_hint

    if "advisory" not in data and tool_name:
        tool_payload = None
        if isinstance(tool_input_payload, dict):
            for key in ("command", "path", "file_path", "pattern", "query", "text", "content"):
                value = tool_input.get(key) if isinstance(tool_input, dict) else None
                if isinstance(value, str) and value.strip():
                    tool_payload = value.strip()
                    break
        if tool_payload:
            tool_payload_meta = _normalize_hook_payload_text(tool_payload)
            data["advisory"] = _build_advisory_payload_hint(
                tool_payload,
                source=data.get("source") or "claude_code",
                tool_name=tool_name,
            )
            data["advisory"]["content_len"] = tool_payload_meta["content_len"]
            if tool_payload_meta["text_truncated"]:
                data["advisory"]["content_hash"] = tool_payload_meta["text_hash"]
                data["advisory"]["truncated"] = True

    kwargs = {}
    if tool_name:
        kwargs["tool_name"] = tool_name
        if tool_input_payload is not None:
            kwargs["tool_input"] = tool_input_payload
        else:
            kwargs["tool_input"] = tool_input
    if trace_id:
        kwargs["trace_id"] = trace_id
    
    if event_type == EventType.POST_TOOL_FAILURE:
        error = input_data.get("tool_error") or input_data.get("error") or ""
        if error:
            kwargs["error"] = str(error)[:500]
    
    quick_capture(event_type, session_id, data, **kwargs)

    # Pattern detection is handled by the background pipeline (lib/pipeline.py)
    # to keep the hook fast. Removed synchronous aggregator call.

    # Optional: emit a lightweight outcome check-in request at session end.
    if hook_event in ("Stop", "SessionEnd") and os.environ.get("SPARK_OUTCOME_CHECKIN") == "1":
        recorded = record_checkin_request(
            session_id=session_id,
            event=hook_event,
            reason="session_end",
            min_interval_s=CHECKIN_MIN_S,
        )
        if recorded and os.environ.get("SPARK_OUTCOME_CHECKIN_PROMPT") == "1":
            sys.stderr.write("[SPARK] Outcome check-in: run `spark outcome`\\n")

    # Optional: prompt for advice feedback at session end.
    if hook_event in ("Stop", "SessionEnd") and ADVICE_FEEDBACK_PROMPT:
        try:
            from lib.advice_feedback import has_recent_requests
            if has_recent_requests():
                sys.stderr.write("[SPARK] Advice feedback pending: run `spark advice-feedback --pending`\\n")
        except Exception:
            pass

    # EIDOS: Complete episode on session end (triggers distillation)
    # Let complete_episode infer the outcome from step data rather than
    # always claiming SUCCESS (which inflated success rates to 100%).
    if hook_event in ("Stop", "SessionEnd") and EIDOS_AVAILABLE:
        try:
            episode = complete_episode(session_id)
            if episode:
                log_debug("observe", f"EIDOS episode {episode.episode_id} completed as {episode.outcome.value}", None)
        except Exception as e:
            log_debug("observe", "EIDOS episode completion failed", e)

    # Auto-promote insights at session end (rate-limited to once per hour)
    if hook_event in ("Stop", "SessionEnd"):
        try:
            from lib.auto_promote import maybe_promote_on_session_end
            cwd = input_data.get("cwd")
            project_dir = Path(cwd) if cwd else None
            maybe_promote_on_session_end(project_dir=project_dir)
        except Exception as e:
            log_debug("observe", "auto-promotion failed", e)

    sys.exit(0)


if __name__ == "__main__":
    main()
