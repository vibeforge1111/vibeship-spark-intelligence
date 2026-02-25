#!/usr/bin/env python3
"""Daily memory quality observatory.

Tracks:
- Capture precision (noise-like ratio in stored memory)
- Context adequacy (context length distribution)
- Retrieval quality (semantic similarity + suppression patterns)
- Missed opportunities (high-signal prompts not captured)

Outputs:
- _observatory/memory_quality_snapshot.json
- docs/reports/<date>_memory_quality_observatory.md
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from lib.memory_capture import importance_score, normalize_memory_text
from lib.queue import EventType, read_recent_events


SPARK_DIR = Path.home() / ".spark"
MEMORY_DB = SPARK_DIR / "memory_store.sqlite"
COGNITIVE_FILE = SPARK_DIR / "cognitive_insights.json"
SEMANTIC_LOG = SPARK_DIR / "logs" / "semantic_retrieval.jsonl"
ADVISORY_ENGINE_LOG = SPARK_DIR / "advisory_engine.jsonl"
MIND_OFFLINE_QUEUE = SPARK_DIR / "mind_offline_queue.jsonl"
OBSERVATORY_DIR = Path("_observatory")
REPORTS_DIR = Path("docs") / "reports"
RETRIEVAL_GUARDRAIL_THRESHOLDS = {
    "semantic_sim_avg_min": 0.22,
    "semantic_sim_low_ratio_max": 0.20,
    "semantic_dominant_key_ratio_max": 0.35,
    "advisory_emit_rate_min": 0.15,
    "advisory_global_dedupe_ratio_max": 0.55,
    "capture_noise_ratio_max": 0.15,
    "context_p50_min": 120,
}

NOISE_MARKERS = (
    "you are spark intelligence, observing a live coding session",
    "system inventory (what actually exists",
    "<task-notification",
    "<task-id>",
    "event_type:",
    "tool_name:",
    "file_path:",
    "cwd:",
)


@dataclass
class CaptureRow:
    content: str
    source: str
    category: str
    created_at: float


def _now_ts() -> float:
    return time.time()


def _read_jsonl(path: Path, limit: int | None = None) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if limit is not None and limit > 0:
        lines = lines[-limit:]
    out: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _load_capture_rows(window_s: float) -> List[CaptureRow]:
    if not MEMORY_DB.exists():
        return []
    out: List[CaptureRow] = []
    cutoff = _now_ts() - window_s
    with sqlite3.connect(MEMORY_DB) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "select content, source, category, created_at from memories where source='capture'"
        ).fetchall()
    for r in rows:
        created_at = float(r["created_at"] or 0.0)
        if created_at < cutoff:
            continue
        out.append(
            CaptureRow(
                content=str(r["content"] or ""),
                source=str(r["source"] or ""),
                category=str(r["category"] or ""),
                created_at=created_at,
            )
        )
    return out


def _is_noise_like(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    return any(m in t for m in NOISE_MARKERS)


def _context_stats() -> Dict[str, Any]:
    if not COGNITIVE_FILE.exists():
        return {"count": 0}
    try:
        obj = json.loads(COGNITIVE_FILE.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {"count": 0}

    items: List[Dict[str, Any]] = []
    if isinstance(obj, dict):
        items = [v for v in obj.values() if isinstance(v, dict)]
    elif isinstance(obj, list):
        items = [v for v in obj if isinstance(v, dict)]

    contexts = [len(str(it.get("context") or "")) for it in items]
    if not contexts:
        return {"count": 0}
    contexts_sorted = sorted(contexts)
    return {
        "count": len(contexts),
        "avg": round(sum(contexts) / len(contexts), 1),
        "p50": int(statistics.median(contexts)),
        "p90": int(contexts_sorted[max(0, int(len(contexts) * 0.9) - 1)]),
        "lt30": sum(1 for x in contexts if x < 30),
        "lt80": sum(1 for x in contexts if x < 80),
    }


def _semantic_stats(window_s: float) -> Dict[str, Any]:
    cutoff = _now_ts() - window_s
    rows = [r for r in _read_jsonl(SEMANTIC_LOG, limit=8000) if float(r.get("ts") or 0.0) >= cutoff]
    sims: List[float] = []
    keys = Counter()
    for row in rows:
        for res in (row.get("final_results") or []):
            if not isinstance(res, dict):
                continue
            try:
                sims.append(float(res.get("sim") or 0.0))
            except Exception:
                pass
            keys[str(res.get("key") or "")] += 1
    total_hits = int(sum(keys.values()))
    dominant_key_ratio = 0.0
    if total_hits > 0:
        top_count = keys.most_common(1)[0][1] if keys else 0
        dominant_key_ratio = round(top_count / total_hits, 3)
    if not rows:
        return {"queries": 0}
    return {
        "queries": len(rows),
        "sim_avg": round(sum(sims) / len(sims), 3) if sims else 0.0,
        "sim_lt_0_1_ratio": round((sum(1 for s in sims if s < 0.1) / len(sims)), 3) if sims else 0.0,
        "dominant_key_ratio": dominant_key_ratio,
        "top_keys": keys.most_common(6),
    }


def _advisory_suppression_stats(window_s: float) -> Dict[str, Any]:
    cutoff = _now_ts() - window_s
    rows = [r for r in _read_jsonl(ADVISORY_ENGINE_LOG, limit=3000) if float(r.get("ts") or 0.0) >= cutoff]
    if not rows:
        return {"events": 0}
    no_emit = [r for r in rows if r.get("event") == "no_emit"]
    emitted = [r for r in rows if r.get("event") == "emitted"]
    reasons = Counter(str(r.get("gate_reason") or "") for r in no_emit)
    return {
        "events": len(rows),
        "emit_rate": round(len(emitted) / len(rows), 3),
        "no_emit": len(no_emit),
        "top_no_emit_reasons": reasons.most_common(8),
        "global_dedupe_ratio": round(
            (sum(1 for r in no_emit if "global_dedupe" in str(r.get("gate_reason") or "")) / len(no_emit)), 3
        ) if no_emit else 0.0,
    }


def _missed_opportunities(window_s: float) -> Dict[str, Any]:
    cutoff = _now_ts() - window_s
    events = read_recent_events(6000)
    candidates: List[Dict[str, Any]] = []
    for e in events:
        if float(e.timestamp or 0.0) < cutoff:
            continue
        if e.event_type != EventType.USER_PROMPT:
            continue
        payload = (e.data or {}).get("payload") or {}
        if str(payload.get("role") or "user") != "user":
            continue
        text = str(payload.get("text") or "").strip()
        if not text:
            continue
        if _is_noise_like(text):
            continue
        score, breakdown = importance_score(text)
        if score >= 0.72:
            candidates.append(
                {
                    "session_id": e.session_id,
                    "timestamp": float(e.timestamp or 0.0),
                    "text": normalize_memory_text(text),
                    "score": round(float(score), 3),
                    "breakdown": breakdown,
                }
            )

    captured = _load_capture_rows(window_s)
    captured_norm = {normalize_memory_text(r.content).lower()[:220] for r in captured}

    missed = []
    for c in candidates:
        key = c["text"].lower()[:220]
        if key and key not in captured_norm:
            missed.append(c)

    missed.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return {
        "candidate_high_signal": len(candidates),
        "missed_high_signal": len(missed),
        "missed_examples": [
            {
                "score": m["score"],
                "text": m["text"][:240],
                "session_id": m["session_id"],
            }
            for m in missed[:10]
        ],
    }


def build_snapshot(window_hours: int = 24) -> Dict[str, Any]:
    window_s = float(window_hours) * 3600.0
    capture = _load_capture_rows(window_s)
    capture_lengths = [len(c.content or "") for c in capture]
    noise_count = sum(1 for c in capture if _is_noise_like(c.content))

    offline_rows = _read_jsonl(MIND_OFFLINE_QUEUE, limit=5000)
    offline_noise = 0
    for row in offline_rows:
        md = row.get("memory_data") or {}
        if isinstance(md, dict) and _is_noise_like(str(md.get("content") or "")):
            offline_noise += 1

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": window_hours,
        "capture": {
            "count": len(capture),
            "noise_like_count": noise_count,
            "noise_like_ratio": round(noise_count / len(capture), 3) if capture else 0.0,
            "len_avg": round(sum(capture_lengths) / len(capture_lengths), 1) if capture_lengths else 0.0,
            "len_p50": int(statistics.median(capture_lengths)) if capture_lengths else 0,
            "len_p90": int(sorted(capture_lengths)[max(0, int(len(capture_lengths) * 0.9) - 1)]) if capture_lengths else 0,
            "category_top": Counter(c.category for c in capture).most_common(8),
        },
        "offline_queue": {
            "rows_sampled": len(offline_rows),
            "noise_like_count": offline_noise,
            "noise_like_ratio": round(offline_noise / len(offline_rows), 3) if offline_rows else 0.0,
        },
        "context": _context_stats(),
        "semantic_retrieval": _semantic_stats(window_s),
        "advisory_engine": _advisory_suppression_stats(window_s),
        "missed_capture": _missed_opportunities(window_s),
    }
    return snapshot


def _snapshot_grade(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    capture_noise = float(((snapshot.get("capture") or {}).get("noise_like_ratio") or 0.0))
    context_p50 = int(((snapshot.get("context") or {}).get("p50") or 0))
    missed_ratio = 0.0
    missed = (snapshot.get("missed_capture") or {})
    cand = float(missed.get("candidate_high_signal") or 0.0)
    if cand > 0:
        missed_ratio = float(missed.get("missed_high_signal") or 0.0) / cand

    score = 1.0
    score -= min(0.4, capture_noise * 0.6)
    if context_p50 < 80:
        score -= 0.2
    if context_p50 < 40:
        score -= 0.1
    score -= min(0.3, missed_ratio * 0.5)
    score = max(0.0, min(1.0, score))

    if score >= 0.8:
        band = "GREEN"
    elif score >= 0.6:
        band = "YELLOW"
    else:
        band = "RED"

    return {
        "score": round(score, 3),
        "band": band,
        "capture_noise_ratio": round(capture_noise, 3),
        "context_p50": context_p50,
        "missed_high_signal_ratio": round(missed_ratio, 3),
    }


def _guardrail_check(
    *,
    name: str,
    actual: float,
    min_value: float | None = None,
    max_value: float | None = None,
    unit: str = "",
) -> Dict[str, Any]:
    passed = True
    if min_value is not None:
        passed = passed and actual >= min_value
    if max_value is not None:
        passed = passed and actual <= max_value
    expectation = ""
    if min_value is not None and max_value is not None:
        expectation = f"{min_value} <= x <= {max_value}{unit}"
    elif min_value is not None:
        expectation = f"x >= {min_value}{unit}"
    elif max_value is not None:
        expectation = f"x <= {max_value}{unit}"
    return {
        "name": name,
        "actual": round(float(actual), 3),
        "expectation": expectation,
        "pass": bool(passed),
    }


def _retrieval_guardrails(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    semantic = snapshot.get("semantic_retrieval") if isinstance(snapshot.get("semantic_retrieval"), dict) else {}
    advisory = snapshot.get("advisory_engine") if isinstance(snapshot.get("advisory_engine"), dict) else {}
    capture = snapshot.get("capture") if isinstance(snapshot.get("capture"), dict) else {}
    context = snapshot.get("context") if isinstance(snapshot.get("context"), dict) else {}

    checks = [
        _guardrail_check(
            name="semantic.sim_avg",
            actual=float(semantic.get("sim_avg") or 0.0),
            min_value=float(RETRIEVAL_GUARDRAIL_THRESHOLDS["semantic_sim_avg_min"]),
        ),
        _guardrail_check(
            name="semantic.sim_lt_0_1_ratio",
            actual=float(semantic.get("sim_lt_0_1_ratio") or 0.0),
            max_value=float(RETRIEVAL_GUARDRAIL_THRESHOLDS["semantic_sim_low_ratio_max"]),
        ),
        _guardrail_check(
            name="semantic.dominant_key_ratio",
            actual=float(semantic.get("dominant_key_ratio") or 0.0),
            max_value=float(RETRIEVAL_GUARDRAIL_THRESHOLDS["semantic_dominant_key_ratio_max"]),
        ),
        _guardrail_check(
            name="advisory.emit_rate",
            actual=float(advisory.get("emit_rate") or 0.0),
            min_value=float(RETRIEVAL_GUARDRAIL_THRESHOLDS["advisory_emit_rate_min"]),
        ),
        _guardrail_check(
            name="advisory.global_dedupe_ratio",
            actual=float(advisory.get("global_dedupe_ratio") or 0.0),
            max_value=float(RETRIEVAL_GUARDRAIL_THRESHOLDS["advisory_global_dedupe_ratio_max"]),
        ),
        _guardrail_check(
            name="capture.noise_like_ratio",
            actual=float(capture.get("noise_like_ratio") or 0.0),
            max_value=float(RETRIEVAL_GUARDRAIL_THRESHOLDS["capture_noise_ratio_max"]),
        ),
        _guardrail_check(
            name="context.p50",
            actual=float(context.get("p50") or 0.0),
            min_value=float(RETRIEVAL_GUARDRAIL_THRESHOLDS["context_p50_min"]),
        ),
    ]
    failed = [c for c in checks if not c.get("pass")]
    return {
        "passing": len(failed) == 0,
        "checks": checks,
        "failed_count": len(failed),
        "failed_names": [str(c.get("name")) for c in failed],
        "thresholds": dict(RETRIEVAL_GUARDRAIL_THRESHOLDS),
    }


def write_outputs(snapshot: Dict[str, Any]) -> None:
    OBSERVATORY_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    grade = _snapshot_grade(snapshot)
    guardrails = _retrieval_guardrails(snapshot)
    payload = dict(snapshot)
    payload["grade"] = grade
    payload["retrieval_guardrails"] = guardrails

    snapshot_path = OBSERVATORY_DIR / "memory_quality_snapshot.json"
    snapshot_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    day = datetime.now().strftime("%Y-%m-%d")
    guardrail_path = REPORTS_DIR / f"{day}_retrieval_guardrails.json"
    guardrail_path.write_text(json.dumps(guardrails, indent=2), encoding="utf-8")
    report_path = REPORTS_DIR / f"{day}_memory_quality_observatory.md"
    lines = [
        "# Memory Quality Observatory",
        "",
        f"- Generated: {snapshot.get('generated_at')}",
        f"- Window: last {snapshot.get('window_hours')}h",
        f"- Grade: **{grade['band']}** (score={grade['score']})",
        "",
        "## 1) Capture Precision",
        f"- capture count: {payload['capture']['count']}",
        f"- noise-like ratio: {payload['capture']['noise_like_ratio']}",
        f"- length p50/p90: {payload['capture']['len_p50']} / {payload['capture']['len_p90']}",
        "",
        "## 2) Context Adequacy",
        f"- context p50: {payload['context'].get('p50', 0)}",
        f"- context <30 chars: {payload['context'].get('lt30', 0)}",
        f"- context <80 chars: {payload['context'].get('lt80', 0)}",
        "",
        "## 3) Retrieval Health",
        f"- semantic sim avg: {payload['semantic_retrieval'].get('sim_avg', 0.0)}",
        f"- semantic sim <0.1 ratio: {payload['semantic_retrieval'].get('sim_lt_0_1_ratio', 0.0)}",
        f"- advisory emit rate: {payload['advisory_engine'].get('emit_rate', 0.0)}",
        f"- global dedupe suppression ratio: {payload['advisory_engine'].get('global_dedupe_ratio', 0.0)}",
        f"- dominant key ratio: {payload['semantic_retrieval'].get('dominant_key_ratio', 0.0)}",
        "",
        "## 4) Missed Capture Opportunities",
        f"- high-signal candidates: {payload['missed_capture'].get('candidate_high_signal', 0)}",
        f"- missed high-signal: {payload['missed_capture'].get('missed_high_signal', 0)}",
        "",
        "### Missed examples (top)",
    ]
    for ex in payload["missed_capture"].get("missed_examples", [])[:8]:
        lines.append(f"- ({ex['score']}) {ex['text']}")

    lines.extend(
        [
            "",
            "",
            "## 5) Retrieval Guardrails",
            f"- overall: {'PASS' if guardrails.get('passing') else 'FAIL'}",
            f"- failed checks: {guardrails.get('failed_count', 0)}",
            "",
            "| Check | Actual | Expectation | Status |",
            "| --- | ---: | --- | --- |",
        ]
    )
    for check in guardrails.get("checks", []):
        status = "PASS" if check.get("pass") else "FAIL"
        lines.append(
            f"| {check.get('name')} | {check.get('actual')} | {check.get('expectation')} | {status} |"
        )

    lines.extend(
        [
            "",
            "## 6) Next 24h Actions",
            "1. Remove top repeated noise marker from capture path.",
            "2. Promote one missed high-signal pattern into explicit trigger phrase.",
            "3. Review dedupe suppressions and lower generic memory replay where safe.",
        ]
    )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    snapshot = build_snapshot(window_hours=24)
    write_outputs(snapshot)
    out = {
        "grade": _snapshot_grade(snapshot),
        "retrieval_guardrails": _retrieval_guardrails(snapshot),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
