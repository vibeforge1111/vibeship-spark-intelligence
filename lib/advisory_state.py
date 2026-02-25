"""
Advisory State: Persistent session context for the advisory engine.

Each hook invocation is a fresh Python process. This module maintains
state across invocations via a lightweight JSON file per session.

Tracks:
- Recent tool calls (last N) for pattern detection
- User intent (extracted from last UserPromptSubmit)
- Task phase (exploration / planning / implementation / testing / debugging / deployment)
- Advice already shown (to avoid repetition)
- Active suppression rules
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .diagnostics import log_debug

# ============= Configuration =============
STATE_DIR = Path.home() / ".spark" / "advisory_state"
MAX_RECENT_TOOLS = 20
MAX_SHOWN_ADVICE = 100
STATE_TTL_SECONDS = 7200  # 2 hours - expire stale sessions
INTENT_MAX_LEN = 500
SHOWN_ADVICE_TTL_S = max(5, min(86400, int(os.getenv("SPARK_ADVISORY_SHOWN_TTL_S", "600") or 600)))

_COOLDOWN_SCALE_MIN = 0.1
_COOLDOWN_SCALE_MAX = 10.0


# ============= Task Phase Detection =============

class TaskPhase:
    EXPLORATION = "exploration"      # Reading files, searching, understanding
    PLANNING = "planning"            # Discussing approach, asking questions
    IMPLEMENTATION = "implementation" # Writing/editing code
    TESTING = "testing"              # Running tests, checking output
    DEBUGGING = "debugging"          # After failure, investigating
    DEPLOYMENT = "deployment"        # Git operations, pushing, releasing

# Tool → phase mapping (most likely phase when this tool is used)
TOOL_PHASE_SIGNALS = {
    "Read": TaskPhase.EXPLORATION,
    "Glob": TaskPhase.EXPLORATION,
    "Grep": TaskPhase.EXPLORATION,
    "WebFetch": TaskPhase.EXPLORATION,
    "WebSearch": TaskPhase.EXPLORATION,
    "Task": TaskPhase.EXPLORATION,
    "AskUserQuestion": TaskPhase.PLANNING,
    "EnterPlanMode": TaskPhase.PLANNING,
    "ExitPlanMode": TaskPhase.PLANNING,
    "Edit": TaskPhase.IMPLEMENTATION,
    "Write": TaskPhase.IMPLEMENTATION,
    "NotebookEdit": TaskPhase.IMPLEMENTATION,
}

# Bash command patterns → phase
BASH_PHASE_PATTERNS = [
    (r"(?:pytest|jest|mocha|npm test|python -m pytest|cargo test)", TaskPhase.TESTING),
    (r"(?:npm run build|cargo build|make|tsc|webpack)", TaskPhase.IMPLEMENTATION),
    (r"(?:git push|git merge|deploy|npm publish|docker push)", TaskPhase.DEPLOYMENT),
    (r"(?:git status|git diff|git log|git branch)", TaskPhase.EXPLORATION),
    (r"(?:git add|git commit)", TaskPhase.DEPLOYMENT),
    (r"(?:curl|wget|ping|netstat|ss )", TaskPhase.DEBUGGING),
    (r"(?:pip install|npm install|yarn add)", TaskPhase.IMPLEMENTATION),
]


@dataclass
class ToolCall:
    """Record of a single tool invocation."""
    tool_name: str
    timestamp: float
    success: Optional[bool] = None
    trace_id: Optional[str] = None
    input_hint: str = ""  # first 200 chars of key input

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ToolCall":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SessionState:
    """Full state for one advisory session."""
    session_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Recent tool calls
    recent_tools: List[dict] = field(default_factory=list)

    # User intent from last UserPromptSubmit
    user_intent: str = ""
    intent_updated_at: float = 0.0
    intent_family: str = "emergent_other"
    intent_confidence: float = 0.0
    task_plane: str = "build_delivery"
    intent_reason: str = ""

    # Inferred task phase
    task_phase: str = TaskPhase.EXPLORATION
    phase_confidence: float = 0.5
    phase_history: List[str] = field(default_factory=list)  # last 5 phases

    # Advice already emitted: advice_id → timestamp (TTL-based, re-eligible after cooldown)
    # Advice already emitted:
    # - raw ids for backwards compatibility
    # - context keys for focused repeat suppression (tool + phase)
    #   format: "{advice_id}|{tool}|{phase}" (TTL-based)
    shown_advice_ids: Dict[str, float] = field(default_factory=dict)
    last_advisory_packet_id: str = ""
    last_advisory_route: str = ""
    last_advisory_tool: str = ""
    last_advisory_advice_ids: List[str] = field(default_factory=list)
    last_advisory_at: float = 0.0
    last_advisory_text_fingerprint: str = ""
    last_advisory_context_fingerprint: str = ""

    # Consecutive failures (for debugging phase detection)
    consecutive_failures: int = 0
    last_failure_tool: str = ""

    # Suppression: tool_name → until_timestamp (legacy float) or structured dict.
    suppressed_tools: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        valid_keys = cls.__dataclass_fields__
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        # Backwards compat: old state files stored shown_advice_ids as a list.
        # Use time.time() so the TTL check in the gate treats them as "just shown"
        # (0.0 would fail the `shown_at > 0` guard and never suppress).
        raw_shown = filtered.get("shown_advice_ids")
        if isinstance(raw_shown, list):
            import time as _time
            filtered["shown_advice_ids"] = {str(aid): _time.time() for aid in raw_shown}
        raw_suppressed = filtered.get("suppressed_tools")
        if isinstance(raw_suppressed, dict):
            normalized: Dict[str, Any] = {}
            for tool_name, raw_entry in raw_suppressed.items():
                key = str(tool_name or "").strip()
                if not key:
                    continue
                if isinstance(raw_entry, dict):
                    try:
                        started_at = float(raw_entry.get("started_at", 0.0) or 0.0)
                    except Exception:
                        started_at = 0.0
                    try:
                        duration_s = float(raw_entry.get("duration_s", 0.0) or 0.0)
                    except Exception:
                        duration_s = 0.0
                    try:
                        until = float(raw_entry.get("until", 0.0) or 0.0)
                    except Exception:
                        until = 0.0
                    if until <= 0.0 and duration_s > 0.0 and started_at > 0.0:
                        until = started_at + duration_s
                    normalized[key] = {
                        "started_at": started_at,
                        "duration_s": duration_s,
                        "until": until,
                    }
                    continue
                try:
                    normalized[key] = float(raw_entry or 0.0)
                except Exception:
                    continue
            filtered["suppressed_tools"] = normalized
        return cls(**filtered)


# ============= State Persistence =============

def _state_path(session_id: str) -> Path:
    """Get file path for a session's state."""
    raw = str(session_id or "unknown")
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
    prefix = raw.replace("/", "_").replace("\\", "_")
    prefix = "".join(ch for ch in prefix if ch.isalnum() or ch in {"_", "-", "."})
    prefix = prefix[:32].strip("_- .") or "session"
    safe_id = f"{prefix}_{digest}"
    return STATE_DIR / f"{safe_id}.json"


