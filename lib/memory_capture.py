"""Memory capture engine (portable, lightweight)

Goal
----
Turn high-signal conversational statements into durable Spark learnings *without*
platform coupling.

Design constraints
------------------
- Works from normalized SparkEventV1 payloads stored in the existing queue.
- No LLM required (fast, deterministic).
- Adapters can optionally send explicit intent events:
    kind=command, payload.intent="remember"
- Otherwise we use heuristic detection (keywords + emphasis signals).

This module is intentionally pure + testable:
- input: Spark queue events (SparkEvent)
- output: either committed learnings or pending suggestions

"""

from __future__ import annotations

import json
import re
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib.cognitive_learner import CognitiveCategory, get_cognitive_learner
from lib.config_authority import resolve_section
from lib.queue import read_recent_events, EventType
from lib.memory_banks import store_memory
from lib.outcome_log import append_outcome, make_outcome_id
from lib.outcome_checkin import record_checkin_request


PENDING_DIR = Path.home() / ".spark"
PENDING_FILE = PENDING_DIR / "pending_memory.json"
STATE_FILE = PENDING_DIR / "memory_capture_state.json"
TUNEABLES_FILE = Path.home() / ".spark" / "tuneables.json"
MAX_CAPTURE_CHARS = 2000
CONTEXT_CAPTURE_CHARS = 320


# -----------------------------
# Scoring / Heuristics
# -----------------------------

HARD_TRIGGERS = {
    "remember this": 1.0,
    "don\u2019t forget": 0.95,
    "dont forget": 0.95,
    "note this": 0.9,
    "save this": 0.9,
    "lock this in": 0.95,
    "non-negotiable": 0.95,
    "hard rule": 0.95,
    "hard boundary": 0.95,
    "from now on": 0.85,
    "always": 0.65,
    "never": 0.65,
}

SOFT_TRIGGERS = {
    "i prefer": 0.55,
    "i hate": 0.75,
    "i don\u2019t like": 0.65,
    "i dont like": 0.65,
    "i need": 0.5,
    "i want": 0.5,
    "we should": 0.45,
    "design constraint": 0.65,
    "default": 0.4,
    "compatibility": 0.35,
    "adaptability": 0.35,
    "should": 0.25,
    "must": 0.4,
    "non-negotiable": 0.55,
    "for this project": 0.65,
}

DECISION_MARKERS = {
    "let's do it": 0.25,
    "lets do it": 0.25,
    "ship it": 0.25,
    "do it": 0.15,
}
_DECISION_EXTRA = {
    "launch",
    "greenlight",
    "approved",
    "go with",
    "move forward",
}

_CAPTURE_NOISE_PATTERNS = (
    re.compile(r"you are spark intelligence, observing a live coding session", re.I),
    re.compile(r"system inventory \(what actually exists", re.I),
    re.compile(r"<task-notification>|<task-id>|<output-file>|<status>|<summary>", re.I),
    re.compile(r"\n\s*- services:\s", re.I),
    re.compile(r"^#\s*provider prompt", re.I),
    re.compile(r"\bmission id:\b|\bassigned tasks:\b|\bexecution expectations:\b", re.I),
    re.compile(r"\bh70 skill loading\b|\bmission completion gate\b", re.I),
    re.compile(r"\bcurl\s+-x\s+post\s+http://127\.0\.0\.1:\d+/api/events\b", re.I),
    re.compile(r"^\s*evidence\s*:", re.I),
)
_INLINE_NOISE_FIELD_RE = re.compile(r"\b(event_type|tool_name|file_path|cwd)\s*:\s*\S+", re.I)

_CAPTURE_META_LINE_RE = re.compile(
    r"^\s*(mission|mission id|provider|model|role|strategy|priority|importance|task id|task name|"
    r"source|progress|kpi|intent|mcp plan|execution expectations|verification)\s*[:=]",
    re.I,
)

