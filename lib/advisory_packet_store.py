"""
Advisory packet store for predictive/direct-path reuse.

Phase 1 scope:
- Deterministic packet CRUD
- Exact and relaxed lookup
- Invalidation helpers
- Background prefetch queue append
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config_authority import resolve_section

# httpx moved to advisory_packet_llm_reranker.py

PACKET_DIR = Path.home() / ".spark" / "advice_packets"
INDEX_FILE = PACKET_DIR / "index.json"
PREFETCH_QUEUE_FILE = PACKET_DIR / "prefetch_queue.jsonl"
OBSIDIAN_EXPORT_DIR = PACKET_DIR / "obsidian"
OBSIDIAN_PACKETS_DIR = OBSIDIAN_EXPORT_DIR / "packets"
OBSIDIAN_INDEX_FILE = OBSIDIAN_PACKETS_DIR / "index.md"
ADVISORY_DECISION_LEDGER_FILE = Path.home() / ".spark" / "advisory_decision_ledger.jsonl"
ADVISORY_ENGINE_LOG_FILE = Path.home() / ".spark" / "advisory_engine.jsonl"
ADVISORY_EMIT_FILE = Path.home() / ".spark" / "advisory_emit.jsonl"
ADVISORY_LOW_AUTH_DEDUPE_FILE = Path.home() / ".spark" / "advisory_low_auth_dedupe.jsonl"
ADVISORY_GLOBAL_DEDUPE_FILE = Path.home() / ".spark" / "advisory_global_dedupe.jsonl"
ADVICE_FEEDBACK_REQUESTS_FILE = Path.home() / ".spark" / "advice_feedback_requests.jsonl"
ADVICE_FEEDBACK_FILE = Path.home() / ".spark" / "advice_feedback.jsonl"
ADVISORY_RETRIEVAL_ROUTE_LOG_FILE = Path.home() / ".spark" / "advisor" / "retrieval_router.jsonl"
ADVISOR_ADVICE_LOG_FILE = Path.home() / ".spark" / "advisor" / "advice_log.jsonl"
ADVISOR_RECENT_ADVICE_FILE = Path.home() / ".spark" / "advisor" / "recent_advice.jsonl"
OUTCOMES_FILE = Path.home() / ".spark" / "outcomes.jsonl"
OUTCOME_LINKS_FILE = Path.home() / ".spark" / "outcome_links.jsonl"
IMPLICIT_FEEDBACK_FILE = Path.home() / ".spark" / "advisor" / "implicit_feedback.jsonl"
TRACE_EVENT_HISTORY_MAX = 12
TRACE_HISTORY_TEXT_MAX = 60

DEFAULT_PACKET_TTL_S = 900.0
MAX_INDEX_PACKETS = 2000
RELAXED_MATCH_WEIGHT_TOOL = 4.0
RELAXED_MATCH_WEIGHT_INTENT = 3.0
RELAXED_MATCH_WEIGHT_PLANE = 2.0
RELAXED_WILDCARD_TOOL_BONUS = 0.5
RELAXED_EFFECTIVENESS_WEIGHT = 2.0
RELAXED_LOW_EFFECTIVENESS_THRESHOLD = 0.3
RELAXED_LOW_EFFECTIVENESS_PENALTY = 0.5
RELAXED_MIN_MATCH_DIMENSIONS = 1
RELAXED_MIN_MATCH_SCORE = 3.0
DEFAULT_PACKET_RELAXED_MAX_CANDIDATES = 6
DEFAULT_PACKET_RELAXED_PREVIEW_CHARS = 360
DEFAULT_PACKET_LOOKUP_CANDIDATES = 6
# LLM reranking defaults moved to advisory_packet_llm_reranker.py
DEFAULT_OBSIDIAN_EXPORT_MAX_PACKETS = 300
DEFAULT_OBSIDIAN_EXPORT_ENABLED = False
DEFAULT_OBSIDIAN_AUTO_EXPORT = False
DEFAULT_OBSIDIAN_EXPORT_DIR = str(OBSIDIAN_EXPORT_DIR)
INDEX_SCHEMA_VERSION_KEY = "_schema_version"
INDEX_SCHEMA_VERSION = 2

REQUIRED_PACKET_FIELDS = {
    "packet_id",
    "project_key",
    "session_context_key",
    "tool_name",
    "intent_family",
    "task_plane",
    "advisory_text",
    "source_mode",
    "created_ts",
    "updated_ts",
    "fresh_until_ts",
    "lineage",
    "usage_count",
    "emit_count",
    "deliver_count",
    "helpful_count",
    "unhelpful_count",
    "noisy_count",
    "feedback_count",
    "acted_count",
    "blocked_count",
    "harmful_count",
    "ignored_count",
    "read_count",
    "effectiveness_score",
}
REQUIRED_LINEAGE_FIELDS = {"sources", "memory_absent_declared"}

_INDEX_CACHE: Optional[Dict[str, Any]] = None
_INDEX_CACHE_MTIME_NS: Optional[int] = None
_ALIASED_EXACT_KEYS: set[str] = set()

_OBSIDIAN_CONFIG_DIR_OVERRIDE: Optional[str] = None
PACKET_RELAXED_MAX_CANDIDATES = int(DEFAULT_PACKET_RELAXED_MAX_CANDIDATES)
PACKET_LOOKUP_CANDIDATES = int(DEFAULT_PACKET_LOOKUP_CANDIDATES)
# LLM reranking config globals now live in advisory_packet_llm_reranker module.
# Backward-compat aliases (read from extracted module):
PACKET_LOOKUP_LLM_ENABLED = False       # canonical: _llm_reranker.PACKET_LOOKUP_LLM_ENABLED
PACKET_LOOKUP_LLM_PROVIDER = "minimax"  # canonical: _llm_reranker.PACKET_LOOKUP_LLM_PROVIDER
PACKET_LOOKUP_LLM_FALLBACK_TO_SCORING = True
OBSIDIAN_EXPORT_ENABLED = bool(DEFAULT_OBSIDIAN_EXPORT_ENABLED)
OBSIDIAN_AUTO_EXPORT = bool(DEFAULT_OBSIDIAN_AUTO_EXPORT)
OBSIDIAN_EXPORT_MAX_PACKETS = int(DEFAULT_OBSIDIAN_EXPORT_MAX_PACKETS)
_OBSIDIAN_SYNC_STATUS: Dict[str, Any] = {
    "status": "not_run",
    "criticality": "non_critical",
    "message": "obsidian sync not attempted yet",
    "source": "advisory_packet_store",
}


def _obsidian_export_dir() -> Path:
    base = str(_OBSIDIAN_CONFIG_DIR_OVERRIDE or DEFAULT_OBSIDIAN_EXPORT_DIR).strip()
    if base:
        return Path(base).expanduser()
    return OBSIDIAN_EXPORT_DIR


def _obsidian_packets_dir() -> Path:
    return _obsidian_export_dir() / "packets"


def _obsidian_root_dir() -> Path:
    return _obsidian_export_dir()


def _obsidian_watchtower_file() -> Path:
    return _obsidian_root_dir() / "watchtower.md"


def _obsidian_index_file() -> Path:
    return _obsidian_packets_dir() / "index.md"


def _obsidian_enabled() -> bool:
    return bool(OBSIDIAN_EXPORT_ENABLED)


def _record_obsidian_status(
    status: str,
    *,
    message: str = "",
    source: str = "advisory_packet_store",
) -> Dict[str, Any]:
    _OBSIDIAN_SYNC_STATUS.update(
        {
            "status": status,
            "criticality": "non_critical",
            "message": str(message or "").strip(),
            "source": str(source),
        }
    )
    return dict(_OBSIDIAN_SYNC_STATUS)


def _get_obsidian_status() -> Dict[str, Any]:
    return dict(_OBSIDIAN_SYNC_STATUS)


def _decision_ledger_enabled() -> bool:
    return True


def _read_advisory_decision_ledger(limit: int = 120) -> List[Dict[str, Any]]:
    if not ADVISORY_DECISION_LEDGER_FILE.exists():
        return []
    try:
        limit_count = int(limit)
    except Exception:
        limit_count = 120
    if limit_count <= 0:
        limit_count = 0

    try:
        raw = ADVISORY_DECISION_LEDGER_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    if not raw:
        return []

    if limit_count > 0:
        raw = raw[-limit_count:]

    out: List[Dict[str, Any]] = []
    for line in raw:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _read_jsonl_lines(path: Path, limit: int = 1200) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        limit_count = max(0, int(limit or 0))
    except Exception:
        limit_count = 0

    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    if not raw:
        return []
    if limit_count > 0:
        raw = raw[-limit_count:]

    out: List[Dict[str, Any]] = []
    for line in raw:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _decision_ledger_meta() -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "path": str(ADVISORY_DECISION_LEDGER_FILE),
        "enabled": bool(_decision_ledger_enabled()),
        "exists": False,
    }
    if not ADVISORY_DECISION_LEDGER_FILE.exists():
        return meta
    try:
        raw = ADVISORY_DECISION_LEDGER_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return meta

    total = len([ln for ln in raw if ln.strip()])
    recent = _read_advisory_decision_ledger(limit=20)
    emitted_recent = sum(1 for row in recent if str(row.get("outcome", "")).strip().lower() == "emitted")
    meta.update(
        {
            "exists": True,
            "entry_count": int(total),
            "recent_count": int(len(recent)),
            "recent_emitted_count": int(emitted_recent),
            "recent_emission_rate": round(emitted_recent / max(len(recent), 1), 3) if recent else 0.0,
        }
    )
    return meta


def _trace_ids_for_packet(packet: Dict[str, Any]) -> List[str]:
    if not isinstance(packet, dict):
        return []
    out: List[str] = []
    seen: set[str] = set()

    lineage = packet.get("lineage") if isinstance(packet.get("lineage"), dict) else {}
    for trace_id in (str(lineage.get("trace_id") or "").strip(), str(packet.get("last_trace_id") or "").strip()):
        if trace_id and trace_id not in seen:
            out.append(trace_id)
            seen.add(trace_id)

    for row in packet.get("trace_usage_history") or []:
        if not isinstance(row, dict):
            continue
        trace_id = str(row.get("trace_id") or "").strip()
        if trace_id and trace_id not in seen:
            out.append(trace_id)
            seen.add(trace_id)
    return out


def _advice_ids_for_packet(packet: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    if not isinstance(packet, dict):
        return out
    seen: set[str] = set()
    for row in packet.get("advice_items") or []:
        if not isinstance(row, dict):
            continue
        advice_id = str(row.get("advice_id") or "").strip()
        if advice_id and advice_id not in seen:
            out.append(advice_id)
            seen.add(advice_id)
    return out


def _advice_insight_keys_for_packet(packet: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    if not isinstance(packet, dict):
        return out
    seen: set[str] = set()
    for row in packet.get("advice_items") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("insight_key") or "").strip()
        if key and key not in seen:
            out.append(key)
            seen.add(key)
    return out


def _normalize_trace_usage_history(
    history: Any,
    *,
    limit: int = TRACE_EVENT_HISTORY_MAX,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(history, list):
        return []
    max_items = max(1, int(limit or TRACE_EVENT_HISTORY_MAX))
    for row in history:
        if len(out) >= max_items:
            break
        if not isinstance(row, dict):
            continue
        payload = dict(row)
        trace_id = str(payload.get("trace_id") or "").strip()
        if trace_id:
            payload["trace_id"] = trace_id
        payload["tool_name"] = str(payload.get("tool_name") or "").strip()[:40]
        payload["route"] = str(payload.get("route") or "").strip()[:80]
        payload["emitted"] = bool(payload.get("emitted", False))
        try:
            payload["ts"] = float(payload.get("ts") or 0.0)
        except Exception:
            payload["ts"] = 0.0
        payload["route_order"] = int(payload.get("route_order") or len(out) + 1)
        out.append(payload)
    # Most recent at the end in the UI.
    return sorted(out, key=lambda row: float(row.get("ts", 0.0)), reverse=False)[-max_items:]


def _packet_trace_history_events(
    packet: Dict[str, Any],
    *,
    limit: int = 180,
) -> List[Dict[str, Any]]:
    if not isinstance(packet, dict):
        return []

    packet_id = str(packet.get("packet_id") or "").strip()
    if not packet_id:
        return []

    trace_ids = set(_trace_ids_for_packet(packet))
    advice_ids = set(_advice_ids_for_packet(packet))
    packet_insight_keys = set(_advice_insight_keys_for_packet(packet))
    linked_outcome_ids: set[str] = set()
    outcome_trace_by_id: Dict[str, str] = {}
    outcome_ts_by_id: Dict[str, float] = {}
    events: List[Dict[str, Any]] = []

    for row in _packet_decision_events(packet_id, limit=limit):
        normalized = dict(row)
        normalized["trace_system"] = "advisory_decision_ledger"
        events.append(normalized)

    if ADVISORY_ENGINE_LOG_FILE.exists():
        for row in _read_jsonl_lines(ADVISORY_ENGINE_LOG_FILE, limit=limit * 2):
            if not isinstance(row, dict):
                continue
            row_trace = str(row.get("trace_id") or "").strip()
            if str(row.get("packet_id") or "").strip() == packet_id or row_trace in trace_ids:
                normalized = dict(row)
                normalized["trace_system"] = "advisory_engine"
                events.append(normalized)

    if ADVISORY_RETRIEVAL_ROUTE_LOG_FILE.exists():
        for row in _read_jsonl_lines(ADVISORY_RETRIEVAL_ROUTE_LOG_FILE, limit=limit * 2):
            if not isinstance(row, dict):
                continue
            row_trace = str(row.get("trace_id") or "").strip()
            if row_trace in trace_ids:
                normalized = dict(row)
                normalized["trace_system"] = "advisor_retrieval_router"
                events.append(normalized)

    if ADVISORY_EMIT_FILE.exists():
        for row in _read_jsonl_lines(ADVISORY_EMIT_FILE, limit=limit * 2):
            if not isinstance(row, dict):
                continue
            row_trace = str(row.get("trace_id") or "").strip()
            if row_trace in trace_ids:
                normalized = dict(row)
                normalized["trace_system"] = "advisory_emit"
                events.append(normalized)

    if ADVISORY_LOW_AUTH_DEDUPE_FILE.exists():
        for row in _read_jsonl_lines(ADVISORY_LOW_AUTH_DEDUPE_FILE, limit=limit * 2):
            if not isinstance(row, dict):
                continue
            row_trace = str(row.get("trace_id") or "").strip()
            if row_trace not in trace_ids:
                continue
            normalized = dict(row)
            normalized["trace_system"] = "advisory_low_auth_dedupe"
            events.append(normalized)

    if ADVISORY_GLOBAL_DEDUPE_FILE.exists():
        for row in _read_jsonl_lines(ADVISORY_GLOBAL_DEDUPE_FILE, limit=limit * 2):
            if not isinstance(row, dict):
                continue
            row_trace = str(row.get("trace_id") or "").strip()
            if row_trace not in trace_ids:
                continue
            normalized = dict(row)
            normalized["trace_system"] = "advisory_global_dedupe"
            events.append(normalized)

    if ADVISOR_ADVICE_LOG_FILE.exists():
        for row in _read_jsonl_lines(ADVISOR_ADVICE_LOG_FILE, limit=limit * 2):
            if not isinstance(row, dict):
                continue
            row_trace = str(row.get("trace_id") or "").strip()
            if row_trace not in trace_ids:
                continue
            normalized = dict(row)
            normalized["trace_system"] = "advisor_advice_log"
            events.append(normalized)

    if ADVISOR_RECENT_ADVICE_FILE.exists():
        for row in _read_jsonl_lines(ADVISOR_RECENT_ADVICE_FILE, limit=limit * 2):
            if not isinstance(row, dict):
                continue
            row_trace = str(row.get("trace_id") or "").strip()
            if row_trace not in trace_ids:
                continue
            normalized = dict(row)
            normalized["trace_system"] = "advisor_recent_advice"
            events.append(normalized)

    if ADVICE_FEEDBACK_REQUESTS_FILE.exists():
        for row in _read_jsonl_lines(ADVICE_FEEDBACK_REQUESTS_FILE, limit=limit * 2):
            if not isinstance(row, dict):
                continue
            match_packet = str(row.get("packet_id") or "").strip() == packet_id
            row_trace = str(row.get("trace_id") or "").strip()
            if not match_packet and row_trace not in trace_ids:
                continue
            row_advice_ids = row.get("advice_ids") or []
            if not isinstance(row_advice_ids, list):
                row_advice_ids = []
            if not match_packet and not (advice_ids and set(str(x) for x in row_advice_ids).intersection(advice_ids)):
                continue
            normalized = dict(row)
            normalized["trace_system"] = "advice_feedback_request"
            events.append(normalized)

    if ADVICE_FEEDBACK_FILE.exists():
        for row in _read_jsonl_lines(ADVICE_FEEDBACK_FILE, limit=limit * 2):
            if not isinstance(row, dict):
                continue
            match_packet = str(row.get("packet_id") or "").strip() == packet_id
            row_trace = str(row.get("trace_id") or "").strip()
            if not match_packet and row_trace not in trace_ids:
                continue
            row_advice_ids = row.get("advice_ids") or []
            if not isinstance(row_advice_ids, list):
                row_advice_ids = []
            if not match_packet and not (advice_ids and set(str(x) for x in row_advice_ids).intersection(advice_ids)):
                continue
            normalized = dict(row)
            normalized["trace_system"] = "advice_feedback"
            events.append(normalized)

    if OUTCOMES_FILE.exists():
        for row in _read_jsonl_lines(OUTCOMES_FILE, limit=limit * 2):
            if not isinstance(row, dict):
                continue
            row_trace = str(row.get("trace_id") or "").strip()
            row_outcome_id = str(row.get("outcome_id") or "").strip()
            if not row_trace and not row_outcome_id:
                continue

            row_insight_keys: set[str] = set()
            outcome_insight = row.get("insight")
            if isinstance(outcome_insight, str):
                outcome_insight = outcome_insight.strip()
                if outcome_insight:
                    row_insight_keys.add(outcome_insight)
            elif isinstance(outcome_insight, list):
                for item in outcome_insight:
                    text = str(item or "").strip()
                    if text:
                        row_insight_keys.add(text)
            if packet_insight_keys:
                row_insight_keys.update(str(item).strip() for item in _safe_list([row.get("insight_key")], max_items=10) if str(item).strip())

            match_trace = bool(row_trace and row_trace in trace_ids)
            match_insight = bool(packet_insight_keys and row_insight_keys.intersection(packet_insight_keys))
            if not match_trace and not match_insight:
                continue

            normalized = dict(row)
            normalized["trace_system"] = "advisory_outcome"
            normalized.setdefault("trace_id", row_trace)
            normalized["event"] = f"outcome:{str(row.get('event_type') or 'recorded')}"
            if row_outcome_id:
                linked_outcome_ids.add(row_outcome_id)
                if row_trace:
                    outcome_trace_by_id[row_outcome_id] = row_trace
                try:
                    outcome_ts_by_id[row_outcome_id] = float(
                        row.get("created_at") or row.get("timestamp") or row.get("time") or row.get("event_ts") or 0.0
                    )
                except Exception:
                    outcome_ts_by_id[row_outcome_id] = 0.0
            if not normalized.get("ts"):
                normalized["ts"] = outcome_ts_by_id.get(row_outcome_id, 0.0)
            events.append(normalized)

    if OUTCOME_LINKS_FILE.exists():
        for row in _read_jsonl_lines(OUTCOME_LINKS_FILE, limit=limit * 2):
            if not isinstance(row, dict):
                continue
            row_outcome_id = str(row.get("outcome_id") or "").strip()
            if not row_outcome_id:
                continue
            if row_outcome_id not in linked_outcome_ids:
                continue
            normalized = dict(row)
            normalized["trace_system"] = "outcome_links"
            normalized["trace_id"] = str(outcome_trace_by_id.get(row_outcome_id, "")).strip()
            normalized["event"] = "outcome_link"
            if not normalized.get("ts"):
                normalized["ts"] = outcome_ts_by_id.get(row_outcome_id, 0.0)
            events.append(normalized)

    if IMPLICIT_FEEDBACK_FILE.exists():
        for row in _read_jsonl_lines(IMPLICIT_FEEDBACK_FILE, limit=limit * 2):
            if not isinstance(row, dict):
                continue
            row_trace = str(row.get("trace_id") or "").strip()
            if row_trace not in trace_ids:
                continue
            normalized = dict(row)
            normalized["trace_system"] = "implicit_feedback"
            if not normalized.get("ts"):
                normalized["ts"] = float(row.get("timestamp") or row.get("time") or 0.0)
            events.append(normalized)

    events = [row for row in events if isinstance(row, dict)]
    events.sort(key=lambda row: float(row.get("ts") or 0.0), reverse=True)
    return events[:limit]


def _trace_coverage_summary(
    packet: Dict[str, Any],
    *,
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, int]:
    coverage: Dict[str, int] = {
        "advisory_decision_ledger": 0,
        "advisory_engine": 0,
        "advisor_retrieval_router": 0,
        "advisory_emit": 0,
        "advisory_low_auth_dedupe": 0,
        "advisory_global_dedupe": 0,
        "advisor_advice_log": 0,
        "advisor_recent_advice": 0,
        "advice_feedback_request": 0,
        "advice_feedback": 0,
        "advisory_outcome": 0,
        "outcome_links": 0,
        "implicit_feedback": 0,
    }
    if not isinstance(packet, dict):
        return coverage
    packet_id = str(packet.get("packet_id") or "").strip()
    if not packet_id:
        return coverage
    rows = events
    if rows is None:
        rows = _packet_trace_history_events(packet, limit=180)
    for row in rows:
        system = str(row.get("trace_system") or "").strip()
        if system in coverage:
            coverage[system] += 1
    return coverage


def _load_packet_store_config(
    path: Optional[Path] = None,
    *,
    baseline_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load advisory packet-store tuneables through config authority."""
    tuneables = path or (Path.home() / ".spark" / "tuneables.json")
    resolved = resolve_section(
        "advisory_packet_store",
        baseline_path=baseline_path,
        runtime_path=tuneables,
    )
    return resolved.data if isinstance(resolved.data, dict) else {}


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_list(value: Any, *, max_items: int = 20) -> List[str]:
    out: List[str] = []
    if isinstance(value, (list, tuple, set)):
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            out.append(text)
            if len(out) >= max_items:
                break
    elif isinstance(value, str):
        text = value.strip()
        if text:
            out.append(text)
    return out


