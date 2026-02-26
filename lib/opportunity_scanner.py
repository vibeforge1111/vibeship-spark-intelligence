"""Opportunity Scanner for Spark self-evolution.

MIGRATION NOTE (2026-02-22): This module is being migrated to
spark-learning-systems (system 27-opportunity-scanner). Use
lib.opportunity_scanner_adapter for imports — it provides a seamless
fallback to this local module until the external package is ready.

Default behavior is self-Socratic:
1) Runtime self-scan identifies Spark improvement opportunities from active work.
2) User-facing Socratic questions are optional and disabled by default.

Both paths enforce anti-telemetry filtering and consciousness guardrails.
"""

from __future__ import annotations

import json
import os
import re
import hashlib
import time
import configparser
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .diagnostics import log_debug
from .primitive_filter import is_primitive_text
from .soul_upgrade import fetch_soul_state, soul_kernel_pass


SCANNER_ENABLED: bool = True
SELF_MAX_ITEMS: int = 3
USER_MAX_ITEMS: int = 2
MAX_HISTORY_LINES: int = 500
SELF_DEDUP_WINDOW_S: float = 14400.0
SELF_RECENT_LOOKBACK: int = 240
SELF_CATEGORY_CAP: int = 1
USER_SCAN_ENABLED: bool = False
SCAN_EVENT_LIMIT: int = 120

OPPORTUNITY_DIR = Path.home() / ".spark" / "opportunity_scanner"
SELF_FILE = OPPORTUNITY_DIR / "self_opportunities.jsonl"
USER_FILE = OPPORTUNITY_DIR / "user_opportunities.jsonl"
OUTCOME_FILE = OPPORTUNITY_DIR / "outcomes.jsonl"
DECISIONS_FILE = OPPORTUNITY_DIR / "decisions.jsonl"
OUTCOME_WINDOW_S: float = 21600.0
OUTCOME_LOOKBACK: int = 200
PROMOTION_FILE = OPPORTUNITY_DIR / "promoted_opportunities.jsonl"
PROMOTION_MIN_SUCCESSES: int = 2
PROMOTION_MIN_EFFECTIVENESS: float = 0.66
PROMOTION_LOOKBACK: int = 400
LLM_ENABLED: bool = True
LLM_PROVIDER: str = ""
LLM_TIMEOUT_S: float = 2.5
LLM_MAX_ITEMS: int = 3
LLM_MIN_CONTEXT_CHARS: int = 140
LLM_COOLDOWN_S: float = 300.0

_TELEMETRY_MARKERS = (
    "tool_",
    "_error",
    "trace_id",
    "event_type:",
    "post_tool",
    "pre_tool",
    "status code",
    "heartbeat",
    "queue/events.jsonl",
    "pid=",
    "request failed",
)
_STRATEGIC_MARKERS = (
    "improve",
    "better",
    "opportunity",
    "evolve",
    "strategy",
    "goal",
    "plan",
    "roadmap",
    "launch",
    "scale",
    "growth",
    "autonomy",
)
_HIGH_IMPACT_TOOLS = {"task", "edit", "write", "bash", "askuser"}
_SELF_CATEGORY_ALLOWLIST = {
    "verification_gap",
    "outcome_clarity",
    "assumption_audit",
    "reversibility",
    "humanity_guardrail",
    "compounding_learning",
}
_FORBIDDEN_LLM_PROVIDERS = {"deepseek", "deep-seek"}
_LAST_LLM_ATTEMPT_BY_KEY: Dict[str, float] = {}

_DECISION_LOOKBACK: int = 500
_DISMISS_TTL_S: float = 604800.0

_GIT_ROOT_CACHE: Dict[str, str] = {}
_GIT_ORIGIN_CACHE: Dict[str, str] = {}


def _load_scanner_config() -> None:
    """Load opportunity scanner config via config-authority."""
    global SCANNER_ENABLED, SELF_MAX_ITEMS, USER_MAX_ITEMS, MAX_HISTORY_LINES
    global SELF_DEDUP_WINDOW_S, SELF_RECENT_LOOKBACK, SELF_CATEGORY_CAP
    global USER_SCAN_ENABLED, SCAN_EVENT_LIMIT
    global OUTCOME_WINDOW_S, OUTCOME_LOOKBACK
    global PROMOTION_MIN_SUCCESSES, PROMOTION_MIN_EFFECTIVENESS, PROMOTION_LOOKBACK
    global LLM_ENABLED, LLM_PROVIDER, LLM_TIMEOUT_S, LLM_MAX_ITEMS
    global LLM_MIN_CONTEXT_CHARS, LLM_COOLDOWN_S
    global _DECISION_LOOKBACK, _DISMISS_TTL_S
    try:
        from .config_authority import resolve_section, env_bool, env_int, env_float, env_str
        cfg = resolve_section(
            "opportunity_scanner",
            env_overrides={
                "enabled": env_bool("SPARK_OPPORTUNITY_SCANNER"),
                "self_max_items": env_int("SPARK_OPPORTUNITY_SELF_MAX"),
                "user_max_items": env_int("SPARK_OPPORTUNITY_USER_MAX"),
                "max_history_lines": env_int("SPARK_OPPORTUNITY_HISTORY_MAX"),
                "self_dedup_window_s": env_float("SPARK_OPPORTUNITY_SELF_DEDUP_WINDOW_S"),
                "self_recent_lookback": env_int("SPARK_OPPORTUNITY_SELF_RECENT_LOOKBACK"),
                "self_category_cap": env_int("SPARK_OPPORTUNITY_SELF_CATEGORY_CAP"),
                "user_scan_enabled": env_bool("SPARK_OPPORTUNITY_USER_SCAN"),
                "scan_event_limit": env_int("SPARK_OPPORTUNITY_SCAN_EVENT_LIMIT"),
                "outcome_window_s": env_float("SPARK_OPPORTUNITY_OUTCOME_WINDOW_S"),
                "outcome_lookback": env_int("SPARK_OPPORTUNITY_OUTCOME_LOOKBACK"),
                "promotion_min_successes": env_int("SPARK_OPPORTUNITY_PROMOTION_MIN_SUCCESSES"),
                "promotion_min_effectiveness": env_float("SPARK_OPPORTUNITY_PROMOTION_MIN_EFFECTIVENESS"),
                "promotion_lookback": env_int("SPARK_OPPORTUNITY_PROMOTION_LOOKBACK"),
                "llm_enabled": env_bool("SPARK_OPPORTUNITY_LLM_ENABLED"),
                "llm_provider": env_str("SPARK_OPPORTUNITY_LLM_PROVIDER"),
                "llm_timeout_s": env_float("SPARK_OPPORTUNITY_LLM_TIMEOUT_S"),
                "llm_max_items": env_int("SPARK_OPPORTUNITY_LLM_MAX_ITEMS"),
                "llm_min_context_chars": env_int("SPARK_OPPORTUNITY_LLM_MIN_CONTEXT_CHARS"),
                "llm_cooldown_s": env_float("SPARK_OPPORTUNITY_LLM_COOLDOWN_S"),
                "decision_lookback": env_int("SPARK_OPPORTUNITY_DECISION_LOOKBACK"),
                "dismiss_ttl_s": env_float("SPARK_OPPORTUNITY_DISMISS_TTL_S"),
            },
        ).data
        SCANNER_ENABLED = bool(cfg.get("enabled", True))
        SELF_MAX_ITEMS = int(cfg.get("self_max_items", 3))
        USER_MAX_ITEMS = int(cfg.get("user_max_items", 2))
        MAX_HISTORY_LINES = int(cfg.get("max_history_lines", 500))
        SELF_DEDUP_WINDOW_S = float(cfg.get("self_dedup_window_s", 14400.0))
        SELF_RECENT_LOOKBACK = int(cfg.get("self_recent_lookback", 240))
        SELF_CATEGORY_CAP = int(cfg.get("self_category_cap", 1))
        USER_SCAN_ENABLED = bool(cfg.get("user_scan_enabled", False))
        SCAN_EVENT_LIMIT = int(cfg.get("scan_event_limit", 120))
        OUTCOME_WINDOW_S = float(cfg.get("outcome_window_s", 21600.0))
        OUTCOME_LOOKBACK = int(cfg.get("outcome_lookback", 200))
        PROMOTION_MIN_SUCCESSES = int(cfg.get("promotion_min_successes", 2))
        PROMOTION_MIN_EFFECTIVENESS = float(cfg.get("promotion_min_effectiveness", 0.66))
        PROMOTION_LOOKBACK = int(cfg.get("promotion_lookback", 400))
        LLM_ENABLED = bool(cfg.get("llm_enabled", True))
        LLM_PROVIDER = str(cfg.get("llm_provider", "")).strip().lower()
        LLM_TIMEOUT_S = float(cfg.get("llm_timeout_s", 2.5))
        LLM_MAX_ITEMS = int(cfg.get("llm_max_items", 3))
        LLM_MIN_CONTEXT_CHARS = int(cfg.get("llm_min_context_chars", 140))
        LLM_COOLDOWN_S = float(cfg.get("llm_cooldown_s", 300.0))
        _DECISION_LOOKBACK = int(cfg.get("decision_lookback", 500))
        _DISMISS_TTL_S = float(cfg.get("dismiss_ttl_s", 604800.0))
    except Exception:
        pass  # keep module-level defaults