_SIGNAL_HINT_RE = re.compile(
    r"\b(should|must|because|prefer|decision|fix|ship|regression|bug|test|quality|confidence)\b",
    re.I,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\s*[;|]\s+")
_SEMANTIC_SUMMARY_RE = re.compile(
    r"\b(because|so that|therefore|hence|prefer|must|should|avoid|trade-?off|"
    r"threshold|confidence|quality|latency|impact|decision)\b",
    re.I,
)


def _is_noise_line(text: str) -> bool:
    line = str(text or "").strip()
    if not line:
        return True
    if _INLINE_NOISE_FIELD_RE.search(line):
        residual = _INLINE_NOISE_FIELD_RE.sub(" ", line)
        residual = re.sub(r"\s+", " ", residual).strip(" -:;|")
        if len(residual) < 20:
            return True
    if _CAPTURE_META_LINE_RE.search(line):
        return True
    return any(rx.search(line) for rx in _CAPTURE_NOISE_PATTERNS)


def _strip_inline_noise_tokens(text: str) -> str:
    cleaned = _INLINE_NOISE_FIELD_RE.sub(" ", str(text or ""))
    cleaned = re.sub(r"<task-notification>|<task-id>|<output-file>|<status>|<summary>", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:;|")
    return cleaned


def _noise_line_stats(text: str) -> Tuple[int, int, int]:
    total = 0
    noise = 0
    signal = 0
    for raw in str(text or "").splitlines():
        line = _strip_inline_noise_tokens(raw.strip())
        if not line:
            continue
        total += 1
        if _is_noise_line(line):
            noise += 1
            continue
        if _SIGNAL_HINT_RE.search(line):
            signal += 1
    return noise, total, signal


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _is_decision_text(text: str) -> bool:
    t = _norm(text)
    for k in DECISION_MARKERS:
        if k in t:
            return True
    for k in _DECISION_EXTRA:
        if k in t:
            return True
    return False


def _is_capture_noise(text: str) -> bool:
    sample = str(text or "").strip()
    if not sample:
        return True
    sample_clean = _strip_inline_noise_tokens(sample)
    if not sample_clean:
        return True
    if any(rx.search(sample_clean) for rx in _CAPTURE_NOISE_PATTERNS):
        return True
    noise_lines, total_lines, signal_lines = _noise_line_stats(sample_clean)
    if total_lines >= 4 and noise_lines / max(1, total_lines) >= 0.55 and signal_lines <= 1:
        return True
    if total_lines >= 8 and noise_lines >= 6:
        return True
    return False


def _compact_context_snippet(text: str, *, max_chars: int) -> str:
    """Keep semantically useful context while dropping noisy scaffolding."""
    sample = str(text or "")
    lines: List[str] = []
    for raw in sample.splitlines():
        line = _strip_inline_noise_tokens(raw.strip())
        if not line:
            continue
        if _is_noise_line(line):
            continue
        lines.append(line)
    if not lines:
        return ""
    compact = " ".join(lines)
    compact = re.sub(r"\s+", " ", compact).strip()
    if not compact:
        return ""
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(compact) if p.strip()]
    if parts:
        scored: List[Tuple[float, int, str]] = []
        for idx, part in enumerate(parts):
            score = 0.0
            if _SEMANTIC_SUMMARY_RE.search(part):
                score += 1.2
            if _SIGNAL_HINT_RE.search(part):
                score += 0.8
            if re.search(r"\b\d+(\.\d+)?%?\b", part):
                score += 0.4
            if 24 <= len(part) <= 220:
                score += 0.2
            scored.append((score, idx, part))
        keep_n = min(4, len(scored))
        top = sorted(scored, key=lambda item: (item[0], -item[1]), reverse=True)[:keep_n]
        top_idx = {idx for _, idx, _ in top}
        summary_parts = [part for idx, part in enumerate(parts) if idx in top_idx]
        if summary_parts:
            compact = " ".join(summary_parts)
    compact = re.sub(r"\s+", " ", compact).strip()
    if len(compact) > max_chars:
        compact = compact[:max_chars].rstrip()
    return compact


def infer_category(text: str) -> CognitiveCategory:
    t = _norm(text)
    if any(k in t for k in ["security", "boundary", "non-negotiable", "hard rule"]):
        return CognitiveCategory.META_LEARNING
    if any(k in t for k in ["prefer", "hate", "don't like", "dont like", "love"]):
        return CognitiveCategory.USER_UNDERSTANDING
    if any(k in t for k in ["tone", "be direct", "no sugarcoating", "explain"]):
        return CognitiveCategory.COMMUNICATION
    if any(k in t for k in ["principle", "philosophy", "rule", "design constraint", "architecture", "compatibility", "adaptability"]):
        return CognitiveCategory.WISDOM
    return CognitiveCategory.META_LEARNING


def importance_score(text: str) -> Tuple[float, Dict[str, float]]:
    """Return (score 0..1, breakdown)."""
    t = _norm(text)
    breakdown: Dict[str, float] = {}

    def apply(phrases: Dict[str, float], bucket: str):
        s = 0.0
        for p, w in phrases.items():
            if p in t:
                s = max(s, w)  # strongest match wins
        if s:
            breakdown[bucket] = s
        return s

    score = 0.0
    score = max(score, apply(HARD_TRIGGERS, "hard_trigger"))
    score = max(score, apply(SOFT_TRIGGERS, "soft_trigger"))
    score = max(score, apply(DECISION_MARKERS, "decision_marker"))

    # Emphasis signals (cheap but useful)
    if re.search(r"\b(must|nonnegotiable|non-negotiable|critical|important)\b", t):
        breakdown["emphasis"] = max(breakdown.get("emphasis", 0.0), 0.2)
        score = min(1.0, score + 0.2)

    # ALL CAPS word emphasis
    if re.search(r"\b[A-Z]{4,}\b", (text or "")):
        breakdown["caps"] = max(breakdown.get("caps", 0.0), 0.1)
        score = min(1.0, score + 0.1)

    # Length heuristic: longer statements more likely to be principles
    if len((text or "").strip()) > 180:
        breakdown["length"] = max(breakdown.get("length", 0.0), 0.05)
        score = min(1.0, score + 0.05)

    # --- Semantic signals (catch useful content without trigger phrases) ---
    # These signals COMBINE: causal + quant + tech together can reach threshold

    semantic_sum = 0.0

    # Causal language: explains WHY something works
    causal_score = 0.0
    if re.search(r"\b(because|due to|causes|leads to|results in|since|the reason)\b", t):
        causal_score = 0.30
    elif re.search(r"\b(so that|in order to|prevents|ensures|helps|improves|reduces)\b", t):
        causal_score = 0.20
    elif re.search(r"\b(tends? to|generally|typically|usually|often leads|commonly|in practice)\b", t):
        causal_score = 0.15
    if causal_score:
        breakdown["causal"] = causal_score
        semantic_sum += causal_score

    # Quantitative evidence: numbers suggest data-backed insights
    quant_score = 0.0
    if re.search(r"\d+\.?\d*\s*(%|percent|ms|seconds?|s\b|mb|gb|kb|fps|rpm|req|tps|x faster|x slower|x more|x less|x reduction|x improvement)", t, re.IGNORECASE):
        quant_score = 0.30
    elif re.search(r"\bfrom\s+\d+\.?\d*\S*\s+to\s+\d+", t):
        quant_score = 0.30  # "from 4.2s to 1.6s" pattern
    elif re.search(r"\b\d{2,}\b", t) and re.search(r"\b(avg|average|median|reduced|increased|improved|from|to)\b", t):
        quant_score = 0.25
    if quant_score:
        breakdown["quantitative"] = quant_score
        semantic_sum += quant_score

    # Comparative language: preference/evaluation with specifics
    compare_score = 0.0
    if re.search(r"\b(better than|worse than|instead of|prefer .+ over|outperforms|compared to|rather than)\b", t):
        compare_score = 0.25
    elif re.search(r"\b(faster|slower|simpler|safer|cleaner|more reliable|less error|more \w+ than)\b", t):
        compare_score = 0.15
    if compare_score:
        breakdown["comparative"] = compare_score
        semantic_sum += compare_score

    # Technical specificity: named frameworks, patterns, or techniques
    tech_score = 0.0
    tech_hits = len(re.findall(
        r"\b(React|Vue|Svelte|Angular|Next\.?js|Express|FastAPI|Django|Flask|"
        r"bcrypt|argon2|JWT|OAuth|PKCE|OIDC|"
        r"SQL|NoSQL|Redis|Memcached|Elasticsearch|"
        r"Docker|Kubernetes|Terraform|Ansible|"
        r"CI/CD|GitHub.?Actions|Jenkins|ArgoCD|"
        r"webpack|vite|esbuild|rollup|"
        r"TypeScript|Python|Rust|"
        r"useEffect|useState|useMemo|useCallback|React\.memo|"
        r"middleware|endpoint|schema|migrat\w*|"
        r"async|await|promise|callback|hook|component|reducer|"
        r"lazy.?load\w*|memoiz\w*|debounc\w*|throttl\w*|cach\w+|index\w*|partition\w*|"
        r"rate.?limit\w*|CORS|CSRF|XSS|CSP|OWASP|inject\w*|sanitiz\w*|"
        r"connection.?pool\w*|multi.?stage|canary|rolling|blue.?green|"
        r"circuit.?breaker|dead.?letter|retr\w+|backoff|idempoten\w*|"
        r"PostgreSQL|MySQL|MongoDB|SQLite|"
        r"SQS|SNS|Lambda|S3|EC2|ECS|"
        r"Datadog|Sentry|Pino|Winston|"
        r"Prisma|Drizzle|Sequelize|"
        r"dbt|Airflow|Spark|Kafka|RabbitMQ|"
        r"PgBouncer|Nginx|HAProxy|CDN|"
        r"BVH|ECS|GC|FPS|LCP|FCP|INP|CLS)\b", t, re.IGNORECASE
    ))
    if tech_hits >= 3:
        tech_score = 0.30
    elif tech_hits >= 2:
        tech_score = 0.22
    elif tech_hits >= 1:
        tech_score = 0.15
    if tech_score:
        breakdown["technical"] = tech_score
        semantic_sum += tech_score

    # Actionable language: concrete instruction or recommendation
    action_score = 0.0
    if re.search(r"\b(always|never|avoid\w*|make sure|ensure|check\w*|verify|consider\w*|us(?:e|ing|ed)|implement\w*|add\w*|set\w*|configur\w*)\b", t):
        action_score = 0.15
    if action_score:
        breakdown["actionable"] = action_score
        semantic_sum += action_score

    # Apply semantic sum (signals stack additively)
    if semantic_sum > 0:
        score = max(score, min(1.0, semantic_sum))

    return float(min(1.0, score)), breakdown


# -----------------------------
# Pending suggestions storage
# -----------------------------

@dataclass
class MemorySuggestion:
    suggestion_id: str
    created_at: float
    session_id: str
    text: str
    category: str
    score: float
    breakdown: Dict[str, float]
    status: str = "pending"  # pending|accepted|rejected|auto_saved

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "created_at": self.created_at,
            "session_id": self.session_id,
            "text": self.text,
            "category": self.category,
            "score": self.score,
            "breakdown": self.breakdown,
            "status": self.status,
        }