def _meta_count(row: Dict[str, Any], key: str, *, fallback_key: Optional[str] = None) -> int:
    if not isinstance(row, dict):
        return 0
    value = row.get(key)
    if key in row or fallback_key is None:
        return max(0, _to_int(value, 0))
    if fallback_key in row:
        return max(0, _to_int(row.get(fallback_key), 0))
    return 0


# ── LLM reranker (extracted to advisory_packet_llm_reranker.py) ──────
# LLM config globals now live in advisory_packet_llm_reranker module.
# apply_packet_store_config() updates them there via module reference.
import lib.advisory_packet_llm_reranker as _llm_reranker  # noqa: E402

from .advisory_packet_llm_reranker import (  # noqa: F401,E402 — re-export for compat
    _build_lookup_payload,
    _call_lookup_llm,
    _extract_json_like_array,
    _lookup_llm_api_key,
    _lookup_llm_url,
    _rerank_candidates_with_lookup_llm,
    _sanitize_lookup_provider,
)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _compute_effectiveness_score(
    *,
    helpful_count: int,
    unhelpful_count: int,
    noisy_count: int,
) -> float:
    # Simple Bayesian estimate with neutral prior + noise penalty.
    prior_good = 1.0
    prior_bad = 1.0
    effective_good = max(0.0, float(helpful_count)) + prior_good
    effective_bad = max(0.0, float(unhelpful_count)) + prior_bad
    score = effective_good / max(1.0, effective_good + effective_bad)
    score -= min(0.35, max(0, int(noisy_count)) * 0.05)
    return max(0.05, min(0.99, float(score)))