# Load on import; hot-reload via tuneables_reload dispatcher
_load_scanner_config()

try:
    from .tuneables_reload import register_reload
    register_reload("opportunity_scanner", lambda _s: _load_scanner_config(), "opportunity_scanner")
except Exception:
    pass


_QUESTION_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "for",
    "in",
    "on",
    "at",
    "is",
    "it",
    "this",
    "that",
    "what",
    "which",
    "how",
    "will",
    "with",
    "before",
    "after",
    "from",
    "should",
    "does",
    "can",
}


def _tail_jsonl(path: Path, max_lines: int) -> List[Dict[str, Any]]:
    if max_lines <= 0 or not path.exists():
        return []
    try:
        rows = []
        for raw in path.read_text(encoding="utf-8").splitlines()[-max_lines:]:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows
    except Exception:
        return []


def _append_jsonl_capped(path: Path, row: Dict[str, Any], max_lines: int = MAX_HISTORY_LINES) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")
        tail = path.read_text(encoding="utf-8").splitlines()[-max_lines:]
        path.write_text("\n".join(tail) + "\n", encoding="utf-8")
    except Exception:
        return


def _is_telemetry_noise(text: str) -> bool:
    if not text:
        return True
    tl = str(text).strip().lower()
    if not tl:
        return True
    if is_primitive_text(tl):
        return True
    if any(marker in tl for marker in _TELEMETRY_MARKERS):
        return True
    if len(tl) < 18:
        return True
    return False


def _event_type_name(ev: Any) -> str:
    et = getattr(ev, "event_type", "")
    if hasattr(et, "value"):
        return str(et.value or "").strip().lower()
    return str(et or "").strip().lower()


def _tool_name(ev: Any) -> str:
    return str(getattr(ev, "tool_name", "") or "").strip().lower()


def _extract_prompt_text(ev: Any) -> str:
    data = getattr(ev, "data", {}) or {}
    payload = data.get("payload") if isinstance(data, dict) else {}
    if isinstance(payload, dict):
        return str(payload.get("text") or "").strip()
    return ""