def _load_pending() -> Dict[str, Any]:
    if not PENDING_FILE.exists():
        return {"items": []}
    try:
        return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"items": []}


def _save_pending(d: Dict[str, Any]) -> None:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(d, indent=2, sort_keys=True), encoding="utf-8")


def _state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(d: Dict[str, Any]) -> None:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(d, indent=2, sort_keys=True), encoding="utf-8")


def _make_id(session_id: str, text: str) -> str:
    raw = f"{session_id}|{_norm(normalize_memory_text(text))}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:10]


# -----------------------------
# Core processing
# -----------------------------

AUTO_SAVE_THRESHOLD = 0.72
SUGGEST_THRESHOLD = 0.60


_REMEMBER_PREFIX_RE = re.compile(r"^\s*(remember this|note this|save this)\s*:\s*", re.IGNORECASE)
_MESSAGE_ID_LINE_RE = re.compile(r"\n?\[message_id:.*?\]\s*$", re.IGNORECASE | re.DOTALL)
# Clawdbot transcript prefix, e.g. "[Telegram Meta ...] "
_CHANNEL_PREFIX_RE = re.compile(r"^\s*\[[^\]]+\]\s*", re.IGNORECASE)


def _load_memory_capture_config() -> Dict[str, Any]:
    resolved = resolve_section("memory_capture", runtime_path=TUNEABLES_FILE)
    return resolved.data if isinstance(resolved.data, dict) else {}