def _normalize_packet(packet: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(packet or {})
    out["read_count"] = max(0, _to_int(out.get("read_count", 0), 0))
    out["last_read_ts"] = float(_to_float(out.get("last_read_ts", 0.0), 0.0))
    out["last_read_route"] = str(out.get("last_read_route", "") or "")
    # Backwards compatibility with older packets where usage_count/deliver_count were
    # not tracked independently yet.
    out["usage_count"] = max(0, _to_int(out.get("usage_count", out.get("read_count", 0)), 0))
    out["emit_count"] = max(0, _to_int(out.get("emit_count", 0), 0))
    out["deliver_count"] = max(0, _to_int(out.get("deliver_count", out.get("emit_count", 0)), 0))
    out["helpful_count"] = max(0, _to_int(out.get("helpful_count", 0), 0))
    out["unhelpful_count"] = max(0, _to_int(out.get("unhelpful_count", 0), 0))
    out["noisy_count"] = max(0, _to_int(out.get("noisy_count", 0), 0))
    out["feedback_count"] = max(0, _to_int(out.get("feedback_count", 0), 0))
    out["acted_count"] = max(0, _to_int(out.get("acted_count", 0), 0))
    out["blocked_count"] = max(0, _to_int(out.get("blocked_count", 0), 0))
    out["harmful_count"] = max(0, _to_int(out.get("harmful_count", 0), 0))
    out["ignored_count"] = max(0, _to_int(out.get("ignored_count", 0), 0))
    out["last_trace_id"] = str(out.get("last_trace_id") or (out.get("lineage", {}).get("trace_id") if isinstance(out.get("lineage"), dict) else "") or "").strip()
    out["trace_usage_history"] = _normalize_trace_usage_history(
        out.get("trace_usage_history"),
        limit=TRACE_EVENT_HISTORY_MAX,
    )
    out["effectiveness_score"] = _compute_effectiveness_score(
        helpful_count=out["helpful_count"],
        unhelpful_count=out["unhelpful_count"],
        noisy_count=out["noisy_count"],
    )
    out["category_summary"] = _safe_list(out.get("category_summary"), max_items=20)
    out["source_summary"] = _safe_list(out.get("source_summary"), max_items=40)
    return out


def _now() -> float:
    return time.time()


def _ensure_dirs() -> None:
    PACKET_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # os.replace is atomic even on Windows (no unlink+rename race)
    os.replace(str(tmp), str(path))


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return dict(default)


def _packet_lookup_context(row: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    return {
        "packet_id": str(row.get("packet_id") or ""),
        "tool_name": str(row.get("tool_name") or ""),
        "intent_family": str(row.get("intent_family") or ""),
        "task_plane": str(row.get("task_plane") or ""),
        "project_key": str(row.get("project_key") or ""),
        "updated_ts": float(row.get("updated_ts") or 0.0),
        "fresh_until_ts": float(row.get("fresh_until_ts") or 0.0),
    }



def _packet_decision_events(packet_id: str, limit: int = 120) -> List[Dict[str, Any]]:
    if not packet_id:
        return []
    try:
        limit_count = max(1, min(int(limit or 0), 500))
    except Exception:
        limit_count = 120
    matched: List[Dict[str, Any]] = []
    for row in _read_advisory_decision_ledger(limit=limit_count * 3):
        try:
            if str(row.get("packet_id") or "") == str(packet_id):
                matched.append(dict(row))
        except Exception:
            continue
    return matched[:limit_count]


def _obsidian_payload(packet: Dict[str, Any]) -> str:
    packet_id = str(packet.get("packet_id") or "")
    if not packet_id:
        return ""
    project = str(packet.get("project_key") or "unknown_project")
    session_ctx = str(packet.get("session_context_key") or "")
    tool = str(packet.get("tool_name") or "*")
    intent = str(packet.get("intent_family") or "emergent_other")
    plane = str(packet.get("task_plane") or "build_delivery")
    source_mode = str(packet.get("source_mode") or "")
    advisory_text = str(packet.get("advisory_text") or "").strip()
    created_ts = float(packet.get("created_ts") or 0.0)
    updated_ts = float(packet.get("updated_ts") or 0.0)
    fresh_until_ts = float(packet.get("fresh_until_ts") or 0.0)
    sources = _safe_list(packet.get("source_summary"), max_items=30)
    categories = _safe_list(packet.get("category_summary"), max_items=20)
    source_line = ", ".join(sources) if sources else "unset"
    category_line = ", ".join(categories) if categories else "unset"
    lineage = packet.get("lineage") if isinstance(packet.get("lineage"), dict) else {}
    lineage_sources = _safe_list(lineage.get("sources"), max_items=20)
    memory_absent_declared = bool(lineage.get("memory_absent_declared", False))
    trace_id = str(lineage.get("trace_id", "") or "").strip()
    flags = _readiness_flags(packet, now_ts=_now())
    freshness_remaining = float(packet.get("fresh_until_ts", 0.0) or 0.0) - _now()
    if freshness_remaining < 0.0:
        freshness_remaining = 0.0
    last_read_ts = float(packet.get("last_read_ts", 0.0) or 0.0)
    last_read_at = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_read_ts))
        if last_read_ts > 0.0
        else "never"
    )

    def _yaml(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    def _yaml_list(values: List[str]) -> str:
        safe_values = [str(v) for v in _safe_list(values, max_items=20)]
        if not safe_values:
            return "[]"
        return "[" + ", ".join(_yaml(v) for v in safe_values) + "]"

    freshness_ratio = 0.0
    try:
        freshness_ratio = max(0.0, min(1.0, float(packet.get("freshness_ratio", 0.0) or 0.0)))
    except Exception:
        freshness_ratio = 0.0

    readiness = float(flags.get("readiness_score", 0.0) or 0.0)
    advice_rows = [row for row in (packet.get("advice_items") or []) if isinstance(row, dict)]

    def _bucket_source(value: str) -> str:
        source = str(value or "").strip().lower()
        if "eidos" in source or "distill" in source or "chip" in source:
            return "distilled"
        if "memory" in source or "mind" in source or "bridge" in source or "bank" in source or "semantic" in source:
            return "memory"
        if "packet" in source or "advisor" in source or "live" in source or "synth" in source:
            return "transformed"
        return "other"

    advice_by_bucket: Dict[str, List[Dict[str, Any]]] = {
        "memory": [],
        "distilled": [],
        "transformed": [],
        "other": [],
    }
    for row in advice_rows:
        advice_by_bucket[_bucket_source(str(row.get("source", "")))].append(row)

    packet_events = _packet_decision_events(packet_id, limit=50)
    packet_trace_events = _packet_trace_history_events(packet, limit=120)
    selected_total = sum(int(row.get("selected_count", 0) or 0) for row in packet_events)
    suppressed_total = sum(int(row.get("suppressed_count", 0) or 0) for row in packet_events)
    route_hint = str(packet_events[0].get("route", "") or "none") if packet_events else "none"
    trace_coverage = _trace_coverage_summary(packet, events=packet_trace_events)
    stage_counter: Counter[str] = Counter()
    suppression_reasons: List[str] = []
    for row in packet_events:
        stage_counter[str(row.get("stage", "") or "unspecified").strip() or "unspecified"] += 1
        suppression_reasons.extend(
            _safe_list([str(r.get("reason") or "") for r in row.get("suppressed_reasons", [])], max_items=4)
        )
    stage_text = ", ".join(f"{k}({v})" for k, v in stage_counter.most_common(8))
    if not stage_text:
        stage_text = "none"

    def _event_lines(event: Dict[str, Any], idx: int) -> List[str]:
        try:
            ts = float(
                event.get("ts")
                or event.get("created_at")
                or event.get("timestamp")
                or event.get("time")
                or 0.0
            )
        except Exception:
            ts = 0.0
        ts_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "unknown"
        stage = str(event.get("stage", "") or "unknown")
        outcome = str(event.get("outcome", "") or stage)
        suppressed = int(event.get("suppressed_count", 0) or 0)
        selected = int(event.get("selected_count", 0) or 0)
        reasons = _safe_list([str(r.get("reason") or "") for r in event.get("suppressed_reasons", [])], max_items=3)
        return [
            f"{idx}. {ts_text}",
            f"   - tool={str(event.get('tool', '') or '*')} route={str(event.get('route', '') or 'none')}",
            f"   - stage={stage} outcome={outcome}",
            f"   - selected={selected} suppressed={suppressed}",
            f"   - reasons={(', '.join(reasons) if reasons else 'none')}",
        ]

    def _trace_event_lines(event: Dict[str, Any], idx: int) -> List[str]:
        try:
            ts = float(
                event.get("ts")
                or event.get("created_at")
                or event.get("timestamp")
                or event.get("time")
                or 0.0
            )
        except Exception:
            ts = 0.0
        ts_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "unknown"
        system = str(event.get("trace_system") or "unknown")
        route = str(event.get("route", "") or event.get("path", "") or "none")
        tool = str(event.get("tool", "") or event.get("tool_name", "") or "*")
        stage = str(
            event.get("stage", "")
            or event.get("outcome", "")
            or event.get("status", "")
            or event.get("event", "")
            or "pipeline"
        )
        outcome = str(event.get("outcome", "") or event.get("stage", "") or "unspecified").strip() or "unspecified"
        event_name = str(event.get("event", "") or stage)
        insight_key = str(event.get("insight_key", "")).strip()
        outcome_id = str(event.get("outcome_id", "") or event.get("outcome_trace_id", "")).strip()
        trace_status = str(event.get("status", "") or event.get("source", "") or "n/a").strip()
        advice_rows = event.get("advice_ids") or event.get("advice_ids_merged") or event.get("advice_items") or []
        advice_count = len(advice_rows) if isinstance(advice_rows, (list, tuple)) else 0
        selected = int(event.get("selected_count", 0) or 0)
        suppressed = int(event.get("suppressed_count", 0) or 0)
        return [
            f"{idx}. {ts_text} [{system}]",
            f"   - tool={tool} route={route}",
            f"   - stage={stage} outcome={outcome}",
            f"   - event={event_name}",
            f"   - trace_status={trace_status} insight={insight_key or 'none'}",
            f"   - outcome_id={outcome_id or 'none'}",
            f"   - trace_id={str(event.get('trace_id') or 'none')}",
            f"   - advice_count={advice_count} selected={selected} suppressed={suppressed}",
        ]

    def _advice_lines(items: List[Dict[str, Any]], title: str, limit: int = 8) -> List[str]:
        if not items:
            return [f"### {title}", "- none"]
        out: List[str] = [f"### {title} ({len(items)} items)"]
        for idx, item in enumerate(items[:limit], start=1):
            if not isinstance(item, dict):
                continue
            aid = str(item.get("advice_id") or f"item_{idx}")
            source = str(item.get("source") or "unknown")
            category = str(item.get("category") or item.get("source") or "general")
            text = str(item.get("text") or "").strip()
            confidence = item.get("confidence")
            context_match = item.get("context_match")
            try:
                confidence_text = f"{float(confidence):.2f}"
            except Exception:
                confidence_text = "n/a"
            try:
                context_text = f"{float(context_match):.2f}"
            except Exception:
                context_text = "n/a"
            out.append(f"{idx}. {aid}")
            out.append(f"- source={source} bucket={_bucket_source(source)} category={category}")
            out.append(f"- confidence={confidence_text} context_match={context_text}")
            reason = str(item.get("reason") or "").strip()
            if reason:
                out.append(f"- reason={reason}")
            if text:
                out.append(f"- text={text}")
            proof_refs = item.get("proof_refs")
            if isinstance(proof_refs, dict) and proof_refs:
                out.append(f"- evidence_hash={str(item.get('evidence_hash') or 'n/a')}")
                proof_bits: List[str] = []
                if str(proof_refs.get("trace_id") or "").strip():
                    proof_bits.append(f"trace={str(proof_refs.get('trace_id') or '')}")
                if str(proof_refs.get("insight_key") or "").strip():
                    proof_bits.append(f"insight={str(proof_refs.get('insight_key') or '')}")
            if proof_bits:
                out.append("- proof=" + ", ".join(proof_bits))
        return out

    def _short_text(value: Any, max_chars: int = 240) -> str:
        text = str(value or "").strip().replace("\n", " ").replace("\r", " ")
        if not text:
            return "(empty)"
        if len(text) <= max_chars:
            return text
        return text[: max(1, max_chars - 1)].rstrip() + "…"

    source_counter: Counter[str] = Counter()
    route_history: List[str] = []
    outcome_counter: Counter[str] = Counter()
    for row in packet_events:
        route = str(row.get("route", "") or "none").strip() or "none"
        if route not in route_history:
            route_history.append(route)
        outcome = str(row.get("outcome", "") or row.get("stage", "") or "unspecified").strip().lower()
        if not outcome:
            outcome = "unspecified"
        outcome_counter[outcome] += 1
        row_sources = row.get("source_counts")
        if isinstance(row_sources, dict):
            for source_name, count in row_sources.items():
                try:
                    source_counter[str(source_name)] += int(count or 0)
                except Exception:
                    continue

    outcome_summary = ", ".join(f"{name}:{count}" for name, count in outcome_counter.most_common()) or "none"
    source_summary_for_events = ", ".join(_short_text(name) for name in _safe_list(list(source_counter.keys()), max_items=20)) or "none"

    lines = [
        "---",
        "type: spark-advisory-packet",
        f"packet_id: {_yaml(packet_id)}",
        f"project_key: {_yaml(project)}",
        f"session_context_key: {_yaml(session_ctx)}",
        f"tool_name: {_yaml(tool)}",
        f"intent_family: {_yaml(intent)}",
        f"task_plane: {_yaml(plane)}",
        f"source_mode: {_yaml(source_mode)}",
        f"created_at: {_yaml(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created_ts)) if created_ts else '')}",
        f"updated_at: {_yaml(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(updated_ts)) if updated_ts else '')}",
        f"fresh_until: {_yaml(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(fresh_until_ts)) if fresh_until_ts else '')}",
        f"ready_for_use: {_yaml(bool(flags.get('ready_for_use', False)))}",
        f"fresh_now: {_yaml(bool(flags.get('is_fresh', False)))}",
        f"invalidated: {_yaml(bool(packet.get('invalidated', False)))}",
        f"invalidation_reason: {_yaml(str(packet.get('invalidate_reason', '') or '')[:240])}",
        f"effectiveness_score: {_yaml(float(packet.get('effectiveness_score', 0.5) or 0.5))}",
        f"readiness_score: {_yaml(readiness)}",
        f"freshness_ratio: {_yaml(freshness_ratio)}",
        f"usage_count: {_yaml(int(packet.get('usage_count', 0) or 0))}",
        f"emit_count: {_yaml(int(packet.get('emit_count', 0) or 0))}",
        f"deliver_count: {_yaml(int(packet.get('deliver_count', packet.get('emit_count', 0)) or 0))}",
        f"helpful_count: {_yaml(int(packet.get('helpful_count', 0) or 0))}",
        f"unhelpful_count: {_yaml(int(packet.get('unhelpful_count', 0) or 0))}",
        f"noisy_count: {_yaml(int(packet.get('noisy_count', 0) or 0))}",
        f"sources: {_yaml_list(sources)}",
        f"categories: {_yaml_list(categories)}",
        f"advice_count: {_yaml(len(advice_rows))}",
        f"lineage_sources: {_yaml_list(lineage_sources)}",
        f"memory_absent_declared: {_yaml(memory_absent_declared)}",
        f"trace_id: {_yaml(trace_id or 'none')}",
        f"selected_total: {_yaml(selected_total)}",
        f"suppressed_total: {_yaml(suppressed_total)}",
        f"route_history: {_yaml_list(route_history)}",
        f"outcomes: {_yaml(outcome_summary)}",
        f"event_sources: {_yaml(source_summary_for_events)}",
        f"tags: ['spark', 'advisory', 'watchtower', {_yaml(tool)}, {_yaml(intent)}]",
        "---",
        "",
        f"# Packet {packet_id} | {tool} | {intent}",
        "",
        "## Packet story for humans",
        f"- freshness: {'fresh' if bool(flags.get('is_fresh')) else 'stale'}",
        f"- readiness: {readiness:.3f}",
        f"- selected in decisions: {selected_total}",
        f"- suppressed in decisions: {suppressed_total}",
        f"- route history: {', '.join(route_history) if route_history else route_hint}",
        f"- last read: {last_read_at}",
        "",
        "## Here are the memories",
        f"- lineage sources: {', '.join(lineage_sources) if lineage_sources else 'none'}",
        f"- memory_absent_declared: {memory_absent_declared}",
        f"- source_mode: `{source_mode}`",
        f"- trace_id: `{trace_id or 'none'}`",
        f"- memory summary: {_short_text('; '.join(_short_text(row.get('text', ''), 120) for row in advice_by_bucket['memory']), 220) if advice_by_bucket['memory'] else '(no memory-derived rows captured)'}",
        "",
        *_advice_lines(advice_by_bucket['memory'], "Memory-derived inputs"),
        "",
        "## Here are the distilled versions",
        f"- memory-derived: {len(advice_by_bucket['memory'])}",
        f"- distillations: {len(advice_by_bucket['distilled'])}",
        f"- transformed/live: {len(advice_by_bucket['transformed'])}",
        f"- other: {len(advice_by_bucket['other'])}",
        "",
        *_advice_lines(advice_by_bucket['distilled'], "Distilled"),
        *_advice_lines(advice_by_bucket['other'], "Other"),
        "",
        "## Here are transformed ones",
        *_advice_lines(advice_by_bucket['transformed'], "Transformed/live"),
        "",
        "## Here is how they got transformed",
        f"- advisory route: `{route_hint}`",
        f"- route history: {', '.join(route_history) if route_history else route_hint}",
        f"- gate stages seen: {stage_text}",
        f"- decision outcomes: {outcome_summary}",
        f"- suppression reasons: {', '.join(s for s in suppression_reasons if s) if suppression_reasons else 'none'}",
        f"- advisory evidence sources: {source_summary_for_events}",
        "",
        "## Advisory Packet Metadata",
        f"- Project: `{project}`",
        f"- Session key: `{session_ctx}`",
        f"- Tool context: `{tool}`",
        f"- Intent family: `{intent}`",
        f"- Task plane: `{plane}`",
        f"- Sources: {source_line}",
        f"- Categories: {category_line}",
        f"- Invalidation reason: `{str(packet.get('invalidate_reason', '') or 'none')}`",
        f"- Readiness: {float(flags.get('readiness_score', 0.0) or 0.0):.3f}",
        f"- Fresh now: {'yes' if bool(flags.get('is_fresh')) else 'no'}",
        f"- Ready for use: {bool(flags.get('ready_for_use'))}",
        f"- Freshness remaining (s): {int(freshness_remaining)}",
        f"- Last read at: {last_read_at}",
        f"- Last read route: `{str(packet.get('last_read_route', '') or 'none')}`",
        f"- Effectiveness: {float(packet.get('effectiveness_score', 0.5) or 0.5):.3f}",
        f"- Usage: {int(packet.get('usage_count', 0) or 0)}",
        f"- Deliveries: {int(packet.get('deliver_count', 0) or 0)}",
        f"- Emitted: {int(packet.get('emit_count', 0) or 0)}",
        f"- Feedback: {int(packet.get('feedback_count', 0) or 0)}",
        f"- Helpful: {int(packet.get('helpful_count', 0) or 0)}",
        f"- Unhelpful: {int(packet.get('unhelpful_count', 0) or 0)}",
        f"- Noisy: {int(packet.get('noisy_count', 0) or 0)}",
        "",
        "## Here is what is ready for advisory",
        f"- ready_for_use: {bool(flags.get('ready_for_use', False))}",
        f"- selected total (all events): {selected_total}",
        f"- suppressed total (all events): {suppressed_total}",
        "",
        "## Here is what is getting pulled as advisory",
    ]
    if packet_events:
        for idx, event in enumerate(packet_events[:25], start=1):
            lines.extend(_event_lines(event, idx))
            lines.append("")
    else:
        lines.append("- no decision events yet (ready to observe once advisory pulls happen)")
        lines.append("")

    lines.extend(
        [
            "## Advisory Text (latest merged packet)",
            advisory_text if advisory_text else "*(no advisory text payload)*",
            "",
            "## What Meta-Ralph said",
            f"- outcome route: `{route_hint}`",
            f"- selected events: {selected_total}",
            f"- suppressed events: {suppressed_total}",
            f"- outcomes seen: {outcome_summary}",
            f"- decision event sources: {source_summary_for_events}",
            "- check `~/.spark/advisory_engine.jsonl`, `~/.spark/advisory_emit.jsonl`, `~/.spark/advisory_decision_ledger.jsonl`, `~/.spark/advisor/retrieval_router.jsonl` for score trail",
            "",
            "## Advisory Traceability Timeline",
        ]
    )
    if packet_trace_events:
        for idx, event in enumerate(packet_trace_events[:35], start=1):
            lines.extend(_trace_event_lines(event, idx))
            lines.append("")
    else:
        lines.append("- no trace events available yet")
        lines.append("")

    lines.extend(
        [
            "## Trace-system coverage",
            f"- advisory_decision_ledger: {'ok' if trace_coverage.get('advisory_decision_ledger', 0) > 0 else 'missing'} ({trace_coverage.get('advisory_decision_ledger', 0)})",
            f"- advisory_engine: {'ok' if trace_coverage.get('advisory_engine', 0) > 0 else 'missing'} ({trace_coverage.get('advisory_engine', 0)})",
            f"- advisor_retrieval_router: {'ok' if trace_coverage.get('advisor_retrieval_router', 0) > 0 else 'missing'} ({trace_coverage.get('advisor_retrieval_router', 0)})",
            f"- advisory_emit: {'ok' if trace_coverage.get('advisory_emit', 0) > 0 else 'missing'} ({trace_coverage.get('advisory_emit', 0)})",
            f"- advisory_low_auth_dedupe: {'ok' if trace_coverage.get('advisory_low_auth_dedupe', 0) > 0 else 'missing'} ({trace_coverage.get('advisory_low_auth_dedupe', 0)})",
            f"- advisory_global_dedupe: {'ok' if trace_coverage.get('advisory_global_dedupe', 0) > 0 else 'missing'} ({trace_coverage.get('advisory_global_dedupe', 0)})",
            f"- advisor_advice_log: {'ok' if trace_coverage.get('advisor_advice_log', 0) > 0 else 'missing'} ({trace_coverage.get('advisor_advice_log', 0)})",
            f"- advisor_recent_advice: {'ok' if trace_coverage.get('advisor_recent_advice', 0) > 0 else 'missing'} ({trace_coverage.get('advisor_recent_advice', 0)})",
            f"- advice_feedback_request: {'ok' if trace_coverage.get('advice_feedback_request', 0) > 0 else 'missing'} ({trace_coverage.get('advice_feedback_request', 0)})",
            f"- advice_feedback: {'ok' if trace_coverage.get('advice_feedback', 0) > 0 else 'missing'} ({trace_coverage.get('advice_feedback', 0)})",
            f"- advisory_outcome: {'ok' if trace_coverage.get('advisory_outcome', 0) > 0 else 'missing'} ({trace_coverage.get('advisory_outcome', 0)})",
            f"- outcome_links: {'ok' if trace_coverage.get('outcome_links', 0) > 0 else 'missing'} ({trace_coverage.get('outcome_links', 0)})",
            f"- implicit_feedback: {'ok' if trace_coverage.get('implicit_feedback', 0) > 0 else 'missing'} ({trace_coverage.get('implicit_feedback', 0)})",
            "",
            "## Here is what may need work",
        ]
    )
    trace_systems_required = {
        "advisory_decision_ledger",
        "advisory_engine",
        "advisor_retrieval_router",
        "advisory_emit",
        "advice_feedback",
        "advice_feedback_request",
    }
    trace_systems_optional = {
        "advisory_outcome",
        "outcome_links",
        "implicit_feedback",
    }
    missing_systems = [name for name in trace_systems_required if trace_coverage.get(name, 0) <= 0]
    if missing_systems:
        lines.append(f"- missing trace systems this cycle: {', '.join(missing_systems)}")
    missing_optional_systems = [name for name in trace_systems_optional if trace_coverage.get(name, 0) <= 0]
    if missing_optional_systems:
        lines.append(f"- optional trace systems not yet seen for this packet: {', '.join(missing_optional_systems)}")
    if not packet.get("trace_usage_history"):
        lines.append("- trace usage history: no usage/outcome markers yet")
    lines.append(f"- timeline depth: {len(packet_trace_events)} events")
    if bool(packet.get("invalidated", False)):
        lines.append(f"- invalidated: yes ({str(packet.get('invalidate_reason', '') or 'none')})")
    else:
        lines.append("- invalidated: no")
    if not bool(flags.get("is_fresh", False)):
        lines.append("- stale: packet has exceeded freshness window")
    if int(packet.get("noisy_count", 0) or 0) > 0:
        lines.append(f"- noisy_count: {int(packet.get('noisy_count', 0) or 0)}")
    if readiness < 0.35:
        lines.append("- readiness is below advisory threshold 0.35")
    if not advice_rows:
        lines.append("- no structured advice rows: difficult to trace source transform")
    elif len(advice_rows) < 2:
        lines.append("- very small advisory payload: consider collecting more evidence")
    else:
        lines.append(f"- structured advice rows captured: {len(advice_rows)}")
    lines.append(f"- other bucket size: {len(advice_by_bucket['other'])}")

    return "\n".join(lines).strip() + "\n"


def _packet_readiness_score(packet: Dict[str, Any], now_ts: Optional[float] = None) -> float:
    if not isinstance(packet, dict):
        return 0.0
    if bool(packet.get("invalidated")):
        return 0.0
    now_value = float(now_ts if now_ts is not None else _now())
    freshness_until = float(packet.get("fresh_until_ts", 0.0) or 0.0)
    if freshness_until <= now_value:
        return 0.0

    updated_ts = float(packet.get("updated_ts", 0.0) or 0.0)
    ttl = float(max(30.0, float(packet.get("ttl_s", 0.0) or (freshness_until - updated_ts) or DEFAULT_PACKET_TTL_S)))
    remaining = min(ttl, max(0.0, freshness_until - now_value))
    freshness_ratio = remaining / ttl if ttl > 0 else 0.0
    effectiveness = float(packet.get("effectiveness_score", 0.5) or 0.5)
    effectiveness = max(0.0, min(1.0, effectiveness))
    score = (0.35 * max(0.0, min(1.0, freshness_ratio))) + (0.65 * effectiveness)
    return max(0.0, min(1.0, score))


def _readiness_flags(packet: Dict[str, Any], now_ts: Optional[float] = None) -> Dict[str, Any]:
    now_value = float(now_ts if now_ts is not None else _now())
    freshness_until = float(packet.get("fresh_until_ts", 0.0) or 0.0)
    is_fresh = (not bool(packet.get("invalidated"))) and (freshness_until >= now_value)
    score = _packet_readiness_score(packet, now_value)
    return {
        "is_fresh": bool(is_fresh),
        "ready_for_use": bool(is_fresh and score >= 0.35),
        "readiness_score": float(score),
        "ready_age_s": max(0.0, now_value - float(packet.get("updated_ts", 0.0) or 0.0)),
    }


def _obsidian_catalog_entry(packet: Dict[str, Any], now_ts: Optional[float] = None) -> Dict[str, Any]:
    now_value = float(now_ts if now_ts is not None else _now())
    flags = _readiness_flags(packet, now_ts=now_value)
    fresh_remaining = float(packet.get("fresh_until_ts", 0.0) or 0.0) - now_value
    if fresh_remaining < 0.0:
        fresh_remaining = 0.0
    return {
        "packet_id": str(packet.get("packet_id") or ""),
        "project_key": str(packet.get("project_key") or ""),
        "session_context_key": str(packet.get("session_context_key") or ""),
        "tool_name": str(packet.get("tool_name") or ""),
        "intent_family": str(packet.get("intent_family") or ""),
        "task_plane": str(packet.get("task_plane") or ""),
        "updated_ts": float(packet.get("updated_ts", 0.0) or 0.0),
        "fresh_until_ts": float(packet.get("fresh_until_ts", 0.0) or 0.0),
        "ready_for_use": bool(flags.get("ready_for_use")),
        "is_fresh": bool(flags.get("is_fresh")),
        "invalidated": bool(packet.get("invalidated", False)),
        "invalidate_reason": str(packet.get("invalidate_reason", "") or ""),
        "freshness_remaining_s": float(fresh_remaining),
        "readiness_score": float(flags.get("readiness_score", 0.0)),
        "effectiveness_score": float(packet.get("effectiveness_score", 0.5) or 0.5),
        "read_count": int(packet.get("read_count", 0) or 0),
        "last_read_ts": float(packet.get("last_read_ts", 0.0) or 0.0),
        "last_read_route": str(packet.get("last_read_route", "") or ""),
        "usage_count": int(packet.get("usage_count", 0) or 0),
        "emit_count": int(packet.get("emit_count", 0) or 0),
        "deliver_count": int(packet.get("deliver_count", packet.get("emit_count", 0)) or 0),
        "last_trace_id": str(packet.get("last_trace_id", "") or "").strip(),
        "trace_usage_history": _normalize_trace_usage_history(
            packet.get("trace_usage_history", []),
            limit=TRACE_EVENT_HISTORY_MAX,
        ),
        "source_summary": _safe_list(packet.get("source_summary"), max_items=10),
        "category_summary": _safe_list(packet.get("category_summary"), max_items=8),
    }


def _build_obsidian_catalog(
    *,
    now_ts: Optional[float] = None,
    only_ready: bool = False,
    include_stale: bool = False,
    include_invalid: bool = False,
    limit: int = 0,
) -> List[Dict[str, Any]]:
    index = _load_index()
    meta = index.get("packet_meta") or {}
    out: List[Dict[str, Any]] = []
    now_value = float(now_ts if now_ts is not None else _now())
    limit_count = max(0, int(limit or 0))
    for packet_id, row in meta.items():
        pid = str(packet_id or "").strip()
        if not pid:
            continue
        row_packet = get_packet(pid)
        if not row_packet:
            continue
        flags = _readiness_flags(row_packet, now_value)
        if not include_invalid and bool(row_packet.get("invalidated")):
            continue
        if not include_stale and not bool(flags.get("is_fresh", False)):
            continue
        if only_ready and not bool(flags.get("ready_for_use", False)):
            continue
        entry = _obsidian_catalog_entry(row_packet, now_ts=now_value)
        if not entry.get("packet_id"):
            continue
        out.append(entry)

    out.sort(key=lambda row: (float(row.get("readiness_score", 0.0) or 0.0), float(row.get("updated_ts", 0.0) or 0.0), str(row.get("packet_id") or "")), reverse=True)
    if limit_count > 0:
        return out[:limit_count]
    return out


def _render_obsidian_index(lines: List[str], catalog: List[Dict[str, Any]]) -> None:
    try:
        watchtower = _read_advisory_decision_ledger(limit=max(0, int(OBSIDIAN_EXPORT_MAX_PACKETS // 3)))
    except Exception:
        watchtower: List[Dict[str, Any]] = []
    try:
        watchtower_stage: Counter[str] = Counter()
        for row in watchtower:
            stage = str(row.get("stage", "") or "unspecified").strip() or "unspecified"
            watchtower_stage[stage] += 1
    except Exception:
        watchtower_stage = Counter()

    def _format_status_values(values: List[str]) -> str:
        if not values:
            return "-"
        return " ".join(f"`{v}`" for v in values[:8])

    def _render_obsidian_counter_lines(title: str, counter: Counter[str], limit: int = 8) -> List[str]:
        items = [f"{k} ({v})" for k, v in counter.most_common(limit)]
        if not items:
            return [f"- {title}: none"]
        return [f"- {title}: {', '.join(items)}"]

    category_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()
    project_counter: Counter[str] = Counter()
    tool_counter: Counter[str] = Counter()
    intent_counter: Counter[str] = Counter()
    pulled_ids: set[str] = set()
    emitted_ids: set[str] = set()
    suppressed_ids: set[str] = set()
    trace_linked_count = 0
    trace_history_count = 0
    for row in catalog:
        for category in _safe_list(row.get("category_summary"), max_items=20):
            if category:
                category_counter[str(category)] += 1
        for source in _safe_list(row.get("source_summary"), max_items=20):
            if source:
                source_counter[str(source)] += 1
        project = str(row.get("project_key") or "unknown_project").strip()
        if project:
            project_counter[project] += 1
        tool = str(row.get("tool_name") or "*").strip()
        if tool:
            tool_counter[tool] += 1
        intent = str(row.get("intent_family") or "emergent_other").strip()
        if intent:
            intent_counter[intent] += 1
        if str(row.get("last_trace_id") or "").strip():
            trace_linked_count += 1
        if row.get("trace_usage_history"):
            trace_history_count += 1

    ready = [r for r in catalog if bool(r.get("ready_for_use"))]
    invalid = [r for r in catalog if bool(r.get("invalidated"))]
    stale = [r for r in catalog if not bool(r.get("is_fresh")) and not bool(r.get("invalidated"))]
    for row in watchtower:
        packet_id = str(row.get("packet_id") or "").strip()
        if not packet_id:
            continue
        pulled_ids.add(packet_id)
        if int(row.get("selected_count", 0) or 0) > 0 or str(row.get("outcome", "") or "").strip().lower() == "emitted":
            emitted_ids.add(packet_id)
        else:
            suppressed_ids.add(packet_id)

    lines.append("# SPARK Advisory Packet Catalog")
    lines.append("")
    lines.extend(
        [
            "## How to use this view",
            "- Think of this as the **operational entry point**.",
            "- [[../watchtower|Open watchtower dashboard]] for suppression + trend context.",
            "",
            f"- updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(_now()))}",
            f"- entries: {len(catalog)}",
            f"- ready now: {len(ready)}",
            f"- stale: {len(stale)}",
            f"- invalidated: {len(invalid)}",
            f"- recent suppression events: {len(watchtower)}",
            f"- packets with advisory pull events: {len(pulled_ids)}",
            f"- packets seen as emitted: {len(emitted_ids)}",
            f"- packets with active trace lineage: {trace_linked_count}",
            f"- packets with local trace history entries: {trace_history_count}",
            "",
        ]
    )
    unused = [r for r in catalog if str(r.get("packet_id") or "") not in pulled_ids]
    never_used = [r for r in ready if str(r.get("packet_id") or "") not in pulled_ids]
    lines.extend(
        [
            "## Readiness and usage snapshot",
            f"- never pulled: {len(unused)}",
            f"- ready + never pulled: {len(never_used)}",
            ""
        ]
    )
    lines.extend(
        [
            "## Distribution snapshot",
            *_render_obsidian_counter_lines("top sources", source_counter),
            *_render_obsidian_counter_lines("top categories", category_counter),
            *_render_obsidian_counter_lines("top projects", project_counter),
            *_render_obsidian_counter_lines("top tools", tool_counter),
            *_render_obsidian_counter_lines("top intents", intent_counter),
            "",
        ]
    )

    lines.append("## Watchtower highlights")
    if watchtower_stage:
        lines.append(
            "- recent stages: "
            + ", ".join(f"{k}({v})" for k, v in watchtower_stage.most_common(8))
        )
    else:
        lines.append("- no recent suppression events")
    lines.append("")

    if ready:
        lines.append("## Top ready packets (open first)")
        ready_rows = sorted(
            ready,
            key=lambda row: (
                float(row.get("readiness_score", 0.0) or 0.0),
                float(row.get("effectiveness_score", 0.0) or 0.0),
                float(row.get("updated_ts", 0.0) or 0.0),
            ),
            reverse=True,
        )[:12]
        for idx, row in enumerate(ready_rows, start=1):
            packet_id = str(row.get("packet_id") or "")
            readiness = float(row.get("readiness_score") or 0.0)
            impact = float(row.get("effectiveness_score") or 0.0)
            stage = str(row.get("stage", "") or "unknown")
            lines.append(
                f"{idx}. [[{packet_id}]] readiness={readiness:.2f} effect={impact:.2f} stage={stage} "
                f"| sources: {_format_status_values(_safe_list(row.get('source_summary'), max_items=4))}"
            )
    else:
        lines.append("## Top ready packets")
        lines.append("- no ready packets currently")
    lines.append("")

    lines.append("## Quick pullability list")
    if never_used:
        lines.append("### Ready packets with no pull history (investigate these first)")
        for idx, row in enumerate(never_used[:10], start=1):
            packet_id = str(row.get("packet_id") or "")
            readiness = float(row.get("readiness_score", 0.0) or 0.0)
            lines.append(
                f"{idx}. [[{packet_id}]] readiness={readiness:.2f} "
                "| selected=0 suppressed=0 (no advisory pulls)"
            )
        lines.append("")
    elif ready:
        lines.append("- ready packets all have recent pull history")
        lines.append("")
    else:
        lines.append("- no ready packets currently")
        lines.append("")

    if emitted_ids:
        lines.append("### Recently emitted packets")
        for idx, row in enumerate(ready[:20], start=1):
            pid = str(row.get("packet_id") or "")
            if pid not in emitted_ids:
                continue
            selected_total = sum(1 for row_evt in watchtower if str(row_evt.get("packet_id") or "") == pid and int(row_evt.get("selected_count", 0) or 0) > 0)
            lines.append(f"{idx}. [[{pid}]] selected_hits={selected_total}")
        lines.append("")

    lines.append("## Packet catalog snapshot")
    for idx, row in enumerate(catalog[:80], start=1):
        packet_id = str(row.get("packet_id") or "")
        project_key = str(row.get("project_key") or "unknown_project")
        task_plane = str(row.get("task_plane") or "build_delivery")
        readiness = float(row.get("readiness_score") or 0.0)
        freshness = "fresh" if bool(row.get("is_fresh")) else "stale"
        updated_ts = float(row.get("updated_ts", 0.0) or 0.0)
        updated_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(updated_ts)) if updated_ts else "unknown"
        lines.append(
            f"{idx}. [[{packet_id}]] project={project_key} plane={task_plane} "
            f"readiness={readiness:.2f} {freshness} updated={updated_text}"
        )
    lines.append("")


def _render_obsidian_watchtower(lines: List[str], catalog: List[Dict[str, Any]]) -> None:
    now_value = _now()
    now_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_value))
    ready = [r for r in catalog if bool(r.get("ready_for_use"))]
    invalid = [r for r in catalog if bool(r.get("invalidated"))]
    stale = [r for r in catalog if not bool(r.get("is_fresh")) and not bool(r.get("invalidated"))]

    source_counter: Counter[str] = Counter()
    project_counter: Counter[str] = Counter()
    tool_counter: Counter[str] = Counter()
    intent_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    pulled_ids: set[str] = set()
    emitted_ids: set[str] = set()
    suppressed_ids: set[str] = set()
    trace_linked_count = 0
    trace_history_count = 0
    for row in catalog:
        for source in _safe_list(row.get("source_summary"), max_items=20):
            if source:
                source_counter[str(source)] += 1
        for category in _safe_list(row.get("category_summary"), max_items=20):
            if category:
                category_counter[str(category)] += 1
        project_counter[str(row.get("project_key") or "unknown_project")] += 1
        tool_counter[str(row.get("tool_name") or "*")] += 1
        intent_counter[str(row.get("intent_family") or "emergent_other")] += 1
        if str(row.get("last_trace_id") or "").strip():
            trace_linked_count += 1
        if row.get("trace_usage_history"):
            trace_history_count += 1
    try:
        watchtower = _read_advisory_decision_ledger(limit=max(0, int(OBSIDIAN_EXPORT_MAX_PACKETS // 2)))
    except Exception:
        watchtower = []
    watchtower_reasons: Counter[str] = Counter()
    watchtower_stage: Counter[str] = Counter()
    for row in watchtower:
        stage = str(row.get("stage", "") or "unknown").strip() or "unknown"
        watchtower_stage[stage] += 1
        for reason in _safe_list([str(r.get("reason") or "") for r in row.get("suppressed_reasons", [])], max_items=8):
            if reason:
                watchtower_reasons[str(reason)] += 1
        packet_id = str(row.get("packet_id") or "").strip()
        if packet_id:
            pulled_ids.add(packet_id)
            if int(row.get("selected_count", 0) or 0) > 0 or str(row.get("outcome", "") or "").strip().lower() == "emitted":
                emitted_ids.add(packet_id)
            else:
                suppressed_ids.add(packet_id)

    trace_systems_all: List[str] = [
        "advisory_decision_ledger",
        "advisory_engine",
        "advisor_retrieval_router",
        "advisory_emit",
        "advisory_low_auth_dedupe",
        "advisory_global_dedupe",
        "advisor_advice_log",
        "advisor_recent_advice",
        "advice_feedback_request",
        "advice_feedback",
        "advisory_outcome",
        "outcome_links",
        "implicit_feedback",
    ]
    trace_system_packets: Dict[str, set[str]] = {name: set() for name in trace_systems_all}
    packet_trace_systems: Dict[str, set[str]] = {}
    sample_size = min(120, len(catalog))
    for row in catalog[:sample_size]:
        pid = str(row.get("packet_id") or "").strip()
        if not pid:
            continue
        packet_systems: set[str] = set()
        try:
            for event in _packet_trace_history_events(row, limit=120):
                system = str(event.get("trace_system") or "").strip()
                if system in trace_system_packets:
                    trace_system_packets[system].add(pid)
                if system:
                    packet_systems.add(system)
        except Exception:
            continue
        packet_trace_systems[pid] = packet_systems

    trace_system_file_map: Dict[str, Path] = {
        "advisory_decision_ledger": ADVISORY_DECISION_LEDGER_FILE,
        "advisory_engine": ADVISORY_ENGINE_LOG_FILE,
        "advisor_retrieval_router": ADVISORY_RETRIEVAL_ROUTE_LOG_FILE,
        "advisory_emit": ADVISORY_EMIT_FILE,
        "advisory_low_auth_dedupe": ADVISORY_LOW_AUTH_DEDUPE_FILE,
        "advisory_global_dedupe": ADVISORY_GLOBAL_DEDUPE_FILE,
        "advisor_advice_log": ADVISOR_ADVICE_LOG_FILE,
        "advisor_recent_advice": ADVISOR_RECENT_ADVICE_FILE,
        "advice_feedback_request": ADVICE_FEEDBACK_REQUESTS_FILE,
        "advice_feedback": ADVICE_FEEDBACK_FILE,
        "advisory_outcome": OUTCOMES_FILE,
        "outcome_links": OUTCOME_LINKS_FILE,
        "implicit_feedback": IMPLICIT_FEEDBACK_FILE,
    }
    trace_health_required = {
        "advisory_decision_ledger",
        "advisory_engine",
        "advisor_retrieval_router",
        "advisory_emit",
        "advice_feedback_request",
    }
    trace_health_optional = {
        "advisory_low_auth_dedupe",
        "advisory_global_dedupe",
        "advisor_advice_log",
        "advisor_recent_advice",
        "advice_feedback",
        "advisory_outcome",
        "outcome_links",
        "implicit_feedback",
    }
    required_per_packet_values = []
    for pid in packet_trace_systems.keys():
        seen = packet_trace_systems.get(pid, set()) or set()
        required_seen = len(trace_health_required.intersection(seen))
        required_score = (required_seen / float(len(trace_health_required))) if trace_health_required else 0.0
        required_per_packet_values.append(required_score)
    required_sampled_packet_health = (
        (sum(required_per_packet_values) / float(len(required_per_packet_values)))
        if required_per_packet_values
        else 0.0
    )
    required_system_sampled_coverage: Dict[str, float] = {
        system: (len(trace_system_packets.get(system, set())) / float(max(1, len(catalog[:sample_size])))) * 100.0
        for system in trace_health_required
    }
    required_system_ranked = sorted(
        required_system_sampled_coverage.items(),
        key=lambda item: (item[1], item[0]),
        reverse=True,
    )
    required_rank_token_map = {
        "critical": "🟢",
        "warning": "🟡",
        "blocked": "🔴",
    }
    def _rank_token_for_pct(pct: float) -> str:
        if pct >= 80.0:
            return required_rank_token_map["critical"]
        if pct >= 50.0:
            return required_rank_token_map["warning"]
        return required_rank_token_map["blocked"]

    if required_sampled_packet_health >= 0.85:
        required_health_token = required_rank_token_map["critical"]
        required_health_label = "healthy"
    elif required_sampled_packet_health >= 0.65:
        required_health_token = required_rank_token_map["warning"]
        required_health_label = "degraded"
    else:
        required_health_token = required_rank_token_map["blocked"]
        required_health_label = "critical"

    trace_health_window = max(1, min(300, len(watchtower) if watchtower else 200))
    trace_system_health_counts: Dict[str, int] = {}
    for name, path in trace_system_file_map.items():
        trace_system_health_counts[name] = len(_read_jsonl_lines(path, limit=trace_health_window))

    trace_health_required_hits: Dict[str, int] = {
        system: int(trace_system_health_counts.get(system, 0) or 0) for system in sorted(trace_health_required)
    }
    trace_health_optional_hits: Dict[str, int] = {
        system: int(trace_system_health_counts.get(system, 0) or 0) for system in sorted(trace_health_optional)
    }
    required_missing = [name for name, hit in trace_health_required_hits.items() if hit <= 0]
    optional_missing = [name for name, hit in trace_health_optional_hits.items() if hit <= 0]
    required_present_count = len(trace_health_required_hits) - len(required_missing)
    required_coverage_score = (
        (required_present_count / float(len(trace_health_required_hits))) if trace_health_required_hits else 0.0
    )
    hot_systems = sorted(
        trace_system_health_counts.items(),
        key=lambda item: (item[1], item[0]),
        reverse=True,
    )

    lines.extend(
        [
            "# SPARK Advisory Watchtower",
            "",
            "## Entry point",
            "- This is the deeper observability layer for advisory behavior.",
            "- Open this page first when you want to understand *what changed and why*.",
            "",
            "- updated: " + now_text,
            "- packet notes: [[packets/index|Packet Catalog]]",
            f"- total packets: {len(catalog)}",
            f"- ready now: {len(ready)}",
            f"- stale: {len(stale)}",
            f"- invalidated: {len(invalid)}",
            f"- trace health: {required_health_token} required systems seen per sampled packet: {required_sampled_packet_health:.0%} ({required_health_label})",
            f"- decision ledger events: {len(watchtower)}",
            f"- packets with active trace lineage: {trace_linked_count}",
            f"- packets with local trace history entries: {trace_history_count}",
            "",
        ]
    )

    lines.append("## Quick summary")
    lines.append(f"- decision ledger enabled: {bool(_decision_ledger_enabled())}")
    lines.append(f"- ledger path: `{ADVISORY_DECISION_LEDGER_FILE}`")
    lines.append(f"- watchtower file: `{_obsidian_watchtower_file()}`")
    if watchtower_stage:
        lines.append(
            "- gate outcomes: "
            + ", ".join(f"{k}({v})" for k, v in watchtower_stage.most_common(10))
        )
    if watchtower_reasons:
        lines.append(
            "- top suppression reasons: "
            + ", ".join(f"{k}({v})" for k, v in watchtower_reasons.most_common(12))
        )

    lines.append("## Trace health pane (global, last N cycles)")
    lines.append(f"- window: last {trace_health_window} cycles")
    lines.append(f"- required-system coverage score: {required_coverage_score:.2f}")
    lines.append(
        "- required-system visibility by sample: "
        + ", ".join(
            f"{_rank_token_for_pct(float(pct))} {name}({pct:.1f}%)" for name, pct in required_system_ranked
        )
    )
    if required_missing:
        lines.append(
            "- required systems missing all events in window: "
            + ", ".join(sorted(required_missing))
        )
    else:
        lines.append("- required systems present in window: all")
    lines.append("")
    lines.append("### Required systems")
    for system, hit_count in trace_health_required_hits.items():
        pct = (hit_count / float(trace_health_window)) * 100.0
        lines.append(f"- {system}: {hit_count}/{trace_health_window} cycles ({pct:.1f}%)")

    lines.append("")
    lines.append("### Optional systems")
    if optional_missing:
        lines.append("- optional systems with no events in window: " + ", ".join(sorted(optional_missing)))
    else:
        lines.append("- optional systems with no events in window: none")
    for system, hit_count in trace_health_optional_hits.items():
        pct = (hit_count / float(trace_health_window)) * 100.0
        lines.append(f"- {system}: {hit_count}/{trace_health_window} cycles ({pct:.1f}%)")

    lines.append("")
    lines.append("### Hot systems in window")
    for system, hit_count in hot_systems[:10]:
        pct = (hit_count / float(trace_health_window)) * 100.0
        lines.append(f"- {system}: {hit_count} events ({pct:.1f}% of window)")
    lines.append("")

    lines.append("## Trace-system heatmap (sample of recent packets)")
    if sample_size:
        for system in trace_systems_all:
            count = len(trace_system_packets.get(system, set()))
            pct = (count / float(sample_size)) * 100.0
            lines.append(f"- {system}: {count}/{sample_size} packets ({pct:.1f}%)")
    else:
        lines.append("- no recent packets in sample window")
    lines.append(f"- packets with pull events: {len(pulled_ids)}")
    lines.append(f"- packets emitted in last watch window: {len(emitted_ids)}")
    lines.append(f"- packets currently only suppressed: {len(suppressed_ids)}")
    lines.append(
        f"- packets with no trace usage history: {max(0, len(catalog) - trace_history_count)}"
    )
    lines.append("")

    lines.append("## Readiness + pull triage")
    unused_ready = [r for r in ready if str(r.get("packet_id") or "") not in pulled_ids]
    if unused_ready:
        lines.append("### Ready but never pulled")
        for idx, row in enumerate(unused_ready[:12], start=1):
            packet_id = str(row.get("packet_id") or "")
            readiness = float(row.get("readiness_score", 0.0) or 0.0)
            lines.append(
                f"{idx}. [[{packet_id}]] readiness={readiness:.2f} "
                f"| sources={', '.join(str(x) for x in _safe_list(row.get('source_summary'), max_items=3))}"
            )
        lines.append("")
    else:
        lines.append("- no ready packets pending pull actions")
        lines.append("")

    lines.append("## Top ready packets")
    top_ready_rows = sorted(
        ready,
        key=lambda row: (
            float(row.get("readiness_score", 0.0) or 0.0),
            float(row.get("effectiveness_score", 0.0) or 0.0),
            float(row.get("updated_ts", 0.0) or 0.0),
        ),
        reverse=True,
    )[:15]
    for idx, row in enumerate(top_ready_rows, start=1):
        packet_id = str(row.get("packet_id") or "")
        readiness = float(row.get("readiness_score") or 0.0)
        impact = float(row.get("effectiveness_score") or 0.0)
        usage_count = int(row.get("usage_count", 0) or 0)
        lines.append(
            f"{idx}. [[{packet_id}]] "
            f"| readiness={readiness:.2f} "
            f"| effect={impact:.2f} "
            f"| usage={usage_count} "
            f"| sources={', '.join(str(x) for x in _safe_list(row.get('source_summary'), max_items=3))}"
        )
    lines.append("")

    lines.append("## Decision tail (most recent)")
    if not watchtower:
        lines.append("- no decision events yet")
    else:
        for idx, row in enumerate(watchtower[:100], start=1):
            ts = float(row.get("ts", 0.0) or 0.0)
            ts_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "unknown"
            tool = str(row.get("tool", "") or "*")
            route = str(row.get("route", "") or "*")
            stage = str(row.get("stage", "") or "unknown")
            outcome = str(row.get("outcome", "") or stage)
            selected = int(row.get("selected_count", 0) or 0)
            suppressed = int(row.get("suppressed_count", 0) or 0)
            lines.append(
                f"{idx}. {ts_text} | tool={tool} | route={route} | outcome={outcome} "
                f"| selected={selected} suppressed={suppressed}"
            )
    lines.append("")

    if invalid:
        lines.append("## Invalidated packet list (for cleanup review)")
        for idx, row in enumerate(invalid[:30], start=1):
            packet_id = str(row.get("packet_id") or "")
            updated_ts = float(row.get("updated_ts", 0.0) or 0.0)
            updated_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(updated_ts)) if updated_ts else "unknown"
            lines.append(
                f"{idx}. [[{packet_id}]] reason={str(row.get('invalidate_reason') or 'none')} updated={updated_text}"
            )
        lines.append("")

    lines.append("## Distribution summary")
    lines.extend(
        [
            "- top source: " + ", ".join(f"{k}({v})" for k, v in source_counter.most_common(8)),
            "- top categories: " + ", ".join(f"{k}({v})" for k, v in category_counter.most_common(8)),
            "- top projects: " + ", ".join(f"{k}({v})" for k, v in project_counter.most_common(8)),
            "- top tools: " + ", ".join(f"{k}({v})" for k, v in tool_counter.most_common(8)),
            "- top intents: " + ", ".join(f"{k}({v})" for k, v in intent_counter.most_common(8)),
            "",
        ]
    )

    packets_path = str(_obsidian_packets_dir()).replace("\\", "/")
    lines.extend(
        [
            "## Quick queries (Dataview optional)",
            "```dataview",
            "TABLE file.link as packet, readiness_score, effectiveness_score, usage_count, project_key",
            f'FROM "{packets_path}"',
            "WHERE type = \"spark-advisory-packet\"",
            "SORT file.mtime desc",
            "LIMIT 80",
            "```",
        ]
    )

    lines.append("")

def _sync_obsidian_catalog() -> Optional[str]:
    if not _obsidian_enabled():
        _record_obsidian_status("disabled", message="obsidian_export disabled by tuneables")
        return None
    if not OBSIDIAN_AUTO_EXPORT:
        _record_obsidian_status("disabled", message="obsidian_auto_export is false")
        return None
    try:
        packets_dir = _obsidian_packets_dir()
        if not packets_dir.exists():
            _record_obsidian_status("skipped", message=f"obsidian packets dir missing: {packets_dir}")
            return None

        catalog = _build_obsidian_catalog(
            now_ts=_now(),
            only_ready=False,
            include_stale=True,
            include_invalid=True,
            limit=max(1, OBSIDIAN_EXPORT_MAX_PACKETS),
        )
        if not catalog and not ADVISORY_DECISION_LEDGER_FILE.exists():
            _record_obsidian_status("skipped", message="no obsidian catalog data or advisory events")
            return None

        lines: List[str] = []
        _render_obsidian_index(lines, catalog)
        target = _obsidian_index_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")

        watchtower_lines: List[str] = []
        _render_obsidian_watchtower(watchtower_lines, catalog)
        watchtower_target = _obsidian_watchtower_file()
        watchtower_target.parent.mkdir(parents=True, exist_ok=True)
        watchtower_target.write_text("\n".join(watchtower_lines) + "\n", encoding="utf-8")
        _record_obsidian_status(
            "success",
            message=f"wrote index/watchtower to {_obsidian_export_dir()}",
        )
        return str(target)
    except Exception as e:
        _record_obsidian_status(
            "error",
            message=f"sync failed: {e}",
            source="advisory_packet_store._sync_obsidian_catalog",
        )
        return None


def _export_packet_to_obsidian(packet: Dict[str, Any], *, force: bool = False) -> Optional[str]:
    if not _obsidian_enabled() or not isinstance(packet, dict):
        _record_obsidian_status("skipped", message="packet export skipped: obsidian disabled or packet invalid")
        return None
    packet_id = str(packet.get("packet_id") or "").strip()
    if not packet_id:
        _record_obsidian_status("skipped", message="packet export skipped: missing packet_id")
        return None
    if not OBSIDIAN_AUTO_EXPORT and not force:
        _record_obsidian_status("skipped", message="packet export skipped: auto_export is false")
        return None

    packets_dir = _obsidian_packets_dir()
    payload = _obsidian_payload(packet)
    if not payload:
        _record_obsidian_status("skipped", message="packet export skipped: empty payload")
        return None

    try:
        packets_dir.mkdir(parents=True, exist_ok=True)
        target = packets_dir / f"{packet_id}.md"
        target.write_text(payload, encoding="utf-8")
        all_exports = list(packets_dir.glob("*.md"))
        all_exports.sort(key=lambda p: p.stat().st_mtime)
        keep = max(1, OBSIDIAN_EXPORT_MAX_PACKETS)
        # Keep the catalog file if it exists.
        catalog_name = _obsidian_index_file().name.lower()
        if len(all_exports) > keep:
            for stale in all_exports[: len(all_exports) - keep]:
                if stale.name.lower() == catalog_name:
                    continue
                try:
                    stale.unlink()
                except Exception:
                    pass

        _sync_obsidian_catalog()
        _record_obsidian_status("success", message=f"exported packet {packet_id}")
        return str(target)
    except Exception as e:
        _record_obsidian_status(
            "error",
            message=f"packet export failed for {packet_id}: {e}",
            source="advisory_packet_store._export_packet_to_obsidian",
        )
        return None

    return None


def export_packet_packet(packet_id: str) -> Optional[str]:
    """Export an advisory packet into Obsidian manually (outside auto flow)."""
    packet = get_packet(packet_id)
    if not packet:
        return None
    original_auto = OBSIDIAN_AUTO_EXPORT
    try:
        return _export_packet_to_obsidian(packet, force=True)
    except Exception:
        return None
    finally:
        # restore original auto export preference if any caller mutates at runtime
        if original_auto != OBSIDIAN_AUTO_EXPORT:
            pass


def _packet_path(packet_id: str) -> Path:
    return PACKET_DIR / f"{packet_id}.json"


def _obsidian_dir_override(raw: Any) -> None:
    global _OBSIDIAN_CONFIG_DIR_OVERRIDE
    if raw is None:
        _OBSIDIAN_CONFIG_DIR_OVERRIDE = None
        return
    value = str(raw).strip()
    if value:
        _OBSIDIAN_CONFIG_DIR_OVERRIDE = value
    else:
        _OBSIDIAN_CONFIG_DIR_OVERRIDE = None


def _make_exact_key(
    project_key: str,
    session_context_key: str,
    tool_name: str,
    intent_family: str,
) -> str:
    parts = [project_key or "", session_context_key or "", tool_name or "", intent_family or ""]
    return "|".join(parts)


def _sanitize_token(value: Any, default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    return text[:120]


def _make_packet_id(
    project_key: str,
    session_context_key: str,
    tool_name: str,
    intent_family: str,
    created_ts: float,
) -> str:
    raw = _make_exact_key(project_key, session_context_key, tool_name, intent_family)
    digest = hashlib.sha1(f"{raw}|{created_ts:.6f}".encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"pkt_{digest}"


def _derive_packet_metadata(
    advice_items: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[str], List[str]]:
    """Derive compact source and category summaries from packet advice rows."""
    sources: List[str] = []
    categories: List[str] = []
    for row in (advice_items or []):
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "").strip()
        category = str(row.get("category") or "").strip()
        if source:
            sources.append(source)
        if category:
            categories.append(category)

    # Deduplicate preserving order.
    def _uniq(values: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
        return out

    return _uniq(sources), _uniq(categories)


def _normalize_packet_meta_row(row: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(row, dict):
        return None
    out = dict(row)
    out["read_count"] = max(0, _to_int(out.get("read_count", 0), 0))
    out["usage_count"] = max(0, _to_int(out.get("usage_count", out.get("read_count", 0)), 0))
    out["emit_count"] = max(0, _to_int(out.get("emit_count", 0), 0))
    out["deliver_count"] = max(0, _to_int(out.get("deliver_count", out.get("emit_count", 0)), 0))
    out["feedback_count"] = max(0, _to_int(out.get("feedback_count", 0), 0))
    out["helpful_count"] = max(0, _to_int(out.get("helpful_count", 0), 0))
    out["unhelpful_count"] = max(0, _to_int(out.get("unhelpful_count", 0), 0))
    out["noisy_count"] = max(0, _to_int(out.get("noisy_count", 0), 0))
    out["acted_count"] = max(0, _to_int(out.get("acted_count", 0), 0))
    out["blocked_count"] = max(0, _to_int(out.get("blocked_count", 0), 0))
    out["harmful_count"] = max(0, _to_int(out.get("harmful_count", 0), 0))
    out["ignored_count"] = max(0, _to_int(out.get("ignored_count", 0), 0))
    out["last_trace_id"] = str(out.get("last_trace_id") or "").strip()
    out["trace_usage_history"] = _normalize_trace_usage_history(
        out.get("trace_usage_history"),
        limit=TRACE_EVENT_HISTORY_MAX,
    )
    out["source_summary"] = _safe_list(out.get("source_summary"), max_items=40)
    out["category_summary"] = _safe_list(out.get("category_summary"), max_items=20)
    out["readiness_score"] = float(out.get("readiness_score") or 0.0)
    out["effectiveness_score"] = float(out.get("effectiveness_score", 0.5) or 0.5)
    out["fresh_until_ts"] = float(out.get("fresh_until_ts", 0.0) or 0.0)
    out["updated_ts"] = float(out.get("updated_ts", 0.0) or 0.0)
    out["last_read_ts"] = float(out.get("last_read_ts", 0.0) or 0.0)
    out["last_read_route"] = str(out.get("last_read_route", "") or "")
    out["invalidated"] = bool(out.get("invalidated", False))
    out["project_key"] = str(out.get("project_key") or "")
    out["session_context_key"] = str(out.get("session_context_key") or "")
    out["tool_name"] = str(out.get("tool_name") or "")
    out["intent_family"] = str(out.get("intent_family") or "")
    out["task_plane"] = str(out.get("task_plane") or "")
    out["source_mode"] = str(out.get("source_mode") or "")
    return out


def _normalize_packet_meta(index: Dict[str, Any]) -> bool:
    meta = index.get("packet_meta")
    if not isinstance(meta, dict):
        index["packet_meta"] = {}
        return True

    changed = False
    normalized_meta: Dict[str, Any] = {}
    for packet_id, row in meta.items():
        normalized = _normalize_packet_meta_row(row)
        if normalized is None:
            changed = True
            continue
        if not isinstance(row, dict) or row != normalized:
            changed = True
        normalized_meta[str(packet_id or "")] = normalized

    if not isinstance(index.get("packet_meta"), dict):
        changed = True
    index["packet_meta"] = normalized_meta
    return changed


def _migrate_packet_index_schema(index: Dict[str, Any]) -> bool:
    try:
        if not isinstance(index, dict):
            return False
        current = int(index.get(INDEX_SCHEMA_VERSION_KEY, 1))
    except Exception:
        current = 1
    if current >= INDEX_SCHEMA_VERSION:
        return False
    index[INDEX_SCHEMA_VERSION_KEY] = INDEX_SCHEMA_VERSION
    return True


def _load_index() -> Dict[str, Any]:
    _ensure_dirs()
    default = {"by_exact": {}, "packet_meta": {}}
    global _INDEX_CACHE, _INDEX_CACHE_MTIME_NS

    try:
        mtime_ns = int(INDEX_FILE.stat().st_mtime_ns) if INDEX_FILE.exists() else None
    except Exception:
        mtime_ns = None

    # Hot-path optimization: lookups happen on pre-tool advisory. Avoid re-parsing
    # the index JSON unless the file changed.
    if _INDEX_CACHE is not None and mtime_ns is not None and _INDEX_CACHE_MTIME_NS == mtime_ns:
        return _INDEX_CACHE

    data = _read_json(INDEX_FILE, default)
    data.setdefault("by_exact", {})
    data.setdefault("packet_meta", {})

    migrated = _migrate_packet_index_schema(data)
    meta_changed = _normalize_packet_meta(data)
    if migrated or meta_changed:
        try:
            _save_index(data)
            mtime_ns = int(INDEX_FILE.stat().st_mtime_ns) if INDEX_FILE.exists() else mtime_ns
        except Exception:
            pass

    _INDEX_CACHE = data
    _INDEX_CACHE_MTIME_NS = mtime_ns
    return data


def _save_index(index: Dict[str, Any]) -> None:
    _ensure_dirs()
    _atomic_write_json(INDEX_FILE, index)
    # Keep cache coherent for subsequent reads in this process.
    global _INDEX_CACHE, _INDEX_CACHE_MTIME_NS
    _INDEX_CACHE = index
    try:
        _INDEX_CACHE_MTIME_NS = int(INDEX_FILE.stat().st_mtime_ns) if INDEX_FILE.exists() else None
    except Exception:
        _INDEX_CACHE_MTIME_NS = None


def alias_exact_key(
    *,
    project_key: str,
    session_context_key: str,
    tool_name: str,
    intent_family: str,
    packet_id: str,
) -> bool:
    """
    Promote a packet found via relaxed lookup into the exact index by creating an alias from the
    current exact key to the existing packet_id. This increases future exact-hit rate without
    duplicating packet files.
    """
    if not packet_id:
        return False
    project = _sanitize_token(project_key, "unknown_project")
    session_ctx = _sanitize_token(session_context_key, "default")
    tool = _sanitize_token(tool_name, "*")
    intent = _sanitize_token(intent_family, "emergent_other")
    exact_key = _make_exact_key(project, session_ctx, tool, intent)
    if exact_key in _ALIASED_EXACT_KEYS:
        return False
    index = _load_index()
    by_exact = index.get("by_exact") or {}
    if by_exact.get(exact_key) == packet_id:
        _ALIASED_EXACT_KEYS.add(exact_key)
        return False
    by_exact[exact_key] = packet_id
    index["by_exact"] = by_exact
    _save_index(index)
    _ALIASED_EXACT_KEYS.add(exact_key)
    return True


def build_packet(
    *,
    project_key: str,
    session_context_key: str,
    tool_name: str,
    intent_family: str,
    task_plane: str,
    advisory_text: str,
    source_mode: str,
    advice_items: Optional[List[Dict[str, Any]]] = None,
    lineage: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    ttl_s: Optional[float] = None,
) -> Dict[str, Any]:
    created = _now()
    rows = list(advice_items or [])
    project = _sanitize_token(project_key, "unknown_project")
    session_ctx = _sanitize_token(session_context_key, "default")
    tool = _sanitize_token(tool_name, "*")
    intent = _sanitize_token(intent_family, "emergent_other")
    plane = _sanitize_token(task_plane, "build_delivery")
    mode = _sanitize_token(source_mode, "deterministic")
    packet_id = _make_packet_id(project, session_ctx, tool, intent, created)
    safe_lineage = dict(lineage or {})
    safe_lineage.setdefault("sources", [])
    safe_lineage.setdefault("memory_absent_declared", False)
    if trace_id:
        safe_lineage.setdefault("trace_id", trace_id)

    ttl_value = DEFAULT_PACKET_TTL_S if ttl_s is None else float(ttl_s or DEFAULT_PACKET_TTL_S)
    source_summary, category_summary = _derive_packet_metadata(rows)
    return {
        "packet_id": packet_id,
        "project_key": project,
        "session_context_key": session_ctx,
        "tool_name": tool,
        "intent_family": intent,
        "task_plane": plane,
        "advisory_text": (advisory_text or "").strip(),
        "source_mode": mode,
        "advice_items": rows,
        "source_summary": source_summary,
        "category_summary": category_summary,
        "lineage": safe_lineage,
        "created_ts": created,
        "updated_ts": created,
        "fresh_until_ts": created + max(30.0, float(ttl_value)),
        "invalidated": False,
        "invalidate_reason": "",
        "read_count": 0,
        "last_read_ts": 0.0,
        "last_read_route": "",
        "last_trace_id": (str((lineage.get("trace_id") or "") if isinstance(safe_lineage, dict) else "").strip() or ""),
        "trace_usage_history": [],
        "usage_count": 0,
        "emit_count": 0,
        "deliver_count": 0,
        "helpful_count": 0,
        "unhelpful_count": 0,
        "noisy_count": 0,
        "feedback_count": 0,
        "acted_count": 0,
        "blocked_count": 0,
        "harmful_count": 0,
        "ignored_count": 0,
        "effectiveness_score": 0.5,
    }


def validate_packet(packet: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(packet, dict):
        return False, "packet must be a dict"
    missing = REQUIRED_PACKET_FIELDS - set(packet.keys())
    if missing:
        return False, f"missing_fields:{','.join(sorted(missing))}"
    lineage = packet.get("lineage")
    if not isinstance(lineage, dict):
        return False, "lineage must be a dict"
    lineage_missing = REQUIRED_LINEAGE_FIELDS - set(lineage.keys())
    if lineage_missing:
        return False, f"missing_lineage_fields:{','.join(sorted(lineage_missing))}"
    if not packet.get("packet_id"):
        return False, "packet_id missing"
    if not isinstance(packet.get("advisory_text"), str):
        return False, "advisory_text must be string"
    return True, ""


def save_packet(packet: Dict[str, Any]) -> str:
    packet = _normalize_packet(packet)
    ok, reason = validate_packet(packet)
    if not ok:
        raise ValueError(f"invalid packet: {reason}")

    _ensure_dirs()
    packet_id = str(packet.get("packet_id"))
    packet["updated_ts"] = _now()

    _packet_path(packet_id).write_text(
        json.dumps(packet, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    index = _load_index()
    exact_key = _make_exact_key(
        str(packet.get("project_key", "")),
        str(packet.get("session_context_key", "")),
        str(packet.get("tool_name", "")),
        str(packet.get("intent_family", "")),
    )
    index["by_exact"][exact_key] = packet_id
    flags = _readiness_flags(packet, now_ts=packet.get("updated_ts"))
    index["packet_meta"][packet_id] = {
        "project_key": packet.get("project_key"),
        "session_context_key": packet.get("session_context_key"),
        "tool_name": packet.get("tool_name"),
        "intent_family": packet.get("intent_family"),
        "task_plane": packet.get("task_plane"),
        "source_summary": _safe_list(packet.get("source_summary"), max_items=40),
        "category_summary": _safe_list(packet.get("category_summary"), max_items=20),
        "updated_ts": packet.get("updated_ts"),
        "fresh_until_ts": packet.get("fresh_until_ts"),
        "invalidated": bool(packet.get("invalidated", False)),
        "last_trace_id": str(packet.get("last_trace_id") or "").strip(),
        "trace_usage_history": _normalize_trace_usage_history(
            packet.get("trace_usage_history"),
            limit=TRACE_EVENT_HISTORY_MAX,
        ),
        "read_count": int(packet.get("read_count", 0) or 0),
        "last_read_ts": float(packet.get("last_read_ts", 0.0) or 0.0),
        "last_read_route": str(packet.get("last_read_route") or ""),
        "usage_count": int(packet.get("usage_count", 0) or 0),
        "emit_count": int(packet.get("emit_count", 0) or 0),
        "deliver_count": int(packet.get("deliver_count", 0) or 0),
        "feedback_count": int(packet.get("feedback_count", 0) or 0),
        "helpful_count": int(packet.get("helpful_count", 0) or 0),
        "unhelpful_count": int(packet.get("unhelpful_count", 0) or 0),
        "noisy_count": int(packet.get("noisy_count", 0) or 0),
        "effectiveness_score": float(packet.get("effectiveness_score", 0.5) or 0.5),
        "source_mode": str(packet.get("source_mode") or ""),
        "age_s": max(0.0, _now() - float(packet.get("updated_ts", 0.0) or 0.0)),
        "is_ready": bool(flags.get("ready_for_use", False)),
        "readiness_score": float(flags.get("readiness_score", 0.0)),
    }
    _prune_index(index)
    _save_index(index)
    try:
        _export_packet_to_obsidian(packet)
    except Exception:
        pass
    return packet_id


def _prune_index(index: Dict[str, Any]) -> None:
    meta = index.get("packet_meta") or {}
    if len(meta) <= MAX_INDEX_PACKETS:
        return
    ordered = sorted(
        meta.items(),
        key=lambda kv: float((kv[1] or {}).get("updated_ts", 0.0)),
    )
    remove_count = len(meta) - MAX_INDEX_PACKETS
    remove_ids = {packet_id for packet_id, _ in ordered[:remove_count]}
    for packet_id in remove_ids:
        meta.pop(packet_id, None)
    by_exact = index.get("by_exact") or {}
    dead_keys = [k for k, v in by_exact.items() if v in remove_ids]
    for k in dead_keys:
        by_exact.pop(k, None)


def get_packet(packet_id: str) -> Optional[Dict[str, Any]]:
    if not packet_id:
        return None
    try:
        path = _packet_path(packet_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return _normalize_packet(data)
    except Exception:
        return None
    return None


def _is_fresh(packet: Dict[str, Any], now_ts: Optional[float] = None) -> bool:
    now_value = float(now_ts if now_ts is not None else _now())
    if bool(packet.get("invalidated")):
        return False
    return float(packet.get("fresh_until_ts", 0.0)) >= now_value


def _candidate_match_score(
    row: Dict[str, Any],
    *,
    project: str,
    tool_name: str,
    intent_family: str,
    task_plane: str,
    now_value: float,
) -> Optional[Tuple[float, float]]:
    if row.get("project_key") != project:
        return None
    if bool(row.get("invalidated")):
        return None
    if float(row.get("fresh_until_ts", 0.0)) < now_value:
        return None

    score = 0.0
    match_score = 0.0
    match_dimensions = 0
    row_tool = str(row.get("tool_name") or "")
    row_intent = str(row.get("intent_family") or "")
    row_plane = str(row.get("task_plane") or "")

    if tool_name and row_tool == tool_name:
        score += RELAXED_MATCH_WEIGHT_TOOL
        match_score += RELAXED_MATCH_WEIGHT_TOOL
        match_dimensions += 1
    elif row_tool == "*":
        score += RELAXED_WILDCARD_TOOL_BONUS
        match_score += RELAXED_WILDCARD_TOOL_BONUS
        match_dimensions += 1
    if intent_family and row_intent == intent_family:
        score += RELAXED_MATCH_WEIGHT_INTENT
        match_score += RELAXED_MATCH_WEIGHT_INTENT
        match_dimensions += 1
    if task_plane and row_plane == task_plane:
        score += RELAXED_MATCH_WEIGHT_PLANE
        match_score += RELAXED_MATCH_WEIGHT_PLANE
        match_dimensions += 1

    if match_dimensions < RELAXED_MIN_MATCH_DIMENSIONS:
        return None
    if match_score < RELAXED_MIN_MATCH_SCORE:
        return None

    effectiveness = max(0.0, min(1.0, float(row.get("effectiveness_score", 0.5) or 0.5)))
    score += effectiveness * RELAXED_EFFECTIVENESS_WEIGHT
    if effectiveness < RELAXED_LOW_EFFECTIVENESS_THRESHOLD:
        score -= RELAXED_LOW_EFFECTIVENESS_PENALTY
    score += min(1.0, max(0.0, (float(row.get("updated_ts", 0.0)) / 1e10)))
    return score, float(row.get("updated_ts", 0.0))


def lookup_exact(
    *,
    project_key: str,
    session_context_key: str,
    tool_name: str,
    intent_family: str,
    now_ts: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    index = _load_index()
    # Mirror build_packet/save_packet sanitization so exact hits work even if caller passes raw values.
    project = _sanitize_token(project_key, "unknown_project")
    session_ctx = _sanitize_token(session_context_key, "default")
    tool = _sanitize_token(tool_name, "*")
    intent = _sanitize_token(intent_family, "emergent_other")
    exact_key = _make_exact_key(project, session_ctx, tool, intent)
    packet_id = (index.get("by_exact") or {}).get(exact_key)
    packet = get_packet(str(packet_id or ""))
    if not packet:
        return None
    if not _is_fresh(packet, now_ts=now_ts):
        return None
    return packet


def resolve_advisory_packet_for_context(
    *,
    project_key: str,
    session_context_key: str,
    tool_name: str = "",
    intent_family: str = "",
    task_plane: str = "",
    context_text: str = "",
    now_ts: Optional[float] = None,
    do_alias_relaxed_to_exact: bool = True,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Resolve an advisory packet with exact-first fallback semantics.

    Returns:
        (packet, route): packet may be None; route is one of
        "packet_exact", "packet_relaxed", or "packet_miss".
    """
    packet = lookup_exact(
        project_key=project_key,
        session_context_key=session_context_key,
        tool_name=tool_name,
        intent_family=intent_family,
        now_ts=now_ts,
    )
    if packet:
        return packet, "packet_exact"

    packet = lookup_relaxed(
        project_key=project_key,
        tool_name=tool_name,
        intent_family=intent_family,
        task_plane=task_plane,
        now_ts=now_ts,
        context_text=context_text,
    )
    if not packet:
        return None, "packet_miss"

    if do_alias_relaxed_to_exact:
        try:
            if (
                str(packet.get("project_key") or "").strip() == str(project_key or "").strip()
                and str(packet.get("tool_name") or "").strip() == str(tool_name or "").strip()
                and str(packet.get("intent_family") or "").strip() == str(intent_family or "").strip()
            ):
                alias_exact_key(
                    project_key=project_key,
                    session_context_key=session_context_key,
                    tool_name=tool_name,
                    intent_family=intent_family,
                    packet_id=str(packet.get("packet_id") or ""),
                )
        except Exception:
            pass

    return packet, "packet_relaxed"


def lookup_relaxed(
    *,
    project_key: str,
    tool_name: str = "",
    intent_family: str = "",
    task_plane: str = "",
    now_ts: Optional[float] = None,
    context_text: str = "",
) -> Optional[Dict[str, Any]]:
    candidates = lookup_relaxed_candidates(
        project_key=project_key,
        tool_name=tool_name,
        intent_family=intent_family,
        task_plane=task_plane,
        now_ts=now_ts,
        max_candidates=PACKET_LOOKUP_CANDIDATES,
        context_text=context_text,
    )
    if not candidates:
        return None
    packet_id = str(candidates[0].get("packet_id") or "")
    if not packet_id:
        return None
    return get_packet(packet_id)


def _llm_area_packet_rerank(candidates: List[Dict[str, Any]], context_text: str) -> List[Dict[str, Any]]:
    """LLM area: rerank packet candidates before emit.

    When disabled (default), returns candidates unchanged.
    """
    try:
        from .llm_area_prompts import format_prompt
        from .llm_dispatch import llm_area_call

        previews = [c.get("advisory_text_preview", "")[:100] for c in candidates[:5]]
        prompt = format_prompt(
            "packet_rerank",
            candidates=str(previews),
            context=context_text[:300],
            count=str(len(candidates)),
        )
        result = llm_area_call("packet_rerank", prompt, fallback="")
        if result.used_llm and result.text:
            import json as _json
            try:
                data = _json.loads(result.text)
                if isinstance(data, dict) and data.get("order"):
                    order = data["order"]
                    if isinstance(order, list) and all(isinstance(i, int) for i in order):
                        reordered = []
                        for idx in order:
                            if 0 <= idx < len(candidates):
                                reordered.append(candidates[idx])
                        remaining = [c for i, c in enumerate(candidates) if i not in order]
                        return reordered + remaining
            except (ValueError, TypeError):
                pass
        return candidates
    except Exception:
        return candidates


def lookup_relaxed_candidates(
    *,
    project_key: str,
    tool_name: str = "",
    intent_family: str = "",
    task_plane: str = "",
    now_ts: Optional[float] = None,
    max_candidates: int = 10,
    context_text: str = "",
) -> List[Dict[str, Any]]:
    index = _load_index()
    meta = index.get("packet_meta") or {}
    now_value = float(now_ts if now_ts is not None else _now())
    limit = max(1, min(30, int(max_candidates or PACKET_RELAXED_MAX_CANDIDATES or 1)))
    candidates: List[Tuple[float, float, str, Dict[str, Any]]] = []
    project = _sanitize_token(project_key, "unknown_project")
    tool_name = _sanitize_token(tool_name, "") if tool_name else ""
    intent_family = _sanitize_token(intent_family, "") if intent_family else ""
    task_plane = _sanitize_token(task_plane, "") if task_plane else ""

    for packet_id, item in meta.items():
        row = item or {}
        scored = _candidate_match_score(
            row,
            project=project,
            tool_name=tool_name,
            intent_family=intent_family,
            task_plane=task_plane,
            now_value=now_value,
        )
        if not scored:
            continue
        score, updated_ts = scored
        candidates.append((score, updated_ts, str(packet_id or ""), row))

    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    out: List[Dict[str, Any]] = []
    for score, updated_ts, packet_id, row in candidates[:limit]:
        preview = ""
        try:
            packet = get_packet(packet_id)
            if packet:
                text = str(packet.get("advisory_text") or "")
                preview = text[:DEFAULT_PACKET_RELAXED_PREVIEW_CHARS].replace("\n", " ").strip()
        except Exception:
            preview = ""

        item = {
            "packet_id": str(packet_id),
            "score": float(score),
            "updated_ts": float(updated_ts),
            "tool_name": str(row.get("tool_name") or ""),
            "intent_family": str(row.get("intent_family") or ""),
            "task_plane": str(row.get("task_plane") or ""),
            "source_summary": _safe_list(row.get("source_summary"), max_items=20),
            "category_summary": _safe_list(row.get("category_summary"), max_items=20),
            "effectiveness_score": float(row.get("effectiveness_score", 0.5) or 0.5),
            "read_count": _meta_count(row, "read_count"),
            "usage_count": _meta_count(row, "usage_count", fallback_key="read_count"),
            "emit_count": _meta_count(row, "emit_count"),
            "deliver_count": _meta_count(row, "deliver_count", fallback_key="emit_count"),
            "fresh_until_ts": float(row.get("fresh_until_ts", 0.0) or 0.0),
            "advisory_text_preview": preview,
            "invalidated": bool(row.get("invalidated", False)),
        }
        out.append(item)

    if context_text and len(out) > 1:
        out = _rerank_candidates_with_lookup_llm(out, context_text=context_text)

    # LLM area: packet_rerank — additional LLM-based reranking of candidates
    if len(out) > 1:
        out = _llm_area_packet_rerank(out, context_text)

    return out


def get_advisory_catalog(
    *,
    project_key: str = "",
    tool_name: str = "",
    intent_family: str = "",
    task_plane: str = "",
    only_ready: bool = True,
    include_stale: bool = False,
    min_effectiveness: Optional[float] = None,
    limit: int = 60,
) -> List[Dict[str, Any]]:
    """Read a curated advisory catalog directly from packet meta + packet payload."""
    index = _load_index()
    meta = index.get("packet_meta") or {}
    normalized_project = str(project_key or "").strip().lower()
    normalized_tool = str(tool_name or "").strip().lower()
    normalized_intent = str(intent_family or "").strip().lower()
    normalized_plane = str(task_plane or "").strip().lower()
    limit_rows = max(1, min(500, int(limit or 60)))

    out: List[Dict[str, Any]] = []
    for packet_id, row in meta.items():
        if not isinstance(row, dict):
            continue
        row_project = str(row.get("project_key") or "").strip().lower()
        if normalized_project and row_project and row_project != normalized_project:
            continue
        row_tool = str(row.get("tool_name") or "").strip().lower()
        if normalized_tool and row_tool and row_tool != normalized_tool:
            continue
        row_intent = str(row.get("intent_family") or "").strip().lower()
        if normalized_intent and row_intent and row_intent != normalized_intent:
            continue
        row_plane = str(row.get("task_plane") or "").strip().lower()
        if normalized_plane and row_plane and row_plane != normalized_plane:
            continue

        try:
            packet = get_packet(str(packet_id or ""))
            if not packet:
                continue
            flags = _readiness_flags(packet)
            if not include_stale and not bool(flags.get("is_fresh", False)):
                continue
            if only_ready and not bool(flags.get("ready_for_use", False)):
                continue
            min_effective = min_effectiveness
            if min_effective is not None and float(packet.get("effectiveness_score", 0.5) or 0.0) < float(min_effective):
                continue
            item = _obsidian_catalog_entry(packet, now_ts=_now())
            item["packet_meta_only"] = False
            out.append(item)
        except Exception:
            # Fall back to meta-only row if packet body cannot be read.
            flags = _readiness_flags(row)
            if not include_stale and not bool(flags.get("is_fresh", False)):
                continue
            if only_ready and not bool(flags.get("ready_for_use", False)):
                continue
            score = float(row.get("effectiveness_score", 0.5) or 0.5)
            if min_effectiveness is not None and score < float(min_effectiveness):
                continue
            out.append({
                "packet_id": str(packet_id or ""),
                "project_key": str(row.get("project_key") or ""),
                "session_context_key": str(row.get("session_context_key") or ""),
                "tool_name": str(row.get("tool_name") or ""),
                "intent_family": str(row.get("intent_family") or ""),
                "task_plane": str(row.get("task_plane") or ""),
                "invalidated": bool(row.get("invalidated", False)),
                "invalidate_reason": str(row.get("invalidate_reason", "") or ""),
                "updated_ts": float(row.get("updated_ts", 0.0) or 0.0),
                "fresh_until_ts": float(row.get("fresh_until_ts", 0.0) or 0.0),
                "ready_for_use": bool(flags.get("ready_for_use", False)),
                "is_fresh": bool(flags.get("is_fresh", False)),
                "readiness_score": float(flags.get("readiness_score", 0.0)),
                "effectiveness_score": score,
                "read_count": _meta_count(row, "read_count"),
                "usage_count": _meta_count(row, "usage_count", fallback_key="read_count"),
                "emit_count": _meta_count(row, "emit_count"),
                "deliver_count": _meta_count(row, "deliver_count", fallback_key="emit_count"),
                "source_summary": _safe_list(row.get("source_summary"), max_items=10),
                "category_summary": _safe_list(row.get("category_summary"), max_items=8),
                "packet_meta_only": True,
            })

    out.sort(
        key=lambda r: (
            float(r.get("readiness_score", 0.0) or 0.0),
            float(r.get("updated_ts", 0.0) or 0.0),
            str(r.get("packet_id") or ""),
        ),
        reverse=True,
    )
    return out[:limit_rows]


def invalidate_packet(packet_id: str, reason: str = "manual") -> bool:
    packet = get_packet(packet_id)
    if not packet:
        return False
    packet["invalidated"] = True
    packet["invalidate_reason"] = reason[:200]
    packet["updated_ts"] = _now()
    _packet_path(packet_id).write_text(
        json.dumps(packet, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    index = _load_index()
    if packet_id in (index.get("packet_meta") or {}):
        index["packet_meta"][packet_id]["invalidated"] = True
        index["packet_meta"][packet_id]["updated_ts"] = packet["updated_ts"]
        index["packet_meta"][packet_id]["invalidate_reason"] = reason[:200]
    _save_index(index)
    try:
        if _obsidian_enabled():
            _export_packet_to_obsidian(packet, force=True)
    except Exception:
        pass
    return True


def invalidate_packets(
    *,
    project_key: Optional[str] = None,
    tool_name: Optional[str] = None,
    intent_family: Optional[str] = None,
    reason: str = "filtered_invalidation",
    file_hint: Optional[str] = None,
) -> int:
    """Invalidate matching packets.

    When *file_hint* is provided (e.g. an edited file path), only
    packets whose advisory text or advice items reference that file
    are invalidated, rather than blanket project-wide invalidation.
    """
    index = _load_index()
    meta = index.get("packet_meta") or {}
    to_invalidate: List[str] = []

    # Normalise file_hint for substring matching
    file_hint_lower = ""
    if file_hint:
        file_hint_lower = file_hint.replace("\\", "/").rsplit("/", 1)[-1].lower()

    for packet_id, row in meta.items():
        item = row or {}
        if project_key and item.get("project_key") != project_key:
            continue
        if tool_name and item.get("tool_name") != tool_name:
            continue
        if intent_family and item.get("intent_family") != intent_family:
            continue

        # If file_hint given, only invalidate packets that reference
        # the same file (by filename match in advisory text or advice items).
        # NOTE: packet_meta intentionally does not store advisory_text/advice_items,
        # so we must read full packet for reliable matching.
        if file_hint_lower:
            pkt_tool = str(item.get("tool_name") or "").lower()
            packet = get_packet(packet_id)
            pkt_text = str((packet or {}).get("advisory_text") or "").lower()
            items_blob = (packet or {}).get("advice_items") or []
            items_text = json.dumps(items_blob, ensure_ascii=False).lower()

            if file_hint_lower not in pkt_text and file_hint_lower not in items_text:
                # Also skip wildcard baseline packets â€” those aren't file-specific.
                if pkt_tool == "*":
                    continue
                continue

        to_invalidate.append(packet_id)
    count = 0
    for packet_id in to_invalidate:
        if invalidate_packet(packet_id, reason=reason):
            count += 1
    return count


def record_packet_usage(
    packet_id: str,
    *,
    emitted: bool = False,
    route: Optional[str] = None,
    trace_id: Optional[str] = None,
    tool_name: Optional[str] = None,
) -> Dict[str, Any]:
    packet = get_packet(packet_id)
    if not packet:
        return {"ok": False, "reason": "packet_not_found", "packet_id": packet_id}

    usage_ts = _now()
    trace_value = str(trace_id or "").strip()
    tool_value = str(tool_name or "").strip()
    packet["read_count"] = int(packet.get("read_count", 0) or 0) + 1
    packet["last_read_ts"] = usage_ts
    packet["last_read_route"] = str(route or packet.get("last_read_route") or "")
    packet["usage_count"] = int(packet.get("usage_count", 0) or 0) + 1
    if emitted:
        packet["emit_count"] = int(packet.get("emit_count", 0) or 0) + 1
        packet["deliver_count"] = int(packet.get("deliver_count", 0) or 0) + 1
    if trace_value:
        packet["last_trace_id"] = trace_value
        usage_history = packet.get("trace_usage_history") or []
        usage_history.append(
            {
                "ts": usage_ts,
                "trace_id": trace_value,
                "tool_name": tool_value,
                "route": str(route or "").strip(),
                "emitted": bool(emitted),
                "route_order": len(usage_history) + 1,
                "event": "packet_usage",
            }
        )
        packet["trace_usage_history"] = _normalize_trace_usage_history(
            usage_history,
            limit=TRACE_EVENT_HISTORY_MAX,
        )
    packet["last_route"] = str(route or packet.get("last_route") or "")
    packet["last_used_ts"] = usage_ts
    packet = _normalize_packet(packet)
    save_packet(packet)
    return {
        "ok": True,
        "packet_id": packet_id,
        "read_count": int(packet.get("read_count", 0) or 0),
        "usage_count": int(packet.get("usage_count", 0) or 0),
        "emit_count": int(packet.get("emit_count", 0) or 0),
        "deliver_count": int(packet.get("deliver_count", 0) or 0),
        "trace_id": str(packet.get("last_trace_id") or "").strip(),
    }


# ── Feedback/outcome recording (extracted to advisory_packet_feedback.py) ──
from .advisory_packet_feedback import (  # noqa: F401,E402 — re-export for compat
    record_packet_feedback,
    record_packet_feedback_for_advice,
    record_packet_outcome,
    record_packet_outcome_for_advice,
)


def enqueue_prefetch_job(job: Dict[str, Any]) -> str:
    _ensure_dirs()
    ts = _now()
    payload = dict(job or {})
    if not payload.get("job_id"):
        digest = hashlib.sha1(f"{ts:.6f}|{json.dumps(payload, sort_keys=True)}".encode("utf-8")).hexdigest()[:10]
        payload["job_id"] = f"pf_{digest}"
    payload.setdefault("created_ts", ts)
    payload.setdefault("status", "queued")
    with PREFETCH_QUEUE_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return str(payload["job_id"])


def apply_packet_store_config(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    """Apply packet store tuneables used by packet creation and relaxed ranking."""
    global DEFAULT_PACKET_TTL_S
    global MAX_INDEX_PACKETS
    global RELAXED_EFFECTIVENESS_WEIGHT
    global RELAXED_LOW_EFFECTIVENESS_THRESHOLD
    global RELAXED_LOW_EFFECTIVENESS_PENALTY
    global RELAXED_MIN_MATCH_DIMENSIONS
    global RELAXED_MIN_MATCH_SCORE
    global PACKET_RELAXED_MAX_CANDIDATES
    global PACKET_LOOKUP_CANDIDATES
    # LLM globals now live in _llm_reranker module (set via module reference below)
    global OBSIDIAN_EXPORT_ENABLED
    global OBSIDIAN_AUTO_EXPORT
    global OBSIDIAN_EXPORT_MAX_PACKETS
    global DEFAULT_OBSIDIAN_EXPORT_DIR

    applied: List[str] = []
    warnings: List[str] = []
    if not isinstance(cfg, dict):
        return {"applied": applied, "warnings": warnings}

    if "packet_ttl_s" in cfg:
        try:
            DEFAULT_PACKET_TTL_S = max(30.0, min(86400.0, float(cfg.get("packet_ttl_s") or 30.0)))
            applied.append("packet_ttl_s")
        except Exception:
            warnings.append("invalid_packet_ttl_s")

    if "max_index_packets" in cfg:
        try:
            MAX_INDEX_PACKETS = max(100, min(50000, int(cfg.get("max_index_packets") or 100)))
            applied.append("max_index_packets")
        except Exception:
            warnings.append("invalid_max_index_packets")

    if "relaxed_effectiveness_weight" in cfg:
        try:
            RELAXED_EFFECTIVENESS_WEIGHT = max(
                0.0,
                min(10.0, float(cfg.get("relaxed_effectiveness_weight") or 0.0)),
            )
            applied.append("relaxed_effectiveness_weight")
        except Exception:
            warnings.append("invalid_relaxed_effectiveness_weight")

    if "relaxed_low_effectiveness_threshold" in cfg:
        try:
            RELAXED_LOW_EFFECTIVENESS_THRESHOLD = max(
                0.0,
                min(1.0, float(cfg.get("relaxed_low_effectiveness_threshold") or 0.0)),
            )
            applied.append("relaxed_low_effectiveness_threshold")
        except Exception:
            warnings.append("invalid_relaxed_low_effectiveness_threshold")

    if "relaxed_low_effectiveness_penalty" in cfg:
        try:
            RELAXED_LOW_EFFECTIVENESS_PENALTY = max(
                0.0,
                min(5.0, float(cfg.get("relaxed_low_effectiveness_penalty") or 0.0)),
            )
            applied.append("relaxed_low_effectiveness_penalty")
        except Exception:
            warnings.append("invalid_relaxed_low_effectiveness_penalty")

    if "relaxed_min_match_dimensions" in cfg:
        try:
            RELAXED_MIN_MATCH_DIMENSIONS = max(
                0,
                min(3, int(cfg.get("relaxed_min_match_dimensions") or 0)),
            )
            applied.append("relaxed_min_match_dimensions")
        except Exception:
            warnings.append("invalid_relaxed_min_match_dimensions")

    if "relaxed_min_match_score" in cfg:
        try:
            RELAXED_MIN_MATCH_SCORE = max(
                0.0,
                min(10.0, float(cfg.get("relaxed_min_match_score") or 0.0)),
            )
            applied.append("relaxed_min_match_score")
        except Exception:
            warnings.append("invalid_relaxed_min_match_score")

    if "relaxed_max_candidates" in cfg:
        try:
            PACKET_RELAXED_MAX_CANDIDATES = max(
                1,
                min(30, int(cfg.get("relaxed_max_candidates") or 1)),
            )
            applied.append("relaxed_max_candidates")
        except Exception:
            warnings.append("invalid_relaxed_max_candidates")

    if "packet_lookup_candidates" in cfg:
        try:
            PACKET_LOOKUP_CANDIDATES = max(
                1,
                min(30, int(cfg.get("packet_lookup_candidates") or 1)),
            )
            applied.append("packet_lookup_candidates")
        except Exception:
            warnings.append("invalid_packet_lookup_candidates")

    # LLM reranking config → set on extracted module
    if "packet_lookup_llm_enabled" in cfg:
        _llm_reranker.PACKET_LOOKUP_LLM_ENABLED = _coerce_bool(
            cfg.get("packet_lookup_llm_enabled"),
            _llm_reranker.PACKET_LOOKUP_LLM_ENABLED,
        )
        applied.append("packet_lookup_llm_enabled")

    if "packet_lookup_llm_provider" in cfg:
        _llm_reranker.PACKET_LOOKUP_LLM_PROVIDER = _sanitize_lookup_provider(cfg.get("packet_lookup_llm_provider"))
        applied.append("packet_lookup_llm_provider")

    if "packet_lookup_llm_timeout_s" in cfg:
        try:
            _llm_reranker.PACKET_LOOKUP_LLM_TIMEOUT_S = max(0.2, float(cfg.get("packet_lookup_llm_timeout_s")))
            applied.append("packet_lookup_llm_timeout_s")
        except Exception:
            warnings.append("invalid_packet_lookup_llm_timeout_s")

    if "packet_lookup_llm_top_k" in cfg:
        try:
            _llm_reranker.PACKET_LOOKUP_LLM_TOP_K = max(1, min(20, int(cfg.get("packet_lookup_llm_top_k") or 1)))
            applied.append("packet_lookup_llm_top_k")
        except Exception:
            warnings.append("invalid_packet_lookup_llm_top_k")

    if "packet_lookup_llm_min_candidates" in cfg:
        try:
            _llm_reranker.PACKET_LOOKUP_LLM_MIN_CANDIDATES = max(
                1, min(20, int(cfg.get("packet_lookup_llm_min_candidates") or 1))
            )
            applied.append("packet_lookup_llm_min_candidates")
        except Exception:
            warnings.append("invalid_packet_lookup_llm_min_candidates")

    if "packet_lookup_llm_context_chars" in cfg:
        try:
            _llm_reranker.PACKET_LOOKUP_LLM_CONTEXT_CHARS = max(
                40, min(5000, int(cfg.get("packet_lookup_llm_context_chars") or 40))
            )
            applied.append("packet_lookup_llm_context_chars")
        except Exception:
            warnings.append("invalid_packet_lookup_llm_context_chars")

    if "packet_lookup_llm_provider_url" in cfg:
        url = str(cfg.get("packet_lookup_llm_provider_url") or _llm_reranker.PACKET_LOOKUP_LLM_URL).strip()
        if url:
            _llm_reranker.PACKET_LOOKUP_LLM_URL = url.rstrip("/")
            applied.append("packet_lookup_llm_provider_url")

    if "packet_lookup_llm_model" in cfg:
        model = str(cfg.get("packet_lookup_llm_model") or _llm_reranker.PACKET_LOOKUP_LLM_MODEL).strip()
        if model:
            _llm_reranker.PACKET_LOOKUP_LLM_MODEL = model
            applied.append("packet_lookup_llm_model")

    if "obsidian_enabled" in cfg:
        OBSIDIAN_EXPORT_ENABLED = _coerce_bool(
            cfg.get("obsidian_enabled"),
            OBSIDIAN_EXPORT_ENABLED,
        )
        applied.append("obsidian_enabled")

    if "obsidian_auto_export" in cfg:
        OBSIDIAN_AUTO_EXPORT = _coerce_bool(
            cfg.get("obsidian_auto_export"),
            OBSIDIAN_AUTO_EXPORT,
        )
        applied.append("obsidian_auto_export")

    if "obsidian_export_max_packets" in cfg:
        try:
            OBSIDIAN_EXPORT_MAX_PACKETS = max(1, min(5000, int(cfg.get("obsidian_export_max_packets") or 1)))
            applied.append("obsidian_export_max_packets")
        except Exception:
            warnings.append("invalid_obsidian_export_max_packets")

    if "obsidian_export_dir" in cfg:
        try:
            raw_dir = str(cfg.get("obsidian_export_dir") or DEFAULT_OBSIDIAN_EXPORT_DIR).strip()
            if raw_dir:
                _obsidian_dir_override(raw_dir)
            applied.append("obsidian_export_dir")
        except Exception:
            warnings.append("invalid_obsidian_export_dir")

    return {"applied": applied, "warnings": warnings}


def _reload_packet_store_config(_cfg: Dict[str, Any]) -> None:
    apply_packet_store_config(_load_packet_store_config())


def get_packet_store_config() -> Dict[str, Any]:
    return {
        "packet_ttl_s": float(DEFAULT_PACKET_TTL_S),
        "max_index_packets": int(MAX_INDEX_PACKETS),
        "relaxed_effectiveness_weight": float(RELAXED_EFFECTIVENESS_WEIGHT),
        "relaxed_low_effectiveness_threshold": float(RELAXED_LOW_EFFECTIVENESS_THRESHOLD),
        "relaxed_low_effectiveness_penalty": float(RELAXED_LOW_EFFECTIVENESS_PENALTY),
        "relaxed_min_match_dimensions": int(RELAXED_MIN_MATCH_DIMENSIONS),
        "relaxed_min_match_score": float(RELAXED_MIN_MATCH_SCORE),
        "relaxed_max_candidates": int(PACKET_RELAXED_MAX_CANDIDATES),
        "packet_lookup_candidates": int(PACKET_LOOKUP_CANDIDATES),
        "packet_lookup_llm_enabled": bool(_llm_reranker.PACKET_LOOKUP_LLM_ENABLED),
        "packet_lookup_llm_provider": str(_llm_reranker.PACKET_LOOKUP_LLM_PROVIDER),
        "packet_lookup_llm_timeout_s": float(_llm_reranker.PACKET_LOOKUP_LLM_TIMEOUT_S),
        "packet_lookup_llm_top_k": int(_llm_reranker.PACKET_LOOKUP_LLM_TOP_K),
        "packet_lookup_llm_min_candidates": int(_llm_reranker.PACKET_LOOKUP_LLM_MIN_CANDIDATES),
        "packet_lookup_llm_context_chars": int(_llm_reranker.PACKET_LOOKUP_LLM_CONTEXT_CHARS),
        "packet_lookup_llm_provider_url": str(_llm_reranker.PACKET_LOOKUP_LLM_URL),
        "packet_lookup_llm_model": str(_llm_reranker.PACKET_LOOKUP_LLM_MODEL),
        "obsidian_enabled": bool(OBSIDIAN_EXPORT_ENABLED),
        "obsidian_auto_export": bool(OBSIDIAN_AUTO_EXPORT),
        "obsidian_export_max_packets": int(OBSIDIAN_EXPORT_MAX_PACKETS),
        "obsidian_export_dir": str(_obsidian_export_dir()),
    }


def get_store_status() -> Dict[str, Any]:
    index = _load_index()
    meta = index.get("packet_meta") or {}
    total = len(meta)
    active = sum(1 for row in meta.values() if not bool((row or {}).get("invalidated")))
    now_value = _now()
    source_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    fresh = sum(
        1
        for row in meta.values()
        if (not bool((row or {}).get("invalidated")))
        and float((row or {}).get("fresh_until_ts", 0.0)) >= now_value
    )
    queue_depth = 0
    try:
        if PREFETCH_QUEUE_FILE.exists():
            queue_depth = len([ln for ln in PREFETCH_QUEUE_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()])
    except Exception:
        queue_depth = 0
    usage_total = sum(_meta_count(row, "usage_count", fallback_key="read_count") for row in meta.values())
    emit_total = sum(_meta_count(row, "emit_count") for row in meta.values())
    deliver_total = sum(_meta_count(row, "deliver_count", fallback_key="emit_count") for row in meta.values())
    read_total = sum(_meta_count(row, "read_count") for row in meta.values())
    feedback_total = sum(_meta_count(row, "feedback_count") for row in meta.values())
    noisy_total = sum(_meta_count(row, "noisy_count") for row in meta.values())
    avg_effectiveness = 0.0
    freshness_age_sum = 0.0
    freshness_age_count = 0
    age_sum = 0.0
    age_count = 0
    stale = 0
    ready_meta = 0
    inactive = total - active
    if meta:
        avg_effectiveness = sum(
            float((row or {}).get("effectiveness_score", 0.5) or 0.5)
            for row in meta.values()
        ) / max(1, len(meta))
        for row in meta.values():
            if bool((row or {}).get("invalidated")):
                continue
            flags = _readiness_flags(_normalize_packet(dict(row)))
            if bool(flags.get("ready_for_use")):
                ready_meta += 1
            for source in _safe_list(row.get("source_summary"), max_items=1):
                source_counter[source] += 1
            for category in _safe_list(row.get("category_summary"), max_items=1):
                category_counter[category] += 1
        for row in meta.values():
            if bool((row or {}).get("invalidated")):
                continue
            updated_ts = float((row or {}).get("updated_ts", 0.0) or 0.0)
            age_sum += max(0.0, now_value - updated_ts)
            age_count += 1
            freshness_age = float((row or {}).get("fresh_until_ts", 0.0) or 0.0) - now_value
            if freshness_age > 0.0:
                freshness_age_sum += freshness_age
                freshness_age_count += 1
    stale = sum(
        1
        for row in meta.values()
        if not bool((row or {}).get("invalidated"))
        and float((row or {}).get("fresh_until_ts", 0.0)) < now_value
    )
    active_rows = max(1, int(active))
    top_sources = [
        {"name": str(name), "count": int(count)}
        for name, count in source_counter.most_common(5)
    ]
    top_categories = [
        {"name": str(name), "count": int(count)}
        for name, count in category_counter.most_common(5)
    ]
    top_concentration = 0.0
    if top_categories:
        top_concentration = top_categories[0]["count"] / float(max(active_rows, 1))
    return {
        "schema_version": int(index.get(INDEX_SCHEMA_VERSION_KEY, 1) or 1),
        "total_packets": total,
        "active_packets": active,
        "fresh_packets": fresh,
        "stale_packets": stale,
        "inactive_packets": inactive,
        "freshness_ratio": round(float(fresh) / max(total, 1), 3),
        "ready_packets": int(ready_meta),
        "stale_ratio": round(float(stale) / max(total, 1), 3),
        "inactive_ratio": round(float(inactive) / max(total, 1), 3),
        "readiness_ratio": round(float(fresh) / max(active_rows, 1), 3),
        "catalog_size": int(total),
        "catalog_ready_packets": int(ready_meta),
        "top_sources": top_sources,
        "top_categories": top_categories,
        "top_category_concentration": round(float(top_concentration), 3),
        "lookup_candidate_budget": int(PACKET_LOOKUP_CANDIDATES),
        "packet_age_avg_s": round(float(age_sum / max(age_count, 1)), 2),
        "packet_freshness_age_avg_s": round(
            float(freshness_age_sum / max(freshness_age_count, 1)),
            2,
        ),
        "queue_depth": queue_depth,
        "usage_total": usage_total,
        "read_total": read_total,
        "emit_total": emit_total,
        "deliver_total": deliver_total,
        "category_inventory": [
            {"category": str(name), "count": int(count)}
            for name, count in category_counter.most_common(20)
        ],
        "source_inventory": [
            {"source": str(name), "count": int(count)}
            for name, count in source_counter.most_common(20)
        ],
        "feedback_total": feedback_total,
        "noisy_total": noisy_total,
        "emit_hit_rate": (emit_total / max(usage_total, 1)) if usage_total > 0 else None,
        "deliver_hit_rate": (deliver_total / max(usage_total, 1)) if usage_total > 0 else None,
        "hit_rate": (deliver_total / max(usage_total, 1)) if usage_total > 0 else None,
        "avg_effectiveness_score": round(float(avg_effectiveness), 3),
        "lookup_rerank_enabled": bool(_llm_reranker.PACKET_LOOKUP_LLM_ENABLED),
        "config": get_packet_store_config(),
        "lookup_rerank_provider": str(_llm_reranker.PACKET_LOOKUP_LLM_PROVIDER),
        "obsidian_enabled": bool(OBSIDIAN_EXPORT_ENABLED),
        "obsidian_auto_export": bool(OBSIDIAN_AUTO_EXPORT),
        "obsidian_export_dir": str(_obsidian_export_dir()),
        "obsidian_export_dir_exists": bool(_obsidian_export_dir().exists()),
        "obsidian_index_file": str(_obsidian_index_file()),
        "obsidian_watchtower_file": str(_obsidian_watchtower_file()),
        "obsidian_sync_status": _get_obsidian_status(),
        "decision_ledger": _decision_ledger_meta(),
        "index_file": str(INDEX_FILE),
    }


try:
    _BOOT_PACKET_CFG = _load_packet_store_config()
    if _BOOT_PACKET_CFG:
        apply_packet_store_config(_BOOT_PACKET_CFG)
    try:
        from .tuneables_reload import register_reload as _register_packet_store_reload

        _register_packet_store_reload(
            "advisory_packet_store",
            _reload_packet_store_config,
            label="advisory_packet_store.apply_config",
        )
    except Exception:
        pass
except Exception:
    pass