def _extract_edit_text(ev: Any) -> str:
    tool_input = getattr(ev, "tool_input", {}) or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    data = getattr(ev, "data", {}) or {}
    payload = data.get("payload") if isinstance(data, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    text = (
        tool_input.get("new_string")
        or tool_input.get("content")
        or payload.get("new_string")
        or payload.get("content")
        or ""
    )
    return str(text or "").strip()


def _extract_trace_id(ev: Any) -> str:
    data = getattr(ev, "data", {}) or {}
    if not isinstance(data, dict):
        data = {}
    tid = str(data.get("trace_id") or "").strip()
    if tid:
        return tid
    payload = data.get("payload")
    if isinstance(payload, dict):
        return str(payload.get("trace_id") or "").strip()
    return ""


def _select_primary_trace_id(events: Sequence[Any]) -> str:
    for ev in reversed(list(events or [])):
        tid = _extract_trace_id(ev)
        if tid:
            return tid
    return ""


def _opportunity_id(
    *,
    session_id: str,
    category: str,
    question: str,
    ts: float,
) -> str:
    seed = f"{session_id}|{category}|{question}|{ts:.6f}"
    return f"opp:{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16]}"


def _load_recorded_outcome_ids() -> set[str]:
    rows = _tail_jsonl(OUTCOME_FILE, OUTCOME_LOOKBACK * 3)
    out: set[str] = set()
    for row in rows:
        oid = str(row.get("opportunity_id") or "").strip()
        if oid:
            out.add(oid)
    return out


def _load_promoted_opportunity_keys() -> set[str]:
    rows = _tail_jsonl(PROMOTION_FILE, PROMOTION_LOOKBACK)
    out: set[str] = set()
    for row in rows:
        key = str(row.get("promotion_key") or "").strip()
        if key:
            out.add(key)
    return out


def _evaluate_opportunity_signal(category: str, text: str, stats: Dict[str, Any]) -> tuple[bool, bool, str]:
    cat = str(category or "").strip().lower()
    tl = str(text or "").lower()
    validation = stats.get("validation") if isinstance(stats, dict) else {}
    validation = validation if isinstance(validation, dict) else {}

    if cat == "verification_gap":
        matched = int(validation.get("matched") or 0)
        proved = _mentions_any(tl, ("pytest", "test", "assert", "verified", "validation", "proof", "smoke"))
        improved = bool(proved or matched > 0)
        acted = improved or _mentions_any(tl, ("check", "verify", "run test"))
        evidence = "verification evidence detected" if improved else "verification still weak"
        return acted, improved, evidence

    if cat == "outcome_clarity":
        improved = _mentions_any(tl, ("definition of done", "success criteria", "acceptance", "done when"))
        acted = improved or _mentions_any(tl, ("outcome", "done", "success"))
        evidence = "success criteria surfaced" if improved else "success criteria still implicit"
        return acted, improved, evidence

    if cat == "assumption_audit":
        improved = _mentions_any(tl, ("hypothesis", "assumption", "falsifiable", "disprove", "experiment"))
        acted = improved or _mentions_any(tl, ("debug", "root cause"))
        evidence = "assumption testing signal found" if improved else "assumption audit not explicit"
        return acted, improved, evidence

    if cat == "reversibility":
        improved = _mentions_any(tl, ("rollback", "fallback", "reversible", "undo plan", "safe revert"))
        acted = improved or _mentions_any(tl, ("risk", "regress"))
        evidence = "reversibility plan present" if improved else "rollback path not explicit"
        return acted, improved, evidence

    if cat == "humanity_guardrail":
        improved = _mentions_any(tl, ("user benefit", "people", "human", "harm", "safety", "non-harm"))
        acted = improved or _mentions_any(tl, ("guardrail", "ethic", "impact"))
        evidence = "humanity/safety framing present" if improved else "humanity framing still missing"
        return acted, improved, evidence

    if cat in {"compounding_learning", "compounding"}:
        improved = _mentions_any(tl, ("reusable", "pattern", "distill", "promote", "playbook", "eidos"))
        acted = improved or _mentions_any(tl, ("learn", "transfer"))
        evidence = "compounding learning captured" if improved else "transfer rule not yet captured"
        return acted, improved, evidence

    acted = _mentions_any(tl, ("improve", "opportunity", "next step"))
    improved = acted
    evidence = "generic opportunity progress" if improved else "no clear acted-on signal"
    return acted, improved, evidence


def _mentions_any(text: str, words: Sequence[str]) -> bool:
    tl = str(text or "").lower()
    return any(w in tl for w in words)


def _question_key(question: str) -> str:
    tokens = [t for t in re.findall(r"[a-z0-9]+", str(question or "").lower()) if t not in _QUESTION_STOPWORDS]
    if not tokens:
        return ""
    return " ".join(tokens[:14])


def _extract_scope_and_operation(text: str) -> tuple[Optional[str], Optional[str]]:
    """Extract explicit scope/operation markers from text.

    Supported markers:
    - scope:project|operation|global (or scope=...)
    - op:<name> or operation:<name> (or op=...)
    """
    t = str(text or "")
    scope = None
    m = re.search(r"\bscope\s*[:=]\s*(project|operation|global)\b", t, flags=re.I)
    if m:
        scope = str(m.group(1) or "").strip().lower()

    op = None
    m = re.search(r"\b(?:op|operation)\s*[:=]\s*([a-z0-9][a-z0-9_-]{1,48})\b", t, flags=re.I)
    if m:
        op = str(m.group(1) or "").strip().lower()
    return scope, op


def _extract_event_cwd(ev: Any) -> Optional[str]:
    try:
        data = getattr(ev, "data", None) or {}
        if isinstance(data, dict):
            cwd = data.get("cwd")
            if cwd:
                return str(cwd)
            payload = data.get("payload") or {}
            if isinstance(payload, dict) and payload.get("cwd"):
                return str(payload.get("cwd"))
    except Exception:
        return None
    return None


def _find_git_root(cwd: str) -> Optional[Path]:
    if not cwd:
        return None
    key = str(cwd).strip()
    cached = _GIT_ROOT_CACHE.get(key)
    if cached is not None:
        return Path(cached) if cached else None
    try:
        p = Path(key).expanduser()
    except Exception:
        _GIT_ROOT_CACHE[key] = ""
        return None
    try:
        p = p.resolve()
    except Exception:
        pass

    cur = p
    for _ in range(30):
        try:
            git_marker = cur / ".git"
            if git_marker.exists():
                _GIT_ROOT_CACHE[key] = str(cur)
                return cur
        except Exception:
            break
        if cur.parent == cur:
            break
        cur = cur.parent

    _GIT_ROOT_CACHE[key] = ""
    return None


def _git_origin_url(root: Path) -> str:
    if not root:
        return ""
    rkey = str(root)
    cached = _GIT_ORIGIN_CACHE.get(rkey)
    if cached is not None:
        return cached

    url = ""
    try:
        cfg_path = root / ".git" / "config"
        if cfg_path.exists():
            cp = configparser.ConfigParser()
            cp.read(cfg_path, encoding="utf-8")
            if cp.has_section('remote "origin"') and cp.has_option('remote "origin"', "url"):
                url = str(cp.get('remote "origin"', "url") or "").strip()
    except Exception:
        url = ""

    _GIT_ORIGIN_CACHE[rkey] = url
    return url


def _infer_project_identity(events: Sequence[Any]) -> tuple[Optional[str], Optional[str]]:
    """Return (project_id, project_label) if possible."""
    cwd = None
    try:
        recent = list(events or [])
    except Exception:
        recent = []
    for ev in reversed(recent[-30:]):
        cwd = _extract_event_cwd(ev)
        if cwd:
            break
    if not cwd:
        return None, None
    root = _find_git_root(cwd)
    if not root:
        h = hashlib.sha1(str(cwd).encode("utf-8", errors="ignore")).hexdigest()[:16]
        return f"path:{h}", Path(cwd).name
    origin = _git_origin_url(root)
    if origin:
        h = hashlib.sha1(origin.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return f"git:{h}", root.name
    h = hashlib.sha1(str(root).encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"path:{h}", root.name


def _load_blocked_question_keys(now_ts: Optional[float] = None) -> set[str]:
    """Return question keys dismissed recently to reduce spam."""
    now = float(now_ts or time.time())
    blocked: set[str] = set()
    if not DECISIONS_FILE.exists():
        return blocked
    try:
        lines = DECISIONS_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return blocked
    if len(lines) > _DECISION_LOOKBACK:
        lines = lines[-_DECISION_LOOKBACK:]
    latest: Dict[str, Dict[str, Any]] = {}
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        qk = str(row.get("question_key") or "").strip()
        if not qk:
            continue
        try:
            ts = float(row.get("ts") or 0.0)
        except Exception:
            ts = 0.0
        prev = latest.get(qk)
        if prev is None or ts >= float(prev.get("ts") or 0.0):
            latest[qk] = {"ts": ts, "action": str(row.get("action") or "").strip().lower()}
    for qk, meta in latest.items():
        action = str(meta.get("action") or "")
        ts = float(meta.get("ts") or 0.0)
        if action == "dismiss" and ts > 0 and (now - ts) <= float(_DISMISS_TTL_S or 0.0):
            blocked.add(qk)
    return blocked


def _extract_json_candidate(raw: str) -> Optional[Any]:
    text = str(raw or "").strip()
    if not text:
        return None

    # MiniMax and some other providers may return:
    #   <think> ... {"foo": 1} ... </think> {"opportunities": [...]}
    # which breaks naive "first { ... last }" slicing due to braces in the think block.
    # Use JSONDecoder.raw_decode scanning to extract the first valid JSON value, and
    # prefer the schema we actually want (dict with "opportunities").
    decoder = json.JSONDecoder()

    candidates = [text]
    # Prefer scanning after a provider "thinking" block if present. This avoids
    # accidentally parsing echoed prompt schema inside <think>...</think>.
    think_matches = list(re.finditer(r"</think>", text, flags=re.IGNORECASE))
    if think_matches:
        after = text[think_matches[-1].end() :].strip()
        if after:
            candidates.insert(0, after)
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE):
        payload = str(m.group(1) or "").strip()
        if payload:
            candidates.append(payload)

    best: Optional[Any] = None
    for cand in candidates:
        s = str(cand or "").strip()
        if not s:
            continue
        for i, ch in enumerate(s):
            if ch not in "{[":
                continue
            try:
                obj, _end = decoder.raw_decode(s[i:])
            except Exception:
                continue
            if isinstance(obj, dict) and "opportunities" in obj:
                return obj
            if best is None:
                best = obj
    return best


def _sanitize_llm_self_rows(rows: Any) -> List[Dict[str, Any]]:
    if isinstance(rows, dict):
        arr = rows.get("opportunities")
        rows = arr if isinstance(arr, list) else [rows]
    if not isinstance(rows, list):
        return []

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        category = str(row.get("category") or "assumption_audit").strip().lower()
        if category not in _SELF_CATEGORY_ALLOWLIST:
            continue
        question = str(row.get("question") or "").strip()
        next_step = str(row.get("next_step") or "").strip()
        rationale = str(row.get("rationale") or "").strip()
        if not question or not next_step:
            continue
        if _is_telemetry_noise(question) or _is_telemetry_noise(next_step):
            continue
        qk = _question_key(question)
        if not qk or qk in seen:
            continue
        seen.add(qk)

        priority = str(row.get("priority") or "medium").strip().lower()
        if priority not in {"high", "medium", "low"}:
            priority = "medium"

        try:
            confidence = float(row.get("confidence") or 0.72)
        except Exception:
            confidence = 0.72
        confidence = max(0.55, min(0.95, confidence))

        out.append(
            {
                "category": category,
                "priority": priority,
                "confidence": round(confidence, 2),
                "question": question,
                "next_step": next_step,
                "rationale": rationale or "LLM-suggested self-improvement opportunity.",
                "source": "llm",
            }
        )
        if len(out) >= LLM_MAX_ITEMS:
            break
    return out


def _generate_llm_self_candidates(
    *,
    prompts: List[str],
    edits: List[str],
    query: str,
    stats: Dict[str, Any],
    kernel_ok: bool,
    session_id: str = "default",
    cooldown_key: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    meta: Dict[str, Any] = {
        "enabled": bool(LLM_ENABLED),
        "attempted": False,
        "used": False,
        "provider": None,
        "error": None,
        "candidates": 0,
        "skipped_reason": None,
    }
    if not LLM_ENABLED:
        return [], meta
    if LLM_PROVIDER in _FORBIDDEN_LLM_PROVIDERS:
        meta["error"] = f"provider_blocked:{LLM_PROVIDER}"
        return [], meta

    context_bits = prompts[-3:] + edits[-2:] + ([query] if query else [])
    context_text = " ".join(str(x or "").strip() for x in context_bits if str(x or "").strip()).strip()
    if len(context_text) < max(24, int(LLM_MIN_CONTEXT_CHARS or 0)):
        meta["skipped_reason"] = "insufficient_context"
        return [], meta
    try:
        now = time.time()
        key = str(cooldown_key or session_id or "default")
        last = float(_LAST_LLM_ATTEMPT_BY_KEY.get(key, 0.0) or 0.0)
        if float(LLM_COOLDOWN_S or 0.0) > 0 and last > 0 and (now - last) < float(LLM_COOLDOWN_S or 0.0):
            meta["skipped_reason"] = "cooldown"
            return [], meta
    except Exception:
        pass

    try:
        # Use import_module so tests can monkeypatch sys.modules["lib.advisory_synthesizer"]
        # even if the real module was imported earlier in the process.
        import importlib

        synth = importlib.import_module("lib.advisory_synthesizer")
    except Exception as e:
        meta["error"] = f"import_failed:{type(e).__name__}"
        return [], meta

    # Keep this prompt short: some providers spend the whole token budget in "<think>"
    # unless we are extremely direct.
    stat_slice = {
        "errors": (stats or {}).get("errors", []),
        "validation": (stats or {}).get("validation", {}),
    }
    prompt = (
        "Return ONLY JSON. No markdown.\n"
        'Output: JSON object with key "opportunities" (max 3).\n'
        "Each opportunity keys: category, priority, confidence, question, next_step, rationale.\n"
        "category must be one of: verification_gap, outcome_clarity, assumption_audit, reversibility, humanity_guardrail, compounding_learning.\n"
        "priority must be high|medium|low. confidence must be 0.55-0.95.\n"
        "Filter telemetry/noise (tool_*_error, status code, trace ids, heartbeat logs). Focus on meaningful improvements.\n"
        f"Kernel: {'conscious' if kernel_ok else 'conservative'}.\n"
        f"Context: {context_text[:900]}\n"
        f"Stats: {json.dumps(stat_slice, ensure_ascii=True)[:320]}"
    )

    meta["attempted"] = True
    prev_timeout = getattr(synth, "AI_TIMEOUT_S", None)
    try:
        synth.AI_TIMEOUT_S = LLM_TIMEOUT_S
        chain = synth._get_provider_chain(LLM_PROVIDER or None)
        if LLM_PROVIDER:
            chain = [p for p in chain if str(p or "").strip().lower() == LLM_PROVIDER]
        chain = [p for p in chain if str(p or "").strip().lower() not in _FORBIDDEN_LLM_PROVIDERS]
        if not chain:
            meta["error"] = "no_allowed_provider"
            return [], meta
        last_error = None
        for provider in chain:
            try:
                # Per-provider time budget. Cloud providers (esp. minimax) are higher-latency than local.
                provider_timeout = float(LLM_TIMEOUT_S)
                if str(provider or "").strip().lower() == "minimax":
                    provider_timeout = max(provider_timeout, 12.0)
                synth.AI_TIMEOUT_S = provider_timeout
                _LAST_LLM_ATTEMPT_BY_KEY[str(cooldown_key or session_id or "default")] = time.time()
                raw = synth._query_provider(provider, prompt)
            except Exception as e:
                last_error = f"{provider}:{type(e).__name__}"
                continue
            if not raw:
                # Surface timeouts/empty responses in scanner meta so operators can tune
                # SPARK_OPPORTUNITY_LLM_TIMEOUT_S or switch providers.
                last_error = last_error or f"{provider}:empty_or_timeout"
                continue
            parsed = _extract_json_candidate(raw)
            rows = _sanitize_llm_self_rows(parsed)
            if not rows:
                # MiniMax sometimes spends the whole token budget in <think>. One retry with a
                # shorter prompt is cheap insurance.
                if str(provider or "").strip().lower() == "minimax":
                    retry_prompt = (
                        "Return ONLY JSON. No markdown.\n"
                        'Output: {"opportunities":[{"category":"...","priority":"high|medium|low","confidence":0.72,'
                        '"question":"...","next_step":"...","rationale":"..."}]}.\n'
                        "Max 2 opportunities.\n"
                        "Rules: no telemetry; meaningful improvements; self-directed; actionable.\n"
                        f"Context: {context_text[:360]}"
                    )
                    try:
                        raw2 = synth._query_provider(provider, retry_prompt)
                    except Exception:
                        raw2 = None
                    if raw2:
                        parsed2 = _extract_json_candidate(raw2)
                        rows2 = _sanitize_llm_self_rows(parsed2)
                        if rows2:
                            rows = rows2
                        else:
                            last_error = f"{provider}:unparseable_or_empty"
                            continue
                    else:
                        last_error = f"{provider}:unparseable_or_empty"
                        continue
                else:
                    last_error = f"{provider}:unparseable_or_empty"
                    continue
            meta["used"] = True
            meta["provider"] = provider
            meta["candidates"] = len(rows)
            for r in rows:
                if isinstance(r, dict):
                    r.setdefault("llm_provider", provider)
            return rows, meta
        if last_error:
            meta["error"] = last_error
    finally:
        if prev_timeout is not None:
            try:
                synth.AI_TIMEOUT_S = prev_timeout
            except Exception:
                pass

    return [], meta


def _priority_score(priority: Any) -> int:
    pl = str(priority or "").strip().lower()
    if pl == "high":
        return 3
    if pl == "medium":
        return 2
    if pl == "low":
        return 1
    return 0


def _recent_self_question_keys() -> set[str]:
    if SELF_DEDUP_WINDOW_S <= 0:
        return set()
    rows = _tail_jsonl(SELF_FILE, SELF_RECENT_LOOKBACK)
    if not rows:
        return set()
    now = time.time()
    out = set()
    for row in rows:
        ts = float(row.get("ts") or 0.0)
        if ts <= 0:
            continue
        if (now - ts) > SELF_DEDUP_WINDOW_S:
            continue
        key = _question_key(str(row.get("question") or ""))
        if key:
            out.add(key)
    return out


def _select_diverse_self_rows(
    candidates: List[Dict[str, Any]],
    *,
    max_items: int,
    recent_keys: Optional[set[str]] = None,
) -> tuple[List[Dict[str, Any]], int]:
    if not candidates:
        return [], 0
    rk = recent_keys or set()
    merged_by_key: Dict[str, Dict[str, Any]] = {}
    for row in candidates:
        key = _question_key(str(row.get("question") or ""))
        if not key:
            continue
        prev = merged_by_key.get(key)
        if prev is None:
            merged_by_key[key] = row
            continue
        prev_score = (_priority_score(prev.get("priority")), float(prev.get("confidence") or 0.0))
        row_score = (_priority_score(row.get("priority")), float(row.get("confidence") or 0.0))
        if row_score > prev_score:
            merged_by_key[key] = row

    merged = list(merged_by_key.values())
    if not merged:
        return [], 0

    merged.sort(
        key=lambda r: (
            0 if _question_key(str(r.get("question") or "")) in rk else 1,
            _priority_score(r.get("priority")),
            float(r.get("confidence") or 0.0),
        ),
        reverse=True,
    )

    selected: List[Dict[str, Any]] = []
    category_counts: Dict[str, int] = {}
    filtered_recent = 0

    # Pass 1: favor novel questions and category diversity.
    for row in merged:
        key = _question_key(str(row.get("question") or ""))
        if key in rk:
            filtered_recent += 1
            continue
        cat = str(row.get("category") or "general")
        if category_counts.get(cat, 0) >= SELF_CATEGORY_CAP:
            continue
        selected.append(row)
        category_counts[cat] = category_counts.get(cat, 0) + 1
        if len(selected) >= max_items:
            return selected, filtered_recent

    # Pass 2: fill from remaining novel rows even if category repeats.
    if len(selected) < max_items:
        seen = {_question_key(str(r.get("question") or "")) for r in selected}
        for row in merged:
            key = _question_key(str(row.get("question") or ""))
            if key in rk or key in seen:
                continue
            selected.append(row)
            seen.add(key)
            if len(selected) >= max_items:
                return selected, filtered_recent

    return selected, filtered_recent


def _derive_self_candidates(
    *,
    prompts: List[str],
    edits: List[str],
    stats: Dict[str, Any],
    query: str,
    kernel_ok: bool,
) -> List[Dict[str, Any]]:
    combined = " ".join(prompts + edits[:2] + [query]).strip()
    has_tests = _mentions_any(combined, ("pytest", "test", "assert", "integration test", "unit test"))
    has_done = _mentions_any(combined, ("done", "definition of done", "acceptance", "success criteria"))
    has_risk = _mentions_any(combined, ("risk", "rollback", "safety", "security", "guardrail"))
    has_human = _mentions_any(combined, ("user", "human", "humanity", "helpful", "harm"))
    errors = stats.get("errors") if isinstance(stats, dict) else []
    validation = stats.get("validation") if isinstance(stats, dict) else {}
    surprises = int((validation or {}).get("surprises") or 0)
    duplicate_prompts = len({p.strip().lower() for p in prompts}) < len(prompts) if prompts else False

    rows: List[Dict[str, Any]] = []
    if edits and not has_tests:
        rows.append(
            {
                "category": "verification_gap",
                "priority": "high",
                "confidence": 0.84,
                "question": "What is the smallest proof that this change works before the next edit?",
                "next_step": "Run one focused command/test that validates the changed behavior.",
                "rationale": "Edits are happening without explicit verification evidence.",
            }
        )
    if prompts and not has_done:
        rows.append(
            {
                "category": "outcome_clarity",
                "priority": "high",
                "confidence": 0.81,
                "question": "What exact outcome marks done, and how will Spark verify it?",
                "next_step": "Define one measurable completion check and attach it to this task.",
                "rationale": "Clear completion criteria prevent loop drift and shallow progress.",
            }
        )
    if (errors and len(errors) > 0) or surprises > 0 or duplicate_prompts:
        rows.append(
            {
                "category": "assumption_audit",
                "priority": "medium",
                "confidence": 0.76,
                "question": "Which assumption keeps failing, and what evidence would quickly disprove it?",
                "next_step": "Write one falsifiable hypothesis and test it before more edits.",
                "rationale": "Repeated friction signals an untested assumption in the loop.",
            }
        )
    if edits and not has_risk:
        rows.append(
            {
                "category": "reversibility",
                "priority": "medium",
                "confidence": 0.72,
                "question": "What is the safest reversible step if this change regresses?",
                "next_step": "Define a rollback check or fallback path before broad changes.",
                "rationale": "Autonomy must stay bounded by explicit reversibility planning.",
            }
        )
    if not has_human:
        rows.append(
            {
                "category": "humanity_guardrail",
                "priority": "medium",
                "confidence": 0.74,
                "question": "How does this decision help people and reduce downside in edge cases?",
                "next_step": "State one direct user benefit and one harm-avoidance check.",
                "rationale": "Conscious autonomy should remain aligned with service and non-harm.",
            }
        )
    if kernel_ok and _mentions_any(combined, ("improve", "better", "evolve", "learning", "autonomy")):
        rows.append(
            {
                "category": "compounding_learning",
                "priority": "medium",
                "confidence": 0.79,
                "question": "What reusable learning from this task should Spark promote for future work?",
                "next_step": "Capture one transferable rule with evidence and promote it to context/advisor memory.",
                "rationale": "Compounding intelligence requires explicit transfer, not implicit recall.",
            }
        )
    for r in rows:
        r.setdefault("source", "heuristic")
    return rows


def _track_meta_retrieval(
    *,
    opportunity_id: str,
    question: str,
    category: str,
    trace_id: str,
) -> None:
    try:
        from .meta_ralph import get_meta_ralph

        key_hash = hashlib.sha1(f"{category}|{question}".encode("utf-8")).hexdigest()[:10]
        get_meta_ralph().track_retrieval(
            opportunity_id,
            question,
            insight_key=f"opportunity:{category}:{key_hash}",
            source="opportunity_scanner",
            trace_id=(trace_id or None),
        )
    except Exception as e:
        log_debug("opportunity_scanner", "meta retrieval tracking failed", e)


def _track_meta_outcome(
    *,
    opportunity_id: str,
    outcome: str,
    evidence: str,
    category: str,
    trace_id: str,
) -> None:
    try:
        from .meta_ralph import get_meta_ralph

        get_meta_ralph().track_outcome(
            opportunity_id,
            outcome,
            evidence,
            trace_id=(trace_id or None),
            insight_key=f"opportunity:{category}",
            source="opportunity_scanner",
        )
    except Exception as e:
        log_debug("opportunity_scanner", "meta outcome tracking failed", e)


def _track_recent_outcomes(
    *,
    session_id: str,
    text: str,
    stats: Dict[str, Any],
    trace_id: str,
    persist: bool,
) -> Dict[str, int]:
    rows = _tail_jsonl(SELF_FILE, OUTCOME_LOOKBACK)
    if not rows:
        return {"tracked": 0, "improved": 0}
    now = time.time()
    seen_outcomes = _load_recorded_outcome_ids()
    tracked = 0
    improved_count = 0

    for row in reversed(rows):
        sid = str(row.get("session_id") or "").strip()
        if sid and sid != session_id:
            continue
        ts = float(row.get("ts") or 0.0)
        if ts <= 0:
            continue
        if OUTCOME_WINDOW_S > 0 and (now - ts) > OUTCOME_WINDOW_S:
            continue
        category = str(row.get("category") or "general")
        question = str(row.get("question") or "").strip()
        if not question:
            continue
        opp_id = str(row.get("opportunity_id") or "").strip()
        if not opp_id:
            opp_id = _opportunity_id(session_id=session_id, category=category, question=question, ts=ts)
        if opp_id in seen_outcomes:
            continue

        acted, improved, evidence = _evaluate_opportunity_signal(category, text, stats)
        if not acted:
            continue

        tracked += 1
        if improved:
            improved_count += 1

        retrieve_trace = str(row.get("trace_id") or "").strip()
        outcome_trace = trace_id or retrieve_trace
        outcome = "good" if improved else "bad"
        outcome_row = {
            "ts": now,
            "session_id": session_id,
            "opportunity_id": opp_id,
            "category": category,
            "acted_on": True,
            "improved": bool(improved),
            "outcome": outcome,
            "evidence": evidence,
            "trace_id": retrieve_trace or None,
            "outcome_trace_id": outcome_trace or None,
            "strict_trace_match": bool(retrieve_trace and outcome_trace and retrieve_trace == outcome_trace),
        }
        if persist:
            _append_jsonl_capped(OUTCOME_FILE, outcome_row)
            seen_outcomes.add(opp_id)

        _track_meta_outcome(
            opportunity_id=opp_id,
            outcome=outcome,
            evidence=f"opportunity:{category} {evidence}",
            category=category,
            trace_id=outcome_trace,
        )

    return {"tracked": tracked, "improved": improved_count}


def promote_high_performing_opportunities(
    *,
    limit: int = 3,
    persist: bool = True,
) -> List[Dict[str, Any]]:
    self_rows = _tail_jsonl(SELF_FILE, PROMOTION_LOOKBACK)
    outcome_rows = _tail_jsonl(OUTCOME_FILE, PROMOTION_LOOKBACK)
    if not self_rows or not outcome_rows:
        return []

    by_opp: Dict[str, Dict[str, Any]] = {}
    for row in self_rows:
        oid = str(row.get("opportunity_id") or "").strip()
        if oid:
            by_opp[oid] = row

    grouped: Dict[str, Dict[str, Any]] = {}
    for out in outcome_rows:
        oid = str(out.get("opportunity_id") or "").strip()
        if not oid:
            continue
        src = by_opp.get(oid) or {}
        question = str(src.get("question") or "").strip()
        if not question:
            continue
        category = str(src.get("category") or "general").strip().lower()
        key = _question_key(question) or f"{category}:{question.lower()[:32]}"
        g = grouped.setdefault(
            key,
            {
                "promotion_key": key,
                "category": category,
                "question": question,
                "next_step": str(src.get("next_step") or "").strip(),
                "attempts": 0,
                "good": 0,
                "strict_good": 0,
            },
        )
        if bool(out.get("acted_on")):
            g["attempts"] += 1
        if str(out.get("outcome") or "").strip().lower() == "good":
            g["good"] += 1
            if bool(out.get("strict_trace_match")):
                g["strict_good"] += 1

    promoted_keys = _load_promoted_opportunity_keys() if persist else set()
    now = time.time()
    candidates: List[Dict[str, Any]] = []
    for g in grouped.values():
        attempts = int(g.get("attempts") or 0)
        good = int(g.get("good") or 0)
        if attempts <= 0:
            continue
        effectiveness = good / max(attempts, 1)
        if good < PROMOTION_MIN_SUCCESSES:
            continue
        if effectiveness < PROMOTION_MIN_EFFECTIVENESS:
            continue
        pkey = str(g.get("promotion_key") or "")
        if pkey in promoted_keys:
            continue
        category = str(g.get("category") or "general")
        question = str(g.get("question") or "")
        next_step = str(g.get("next_step") or "Apply the same pattern with explicit proof checks.")
        statement = (
            f"When {category.replace('_', ' ')} appears, use: {next_step} "
            f"because opportunity outcomes were good in {good}/{attempts} acted cases."
        )
        candidate = {
            "ts": now,
            "promotion_key": pkey,
            "promotion_id": f"opp-promote:{hashlib.sha1((pkey + str(now)).encode('utf-8')).hexdigest()[:14]}",
            "category": category,
            "question": question,
            "next_step": next_step,
            "attempts": attempts,
            "good": good,
            "strict_good": int(g.get("strict_good") or 0),
            "effectiveness": round(effectiveness, 4),
            "statement": statement,
            "eidos_observation": f"Opportunity promotion candidate: {statement}",
        }
        candidates.append(candidate)

    candidates.sort(
        key=lambda r: (
            float(r.get("effectiveness") or 0.0),
            int(r.get("good") or 0),
            int(r.get("strict_good") or 0),
        ),
        reverse=True,
    )
    selected = candidates[: max(0, int(limit or 0))]
    if persist and selected:
        for row in selected:
            _append_jsonl_capped(PROMOTION_FILE, row)
    return selected


def scan_runtime_opportunities(
    events: Sequence[Any],
    *,
    stats: Optional[Dict[str, Any]] = None,
    query: str = "",
    session_id: str = "default",
    persist: bool = True,
) -> Dict[str, Any]:
    """Scan active bridge-cycle work and produce self-improvement opportunities."""
    base = {
        "enabled": bool(SCANNER_ENABLED),
        "kernel_pass": False,
        "mode": "disabled",
        "captured_prompts": 0,
        "captured_edits": 0,
        "telemetry_filtered": 0,
        "dedup_recent_filtered": 0,
        "outcomes_tracked": 0,
        "outcomes_improved": 0,
        "llm": {
            "enabled": bool(LLM_ENABLED),
            "attempted": False,
            "used": False,
            "provider": None,
            "error": None,
            "candidates": 0,
        },
        "promoted_candidates": [],
        "opportunities_found": 0,
        "self_opportunities": [],
    }
    if not SCANNER_ENABLED:
        return base

    # Keep runtime cost bounded even if the pipeline hands us a large backlog.
    if SCAN_EVENT_LIMIT > 0:
        try:
            if isinstance(events, list):
                events = events[-SCAN_EVENT_LIMIT:]
            else:
                events = list(events or [])[-SCAN_EVENT_LIMIT:]
        except Exception:
            events = list(events or [])[-SCAN_EVENT_LIMIT:]

    spark_stats = stats if isinstance(stats, dict) else {}
    prompts: List[str] = []
    edits: List[str] = []
    telemetry_filtered = 0
    scope_hint = None
    operation = None

    for ev in events or []:
        et = _event_type_name(ev)
        tool = _tool_name(ev)
        if et == "user_prompt":
            text = _extract_prompt_text(ev)
            if _is_telemetry_noise(text):
                telemetry_filtered += 1
                continue
            prompts.append(text[:600])
            continue
        if et == "post_tool" and tool in {"edit", "write", "notebookedit"}:
            text = _extract_edit_text(ev)
            if not text:
                continue
            if _is_telemetry_noise(text[:400]):
                telemetry_filtered += 1
                continue
            edits.append(text[:1200])

    has_context = bool(prompts or edits or (str(query or "").strip() and len(str(query or "").strip()) >= 24))
    # Extract explicit tags from the most recent user prompt / edit / query.
    try:
        tag_text = " ".join([prompts[-1] if prompts else "", edits[-1] if edits else "", str(query or "")]).strip()
        sh, op = _extract_scope_and_operation(tag_text)
        scope_hint = sh or None
        operation = op or None
    except Exception:
        scope_hint = None
        operation = None

    project_id, project_label = _infer_project_identity(events)
    scope_type = "project"
    scope_id = project_id or "default"
    if scope_hint == "global":
        scope_type = "spark_global"
        scope_id = "global"
    elif scope_hint == "operation" and operation:
        scope_type = "operation"
        scope_id = operation
    elif scope_hint == "project":
        scope_type = "project"
        scope_id = project_id or "default"

    cooldown_key = f"{scope_type}:{scope_id}"

    primary_trace_id = _select_primary_trace_id(events)
    combined_text = " ".join(prompts + edits + [query]).strip()
    outcome_stats = _track_recent_outcomes(
        session_id=str(session_id or "default"),
        text=combined_text,
        stats=spark_stats,
        trace_id=primary_trace_id,
        persist=persist,
    )
    promoted_candidates = promote_high_performing_opportunities(limit=3, persist=persist)

    try:
        soul = fetch_soul_state(session_id=session_id or "default")
        kernel_ok = bool(soul_kernel_pass(soul))
    except Exception:
        kernel_ok = False
    mode = "conscious" if kernel_ok else "conservative"

    if not has_context:
        # No new meaningful work context; do not spam the same evergreen prompts.
        # (We still ran outcome tracking above to keep the loop's attribution consistent.)
        return {
            "enabled": True,
            "kernel_pass": kernel_ok,
            "mode": mode,
            "captured_prompts": len(prompts),
            "captured_edits": len(edits),
            "telemetry_filtered": telemetry_filtered,
            "dedup_recent_filtered": 0,
            "outcomes_tracked": int(outcome_stats.get("tracked") or 0),
            "outcomes_improved": int(outcome_stats.get("improved") or 0),
            "llm": base["llm"],
            "promoted_candidates": promoted_candidates,
            "opportunities_found": 0,
            "self_opportunities": [],
            "persisted": 0,
        }

    candidates = _derive_self_candidates(
        prompts=prompts,
        edits=edits,
        stats=spark_stats,
        query=query,
        kernel_ok=kernel_ok,
    )
    llm_candidates, llm_meta = _generate_llm_self_candidates(
        prompts=prompts,
        edits=edits,
        query=query,
        stats=spark_stats,
        kernel_ok=kernel_ok,
        session_id=str(session_id or "default"),
        cooldown_key=cooldown_key,
    )
    if llm_candidates:
        candidates.extend(llm_candidates)
    blocked_keys = _load_blocked_question_keys()
    recent_keys = _recent_self_question_keys() | blocked_keys
    deduped, dedup_recent_filtered = _select_diverse_self_rows(
        candidates,
        max_items=SELF_MAX_ITEMS,
        recent_keys=recent_keys,
    )
    try:
        llm_meta["selected"] = int(
            sum(1 for r in (deduped or []) if isinstance(r, dict) and str(r.get("source") or "").strip().lower() == "llm")
        )
    except Exception:
        llm_meta["selected"] = 0

    now_ts = time.time()
    persisted = 0
    if persist and deduped:
        for idx, row in enumerate(deduped):
            # If we had to fall back to repeated prompts (pass-3 selection), avoid
            # re-persisting the same question into history every cycle.
            if _question_key(str(row.get("question") or "")) in recent_keys:
                continue
            row_ts = now_ts + (idx * 0.0001)
            opp_id = _opportunity_id(
                session_id=str(session_id or "default"),
                category=str(row.get("category") or "general"),
                question=str(row.get("question") or ""),
                ts=row_ts,
            )
            entry = {
                "ts": row_ts,
                "session_id": str(session_id or "default"),
                "trace_id": primary_trace_id or None,
                "opportunity_id": opp_id,
                "scope": "self",
                "scope_type": scope_type,
                "scope_id": scope_id,
                "project_id": project_id,
                "project_label": project_label,
                "operation": operation,
                "mode": mode,
                **row,
            }
            _append_jsonl_capped(SELF_FILE, entry)
            row["opportunity_id"] = opp_id
            row["trace_id"] = primary_trace_id or None
            _track_meta_retrieval(
                opportunity_id=opp_id,
                question=str(row.get("question") or ""),
                category=str(row.get("category") or "general"),
                trace_id=primary_trace_id,
            )
            persisted += 1

    return {
        "enabled": True,
        "kernel_pass": kernel_ok,
        "mode": mode,
        "captured_prompts": len(prompts),
        "captured_edits": len(edits),
        "telemetry_filtered": telemetry_filtered,
        "dedup_recent_filtered": dedup_recent_filtered,
        "decision_blocked_filtered": len(blocked_keys) if isinstance(blocked_keys, set) else 0,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "project_id": project_id,
        "project_label": project_label,
        "operation": operation,
        "outcomes_tracked": int(outcome_stats.get("tracked") or 0),
        "outcomes_improved": int(outcome_stats.get("improved") or 0),
        "llm": llm_meta,
        "promoted_candidates": promoted_candidates,
        "opportunities_found": len(deduped),
        "self_opportunities": deduped,
        "persisted": persisted,
    }


def _context_match_score(question: str, context: str) -> float:
    q_tokens = {t for t in re.findall(r"[a-z0-9_]+", str(question or "").lower()) if len(t) >= 4}
    c_tokens = {t for t in re.findall(r"[a-z0-9_]+", str(context or "").lower()) if len(t) >= 4}
    if not q_tokens or not c_tokens:
        return 0.55
    overlap = len(q_tokens & c_tokens) / max(1, len(q_tokens))
    return max(0.55, min(0.95, 0.55 + overlap))


def _derive_user_candidates(text: str, *, kernel_ok: bool) -> List[Dict[str, Any]]:
    has_done = _mentions_any(text, ("done", "acceptance", "success criteria", "definition of done"))
    has_constraints = _mentions_any(text, ("constraint", "budget", "deadline", "scope", "risk"))
    has_human = _mentions_any(text, ("user", "customer", "human", "people", "harm", "safety"))
    has_reuse = _mentions_any(text, ("reuse", "template", "pattern", "playbook", "transfer"))
    growth_domain = _mentions_any(text, ("growth", "market", "launch", "adoption", "opportunity", "strategy"))

    rows: List[Dict[str, Any]] = []
    if not has_done:
        rows.append(
            {
                "category": "outcome_clarity",
                "confidence": 0.7,
                "question": "What is the one measurable outcome that defines success for this task?",
                "next_step": "Write the success check first, then execute against it.",
                "rationale": "Clarity on success creates better decisions and cleaner execution.",
            }
        )
    if not has_constraints:
        rows.append(
            {
                "category": "constraint_surface",
                "confidence": 0.68,
                "question": "Which constraint will break this plan first if ignored?",
                "next_step": "Name one hard constraint and adapt the plan around it.",
                "rationale": "Early constraint visibility prevents expensive rework.",
            }
        )
    if not has_human:
        rows.append(
            {
                "category": "humanity_guardrail",
                "confidence": 0.72,
                "question": "Who benefits most from this change, and what harm should we explicitly avoid?",
                "next_step": "Add one user-benefit statement and one safety check before shipping.",
                "rationale": "Conscious agency should be anchored to service and non-harm.",
            }
        )
    if kernel_ok and not has_reuse:
        rows.append(
            {
                "category": "compounding",
                "confidence": 0.66,
                "question": "What part of this work can become a reusable pattern for future tasks?",
                "next_step": "Capture one reusable pattern and where Spark should apply it next.",
                "rationale": "Compounding behavior turns one solution into recurring leverage.",
            }
        )
    if kernel_ok and growth_domain:
        rows.append(
            {
                "category": "upside_mapping",
                "confidence": 0.69,
                "question": "Where is the highest-upside, lowest-regret opportunity for people here?",
                "next_step": "List one high-upside opportunity and the first low-risk validation step.",
                "rationale": "Opportunity mapping improves both execution and advisory quality.",
            }
        )
    return rows


def generate_user_opportunities(
    *,
    tool_name: str,
    context: str,
    task_context: str = "",
    session_id: str = "default",
    persist: bool = False,
) -> List[Dict[str, Any]]:
    """Generate user-facing Socratic opportunity prompts for current work."""
    if not SCANNER_ENABLED or not USER_SCAN_ENABLED:
        return []

    tool = str(tool_name or "").strip().lower()
    text = f"{context or ''} {task_context or ''}".strip()
    if _is_telemetry_noise(text):
        return []

    strategic = _mentions_any(text.lower(), _STRATEGIC_MARKERS)
    if tool not in _HIGH_IMPACT_TOOLS and not strategic:
        return []

    try:
        soul = fetch_soul_state(session_id=session_id or "default")
        kernel_ok = bool(soul_kernel_pass(soul))
    except Exception:
        kernel_ok = False

    mode = "conscious" if kernel_ok else "conservative"
    candidates = _derive_user_candidates(text.lower(), kernel_ok=kernel_ok)
    out: List[Dict[str, Any]] = []
    seen = set()
    now_ts = time.time()
    for row in candidates:
        q = str(row.get("question") or "").strip()
        if not q:
            continue
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        context_match = _context_match_score(q, text)
        enriched = {
            "ts": now_ts,
            "scope": "user",
            "mode": mode,
            "tool_name": tool_name,
            "context_match": context_match,
            **row,
        }
        out.append(enriched)
        if len(out) >= USER_MAX_ITEMS:
            break

    if persist and out:
        for row in out:
            entry = {"session_id": str(session_id or "default"), **row}
            _append_jsonl_capped(USER_FILE, entry)

    return out


def get_recent_self_opportunities(limit: int = 3, max_age_s: float = 172800.0) -> List[Dict[str, Any]]:
    """Return recent persisted self opportunities for context surfaces."""
    rows = _tail_jsonl(SELF_FILE, max(1, int(limit or 1) * 6))
    if not rows:
        return []
    now = time.time()
    out: List[Dict[str, Any]] = []
    for row in reversed(rows):
        ts = float(row.get("ts") or 0.0)
        if ts <= 0:
            continue
        if max_age_s > 0 and (now - ts) > float(max_age_s):
            continue
        question = str(row.get("question") or "").strip()
        if not question:
            continue
        out.append(row)
        if len(out) >= max(1, int(limit or 1)):
            break
    return out


def get_scanner_status() -> Dict[str, Any]:
    try:
        self_rows = _tail_jsonl(SELF_FILE, 20)
        outcome_rows = _tail_jsonl(OUTCOME_FILE, 80)
        promotion_rows = _tail_jsonl(PROMOTION_FILE, 40)
    except Exception as e:
        log_debug("opportunity_scanner", "status read failed", e)
        self_rows = []
        outcome_rows = []
        promotion_rows = []
    acted = [r for r in outcome_rows if bool(r.get("acted_on"))]
    improved = [r for r in acted if bool(r.get("improved"))]
    adoption_rate = (len(improved) / max(len(acted), 1)) if acted else 0.0
    return {
        "enabled": bool(SCANNER_ENABLED),
        "user_scan_enabled": bool(USER_SCAN_ENABLED),
        "llm_enabled": bool(LLM_ENABLED),
        "llm_provider": LLM_PROVIDER or "auto",
        "llm_timeout_s": float(LLM_TIMEOUT_S),
        "self_file": str(SELF_FILE),
        "user_file": str(USER_FILE),
        "outcome_file": str(OUTCOME_FILE),
        "self_recent": len(self_rows),
        "outcomes_recent": len(outcome_rows),
        "adoption_rate": round(adoption_rate, 4),
        "promotions_recent": len(promotion_rows),
    }
