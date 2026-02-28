"""Generate context-first advisory observability pages.

These pages focus on advisory usefulness as a traced, end-to-end system:
event capture -> queue -> engine decisions -> emitted advisory -> feedback.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..advisory_content_quality import build_production_noise_report
from .config import spark_dir
from .linker import flow_link, fmt_num
from .readers import _coerce_decision_outcome

_SD = spark_dir()
_REPO_ROOT = Path(__file__).resolve().parents[2]

_KNOWN_LABELS = {"helpful", "unhelpful", "harmful"}
_BLOCKING_EVENTS = {
    "gate_no_emit",
    "context_repeat_blocked",
    "text_repeat_blocked",
    "question_like_blocked",
    "global_dedupe_suppressed",
    "emit_failed",
    "synth_empty",
    "no_gate_emissions",
    "no_ranked_advice",
    "exception",
}

_ACTION_VERBS = (
    "use",
    "run",
    "check",
    "verify",
    "compare",
    "trace",
    "retry",
    "add",
    "remove",
    "refactor",
    "gate",
    "inspect",
    "log",
    "checkpoint",
    "align",
    "split",
    "sample",
    "audit",
    "rewrite",
)
_TRANSFER_CUES = ("if ", "when ", "before ", "after ", "always ", "never ")
_TRANSIENT_CUES = (
    "chunk id",
    "session:",
    "task-notification",
    "wall time:",
    "process exited with code",
    "traceback",
    "tool failed then recovered",
)
_CONVERSATIONAL_PATTERNS = [
    re.compile(r"^\s*(it worked|sounds good|sure|thanks)\b", re.IGNORECASE),
    re.compile(r"\bcan we\b", re.IGNORECASE),
    re.compile(r"\blet'?s do it\b", re.IGNORECASE),
    re.compile(r"\buser expressed satisfaction\b", re.IGNORECASE),
    re.compile(r"\buser persistently asking\b", re.IGNORECASE),
]
_TELEMETRY_PATTERNS = [
    re.compile(r"\bchunk id:\s*[a-f0-9]{4,}\b", re.IGNORECASE),
    re.compile(r"\bexec_command failed\b", re.IGNORECASE),
    re.compile(r"\bprocess exited with code\b", re.IGNORECASE),
    re.compile(r"\bwall time:\b", re.IGNORECASE),
    re.compile(r"<task-notification>", re.IGNORECASE),
    re.compile(r"\btool ['\"]?[a-z0-9_ -]+['\"]? failed then recovered\b", re.IGNORECASE),
    re.compile(r"\bexit code\s+\d+\b", re.IGNORECASE),
]
_CSS_PATTERN = re.compile(r"#[\w-]+\s*\{[^}]*\}|\{[^}]*\b(position|display|padding|margin)\b[^}]*\}", re.IGNORECASE)
_LABEL_WEIGHT = {"none": 0, "weak": 1, "medium": 2, "strong": 3}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path, *, max_rows: int = 12000) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    total = 0
    invalid = 0
    if not path.exists():
        return rows, {"lines": 0, "invalid_lines": 0}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                total += 1
                try:
                    row = json.loads(line)
                except Exception:
                    invalid += 1
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except Exception:
        return [], {"lines": 0, "invalid_lines": 0}
    if max_rows > 0 and len(rows) > max_rows:
        rows = rows[-max_rows:]
    return rows, {"lines": total, "invalid_lines": invalid}


def _parse_ts(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return float(text)
    except Exception:
        pass
    try:
        return float(datetime.fromisoformat(text).timestamp())
    except Exception:
        return 0.0


def _extract_ts(row: dict[str, Any], keys: Iterable[str] | None = None) -> float:
    if keys is None:
        keys = (
            "ts",
            "timestamp",
            "created_at",
            "created_ts",
            "emitted_ts",
            "request_ts",
            "resolved_at",
            "reviewed_at",
        )
    for key in keys:
        ts = _parse_ts(row.get(key))
        if ts > 0:
            return ts
    return 0.0


def _fmt_ts(ts: float) -> str:
    if ts <= 0:
        return "?"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _fmt_pct(numer: float, denom: float, digits: int = 1) -> str:
    if float(denom) <= 0.0:
        return f"{0.0:.{digits}f}%"
    pct = (100.0 * float(numer)) / float(denom)
    return f"{pct:.{digits}f}%"


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _short(text: str, limit: int = 170) -> str:
    txt = " ".join(_norm_text(text).split())
    if len(txt) <= limit:
        return txt
    return txt[: max(0, limit - 3)] + "..."


def _md_escape(value: Any, limit: int | None = None) -> str:
    text = _norm_text(value)
    if limit is not None:
        text = _short(text, limit)
    return text.replace("|", "\\|")


def _json_preview(value: Any, *, max_chars: int = 4000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=True, default=str, sort_keys=True, indent=2)
    except Exception:
        text = _norm_text(value)
    if not text:
        return "{}"
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)] + "..."


def _trace_from_row(row: dict[str, Any]) -> str:
    for key in ("trace_id", "outcome_trace_id", "trace"):
        value = _norm_text(row.get(key))
        if value:
            return value
    return ""


def _is_telemetry_text(text: str) -> bool:
    txt = _norm_text(text)
    if not txt:
        return False
    if _CSS_PATTERN.search(txt):
        return True
    return any(p.search(txt) for p in _TELEMETRY_PATTERNS)


def _is_conversational_text(text: str) -> bool:
    txt = _norm_text(text)
    if not txt:
        return False
    return any(p.search(txt) for p in _CONVERSATIONAL_PATTERNS)


def _extract_text(row: dict[str, Any]) -> str:
    candidates = (
        row.get("text"),
        row.get("advice_text"),
        row.get("insight"),
        row.get("signal"),
        row.get("summary"),
        row.get("notes"),
        row.get("event"),
    )
    for value in candidates:
        txt = _norm_text(value)
        if txt:
            return txt
    return ""


def _label_score(label: str) -> int:
    return _LABEL_WEIGHT.get(label, 0)


def _pick_decay_policy(text: str, transfer_score: str) -> str:
    txt = _norm_text(text).lower()
    if _is_telemetry_text(txt):
        return "prune_next_cycle"
    if _is_conversational_text(txt):
        return "short_window"
    if any(cue in txt for cue in _TRANSIENT_CUES):
        return "short_window"
    if transfer_score in {"strong", "medium"}:
        return "long_window"
    return "medium_window"


def _score_actionability(text: str) -> str:
    txt = _norm_text(text).lower()
    if not txt or _is_telemetry_text(txt) or _is_conversational_text(txt):
        return "none"
    if any(f"{verb} " in txt for verb in _ACTION_VERBS):
        if any(token in txt for token in ("file", "tool", "trace", "config", "route", "gate", "memory", "retriev")):
            return "strong"
        return "medium"
    if any(token in txt for token in ("should", "consider", "need to")):
        return "weak"
    return "none"


def _score_context_fit(row: dict[str, Any], text: str) -> str:
    tool = _norm_text(row.get("tool") or row.get("tool_name"))
    trace = _trace_from_row(row)
    txt = _norm_text(text).lower()
    if _is_telemetry_text(txt) or _is_conversational_text(txt):
        return "weak"
    has_tool_mention = bool(tool) and tool.lower() in txt
    has_scope = bool(trace) or bool(_norm_text(row.get("session_id"))) or bool(_norm_text(row.get("route")))
    if has_tool_mention and has_scope:
        return "strong"
    if has_scope:
        return "medium"
    return "weak"


def _score_causal_confidence(row: dict[str, Any], text: str) -> str:
    if _is_telemetry_text(text) or _is_conversational_text(text):
        return "none"
    helpful_label = _norm_text(row.get("helpfulness_label") or row.get("helpful_label")).lower()
    if helpful_label in _KNOWN_LABELS:
        return "strong"
    if _norm_text(row.get("validation_result")) in {"validated", "contradicted"}:
        return "medium"
    if row.get("followed") is True or bool(_norm_text(row.get("implicit_signal"))):
        return "weak"
    return "none"


def _score_transfer(text: str) -> str:
    txt = _norm_text(text).lower()
    if not txt:
        return "none"
    if _is_telemetry_text(txt) or _is_conversational_text(txt):
        return "none"
    if any(cue in txt for cue in _TRANSFER_CUES) and any(verb in txt for verb in _ACTION_VERBS):
        return "strong"
    if any(verb in txt for verb in _ACTION_VERBS):
        return "medium"
    return "weak"


def _keepability_verdict(row: dict[str, Any], text: str) -> tuple[str, dict[str, str], str]:
    actionability = _score_actionability(text)
    context_fit = _score_context_fit(row, text)
    causal = _score_causal_confidence(row, text)
    transfer = _score_transfer(text)
    decay = _pick_decay_policy(text, transfer)

    dims = {
        "actionability": actionability,
        "context_fit": context_fit,
        "causal_confidence": causal,
        "transfer_score": transfer,
        "decay_policy": decay,
    }

    if _is_telemetry_text(text):
        return "drop", dims, "Telemetry residue that should stay in ops logs, not intelligence memory."
    if _is_conversational_text(text):
        return "drop", dims, "Conversational residue should be rewritten into explicit guidance before keeping."
    if _label_score(actionability) >= 2 and _label_score(context_fit) >= 1 and _label_score(transfer) >= 2:
        return "keep", dims, "Actionable pattern with enough context shape and transfer value."
    if _label_score(actionability) >= 1 or _label_score(context_fit) >= 2:
        return "rewrite", dims, "Potentially useful but phrasing/context is weak; rewrite before keeping."
    return "drop", dims, "Low actionability and weak transfer; not worth long-lived intelligence storage."


def _load_decision_rows(limit: int = 10000) -> tuple[list[dict[str, Any]], str, Path]:
    ledger_path = _SD / "advisory_decision_ledger.jsonl"
    engine_path = _SD / "advisory_engine_alpha.jsonl"
    emit_path = _SD / "advisory_emit.jsonl"

    ledger_rows, _ = _read_jsonl(ledger_path, max_rows=limit)
    if ledger_rows:
        return ledger_rows, "advisory_decision_ledger", ledger_path

    engine_rows_raw, _ = _read_jsonl(engine_path, max_rows=max(limit * 2, 4000))
    if engine_rows_raw:
        normalized: list[dict[str, Any]] = []
        for row in engine_rows_raw:
            outcome = _coerce_decision_outcome(row)
            if outcome == "unknown":
                continue
            rec = dict(row)
            rec["outcome"] = outcome
            rec["tool"] = _norm_text(rec.get("tool") or rec.get("tool_name") or "?")
            rec["route"] = _norm_text(rec.get("route") or rec.get("delivery_route") or "alpha")
            reason = _norm_text(rec.get("gate_reason") or rec.get("reason"))
            if reason and outcome == "blocked" and not rec.get("suppressed_reasons"):
                rec["suppressed_reasons"] = [{"reason": reason, "count": 1}]
            normalized.append(rec)
        return normalized[-limit:], "advisory_engine_alpha_fallback", engine_path

    emit_rows_raw, _ = _read_jsonl(emit_path, max_rows=limit)
    if emit_rows_raw:
        normalized = []
        for row in emit_rows_raw:
            rec = dict(row)
            rec["outcome"] = "emitted"
            rec["tool"] = _norm_text(rec.get("tool") or rec.get("tool_name") or "?")
            rec["route"] = _norm_text(rec.get("route") or "emit_fallback")
            normalized.append(rec)
        return normalized, "advisory_emit_fallback", emit_path

    return [], "none", ledger_path


def _extract_suppression_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    raw = row.get("suppressed_reasons")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                reason = _norm_text(item.get("reason"))
            else:
                reason = _norm_text(item)
            if reason:
                reasons.append(reason)
    for key in ("gate_reason", "reason", "event"):
        reason = _norm_text(row.get(key))
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def _classify_reason(reason: str) -> str:
    txt = reason.lower()
    if "global_dedupe" in txt:
        return "global_dedupe"
    if "question_like" in txt:
        return "question_like"
    if "context_repeat" in txt or "repeat" in txt:
        return "repeat_guard"
    if "cooldown" in txt:
        return "cooldown"
    if "budget" in txt:
        return "budget"
    if "synth" in txt:
        return "synth"
    if "no_ranked_advice" in txt:
        return "retrieval_empty"
    return "other"


def _distribution(counter: Counter[str]) -> dict[str, float]:
    total = float(sum(counter.values()))
    if total <= 0:
        return {}
    return {k: float(v) / total for k, v in counter.items()}


def _drift_score(prev: Counter[str], curr: Counter[str]) -> tuple[float, list[tuple[str, float, float, float]]]:
    prev_dist = _distribution(prev)
    curr_dist = _distribution(curr)
    keys = sorted(set(prev_dist.keys()) | set(curr_dist.keys()))
    deltas: list[tuple[str, float, float, float]] = []
    l1 = 0.0
    for key in keys:
        p = prev_dist.get(key, 0.0)
        c = curr_dist.get(key, 0.0)
        diff = abs(c - p)
        l1 += diff
        deltas.append((key, p, c, diff))
    deltas.sort(key=lambda row: row[3], reverse=True)
    return round((l1 / 2.0) * 100.0, 1), deltas


def _split_windows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not rows:
        return [], []
    with_ts = [row for row in rows if _extract_ts(row) > 0]
    if with_ts:
        ordered = sorted(with_ts, key=_extract_ts)
    else:
        ordered = rows[:]
    mid = max(1, len(ordered) // 2)
    return ordered[:mid], ordered[mid:]


def _norm_cmp_text(value: Any) -> str:
    return " ".join(_norm_text(value).lower().split())


def _queue_trace_id(row: dict[str, Any]) -> str:
    trace = _trace_from_row(row)
    if trace:
        return trace
    data = row.get("data")
    if isinstance(data, dict):
        return _norm_text(data.get("trace_id"))
    return ""


def _parse_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _tool_input_summary(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return "-"
    tool_input = row.get("tool_input")
    if not isinstance(tool_input, dict):
        data = row.get("data")
        if isinstance(data, dict) and isinstance(data.get("tool_input"), dict):
            tool_input = data.get("tool_input")
        else:
            tool_input = {}

    parts: list[str] = []
    key_order = (
        "cmd",
        "command",
        "file_path",
        "path",
        "description",
        "pattern",
        "query",
        "url",
        "offset",
        "limit",
    )
    for key in key_order:
        if key in tool_input:
            value = _norm_text(tool_input.get(key))
            if value:
                parts.append(f"{key}={value}")
    if not parts:
        for key, value in list(tool_input.items())[:4]:
            text = _norm_text(value)
            if text:
                parts.append(f"{key}={text}")
    joined = "; ".join(parts) if parts else "-"
    err = _norm_text((row or {}).get("error"))
    if err:
        joined = f"{joined}; error={err}"
    return _short(joined, 320)


def _load_eidos_distillation_lookup() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    db_path = _SD / "eidos.db"
    if not db_path.exists():
        return {}, {}

    by_prefix: dict[str, dict[str, Any]] = {}
    by_statement: dict[str, dict[str, Any]] = {}

    def _upsert(record: dict[str, Any]) -> None:
        distillation_id = _norm_text(record.get("distillation_id"))
        if not distillation_id:
            return
        prefix = distillation_id[:8]
        existing = by_prefix.get(prefix)
        if existing is None or _to_float(record.get("created_at"), 0.0) >= _to_float(existing.get("created_at"), 0.0):
            by_prefix[prefix] = record
        stmt = _norm_cmp_text(record.get("refined_statement") or record.get("statement"))
        if stmt:
            prev = by_statement.get(stmt)
            if prev is None or _to_float(record.get("created_at"), 0.0) >= _to_float(prev.get("created_at"), 0.0):
                by_statement[stmt] = record

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for table in ("distillations", "distillations_archive"):
            try:
                rows = cur.execute(
                    f"""
                    SELECT distillation_id, type, statement, refined_statement, confidence, created_at, advisory_quality
                    FROM {table}
                    ORDER BY created_at DESC
                    """
                ).fetchall()
            except Exception:
                continue
            for row in rows:
                payload = dict(row)
                payload["table"] = table
                payload["advisory_quality"] = _parse_json_dict(payload.get("advisory_quality"))
                _upsert(payload)
        conn.close()
    except Exception:
        return {}, {}

    return by_prefix, by_statement


def _build_recent_advice_item_index(
    rows: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_trace_advice: dict[tuple[str, str], dict[str, Any]] = {}
    by_advice: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for run in rows:
        trace_id = _trace_from_row(run)
        run_id = _norm_text(run.get("run_id"))
        route = _norm_text(run.get("route"))
        tool = _norm_text(run.get("tool"))
        run_ts = _extract_ts(run, keys=("recorded_at", "ts", "timestamp", "created_at"))
        advice_ids = run.get("advice_ids") if isinstance(run.get("advice_ids"), list) else []
        advice_texts = run.get("advice_texts") if isinstance(run.get("advice_texts"), list) else []
        insight_keys = run.get("insight_keys") if isinstance(run.get("insight_keys"), list) else []
        sources = run.get("sources") if isinstance(run.get("sources"), list) else []
        categories = run.get("categories") if isinstance(run.get("categories"), list) else []
        readiness = run.get("advisory_readiness") if isinstance(run.get("advisory_readiness"), list) else []
        quality = run.get("advisory_quality") if isinstance(run.get("advisory_quality"), list) else []

        for idx, aid_raw in enumerate(advice_ids):
            advice_id = _norm_text(aid_raw)
            if not advice_id:
                continue
            entry = {
                "_ts": run_ts,
                "trace_id": trace_id,
                "run_id": run_id,
                "route": route,
                "tool": tool,
                "advice_id": advice_id,
                "advice_text": _norm_text(advice_texts[idx]) if idx < len(advice_texts) else "",
                "insight_key": _norm_text(insight_keys[idx]) if idx < len(insight_keys) else "",
                "source": _norm_text(sources[idx]) if idx < len(sources) else "",
                "category": _norm_text(categories[idx]) if idx < len(categories) else "",
                "advisory_readiness": readiness[idx] if idx < len(readiness) else None,
                "advisory_quality": quality[idx] if idx < len(quality) else {},
            }
            if trace_id:
                key = (trace_id, advice_id)
                prev = by_trace_advice.get(key)
                if prev is None or _to_float(entry.get("_ts"), 0.0) >= _to_float(prev.get("_ts"), 0.0):
                    by_trace_advice[key] = entry
            by_advice[advice_id].append(entry)

    for advice_id, items in by_advice.items():
        by_advice[advice_id] = sorted(items, key=lambda item: _to_float(item.get("_ts"), 0.0), reverse=True)

    return by_trace_advice, by_advice


def _find_roast_for_text(
    text: str,
    roast_exact: dict[str, dict[str, Any]],
    roast_rows: list[dict[str, Any]],
    cache: dict[str, dict[str, Any] | None],
) -> dict[str, Any] | None:
    norm = _norm_cmp_text(text)
    if not norm:
        return None
    if norm in cache:
        return cache[norm]
    exact = roast_exact.get(norm)
    if exact is not None:
        cache[norm] = exact
        return exact

    match: dict[str, Any] | None = None
    if len(norm) >= 24:
        for row in reversed(roast_rows):
            result = row.get("result") if isinstance(row.get("result"), dict) else {}
            orig = _norm_cmp_text((result or {}).get("original"))
            if not orig:
                continue
            if norm in orig or orig in norm:
                match = row
                break
    cache[norm] = match
    return match


def _advisory_emission_lineage_deep_page(sample_size: int = 160) -> str:
    limit = max(120, int(sample_size))
    quality_all_rows, _ = _read_jsonl(_SD / "advisor" / "advisory_quality_events.jsonl", max_rows=50000)
    quality_all_rows = [row for row in quality_all_rows if _norm_text(row.get("advice_id"))]
    quality_all_rows.sort(
        key=lambda row: _extract_ts(row, keys=("emitted_ts", "recorded_at", "ts", "timestamp", "created_at")),
        reverse=True,
    )

    def _is_synthetic_quality(row: dict[str, Any]) -> bool:
        trace = _trace_from_row(row).lower()
        session_id = _norm_text(row.get("session_id")).lower()
        run_id = _norm_text(row.get("run_id")).lower()
        return trace.startswith("arena:") or session_id.startswith("arena:") or run_id.startswith("arena:")

    quality_non_synth = [row for row in quality_all_rows if not _is_synthetic_quality(row)]
    quality_synth = [row for row in quality_all_rows if _is_synthetic_quality(row)]
    quality_rows = (quality_non_synth[:limit] + quality_synth[: max(0, limit - len(quality_non_synth[:limit]))])[:limit]

    recent_rows, _ = _read_jsonl(_SD / "advisor" / "recent_advice.jsonl", max_rows=35000)
    recent_rows.sort(key=_extract_ts, reverse=True)
    run_item_by_trace_advice, run_items_by_advice = _build_recent_advice_item_index(recent_rows)

    queue_rows, _ = _read_jsonl(_SD / "queue" / "events.jsonl", max_rows=50000)
    queue_rows = sorted(queue_rows, key=_extract_ts)
    queue_by_trace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in queue_rows:
        trace = _queue_trace_id(row)
        if trace:
            queue_by_trace[trace].append(row)

    retrieval_rows, _ = _read_jsonl(_SD / "advisor" / "retrieval_router.jsonl", max_rows=50000)
    retrieval_by_trace: dict[str, dict[str, Any]] = {}
    for row in sorted(retrieval_rows, key=_extract_ts, reverse=True):
        trace = _trace_from_row(row)
        if trace and trace not in retrieval_by_trace:
            retrieval_by_trace[trace] = row

    decision_rows, decision_source, _ = _load_decision_rows(limit=50000)
    decision_by_trace: dict[str, dict[str, Any]] = {}
    for row in sorted(decision_rows, key=_extract_ts, reverse=True):
        trace = _trace_from_row(row)
        if trace and trace not in decision_by_trace:
            decision_by_trace[trace] = row

    outcome_rows, _ = _read_jsonl(_SD / "outcomes.jsonl", max_rows=50000)
    outcome_by_trace: dict[str, dict[str, Any]] = {}
    for row in sorted(outcome_rows, key=_extract_ts, reverse=True):
        trace = _trace_from_row(row)
        if trace and trace not in outcome_by_trace:
            outcome_by_trace[trace] = row

    feedback_rows, _ = _read_jsonl(_SD / "advice_feedback.jsonl", max_rows=50000)
    feedback_by_trace_advice: dict[tuple[str, str], dict[str, Any]] = {}
    for row in sorted(feedback_rows, key=_extract_ts, reverse=True):
        trace = _trace_from_row(row)
        advice_ids = row.get("advice_ids") if isinstance(row.get("advice_ids"), list) else []
        for aid_raw in advice_ids:
            aid = _norm_text(aid_raw)
            if not trace or not aid:
                continue
            key = (trace, aid)
            if key not in feedback_by_trace_advice:
                feedback_by_trace_advice[key] = row

    implicit_rows, _ = _read_jsonl(_SD / "advisor" / "implicit_feedback.jsonl", max_rows=50000)
    implicit_by_trace: dict[str, dict[str, Any]] = {}
    for row in sorted(implicit_rows, key=_extract_ts, reverse=True):
        trace = _trace_from_row(row)
        if trace and trace not in implicit_by_trace:
            implicit_by_trace[trace] = row

    cognitive_payload = _read_json(_SD / "cognitive_insights.json")
    if not isinstance(cognitive_payload, dict):
        cognitive_payload = {}

    roast_payload = _read_json(_SD / "meta_ralph" / "roast_history.json")
    roast_rows = roast_payload.get("history") if isinstance(roast_payload.get("history"), list) else []
    roast_exact: dict[str, dict[str, Any]] = {}
    for row in roast_rows:
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        original_norm = _norm_cmp_text((result or {}).get("original"))
        if original_norm:
            roast_exact[original_norm] = row
    roast_cache: dict[str, dict[str, Any] | None] = {}

    eidos_by_prefix, eidos_by_statement = _load_eidos_distillation_lookup()

    lineage_rows: list[dict[str, Any]] = []
    for row in quality_rows:
        advice_id = _norm_text(row.get("advice_id"))
        trace_id = _trace_from_row(row)
        tool = _norm_text(row.get("tool") or row.get("tool_name")) or "?"
        emitted_ts = _extract_ts(row, keys=("emitted_ts", "recorded_at", "ts", "timestamp", "created_at"))

        run_item = run_item_by_trace_advice.get((trace_id, advice_id))
        if run_item is None:
            fallback = run_items_by_advice.get(advice_id, [])
            run_item = fallback[0] if fallback else None

        insight_key = _norm_text((run_item or {}).get("insight_key"))
        source_hint = _norm_text(row.get("source_hint") or (run_item or {}).get("source")) or "?"
        run_id = _norm_text(row.get("run_id") or (run_item or {}).get("run_id"))
        advice_text = _norm_text(row.get("advice_text") or (run_item or {}).get("advice_text"))

        trace_queue = queue_by_trace.get(trace_id, [])
        pre_row = next((r for r in trace_queue if _norm_text(r.get("event_type")).startswith("pre_")), trace_queue[0] if trace_queue else None)
        post_row = next((r for r in trace_queue if _norm_text(r.get("event_type")).startswith("post_")), None)
        capture_event = _norm_text((pre_row or {}).get("event_type") or ((pre_row or {}).get("data") or {}).get("hook_event")) or "-"
        capture_text = _tool_input_summary(pre_row)
        if capture_text == "-" and isinstance(post_row, dict):
            capture_text = _tool_input_summary(post_row)
        if capture_text == "-":
            capture_text = _norm_text(((pre_row or {}).get("data") or {}).get("hook_event")) or "-"

        memory_row = cognitive_payload.get(insight_key) if insight_key in cognitive_payload else None
        memory_text = _norm_text((memory_row or {}).get("insight") or (memory_row or {}).get("content"))
        memory_source = _norm_text((memory_row or {}).get("source")) or ("eidos" if insight_key.startswith("eidos:") else "-")
        memory_created = _norm_text((memory_row or {}).get("created_at"))
        memory_reliability = _norm_text((memory_row or {}).get("reliability"))
        memory_validated = _norm_text((memory_row or {}).get("times_validated"))
        memory_contradicted = _norm_text((memory_row or {}).get("times_contradicted"))
        memory_readiness = (memory_row or {}).get("advisory_readiness")
        memory_quality = _parse_json_dict((memory_row or {}).get("advisory_quality"))
        memory_unified = memory_quality.get("unified_score")
        memory_context = _norm_text((memory_row or {}).get("context"))
        if not memory_text:
            run_text = _norm_text((run_item or {}).get("advice_text"))
            if run_text:
                memory_text = run_text
                memory_source = f"{source_hint}:ephemeral"
                memory_context = memory_context or "No durable cognitive row found for this insight key."

        roast_row = _find_roast_for_text(memory_text or advice_text, roast_exact, roast_rows, roast_cache)
        roast_result = roast_row.get("result") if isinstance((roast_row or {}).get("result"), dict) else {}
        roast_score = roast_result.get("score") if isinstance(roast_result.get("score"), dict) else {}
        roast_verdict = _norm_text(roast_result.get("verdict"))
        roast_total = roast_score.get("total")

        dist_row: dict[str, Any] | None = None
        dist_prefix = ""
        if advice_id.startswith("eidos:"):
            parts = [part for part in advice_id.split(":") if part]
            if parts:
                dist_prefix = parts[-1][:8]
        if not dist_prefix and insight_key.startswith("eidos:"):
            parts = [part for part in insight_key.split(":") if part]
            if parts:
                dist_prefix = parts[-1][:8]
        if dist_prefix:
            dist_row = eidos_by_prefix.get(dist_prefix)
        if dist_row is None:
            stmt_norm = _norm_cmp_text(advice_text.replace("[EIDOS POLICY]", "").replace("[EIDOS SHARP_EDGE]", ""))
            dist_row = eidos_by_statement.get(stmt_norm) if stmt_norm else None

        dist_quality = _parse_json_dict((dist_row or {}).get("advisory_quality"))
        dist_unified = dist_quality.get("unified_score")
        dist_conf = (dist_row or {}).get("confidence")
        dist_type = _norm_text((dist_row or {}).get("type"))
        dist_id = _norm_text((dist_row or {}).get("distillation_id"))
        dist_statement = _norm_text((dist_row or {}).get("refined_statement") or (dist_row or {}).get("statement"))
        dist_created = _to_float((dist_row or {}).get("created_at"), 0.0)
        if not memory_text and dist_statement:
            memory_text = dist_statement
            memory_source = "eidos:distillation"
            memory_context = memory_context or "Backfilled from EIDOS distillation statement."

        retrieval = retrieval_by_trace.get(trace_id, {})
        retrieval_context = (
            f"route={_norm_text(retrieval.get('route')) or '-'}; "
            f"reason={_norm_text(retrieval.get('reason')) or '-'}; "
            f"primary={_norm_text(retrieval.get('primary_count')) or '0'}; "
            f"returned={_norm_text(retrieval.get('returned_count')) or '0'}; "
            f"top={_norm_text(retrieval.get('primary_top_score')) or '-'}; "
            f"over_budget={_norm_text(retrieval.get('fast_path_over_budget')) or '-'}"
        )

        decision = decision_by_trace.get(trace_id, {})
        decision_extra = decision.get("extra") if isinstance(decision.get("extra"), dict) else {}
        decision_context = (
            f"event={_norm_text(decision.get('event')) or '-'}; "
            f"outcome={_norm_text(decision.get('outcome')) or '-'}; "
            f"retrieved={_norm_text(decision_extra.get('retrieved')) or '-'}; "
            f"emitted_count={_norm_text(decision_extra.get('emitted_count')) or '-'}; "
            f"gate_reason={_norm_text(decision.get('gate_reason') or decision_extra.get('gate_reason')) or '-'}"
        )

        outcome = outcome_by_trace.get(trace_id, {})
        feedback = feedback_by_trace_advice.get((trace_id, advice_id), {})
        implicit = implicit_by_trace.get(trace_id, {})
        quality_context = (
            f"helpfulness={_norm_text(row.get('helpfulness_label') or row.get('helpful_label')) or 'unknown'}; "
            f"followed={_norm_text(row.get('followed')) or '-'}; "
            f"judge={_norm_text(row.get('judge_source')) or '-'}; "
            f"impact={_norm_text(row.get('impact_score')) or '-'}; "
            f"usefulness={_norm_text(row.get('usefulness_score')) or '-'}"
        )
        feedback_context = (
            f"explicit(status={_norm_text(feedback.get('status')) or '-'}, helpful={_norm_text(feedback.get('helpful')) or '-'}, source={_norm_text(feedback.get('source')) or '-'})"
            if feedback
            else "explicit(-)"
        )
        implicit_context = (
            f"implicit(signal={_norm_text(implicit.get('signal')) or '-'}, tool={_norm_text(implicit.get('tool')) or '-'})"
            if implicit
            else "implicit(-)"
        )
        outcome_text = _norm_text(outcome.get("text"))
        outcome_context = (
            f"{_norm_text(outcome.get('event_type')) or '-'}; polarity={_norm_text(outcome.get('polarity')) or '-'}; text={_short(outcome_text, 180)}"
            if outcome
            else "-"
        )
        evidence_refs = "; ".join(
            [
                f"capture=queue/events.jsonl#{trace_id or '-'}",
                f"memory=cognitive_insights.json#{insight_key or '-'}",
                f"meta=meta_ralph/roast_history.json#{_norm_text((roast_row or {}).get('timestamp')) or '-'}",
                f"dist=eidos.db#{dist_id or '-'}",
                f"retrieval=advisor/retrieval_router.jsonl#{trace_id or '-'}",
                f"decision={decision_source}#{trace_id or '-'}",
                f"quality=advisor/advisory_quality_events.jsonl#{advice_id or '-'}",
            ]
        )

        lineage_rows.append(
            {
                "emitted_ts": emitted_ts,
                "trace_id": trace_id,
                "tool": tool,
                "advice_id": advice_id,
                "run_id": run_id,
                "source_hint": source_hint,
                "insight_key": insight_key,
                "capture_event": capture_event,
                "capture_text": capture_text,
                "memory_text": memory_text,
                "memory_source": memory_source,
                "memory_created": memory_created,
                "memory_reliability": memory_reliability,
                "memory_validated": memory_validated,
                "memory_contradicted": memory_contradicted,
                "memory_context": memory_context,
                "memory_readiness": memory_readiness,
                "memory_unified": memory_unified,
                "meta_verdict": roast_verdict or "-",
                "meta_total": roast_total,
                "meta_actionability": roast_score.get("actionability"),
                "meta_reasoning": roast_score.get("reasoning"),
                "meta_specificity": roast_score.get("specificity"),
                "meta_outcome_linked": roast_score.get("outcome_linked"),
                "meta_ts": _norm_text((roast_row or {}).get("timestamp")),
                "dist_id": dist_id,
                "dist_type": dist_type,
                "dist_conf": dist_conf,
                "dist_unified": dist_unified,
                "dist_created_ts": dist_created,
                "dist_statement": dist_statement,
                "retrieval_context": retrieval_context,
                "decision_context": decision_context,
                "advice_text": advice_text,
                "synthetic": _is_synthetic_quality(row),
                "quality_context": quality_context,
                "feedback_context": feedback_context,
                "implicit_context": implicit_context,
                "outcome_context": outcome_context,
                "evidence_refs": evidence_refs,
                "capture_row": pre_row or post_row or {},
                "memory_row": memory_row or {},
                "meta_row": roast_row or {},
                "dist_row": dist_row or {},
                "retrieval_row": retrieval or {},
                "decision_row": decision or {},
                "quality_row": row,
                "feedback_row": feedback or {},
                "implicit_row": implicit or {},
                "outcome_row": outcome or {},
            }
        )

    with_capture = sum(1 for row in lineage_rows if row.get("capture_text") and row.get("capture_text") != "-")
    with_memory = sum(1 for row in lineage_rows if _norm_text(row.get("memory_text")))
    with_meta = sum(1 for row in lineage_rows if _norm_text(row.get("meta_verdict")) not in {"", "-"})
    eidos_items = [row for row in lineage_rows if _norm_text(row.get("source_hint")) == "eidos" or _norm_text(row.get("advice_id")).startswith("eidos:")]
    with_dist = sum(1 for row in eidos_items if _norm_text(row.get("dist_id")))
    with_retrieval = sum(1 for row in lineage_rows if "route=" in _norm_text(row.get("retrieval_context")))
    with_decision = sum(1 for row in lineage_rows if "event=" in _norm_text(row.get("decision_context")))
    with_outcome = sum(1 for row in lineage_rows if _norm_text(row.get("outcome_context")) != "-")
    synthetic_rows = sum(1 for row in lineage_rows if bool(row.get("synthetic")))

    lines = [
        "---",
        "title: Advisory Emission Lineage Deep Dive",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - lineage",
        "  - context-first",
        "  - stage-trace",
        "---",
        "",
        "# Advisory Emission Lineage Deep Dive",
        "",
        f"> {flow_link()} | [[stages/01-event_capture|Stage 1]] -> [[stages/08-advisory|Stage 8]] -> [[stages/11-predictions|Stage 11]]",
        f"> Decision source: `{decision_source}`",
        "",
        "This page traces each emitted advisory item through the full stage chain with raw context.",
        "Use it to answer: what was observed, what was stored, what scored where, and what finally emitted.",
        "",
        "## Coverage Snapshot",
        "",
        f"- Emitted advisory items analyzed: `{len(lineage_rows)}`",
        f"- Synthetic replay rows in sample: `{synthetic_rows}` ({_fmt_pct(synthetic_rows, max(len(lineage_rows), 1))})",
        f"- With Stage 1/2 capture evidence: `{with_capture}` ({_fmt_pct(with_capture, max(len(lineage_rows), 1))})",
        f"- With Stage 4 memory source text: `{with_memory}` ({_fmt_pct(with_memory, max(len(lineage_rows), 1))})",
        f"- With Stage 5 Meta-Ralph score evidence: `{with_meta}` ({_fmt_pct(with_meta, max(len(lineage_rows), 1))})",
        f"- EIDOS-sourced advisories with Stage 7 distillation match: `{with_dist}` / `{len(eidos_items)}` ({_fmt_pct(with_dist, max(len(eidos_items), 1))})",
        f"- With retrieval context: `{with_retrieval}` ({_fmt_pct(with_retrieval, max(len(lineage_rows), 1))})",
        f"- With decision/gate context: `{with_decision}` ({_fmt_pct(with_decision, max(len(lineage_rows), 1))})",
        f"- With outcome context: `{with_outcome}` ({_fmt_pct(with_outcome, max(len(lineage_rows), 1))})",
        "",
    ]
    if with_meta == 0:
        lines.append("- Stage 5 blind spot: no trace-bound Meta-Ralph roast linkage was found for this sample.")
    if with_outcome < max(5, len(lineage_rows) // 10):
        lines.append("- Stage 10 blind spot: limited outcome linkage for emitted traces in this sample window.")
    if with_meta == 0 or with_outcome < max(5, len(lineage_rows) // 10):
        lines.append("")

    lines.extend(
        [
            f"## Stage Chain Table (Latest {len(lineage_rows)})",
            "",
            "| emitted ts | trace | row type | tool | advice_id | source | insight key | stage1/2 observation | stage4 memory text (stored) | stage4 memory scores | stage5 meta-ralph | stage7 distillation | stage8 retrieval | stage8 decision/gate | stage9 emitted advisory | stage10 quality/outcome | evidence refs |",
            "|------------|-------|----------|------|-----------|--------|-------------|----------------------|-----------------------------|----------------------|-------------------|---------------------|------------------|----------------------|------------------------|-------------------------|---------------|",
        ]
    )

    for row in lineage_rows:
        memory_scores = (
            f"readiness={_norm_text(row.get('memory_readiness')) or '-'}; "
            f"unified={_norm_text(row.get('memory_unified')) or '-'}; "
            f"reliability={_norm_text(row.get('memory_reliability')) or '-'}; "
            f"val={_norm_text(row.get('memory_validated')) or '-'}; "
            f"contra={_norm_text(row.get('memory_contradicted')) or '-'}"
        )
        meta_scores = (
            f"{_norm_text(row.get('meta_verdict')) or '-'}; "
            f"total={_norm_text(row.get('meta_total')) or '-'}; "
            f"a={_norm_text(row.get('meta_actionability')) or '-'}; "
            f"r={_norm_text(row.get('meta_reasoning')) or '-'}; "
            f"s={_norm_text(row.get('meta_specificity')) or '-'}; "
            f"o={_norm_text(row.get('meta_outcome_linked')) or '-'}"
        )
        dist_scores = (
            f"id={_norm_text(row.get('dist_id')) or '-'}; "
            f"type={_norm_text(row.get('dist_type')) or '-'}; "
            f"conf={_norm_text(row.get('dist_conf')) or '-'}; "
            f"unified={_norm_text(row.get('dist_unified')) or '-'}; "
            f"statement={_short(_norm_text(row.get('dist_statement')), 130)}"
        )
        quality_outcome = (
            f"{_short(_norm_text(row.get('quality_context')), 190)}; "
            f"{_short(_norm_text(row.get('feedback_context')), 120)}; "
            f"{_short(_norm_text(row.get('implicit_context')), 100)}; "
            f"{_short(_norm_text(row.get('outcome_context')), 170)}"
        )
        capture_summary = _short(
            f"{_norm_text(row.get('capture_event'))}: {_norm_text(row.get('capture_text'))}",
            250,
        )
        lines.append(
            f"| {_fmt_ts(_to_float(row.get('emitted_ts'), 0.0))} | `{_short(_norm_text(row.get('trace_id')), 24) or '-'}` | "
            f"{'synthetic' if bool(row.get('synthetic')) else 'runtime'} | {_md_escape(row.get('tool'))} | `{_short(_norm_text(row.get('advice_id')), 24)}` | {_md_escape(row.get('source_hint'))} | "
            f"`{_short(_norm_text(row.get('insight_key')), 34) or '-'}` | {_md_escape(capture_summary)} | "
            f"{_md_escape(_short(_norm_text(row.get('memory_text')), 220))} | {_md_escape(_short(memory_scores, 170))} | "
            f"{_md_escape(_short(meta_scores, 170))} | {_md_escape(_short(dist_scores, 190))} | "
            f"{_md_escape(_short(_norm_text(row.get('retrieval_context')), 170))} | {_md_escape(_short(_norm_text(row.get('decision_context')), 170))} | "
            f"{_md_escape(_short(_norm_text(row.get('advice_text')), 220))} | {_md_escape(_short(quality_outcome, 220))} | "
            f"{_md_escape(_short(_norm_text(row.get('evidence_refs')), 180))} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Per-Item Dossiers (Latest 25)",
            "",
            "Use these when you need exact stage-by-stage context before tuning rules or thresholds.",
            "",
        ]
    )
    for idx, row in enumerate(lineage_rows[:25], start=1):
        lines.extend(
            [
                f"### {idx}. `{_norm_text(row.get('trace_id')) or '-'} :: {_norm_text(row.get('advice_id')) or '-'}",
                "",
                f"- Emitted: `{_fmt_ts(_to_float(row.get('emitted_ts'), 0.0))}` | row_type=`{'synthetic' if bool(row.get('synthetic')) else 'runtime'}` | tool=`{_norm_text(row.get('tool')) or '?'}` | source=`{_norm_text(row.get('source_hint')) or '?'}` | run_id=`{_norm_text(row.get('run_id')) or '-'}`",
                f"- Stage 1/2 observation: `{_norm_text(row.get('capture_event')) or '-'}` -> {_norm_text(row.get('capture_text')) or '-'}",
                f"- Stage 4 memory key: `{_norm_text(row.get('insight_key')) or '-'}` | source=`{_norm_text(row.get('memory_source')) or '-'}` | created=`{_norm_text(row.get('memory_created')) or '-'}`",
                f"- Stage 4 stored text: {_norm_text(row.get('memory_text')) or '-'}",
                f"- Stage 4 memory context: {_norm_text(row.get('memory_context')) or '-'}",
                f"- Stage 4 memory scores: readiness=`{_norm_text(row.get('memory_readiness')) or '-'}` unified=`{_norm_text(row.get('memory_unified')) or '-'}` reliability=`{_norm_text(row.get('memory_reliability')) or '-'}` validated=`{_norm_text(row.get('memory_validated')) or '-'}` contradicted=`{_norm_text(row.get('memory_contradicted')) or '-'}`",
                f"- Stage 5 Meta-Ralph: verdict=`{_norm_text(row.get('meta_verdict')) or '-'}` total=`{_norm_text(row.get('meta_total')) or '-'}` actionability=`{_norm_text(row.get('meta_actionability')) or '-'}` reasoning=`{_norm_text(row.get('meta_reasoning')) or '-'}` specificity=`{_norm_text(row.get('meta_specificity')) or '-'}` outcome_linked=`{_norm_text(row.get('meta_outcome_linked')) or '-'}` timestamp=`{_norm_text(row.get('meta_ts')) or '-'}`",
                f"- Stage 7 distillation: id=`{_norm_text(row.get('dist_id')) or '-'}` type=`{_norm_text(row.get('dist_type')) or '-'}` confidence=`{_norm_text(row.get('dist_conf')) or '-'}` unified=`{_norm_text(row.get('dist_unified')) or '-'}` created=`{_fmt_ts(_to_float(row.get('dist_created_ts'), 0.0))}`",
                f"- Stage 7 distillation statement: {_norm_text(row.get('dist_statement')) or '-'}",
                f"- Stage 8 retrieval: {_norm_text(row.get('retrieval_context')) or '-'}",
                f"- Stage 8 decision/gate: {_norm_text(row.get('decision_context')) or '-'}",
                f"- Stage 9 emitted advisory: {_norm_text(row.get('advice_text')) or '-'}",
                f"- Stage 10 quality/outcome: {_norm_text(row.get('quality_context')) or '-'}",
                f"- Stage 10 explicit feedback: {_norm_text(row.get('feedback_context')) or '-'}",
                f"- Stage 10 implicit feedback: {_norm_text(row.get('implicit_context')) or '-'}",
                f"- Stage 10 outcome stream: {_norm_text(row.get('outcome_context')) or '-'}",
                f"- Evidence refs: {_norm_text(row.get('evidence_refs')) or '-'}",
                "",
            ]
        )

    lines.extend(
        [
            "## Raw Evidence Bundles (Latest 12)",
            "",
            "Raw snippets for direct inspection of what each stage actually saw/stored/scored.",
            "",
        ]
    )
    for idx, row in enumerate(lineage_rows[:12], start=1):
        bundle = {
            "trace_id": _norm_text(row.get("trace_id")),
            "advice_id": _norm_text(row.get("advice_id")),
            "source_hint": _norm_text(row.get("source_hint")),
            "insight_key": _norm_text(row.get("insight_key")),
            "capture_row": row.get("capture_row") or {},
            "memory_row": row.get("memory_row") or {},
            "meta_row": row.get("meta_row") or {},
            "distillation_row": row.get("dist_row") or {},
            "retrieval_row": row.get("retrieval_row") or {},
            "decision_row": row.get("decision_row") or {},
            "quality_row": row.get("quality_row") or {},
            "feedback_row": row.get("feedback_row") or {},
            "implicit_row": row.get("implicit_row") or {},
            "outcome_row": row.get("outcome_row") or {},
        }
        lines.extend(
            [
                f"### {idx}. Raw `{_norm_text(row.get('trace_id')) or '-'} :: {_norm_text(row.get('advice_id')) or '-'}`",
                "",
                f"- Refs: {_norm_text(row.get('evidence_refs')) or '-'}",
                "",
                "```json",
                _json_preview(bundle, max_chars=7000),
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## Trace Drill",
            "",
            "For any row above, run:",
            "",
            "```bash",
            "python scripts/trace_query.py --trace-id <trace_id>",
            "```",
            "",
        ]
    )

    return "\n".join(lines)


def _trace_lineage_page(data: dict[int, dict[str, Any]]) -> str:
    observe_rows, _ = _read_jsonl(_SD / "logs" / "observe_hook_telemetry.jsonl", max_rows=25000)
    queue_rows, _ = _read_jsonl(_SD / "queue" / "events.jsonl", max_rows=25000)
    quality_rows, _ = _read_jsonl(_SD / "advisor" / "advisory_quality_events.jsonl", max_rows=25000)
    helpful_rows, _ = _read_jsonl(_SD / "advisor" / "helpfulness_events.jsonl", max_rows=25000)
    feedback_rows, _ = _read_jsonl(_SD / "advice_feedback.jsonl", max_rows=25000)
    decision_rows, decision_source, _ = _load_decision_rows(limit=25000)

    stage_sets: dict[str, set[str]] = {
        "event_capture": {_trace_from_row(r) for r in observe_rows if _trace_from_row(r)},
        "queue": {_trace_from_row(r) for r in queue_rows if _trace_from_row(r)},
        "advisory_engine": {_trace_from_row(r) for r in decision_rows if _trace_from_row(r)},
        "quality_spine": {_trace_from_row(r) for r in quality_rows if _trace_from_row(r)},
        "helpfulness": {_trace_from_row(r) for r in helpful_rows if _trace_from_row(r)},
        "explicit_feedback": {_trace_from_row(r) for r in feedback_rows if _trace_from_row(r)},
    }
    engine_set = stage_sets.get("advisory_engine", set())
    denom = float(max(len(engine_set), 1))

    trace_events: dict[str, list[tuple[float, str, str]]] = defaultdict(list)

    def _add_trace_events(rows: list[dict[str, Any]], stage: str, desc_fn) -> None:
        for row in rows:
            trace = _trace_from_row(row)
            if not trace:
                continue
            ts = _extract_ts(row)
            trace_events[trace].append((ts, stage, desc_fn(row)))

    _add_trace_events(
        observe_rows,
        "event_capture",
        lambda row: _norm_text(row.get("event") or row.get("hook_event") or row.get("kind") or "captured"),
    )
    _add_trace_events(
        queue_rows,
        "queue",
        lambda row: _norm_text(row.get("event_type") or row.get("kind") or row.get("tool_name") or "queued"),
    )
    _add_trace_events(
        decision_rows,
        "advisory_engine",
        lambda row: _norm_text(row.get("outcome") or row.get("event") or "decision"),
    )
    _add_trace_events(
        quality_rows,
        "quality_spine",
        lambda row: _norm_text(row.get("helpfulness_label") or row.get("timing_bucket") or "quality"),
    )
    _add_trace_events(
        helpful_rows,
        "helpfulness",
        lambda row: _norm_text(row.get("helpful_label") or "helpfulness"),
    )
    _add_trace_events(
        feedback_rows,
        "explicit_feedback",
        lambda row: _norm_text(row.get("status") or row.get("helpful") or "feedback"),
    )

    trace_rows = []
    for trace, events in trace_events.items():
        stage_names = {stage for _, stage, _ in events}
        latest_ts = max((ts for ts, _, _ in events), default=0.0)
        trace_rows.append((trace, len(stage_names), latest_ts))
    trace_rows.sort(key=lambda row: (row[1], row[2]), reverse=True)

    lines = [
        "---",
        "title: Advisory Trace Lineage",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - trace",
        "  - lineage",
        "---",
        "",
        "# Advisory Trace Lineage",
        "",
        f"> {flow_link()} | [[stages/08-advisory|Stage 8: Advisory]]",
        f"> Decision source used for lineage: `{decision_source}`",
        "",
        "## Stage Coverage Against Advisory Engine Traces",
        "",
        "| Stage | Traces Seen | Coverage vs Advisory Engine |",
        "|-------|-------------|-----------------------------|",
    ]
    for stage in (
        "event_capture",
        "queue",
        "advisory_engine",
        "quality_spine",
        "helpfulness",
        "explicit_feedback",
    ):
        traces = stage_sets.get(stage, set())
        overlap = len(traces & engine_set) if engine_set else 0
        lines.append(
            f"| {stage} | {fmt_num(len(traces))} | {_fmt_pct(overlap, denom)} ({overlap}/{max(len(engine_set), 1)}) |"
        )
    lines.append("")

    if trace_rows:
        lines.extend(
            [
                "## Cross-Stage Trace Samples",
                "",
                "| Trace ID | Stages Touched | Latest Event |",
                "|----------|----------------|--------------|",
            ]
        )
        for trace, stage_count, latest_ts in trace_rows[:15]:
            lines.append(f"| `{trace}` | {stage_count} | {_fmt_ts(latest_ts)} |")
        lines.append("")

        lines.append("## Sample Timelines")
        lines.append("")
        for trace, _, _ in trace_rows[:8]:
            lines.append(f"### `{trace}`")
            timeline = sorted(trace_events.get(trace, []), key=lambda row: row[0])
            if not timeline:
                lines.append("- no events")
                lines.append("")
                continue
            for ts, stage, desc in timeline[:12]:
                lines.append(f"- {_fmt_ts(ts)} | `{stage}` | {desc[:140]}")
            lines.append("")
    else:
        lines.extend(["## Cross-Stage Trace Samples", "", "- No trace-linked events found in current files.", ""])

    stage8 = (data.get(8) or {}) if isinstance(data.get(8), dict) else {}
    coverage = stage8.get("advisory_rating_coverage_summary") or {}
    if isinstance(coverage, dict) and coverage:
        lines.extend(
            [
                "## Prompted-to-Rated Linkage Snapshot",
                "",
                f"- Prompted advisory items: `{coverage.get('prompted_total', 0)}`",
                f"- Explicitly rated: `{coverage.get('explicit_rated_total', 0)}` ({coverage.get('explicit_rate_pct', 0.0)}%)",
                f"- Known helpfulness: `{coverage.get('known_helpful_total', 0)}` ({coverage.get('known_helpful_rate_pct', 0.0)}%)",
                "",
            ]
        )
    return "\n".join(lines)


def _unknown_helpfulness_page(data: dict[int, dict[str, Any]]) -> str:
    summary = _read_json(_SD / "advisor" / "helpfulness_summary.json")
    events, _ = _read_jsonl(_SD / "advisor" / "helpfulness_events.jsonl", max_rows=40000)
    queue_rows, _ = _read_jsonl(_SD / "advisor" / "helpfulness_llm_queue.jsonl", max_rows=5000)
    review_rows, _ = _read_jsonl(_SD / "advisor" / "helpfulness_llm_reviews.jsonl", max_rows=15000)

    by_day: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "total": 0,
            "unknown": 0,
            "known": 0,
            "helpful": 0,
            "queued": 0,
            "llm_applied": 0,
        }
    )
    unknown_tools: Counter[str] = Counter()
    for row in events:
        ts = _extract_ts(row, ("request_ts", "resolved_at", "ts", "created_at"))
        if ts <= 0:
            continue
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        bucket = by_day[day]
        bucket["total"] += 1
        label = _norm_text(row.get("helpful_label")).lower()
        if label in _KNOWN_LABELS:
            bucket["known"] += 1
            if label == "helpful":
                bucket["helpful"] += 1
        else:
            bucket["unknown"] += 1
            unknown_tools[_norm_text(row.get("tool")) or "unknown"] += 1
        if bool(row.get("llm_review_required")):
            bucket["queued"] += 1
        if bool(row.get("llm_review_applied")):
            bucket["llm_applied"] += 1

    review_latest: dict[str, dict[str, Any]] = {}
    for row in review_rows:
        event_id = _norm_text(row.get("event_id"))
        if not event_id:
            continue
        prev = review_latest.get(event_id)
        if prev is None or _extract_ts(row, ("reviewed_at", "ts")) >= _extract_ts(prev, ("reviewed_at", "ts")):
            review_latest[event_id] = row
    queue_ids = {_norm_text(r.get("event_id")) for r in queue_rows if _norm_text(r.get("event_id"))}
    unresolved = 0
    for event_id in queue_ids:
        status = _norm_text((review_latest.get(event_id) or {}).get("status")).lower()
        if status not in {"ok", "abstain"}:
            unresolved += 1

    days = sorted(by_day.keys())[-14:]
    first_unknown = None
    last_unknown = None
    for day in days:
        row = by_day[day]
        if row["total"] <= 0:
            continue
        rate = round((100.0 * row["unknown"]) / max(row["total"], 1), 1)
        if first_unknown is None:
            first_unknown = rate
        last_unknown = rate
    delta = 0.0
    if first_unknown is not None and last_unknown is not None:
        delta = round(last_unknown - first_unknown, 1)

    lines = [
        "---",
        "title: Advisory Unknown Helpfulness Burn-Down",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - helpfulness",
        "  - burndown",
        "---",
        "",
        "# Advisory Unknown Helpfulness Burn-Down",
        "",
        f"> {flow_link()} | [[stages/08-advisory|Stage 8: Advisory]] | [[explore/helpfulness/_index|Helpfulness Explorer]]",
        "",
        "## Current Window Scoreboard",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Events in stream file | {fmt_num(len(events))} |",
        f"| Summary total events | {fmt_num(summary.get('total_events', len(events)))} |",
        f"| Known helpfulness events | {fmt_num(summary.get('known_helpfulness_total', 0))} |",
        f"| Unknown rate | {summary.get('unknown_rate_pct', 0.0)}% |",
        f"| Helpful rate (known) | {summary.get('helpful_rate_pct', 0.0)}% |",
        f"| LLM review queue count | {fmt_num(summary.get('llm_review_queue_count', len(queue_rows)))} |",
        f"| LLM unresolved queue items | {fmt_num(unresolved)} |",
        "",
        "## 14-Day Burn-Down Trend",
        "",
        "| Day | Events | Known | Unknown | Unknown Rate | Helpful (known) | Helpful Rate | Queued | LLM Applied |",
        "|-----|--------|-------|---------|--------------|-----------------|--------------|--------|-------------|",
    ]
    for day in days:
        row = by_day[day]
        unknown_rate = round((100.0 * row["unknown"]) / max(row["total"], 1), 1) if row["total"] > 0 else 0.0
        helpful_rate = round((100.0 * row["helpful"]) / max(row["known"], 1), 1) if row["known"] > 0 else 0.0
        lines.append(
            f"| {day} | {row['total']} | {row['known']} | {row['unknown']} | {unknown_rate}% | "
            f"{row['helpful']} | {helpful_rate}% | {row['queued']} | {row['llm_applied']} |"
        )
    lines.extend(
        [
            "",
            "## Burn-Down Status",
            "",
            f"- Unknown-rate delta across visible window: `{delta:+.1f}%` (negative is improving).",
            "- Goal: unknown rate should trend down while known-helpful rate remains stable or improves.",
            "",
        ]
    )
    if unknown_tools:
        lines.extend(
            [
                "## Top Tools Feeding Unknown Labels",
                "",
                "| Tool | Unknown Labels |",
                "|------|----------------|",
            ]
        )
        for tool, count in unknown_tools.most_common(8):
            lines.append(f"| {tool} | {count} |")
        lines.append("")

    stage8 = (data.get(8) or {}) if isinstance(data.get(8), dict) else {}
    quality_summary = stage8.get("advisory_quality_summary") or {}
    if isinstance(quality_summary, dict) and quality_summary:
        lines.extend(
            [
                "## Emission Quality Cross-Check",
                "",
                f"- Quality spine events: `{quality_summary.get('total_events', 0)}`",
                f"- Avg impact score: `{quality_summary.get('avg_impact_score', 0.0)}`",
                f"- Right-on-time rate: `{quality_summary.get('right_on_time_rate_pct', 0.0)}%`",
                "",
            ]
        )
    return "\n".join(lines)


def _suppression_replay_page() -> str:
    rows, source, source_path = _load_decision_rows(limit=16000)
    blocked_rows = []
    reason_counter: Counter[str] = Counter()
    bucket_counter: Counter[str] = Counter()
    for row in rows:
        outcome = _norm_text(row.get("outcome")).lower()
        if outcome == "emitted":
            continue
        if not outcome:
            event = _norm_text(row.get("event")).lower()
            if event in _BLOCKING_EVENTS:
                outcome = "blocked"
        if outcome not in {"blocked", "suppressed"}:
            continue
        reasons = _extract_suppression_reasons(row)
        if not reasons:
            reasons = [_norm_text(row.get("event")) or "unknown"]
        for reason in reasons:
            reason_counter[reason] += 1
            bucket_counter[_classify_reason(reason)] += 1
        rec = dict(row)
        rec["_reasons"] = reasons
        blocked_rows.append(rec)

    blocked_rows.sort(key=_extract_ts, reverse=True)
    high_potential = []
    for row in blocked_rows:
        selected_count = int(row.get("selected_count") or 0)
        source_counts = row.get("source_counts")
        source_total = 0
        if isinstance(source_counts, dict):
            for value in source_counts.values():
                try:
                    source_total += int(value or 0)
                except Exception:
                    continue
        if selected_count > 0 or source_total > 0:
            high_potential.append((row, selected_count, source_total))

    lines = [
        "---",
        "title: Advisory Suppression Decision Replay",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - suppression",
        "  - replay",
        "---",
        "",
        "# Advisory Suppression Decision Replay",
        "",
        f"> {flow_link()} | [[stages/08-advisory|Stage 8: Advisory]] | [[explore/decisions/_index|Decision Explorer]]",
        f"> Decision source: `{source}` (`{source_path}`)",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total decision rows analyzed | {fmt_num(len(rows))} |",
        f"| Blocked/suppressed rows | {fmt_num(len(blocked_rows))} |",
        f"| High-potential blocked rows | {fmt_num(len(high_potential))} |",
        "",
    ]
    if bucket_counter:
        lines.extend(
            [
                "## Suppression Buckets",
                "",
                "| Bucket | Count | Share of blocked |",
                "|--------|-------|------------------|",
            ]
        )
        denom = float(max(len(blocked_rows), 1))
        for bucket, count in bucket_counter.most_common(10):
            lines.append(f"| {bucket} | {count} | {_fmt_pct(count, denom)} |")
        lines.append("")

    if reason_counter:
        lines.extend(
            [
                "## Top Raw Suppression Reasons",
                "",
                "| Reason | Count |",
                "|--------|-------|",
            ]
        )
        for reason, count in reason_counter.most_common(15):
            lines.append(f"| {reason[:120]} | {count} |")
        lines.append("")

    if high_potential:
        lines.extend(
            [
                "## High-Potential Blocked Samples",
                "",
                "| Time | Tool | Route | Selected | Retrieved Sources | Trace | Reasons |",
                "|------|------|-------|----------|------------------|-------|---------|",
            ]
        )
        for row, selected_count, source_total in high_potential[:20]:
            ts = _fmt_ts(_extract_ts(row))
            tool = _norm_text(row.get("tool") or row.get("tool_name") or "?")
            route = _norm_text(row.get("route") or row.get("delivery_route") or "?")
            trace = _trace_from_row(row) or "?"
            reasons = "; ".join(row.get("_reasons", [])[:2])
            lines.append(
                f"| {ts} | {tool} | `{route}` | {selected_count} | {source_total} | `{trace}` | {reasons[:120]} |"
            )
        lines.append("")
    else:
        lines.extend(["## High-Potential Blocked Samples", "", "- none in current window", ""])

    lines.extend(
        [
            "## Replay Drill",
            "",
            "Use this command on traces above to inspect end-to-end timeline:",
            "",
            "```bash",
            "python scripts/trace_query.py --trace-id <trace_id>",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _context_drift_page() -> str:
    decision_rows, source, _ = _load_decision_rows(limit=22000)
    quality_rows, _ = _read_jsonl(_SD / "advisor" / "advisory_quality_events.jsonl", max_rows=22000)

    prev_dec, curr_dec = _split_windows(decision_rows)
    prev_q, curr_q = _split_windows(quality_rows)

    dimensions: list[tuple[str, Counter[str], Counter[str], int, int]] = []

    def _counter(rows: list[dict[str, Any]], key_fn) -> Counter[str]:
        out: Counter[str] = Counter()
        for row in rows:
            key = key_fn(row)
            if key:
                out[key] += 1
        return out

    dimensions.append(
        (
            "decision_tool",
            _counter(prev_dec, lambda r: _norm_text(r.get("tool") or r.get("tool_name") or "unknown")),
            _counter(curr_dec, lambda r: _norm_text(r.get("tool") or r.get("tool_name") or "unknown")),
            len(prev_dec),
            len(curr_dec),
        )
    )
    dimensions.append(
        (
            "decision_route",
            _counter(prev_dec, lambda r: _norm_text(r.get("route") or r.get("delivery_route") or "unknown")),
            _counter(curr_dec, lambda r: _norm_text(r.get("route") or r.get("delivery_route") or "unknown")),
            len(prev_dec),
            len(curr_dec),
        )
    )
    dimensions.append(
        (
            "quality_provider",
            _counter(prev_q, lambda r: _norm_text(r.get("provider") or "unknown")),
            _counter(curr_q, lambda r: _norm_text(r.get("provider") or "unknown")),
            len(prev_q),
            len(curr_q),
        )
    )
    dimensions.append(
        (
            "quality_phase",
            _counter(prev_q, lambda r: _norm_text(r.get("task_phase") or "unknown").lower()),
            _counter(curr_q, lambda r: _norm_text(r.get("task_phase") or "unknown").lower()),
            len(prev_q),
            len(curr_q),
        )
    )
    dimensions.append(
        (
            "suppression_bucket",
            _counter(
                [r for r in prev_dec if _norm_text(r.get("outcome")).lower() != "emitted"],
                lambda r: _classify_reason((_extract_suppression_reasons(r) or ["other"])[0]),
            ),
            _counter(
                [r for r in curr_dec if _norm_text(r.get("outcome")).lower() != "emitted"],
                lambda r: _classify_reason((_extract_suppression_reasons(r) or ["other"])[0]),
            ),
            len([r for r in prev_dec if _norm_text(r.get("outcome")).lower() != "emitted"]),
            len([r for r in curr_dec if _norm_text(r.get("outcome")).lower() != "emitted"]),
        )
    )

    lines = [
        "---",
        "title: Advisory Context Drift Panel",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - drift",
        "  - context",
        "---",
        "",
        "# Advisory Context Drift Panel",
        "",
        f"> {flow_link()} | [[stages/08-advisory|Stage 8: Advisory]]",
        f"> Decision source for drift inputs: `{source}`",
        "",
        "## Drift Scores (Previous vs Current Window)",
        "",
        "| Dimension | Previous Rows | Current Rows | Drift Score | Top Movers |",
        "|-----------|---------------|--------------|-------------|------------|",
    ]
    for name, prev_ctr, curr_ctr, prev_n, curr_n in dimensions:
        score, movers = _drift_score(prev_ctr, curr_ctr)
        mover_parts = []
        for label, prev_p, curr_p, _ in movers[:3]:
            mover_parts.append(f"{label}:{prev_p*100:.1f}%->{curr_p*100:.1f}%")
        lines.append(
            f"| {name} | {prev_n} | {curr_n} | {score}% | {'; '.join(mover_parts) if mover_parts else '-'} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Interpretation",
            "",
            "- Drift > 25% usually indicates changed user/tool mix, provider routing, or suppression policy behavior.",
            "- Pair this panel with suppression replay to verify whether drift is beneficial or regressive.",
            "",
        ]
    )
    return "\n".join(lines)


def _latest_external_review_status() -> dict[str, Any]:
    reports_dir = _REPO_ROOT / "reports"
    if not reports_dir.exists():
        return {}
    candidates = sorted(
        reports_dir.glob("*_advisory_context_external_review.json"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    if not candidates:
        return {}
    path = candidates[0]
    payload = _read_json(path)
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    inconsistent = 0
    provider_errors = 0
    for row in results:
        if not isinstance(row, dict):
            continue
        response = _norm_text(row.get("response")).lower()
        ok = bool(row.get("ok"))
        if "execution error" in response:
            provider_errors += 1
            if ok:
                inconsistent += 1
    return {
        "path": str(path),
        "results": len(results),
        "provider_errors": provider_errors,
        "inconsistent_ok_flags": inconsistent,
    }


def _data_integrity_page(data: dict[int, dict[str, Any]]) -> str:
    decision_rows, decision_source, decision_path = _load_decision_rows(limit=20000)
    external_review = _latest_external_review_status()

    specs = [
        ("observe_hook_telemetry", _SD / "logs" / "observe_hook_telemetry.jsonl", True),
        ("queue_events", _SD / "queue" / "events.jsonl", True),
        ("advisory_engine_alpha", _SD / "advisory_engine_alpha.jsonl", True),
        ("advisory_decision_ledger", _SD / "advisory_decision_ledger.jsonl", False),
        ("advisory_emit", _SD / "advisory_emit.jsonl", False),
        ("advisory_quality_events", _SD / "advisor" / "advisory_quality_events.jsonl", True),
        ("helpfulness_events", _SD / "advisor" / "helpfulness_events.jsonl", True),
        ("advice_feedback_requests", _SD / "advice_feedback_requests.jsonl", True),
        ("advice_feedback", _SD / "advice_feedback.jsonl", True),
    ]

    lines = [
        "---",
        "title: Advisory Data Quality Integrity",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - integrity",
        "  - data-quality",
        "---",
        "",
        "# Advisory Data Quality Integrity",
        "",
        f"> {flow_link()} | [[stages/08-advisory|Stage 8: Advisory]]",
        "",
        "## File Integrity Matrix",
        "",
        "| Source | Exists | Parsed Rows (windowed) | Invalid Lines | Trace Coverage | Newest Timestamp | Freshness |",
        "|--------|--------|-----------------------|---------------|----------------|------------------|-----------|",
    ]
    now = time.time()
    blind_spots: list[str] = []
    for name, path, required in specs:
        rows, stats = _read_jsonl(path, max_rows=22000)
        exists = path.exists()
        newest_ts = max((_extract_ts(r) for r in rows), default=0.0)
        freshness_s = int(max(0.0, now - newest_ts)) if newest_ts > 0 else -1
        trace_rows = 0
        trace_field_rows = 0
        for row in rows:
            if any(k in row for k in ("trace_id", "outcome_trace_id", "trace")):
                trace_field_rows += 1
            if _trace_from_row(row):
                trace_rows += 1
        trace_pct = _fmt_pct(trace_rows, max(trace_field_rows, 1)) if trace_field_rows > 0 else "n/a"
        freshness_label = f"{freshness_s}s" if freshness_s >= 0 else "unknown"
        trace_cov_label = (
            f"{trace_pct} ({trace_rows}/{max(trace_field_rows, 1)})"
            if trace_field_rows > 0
            else "n/a"
        )
        lines.append(
            f"| {name} | {'yes' if exists else 'no'} | {fmt_num(len(rows))} | "
            f"{fmt_num(stats.get('invalid_lines', 0))} | {trace_cov_label} | "
            f"{_fmt_ts(newest_ts)} | {freshness_label} |"
        )
        if required and not exists:
            blind_spots.append(f"{name} missing")
        if stats.get("invalid_lines", 0) > 0:
            blind_spots.append(f"{name} has invalid jsonl lines")
        if trace_field_rows > 0 and (trace_rows / max(trace_field_rows, 1)) < 0.5:
            blind_spots.append(f"{name} trace coverage below 50%")
    lines.append("")

    lines.extend(
        [
            "## Decision Source Integrity",
            "",
            f"- Active decision source: `{decision_source}`",
            f"- Active decision path: `{decision_path}`",
            f"- Decision rows available: `{len(decision_rows)}`",
            "",
        ]
    )
    if decision_source != "advisory_decision_ledger":
        blind_spots.append("decision ledger missing; using fallback source")
        lines.append(
            "- Warning: decision ledger missing; observatory is using fallback source and should show lower confidence."
        )
        lines.append("")

    stage8 = (data.get(8) or {}) if isinstance(data.get(8), dict) else {}
    coverage_summary = stage8.get("advisory_rating_coverage_summary") or {}
    if isinstance(coverage_summary, dict) and coverage_summary:
        lines.extend(
            [
                "## Prompted-to-Rating Coverage Integrity",
                "",
                f"- Prompted total: `{coverage_summary.get('prompted_total', 0)}`",
                f"- Explicitly rated: `{coverage_summary.get('explicit_rated_total', 0)}`",
                f"- Known helpfulness: `{coverage_summary.get('known_helpful_total', 0)}`",
                f"- Explicit coverage gap: `{coverage_summary.get('explicit_gap', 0)}`",
                f"- Known-helpful gap: `{coverage_summary.get('known_helpful_gap', 0)}`",
                "",
            ]
        )
        if float(coverage_summary.get("known_helpful_rate_pct", 0.0) or 0.0) < 40.0:
            blind_spots.append("known helpfulness coverage below 40%")

    if external_review:
        lines.extend(
            [
                "## External Review Runtime Integrity",
                "",
                f"- Latest external review file: `{external_review.get('path')}`",
                f"- Provider result rows: `{external_review.get('results', 0)}`",
                f"- Provider execution-error rows: `{external_review.get('provider_errors', 0)}`",
                f"- Inconsistent ok=true with execution-error text: `{external_review.get('inconsistent_ok_flags', 0)}`",
                "",
            ]
        )
        if int(external_review.get("inconsistent_ok_flags", 0) or 0) > 0:
            blind_spots.append("external review result status inconsistent with error response")

    lines.append("## Context Blind Spots")
    lines.append("")
    if blind_spots:
        for item in sorted(set(blind_spots)):
            lines.append(f"- {item}")
    else:
        lines.append("- none detected from current integrity checks")
    lines.append("")
    return "\n".join(lines)


def _retrieval_route_forensics_page(detail_rows: int = 450) -> str:
    route_path = _SD / "advisor" / "retrieval_router.jsonl"
    semantic_path = _SD / "logs" / "semantic_retrieval.jsonl"
    route_rows, route_stats = _read_jsonl(route_path, max_rows=50000)
    semantic_rows, semantic_stats = _read_jsonl(semantic_path, max_rows=50000)

    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return int(default)

    def _semantic_empty_bucket(row: dict[str, Any]) -> str:
        candidates = _safe_int(row.get("semantic_candidates_count"), 0)
        final_results = row.get("final_results")
        final_count = len(final_results) if isinstance(final_results, list) else 0
        if final_count > 0:
            return "non_empty"
        if bool(row.get("embedding_available")) and candidates <= 0:
            return "embed_enabled_no_candidates"
        if (not bool(row.get("embedding_available"))) and candidates <= 0:
            return "no_embeddings_no_keyword_overlap"
        if candidates > 0 and final_count <= 0:
            return "gated_or_filtered_after_candidates"
        return "other_empty"

    route_reason_counter: Counter[tuple[str, str]] = Counter()
    tool_route_counter: Counter[tuple[str, str]] = Counter()
    empty_tool_counter: Counter[str] = Counter()
    total_tool_counter: Counter[str] = Counter()

    for row in route_rows:
        route = _norm_text(row.get("route") or "unknown").lower() or "unknown"
        reason = _norm_text(row.get("reason"))
        if not reason:
            reasons = row.get("reasons")
            if isinstance(reasons, list) and reasons:
                reason = _norm_text(reasons[0])
        if not reason:
            reason = "unknown"
        tool = _norm_text(row.get("tool") or row.get("tool_name") or "?")
        route_reason_counter[(route, reason)] += 1
        tool_route_counter[(tool, route)] += 1
        total_tool_counter[tool] += 1
        if route == "empty":
            empty_tool_counter[tool] += 1

    lines = [
        "---",
        "title: Retrieval Route Forensics",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - retrieval",
        "  - forensics",
        "  - context-first",
        "---",
        "",
        "# Retrieval Route Forensics (Context First)",
        "",
        f"> {flow_link()} | [[stages/08-advisory|Stage 8: Advisory]]",
        "",
        "## Data Scope",
        "",
        f"- Retrieval route source: `{route_path}`",
        f"- Retrieval route rows parsed: `{len(route_rows)}`",
        f"- Retrieval route invalid lines: `{route_stats.get('invalid_lines', 0)}`",
        f"- Semantic retrieval source: `{semantic_path}`",
        f"- Semantic retrieval rows parsed: `{len(semantic_rows)}`",
        f"- Semantic retrieval invalid lines: `{semantic_stats.get('invalid_lines', 0)}`",
        "",
        "## Route x Reason Distribution (Top 40)",
        "",
        "| Route | Reason | Count | Share |",
        "|-------|--------|-------|-------|",
    ]
    route_total = max(1, len(route_rows))
    for (route, reason), count in route_reason_counter.most_common(40):
        lines.append(f"| {route} | {reason} | {fmt_num(count)} | {_fmt_pct(count, route_total)} |")
    lines.append("")

    lines.extend(
        [
            "## Tool x Route Matrix (Top 30 Tools)",
            "",
            "| Tool | Total | Empty | Empty Rate | Top Routes |",
            "|------|-------|-------|------------|------------|",
        ]
    )
    for tool, total in total_tool_counter.most_common(30):
        empty_count = empty_tool_counter.get(tool, 0)
        top_routes = sorted(
            [(route, cnt) for (tool_name, route), cnt in tool_route_counter.items() if tool_name == tool],
            key=lambda item: item[1],
            reverse=True,
        )[:3]
        top_routes_text = "; ".join(f"{route}:{cnt}" for route, cnt in top_routes) if top_routes else "-"
        lines.append(
            f"| {tool} | {fmt_num(total)} | {fmt_num(empty_count)} | {_fmt_pct(empty_count, max(1, total))} | {top_routes_text} |"
        )
    lines.append("")

    ordered_route_rows = sorted(route_rows, key=_extract_ts, reverse=True)
    detailed = ordered_route_rows[: max(100, int(detail_rows))]
    lines.extend(
        [
            f"## Detailed Retrieval Rows (Latest {len(detailed)})",
            "",
            "| ts | tool | route | reason | complexity | active_insights | primary | returned | over_budget | route_ms | reasons | trace |",
            "|----|------|-------|--------|------------|-----------------|---------|----------|-------------|----------|---------|-------|",
        ]
    )
    for row in detailed:
        ts = _fmt_ts(_extract_ts(row))
        tool = _norm_text(row.get("tool") or row.get("tool_name") or "?")
        route = _norm_text(row.get("route") or "unknown").lower() or "unknown"
        reason = _norm_text(row.get("reason"))
        reasons = row.get("reasons")
        reasons_txt = ""
        if isinstance(reasons, list):
            reasons_txt = ", ".join(_norm_text(x) for x in reasons if _norm_text(x))[:140]
        if not reason:
            reason = _norm_text(reasons_txt.split(",")[0]) if reasons_txt else "unknown"
        complexity = _safe_int(row.get("complexity_score"), 0)
        active_insights = _safe_int(row.get("active_insights"), 0)
        primary = _safe_int(row.get("primary_count"), 0)
        returned = _safe_int(row.get("returned_count"), 0)
        over_budget = "yes" if bool(row.get("fast_path_over_budget")) else "no"
        route_ms = _safe_int(row.get("route_elapsed_ms"), 0)
        trace = _norm_text(row.get("trace_id"))[:24] or "-"
        lines.append(
            f"| {ts} | {tool} | {route} | {reason} | {complexity} | {active_insights} | "
            f"{primary} | {returned} | {over_budget} | {route_ms} | {reasons_txt or '-'} | {trace} |"
        )
    lines.append("")

    ordered_semantic = sorted(semantic_rows, key=_extract_ts, reverse=True)
    sem_detail = ordered_semantic[:350]
    lines.extend(
        [
            f"## Semantic Retrieval Diagnostics (Latest {len(sem_detail)})",
            "",
            "| ts | empty_bucket | embedding | candidates | raw | post_noise | post_similarity | post_fusion | rescue_used | elapsed_ms | intent_preview |",
            "|----|--------------|-----------|------------|-----|------------|-----------------|-------------|-------------|------------|----------------|",
        ]
    )
    for row in sem_detail:
        ts = _fmt_ts(_extract_ts(row))
        bucket = _semantic_empty_bucket(row)
        embedding = "yes" if bool(row.get("embedding_available")) else "no"
        candidates = _safe_int(row.get("semantic_candidates_count"), 0)
        raw_count = _safe_int(row.get("raw_result_count"), 0)
        post_noise = _safe_int(row.get("post_noise_count"), 0)
        post_similarity = _safe_int(row.get("post_similarity_count"), 0)
        post_fusion = _safe_int(row.get("post_fusion_count"), 0)
        rescue_used = "yes" if bool(row.get("rescue_used")) else "no"
        elapsed_ms = _safe_int(row.get("elapsed_ms"), 0)
        intent = _norm_text(row.get("intent"))[:120].replace("|", "\\|")
        lines.append(
            f"| {ts} | {bucket} | {embedding} | {candidates} | {raw_count} | {post_noise} | "
            f"{post_similarity} | {post_fusion} | {rescue_used} | {elapsed_ms} | {intent or '-'} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Hard Questions For Next Cycle",
            "",
            "- Which `empty_primary` rows had `active_insights > 10` but still returned zero candidates, and why?",
            "- Are generic rewrite intents (for example: `failure pattern and fix`) replacing high-signal context in retrieval queries?",
            "- For each high-empty tool, what % of rows are `embedding_available=false` vs `embed_enabled_no_candidates`?",
            "- Which suppression/threshold settings are discarding candidates after semantic retrieval (`gated_or_filtered_after_candidates` bucket)?",
            "- Which repeated traces are stuck in empty retrieval loops across multiple tools?",
            "",
        ]
    )
    return "\n".join(lines)


def _advisory_content_quality_forensics_page(detail_rows: int = 520) -> str:
    report = build_production_noise_report(
        spark_dir=_SD,
        max_rows_per_source=1600,
        detail_rows=max(120, int(detail_rows)),
    )

    detail = report.get("detailed_rows") if isinstance(report.get("detailed_rows"), list) else []
    false_neg = (
        report.get("false_negative_examples")
        if isinstance(report.get("false_negative_examples"), list)
        else []
    )
    false_pos = (
        report.get("false_positive_examples")
        if isinstance(report.get("false_positive_examples"), list)
        else []
    )
    signature_counts = (
        report.get("hard_noise_signature_counts")
        if isinstance(report.get("hard_noise_signature_counts"), dict)
        else {}
    )
    rule_counts = (
        report.get("classifier_rule_counts")
        if isinstance(report.get("classifier_rule_counts"), dict)
        else {}
    )

    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0

    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except Exception:
            return 0.0

    recall = _safe_float(report.get("recall"))
    fp_rate = _safe_float(report.get("false_positive_rate"))
    lines = [
        "---",
        "title: Advisory Content Quality Forensics",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - content-quality",
        "  - noise-regression",
        "  - context-first",
        "---",
        "",
        "# Advisory Content Quality Forensics",
        "",
        f"> {flow_link()} | [[stages/08-advisory|Stage 8: Advisory]]",
        "",
        "## Summary",
        "",
        f"- Rows analyzed: `{_safe_int(report.get('rows_analyzed'))}`",
        f"- Rows by source: `{report.get('rows_by_source')}`",
        f"- Expected hard-noise rows: `{_safe_int(report.get('expected_noise_rows'))}`",
        f"- Expected signal rows: `{_safe_int(report.get('expected_signal_rows'))}`",
        f"- Classifier recall on hard-noise signatures: `{recall * 100.0:.1f}%`",
        f"- Signal false-positive rate: `{fp_rate * 100.0:.1f}%`",
        "",
        "## Hard Noise Signatures",
        "",
        "| Signature | Count |",
        "|-----------|------:|",
    ]
    if signature_counts:
        for key, value in sorted(signature_counts.items(), key=lambda item: int(item[1]), reverse=True):
            lines.append(f"| {key} | {_safe_int(value)} |")
    else:
        lines.append("| _none_ | 0 |")
    lines.append("")

    lines.extend(
        [
            "## Classifier Rule Distribution (Top 20)",
            "",
            "| Rule | Count |",
            "|------|------:|",
        ]
    )
    if rule_counts:
        for key, value in sorted(rule_counts.items(), key=lambda item: int(item[1]), reverse=True)[:20]:
            lines.append(f"| {key} | {_safe_int(value)} |")
    else:
        lines.append("| _none_ | 0 |")
    lines.append("")

    lines.extend(
        [
            f"## False Negative Examples (Latest {min(120, len(false_neg))})",
            "",
            "| source | id | classifier_rule | hard_reason | snippet |",
            "|--------|----|-----------------|-------------|---------|",
        ]
    )
    if false_neg:
        for row in false_neg[:120]:
            snippet = _norm_text(row.get("snippet")).replace("|", "\\|")
            lines.append(
                f"| {_norm_text(row.get('source')) or '?'} | {_norm_text(row.get('id')) or '?'} | "
                f"{_norm_text(row.get('classifier_rule')) or 'none'} | "
                f"{_norm_text(row.get('hard_noise_reason')) or '-'} | {snippet or '-'} |"
            )
    else:
        lines.append("| _none_ | - | - | - | - |")
    lines.append("")

    lines.extend(
        [
            f"## False Positive Examples (Latest {min(120, len(false_pos))})",
            "",
            "| source | id | classifier_rule | expected_signal | snippet |",
            "|--------|----|-----------------|-----------------|---------|",
        ]
    )
    if false_pos:
        for row in false_pos[:120]:
            snippet = _norm_text(row.get("snippet")).replace("|", "\\|")
            lines.append(
                f"| {_norm_text(row.get('source')) or '?'} | {_norm_text(row.get('id')) or '?'} | "
                f"{_norm_text(row.get('classifier_rule')) or 'none'} | "
                f"{'yes' if bool(row.get('expected_signal')) else 'no'} | {snippet or '-'} |"
            )
    else:
        lines.append("| _none_ | - | - | - | - |")
    lines.append("")

    lines.extend(
        [
            f"## Detailed Content Rows (Latest {len(detail)})",
            "",
            "| source | id | classifier | rule | hard_noise | hard_reason | expected_signal | snippet |",
            "|--------|----|------------|------|------------|-------------|-----------------|---------|",
        ]
    )
    for row in detail:
        snippet = _norm_text(row.get("snippet")).replace("|", "\\|")
        lines.append(
            f"| {_norm_text(row.get('source')) or '?'} | {_norm_text(row.get('id')) or '?'} | "
            f"{'noise' if bool(row.get('classifier_is_noise')) else 'signal'} | "
            f"{_norm_text(row.get('classifier_rule')) or 'none'} | "
            f"{'yes' if bool(row.get('hard_noise')) else 'no'} | "
            f"{_norm_text(row.get('hard_noise_reason')) or '-'} | "
            f"{'yes' if bool(row.get('expected_signal')) else 'no'} | {snippet or '-'} |"
        )
    lines.append("")
    lines.extend(
        [
            "## Hard Questions For Next Cycle",
            "",
            "- Which false-negative signatures are still entering promotion and CLAUDE contexts?",
            "- Are false positives suppressing reusable architecture guidance we actually want to keep?",
            "- Which source contributes the highest share of hard-noise misses, and what upstream gate should own it?",
            "- How many hard-noise misses also appear in emitted advisories in the same window?",
            "",
        ]
    )
    return "\n".join(lines)


def _iter_cognitive_items(limit: int = 220) -> list[dict[str, Any]]:
    payload = _read_json(_SD / "cognitive_insights.json")
    rows: list[dict[str, Any]] = []
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        row = dict(value)
        row["insight_key"] = key
        row["trace_id"] = _norm_text(row.get("trace_id"))
        row["_ts"] = _extract_ts(
            row,
            keys=("created_at", "updated_at", "last_validated_at", "ts", "timestamp"),
        )
        rows.append(row)
    rows.sort(key=lambda r: float(r.get("_ts") or 0.0), reverse=True)
    return rows[: max(120, int(limit))]


def _keepability_gate_page() -> str:
    memory_rows = _iter_cognitive_items(limit=240)
    emission_rows, _ = _read_jsonl(_SD / "advisory_emit.jsonl", max_rows=3500)
    quality_rows, _ = _read_jsonl(_SD / "advisor" / "advisory_quality_events.jsonl", max_rows=3500)

    emission_rows = sorted(emission_rows, key=_extract_ts, reverse=True)[:140]
    quality_rows = sorted(quality_rows, key=_extract_ts, reverse=True)[:160]

    lines = [
        "---",
        "title: Keepability Gate Review",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - memory",
        "  - keepability",
        "  - context-first",
        "---",
        "",
        "# Keepability Gate Review",
        "",
        f"> {flow_link()} | [[stages/06-cognitive_learner|Stage 6]] | [[stages/08-advisory|Stage 8]]",
        "",
        "This page is context-first and item-first. It does not start with headline rates.",
        "Each row is judged by the same keepability dimensions before rules or thresholds are changed.",
        "",
        "## Keepability Dimensions",
        "",
        "| Dimension | What we ask |",
        "|-----------|-------------|",
        "| actionability | Does this text instruct a concrete next step? |",
        "| context-fit | Is it grounded in the current tool/task context rather than generic residue? |",
        "| causal confidence | Is there meaningful evidence that it influenced outcomes? |",
        "| transfer score | Will this still help in future sessions and adjacent tasks? |",
        "| expiry/decay policy | Should this persist, be rewritten, or decay quickly? |",
        "",
        f"## Memory Cohort (Latest {len(memory_rows)})",
        "",
        "| ts | source | key | snippet | actionability | context-fit | causal | transfer | decay | verdict | rationale |",
        "|----|--------|-----|---------|---------------|-------------|--------|----------|-------|---------|-----------|",
    ]

    for row in memory_rows:
        text = _extract_text(row)
        verdict, dims, rationale = _keepability_verdict(row, text)
        lines.append(
            f"| {_fmt_ts(_extract_ts(row, keys=('created_at','last_validated_at','ts')))} | "
            f"{_norm_text(row.get('source')) or 'unknown'} | "
            f"{_short(_norm_text(row.get('insight_key')), 36)} | "
            f"{_md_escape(text, 170)} | "
            f"{dims['actionability']} | {dims['context_fit']} | {dims['causal_confidence']} | "
            f"{dims['transfer_score']} | {dims['decay_policy']} | {verdict} | {_short(rationale, 88)} |"
        )
    lines.append("")

    lines.extend(
        [
            f"## Advisory Emission Cohort (Latest {len(emission_rows)})",
            "",
            "| ts | tool | trace | advisory text | actionability | context-fit | transfer | decay | verdict | rationale |",
            "|----|------|-------|---------------|---------------|-------------|----------|-------|---------|-----------|",
        ]
    )
    for row in emission_rows:
        text = _extract_text(row)
        verdict, dims, rationale = _keepability_verdict(row, text)
        lines.append(
            f"| {_fmt_ts(_extract_ts(row))} | {_norm_text(row.get('tool_name')) or '?'} | "
            f"`{_short(_trace_from_row(row), 18) or '-'}` | {_md_escape(text, 170)} | "
            f"{dims['actionability']} | {dims['context_fit']} | {dims['transfer_score']} | "
            f"{dims['decay_policy']} | {verdict} | {_short(rationale, 88)} |"
        )
    lines.append("")

    lines.extend(
        [
            f"## Quality Event Cohort (Latest {len(quality_rows)})",
            "",
            "| ts | source_hint | trace | advisory text | helpfulness | actionability | causal | transfer | verdict | rationale |",
            "|----|------------|-------|---------------|-------------|---------------|--------|----------|---------|-----------|",
        ]
    )
    for row in quality_rows:
        text = _extract_text(row)
        verdict, dims, rationale = _keepability_verdict(row, text)
        helpfulness = _norm_text(row.get("helpfulness_label") or row.get("helpful_label") or "unknown")
        lines.append(
            f"| {_fmt_ts(_extract_ts(row, keys=('emitted_ts','recorded_at','ts')))} | "
            f"{_norm_text(row.get('source_hint')) or '?'} | `{_short(_trace_from_row(row), 18) or '-'}` | "
            f"{_md_escape(text, 170)} | {helpfulness} | {dims['actionability']} | "
            f"{dims['causal_confidence']} | {dims['transfer_score']} | {verdict} | {_short(rationale, 88)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _context_trace_cohorts_page(sample_size: int = 150) -> str:
    queue_rows, _ = _read_jsonl(_SD / "queue" / "events.jsonl", max_rows=22000)
    retrieval_rows, _ = _read_jsonl(_SD / "advisor" / "retrieval_router.jsonl", max_rows=22000)
    emit_rows, _ = _read_jsonl(_SD / "advisory_emit.jsonl", max_rows=22000)
    outcome_rows, _ = _read_jsonl(_SD / "outcomes.jsonl", max_rows=22000)
    feedback_rows, _ = _read_jsonl(_SD / "advice_feedback.jsonl", max_rows=22000)

    queue_by_trace: dict[str, dict[str, Any]] = {}
    for row in sorted(queue_rows, key=_extract_ts, reverse=True):
        trace = _trace_from_row(row) or _norm_text((row.get("data") or {}).get("trace_id"))
        if trace and trace not in queue_by_trace:
            queue_by_trace[trace] = row

    retrieval_by_trace: dict[str, dict[str, Any]] = {}
    for row in sorted(retrieval_rows, key=_extract_ts, reverse=True):
        trace = _trace_from_row(row)
        if trace and trace not in retrieval_by_trace:
            retrieval_by_trace[trace] = row

    emit_by_trace: dict[str, dict[str, Any]] = {}
    for row in sorted(emit_rows, key=_extract_ts, reverse=True):
        trace = _trace_from_row(row)
        if trace and trace not in emit_by_trace:
            emit_by_trace[trace] = row

    outcome_by_trace: dict[str, dict[str, Any]] = {}
    for row in sorted(outcome_rows, key=_extract_ts, reverse=True):
        trace = _trace_from_row(row)
        if trace and trace not in outcome_by_trace:
            outcome_by_trace[trace] = row

    feedback_by_trace: dict[str, dict[str, Any]] = {}
    for row in sorted(feedback_rows, key=_extract_ts, reverse=True):
        trace = _trace_from_row(row)
        if trace and trace not in feedback_by_trace:
            feedback_by_trace[trace] = row

    ordered_traces: list[str] = []
    for source in (emit_by_trace, retrieval_by_trace, outcome_by_trace, queue_by_trace):
        for trace in source.keys():
            if trace and trace not in ordered_traces:
                ordered_traces.append(trace)
            if len(ordered_traces) >= max(120, int(sample_size)):
                break
        if len(ordered_traces) >= max(120, int(sample_size)):
            break

    def _capture_context(row: dict[str, Any] | None) -> str:
        if not isinstance(row, dict):
            return "-"
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        tool_input = row.get("tool_input") if isinstance(row.get("tool_input"), dict) else {}
        tool_input = tool_input or (data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {})
        parts = [
            _norm_text(row.get("event_type") or row.get("hook_event")),
            _norm_text(row.get("tool_name") or data.get("tool_name")),
            _short(_norm_text(tool_input.get("description") or tool_input.get("command") or tool_input.get("pattern")), 85),
        ]
        return _short(" | ".join(part for part in parts if part), 150)

    def _retrieval_context(row: dict[str, Any] | None) -> str:
        if not isinstance(row, dict):
            return "-"
        route = _norm_text(row.get("route") or "unknown")
        reason = _norm_text(row.get("reason") or "unknown")
        detail = f"route={route}; reason={reason}; primary={_norm_text(row.get('primary_count')) or '0'}"
        return _short(detail, 150)

    def _outcome_context(out_row: dict[str, Any] | None, fb_row: dict[str, Any] | None) -> str:
        if isinstance(out_row, dict):
            txt = _short(_norm_text(out_row.get("text")), 100)
            return _short(
                f"{_norm_text(out_row.get('event_type')) or 'outcome'} | "
                f"{_norm_text(out_row.get('polarity')) or '?'} | {txt}",
                160,
            )
        if isinstance(fb_row, dict):
            return _short(
                f"feedback status={_norm_text(fb_row.get('status')) or '?'}; "
                f"helpful={_norm_text(fb_row.get('helpful')) or '?'}; "
                f"source={_norm_text(fb_row.get('source')) or '?'}",
                160,
            )
        return "-"

    def _trace_verdict(capture_txt: str, retrieval_txt: str, emission_txt: str, outcome_txt: str) -> tuple[str, str]:
        has_gap = "-" in (capture_txt, retrieval_txt, emission_txt)
        if has_gap:
            return "partial", "Missing stage context in the trace chain."
        if _is_telemetry_text(emission_txt):
            return "misaligned", "Emission carries operational residue instead of guidance."
        if "route=empty" in retrieval_txt and emission_txt != "-":
            return "misaligned", "Retrieval was empty yet advisory still emitted generic guidance."
        if emission_txt != "-" and outcome_txt == "-":
            return "unknown", "No clear outcome or feedback context attached to this trace."
        return "coherent", "Trace has capture, retrieval, emission, and outcome context."

    lines = [
        "---",
        "title: Context Trace Cohorts",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - context-first",
        "  - traces",
        "---",
        "",
        "# Context Trace Cohorts",
        "",
        f"> {flow_link()} | [[stages/01-event_capture|Stage 1]] -> [[stages/08-advisory|Stage 8]]",
        "",
        "End-to-end context table over 100+ traces. This is the primary surface for semantic debugging before metric tuning.",
        "",
        f"## Cross-Stage Trace Table (Latest {len(ordered_traces)})",
        "",
        "| trace | capture context | retrieval context | emission text | outcome/feedback | context verdict | analyst note |",
        "|------|------------------|-------------------|---------------|------------------|----------------|--------------|",
    ]

    for trace in ordered_traces:
        capture_txt = _capture_context(queue_by_trace.get(trace))
        retrieval_txt = _retrieval_context(retrieval_by_trace.get(trace))
        emission_txt = _short(_extract_text(emit_by_trace.get(trace, {})), 130) if trace in emit_by_trace else "-"
        outcome_txt = _outcome_context(outcome_by_trace.get(trace), feedback_by_trace.get(trace))
        verdict, note = _trace_verdict(capture_txt, retrieval_txt, emission_txt, outcome_txt)
        lines.append(
            f"| `{_short(trace, 22)}` | {_md_escape(capture_txt)} | "
            f"{_md_escape(retrieval_txt)} | {_md_escape(emission_txt)} | "
            f"{_md_escape(outcome_txt)} | {verdict} | {_short(note, 95)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _intelligence_signal_tables_page() -> str:
    memory_rows = _iter_cognitive_items(limit=260)
    quality_rows, _ = _read_jsonl(_SD / "advisor" / "advisory_quality_events.jsonl", max_rows=5000)
    quality_rows = sorted(quality_rows, key=_extract_ts, reverse=True)

    false_wisdom_rows: list[dict[str, Any]] = []
    for row in memory_rows:
        text = _extract_text(row)
        if not text:
            continue
        if _is_telemetry_text(text) and (
            bool(row.get("promoted")) or int(row.get("times_validated") or 0) >= 5 or float(row.get("reliability") or 0.0) >= 0.6
        ):
            false_wisdom_rows.append(
                {
                    "source": _norm_text(row.get("source")) or "cognitive",
                    "id": _norm_text(row.get("insight_key"))[:48],
                    "text": text,
                    "why_looked_good": _short(
                        f"validated={_norm_text(row.get('times_validated')) or '0'}; "
                        f"reliability={_norm_text(row.get('reliability')) or '0'}; "
                        f"promoted={_norm_text(row.get('promoted')) or 'false'}",
                        130,
                    ),
                    "why_not_keepable": "Telemetry residue rewarded by exposure, not durable user value.",
                    "action": "drop_or_quarantine",
                }
            )
        if len(false_wisdom_rows) >= 140:
            break

    for row in quality_rows:
        text = _extract_text(row)
        if not text or not _is_telemetry_text(text):
            continue
        helpfulness = _norm_text(row.get("helpfulness_label") or "unknown")
        followed = _norm_text(row.get("followed"))
        if helpfulness in {"helpful", "unknown"} and followed in {"True", "true", "1"}:
            false_wisdom_rows.append(
                {
                    "source": _norm_text(row.get("source_hint")) or "quality",
                    "id": _norm_text(row.get("event_id"))[:48],
                    "text": text,
                    "why_looked_good": _short(
                        f"helpfulness={helpfulness}; followed={followed}; judge={_norm_text(row.get('judge_source')) or '?'}",
                        130,
                    ),
                    "why_not_keepable": "Follow-through evidence is not enough when advisory content is non-transferable telemetry.",
                    "action": "rewrite_or_drop",
                }
            )
        if len(false_wisdom_rows) >= 220:
            break

    compounding_rows: list[dict[str, Any]] = []
    for row in memory_rows:
        text = _extract_text(row)
        if not text:
            continue
        verdict, dims, rationale = _keepability_verdict(row, text)
        if verdict != "keep":
            continue
        if dims["transfer_score"] not in {"strong", "medium"}:
            continue
        compounding_rows.append(
            {
                "source": _norm_text(row.get("source")) or "cognitive",
                "id": _norm_text(row.get("insight_key"))[:48],
                "text": text,
                "reusable_shape": "if->action" if any(cue in text.lower() for cue in _TRANSFER_CUES) else "action_pattern",
                "boundary": "tool/context specific; validate before promoting globally",
                "next_rule": "promote_only_if_outcome_linked_and_non_telemetry",
                "note": rationale,
            }
        )
        if len(compounding_rows) >= 80:
            break

    lines = [
        "---",
        "title: Intelligence Signal Tables",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - memory",
        "  - context-first",
        "---",
        "",
        "# Intelligence Signal Tables",
        "",
        f"> {flow_link()} | [[keepability_gate_review|Keepability Gate Review]]",
        "",
        "## False Wisdom Table",
        "",
        "Rows that looked strong in mechanics but fail semantic keepability.",
        "",
        f"| source | id | snippet | why it looked good | why it is not keepable | immediate action |",
        "|--------|----|---------|--------------------|--------------------------|------------------|",
    ]

    for row in false_wisdom_rows[:220]:
        lines.append(
            f"| {row['source']} | {_short(row['id'], 38)} | {_md_escape(row['text'], 170)} | "
            f"{_md_escape(row['why_looked_good'], 95)} | "
            f"{_md_escape(row['why_not_keepable'], 95)} | {row['action']} |"
        )
    if not false_wisdom_rows:
        lines.append("| - | - | - | - | - | - |")
    lines.append("")

    lines.extend(
        [
            "## Compounding Insights Table",
            "",
            "Rows with higher transfer potential that should shape future advisory behavior.",
            "",
            "| source | id | snippet | reusable shape | boundary condition | next capture rule | note |",
            "|--------|----|---------|----------------|--------------------|-------------------|------|",
        ]
    )
    for row in compounding_rows[:80]:
        lines.append(
            f"| {row['source']} | {_short(row['id'], 38)} | {_md_escape(row['text'], 170)} | "
            f"{row['reusable_shape']} | {_md_escape(row['boundary'], 78)} | "
            f"{row['next_rule']} | {_md_escape(row['note'], 90)} |"
        )
    if not compounding_rows:
        lines.append("| - | - | - | - | - | - | - |")
    lines.append("")
    return "\n".join(lines)


def _intelligence_constitution_page() -> str:
    lines = [
        "---",
        "title: Intelligence Constitution",
        "tags:",
        "  - observatory",
        "  - advisory",
        "  - memory",
        "  - constitution",
        "---",
        "",
        "# Intelligence Constitution",
        "",
        "Non-negotiable invariants for what qualifies as intelligence in Spark alpha.",
        "",
        "## Invariants",
        "",
        "1. Memory is not telemetry: operational residue must stay in ops logs unless rewritten into reusable guidance.",
        "2. Promotion requires causal context: co-occurrence alone cannot justify long-lived intelligence.",
        "3. Advice must be context-bound: each advisory should fit the current tool/task moment.",
        "4. Transfer beats novelty: keep what generalizes across sessions, not what merely appeared recently.",
        "5. Every insight has expiry: if it cannot survive context shifts, decay or quarantine it.",
        "6. Observability must be semantic: each stage should expose meaning traces, not only volume and timing.",
        "7. Rewrites are first-class: potentially useful but weak entries are rewritten before promotion.",
        "8. Unknown outcomes are debt: unresolved helpfulness must be tracked as uncertainty, not hidden by proxy wins.",
        "",
        "## Keepability Gate Contract",
        "",
        "| Gate | Required question before keep |",
        "|------|-------------------------------|",
        "| Actionability | What concrete action should the user take now? |",
        "| Context-fit | Why is this relevant to this tool invocation? |",
        "| Causal confidence | What evidence links this guidance to outcome change? |",
        "| Transfer score | Will this help in adjacent future tasks? |",
        "| Expiry/decay | How long should it remain active before revalidation? |",
        "",
        "## Review Surfaces",
        "",
        "- [[keepability_gate_review|Keepability Gate Review]]",
        "- [[context_trace_cohorts|Context Trace Cohorts]]",
        "- [[intelligence_signal_tables|Intelligence Signal Tables]]",
        "",
    ]
    return "\n".join(lines)


def generate_advisory_context_pages(data: dict[int, dict[str, Any]]) -> dict[str, str]:
    """Generate additional observatory pages for context-rich advisory diagnostics."""
    return {
        "advisory_trace_lineage.md": _trace_lineage_page(data),
        "advisory_emission_lineage_deep.md": _advisory_emission_lineage_deep_page(),
        "advisory_unknown_helpfulness_burndown.md": _unknown_helpfulness_page(data),
        "advisory_suppression_replay.md": _suppression_replay_page(),
        "advisory_context_drift.md": _context_drift_page(),
        "advisory_data_integrity.md": _data_integrity_page(data),
        "retrieval_route_forensics.md": _retrieval_route_forensics_page(),
        "advisory_content_quality_forensics.md": _advisory_content_quality_forensics_page(),
        "intelligence_constitution.md": _intelligence_constitution_page(),
        "keepability_gate_review.md": _keepability_gate_page(),
        "context_trace_cohorts.md": _context_trace_cohorts_page(),
        "intelligence_signal_tables.md": _intelligence_signal_tables_page(),
    }
