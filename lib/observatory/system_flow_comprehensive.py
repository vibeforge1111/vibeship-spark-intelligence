"""Generate a comprehensive, human-readable Spark flow reverse engineering page."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import spark_dir

_SPARK_DIR = spark_dir()
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None


def _read_jsonl(path: Path, max_rows: int = 5000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except Exception:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except Exception:
        return []
    if max_rows > 0 and len(rows) > max_rows:
        return rows[-max_rows:]
    return rows


def _format_ts(ts: Any) -> str:
    try:
        value = float(ts or 0.0)
    except Exception:
        value = 0.0
    if value <= 0.0:
        return "-"
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _parse_any_ts(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except Exception:
            pass
        try:
            return float(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
        except Exception:
            return 0.0
    return 0.0


def _preview(value: Any, max_len: int = 180) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _json_snippet(payload: Any, max_len: int = 460) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except Exception:
        text = str(payload)
    text = _preview(text, max_len=max_len)
    return text


def _latest_queue_examples() -> Dict[str, Any]:
    rows = _read_jsonl(_SPARK_DIR / "queue" / "events.jsonl", max_rows=1200)
    if not rows:
        return {"count": 0, "latest": None, "examples": []}
    latest = rows[-1]
    kinds: Dict[str, Dict[str, Any]] = {}
    for row in reversed(rows):
        kind = str(row.get("event_type") or "").strip().lower()
        if not kind or kind in kinds:
            continue
        kinds[kind] = row
        if len(kinds) >= 3:
            break
    return {
        "count": len(rows),
        "latest": latest,
        "examples": list(kinds.values()),
    }


def _latest_pipeline_cycle() -> Dict[str, Any]:
    data = _read_json(_SPARK_DIR / "pipeline_metrics.json")
    if not isinstance(data, list) or not data:
        return {}
    row = data[-1]
    return row if isinstance(row, dict) else {}


def _latest_pending_memory() -> Dict[str, Any]:
    pending = _read_json(_SPARK_DIR / "pending_memory.json")
    if not isinstance(pending, dict):
        return {}
    items = pending.get("items")
    if not isinstance(items, list) or not items:
        return {}
    best: Optional[Dict[str, Any]] = None
    best_score = -1.0
    for row in items:
        if not isinstance(row, dict):
            continue
        try:
            score = float(row.get("score") or 0.0)
        except Exception:
            score = 0.0
        if score >= best_score:
            best = row
            best_score = score
    return best or {}


def _latest_meta_verdict() -> Dict[str, Any]:
    history = _read_json(_SPARK_DIR / "meta_ralph" / "roast_history.json")
    if not isinstance(history, dict):
        return {}
    rows = history.get("history")
    if not isinstance(rows, list) or not rows:
        return {}
    row = rows[-1]
    if not isinstance(row, dict):
        return {}
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    score = result.get("score") if isinstance(result.get("score"), dict) else {}
    return {
        "timestamp": row.get("timestamp"),
        "source": row.get("source"),
        "verdict": result.get("verdict"),
        "total_score": score.get("total"),
        "issues_found": result.get("issues_found") if isinstance(result.get("issues_found"), list) else [],
        "original": result.get("original"),
    }


def _latest_eidos_distillation() -> Dict[str, Any]:
    db = _SPARK_DIR / "eidos.db"
    if not db.exists():
        return {}
    try:
        con = sqlite3.connect(str(db), timeout=2)
        cur = con.cursor()
        cur.execute(
            "SELECT distillation_id, type, statement, confidence, times_retrieved, created_at "
            "FROM distillations ORDER BY rowid DESC LIMIT 1"
        )
        row = cur.fetchone()
        con.close()
        if not row:
            return {}
        return {
            "distillation_id": row[0],
            "type": row[1],
            "statement": row[2],
            "confidence": row[3],
            "times_retrieved": row[4],
            "created_at": row[5],
        }
    except Exception:
        return {}


def _latest_mind_signal() -> Dict[str, Any]:
    hb = _read_json(_SPARK_DIR / "bridge_worker_heartbeat.json")
    mind_state = _read_json(_SPARK_DIR / "mind_sync_state.json")
    out: Dict[str, Any] = {}
    if isinstance(hb, dict):
        stats = hb.get("stats")
        if isinstance(stats, dict):
            mind_sync = stats.get("mind_sync")
            if isinstance(mind_sync, dict):
                out["mind_sync"] = mind_sync
            out["heartbeat_ts"] = hb.get("ts")
    if isinstance(mind_state, dict):
        synced_hashes = mind_state.get("synced_hashes")
        out["synced_hashes_count"] = len(synced_hashes) if isinstance(synced_hashes, list) else 0
        out["mind_last_sync"] = mind_state.get("last_sync")
    return out


def _latest_advisory_examples() -> Dict[str, Any]:
    rows = _read_jsonl(_SPARK_DIR / "advisory_decision_ledger.jsonl", max_rows=3000)
    if not rows:
        return {}
    emitted = None
    blocked = None
    for row in reversed(rows):
        outcome = str(row.get("outcome") or "").strip().lower()
        if emitted is None and outcome == "emitted":
            emitted = row
        if blocked is None and outcome == "blocked":
            blocked = row
        if emitted is not None and blocked is not None:
            break
    return {"latest": rows[-1], "emitted": emitted, "blocked": blocked, "count": len(rows)}


def _latest_feedback_example() -> Dict[str, Any]:
    rows = _read_jsonl(_SPARK_DIR / "advisor" / "implicit_feedback.jsonl", max_rows=2000)
    if not rows:
        return {}
    sig = Counter(str(r.get("signal") or "unknown").strip().lower() for r in rows)
    return {
        "latest": rows[-1],
        "rows": len(rows),
        "signals": dict(sig),
    }


def _latest_promotion_example() -> Dict[str, Any]:
    rows = _read_jsonl(_SPARK_DIR / "promotion_log.jsonl", max_rows=1000)
    if not rows:
        return {}
    recent = rows[-3:]
    result_counts = Counter(str(r.get("result") or "unknown").strip().lower() for r in rows)
    return {
        "latest": rows[-1],
        "recent": recent,
        "result_counts": dict(result_counts),
        "rows": len(rows),
    }


def _suppression_snapshot_24h() -> Dict[str, Any]:
    rows = _read_jsonl(_SPARK_DIR / "advisory_decision_ledger.jsonl", max_rows=9000)
    if not rows:
        return {}
    cutoff = time.time() - 86400.0
    buckets = Counter()
    reasons = Counter()
    outcomes = Counter()
    for row in rows:
        ts = _parse_any_ts(row.get("ts"))
        if ts > 0.0 and ts < cutoff:
            continue
        outcome = str(row.get("outcome") or "unknown").strip().lower() or "unknown"
        outcomes[outcome] += 1
        for entry in row.get("suppressed_reasons") or []:
            if not isinstance(entry, dict):
                continue
            reason = str(entry.get("reason") or "").strip()
            try:
                count = max(1, int(entry.get("count") or 1))
            except Exception:
                count = 1
            if not reason:
                continue
            reasons[reason] += count
            low = reason.lower()
            if "shown " in low and "ttl" in low:
                buckets["shown_ttl"] += count
            elif "global_dedupe" in low:
                buckets["global_dedupe"] += count
            elif "budget exhausted" in low:
                buckets["budget_exhausted"] += count
            elif "fallback_budget" in low or "fallback budget" in low:
                buckets["fallback_budget"] += count
            elif "on cooldown" in low:
                buckets["tool_cooldown"] += count
            elif "phase=" in low or "exploration phase" in low:
                buckets["context_phase_guard"] += count
            else:
                buckets["other"] += count
        for entry in row.get("suppressed") or []:
            if not isinstance(entry, dict):
                continue
            reason = str(entry.get("reason") or "").strip().lower()
            if reason == "text_sig" or reason == "advice_id":
                buckets["global_dedupe"] += 1
                reasons[f"global_dedupe:{reason}"] += 1
    return {
        "outcomes": dict(outcomes),
        "buckets": dict(buckets),
        "top_reasons": reasons.most_common(8),
    }


def _strengths_gaps(data: Dict[int, Dict[str, Any]], suppression: Dict[str, Any]) -> Dict[str, List[str]]:
    strengths: List[str] = []
    gaps: List[str] = []

    queue_pending = int((data.get(2) or {}).get("estimated_pending", 0) or 0)
    if queue_pending < 5000:
        strengths.append(f"Queue depth is under control (~{queue_pending} pending).")
    else:
        gaps.append(f"Queue depth is elevated (~{queue_pending} pending), increasing delay risk.")

    pipeline_ts = _parse_any_ts((data.get(3) or {}).get("last_cycle_ts"))
    if pipeline_ts > 0:
        age = max(0.0, time.time() - pipeline_ts)
        if age <= 300:
            strengths.append(f"Pipeline cycle is fresh (last cycle {int(age)}s ago).")
        else:
            gaps.append(f"Pipeline appears stale (last cycle {int(age)}s ago).")
    else:
        gaps.append("Pipeline freshness cannot be confirmed from state.")

    advisory = data.get(8) or {}
    emit_rate = float(advisory.get("decision_emit_rate", 0.0) or 0.0)
    follow_rate = float(advisory.get("feedback_follow_rate", 0.0) or 0.0)
    if follow_rate >= 60.0:
        strengths.append(f"Implicit follow rate is strong ({follow_rate:.1f}%).")
    if emit_rate < 25.0:
        gaps.append(f"Decision emit rate is relatively low ({emit_rate:.1f}%), indicating possible over-suppression.")

    meta = data.get(5) or {}
    pass_rate = float(meta.get("pass_rate", 0.0) or 0.0)
    if pass_rate >= 20.0:
        strengths.append(f"Meta-Ralph quality pass rate is healthy enough ({pass_rate:.1f}%).")
    else:
        gaps.append(f"Meta-Ralph quality pass rate is low ({pass_rate:.1f}%), may reduce insight throughput.")

    buckets = suppression.get("buckets") if isinstance(suppression.get("buckets"), dict) else {}
    shown = int(buckets.get("shown_ttl", 0) or 0)
    dedupe = int(buckets.get("global_dedupe", 0) or 0)
    total = sum(int(v or 0) for v in buckets.values())
    if total > 0:
        if shown / total > 0.5:
            gaps.append("Shown TTL suppression dominates the advisory gate; repeated guidance is likely too constrained.")
        if dedupe / total > 0.15:
            gaps.append("Global dedupe suppression remains significant; cross-session repeats are still heavily blocked.")

    return {"strengths": strengths, "gaps": gaps}


def generate_system_flow_comprehensive(data: Dict[int, Dict[str, Any]]) -> str:
    """Generate comprehensive system reverse-engineering narrative with live examples."""
    queue = _latest_queue_examples()
    pipeline = _latest_pipeline_cycle()
    memory = _latest_pending_memory()
    meta = _latest_meta_verdict()
    eidos = _latest_eidos_distillation()
    mind = _latest_mind_signal()
    advisory = _latest_advisory_examples()
    feedback = _latest_feedback_example()
    promotion = _latest_promotion_example()
    suppression = _suppression_snapshot_24h()
    diagnostics_path = _REPO_ROOT / "reports" / "runtime" / "advisory_deep_diagnosis_global_dedupe_tuneable.json"
    diagnostics_exists = diagnostics_path.exists()
    sg = _strengths_gaps(data, suppression)

    lines: List[str] = []
    lines.append("---")
    lines.append("title: System Flow Comprehensive")
    lines.append("tags:")
    lines.append("  - observatory")
    lines.append("  - reverse-engineering")
    lines.append("  - system-flow")
    lines.append("  - diagnostics")
    lines.append("---")
    lines.append("")
    lines.append("# Spark Intelligence Flow - Comprehensive Reverse Engineering")
    lines.append("")
    lines.append(f"> Generated: {_format_ts(time.time())}")
    lines.append("> Purpose: explain the entire intelligence path in plain language, backed by live examples and operational evidence.")
    lines.append("")

    lines.append("## Plain-English System Story")
    lines.append("")
    lines.append("1. Hooks capture user prompts and tool events (`hooks/observe.py`).")
    lines.append("2. Events land in the local queue (`lib/queue.py`) for resilient buffering.")
    lines.append("3. Bridge cycle + pipeline process events into learning signals and derived metrics.")
    lines.append("4. Memory capture identifies high-signal candidate learnings and stores/queues them.")
    lines.append("5. Meta-Ralph quality gate filters weak/noisy learnings before they become intelligence.")
    lines.append("5a. `validate_and_store` is the unified write gate — every cognitive write routes through Meta-Ralph. On Meta-Ralph failure it quarantines AND stores (fail-open).")
    lines.append("5b. **Elevation Transforms** — NEEDS_WORK verdicts go through 12 deterministic text transforms (hedge removal, reasoning injection, etc.) and get re-scored. Trained on 137 Claude pairs.")
    lines.append("6. Cognitive store + EIDOS distillations + chips build reusable intelligence assets.")
    lines.append("6a. **Distillation Refiner** — EIDOS distillations pass through a 5-stage candidate ranking (raw → elevation → structure rewrite → composition → optional LLM) to maximize advisory quality.")
    lines.append("7. Mind sync persists selected insights for cross-session retrieval and recall.")
    lines.append("8. Pre-tool advisory engine retrieves, gates, dedupes, synthesizes, and emits advice.")
    lines.append("9. Post-tool outcomes record implicit feedback and update future advisory effectiveness.")
    lines.append("10. Promotion writes validated insights back into project-facing docs and rules.")
    lines.append("11. **Learning-Systems Bridge** — external systems (e.g., System 26 executive loop) can inject validated insights and propose tuneable changes via `lib/learning_systems_bridge.py`.")
    lines.append("12. **Config Authority** — all modules resolve config through `lib/config_authority.py` with 4-layer deterministic precedence (schema → baseline → runtime → env) and hot-reload.")
    lines.append("")

    lines.append("## Live Example Trail (Recent Runtime)")
    lines.append("")
    lines.append("### 1) Hook -> Queue")
    lines.append(f"- Queue sample count inspected: {queue.get('count', 0)}")
    latest_q = queue.get("latest")
    if isinstance(latest_q, dict):
        lines.append(
            f"- Latest event: `{latest_q.get('event_type')}` at {_format_ts(latest_q.get('timestamp'))}, tool=`{latest_q.get('tool_name') or '-'}`"
        )
        lines.append("```json")
        lines.append(_json_snippet(latest_q))
        lines.append("```")
    else:
        lines.append("- No queue events found.")
    lines.append("")

    lines.append("### 2) Pipeline Processing")
    if pipeline:
        lines.append(
            f"- Last cycle: events_read={pipeline.get('events_read', 0)}, insights_created={(pipeline.get('learning_yield') or {}).get('insights_created', 0)}, backpressure={(pipeline.get('health') or {}).get('backpressure_level', '?')}"
        )
        lines.append("```json")
        lines.append(_json_snippet(pipeline))
        lines.append("```")
    else:
        lines.append("- No pipeline cycle sample available.")
    lines.append("")

    lines.append("### 3) Memory Capture")
    if memory:
        lines.append(
            f"- High-score pending memory: category=`{memory.get('category')}`, score={memory.get('score')}, status=`{memory.get('status')}`"
        )
        lines.append(f"- Example text: {_preview(memory.get('text'), 220)}")
    else:
        lines.append("- No pending memory item found.")
    lines.append("")

    lines.append("### 4) Meta-Ralph Quality Gate")
    if meta:
        lines.append(
            f"- Recent verdict: `{meta.get('verdict')}` from `{meta.get('source')}` at `{meta.get('timestamp')}` (score={meta.get('total_score')})"
        )
        issues = meta.get("issues_found") if isinstance(meta.get("issues_found"), list) else []
        lines.append(f"- Issues found: {', '.join([_preview(x, 80) for x in issues[:3]]) or '-'}")
        lines.append(f"- Original learning snippet: {_preview(meta.get('original'), 180)}")
    else:
        lines.append("- No Meta-Ralph verdict sample found.")
    lines.append("")

    lines.append("### 5) Cognitive Intelligence")
    top = ((data.get(6) or {}).get("top_insights") or [])
    if isinstance(top, list) and top:
        first = top[0] if isinstance(top[0], dict) else {}
        lines.append(
            f"- Top insight key=`{first.get('key')}` category=`{first.get('category')}` reliability={first.get('reliability')}"
        )
        lines.append(f"- Insight snippet: {_preview(first.get('insight'), 180)}")
    else:
        lines.append("- No cognitive top-insight sample available.")
    lines.append("")

    lines.append("### 6) EIDOS Distillation")
    if eidos:
        lines.append(
            f"- Latest distillation id=`{eidos.get('distillation_id')}` type=`{eidos.get('type')}` confidence={eidos.get('confidence')} retrieved={eidos.get('times_retrieved')}"
        )
        lines.append(f"- Statement: {_preview(eidos.get('statement'), 200)}")
    else:
        lines.append("- No EIDOS distillation sample available.")
    lines.append("")

    lines.append("### 7) Mind Sync / Cross-Session Memory")
    if mind:
        lines.append(f"- Mind synced hashes tracked: {mind.get('synced_hashes_count', 0)}")
        lines.append(f"- Heartbeat timestamp: {_format_ts(mind.get('heartbeat_ts'))}")
        if isinstance(mind.get("mind_sync"), dict):
            lines.append(f"- Mind sync sample: `{_json_snippet(mind.get('mind_sync'), 220)}`")
    else:
        lines.append("- No mind sync signal found in bridge heartbeat/state.")
    lines.append("")

    lines.append("### 8) Advisory Emission Decisioning")
    if advisory:
        lines.append(f"- Ledger rows inspected: {advisory.get('count', 0)}")
        emitted = advisory.get("emitted")
        blocked = advisory.get("blocked")
        if isinstance(emitted, dict):
            lines.append(
                f"- Emitted example: tool=`{emitted.get('tool')}`, route=`{emitted.get('route')}`, selected={emitted.get('selected_ids')}"
            )
            lines.append(f"  text: {_preview(emitted.get('emitted_text_preview'), 180)}")
        if isinstance(blocked, dict):
            lines.append(
                f"- Blocked example: tool=`{blocked.get('tool')}`, stage=`{blocked.get('stage')}`, reasons=`{_preview(blocked.get('suppressed_reasons'), 160)}`"
            )
    else:
        lines.append("- No advisory ledger examples available.")
    lines.append("")

    lines.append("### 9) Implicit Feedback")
    if feedback:
        lines.append(f"- Feedback rows inspected: {feedback.get('rows', 0)}")
        lines.append(f"- Signal mix: {feedback.get('signals')}")
        latest_fb = feedback.get("latest")
        if isinstance(latest_fb, dict):
            lines.append(
                f"- Latest feedback: tool=`{latest_fb.get('tool')}`, signal=`{latest_fb.get('signal')}`, success={latest_fb.get('success')}, latency_s={latest_fb.get('latency_s')}"
            )
    else:
        lines.append("- No implicit feedback sample found.")
    lines.append("")

    lines.append("### 10) Promotion / System-Level Learning Output")
    if promotion:
        lines.append(f"- Promotion log rows inspected: {promotion.get('rows', 0)}")
        lines.append(f"- Result distribution: {promotion.get('result_counts')}")
        recent_rows = promotion.get("recent")
        if isinstance(recent_rows, list) and recent_rows:
            for row in recent_rows:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    f"- `{row.get('ts')}` key=`{_preview(row.get('key'), 48)}` target=`{row.get('target')}` result=`{row.get('result')}`"
                )
    else:
        lines.append("- No promotion examples found.")
    lines.append("")

    lines.append("## Strengths We Have (Evidence-Based)")
    lines.append("")
    if sg["strengths"]:
        for row in sg["strengths"]:
            lines.append(f"- {row}")
    else:
        lines.append("- No clear strengths surfaced from current telemetry sample.")
    lines.append("")

    lines.append("## Gaps / Risks We Should Address")
    lines.append("")
    lines.append("| Gap | Why it matters | Live evidence |")
    lines.append("|---|---|---|")
    if sg["gaps"]:
        for row in sg["gaps"]:
            lines.append(f"| {row} | Advisory quality and operator trust can degrade. | Runtime observatory sample |")
    else:
        lines.append("| No high-priority gaps detected from current sample | Continue monitoring | Runtime observatory sample |")
    lines.append("")

    lines.append("## Current Suppression Snapshot (24h)")
    lines.append("")
    lines.append(f"- Outcomes: {suppression.get('outcomes', {})}")
    lines.append(f"- Buckets: {suppression.get('buckets', {})}")
    top_reasons = suppression.get("top_reasons")
    if isinstance(top_reasons, list) and top_reasons:
        lines.append("- Top reasons:")
        for reason, count in top_reasons[:8]:
            lines.append(f"  - {reason}: {count}")
    lines.append("")

    lines.append("## Things We Gotta Work On Next")
    lines.append("")
    lines.append("1. Reduce over-suppression from shown TTL while preserving anti-spam controls.")
    lines.append("2. Make per-call emission budget adaptive for high-signal bundles.")
    lines.append("3. Tune cooldowns by tool family and phase instead of one-size-fits-all.")
    lines.append("4. Add emit-rate floor alerts when follow-rate stays high but emissions drop.")
    lines.append("5. Decide prefetch strategy (enable with metrics, or simplify/remove inactive complexity).")
    lines.append("")
    lines.append("### Gaps Closed by Intelligence Flow Evolution")
    lines.append("")
    lines.append("- **Unified write path**: 8 bypass paths closed via `validate_and_store` — all cognitive writes now routed through Meta-Ralph.")
    lines.append("- **Fallback budget**: Quick/packet fallback emissions rate-limited (`fallback_budget_cap=1`, `window=5`).")
    lines.append("- **Auto-tuner bounds**: Clamped from [0.2, 3.0] to [0.8, 1.1] on load, preventing runaway boosts.")
    lines.append("- **JSONL rotation race**: Atomic single-handle rotation prevents lost appends during concurrent writes.")
    lines.append("- **Advisory reorder**: Cheap checks first in `on_pre_tool()` (safety, text repeat, budget before retrieval).")
    lines.append("")

    lines.append("## Linked Docs")
    lines.append("")
    lines.append("- [[advisory_reverse_engineering|Advisory Reverse Engineering]]")
    lines.append("- [[stages/05-meta-ralph|Stage 5 - Meta-Ralph]] (includes Elevation Transforms)")
    lines.append("- [[stages/07-eidos|Stage 7 - EIDOS]] (includes Distillation Refiner)")
    lines.append("- [[stages/08-advisory|Stage 8 - Advisory]]")
    lines.append("- [[stages/12-tuneables|Stage 12 - Tuneables]] (includes Config Authority)")
    lines.append("- [[system_flow_operator_playbook|Operator Playbook]] (includes CLI lifecycle commands)")
    lines.append("- [[../Advisory Implementation Tasks|Advisory Implementation Tasks]]")
    if diagnostics_exists:
        lines.append("- Runtime diagnosis exists in repo: `reports/runtime/advisory_deep_diagnosis_global_dedupe_tuneable.json`")
    lines.append("")

    return "\n".join(lines)