def _apply_memory_capture_config(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    global AUTO_SAVE_THRESHOLD
    global SUGGEST_THRESHOLD
    global MAX_CAPTURE_CHARS
    global CONTEXT_CAPTURE_CHARS

    applied: List[str] = []
    warnings: List[str] = []
    if not isinstance(cfg, dict):
        return {"applied": applied, "warnings": warnings}

    if "auto_save_threshold" in cfg:
        try:
            AUTO_SAVE_THRESHOLD = max(0.1, min(1.0, float(cfg.get("auto_save_threshold") or 0.1)))
            applied.append("auto_save_threshold")
        except Exception:
            warnings.append("invalid_auto_save_threshold")

    if "suggest_threshold" in cfg:
        try:
            SUGGEST_THRESHOLD = max(0.05, min(0.99, float(cfg.get("suggest_threshold") or 0.05)))
            applied.append("suggest_threshold")
        except Exception:
            warnings.append("invalid_suggest_threshold")

    if "max_capture_chars" in cfg:
        try:
            MAX_CAPTURE_CHARS = max(200, min(20000, int(cfg.get("max_capture_chars") or 200)))
            applied.append("max_capture_chars")
        except Exception:
            warnings.append("invalid_max_capture_chars")

    if "context_capture_chars" in cfg:
        try:
            CONTEXT_CAPTURE_CHARS = max(80, min(2000, int(cfg.get("context_capture_chars") or 80)))
            applied.append("context_capture_chars")
        except Exception:
            warnings.append("invalid_context_capture_chars")

    if SUGGEST_THRESHOLD > AUTO_SAVE_THRESHOLD:
        SUGGEST_THRESHOLD = max(0.05, AUTO_SAVE_THRESHOLD - 0.05)
        warnings.append("suggest_threshold_auto_adjusted")

    return {"applied": applied, "warnings": warnings}


def apply_memory_capture_config(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    return _apply_memory_capture_config(cfg)


def get_memory_capture_config() -> Dict[str, Any]:
    return {
        "auto_save_threshold": float(AUTO_SAVE_THRESHOLD),
        "suggest_threshold": float(SUGGEST_THRESHOLD),
        "max_capture_chars": int(MAX_CAPTURE_CHARS),
        "context_capture_chars": int(CONTEXT_CAPTURE_CHARS),
    }


def _reload_memory_capture_config(_cfg: Dict[str, Any]) -> None:
    _apply_memory_capture_config(_load_memory_capture_config())


_apply_memory_capture_config(_load_memory_capture_config())
try:
    from lib.tuneables_reload import register_reload as _register_memory_capture_reload

    _register_memory_capture_reload(
        "memory_capture",
        _reload_memory_capture_config,
        label="memory_capture.reload_from",
    )
except Exception:
    pass


def normalize_memory_text(text: str) -> str:
    t = (text or "").strip()
    t = _CHANNEL_PREFIX_RE.sub("", t)
    t = _REMEMBER_PREFIX_RE.sub("", t)
    t = _MESSAGE_ID_LINE_RE.sub("", t).strip()
    if len(t) > MAX_CAPTURE_CHARS:
        t = t[:MAX_CAPTURE_CHARS].rstrip()
    return t


def commit_learning(
    text: str,
    category: CognitiveCategory,
    context: str = "",
    session_id: str = "",
    trace_id: Optional[str] = None,
) -> bool:
    try:
        clean = normalize_memory_text(text)
        if not clean:
            return False
        if len(clean) > MAX_CAPTURE_CHARS:
            clean = clean[:MAX_CAPTURE_CHARS].rstrip()
        if _is_capture_noise(clean):
            return False
        # Use a compact context snippet so retrieval has useful grounding.
        ctx = _compact_context_snippet((context or clean), max_chars=CONTEXT_CAPTURE_CHARS)
        if not ctx:
            ctx = clean[:CONTEXT_CAPTURE_CHARS]
        # Route through unified validation (Meta-Ralph + noise filter).
        from lib.validate_and_store import validate_and_store_insight
        validate_and_store_insight(
            text=clean, category=category, context=ctx,
            confidence=0.7, source="memory_capture",
        )

        # Also store into layered memory banks for fast retrieval + future project scoping.
        try:
            store_memory(text=clean, category=category.value, session_id=session_id or None, source="capture")
        except Exception:
            pass
        try:
            if _is_decision_text(clean):
                append_outcome({
                    "outcome_id": make_outcome_id(str(time.time()), "project_decision", clean[:120]),
                    "event_type": "project_decision",
                    "tool": None,
                    "text": f"project decision: {clean[:200]}",
                    "polarity": "pos",
                    "created_at": time.time(),
                    "domain": "project",
                    "session_id": session_id or None,
                    "trace_id": trace_id,
                })
                record_checkin_request(
                    session_id=session_id or "session",
                    event="project_decision",
                    reason=clean[:160],
                )
        except Exception:
            pass

        return True
    except Exception as e:
        import logging
        logging.getLogger("spark.memory_capture").warning("commit_learning failed: %s", e)
        return False


def process_recent_memory_events(limit: int = 50) -> Dict[str, Any]:
    """Scan recent queue events and generate suggestions / auto-saves.

    Portable rule: we only use data in Spark queue.

    Returns stats for observability.
    """

    st = _state()
    last_ts = float(st.get("last_ts", 0.0))

    events = read_recent_events(limit)

    pending = _load_pending()
    items: List[Dict[str, Any]] = list(pending.get("items", []))
    existing_ids = {i.get("suggestion_id") for i in items}

    auto_saved = 0
    suggested = 0
    explicit_saved = 0

    max_seen_ts = last_ts

    for e in events:
        max_seen_ts = max(max_seen_ts, float(e.timestamp or 0.0))
        if float(e.timestamp or 0.0) <= last_ts:
            continue

        # We only understand SparkEventV1 shaped payloads via sparkd ingest
        payload = (e.data or {}).get("payload") or {}

        trace_id = (e.data or {}).get("trace_id") if hasattr(e, "data") else None
        if not trace_id and isinstance(payload, dict):
            trace_id = payload.get("trace_id")

        # 1) Explicit intent events (best compatibility)
        if e.event_type == EventType.LEARNING and payload.get("intent") == "remember":
            txt = str(payload.get("text") or "").strip()
            if not txt:
                continue
            cat = payload.get("category")
            try:
                category = CognitiveCategory(str(cat)) if cat else infer_category(txt)
            except Exception:
                category = infer_category(txt)

            ok = commit_learning(
                txt,
                category,
                context="explicit remember intent",
                session_id=e.session_id,
                trace_id=trace_id,
            )
            if ok:
                explicit_saved += 1
            continue

        # 2) Keyword/heuristic from user messages
        if e.event_type != EventType.USER_PROMPT:
            continue

        role = str(payload.get("role") or "user")
        if role != "user":
            continue

        txt = str(payload.get("text") or "").strip()
        if not txt:
            continue
        if _is_capture_noise(txt):
            continue
        if len(txt) > MAX_CAPTURE_CHARS:
            txt = txt[:MAX_CAPTURE_CHARS].rstrip()

        score, breakdown = importance_score(txt)
        if score < SUGGEST_THRESHOLD:
            continue

        # Dedupe: avoid storing the same preference repeatedly (even across sessions)
        norm_txt = normalize_memory_text(txt)
        if not norm_txt:
            continue

        suggestion_id = _make_id(e.session_id, norm_txt)
        if suggestion_id in existing_ids:
            continue

        category = infer_category(norm_txt)

        sug = MemorySuggestion(
            suggestion_id=suggestion_id,
            created_at=time.time(),
            session_id=e.session_id,
            text=norm_txt,
            category=category.value,
            score=score,
            breakdown=breakdown,
        )

        if score >= AUTO_SAVE_THRESHOLD:
            if commit_learning(
                norm_txt,
                category,
                context="auto-captured from conversation",
                session_id=e.session_id,
                trace_id=trace_id,
            ):
                sug.status = "auto_saved"
                auto_saved += 1
            else:
                sug.status = "pending"
                suggested += 1
        else:
            suggested += 1

        items.append(sug.to_dict())
        existing_ids.add(suggestion_id)

    # keep file small
    items = sorted(items, key=lambda x: x.get("created_at", 0), reverse=True)[:200]
    pending["items"] = items
    _save_pending(pending)

    st["last_ts"] = max_seen_ts
    _save_state(st)

    return {
        "auto_saved": auto_saved,
        "explicit_saved": explicit_saved,
        "suggested": suggested,
        "pending_total": sum(1 for i in items if i.get("status") == "pending"),
    }


def list_pending(limit: int = 20) -> List[Dict[str, Any]]:
    d = _load_pending()
    items = [i for i in d.get("items", []) if i.get("status") == "pending"]
    items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return items[:limit]


def accept_suggestion(suggestion_id: str) -> bool:
    d = _load_pending()
    items = d.get("items", [])
    changed = False
    for it in items:
        if it.get("suggestion_id") == suggestion_id and it.get("status") == "pending":
            txt = it.get("text") or ""
            cat = it.get("category") or "meta_learning"
            try:
                category = CognitiveCategory(str(cat))
            except Exception:
                category = infer_category(txt)
            if commit_learning(str(txt), category, context="accepted memory suggestion"):
                it["status"] = "accepted"
                changed = True
    if changed:
        _save_pending(d)
    return changed


def reject_suggestion(suggestion_id: str) -> bool:
    d = _load_pending()
    items = d.get("items", [])
    changed = False
    for it in items:
        if it.get("suggestion_id") == suggestion_id and it.get("status") == "pending":
            it["status"] = "rejected"
            changed = True
    if changed:
        _save_pending(d)
    return changed
