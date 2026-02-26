"""
Spark Cognitive Learner: Learning to THINK, not just to DO.

This module captures higher-level insights that make any LLM more intelligent:
- How to think, not just what to do
- Why things work, not just that they work
- When to apply knowledge, not just what knowledge exists

Learning Categories:
1. SELF-AWARENESS - When am I overconfident? What are my blind spots?
2. USER_UNDERSTANDING - Communication preferences, expertise, working style
3. REASONING - Why did an approach work, not just that it worked
4. CONTEXT - When does a pattern apply vs not apply?
5. WISDOM - General principles that transcend specific tools
6. META_LEARNING - How do I learn best? When should I ask vs act?
7. COMMUNICATION - What explanations work well?
8. CREATIVITY - Novel problem-solving approaches
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

INSIGHT_CONTEXT_CHARS = 320
INSIGHT_EVIDENCE_CHARS = 280
_EVIDENCE_DROP_LINE_RE = re.compile(
    r"^\s*(evidence|event_type|tool_name|file_path|cwd|mission|mission id|provider|model|role|"
    r"task id|task name|source|progress|verification)\s*[:=]",
    re.I,
)
_EVIDENCE_SIGNAL_RE = re.compile(
    r"\b(because|so that|therefore|hence|decision|prefer|must|should|avoid|fix|"
    r"quality|confidence|threshold|risk|trade-?off|impact)\b",
    re.I,
)


def _normalize_signal(signal: str) -> str:
    """Normalize signal string for deduplication.

    Strips variable data like counts, numbers, specific values.
    'Heavy Bash usage (42 calls)' -> 'Heavy Bash usage'
    'Heavy Read usage (5 calls)' -> 'Heavy Read usage'
    """
    s = (signal or "").strip()
    # Remove parenthetical counts like "(42 calls)", "(5 calls)"
    s = re.sub(r'\s*\(\d+\s*calls?\)', '', s)
    # Remove trailing numbers
    s = re.sub(r'\s+\d+$', '', s)
    # Remove any remaining parenthetical numbers
    s = re.sub(r'\s*\(\d+\)', '', s)
    return s.strip()


def _normalize_struggle_text(text: str) -> str:
    """Normalize struggle insight text, collapsing recovered variants."""
    t = (text or "").strip()
    t = re.sub(r"\(\s*recovered\s*\d+%?\s*\)", "(recovered)", t, flags=re.IGNORECASE)
    t = re.sub(r"\brecovered\s*\d+%?\b", "recovered", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _normalize_struggle_key(text: str) -> str:
    """Normalize struggle text for stable keys."""
    return _normalize_struggle_text(text).lower()


def _is_low_signal_struggle_task(task: str) -> bool:
    """Detect telemetry-heavy struggle labels that should not auto-validate aggressively."""
    t = (task or "").strip().lower()
    if not t:
        return False
    noisy_tokens = (
        "_error",
        "mcp__",
        "command_not_found",
        "permission_denied",
        "file_not_found",
        "timeout",
        "syntax_error",
        "fails with",
    )
    return any(token in t for token in noisy_tokens)


def _is_injection_or_garbage(text: str) -> bool:
    """Detect prompt injection attempts and garbled/truncated content."""
    t = (text or "").strip().lower()
    if not t:
        return True
    # Quality test injection pattern
    if "quality_test" in t:
        return True
    # Instruction injection ("remember this because it is critical")
    if "remember this because" in t and ("avoid x" in t or "prefer z" in t):
        return True
    # HTTP error codes masquerading as wisdom
    if len(t) < 30 and any(t.startswith(code) for code in ("429 ", "403 ", "500 ", "404 ")):
        return True
    # Truncated mid-word (ends with incomplete token)
    import re
    alpha_only = re.sub(r'[^a-zA-Z]', '', t)
    if len(alpha_only) < 8:
        return True
    return False


def _is_auto_evidence_line(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    return (
        t.startswith("auto-linked from ")
        or t.startswith("tool=")
        or " success=true" in t
        or " success=false" in t
    )


def _validation_quality_weight(
    category: "CognitiveCategory",
    insight_text: str,
    evidence: List[str],
) -> float:
    """
    Discount reliability for telemetry/test-like insights so auto-counted events
    do not look equivalent to outcome-backed human-useful validation.
    """
    text = (insight_text or "").strip().lower()
    weight = 1.0

    if text.startswith("test:"):
        weight *= 0.05

    if len(text) > 400:
        weight *= 0.2

    if category == CognitiveCategory.SELF_AWARENESS and "i struggle with" in text:
        if _is_low_signal_struggle_task(text):
            weight *= 0.15

    ev = [str(e or "").strip() for e in (evidence or []) if str(e or "").strip()]
    if ev:
        auto_count = sum(1 for e in ev if _is_auto_evidence_line(e))
        auto_ratio = auto_count / max(len(ev), 1)
        if auto_ratio >= 0.5:
            weight *= 0.25

    return max(0.05, min(1.0, float(weight)))


def _compute_advisory_readiness(
    text: str,
    advisory_quality: Dict[str, Any],
    confidence: float = 0.5,
    times_validated: int = 0,
    times_contradicted: int = 0,
) -> float:
    """Score how ready an insight is for advisory reuse.

    This combines advisory quality (primary signal) with reliability and usage history.
    """
    quality = 0.0
    if isinstance(advisory_quality, dict):
        quality = float(advisory_quality.get("unified_score", 0.0) or 0.0)
    base = max(0.0, min(1.0, float(confidence)))
    readiness = max(0.0, 0.10 + 0.45 * quality + 0.20 * base)
    if times_validated:
        readiness += min(0.20, 0.05 * min(times_validated, 4))
    if times_contradicted:
        readiness -= min(0.20, 0.05 * min(times_contradicted, 4))
    if isinstance(text, str) and len(text.strip()) > 120:
        readiness += 0.10
    if isinstance(text, str) and len(text.strip()) < 40:
        readiness -= 0.08
    return max(0.0, min(1.0, readiness))


def _clip_context(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(t) > INSIGHT_CONTEXT_CHARS:
        t = t[:INSIGHT_CONTEXT_CHARS].rstrip()
    return t


def _clip_evidence(text: str) -> str:
    raw = str(text or "")
    lines = []
    for part in raw.splitlines():
        line = part.strip()
        if not line:
            continue
        if _EVIDENCE_DROP_LINE_RE.search(line):
            continue
        if line.startswith("<") and line.endswith(">"):
            continue
        lines.append(line)
    t = re.sub(r"\s+", " ", " ".join(lines)).strip()
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\s*[;|]\s+", t) if p.strip()]
    if parts:
        scored = []
        for idx, part in enumerate(parts):
            score = 0.0
            if _EVIDENCE_SIGNAL_RE.search(part):
                score += 1.2
            if re.search(r"\b\d+(\.\d+)?%?\b", part):
                score += 0.4
            if 24 <= len(part) <= 200:
                score += 0.2
            scored.append((score, idx, part))
        top = sorted(scored, key=lambda item: (item[0], -item[1]), reverse=True)[: min(3, len(scored))]
        top_idx = {idx for _, idx, _ in top}
        t = " ".join(part for idx, part in enumerate(parts) if idx in top_idx)
        t = re.sub(r"\s+", " ", t).strip()
    if len(t) > INSIGHT_EVIDENCE_CHARS:
        t = t[:INSIGHT_EVIDENCE_CHARS].rstrip()
    return t


def _backfill_actionable_context(
    context: str,
    insight: str,
    advisory_quality: Dict[str, Any],
) -> str:
    """Backfill short contexts with actionable structure for future retrieval."""
    base = _clip_context(context)
    parts: List[str] = []
    if base:
        parts.append(base)

    structure = advisory_quality.get("structure") if isinstance(advisory_quality, dict) else {}
    if isinstance(structure, dict):
        condition = str(structure.get("condition") or "").strip()
        action = str(structure.get("action") or "").strip()
        reasoning = str(structure.get("reasoning") or "").strip()
        outcome = str(structure.get("outcome") or "").strip()

        if action:
            if condition:
                parts.append(f"When {condition}")
            parts.append(f"Action: {action}")
            if reasoning:
                parts.append(f"Reason: {reasoning}")
            elif outcome:
                parts.append(f"Outcome: {outcome}")

    merged = " | ".join([p for p in parts if p]).strip(" |")
    if merged and len(merged) >= 80:
        return _clip_context(merged)

    if merged:
        seed = merged
    else:
        seed = re.sub(r"\s+", " ", str(insight or "")).strip()
    if not seed:
        return base

    # Fallback: keep a semantic sentence window from the insight itself.
    segments = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\s*[;|]\s+", seed) if s.strip()]
    if segments:
        seed = " ".join(segments[:3])
    return _clip_context(seed)


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _capture_emotion_state_snapshot() -> Dict[str, Any]:
    try:
        from lib.config_authority import env_bool, resolve_section
        cfg = resolve_section(
            "feature_gates",
            env_overrides={"cognitive_emotion_capture": env_bool("SPARK_COGNITIVE_EMOTION_CAPTURE")},
        ).data
        if not cfg.get("cognitive_emotion_capture", True):
            return {}
    except Exception:
        env = os.environ.get("SPARK_COGNITIVE_EMOTION_CAPTURE")
        if env is not None and str(env).strip().lower() in {"0", "false", "off", "no"}:
            return {}
    try:
        from lib.spark_emotions import SparkEmotions

        state = (SparkEmotions().status() or {}).get("state") or {}
        if not isinstance(state, dict):
            return {}
        return {
            "primary_emotion": str(state.get("primary_emotion") or "steady"),
            "mode": str(state.get("mode") or "real_talk"),
            "warmth": float(state.get("warmth", 0.0) or 0.0),
            "energy": float(state.get("energy", 0.0) or 0.0),
            "confidence": float(state.get("confidence", 0.0) or 0.0),
            "calm": float(state.get("calm", 0.0) or 0.0),
            "playfulness": float(state.get("playfulness", 0.0) or 0.0),
            "strain": float(state.get("strain", 0.0) or 0.0),
            "captured_at": time.time(),
        }
    except Exception:
        return {}


def _boost_confidence(current: float, validated: int) -> float:
    """Boost confidence based on validation count.

    Each validation increases confidence toward 1.0:
    - Start: 0.6
    - 1 validation: 0.7
    - 2 validations: 0.78
    - 3 validations: 0.85
    - 5+ validations: approaches 1.0

    Uses diminishing returns formula: conf + (1 - conf) * 0.25
    """
    # Base boost per validation
    boost_factor = 0.25
    new_conf = current
    for _ in range(min(validated, 10)):  # Cap at 10 boosts
        new_conf = new_conf + (1.0 - new_conf) * boost_factor
    return min(0.99, new_conf)  # Cap at 99%


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now().isoformat()


def _merge_unique(base: List[str], extra: List[str], limit: int = 10) -> List[str]:
    """Merge two lists, preserving order and uniqueness, capped to limit."""
    out: List[str] = []
    for item in (base or []):
        if item and item not in out:
            out.append(item)
    for item in (extra or []):
        if item and item not in out:
            out.append(item)
    return out[-limit:]


def _flatten_evidence(items: List[Any]) -> List[str]:
    """Flatten evidence items into a list of strings."""
    out: List[str] = []
    for item in items or []:
        if isinstance(item, list):
            for sub in item:
                if sub:
                    out.append(str(sub))
        elif item:
            out.append(str(item))
    return out


class _insights_lock:  # noqa: N801
    """Best-effort lock using an exclusive lock file."""

    def __init__(self, lock_file: Path, timeout_s: float = 0.5, stale_s: float = 60.0):
        self.lock_file = lock_file
        self.timeout_s = timeout_s
        self.stale_s = stale_s
        self.fd = None
        self.acquired = False

    def __enter__(self):
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        start = time.time()
        while True:
            try:
                self.fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                # Best-effort metadata to help diagnose stale locks.
                try:
                    os.write(self.fd, f"pid={os.getpid()} ts={time.time():.3f}\n".encode("utf-8", errors="ignore"))
                except Exception:
                    pass
                self.acquired = True
                return self
            except FileExistsError:
                # If a prior writer crashed, the lock file can be left behind forever.
                # Treat very old locks as stale and clear them.
                try:
                    age_s = time.time() - float(self.lock_file.stat().st_mtime or 0.0)
                    if age_s >= float(self.stale_s):
                        try:
                            self.lock_file.unlink()
                            continue
                        except Exception:
                            pass
                except Exception:
                    pass
                if time.time() - start >= self.timeout_s:
                    return self
                time.sleep(0.01)
            except Exception:
                return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            if self.acquired and self.lock_file.exists():
                self.lock_file.unlink()
        except Exception:
            pass
        self.acquired = False


class CognitiveCategory(Enum):
    """Categories of cognitive learning."""
    SELF_AWARENESS = "self_awareness"
    USER_UNDERSTANDING = "user_understanding"
    REASONING = "reasoning"
    CONTEXT = "context"
    WISDOM = "wisdom"
    META_LEARNING = "meta_learning"
    COMMUNICATION = "communication"
    CREATIVITY = "creativity"


@dataclass
class CognitiveInsight:
    """A higher-level insight, not just an operational pattern."""
    category: CognitiveCategory
    insight: str
    evidence: List[str]
    confidence: float
    context: str
    counter_examples: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    times_validated: int = 0
    times_contradicted: int = 0
    promoted: bool = False
    promoted_to: Optional[str] = None
    last_validated_at: Optional[str] = None
    source: str = ""  # adapter that captured this: "openclaw", "cursor", "windsurf", "claude", "depth_forge", etc.
    action_domain: str = ""  # pre-retrieval filter domain: "code", "depth_training", "user_context", "system", "general"
    emotion_state: Dict[str, Any] = field(default_factory=dict)
    advisory_quality: Dict[str, Any] = field(default_factory=dict)  # Embedded quality dimensions from distillation_transformer
    advisory_readiness: float = 0.0

    @property
    def reliability(self) -> float:
        """How reliable is this insight based on validation history?"""
        weight = _validation_quality_weight(self.category, self.insight, self.evidence)
        weighted_validated = float(self.times_validated) * weight
        total = weighted_validated + float(self.times_contradicted)
        if total == 0:
            return max(0.05, min(0.99, float(self.confidence) * weight))
        return weighted_validated / total

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "category": self.category.value,
            "insight": self.insight,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "context": self.context,
            "counter_examples": self.counter_examples,
            "created_at": self.created_at,
            "times_validated": self.times_validated,
            "times_contradicted": self.times_contradicted,
            "promoted": self.promoted,
            "promoted_to": self.promoted_to,
            "last_validated_at": self.last_validated_at,
            "source": self.source,
            "action_domain": self.action_domain,
            "emotion_state": self.emotion_state or {},
            "advisory_quality": self.advisory_quality or {},
            "advisory_readiness": round(self.advisory_readiness, 4),
            "reliability": round(self.reliability, 4),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveInsight":
        """Create from dictionary."""
        times_validated = _coerce_int(data.get("times_validated"), 0)
        times_contradicted = _coerce_int(data.get("times_contradicted"), 0)
        confidence = data.get("confidence")
        if confidence is None:
            # Backfill missing confidence with any legacy reliability or a safe default.
            confidence = float(data.get("reliability") or 0.5)
        return cls(
            category=CognitiveCategory(data["category"]),
            insight=data["insight"],
            evidence=data["evidence"],
            confidence=confidence,
            context=data["context"],
            counter_examples=data.get("counter_examples", []),
            created_at=data.get("created_at", datetime.now().isoformat()),
            times_validated=times_validated,
            times_contradicted=times_contradicted,
            promoted=data.get("promoted", False),
            promoted_to=data.get("promoted_to"),
            last_validated_at=data.get("last_validated_at"),
            source=data.get("source", ""),
            action_domain=data.get("action_domain", ""),
            emotion_state=data.get("emotion_state", {}) if isinstance(data.get("emotion_state"), dict) else {},
            advisory_quality=data.get("advisory_quality", {}) if isinstance(data.get("advisory_quality"), dict) else {},
            advisory_readiness=float(data.get("advisory_readiness", 0.0) or 0.0),
        )


def classify_action_domain(insight_text: str, category: str = "", source: str = "") -> str:
    """Classify an insight into an action domain for pre-retrieval filtering.

    Domains:
        depth_training  - DEPTH training logs and reasoning exercises
        user_context    - Verbatim user quotes and preferences
        code            - Code patterns, tool advice, engineering
        system          - Spark system internals, pipeline, config
        general         - Everything else (always included in retrieval)
    """
    text = str(insight_text or "").strip()
    text_lower = text.lower()
    src = str(source or "").lower()
    cat = str(category or "").lower()

    def _premium_tools_enabled() -> bool:
        try:
            from .feature_flags import PREMIUM_TOOLS
            return PREMIUM_TOOLS
        except ImportError:
            return False

    # No dedicated social/X/Twitter advisory domain in OSS launch.

    # DEPTH training domain
    if text.startswith("[DEPTH:") or "Strong " in text and " reasoning:" in text:
        return "depth_training"
    if any(tag in src for tag in ("depth", "depth_forge")):
        return "depth_training"
    if re.search(r"Strong Socratic depth on", text):
        return "depth_training"

    # User context (verbatim quotes)
    if cat == "user_understanding":
        # Check for verbatim user quotes (starts with lowercase, contains conversational patterns)
        if re.match(r"^(User prefers |Now, can we|Can you now|lets make sure|by the way|instead of this|I think we)", text):
            return "user_context"
        if re.match(r"^I'd say|^I don't think|^can we now|^please remember", text, re.IGNORECASE):
            return "user_context"

    # Code domain — look for code patterns
    if cat in ("self_awareness", "reasoning"):
        if re.search(r"(def |class |import |from \w+ import|self\.\w+|\.py\b)", text):
            return "code"
    if "Always Read a file before Edit" in text:
        return "code"
    if re.search(r"\b(function|method|variable|parameter|argument|return|exception|error handling)\b", text_lower):
        return "code"

    # System domain — Spark internals
    if any(kw in text_lower for kw in ("tuneables", "meta-ralph", "metaralph", "bridge_cycle", "pipeline", "cognitive_learner")):
        return "system"
    if re.search(r"\b(auto-tuner|bridge_worker|sparkd|spark daemon|queue\.py)\b", text_lower):
        return "system"

    return "general"


class CognitiveLearner:
    """
    Learns higher-level cognitive patterns, not just operational ones.

    The goal: Make the LLM more intelligent over time by learning:
    - How to think, not just what to do
    - Why things work, not just that they work
    - When to apply knowledge, not just what knowledge exists
    """

    INSIGHTS_FILE = Path.home() / ".spark" / "cognitive_insights.json"
    LOCK_FILE = Path.home() / ".spark" / ".cognitive.lock"

    def __init__(self):
        self.insights: Dict[str, CognitiveInsight] = {}
        self._dirty = False  # Track unsaved changes
        self._defer_saves = False  # When True, accumulate changes without I/O
        self._load_insights()

    def _load_insights(self):
        """Load existing cognitive insights."""
        if self.INSIGHTS_FILE.exists():
            try:
                data = json.loads(self.INSIGHTS_FILE.read_text(encoding="utf-8"))
                for key, info in data.items():
                    self.insights[key] = CognitiveInsight.from_dict(info)
                # Consolidate duplicate struggle variants (e.g., recovered X%).
                self.dedupe_struggles()
                # Backfill action_domain for insights loaded without one
                self._backfill_action_domains()
                # Ensure advisory_readiness exists for legacy insights.
                self._backfill_advisory_readiness()
            except Exception as e:
                print(f"[SPARK] Error loading insights: {e}")

    def _backfill_action_domains(self):
        """Backfill action_domain for insights that don't have one."""
        changed = False
        for key, insight in self.insights.items():
            if not insight.action_domain:
                domain = classify_action_domain(
                    insight.insight,
                    category=insight.category.value if hasattr(insight.category, "value") else str(insight.category),
                    source=insight.source,
                )
                insight.action_domain = domain
                changed = True
        if changed and not getattr(self, "_defer_saves", False):
            self._save_insights()

    def _backfill_advisory_readiness(self) -> None:
        """Backfill advisory_readiness for existing insights when missing."""
        changed = False
        for key, insight in self.insights.items():
            if insight.advisory_readiness <= 0.0:
                insight.advisory_readiness = _compute_advisory_readiness(
                    insight.insight,
                    getattr(insight, "advisory_quality", None) or {},
                    confidence=getattr(insight, "confidence", 0.5) or 0.5,
                    times_validated=getattr(insight, "times_validated", 0),
                    times_contradicted=getattr(insight, "times_contradicted", 0),
                )
                changed = True
        if changed and not getattr(self, "_defer_saves", False):
            self._save_insights()

    def _merge_insight(self, current: CognitiveInsight, disk: CognitiveInsight) -> CognitiveInsight:
        """Merge two insights, preserving the most reliable/complete data."""
        if not current.insight and disk.insight:
            current.insight = disk.insight
        if not current.context and disk.context:
            current.context = disk.context
        if not current.category:
            current.category = disk.category

        current.evidence = _merge_unique(disk.evidence, current.evidence, limit=10)
        current.counter_examples = _merge_unique(disk.counter_examples, current.counter_examples, limit=10)

        current.confidence = max(current.confidence, disk.confidence)
        # Use max instead of sum to avoid double-counting from the same process,
        # but if disk has more, take disk's value (concurrent processes accumulate)
        current.times_validated = max(current.times_validated, disk.times_validated)
        current.times_contradicted = max(current.times_contradicted, disk.times_contradicted)

        dv = _parse_iso(disk.last_validated_at)
        cv = _parse_iso(current.last_validated_at)
        if dv and (not cv or dv > cv):
            current.last_validated_at = disk.last_validated_at

        dc = _parse_iso(disk.created_at)
        cc = _parse_iso(current.created_at)
        if dc and (not cc or dc < cc):
            current.created_at = disk.created_at

        current.promoted = bool(current.promoted or disk.promoted)
        if not current.promoted_to and disk.promoted_to:
            current.promoted_to = disk.promoted_to

        return current

    def begin_batch(self):
        """Start a batch operation - defer all saves until flush()."""
        self._defer_saves = True

    def end_batch(self):
        """End batch operation and flush if dirty."""
        self._defer_saves = False
        if self._dirty:
            self._save_insights_now()

    def flush(self):
        """Flush any pending changes to disk."""
        if self._dirty:
            self._save_insights_now()

    def _save_insights(self, drop_keys: Optional[set] = None):
        """Save cognitive insights to disk (deferred if in batch mode)."""
        if drop_keys:
            # drop_keys forces an immediate save (used by purge/dedupe)
            self._save_insights_now(drop_keys=drop_keys)
            return
        if self._defer_saves:
            self._dirty = True
            return
        self._save_insights_now()

    def _save_insights_now(self, drop_keys: Optional[set] = None):
        """Actually write insights to disk."""
        self._dirty = False
        self.INSIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _insights_lock(self.LOCK_FILE) as lock:
            if not lock.acquired:
                # Another writer holds the lock; retry on next flush cycle.
                self._dirty = True
                return
            disk_data: Dict[str, Dict[str, Any]] = {}
            if self.INSIGHTS_FILE.exists():
                try:
                    disk_data = json.loads(self.INSIGHTS_FILE.read_text(encoding="utf-8"))
                except Exception:
                    disk_data = {}
            if drop_keys:
                for k in drop_keys:
                    disk_data.pop(k, None)

            merged: Dict[str, CognitiveInsight] = {}
            # Start from disk to avoid losing entries from other processes
            for key, info in disk_data.items():
                try:
                    merged[key] = CognitiveInsight.from_dict(info)
                except Exception:
                    continue

            # Merge in-memory insights
            for key, insight in self.insights.items():
                if key in merged:
                    merged[key] = self._merge_insight(insight, merged[key])
                else:
                    merged[key] = insight

            # Keep in-memory view consistent with merged result
            self.insights = merged

            data = {key: insight.to_dict() for key, insight in self.insights.items()}
            tmp = self.INSIGHTS_FILE.with_suffix(f".json.tmp.{os.getpid()}")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            for _ in range(5):
                try:
                    tmp.replace(self.INSIGHTS_FILE)
                    break
                except Exception:
                    time.sleep(0.05)
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    def _touch_validation(self, insight: CognitiveInsight, validated_delta: int = 0, contradicted_delta: int = 0):
        """Update validation counters and timestamp."""
        if validated_delta:
            insight.times_validated += validated_delta
        if contradicted_delta:
            insight.times_contradicted += contradicted_delta
        if validated_delta or contradicted_delta:
            insight.last_validated_at = _now_iso()

    def _generate_key(self, category: CognitiveCategory, identifier: str) -> str:
        """Generate a unique key for an insight."""
        return f"{category.value}:{identifier[:50]}"

    # =========================================================================
    # SELF-AWARENESS LEARNING
    # =========================================================================

    def learn_overconfidence(self, task_type: str, predicted_success: bool,
                             actual_success: bool, context: str):
        """Learn when I'm overconfident."""
        if predicted_success and not actual_success:
            key = self._generate_key(CognitiveCategory.SELF_AWARENESS, f"overconfident:{task_type}")
            evidence_item = _clip_evidence(context)
            if key in self.insights:
                self._touch_validation(self.insights[key], contradicted_delta=1)
                if evidence_item:
                    self.insights[key].evidence.append(evidence_item)
                # Keep only last 10 evidence items
                self.insights[key].evidence = self.insights[key].evidence[-10:]
            else:
                self.insights[key] = CognitiveInsight(
                    category=CognitiveCategory.SELF_AWARENESS,
                    insight=f"I tend to be overconfident about {task_type} tasks",
                    evidence=[evidence_item] if evidence_item else [],
                    confidence=0.6,
                    context=f"When attempting {task_type}"
                )
            self._save_insights()
            return self.insights[key]

    def learn_struggle_area(self, task_type: str, failure_reason: str):
        """Learn what types of tasks I struggle with."""
        if _is_injection_or_garbage(failure_reason):
            return None
        normalized_task = _normalize_struggle_text(task_type)
        key = self._generate_key(
            CognitiveCategory.SELF_AWARENESS,
            f"struggle:{_normalize_struggle_key(task_type)}",
        )
        low_signal = _is_low_signal_struggle_task(normalized_task)
        failure_evidence = _clip_evidence(failure_reason)
        if key in self.insights:
            if not low_signal:
                self._touch_validation(self.insights[key], validated_delta=1)
            if failure_evidence and failure_evidence not in self.insights[key].evidence:
                self.insights[key].evidence.append(failure_evidence)
                self.insights[key].evidence = self.insights[key].evidence[-10:]
        else:
            self.insights[key] = CognitiveInsight(
                category=CognitiveCategory.SELF_AWARENESS,
                insight=f"I struggle with {normalized_task} tasks",
                evidence=[failure_evidence] if failure_evidence else [],
                confidence=0.35 if low_signal else 0.5,
                context=f"Tasks involving {normalized_task}"
            )
        self._save_insights()
        return self.insights[key]

    def learn_blind_spot(self, what_i_missed: str, how_i_discovered: str):
        """Learn about my blind spots - things I consistently miss."""
        key = self._generate_key(CognitiveCategory.SELF_AWARENESS, f"blindspot:{what_i_missed}")
        if key in self.insights:
            # Merge: accumulate evidence and validate instead of overwriting
            existing = self.insights[key]
            evidence_item = _clip_evidence(how_i_discovered)
            if evidence_item:
                existing.evidence.append(evidence_item)
            existing.times_validated += 1
            existing.confidence = min(1.0, existing.confidence + 0.05)
        else:
            evidence_item = _clip_evidence(how_i_discovered)
            self.insights[key] = CognitiveInsight(
                category=CognitiveCategory.SELF_AWARENESS,
                insight=f"Blind spot: I tend to miss {what_i_missed}",
                evidence=[evidence_item] if evidence_item else [],
                confidence=0.7,
                context="During analysis and planning"
            )
        self._save_insights()
        return self.insights[key]

    # =========================================================================
    # USER UNDERSTANDING
    # =========================================================================

    def learn_user_preference(self, preference_type: str, preference_value: str,
                              evidence: str):
        """Learn about user preferences."""
        if _is_injection_or_garbage(preference_value):
            return None
        key = self._generate_key(CognitiveCategory.USER_UNDERSTANDING, f"pref:{preference_type}")
        evidence_item = _clip_evidence(evidence)
        if key in self.insights:
            self._touch_validation(self.insights[key], validated_delta=1)
            if evidence_item:
                self.insights[key].evidence.append(evidence_item)
            self.insights[key].evidence = self.insights[key].evidence[-10:]
        else:
            self.insights[key] = CognitiveInsight(
                category=CognitiveCategory.USER_UNDERSTANDING,
                insight=f"User prefers {preference_value} for {preference_type}",
                evidence=[evidence_item] if evidence_item else [],
                confidence=0.7,
                context=f"When {preference_type} is relevant"
            )
        self._save_insights()
        return self.insights[key]

    def learn_user_expertise(self, domain: str, level: str, evidence: str):
        """Learn about user's expertise level in a domain."""
        key = self._generate_key(CognitiveCategory.USER_UNDERSTANDING, f"expertise:{domain}")
        evidence_item = _clip_evidence(evidence)
        if key in self.insights:
            # Merge: update level, accumulate evidence, validate
            existing = self.insights[key]
            existing.insight = f"User has {level} expertise in {domain}"
            if evidence_item:
                existing.evidence.append(evidence_item)
            existing.times_validated += 1
            existing.confidence = min(1.0, existing.confidence + 0.05)
        else:
            self.insights[key] = CognitiveInsight(
                category=CognitiveCategory.USER_UNDERSTANDING,
                insight=f"User has {level} expertise in {domain}",
                evidence=[evidence_item] if evidence_item else [],
                confidence=0.6,
                context=f"When discussing {domain}"
            )
        self._save_insights()
        return self.insights[key]

    def learn_communication_style(self, style_aspect: str, preference: str):
        """Learn how user prefers to communicate."""
        key = self._generate_key(CognitiveCategory.USER_UNDERSTANDING, f"comm:{style_aspect}")
        self.insights[key] = CognitiveInsight(
            category=CognitiveCategory.USER_UNDERSTANDING,
            insight=f"User communication style: {style_aspect} = {preference}",
            evidence=[],
            confidence=0.7,
            context="All interactions"
        )
        self._save_insights()
        return self.insights[key]

    # =========================================================================
    # REASONING PATTERNS
    # =========================================================================

    def learn_why(self, what_worked: str, why_it_worked: str, context: str):
        """Learn WHY something worked, not just that it worked."""
        key = self._generate_key(CognitiveCategory.REASONING, f"why:{what_worked}")
        evidence_item = _clip_evidence(context)
        self.insights[key] = CognitiveInsight(
            category=CognitiveCategory.REASONING,
            insight=f"{what_worked} works because {why_it_worked}",
            evidence=[evidence_item] if evidence_item else [],
            confidence=0.7,
            context=_clip_context(context)
        )
        self._save_insights()
        return self.insights[key]

    def learn_principle(self, principle: str, examples: List[str]):
        """Learn a general principle that applies across contexts."""
        if _is_injection_or_garbage(principle):
            return None
        key = self._generate_key(CognitiveCategory.WISDOM, f"principle:{principle}")
        self.insights[key] = CognitiveInsight(
            category=CognitiveCategory.WISDOM,
            insight=principle,
            evidence=examples[:5],
            confidence=0.8,
            context="General principle"
        )
        self._save_insights()
        return self.insights[key]

    def learn_assumption_failure(self, assumption: str, reality: str, context: str):
        """Learn when an assumption proved wrong."""
        if _is_injection_or_garbage(assumption) or _is_injection_or_garbage(reality):
            return None
        key = self._generate_key(CognitiveCategory.REASONING, f"bad_assumption:{assumption}")
        evidence_item = _clip_evidence(context)
        self.insights[key] = CognitiveInsight(
            category=CognitiveCategory.REASONING,
            insight=f"Assumption '{assumption}' often wrong. Reality: {reality}",
            evidence=[evidence_item] if evidence_item else [],
            confidence=0.8,
            context=f"When making assumptions about {assumption[:30]}"
        )
        self._save_insights()
        return self.insights[key]

    # =========================================================================
    # CONTEXT INTELLIGENCE
    # =========================================================================

    def learn_context_boundary(self, pattern: str, applies_when: str,
                               does_not_apply_when: str):
        """Learn when a pattern applies vs doesn't apply."""
        key = self._generate_key(CognitiveCategory.CONTEXT, f"boundary:{pattern}")
        applies_evidence = _clip_evidence(applies_when)
        does_not_apply_evidence = _clip_evidence(does_not_apply_when)
        self.insights[key] = CognitiveInsight(
            category=CognitiveCategory.CONTEXT,
            insight=f"'{pattern}' applies when {applies_when}",
            evidence=[applies_evidence] if applies_evidence else [],
            confidence=0.7,
            context=_clip_context(applies_when),
            counter_examples=[does_not_apply_evidence] if does_not_apply_evidence else []
        )
        self._save_insights()
        return self.insights[key]

    def learn_signal(self, signal: str, what_it_indicates: str):
        """Learn what signals indicate about a situation.

        Deduplicates by normalizing signal (strips variable counts).
        Boosts confidence on repeated observations.
        """
        # Normalize signal for dedup - "Heavy Bash usage (42 calls)" -> "Heavy Bash usage"
        normalized = _normalize_signal(signal)
        key = self._generate_key(CognitiveCategory.CONTEXT, f"signal:{normalized}")

        if key in self.insights:
            # Existing signal - boost confidence and validate
            existing = self.insights[key]
            self._touch_validation(existing, validated_delta=1)
            existing.confidence = _boost_confidence(0.6, existing.times_validated)
            # Add the specific observation as evidence
            evidence_entry = _clip_evidence(f"{signal}: {what_it_indicates}")
            if evidence_entry and evidence_entry not in existing.evidence:
                existing.evidence.append(evidence_entry)
                existing.evidence = existing.evidence[-10:]  # Keep last 10
            self._save_insights()
            return existing

        # New signal
        evidence_entry = _clip_evidence(f"{signal}: {what_it_indicates}")
        self.insights[key] = CognitiveInsight(
            category=CognitiveCategory.CONTEXT,
            insight=f"When I see '{normalized}', it usually means {what_it_indicates}",
            evidence=[evidence_entry] if evidence_entry else [],
            confidence=0.6,
            context=f"Recognizing {normalized}"
        )
        self._save_insights()
        return self.insights[key]

    # =========================================================================
    # META-LEARNING
    # =========================================================================

    def learn_learning_preference(self, what_helps_me_learn: str, evidence: str):
        """Learn about how I learn best."""
        key = self._generate_key(CognitiveCategory.META_LEARNING, f"learning:{what_helps_me_learn}")
        evidence_item = _clip_evidence(evidence)
        self.insights[key] = CognitiveInsight(
            category=CognitiveCategory.META_LEARNING,
            insight=f"I learn better when {what_helps_me_learn}",
            evidence=[evidence_item] if evidence_item else [],
            confidence=0.7,
            context="Learning and improvement"
        )
        self._save_insights()
        return self.insights[key]

    def learn_ask_vs_act(self, situation: str, should_ask: bool, reasoning: str):
        """Learn when to ask the user vs just act."""
        action = "ask first" if should_ask else "act directly"
        key = self._generate_key(CognitiveCategory.META_LEARNING, f"ask_act:{situation}")
        reasoning_evidence = _clip_evidence(reasoning)
        self.insights[key] = CognitiveInsight(
            category=CognitiveCategory.META_LEARNING,
            insight=f"In '{situation}' situations, I should {action}",
            evidence=[reasoning_evidence] if reasoning_evidence else [],
            confidence=0.7,
            context=_clip_context(situation)
        )
        self._save_insights()
        return self.insights[key]

    # =========================================================================
    # COMMUNICATION
    # =========================================================================

    def learn_explanation_success(self, topic: str, explanation_style: str,
                                  was_effective: bool):
        """Learn what explanation styles work for what topics."""
        if was_effective:
            key = self._generate_key(CognitiveCategory.COMMUNICATION, f"explain:{topic}")
            self.insights[key] = CognitiveInsight(
                category=CognitiveCategory.COMMUNICATION,
                insight=f"For {topic}, explain using {explanation_style}",
                evidence=[],
                confidence=0.7,
                context=f"When explaining {topic}"
            )
            self._save_insights()
            return self.insights[key]

    # =========================================================================
    # NOISE FILTERING (Final Gate)
    # =========================================================================

    def _is_noise_insight(self, text: str) -> bool:
        """Final gate filter - block noise patterns at point of storage.

        This catches anything that bypassed earlier filters.
        Returns True if the insight is noise and should NOT be stored.
        """
        if not text:
            return True

        # Check indented code BEFORE stripping (strip removes the evidence)
        raw = text.rstrip()
        if raw and raw[0] in (' ', '\t'):
            leading = len(raw) - len(raw.lstrip())
            if leading >= 4:
                stripped_line = raw.lstrip()
                # Indented assignment: "    current.confidence = max(...)"
                if re.match(r"[\w.]+\s*=\s*.+", stripped_line):
                    return True
                # Indented statement: "    self._log(...)", "    return x"
                if re.match(r"(self\.\w+|if |for |def |class |return |import |from |try:|except|raise |print\(|elif )", stripped_line):
                    return True

        t = text.strip()
        tl = t.lower()

        # 1. Tool sequences: "Sequence 'X -> Y -> Z' worked well"
        if t.startswith("Sequence '") or t.startswith('Sequence "'):
            return True
        if "sequence" in tl and "worked" in tl:
            return True

        # 2. Tool chains with arrows: indicates tool sequence
        arrow_count = t.count("->")
        if arrow_count >= 2:
            return True
        if arrow_count >= 1 and any(s in tl for s in ["sequence", "pattern", "worked well", "works well"]):
            return True

        # 3. Pattern telemetry: "Pattern 'X -> Y' risky" (unless it has actionable content)
        if t.startswith("Pattern '") and "->" in t and "risky" not in tl:
            return True

        # 3b. Usage telemetry: "Heavy Bash usage (42 calls)"
        if re.search(r"\bheavy\s+\w+\s+usage\b", tl):
            return True
        if re.search(r"\busage\s*\(\d+\s*calls?\)", tl):
            return True
        if "usage count" in tl or tl.startswith("usage "):
            return True

        # 4. User wanted without context (short, no explanation)
        if t.startswith("User wanted:") and len(t) < 60:
            return True

        # 4b. Tool satisfaction/frustration telemetry
        if t.startswith("User was satisfied after:") or t.startswith("User frustrated after:"):
            return True

        # 5. User persistently asking (just word tracking)
        if t.startswith("User persistently asking about:"):
            return True

        # 6. Generic success factors
        if t.startswith("Success factor:") and len(t) < 50:
            return True

        # 7. Tool-heavy text (>40% tool names)
        tool_names = ["bash", "read", "edit", "write", "grep", "glob",
                      "todowrite", "taskoutput", "webfetch", "task"]
        words = tl.split()
        if words:
            tool_mentions = sum(1 for w in words if any(tn in w for tn in tool_names))
            if tool_mentions / len(words) > 0.4:
                return True

        # 8. Vague observations without action (Task #12)
        vague_starts = [
            "user seems to", "user appears to", "it seems", "it appears",
            "might be", "could be", "probably", "possibly",
        ]
        if any(tl.startswith(v) for v in vague_starts):
            return True

        # 9. Pure metrics/stats
        if re.search(r"^\d+%?\s+(success|failure|error)", tl):
            return True
        if re.search(r"(success|error|failure)\s+rate[:\s]+\d+", tl):
            return True

        # 10. Too short to be actionable (< 20 chars after stripping)
        if len(t) < 20:
            return True

        # 11. "User prefers X over Y" without reasoning (short form)
        if re.match(r"^user prefers .{5,30} over .{5,30}$", tl):
            return True

        # 12. Chip insight patterns - these are telemetry, not cognitive insights
        # Examples: "[Vibecoding Intelligence] post_tool Edit C:\workspace\..."
        #           "[Market Intelligence] pre_tool Bash..."
        #           "Triggered by 'post_tool_failure'"
        chip_intel_pattern = r"^\[[\w\s-]+ intelligence\]\s*(post_tool|pre_tool)"
        if re.search(chip_intel_pattern, tl):
            return True

        # 13. Triggered by telemetry
        if re.search(r"triggered by ['\"]?(post_tool|pre_tool)", tl):
            return True

        # 14. Benchmark/Intelligence chip outputs with tool events
        if "] post_tool " in t or "] pre_tool " in t:
            return True

        # 15. Chip status telemetry: "status: success, tool_name: X" or "status=success"
        if re.search(r"status[=:]\s*(success|failure|error),?\s*tool_name[=:]", tl):
            return True

        # 16. Success factor without reasoning (short)
        if t.startswith("Success factor:") and len(t) < 100:
            return True

        # 17. Task notification XML blobs
        if "<task-notification>" in t or "<task-id>" in t or "<output-file>" in t:
            return True

        # 18. Code dumps (>5 lines, majority indented at 2+ spaces)
        lines = t.split("\n")
        if len(lines) > 5:
            indented = sum(1 for ln in lines if ln.startswith("  ") or ln.startswith("\t"))
            if indented > len(lines) * 0.5:
                return True

        # 19. Garbled user preferences with single-char fragments
        # e.g. "User prefers 'eeding to pay for it' over 'n'"
        if "User prefers '" in t and "' over '" in t:
            m = re.search(r"over '(.{1,3})'", t)
            if m and len(m.group(1)) <= 2:
                return True

        # 20. Benchmark/intelligence chip artifacts with diagnostic fields
        # Catches [XXX Intelligence] + any of: tool_name, file_path, status, command, etc.
        if re.match(r"^\[[\w\s-]+ Intelligence\]", t):
            diag_fields = r"(tool_name|file_path|status|command|tool_input|context|content|user_prompt)[=:\s]"
            if re.search(diag_fields, t):
                return True

        # 20b. Prompt injection test artifacts
        if "QUALITY_TEST" in t or "quality_test_" in t:
            return True

        # 21. Screenshot / image paths stored as insights
        if re.search(r"\\Screenshots\\|\.png['\"\s]|\.jpg['\"\s]", t):
            return True

        # 22. Rambling transcribed speech without technical substance
        # Long text with filler phrases and no actionable keywords
        if len(t) > 80:
            filler_phrases = ["you know", "in such a way", "kind of", "sort of",
                              "make sure that we", "those things", "these things",
                              "in a way that", "going forward", "i would say",
                              "by the way", "let's bring", "let's make sure",
                              "is going to be"]
            filler_count = sum(1 for fp in filler_phrases if fp in tl)
            tech_keywords = ["function", "class", "import", "error", "bug", "api",
                             "database", "auth", "deploy", "test", "config", "server",
                             "client", "endpoint", "query", "schema", "type"]
            has_tech = any(re.search(rf"\b{kw}\b", tl) for kw in tech_keywords)
            if filler_count >= 2 and not has_tech:
                return True

        # 23. Workflow execution telemetry from Mind
        # e.g., "Workflow Execution 1/9/2026, 5:06:01 PM workflow: Successful workflow pattern"
        if re.match(r"^workflow execution\s+\d{1,2}/\d{1,2}/\d{4}", tl):
            return True

        # 24. Generic testing/pipeline assertions without context
        if re.match(r"^testing\s+\w+\s+\w+\s+(works|passes|runs|completed|succeeded)\s*(correctly|successfully)?\.?$", tl):
            return True

        # 25. Document-like content: markdown headers stored as insights
        # e.g., "# Semantic Advisor Design", "### What's Now Working"
        if re.match(r"^#{1,4}\s+", t):
            return True

        # 26. File paths stored as insights (raw paths without context)
        # e.g., "c:\workspace\xmcp ..."
        if re.match(r"^[a-zA-Z]:\\", t):
            return True

        # 27. Conversational fragments stored as insights
        # User messages captured verbatim: "Do you think we should...", "Can you..."
        # NOTE: "we should", "we need to", "we have to" are VALID imperatives
        # and were removed from this list to avoid filtering actionable insights.
        conversational_starts = [
            "do you think", "can you ", "let's ", "let me ", "okay,",
            "ok,", "alright,", "all right,", "by the way,", "oh,",
            "so,", "well,", "hmm", "what about", "how about",
            "continue to do", "i would say", "yeah,", "yeah ", "yep,",
            "sure,", "right,", "no,", "nah,", "i mean,",
            "it's probably", "it's not", "we already", "we were ",
            # Captured transcript fragments often drop apostrophes ("lets" vs "let's").
            "lets ",
        ]
        if any(tl.startswith(cs) for cs in conversational_starts):
            return True

        # 28. Very long insights (>250 chars) that are likely documents/transcripts, not insights
        if len(t) > 250:
            # Allow long insights if they contain clear action verbs
            action_verbs = ['use ', 'avoid ', 'check ', 'verify ', 'ensure ', 'always ',
                            'never ', 'remember ', "don't ", 'prefer ', 'when ',
                            'must ', 'should ', 'fix ', 'run ', 'stop ', 'try ',
                            'update ', 'critical', 'important', 'correction:']
            has_action = any(v in tl for v in action_verbs)
            # Or if they start with established insight patterns
            insight_starts = ['user prefers ', 'principle:', 'i struggle ', 'i tend to ',
                              'blind spot:', 'assumption ', 'when i see ',
                              'remember:', 'critical:', 'correction:',
                              'rule ', 'we should ', 'we need to ']
            has_insight_start = any(tl.startswith(s) for s in insight_starts)
            if not has_action and not has_insight_start:
                return True

        # 29. Garbled "When using X" fragments from truncated transcription
        # e.g., "When using Bash, prefer 'ver hallucinating'" -- mid-word cutoff
        if re.match(r"^when using \w+,\s*(prefer|remember)[:\s]", tl):
            # Reject long rambling continuations ("... and is this system ...") which are almost
            # always raw transcript fragments rather than durable advice.
            if len(t) > 90 and any(
                frag in tl
                for frag in (
                    " and is this ",
                    " can you ",
                    " do you think",
                    " at some point",
                    " council of ",
                    " lets push",
                    " let's push",
                )
            ):
                return True
            # Check for truncated single-quoted fragment (starts with lowercase mid-word)
            m = re.search(r"'([a-z])", t)
            if m:
                return True
            # Also reject conversational continuations
            if re.search(r"(remember|prefer)[:\s]+'?(actually|lets|let's|just|maybe)", tl):
                return True

        # 30. Label + conversational fragment patterns
        # "Principle: that the @META_RALPH", "Constraint: talk about it right now"
        # Real principles are declarative; these are conversational references.
        label_prefixes = [
            "principle:", "constraint:", "reasoning:", "failure reason:",
            "success factor:", "test:",
        ]
        for lp in label_prefixes:
            if tl.startswith(lp):
                rest = tl[len(lp):].strip()
                # Reject if followed by conversational words
                conv_words = ["that ", "this ", "those ", "these ", "it ",
                              "right now", "all of", "we ", "they ", "follows ",
                              "abides", "keep to", "talk about", "with the ",
                              "with a ", "drop,", "what we", "make sure",
                              "the way", "i would", "i think", "utilize ",
                              "the primary", "the system", "the use of"]
                if any(rest.startswith(cw) for cw in conv_words):
                    return True
                # Reject if rest is too short (<15 chars) to be actionable
                if len(rest) < 15:
                    return True
                break

        # 31. Market intelligence chip output with engagement metrics
        # e.g., "[moltbook] (eng:45) Moltbook is great but..."
        if re.match(r"^\[[\w-]+\]\s*\(eng:\d+\)", tl):
            return True

        # 32. Intelligence chip "Triggered by" with domain tags
        # e.g., "[Market Intelligence] Triggered by 'vibe coding'"
        if re.match(r"^\[[\w\s-]+ intelligence\]\s*triggered by", tl):
            return True

        # 33. Code snippets stored as insights
        # e.g., "ADVICE_CACHE_TTL_SECONDS = 120", "DEFAULT_MIN_VALIDATIONS = 2"
        # Also catches indented code blocks
        if re.match(r"^[A-Z][A-Z_]+\s*=\s*\S+", t):
            return True
        # Indented assignments / expressions (often copied from code or logs)
        # e.g., "    current.confidence = max(...)" (including with dots)
        if re.match(r"^\s{4,}[\w.]+\s*=\s*.+", t):
            return True
        if re.match(r"^\s{4,}(if |for |def |class |return |import |from |try:|except)", t):
            return True
        # Multi-line blocks are almost never durable "insights" and usually indicate a pasted code
        # fragment, transcript chunk, or doc section.
        if "\n" in t:
            return True

        # 34. Docstring/comment fragments (triple-quoted strings, JSDoc, etc.)
        if t.startswith('"""') or t.startswith("'''") or t.startswith("/**") or t.startswith("/*"):
            return True

        # 35. File reference lists stored as insights
        # e.g., "- `lib/pattern_detection/aggregator.py` (added per..."
        if re.match(r"^-\s*`(lib|src|hooks|scripts)/", t):
            return True

        # 36. User preference/wanted with markdown formatting or garbled text
        # e.g., "User wanted: wrong?** 3. **What check would have p..."
        if re.match(r"^user (wanted|prefers?)", tl):
            # Contains markdown bold markers or numbered list fragments
            if "**" in t or re.search(r"\d+\.\s*\*\*", t):
                return True
            # Single-quoted content that starts with a lowercase letter (truncated)
            m = re.search(r"'([a-z])", t)
            if m and "over '" not in t:
                return True

        # 37. Conversational "About these" / "About this" starters
        if tl.startswith("about these ") or tl.startswith("about this "):
            return True

        # 38. Benchmark/pipeline test artifacts
        if "[pipeline_test" in tl or "[benchmark" in tl:
            return True

        # 39. "User wanted:" followed by conversational text (let's, actually, etc.)
        # These are user prompt transcriptions, not actual preference data.
        if tl.startswith("user wanted:"):
            rest = tl[len("user wanted:"):].strip()
            conv_starters = ["let's", "lets", "actually", "i think", "we should",
                             "can we", "i want", "please", "just ", "maybe"]
            if any(rest.startswith(cs) for cs in conv_starters):
                return True

        # 40. "Prefer '" with truncated/garbled content (mid-word cutoff)
        # e.g., "Prefer 'aking them a little awkward..."
        if re.match(r"^prefer\s+'[a-z]", tl):
            return True

        # 41. Markdown section headers embedded in insights
        # e.g., "## Session History", "## Current State: 2026-02-03"
        if re.match(r"^##\s+", t):
            return True

        # 42. "I struggle with tool_N_error" — generic hook error telemetry
        # e.g., "I struggle with tool_5_error tasks", "I struggle with tool_49_error tasks"
        if re.search(r"i struggle with tool_\d+_error", tl):
            return True

        # 47. Cycle summary telemetry — operational data, not cognitive insights
        # e.g., "Cycle summary: Bash used 3 times (100% success)."
        # e.g., "Processed 42 events with 5 tools tracked and 0 error patterns"
        if tl.startswith("cycle summary:"):
            return True
        if re.match(r"^processed \d+ events with \d+ tools? tracked", tl):
            return True

        # 48. Tool usage counts — Tier 1 operational telemetry
        # e.g., "Bash used 8 times (100% success)", "Read had 75% success across 4 uses"
        if re.search(r"\b\w+ used \d+ times?\b", tl):
            return True
        if re.search(r"\bhad \d+%? success across \d+ uses\b", tl):
            return True

        # 49. Large edit warnings — operational telemetry about file edits
        # e.g., "Large edit on pipeline.py (652→1036 chars). Consider smaller..."
        if re.match(r"^large edit on \w+\.\w+\s*\(", tl):
            return True

        # 50. Generic tool struggle — auto-generated from any tool error
        # e.g., "I struggle with Bash_error tasks", "I struggle with Glob_error tasks"
        if re.match(r"^i struggle with \w+_error tasks?$", tl):
            return True

        # 51. Goal genesis telemetry — cycle counts, not actionable insights
        # e.g., "3 goals completed. Top gap: cognitive:self_awareness (severity 1.00)"
        if re.match(r"^\d+ goals? completed\. top gap:", tl):
            return True

        # 43. Python import statements stored as insights (column-0 imports)
        # e.g., "from lib.diagnostics import log_debug as _bridge_log_debug"
        if re.match(r"^(from\s+[\w.]+\s+import\s|import\s+[\w.,\s]+$)", t):
            return True

        # 44. Short/vague "Constraint:" or "Principle:" with conversational fragments
        # e.g., "Constraint: check and about each", "Constraint: utilise all those APIs"
        for lp in ("constraint:", "principle:", "reasoning:"):
            if tl.startswith(lp):
                rest = tl[len(lp):].strip()
                # Conversational markers: direct address, vague references
                if re.search(r"(please|let me know|as well|about each|right now|at the moment|over here|about this|let's|utilise|utilize all)", rest):
                    return True
                # Fragments that just reference something without actionable content
                if re.search(r"^(check |look |see |about |what |how |when |where |that we|the way)", rest):
                    return True
                break

        # 45. Chip intelligence with generic "pattern:" or "observation:" fields
        # e.g., "[Spark Core Intelligence] pattern: awaiting one"
        if re.match(r"^\[[\w\s-]+\]\s*(pattern|observation|event|signal|trigger):", t, re.IGNORECASE):
            return True

        # 46. "User prefers: X" extremely short (< 25 chars after prefix)
        if tl.startswith("user prefers:") or tl.startswith("user aversion:"):
            rest = t.split(":", 1)[1].strip() if ":" in t else ""
            if len(rest) < 25:
                return True

        return False

    def is_noise_insight(self, text: str) -> bool:
        """Public helper for filtering noise insights."""
        return self._is_noise_insight(text)

    # =========================================================================
    # RETRIEVAL AND QUERY
    # =========================================================================

    # Stopwords to skip in word-matching (common words that cause false matches)
    _RETRIEVAL_STOPWORDS = frozenset({
        "the", "and", "for", "with", "from", "this", "that", "used", "have",
        "been", "were", "was", "are", "not", "but", "its", "into", "also",
        "more", "than", "can", "all", "had", "has", "will", "each", "which",
        "their", "them", "then", "when", "what", "how", "about", "would",
        "make", "like", "just", "over", "such", "take", "only", "come",
        "could", "after", "use", "two", "way", "our", "out", "get", "may",
        "cycle", "summary", "summary:", "times", "across", "uses", "success",
        "100%", "had", "session", "session(s)", "consecutive", "failures",
    })

    def get_insights_for_context(
        self,
        context: str,
        limit: int = 10,
        with_keys: bool = False,
    ) -> List[Any]:
        """Get relevant cognitive insights for a given context.

        Lightweight ranking:
        - Prefer direct string matches (query in insight.context/insight text)
        - Then reliability/validations
        - If with_keys=True, returns (insight_key, insight) tuples

        Noise prevention:
        - Filters out noise insights BEFORE limit truncation
        - Requires 2+ word matches (not single-word) to reduce false positives
        - Skips stopwords and short words in word-matching
        """
        relevant: List[tuple[float, str, CognitiveInsight]] = []
        context_lower = (context or "").lower()
        if not context_lower:
            return []

        for key, insight in self.insights.items():
            # Pre-filter: skip cycle summaries and noise
            ii_text = insight.insight or ""
            if ii_text.startswith("Cycle summary:"):
                continue
            if self._is_noise_insight(ii_text):
                continue
            # LLM area: generic_demotion — skip generic platitudes during retrieval
            if self._llm_area_generic_demotion(ii_text, context_lower):
                continue

            ic = (insight.context or "").lower()
            ii = ii_text.lower()

            # Direct context field matching (high precision)
            direct_hit = (
                (ic and ic in context_lower) or
                (context_lower and context_lower in ic)
            )

            # Word-matching: require 2+ meaningful word matches
            # Scan more of the insight text (first 30 words) for better recall
            word_hit = False
            word_match_count = 0
            if not direct_hit:
                words = ii.split()[:30]
                meaningful_words = set(
                    w.rstrip(".,;:!?()'\"") for w in words
                    if len(w) >= 4 and w.rstrip(".,;:!?()'\"") not in self._RETRIEVAL_STOPWORDS
                )
                # Also extract meaningful words from query for bidirectional matching
                query_words = set(
                    w.rstrip(".,;:!?()'\"") for w in context_lower.split()
                    if len(w) >= 4 and w.rstrip(".,;:!?()'\"") not in self._RETRIEVAL_STOPWORDS
                )
                # Basic suffix stemming for better recall
                def _stem(w: str) -> str:
                    for sfx in ("tion", "sion", "ment", "ness", "able", "ible", "ying", "ling", "ting", "ning", "ring", "ding", "ling", "ing", "ied", "ies", "ted", "ely", "ful", "ous", "ive", "ity", "ize", "ise", "ers", "ure", "ual", "ial", "ent", "ant", "ist", "ism", "age", "ary", "ory", "ery", "lly", "ily", "ed", "ly", "er", "es"):
                        if w.endswith(sfx) and len(w) - len(sfx) >= 3:
                            return w[:-len(sfx)]
                    return w
                stemmed_insight = {_stem(w) for w in meaningful_words}
                stemmed_query = {_stem(w) for w in query_words}
                word_match_count = len(meaningful_words & query_words) + len(stemmed_insight & stemmed_query - (meaningful_words & query_words))
                # 2+ matches for normal insights, 1 match for high-reliability ones
                word_hit = (
                    word_match_count >= 2 or
                    (word_match_count >= 1 and insight.reliability >= 0.8)
                )

            if not direct_hit and not word_hit:
                continue

            match_score = 0.0
            if context_lower and context_lower in ic:
                match_score += 1.0
            if context_lower and context_lower in ii:
                match_score += 0.7
            if word_hit and not direct_hit:
                # Scale word match score by how many words matched (more = better)
                match_score += 0.2 + min(0.3, word_match_count * 0.08)

            relevant.append((match_score, key, insight))

        relevant.sort(key=lambda t: (t[0], t[2].reliability, t[2].times_validated), reverse=True)
        top = relevant[:limit]
        if with_keys:
            return [(k, i) for _, k, i in top]
        return [i for _, _, i in top]

    # -- LLM area hooks (opt-in via llm_areas tuneable section) --

    @staticmethod
    def _llm_area_evidence_compress(evidence: str) -> str:
        """LLM area: compress verbose evidence text before storage."""
        if not evidence or len(evidence) < 120:
            return evidence
        try:
            from .llm_area_prompts import format_prompt
            from .llm_dispatch import llm_area_call

            prompt = format_prompt(
                "evidence_compress",
                evidence=evidence[:500],
                char_limit="250",
            )
            result = llm_area_call("evidence_compress", prompt, fallback=evidence)
            if result.used_llm and result.text and len(result.text) < len(evidence):
                return result.text
            return evidence
        except Exception:
            return evidence

    @staticmethod
    def _llm_area_conflict_resolve(new_insight: str, existing: "CognitiveInsight") -> str:
        """LLM area: resolve contradictions between new and existing insights.

        Returns the resolved insight text (may merge, prefer new, or prefer existing).
        When disabled (default), returns new_insight unchanged.
        """
        try:
            from .llm_area_prompts import format_prompt
            from .llm_dispatch import llm_area_call

            prompt = format_prompt(
                "conflict_resolve",
                new_insight=new_insight[:300],
                existing_insight=(existing.insight or "")[:300],
                existing_confidence=str(existing.confidence),
                existing_validations=str(existing.times_validated),
            )
            result = llm_area_call("conflict_resolve", prompt, fallback=new_insight)
            if result.used_llm and result.text:
                return result.text
            return new_insight
        except Exception:
            return new_insight

    @staticmethod
    def _llm_area_generic_demotion(insight_text: str, query: str) -> bool:
        """LLM area: check if insight is too generic for the given query context.

        Returns True if the insight should be demoted (skipped), False to keep.
        When disabled (default), always returns False (no-op).
        """
        try:
            from .llm_area_prompts import format_prompt
            from .llm_dispatch import llm_area_call

            prompt = format_prompt(
                "generic_demotion",
                insight=insight_text[:300],
                query=query[:200],
            )
            result = llm_area_call("generic_demotion", prompt, fallback="keep")
            if result.used_llm and result.text:
                lower = result.text.strip().lower()
                if "demote" in lower or "generic" in lower or "skip" in lower:
                    return True
            return False
        except Exception:
            return False

    def add_insight(self, category: CognitiveCategory, insight: str,
                    context: str = "", confidence: float = 0.7,
                    record_exposure: bool = True,
                    source: str = "") -> Optional[CognitiveInsight]:
        """Add a generic insight directly.

        Boosts confidence on repeated validations.
        If record_exposure=True, also creates an exposure record so predictions
        can be generated and validated.

        Returns None if insight is filtered as noise.
        """
        # FINAL GATE: Block noise patterns that somehow bypassed earlier filters
        if self._is_noise_insight(insight):
            return None

        # Block cycle summaries - operational telemetry, not learning
        if insight.startswith("Cycle summary:"):
            return None

        # Compute advisory quality dimensions for storage
        adv_quality_dict: Dict[str, Any] = {}
        try:
            from lib.distillation_transformer import transform_for_advisory
            adv_quality = transform_for_advisory(insight, source=source)
            adv_quality_dict = adv_quality.to_dict()
            # Suppress insights that won't be useful as advisory
            if adv_quality.suppressed:
                return None
        except Exception:
            pass  # Don't block insight storage if transformer fails

        # Generate key from first few words of insight
        key_part = insight[:40].replace(" ", "_").lower()
        key = self._generate_key(category, key_part)
        emotion_state = _capture_emotion_state_snapshot()
        normalized_context = _backfill_actionable_context(context, insight, adv_quality_dict)
        context_evidence = _clip_evidence(normalized_context or context or insight)

        # LLM area: evidence_compress — compress verbose evidence before storage
        context_evidence = self._llm_area_evidence_compress(context_evidence)

        if key in self.insights:
            # Update existing - boost confidence!
            existing = self.insights[key]

            # LLM area: conflict_resolve — detect and resolve contradictions
            insight = self._llm_area_conflict_resolve(insight, existing)

            self._touch_validation(existing, validated_delta=1)
            existing.confidence = _boost_confidence(confidence, existing.times_validated)
            if context_evidence and context_evidence not in existing.evidence:
                existing.evidence.append(context_evidence)
                existing.evidence = existing.evidence[-10:]
            if normalized_context and len(normalized_context) > len(str(existing.context or "")):
                existing.context = normalized_context
            if emotion_state:
                existing.emotion_state = emotion_state
            # Refresh advisory quality on validation
            if adv_quality_dict:
                existing.advisory_quality = adv_quality_dict
            existing.advisory_readiness = _compute_advisory_readiness(
                insight,
                existing.advisory_quality,
                confidence=existing.confidence,
                times_validated=existing.times_validated,
                times_contradicted=existing.times_contradicted,
            )
        else:
            domain = classify_action_domain(insight, category=category.value, source=source)
            readiness = _compute_advisory_readiness(
                insight,
                adv_quality_dict,
                confidence=confidence,
                times_validated=1,
            )
            self.insights[key] = CognitiveInsight(
                category=category,
                insight=insight,
                evidence=[context_evidence] if context_evidence else [],
                confidence=confidence,
                context=normalized_context,
                source=source,
                action_domain=domain,
                emotion_state=emotion_state,
                advisory_quality=adv_quality_dict,
                advisory_readiness=readiness,
            )

        self._save_insights()

        # Record exposure so predictions can be generated
        if record_exposure:
            try:
                from lib.exposure_tracker import (
                    infer_latest_session_id,
                    infer_latest_trace_id,
                    record_exposures,
                )
                session_id = infer_latest_session_id()
                trace_id = infer_latest_trace_id(session_id)
                record_exposures(
                    source="spark_inject",
                    items=[{
                        "insight_key": key,
                        "category": category.value,
                        "text": insight,
                    }],
                    session_id=session_id,
                    trace_id=trace_id
                )
            except Exception as e:
                logging.getLogger(__name__).debug("Exposure tracking unavailable: %s", e)

        # Index for semantic retrieval (best-effort)
        try:
            from lib.semantic_retriever import index_insight
            index_insight(key, insight, normalized_context)
        except Exception as e:
            logging.getLogger(__name__).debug("Semantic indexing unavailable: %s", e)
            pass  # Don't block writes if semantic indexing fails

        return self.insights[key]

    def purge_primitive_insights(self, dry_run: bool = False, max_preview: int = 20) -> Dict[str, Any]:
        """Remove operational/primitive insights from storage.

        Uses the same noise filter as the final gate to identify items to purge.
        """
        to_remove: List[str] = []
        by_category: Dict[str, int] = {}
        previews: List[str] = []

        for key, insight in self.insights.items():
            if not self._is_noise_insight(insight.insight):
                continue
            to_remove.append(key)
            cat = insight.category.value
            by_category[cat] = by_category.get(cat, 0) + 1
            if len(previews) < max(0, int(max_preview or 0)):
                previews.append(insight.insight[:120])

        if not dry_run and to_remove:
            for key in to_remove:
                self.insights.pop(key, None)
            # Pass drop_keys to ensure removed items don't get merged back from disk
            self._save_insights(drop_keys=set(to_remove))

        return {
            "removed": len(to_remove),
            "by_category": by_category,
            "preview": previews,
            "dry_run": dry_run,
        }

    def apply_outcome(self, insight_key: str, outcome: str, evidence: str = "") -> bool:
        """Apply an outcome (good/bad) to a known insight to influence reliability."""
        if insight_key not in self.insights:
            return False

        ins = self.insights[insight_key]
        outcome = (outcome or "").strip().lower()
        evidence_item = _clip_evidence(evidence)
        if outcome == "good":
            self._touch_validation(ins, validated_delta=1)
            if evidence_item:
                ins.evidence.append(evidence_item)
                ins.evidence = ins.evidence[-10:]
            ins.confidence = _boost_confidence(ins.confidence, 1)
        elif outcome == "bad":
            self._touch_validation(ins, contradicted_delta=1)
            if evidence_item:
                ins.counter_examples.append(evidence_item)
                ins.counter_examples = ins.counter_examples[-10:]
            ins.confidence = max(0.1, ins.confidence * 0.85)
        else:
            return False

        self._save_insights()
        return True

    def get_self_awareness_insights(self) -> List[CognitiveInsight]:
        """Get all self-awareness insights."""
        return [i for i in self.insights.values()
                if i.category == CognitiveCategory.SELF_AWARENESS]

    def get_user_insights(self) -> List[CognitiveInsight]:
        """Get all user understanding insights."""
        return [i for i in self.insights.values()
                if i.category == CognitiveCategory.USER_UNDERSTANDING]

    def get_wisdom(self) -> List[CognitiveInsight]:
        """Get general principles and wisdom."""
        return [i for i in self.insights.values()
                if i.category == CognitiveCategory.WISDOM]

    def get_unpromoted(self) -> List[CognitiveInsight]:
        """Get insights that haven't been promoted yet."""
        return [i for i in self.insights.values() if not i.promoted]

    def get_promotable(self, min_reliability: float = 0.7, min_validations: int = 3) -> List[CognitiveInsight]:
        """Get insights ready for promotion."""
        return [
            i for i in self.insights.values()
            if not i.promoted
            and i.reliability >= min_reliability
            and i.times_validated >= min_validations
        ]

    def mark_promoted(self, insight_key: str, promoted_to: str):
        """Mark an insight as promoted."""
        if insight_key in self.insights:
            self.insights[insight_key].promoted = True
            self.insights[insight_key].promoted_to = promoted_to
            self._save_insights()

    def mark_unpromoted(self, insight_key: str):
        """Clear promoted state so the insight can be re-evaluated."""
        if insight_key in self.insights:
            self.insights[insight_key].promoted = False
            self.insights[insight_key].promoted_to = None
            self._save_insights()

    def format_for_injection(self, insights: List[CognitiveInsight]) -> str:
        """Format insights for context injection."""
        if not insights:
            return ""

        lines = ["## Cognitive Insights"]
        for insight in insights[:10]:
            reliability_str = f"({insight.reliability:.0%} reliable)" if insight.times_validated > 0 else ""
            lines.append(f"- {insight.insight} {reliability_str}")

        return "\n".join(lines)

    def get_stats(self) -> Dict:
        """Get statistics about cognitive learnings."""
        by_category = {}
        for insight in self.insights.values():
            cat = insight.category.value
            by_category[cat] = by_category.get(cat, 0) + 1

        total = len(self.insights)
        avg_reliability = sum(i.reliability for i in self.insights.values()) / max(total, 1)
        promoted_count = sum(1 for i in self.insights.values() if i.promoted)

        return {
            "total_insights": total,
            "by_category": by_category,
            "avg_reliability": avg_reliability,
            "promoted_count": promoted_count,
            "unpromoted_count": total - promoted_count,
        }

    # =========================================================================
    # PHASE 3: DECAY + CONFLICT RESOLUTION
    # =========================================================================

    def _age_days(self, insight: CognitiveInsight) -> float:
        """Compute age in days (prefer last validation if present)."""
        base = _parse_iso(insight.last_validated_at) or _parse_iso(insight.created_at)
        if not base:
            return 0.0
        return max(0.0, (datetime.now() - base).total_seconds() / 86400.0)

    def _half_life_days(self, category: CognitiveCategory) -> float:
        """Half-life in days by category."""
        mapping = {
            CognitiveCategory.USER_UNDERSTANDING: 90.0,   # preferences
            CognitiveCategory.COMMUNICATION: 90.0,
            CognitiveCategory.WISDOM: 180.0,            # principles
            CognitiveCategory.META_LEARNING: 120.0,
            CognitiveCategory.SELF_AWARENESS: 60.0,
            CognitiveCategory.REASONING: 60.0,
            CognitiveCategory.CONTEXT: 45.0,
            CognitiveCategory.CREATIVITY: 60.0,
        }
        return mapping.get(category, 60.0)

    def effective_reliability(self, insight: CognitiveInsight) -> float:
        """Reliability adjusted by temporal decay."""
        age_days = self._age_days(insight)
        half_life = max(1.0, self._half_life_days(insight.category))
        decay = 0.5 ** (age_days / half_life)
        return max(0.0, min(1.0, insight.reliability * decay))

    def prune_stale(self, max_age_days: float = 365.0, min_effective: float = 0.2) -> int:
        """Remove stale insights that have decayed below threshold."""
        to_delete = []
        for key, insight in self.insights.items():
            if self._age_days(insight) < max_age_days:
                continue
            if self.effective_reliability(insight) < min_effective:
                to_delete.append(key)

        for key in to_delete:
            del self.insights[key]

        if to_delete:
            self._save_insights()
        return len(to_delete)

    def get_prune_candidates(
        self,
        max_age_days: float = 365.0,
        min_effective: float = 0.2,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Preview which insights would be pruned by decay rules."""
        candidates: List[Dict[str, Any]] = []
        for key, insight in self.insights.items():
            age = self._age_days(insight)
            if age < max_age_days:
                continue
            eff = self.effective_reliability(insight)
            if eff >= min_effective:
                continue
            candidates.append({
                "key": key,
                "insight": insight.insight,
                "category": insight.category.value,
                "age_days": round(age, 1),
                "effective_reliability": round(eff, 3),
                "reliability": round(insight.reliability, 3),
                "validations": insight.times_validated,
                "contradictions": insight.times_contradicted,
            })

        candidates.sort(key=lambda c: (c["age_days"], -c["effective_reliability"]), reverse=True)
        return candidates[: max(0, int(limit or 0))]

    def _topic_key(self, insight: CognitiveInsight) -> str:
        """Group insights into topics for conflict resolution."""
        stop = {
            "the", "a", "an", "and", "or", "but", "if", "then", "so", "to",
            "of", "in", "on", "for", "with", "by", "is", "are", "was", "were",
            "be", "been", "being", "i", "you", "we", "they", "it", "this", "that",
        }
        words = re.split(r"\W+", (insight.insight or "").lower())
        words = [w for w in words if w and w not in stop]
        key = " ".join(words[:6]) if words else (insight.insight or "")
        return f"{insight.category.value}:{key[:80]}"

    def resolve_conflicts(self, insights: List[CognitiveInsight]) -> List[CognitiveInsight]:
        """Choose best insight per topic based on effective reliability and recency."""
        grouped: Dict[str, List[CognitiveInsight]] = {}
        for ins in insights:
            grouped.setdefault(self._topic_key(ins), []).append(ins)

        resolved: List[CognitiveInsight] = []
        for _, items in grouped.items():
            def score(i: CognitiveInsight) -> float:
                eff = self.effective_reliability(i)
                recency = max(0.0, 1.0 - (self._age_days(i) / 365.0))
                return eff + (0.05 * i.times_validated) + (0.1 * recency)

            resolved.append(max(items, key=score))

        return resolved

    def get_ranked_insights(
        self,
        min_reliability: float = 0.7,
        min_validations: int = 3,
        limit: int = 12,
        resolve_conflicts: bool = True,
        source: str = "",
    ) -> List[CognitiveInsight]:
        """Return insights ranked by effective reliability with decay + conflicts.

        If source is specified, only return insights from that adapter
        (e.g. "openclaw", "cursor", "windsurf").
        """
        eligible = []
        for ins in self.insights.values():
            if ins.times_validated < min_validations:
                continue
            if self.effective_reliability(ins) < min_reliability:
                continue
            if source and getattr(ins, "source", "") and getattr(ins, "source", "") != source:
                continue
            eligible.append(ins)

        if resolve_conflicts:
            eligible = self.resolve_conflicts(eligible)

        eligible.sort(
            key=lambda i: (self.effective_reliability(i), i.times_validated, i.confidence),
            reverse=True,
        )
        return eligible[: max(0, int(limit or 0))]

    def dedupe_signals(self) -> Dict[str, int]:
        """Consolidate duplicate signal entries.

        Merges entries like 'signal:Heavy Bash usage (42 calls)' and
        'signal:Heavy Bash usage (5 calls)' into a single normalized entry.

        Returns dict of {normalized_key: merged_count}
        """
        # Find all signal keys (they start with "signal:" or "context:signal:")
        signal_keys = [k for k in self.insights.keys() if "signal:" in k.lower()]

        # Group by normalized key
        groups: Dict[str, List[str]] = {}
        for key in signal_keys:
            # Extract the signal part after "signal:"
            parts = key.split("signal:", 1)
            if len(parts) < 2:
                continue
            signal_part = parts[1]
            normalized = _normalize_signal(signal_part)
            # Use simple normalized key format
            norm_key = f"signal:{normalized}"

            if norm_key not in groups:
                groups[norm_key] = []
            groups[norm_key].append(key)

        merged_counts = {}
        removed_keys: set = set()
        for norm_key, keys in groups.items():
            if len(keys) <= 1:
                continue  # No duplicates

            # Merge all duplicates into the normalized key
            all_evidence: List[Any] = []
            total_validated = 0
            total_contradicted = 0
            earliest_created = None
            base_insight = None

            for key in keys:
                if key not in self.insights:
                    continue
                ins = self.insights[key]
                all_evidence.extend(ins.evidence)
                total_validated += ins.times_validated
                total_contradicted += ins.times_contradicted
                if earliest_created is None or ins.created_at < earliest_created:
                    earliest_created = ins.created_at
                if base_insight is None:
                    base_insight = ins

            if base_insight is None:
                continue

            # Create/update the normalized entry
            merged = CognitiveInsight(
                category=CognitiveCategory.CONTEXT,
                insight=base_insight.insight,
                evidence=list(dict.fromkeys(_flatten_evidence(all_evidence)))[-10:],  # Dedupe and keep last 10
                confidence=_boost_confidence(0.6, len(keys) + total_validated),
                context=base_insight.context,
                counter_examples=base_insight.counter_examples,
                created_at=earliest_created or base_insight.created_at,
                # Keep original totals; dedupe itself is not a true validation.
                times_validated=total_validated,
                times_contradicted=total_contradicted,
                promoted=base_insight.promoted,
                promoted_to=base_insight.promoted_to,
            )

            # Remove old duplicates, add merged
            for key in keys:
                if key in self.insights:
                    del self.insights[key]
                    removed_keys.add(key)

            self.insights[norm_key] = merged
            merged_counts[norm_key] = len(keys)

        if merged_counts:
            self._save_insights(drop_keys=removed_keys)

        return merged_counts

    def dedupe_struggles(self) -> Dict[str, int]:
        """Consolidate duplicate struggle insights (recovered X% variants).

        Returns dict of {normalized_key: merged_count}.
        """
        struggle_keys = [
            k for k, v in self.insights.items()
            if v.category == CognitiveCategory.SELF_AWARENESS and "struggle:" in k.lower()
        ]

        groups: Dict[str, List[str]] = {}
        for key in struggle_keys:
            ins = self.insights.get(key)
            if not ins:
                continue
            norm = _normalize_struggle_key(ins.insight or "")
            if not norm:
                continue
            norm_key = f"{CognitiveCategory.SELF_AWARENESS.value}:struggle:{norm[:50]}"
            groups.setdefault(norm_key, []).append(key)

        merged_counts: Dict[str, int] = {}
        removed_keys: set = set()
        for norm_key, keys in groups.items():
            if len(keys) <= 1:
                continue

            all_evidence = []
            total_validated = 0
            total_contradicted = 0
            earliest_created = None
            latest_validated = None
            base_insight = None

            for key in keys:
                ins = self.insights.get(key)
                if not ins:
                    continue
                all_evidence.extend(ins.evidence)
                total_validated += ins.times_validated
                total_contradicted += ins.times_contradicted
                if earliest_created is None or ins.created_at < earliest_created:
                    earliest_created = ins.created_at
                if ins.last_validated_at:
                    if latest_validated is None or ins.last_validated_at > latest_validated:
                        latest_validated = ins.last_validated_at
                if base_insight is None or ins.times_validated > base_insight.times_validated:
                    base_insight = ins

            if base_insight is None:
                continue

            merged = CognitiveInsight(
                category=CognitiveCategory.SELF_AWARENESS,
                insight=_normalize_struggle_text(base_insight.insight),
                evidence=list(dict.fromkeys(_flatten_evidence(all_evidence)))[-10:],
                confidence=max(base_insight.confidence, 0.5),
                context=base_insight.context,
                counter_examples=base_insight.counter_examples,
                created_at=earliest_created or base_insight.created_at,
                times_validated=total_validated,
                times_contradicted=total_contradicted,
                promoted=base_insight.promoted,
                promoted_to=base_insight.promoted_to,
                last_validated_at=latest_validated,
            )

            for key in keys:
                if key in self.insights:
                    del self.insights[key]
                    removed_keys.add(key)

            self.insights[norm_key] = merged
            merged_counts[norm_key] = len(keys)

        if merged_counts:
            self._save_insights(drop_keys=removed_keys)

        return merged_counts

    def promote_to_wisdom(self) -> Dict[str, int]:
        """Promote high-confidence insights to WISDOM category.

        Scans insights with 10+ validations and 85%+ reliability.
        Skips already-wisdom insights and Spark-internal meta-learning noise.
        """
        stats = {"scanned": 0, "promoted": 0}
        changed = False

        for key, insight in list(self.insights.items()):
            stats["scanned"] += 1

            # Already wisdom
            if insight.category == CognitiveCategory.WISDOM:
                continue

            # Skip meta-learning about Spark internals
            low = insight.insight.lower()
            if any(marker in low for marker in [
                "[system gap]", "auto-tuner", "tuneables", "meta-ralph",
                "bridge_cycle", "cognitive_learner", "pipeline health",
            ]):
                continue

            # Check thresholds
            total = insight.times_validated + insight.times_contradicted
            if insight.times_validated < 10 or total < 10:
                continue
            reliability = insight.times_validated / total if total else 0
            if reliability < 0.85:
                continue

            # Promote
            insight.category = CognitiveCategory.WISDOM
            changed = True
            stats["promoted"] += 1

        if changed:
            self._save_insights()

        return stats


# ============= Singleton =============
_cognitive_learner: Optional[CognitiveLearner] = None

def get_cognitive_learner() -> CognitiveLearner:
    """Get the global cognitive learner instance."""
    global _cognitive_learner
    if _cognitive_learner is None:
        _cognitive_learner = CognitiveLearner()
    return _cognitive_learner
