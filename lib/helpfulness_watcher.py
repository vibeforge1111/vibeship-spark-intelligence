"""Deterministic advisory helpfulness watcher.

Builds a canonical helpfulness event stream from existing Spark logs:
- advice exposures: ~/.spark/advice_feedback_requests.jsonl
- explicit feedback: ~/.spark/advice_feedback.jsonl
- implicit signals: ~/.spark/advisor/implicit_feedback.jsonl

Design goals:
- lightweight: tail-based reads and bounded outputs
- stable: deterministic joins with trace/run/group keys
- accurate-first: explicit feedback is authoritative; implicit success does
  not auto-count as "helpful" without stronger evidence
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WatcherConfig:
    spark_dir: Path
    max_request_rows: int = 6000
    max_explicit_rows: int = 10000
    max_implicit_rows: int = 16000
    explicit_window_s: int = 6 * 3600
    implicit_window_s: int = 90 * 60
    min_created_at: float = 0.0
    llm_review_confidence_threshold: float = 0.75
    min_applied_review_confidence: float = 0.65
    max_review_rows: int = 20000
    write_files: bool = True


@dataclass(frozen=True)
class WatcherPaths:
    requests_file: Path
    explicit_file: Path
    implicit_file: Path
    events_file: Path
    summary_file: Path
    llm_queue_file: Path
    llm_reviews_file: Path


def _default_paths(spark_dir: Path) -> WatcherPaths:
    return WatcherPaths(
        requests_file=spark_dir / "advice_feedback_requests.jsonl",
        explicit_file=spark_dir / "advice_feedback.jsonl",
        implicit_file=spark_dir / "advisor" / "implicit_feedback.jsonl",
        events_file=spark_dir / "advisor" / "helpfulness_events.jsonl",
        summary_file=spark_dir / "advisor" / "helpfulness_summary.json",
        llm_queue_file=spark_dir / "advisor" / "helpfulness_llm_queue.jsonl",
        llm_reviews_file=spark_dir / "advisor" / "helpfulness_llm_reviews.jsonl",
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _coerce_bool_or_none(value: Any) -> Optional[bool]:
    if value is True:
        return True
    if value is False:
        return False
    return None


def _tail_jsonl(path: Path, max_rows: int) -> List[Dict[str, Any]]:
    if not path.exists() or max_rows <= 0:
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-max_rows:]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _norm_tool(value: Any) -> str:
    return _norm_text(value).lower()


def _hash_id(blob: str) -> str:
    return hashlib.sha256(blob.encode("utf-8", errors="ignore")).hexdigest()[:24]


def _event_id_for_request(req: Dict[str, Any], advice_id: str, idx: int) -> str:
    run_id = _norm_text(req.get("run_id"))
    trace_id = _norm_text(req.get("trace_id"))
    group = _norm_text(req.get("advisory_group_key"))
    ts = _safe_float(req.get("created_at"), 0.0)
    base = "|".join(
        [
            run_id or trace_id or group or f"no-key:{ts:.3f}:{idx}",
            _norm_tool(req.get("tool")),
            _norm_text(advice_id),
        ]
    )
    return _hash_id(base)


def _sort_rows_by_ts(rows: Iterable[Dict[str, Any]], ts_key: str) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda r: _safe_float(r.get(ts_key), 0.0))


def _build_explicit_indexes(
    rows: Iterable[Dict[str, Any]],
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]]:
    by_advice: Dict[str, List[Dict[str, Any]]] = {}
    by_group: Dict[str, List[Dict[str, Any]]] = {}
    by_trace: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        advice_ids = row.get("advice_ids")
        if isinstance(advice_ids, list):
            for aid in advice_ids:
                key = _norm_text(aid)
                if key:
                    by_advice.setdefault(key, []).append(row)
        group = _norm_text(row.get("advisory_group_key"))
        if group:
            by_group.setdefault(group, []).append(row)
        trace = _norm_text(row.get("trace_id"))
        if trace:
            by_trace.setdefault(trace, []).append(row)
    for bucket in (by_advice, by_group, by_trace):
        for key in list(bucket.keys()):
            bucket[key] = _sort_rows_by_ts(bucket[key], "created_at")
    return by_advice, by_group, by_trace


def _build_implicit_indexes(
    rows: Iterable[Dict[str, Any]],
) -> Tuple[Dict[Tuple[str, str], List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]]:
    by_trace_tool: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    by_trace: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        trace = _norm_text(row.get("trace_id"))
        tool = _norm_tool(row.get("tool"))
        if trace and tool:
            by_trace_tool.setdefault((trace, tool), []).append(row)
        if trace:
            by_trace.setdefault(trace, []).append(row)
    for bucket in (by_trace_tool, by_trace):
        for key in list(bucket.keys()):
            bucket[key] = _sort_rows_by_ts(bucket[key], "timestamp")
    return by_trace_tool, by_trace


def _pick_best_explicit(
    req: Dict[str, Any],
    advice_id: str,
    by_advice: Dict[str, List[Dict[str, Any]]],
    by_group: Dict[str, List[Dict[str, Any]]],
    by_trace: Dict[str, List[Dict[str, Any]]],
    window_s: int,
) -> Optional[Dict[str, Any]]:
    req_ts = _safe_float(req.get("created_at"), 0.0)
    if req_ts <= 0.0:
        return None
    req_trace = _norm_text(req.get("trace_id"))
    req_run = _norm_text(req.get("run_id"))
    req_group = _norm_text(req.get("advisory_group_key"))
    req_tool = _norm_tool(req.get("tool"))

    candidates: List[Dict[str, Any]] = []
    candidates.extend(by_advice.get(_norm_text(advice_id), []))
    if req_group:
        candidates.extend(by_group.get(req_group, []))
    if req_trace:
        candidates.extend(by_trace.get(req_trace, []))
    if not candidates:
        return None

    best: Optional[Tuple[float, float, Dict[str, Any]]] = None
    for row in candidates:
        ts = _safe_float(row.get("created_at"), 0.0)
        if ts <= 0.0:
            continue
        if ts + 5 < req_ts:
            continue
        if ts - req_ts > float(window_s):
            continue
        trace = _norm_text(row.get("trace_id"))
        run_id = _norm_text(row.get("run_id"))
        group = _norm_text(row.get("advisory_group_key"))
        tool = _norm_tool(row.get("tool"))
        score = 0.0
        if req_trace and trace and req_trace == trace:
            score += 8.0
        if req_group and group and req_group == group:
            score += 5.0
        if req_run and run_id and req_run == run_id:
            score += 4.0
        if req_tool and tool and req_tool == tool:
            score += 1.0
        if score <= 0:
            continue
        score += max(0.0, 1.0 - ((ts - req_ts) / max(float(window_s), 1.0)))
        choice = (score, -ts, row)
        if best is None or choice > best:
            best = choice
    return best[2] if best else None


def _pick_best_implicit(
    req: Dict[str, Any],
    by_trace_tool: Dict[Tuple[str, str], List[Dict[str, Any]]],
    by_trace: Dict[str, List[Dict[str, Any]]],
    window_s: int,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    req_ts = _safe_float(req.get("created_at"), 0.0)
    req_trace = _norm_text(req.get("trace_id"))
    req_tool = _norm_tool(req.get("tool"))
    if req_ts <= 0.0 or not req_trace:
        return None, False

    rows = by_trace_tool.get((req_trace, req_tool), [])
    tool_fallback = False
    if not rows:
        rows = by_trace.get(req_trace, [])
        tool_fallback = bool(rows)
    if not rows:
        return None, False

    best_row: Optional[Dict[str, Any]] = None
    for row in rows:
        ts = _safe_float(row.get("timestamp"), 0.0)
        if ts <= 0:
            continue
        if ts + 5 < req_ts:
            continue
        if ts - req_ts > float(window_s):
            continue
        if best_row is None or ts < _safe_float(best_row.get("timestamp"), 0.0):
            best_row = row
    return best_row, tool_fallback


def _derive_from_explicit(row: Dict[str, Any]) -> Dict[str, Any]:
    helpful = row.get("helpful")
    followed = _coerce_bool_or_none(row.get("followed"))
    status = _norm_text(row.get("status")).lower()

    if status == "harmful":
        return {"label": "harmful", "followed": True, "confidence": 0.99, "judge_source": "explicit_feedback"}
    if helpful is True:
        return {"label": "helpful", "followed": True if followed is not False else False, "confidence": 0.99, "judge_source": "explicit_feedback"}
    if helpful is False:
        return {"label": "unhelpful", "followed": True if followed is not False else False, "confidence": 0.99, "judge_source": "explicit_feedback"}
    if status in {"blocked"}:
        return {"label": "unhelpful", "followed": True if followed is not False else False, "confidence": 0.96, "judge_source": "explicit_feedback_status"}
    if status in {"ignored", "skipped"}:
        return {"label": "not_followed", "followed": False, "confidence": 0.96, "judge_source": "explicit_feedback_status"}
    if status == "acted":
        return {"label": "helpful", "followed": True, "confidence": 0.86, "judge_source": "explicit_feedback_status"}
    if followed is False:
        return {"label": "not_followed", "followed": False, "confidence": 0.92, "judge_source": "explicit_feedback"}
    if followed is True:
        return {"label": "unknown", "followed": True, "confidence": 0.7, "judge_source": "explicit_feedback_partial"}
    return {"label": "unknown", "followed": None, "confidence": 0.6, "judge_source": "explicit_feedback_partial"}


def _derive_from_implicit(signal: str, *, tool_fallback: bool) -> Dict[str, Any]:
    sig = _norm_text(signal).lower()
    penalty = 0.08 if tool_fallback else 0.0
    if sig == "unhelpful":
        return {"label": "unhelpful", "followed": None, "confidence": max(0.0, 0.74 - penalty), "judge_source": "implicit_feedback"}
    if sig in {"ignored", "not_followed"}:
        return {"label": "not_followed", "followed": False, "confidence": max(0.0, 0.68 - penalty), "judge_source": "implicit_feedback"}
    if sig in {"followed", "helpful"}:
        # Success alone is not enough to claim helpfulness confidently.
        return {"label": "unknown", "followed": True, "confidence": max(0.0, 0.58 - penalty), "judge_source": "implicit_feedback"}
    return {"label": "unknown", "followed": None, "confidence": 0.4, "judge_source": "implicit_feedback"}


def _is_conflict(label_a: str, label_b: str) -> bool:
    la = _norm_text(label_a).lower()
    lb = _norm_text(label_b).lower()
    if not la or not lb or la == lb:
        return False
    decisive = {"helpful", "unhelpful", "harmful", "not_followed"}
    return la in decisive and lb in decisive


def _make_event(
    req: Dict[str, Any],
    advice_id: str,
    source_hint: str,
    explicit_row: Optional[Dict[str, Any]],
    implicit_row: Optional[Dict[str, Any]],
    implicit_tool_fallback: bool,
    *,
    idx: int,
    confidence_threshold: float,
) -> Dict[str, Any]:
    req_ts = _safe_float(req.get("created_at"), 0.0)
    trace_id = _norm_text(req.get("trace_id"))
    run_id = _norm_text(req.get("run_id"))
    group = _norm_text(req.get("advisory_group_key"))
    tool = _norm_text(req.get("tool"))

    explicit_decision = _derive_from_explicit(explicit_row) if explicit_row else None
    implicit_signal = _norm_text((implicit_row or {}).get("signal")).lower()
    implicit_decision = _derive_from_implicit(implicit_signal, tool_fallback=implicit_tool_fallback) if implicit_row else None

    conflict = False
    if explicit_decision and implicit_decision:
        conflict = _is_conflict(explicit_decision.get("label", ""), implicit_decision.get("label", ""))

    if explicit_decision and explicit_decision.get("label") != "unknown":
        final = dict(explicit_decision)
        if conflict:
            final["confidence"] = max(0.0, float(final.get("confidence", 0.0)) - 0.1)
    elif explicit_decision and implicit_decision and implicit_decision.get("label") != "unknown":
        final = dict(implicit_decision)
        final["judge_source"] = "implicit_after_explicit_unknown"
        final["confidence"] = max(0.0, float(final.get("confidence", 0.0)) - 0.05)
    elif explicit_decision:
        final = dict(explicit_decision)
    elif implicit_decision:
        final = dict(implicit_decision)
    else:
        final = {
            "label": "unknown",
            "followed": None,
            "confidence": 0.2,
            "judge_source": "no_signal",
        }

    explicit_ts = _safe_float((explicit_row or {}).get("created_at"), 0.0)
    implicit_ts = _safe_float((implicit_row or {}).get("timestamp"), 0.0)
    evidence_ts = min(x for x in [explicit_ts, implicit_ts] if x > 0) if (explicit_ts > 0 or implicit_ts > 0) else 0.0
    latency_s = max(0.0, evidence_ts - req_ts) if req_ts > 0 and evidence_ts > 0 else None

    evidence_refs: List[str] = []
    if explicit_row:
        evidence_refs.append(
            f"advice_feedback.jsonl:trace={_norm_text(explicit_row.get('trace_id'))}:run={_norm_text(explicit_row.get('run_id'))}:advice={_norm_text(advice_id)}"
        )
    if implicit_row:
        evidence_refs.append(
            f"advisor/implicit_feedback.jsonl:trace={_norm_text(implicit_row.get('trace_id'))}:tool={_norm_text(implicit_row.get('tool'))}:signal={implicit_signal}"
        )

    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": _event_id_for_request(req, advice_id, idx),
        "request_ts": req_ts,
        "resolved_at": time.time(),
        "session_id": _norm_text(req.get("session_id")),
        "session_kind": _norm_text(req.get("session_kind")),
        "tool": tool,
        "trace_id": trace_id,
        "run_id": run_id,
        "advisory_group_key": group,
        "packet_id": _norm_text(req.get("packet_id")),
        "route": _norm_text(req.get("route")),
        "advice_id": _norm_text(advice_id),
        "source_hint": _norm_text(source_hint),
        "helpful_label": _norm_text(final.get("label")).lower() or "unknown",
        "followed": final.get("followed"),
        "confidence": round(_safe_float(final.get("confidence"), 0.0), 3),
        "judge_source": _norm_text(final.get("judge_source")) or "unknown",
        "explicit_present": bool(explicit_row),
        "implicit_present": bool(implicit_row),
        "explicit_status": _norm_text((explicit_row or {}).get("status")).lower() or None,
        "implicit_signal": implicit_signal or None,
        "conflict": bool(conflict),
        "llm_review_required": bool(
            conflict
            or (
                _safe_float(final.get("confidence"), 0.0) < confidence_threshold
                and _norm_text(final.get("judge_source")) not in {"", "no_signal"}
            )
        ),
        "latency_s": round(latency_s, 3) if isinstance(latency_s, float) else None,
        "evidence_refs": evidence_refs[:6],
    }
    return event


def _summarize(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(events)
    by_label: Dict[str, int] = {}
    judge_source: Dict[str, int] = {}
    conflicts = 0
    llm_queue = 0
    high_confidence = 0
    followed_true = 0
    followed_false = 0
    llm_review_applied_count = 0
    for row in events:
        label = _norm_text(row.get("helpful_label")).lower() or "unknown"
        by_label[label] = by_label.get(label, 0) + 1
        js = _norm_text(row.get("judge_source")) or "unknown"
        judge_source[js] = judge_source.get(js, 0) + 1
        if bool(row.get("conflict")):
            conflicts += 1
        if bool(row.get("llm_review_required")):
            llm_queue += 1
        if _safe_float(row.get("confidence"), 0.0) >= 0.9:
            high_confidence += 1
        if bool(row.get("llm_review_applied")):
            llm_review_applied_count += 1
        followed = row.get("followed")
        if followed is True:
            followed_true += 1
        elif followed is False:
            followed_false += 1

    helpful = by_label.get("helpful", 0)
    unhelpful = by_label.get("unhelpful", 0)
    harmful = by_label.get("harmful", 0)
    unknown = by_label.get("unknown", 0)
    not_followed = by_label.get("not_followed", 0)

    known_helpfulness = helpful + unhelpful + harmful
    helpful_rate = (100.0 * helpful / known_helpfulness) if known_helpfulness > 0 else 0.0
    conflict_rate = (100.0 * conflicts / max(total, 1)) if total > 0 else 0.0
    unknown_rate = (100.0 * unknown / max(total, 1)) if total > 0 else 0.0
    follow_eval_total = followed_true + followed_false
    follow_rate = (100.0 * followed_true / max(follow_eval_total, 1)) if follow_eval_total > 0 else 0.0

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.time(),
        "total_events": total,
        "labels": by_label,
        "judge_source": judge_source,
        "known_helpfulness_total": known_helpfulness,
        "helpful_rate_pct": round(helpful_rate, 2),
        "unknown_rate_pct": round(unknown_rate, 2),
        "conflict_count": conflicts,
        "conflict_rate_pct": round(conflict_rate, 2),
        "llm_review_queue_count": llm_queue,
        "llm_review_applied_count": llm_review_applied_count,
        "high_confidence_count": high_confidence,
        "followed_true": followed_true,
        "followed_false": followed_false,
        "follow_eval_total": follow_eval_total,
        "follow_rate_pct": round(follow_rate, 2),
        "not_followed_count": not_followed,
    }


def _review_index(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        eid = _norm_text(row.get("event_id"))
        if not eid:
            continue
        prior = out.get(eid)
        if not prior or _safe_float(row.get("reviewed_at"), 0.0) >= _safe_float(prior.get("reviewed_at"), 0.0):
            out[eid] = row
    return out


def _apply_review_override(
    event: Dict[str, Any],
    review: Dict[str, Any],
    *,
    min_confidence: float,
) -> Dict[str, Any]:
    row = dict(event)
    row["llm_review_present"] = True
    row["llm_review_status"] = _norm_text(review.get("status")).lower()
    row["llm_review_provider"] = _norm_text(review.get("provider"))
    row["llm_review_label"] = _norm_text(review.get("label")).lower()
    row["llm_review_confidence"] = round(_safe_float(review.get("confidence"), 0.0), 3)

    status = row["llm_review_status"]
    label = row["llm_review_label"]
    confidence = _safe_float(row["llm_review_confidence"], 0.0)
    if status != "ok":
        row["llm_review_applied"] = False
        return row
    if label not in {"helpful", "unhelpful", "harmful", "not_followed", "unknown"}:
        row["llm_review_applied"] = False
        return row
    if confidence < max(0.0, float(min_confidence)):
        row["llm_review_applied"] = False
        return row

    base_label = _norm_text(row.get("helpful_label")).lower()
    if _is_conflict(base_label, label):
        row["conflict"] = True
    row["base_helpful_label"] = base_label
    row["helpful_label"] = label
    row["judge_source"] = f"llm_review:{row['llm_review_provider'] or 'unknown'}"
    row["confidence"] = max(_safe_float(row.get("confidence"), 0.0), confidence)
    if label == "not_followed":
        row["followed"] = False
    row["llm_review_applied"] = True
    row["llm_review_required"] = False
    return row


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _write_jsonl_atomic(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(str(tmp), str(path))


def run_helpfulness_watcher(cfg: WatcherConfig) -> Dict[str, Any]:
    paths = _default_paths(cfg.spark_dir)

    req_rows = _tail_jsonl(paths.requests_file, cfg.max_request_rows)
    explicit_rows = _tail_jsonl(paths.explicit_file, cfg.max_explicit_rows)
    implicit_rows = _tail_jsonl(paths.implicit_file, cfg.max_implicit_rows)
    reviews_rows = _tail_jsonl(paths.llm_reviews_file, cfg.max_review_rows)

    req_rows = [
        r for r in req_rows
        if _safe_float(r.get("created_at"), 0.0) >= cfg.min_created_at
    ]
    req_rows = _sort_rows_by_ts(req_rows, "created_at")

    by_advice, by_group, by_trace = _build_explicit_indexes(explicit_rows)
    implicit_by_trace_tool, implicit_by_trace = _build_implicit_indexes(implicit_rows)
    reviews_by_event = _review_index(reviews_rows)

    events_map: Dict[str, Dict[str, Any]] = {}
    for req_idx, req in enumerate(req_rows):
        advice_ids = req.get("advice_ids")
        if not isinstance(advice_ids, list):
            continue
        sources = req.get("sources") if isinstance(req.get("sources"), list) else []
        for i, aid in enumerate(advice_ids[:40]):
            advice_id = _norm_text(aid)
            if not advice_id:
                continue
            source_hint = _norm_text(sources[i]) if i < len(sources) else ""

            explicit_row = _pick_best_explicit(
                req,
                advice_id,
                by_advice=by_advice,
                by_group=by_group,
                by_trace=by_trace,
                window_s=cfg.explicit_window_s,
            )
            implicit_row, implicit_tool_fallback = _pick_best_implicit(
                req,
                by_trace_tool=implicit_by_trace_tool,
                by_trace=implicit_by_trace,
                window_s=cfg.implicit_window_s,
            )
            event = _make_event(
                req,
                advice_id,
                source_hint,
                explicit_row=explicit_row,
                implicit_row=implicit_row,
                implicit_tool_fallback=implicit_tool_fallback,
                idx=req_idx,
                confidence_threshold=cfg.llm_review_confidence_threshold,
            )
            review = reviews_by_event.get(event.get("event_id", ""))
            if review:
                event = _apply_review_override(
                    event,
                    review,
                    min_confidence=cfg.min_applied_review_confidence,
                )
            events_map[event["event_id"]] = event

    events = sorted(events_map.values(), key=lambda r: (_safe_float(r.get("request_ts"), 0.0), _norm_text(r.get("event_id"))))
    summary = _summarize(events)
    llm_queue = [row for row in events if bool(row.get("llm_review_required"))]

    if cfg.write_files:
        _write_jsonl_atomic(paths.events_file, events)
        _write_json_atomic(paths.summary_file, summary)
        _write_jsonl_atomic(paths.llm_queue_file, llm_queue)

    return {
        "ok": True,
        "paths": {
            "events_file": str(paths.events_file),
            "summary_file": str(paths.summary_file),
            "llm_queue_file": str(paths.llm_queue_file),
        },
        "inputs": {
            "requests_rows": len(req_rows),
            "explicit_rows": len(explicit_rows),
            "implicit_rows": len(implicit_rows),
            "review_rows": len(reviews_rows),
        },
        "summary": summary,
    }


def run_helpfulness_watcher_default(
    *,
    spark_dir: Optional[Path] = None,
    max_request_rows: int = 6000,
    max_explicit_rows: int = 10000,
    max_implicit_rows: int = 16000,
    explicit_window_s: int = 6 * 3600,
    implicit_window_s: int = 90 * 60,
    min_created_at: float = 0.0,
    llm_review_confidence_threshold: float = 0.75,
    min_applied_review_confidence: float = 0.65,
    max_review_rows: int = 20000,
    write_files: bool = True,
) -> Dict[str, Any]:
    cfg = WatcherConfig(
        spark_dir=(spark_dir or (Path.home() / ".spark")),
        max_request_rows=max_request_rows,
        max_explicit_rows=max_explicit_rows,
        max_implicit_rows=max_implicit_rows,
        explicit_window_s=explicit_window_s,
        implicit_window_s=implicit_window_s,
        min_created_at=min_created_at,
        llm_review_confidence_threshold=llm_review_confidence_threshold,
        min_applied_review_confidence=min_applied_review_confidence,
        max_review_rows=max_review_rows,
        write_files=write_files,
    )
    return run_helpfulness_watcher(cfg)