def load_state(session_id: str) -> SessionState:
    """Load session state from disk, or create new."""
    path = _state_path(session_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            state = SessionState.from_dict(data)
            # Check TTL
            if time.time() - state.updated_at > STATE_TTL_SECONDS:
                log_debug("advisory_state", f"Session {session_id} expired, creating new", None)
                return SessionState(session_id=session_id)
            return state
        except Exception as e:
            log_debug("advisory_state", f"Failed to load state for {session_id}", e)
    return SessionState(session_id=session_id)


def save_state(state: SessionState) -> None:
    """Persist session state to disk."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        path = _state_path(state.session_id)
        state.updated_at = time.time()
        path.write_text(json.dumps(state.to_dict(), default=str), encoding="utf-8")
    except Exception as e:
        log_debug("advisory_state", "Failed to save state", e)


def cleanup_expired_states() -> int:
    """Remove expired session state files. Returns count removed."""
    removed = 0
    try:
        if not STATE_DIR.exists():
            return 0
        now = time.time()
        for path in STATE_DIR.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
                if now - mtime > STATE_TTL_SECONDS:
                    path.unlink()
                    removed += 1
            except Exception:
                pass
    except Exception:
        pass
    return removed


# ============= State Updates =============

def record_tool_call(
    state: SessionState,
    tool_name: str,
    tool_input: Optional[dict] = None,
    success: Optional[bool] = None,
    trace_id: Optional[str] = None,
) -> None:
    """Record a tool call and update phase inference."""
    # Extract input hint
    input_hint = ""
    if isinstance(tool_input, dict):
        for k in ("command", "file_path", "path", "pattern", "query", "url"):
            v = tool_input.get(k)
            if isinstance(v, str) and v:
                input_hint = v[:200]
                break

    call = ToolCall(
        tool_name=tool_name,
        timestamp=time.time(),
        success=success,
        trace_id=trace_id,
        input_hint=input_hint,
    )
    state.recent_tools.append(call.to_dict())

    # Keep bounded
    if len(state.recent_tools) > MAX_RECENT_TOOLS:
        state.recent_tools = state.recent_tools[-MAX_RECENT_TOOLS:]

    # Update failure tracking
    if success is False:
        state.consecutive_failures += 1
        state.last_failure_tool = tool_name
    elif success is True:
        state.consecutive_failures = 0

    # Update phase
    _update_phase(state, tool_name, tool_input, success)


def record_user_intent(state: SessionState, intent: str) -> None:
    """Update user intent from UserPromptSubmit."""
    if intent and len(intent.strip()) > 5:
        state.user_intent = intent.strip()[:INTENT_MAX_LEN]
        state.intent_updated_at = time.time()


def _clamp_shown_ttl(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = 600
    return max(5, min(86400, parsed))


def _clamp_cooldown_scale(value: Any) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = 1.0
    return max(_COOLDOWN_SCALE_MIN, min(_COOLDOWN_SCALE_MAX, parsed))


def apply_state_gate_config(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    """Apply advisory_gate tuneables consumed by advisory_state."""
    global SHOWN_ADVICE_TTL_S

    applied: List[str] = []
    warnings: List[str] = []
    if not isinstance(cfg, dict):
        return {"applied": applied, "warnings": warnings}

    # Backward-compat alias:
    # advice_repeat_cooldown_s maps to shown_advice_ttl_s when explicit TTL
    # tuneable is absent.
    ttl_raw = None
    ttl_applied_key = ""
    if "shown_advice_ttl_s" in cfg:
        ttl_raw = cfg.get("shown_advice_ttl_s")
        ttl_applied_key = "shown_advice_ttl_s"
    elif "advice_repeat_cooldown_s" in cfg:
        ttl_raw = cfg.get("advice_repeat_cooldown_s")
        ttl_applied_key = "shown_advice_ttl_s"

    if ttl_raw is not None:
        try:
            SHOWN_ADVICE_TTL_S = _clamp_shown_ttl(ttl_raw)
            applied.append(ttl_applied_key)
        except Exception:
            warnings.append("invalid_shown_advice_ttl_s")

    return {"applied": applied, "warnings": warnings}


def get_shown_advice_ttl_s() -> int:
    return int(SHOWN_ADVICE_TTL_S)


def _load_state_gate_config(path: Optional[Path] = None) -> Dict[str, Any]:
    from .config_authority import resolve_section
    tuneables = path or (Path.home() / ".spark" / "tuneables.json")
    cfg = resolve_section("advisory_gate", runtime_path=tuneables).data
    return cfg if isinstance(cfg, dict) else {}


_BOOT_STATE_GATE_CFG = _load_state_gate_config()
if _BOOT_STATE_GATE_CFG:
    apply_state_gate_config(_BOOT_STATE_GATE_CFG)

try:
    from .tuneables_reload import register_reload as _state_register

    _state_register(
        "advisory_gate",
        apply_state_gate_config,
        label="advisory_state.apply_gate_config",
    )
except ImportError:
    pass


def _advice_shown_key(advice_id: str, *, tool_name: str = "", task_phase: str = "") -> str:
    aid = str(advice_id or "").strip()
    if not aid:
        return ""
    tool = str(tool_name or "").strip().lower() or "*"
    phase = str(task_phase or "").strip().lower() or "*"
    return f"{aid}|{tool}|{phase}"


def mark_advice_shown(
    state: SessionState,
    advice_ids: List[str],
    *,
    tool_name: str = "",
    task_phase: str = "",
) -> None:
    """Record that advice was emitted to Claude (with timestamp for TTL)."""
    if not state:
        return
    now = time.time()
    for aid in advice_ids:
        aid = str(aid or "").strip()
        if not aid:
            continue
        # Preserve backward compatibility for historical state readers.
        state.shown_advice_ids[aid] = now
        state.shown_advice_ids[_advice_shown_key(aid, tool_name=tool_name, task_phase=task_phase)] = now

    # Evict expired entries to keep bounded
    if len(state.shown_advice_ids) > MAX_SHOWN_ADVICE:
        cutoff = now - SHOWN_ADVICE_TTL_S
        state.shown_advice_ids = {
            k: v for k, v in state.shown_advice_ids.items() if v > cutoff
        }
        # If still too large after TTL eviction, keep most recent
        if len(state.shown_advice_ids) > MAX_SHOWN_ADVICE:
            sorted_items = sorted(state.shown_advice_ids.items(), key=lambda x: x[1])
            state.shown_advice_ids = dict(sorted_items[-MAX_SHOWN_ADVICE:])


def suppress_tool_advice(state: SessionState, tool_name: str, duration_s: float = 300) -> None:
    """Suppress advisory for a specific tool for duration_s seconds."""
    now = time.time()
    duration = max(0.0, float(duration_s or 0.0))
    state.suppressed_tools[tool_name] = {
        "started_at": now,
        "duration_s": duration,
        "until": now + duration,
    }


def is_tool_suppressed(state: SessionState, tool_name: str, *, cooldown_scale: float = 1.0) -> bool:
    """Check if advisory is suppressed for this tool."""
    if not state:
        return False

    now = time.time()
    entry = state.suppressed_tools.get(tool_name)
    if entry is None:
        return False

    if isinstance(entry, dict):
        try:
            started_at = float(entry.get("started_at", 0.0) or 0.0)
        except Exception:
            started_at = 0.0
        try:
            duration_s = float(entry.get("duration_s", 0.0) or 0.0)
        except Exception:
            duration_s = 0.0
        try:
            until = float(entry.get("until", 0.0) or 0.0)
        except Exception:
            until = 0.0

        if started_at <= 0.0:
            started_at = max(0.0, until - max(duration_s, 0.0))
        if duration_s <= 0.0 and until > started_at:
            duration_s = max(0.0, until - started_at)

        if duration_s > 0.0 and started_at > 0.0:
            scale = _clamp_cooldown_scale(cooldown_scale)
            effective_until = started_at + (duration_s * scale)
            if now < effective_until:
                return True
            # Keep entry until max scaled window ends so higher-scale categories
            # can still honor cooldown for the same tool.
            max_until = started_at + (duration_s * _COOLDOWN_SCALE_MAX)
            if now >= max_until:
                state.suppressed_tools.pop(tool_name, None)
            return False

        if now < until:
            return True
        state.suppressed_tools.pop(tool_name, None)
        return False

    try:
        until = float(entry or 0.0)
    except Exception:
        until = 0.0
    if now < until:
        return True
    # Expired - clean up legacy format.
    state.suppressed_tools.pop(tool_name, None)
    return False


# ============= Phase Inference =============

def _update_phase(
    state: SessionState,
    tool_name: str,
    tool_input: Optional[dict],
    success: Optional[bool],
) -> None:
    """Infer the current task phase from tool usage patterns."""
    import re

    new_phase = None
    confidence = 0.5

    # Debugging override: consecutive failures = debugging
    if state.consecutive_failures >= 2:
        new_phase = TaskPhase.DEBUGGING
        confidence = 0.9
    elif tool_name == "Bash" and isinstance(tool_input, dict):
        cmd = str(tool_input.get("command", ""))
        for pattern, phase in BASH_PHASE_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                new_phase = phase
                confidence = 0.7
                break
    elif tool_name in TOOL_PHASE_SIGNALS:
        new_phase = TOOL_PHASE_SIGNALS[tool_name]
        confidence = 0.6

    if new_phase:
        state.task_phase = new_phase
        state.phase_confidence = confidence
        state.phase_history.append(new_phase)
        if len(state.phase_history) > 5:
            state.phase_history = state.phase_history[-5:]


def get_phase_context(state: SessionState) -> str:
    """Get a human-readable description of current task phase."""
    phase_labels = {
        TaskPhase.EXPLORATION: "exploring the codebase",
        TaskPhase.PLANNING: "planning the approach",
        TaskPhase.IMPLEMENTATION: "writing code",
        TaskPhase.TESTING: "running tests",
        TaskPhase.DEBUGGING: "debugging an issue",
        TaskPhase.DEPLOYMENT: "preparing deployment",
    }
    label = phase_labels.get(state.task_phase, state.task_phase)
    if state.user_intent:
        return f"{label} — intent: {state.user_intent[:100]}"
    return label


def get_recent_tool_sequence(state: SessionState, n: int = 5) -> List[str]:
    """Get the last N tool names for pattern matching."""
    return [t["tool_name"] for t in state.recent_tools[-n:]]


def resolve_recent_trace_id(
    state: SessionState,
    tool_name: str,
    *,
    max_age_s: float = 300.0,
) -> Optional[str]:
    """Resolve the most likely trace_id for a post-tool outcome event.

    Prefer unresolved PreTool entries (success is None) for the same tool,
    then fall back to the latest trace-bearing row for that tool.
    """
    tool_lower = (tool_name or "").strip().lower()
    if not tool_lower:
        return None

    now = time.time()
    fallback: Optional[str] = None

    for row in reversed(state.recent_tools):
        if not isinstance(row, dict):
            continue
        row_tool = str(row.get("tool_name") or "").strip().lower()
        if row_tool != tool_lower:
            continue

        try:
            ts = float(row.get("timestamp") or 0.0)
        except Exception:
            ts = 0.0
        if max_age_s > 0 and ts > 0 and (now - ts) > max_age_s:
            break

        trace_id = str(row.get("trace_id") or "").strip()
        if not trace_id:
            continue

        success = row.get("success")
        if success is None:
            return trace_id
        if fallback is None:
            fallback = trace_id

    return fallback


def had_recent_read(state: SessionState, file_path: str, within_s: float = 60) -> bool:
    """Check if a file was recently Read (useful for suppressing 'Read before Edit' advice)."""
    now = time.time()
    for t in reversed(state.recent_tools):
        if now - t.get("timestamp", 0) > within_s:
            break
        if t.get("tool_name") == "Read" and file_path in t.get("input_hint", ""):
            return True
    return False
