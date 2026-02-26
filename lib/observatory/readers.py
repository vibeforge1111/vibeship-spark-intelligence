"""Read-only data loaders for all 12 pipeline stages.

Each reader returns a dict of metrics from ~/.spark/ state files.
No imports from pipeline modules — pure file I/O, zero side effects.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import spark_dir

_SD = spark_dir()


def _load_json(path: Path) -> dict | list | None:
    """Load a JSON file, return None on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _tail_jsonl(path: Path, n: int = 20) -> list[dict]:
    """Read the last N lines of a JSONL file efficiently."""
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        if size == 0:
            return []
        # For small files, just read all
        if size < 500_000:
            lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            results = []
            for line in lines[-n:]:
                try:
                    results.append(json.loads(line))
                except Exception:
                    pass
            return results
        # For large files, seek from end
        with open(path, "rb") as f:
            f.seek(max(0, size - 100_000))  # read last ~100KB
            chunk = f.read().decode("utf-8", errors="replace")
        lines = chunk.strip().splitlines()
        # First line may be partial, skip it
        if len(lines) > 1:
            lines = lines[1:]
        results = []
        for line in lines[-n:]:
            try:
                results.append(json.loads(line))
            except Exception:
                pass
        return results
    except Exception:
        return []


def _count_jsonl(path: Path) -> int:
    """Estimate line count of a JSONL file from file size."""
    if not path.exists():
        return 0
    try:
        size = path.stat().st_size
        if size == 0:
            return 0
        if size < 200_000:
            return len(path.read_text(encoding="utf-8", errors="replace").strip().splitlines())
        # Sample 10 lines from start to estimate avg line size
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            sample_lines = []
            for i, line in enumerate(f):
                if i >= 10:
                    break
                sample_lines.append(line)
        if not sample_lines:
            return 0
        avg_line = sum(len(line) for line in sample_lines) / len(sample_lines)
        if avg_line <= 0:
            return 0
        return int(size / avg_line)
    except Exception:
        return 0


def _file_mtime(path: Path) -> float | None:
    """Return mtime of a file, or None."""
    try:
        return path.stat().st_mtime if path.exists() else None
    except Exception:
        return None


def _file_size(path: Path) -> int:
    """Return file size in bytes, or 0."""
    try:
        return path.stat().st_size if path.exists() else 0
    except Exception:
        return 0


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


# ── Stage 1: Event Capture ──────────────────────────────────────────

def read_event_capture() -> dict[str, Any]:
    d: dict[str, Any] = {"stage": 1, "name": "Event Capture"}
    # Bridge worker heartbeat
    hb = _load_json(_SD / "bridge_worker_heartbeat.json") or {}
    d["last_cycle_ts"] = hb.get("last_cycle_ts") or hb.get("ts")
    d["errors"] = hb.get("errors", [])
    d["context_updated"] = hb.get("context_updated", False)
    # Scheduler heartbeat
    sh = _load_json(_SD / "scheduler_heartbeat.json") or {}
    d["scheduler_ts"] = sh.get("ts") or sh.get("last_ts")
    d["scheduler_running"] = sh.get("running", False)
    # Watchdog
    wd = _load_json(_SD / "watchdog_state.json") or {}
    d["watchdog_status"] = wd.get("status", "unknown")
    d["watchdog_ts"] = wd.get("last_check_ts") or wd.get("ts")
    return d


# ── Stage 2: Queue ──────────────────────────────────────────────────

def read_queue() -> dict[str, Any]:
    d: dict[str, Any] = {"stage": 2, "name": "Queue"}
    qs = _load_json(_SD / "queue" / "state.json") or {}
    d["head_bytes"] = qs.get("head_bytes", 0)
    events_path = _SD / "queue" / "events.jsonl"
    d["events_file_size"] = _file_size(events_path)
    d["estimated_pending"] = _count_jsonl(events_path)
    d["events_mtime"] = _file_mtime(events_path)
    overflow = _SD / "queue" / "events.overflow.jsonl"
    d["overflow_exists"] = overflow.exists()
    d["overflow_size"] = _file_size(overflow)
    return d


# ── Stage 3: Pipeline ───────────────────────────────────────────────

def read_pipeline() -> dict[str, Any]:
    d: dict[str, Any] = {"stage": 3, "name": "Pipeline"}
    ps = _load_json(_SD / "pipeline_state.json") or {}
    d["total_events_processed"] = ps.get("total_events_processed", 0)
    d["total_insights_created"] = ps.get("total_insights_created", 0)
    d["last_processing_rate"] = ps.get("last_processing_rate", 0)
    d["last_batch_size"] = ps.get("last_batch_size", 0)
    d["consecutive_empty_cycles"] = ps.get("consecutive_empty_cycles", 0)
    d["last_cycle_ts"] = ps.get("last_cycle_ts")
    # Recent cycles from pipeline_metrics.json
    metrics = _load_json(_SD / "pipeline_metrics.json")
    if isinstance(metrics, list):
        d["recent_cycles"] = metrics[-5:]  # last 5 cycles
    else:
        d["recent_cycles"] = []
    return d


# ── Stage 4: Memory Capture ─────────────────────────────────────────

def read_memory_capture(max_recent: int = 10) -> dict[str, Any]:
    d: dict[str, Any] = {"stage": 4, "name": "Memory Capture"}
    mcs = _load_json(_SD / "memory_capture_state.json") or {}
    d["last_capture_ts"] = mcs.get("last_ts")
    pending = _load_json(_SD / "pending_memory.json") or {}
    items = pending.get("items", []) if isinstance(pending, dict) else []
    d["pending_count"] = len(items)
    d["recent_pending"] = []
    for item in items[:max_recent]:
        d["recent_pending"].append({
            "text": (item.get("text", "")[:120] + "...") if len(item.get("text", "")) > 120 else item.get("text", ""),
            "category": item.get("category", "?"),
            "score": item.get("score", 0),
            "status": item.get("status", "?"),
        })
    # Category distribution
    cats: dict[str, int] = {}
    for item in items:
        c = item.get("category", "unknown")
        cats[c] = cats.get(c, 0) + 1
    d["category_distribution"] = cats
    return d


# ── Stage 5: Meta-Ralph ─────────────────────────────────────────────

def read_meta_ralph(max_recent: int = 15) -> dict[str, Any]:
    d: dict[str, Any] = {"stage": 5, "name": "Meta-Ralph"}
    # Learnings store — count keys
    ls = _load_json(_SD / "meta_ralph" / "learnings_store.json") or {}
    d["learnings_count"] = len(ls) if isinstance(ls, dict) else 0
    # Outcome tracking
    ot = _load_json(_SD / "meta_ralph" / "outcome_tracking.json") or {}
    d["outcome_tracking"] = ot
    d["outcomes_total_tracked"] = ot.get("total_tracked", 0)
    d["outcomes_acted_on"] = ot.get("acted_on", 0)
    d["outcomes_good"] = ot.get("good_outcomes", 0)
    d["outcomes_bad"] = ot.get("bad_outcomes", 0)
    d["outcomes_effectiveness"] = round(
        ot.get("good_outcomes", 0) / max(ot.get("acted_on", 0), 1) * 100, 1
    )
    # Roast history — recent verdicts
    rh = _load_json(_SD / "meta_ralph" / "roast_history.json") or {}
    history = rh.get("history", []) if isinstance(rh, dict) else []
    total_roasted = 0
    if isinstance(rh, dict):
        total_roasted = _as_int(rh.get("total_roasted"), 0)
    d["total_roasted"] = max(total_roasted, len(history))
    recent = history[-max_recent:] if history else []
    d["recent_verdicts"] = []
    verdicts: dict[str, int] = {}
    # Dimension averages across all history
    dims = ["actionability", "novelty", "reasoning", "specificity", "outcome_linked", "ethics"]
    dim_sums: dict[str, float] = {dim: 0.0 for dim in dims}
    dim_counts: dict[str, int] = {dim: 0 for dim in dims}
    total_score_sum = 0.0
    total_score_count = 0
    for entry in history:
        r = entry.get("result", {})
        v = r.get("verdict", "unknown")
        verdicts[v] = verdicts.get(v, 0) + 1
        score = r.get("score", {})
        if isinstance(score, dict):
            for dim in dims:
                val = score.get(dim)
                if isinstance(val, (int, float)):
                    dim_sums[dim] += val
                    dim_counts[dim] += 1
            total = score.get("total")
            if isinstance(total, (int, float)):
                total_score_sum += total
                total_score_count += 1
    quality_passed = verdicts.get("quality", 0)
    if isinstance(rh, dict):
        quality_passed = _as_int(rh.get("quality_passed"), quality_passed)
    d["quality_passed"] = quality_passed
    d["verdict_distribution"] = verdicts
    d["dimension_averages"] = {
        dim: round(dim_sums[dim] / max(dim_counts[dim], 1), 2) for dim in dims
    }
    d["avg_total_score"] = round(total_score_sum / max(total_score_count, 1), 2)
    d["pass_rate"] = round(d["quality_passed"] / max(d["total_roasted"], 1) * 100, 1)
    # Weak dimensions (below 1.0 avg or lowest 2)
    sorted_dims = sorted(d["dimension_averages"].items(), key=lambda x: x[1])
    d["weak_dimensions"] = [dim for dim, avg in sorted_dims[:2] if avg < 1.5]
    for entry in recent:
        r = entry.get("result", {})
        d["recent_verdicts"].append({
            "ts": entry.get("timestamp", "?"),
            "source": entry.get("source", "?"),
            "verdict": r.get("verdict", "?"),
            "score": r.get("score", {}).get("total", 0) if isinstance(r.get("score"), dict) else 0,
            "issues": r.get("issues_found", [])[:2],
        })
    return d


# ── Stage 6: Cognitive Learner ───────────────────────────────────────

def read_cognitive(max_recent: int = 15) -> dict[str, Any]:
    d: dict[str, Any] = {"stage": 6, "name": "Cognitive Learner"}
    ci = _load_json(_SD / "cognitive_insights.json") or {}
    if not isinstance(ci, dict):
        ci = {}
    d["total_insights"] = len(ci)
    # Category distribution
    cats: dict[str, int] = {}
    top_reliability: list[dict] = []
    for key, val in ci.items():
        if not isinstance(val, dict):
            continue
        cat = val.get("category", "unknown")
        cats[cat] = cats.get(cat, 0) + 1
        top_reliability.append({
            "key": key[:60],
            "category": cat,
            "reliability": val.get("reliability", 0),
            "validations": val.get("times_validated", 0),
            "promoted": val.get("promoted", False),
            "insight": (val.get("insight", "")[:100] + "...") if len(val.get("insight", "")) > 100 else val.get("insight", ""),
        })
    d["category_distribution"] = cats
    # Sort by reliability desc, take top N
    top_reliability.sort(key=lambda x: (-x["reliability"], -x["validations"]))
    d["top_insights"] = top_reliability[:max_recent]
    d["mtime"] = _file_mtime(_SD / "cognitive_insights.json")
    return d


# ── Stage 7: EIDOS ──────────────────────────────────────────────────

def read_eidos() -> dict[str, Any]:
    d: dict[str, Any] = {"stage": 7, "name": "EIDOS"}
    db_path = _SD / "eidos.db"
    d["db_exists"] = db_path.exists()
    d["db_size"] = _file_size(db_path)
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path), timeout=2)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            # Count episodes
            try:
                cur.execute("SELECT COUNT(*) FROM episodes")
                d["episodes"] = cur.fetchone()[0]
            except Exception:
                d["episodes"] = 0
            # Count steps
            try:
                cur.execute("SELECT COUNT(*) FROM steps")
                d["steps"] = cur.fetchone()[0]
            except Exception:
                d["steps"] = 0
            # Count distillations
            try:
                cur.execute("SELECT COUNT(*) FROM distillations")
                d["distillations"] = cur.fetchone()[0]
            except Exception:
                d["distillations"] = 0
            # Recent distillations
            try:
                cur.execute("SELECT * FROM distillations ORDER BY rowid DESC LIMIT 10")
                rows = cur.fetchall()
                d["recent_distillations"] = [dict(r) for r in rows]
            except Exception:
                d["recent_distillations"] = []

            # Advisory quality + feedback observability.
            d["advisory_quality_histogram"] = []
            d["feedback_loop"] = {
                "used_distillations": 0,
                "total_uses": 0,
                "total_helped": 0,
                "effectiveness_pct": 0.0,
            }
            d["suppression_breakdown"] = {
                "pass_transformer": 0,
                "fail_suppressed": 0,
                "fail_score_floor": 0,
                "unknown_quality": 0,
                "archived_suppressed": 0,
                "archived_score_floor": 0,
            }
            try:
                cur.execute(
                    "SELECT advisory_quality, times_used, times_helped FROM distillations"
                )
                all_rows = cur.fetchall()

                used_distillations = 0
                total_uses = 0
                total_helped = 0
                scores: list[float] = []

                for row in all_rows:
                    times_used = int(row["times_used"] or 0)
                    times_helped = int(row["times_helped"] or 0)
                    if times_used > 0:
                        used_distillations += 1
                    total_uses += times_used
                    total_helped += times_helped

                    aq_raw = row["advisory_quality"]
                    aq = None
                    if isinstance(aq_raw, str) and aq_raw.strip():
                        try:
                            aq = json.loads(aq_raw)
                        except Exception:
                            aq = None
                    elif isinstance(aq_raw, dict):
                        aq = aq_raw

                    if not isinstance(aq, dict):
                        d["suppression_breakdown"]["unknown_quality"] += 1
                        continue

                    unified = float(aq.get("unified_score", 0.0) or 0.0)
                    suppressed = bool(aq.get("suppressed", False))
                    scores.append(unified)

                    if suppressed:
                        d["suppression_breakdown"]["fail_suppressed"] += 1
                    elif unified < 0.35:
                        d["suppression_breakdown"]["fail_score_floor"] += 1
                    else:
                        d["suppression_breakdown"]["pass_transformer"] += 1

                bins = [
                    ("0.0-0.2", 0.0, 0.2),
                    ("0.2-0.4", 0.2, 0.4),
                    ("0.4-0.6", 0.4, 0.6),
                    ("0.6-0.8", 0.6, 0.8),
                    ("0.8-1.0", 0.8, 1.01),
                ]
                histogram = []
                for label, lo, hi in bins:
                    count = sum(1 for s in scores if lo <= s < hi)
                    histogram.append({"bucket": label, "count": count})
                d["advisory_quality_histogram"] = histogram

                effectiveness = (100.0 * total_helped / max(total_uses, 1)) if total_uses else 0.0
                d["feedback_loop"] = {
                    "used_distillations": used_distillations,
                    "total_uses": total_uses,
                    "total_helped": total_helped,
                    "effectiveness_pct": round(effectiveness, 1),
                }
            except Exception:
                pass

            try:
                cur.execute(
                    "SELECT archive_reason, COUNT(*) AS c FROM distillations_archive GROUP BY archive_reason"
                )
                for row in cur.fetchall():
                    reason = str(row["archive_reason"] or "")
                    count = int(row["c"] or 0)
                    if reason.startswith("suppressed:"):
                        d["suppression_breakdown"]["archived_suppressed"] += count
                    elif reason.startswith("unified_score_below_floor:"):
                        d["suppression_breakdown"]["archived_score_floor"] += count
            except Exception:
                pass
            conn.close()
        except Exception:
            d["episodes"] = 0
            d["steps"] = 0
            d["distillations"] = 0
            d["recent_distillations"] = []
            d["advisory_quality_histogram"] = []
            d["feedback_loop"] = {}
            d["suppression_breakdown"] = {}
    else:
        d["episodes"] = 0
        d["steps"] = 0
        d["distillations"] = 0
        d["recent_distillations"] = []
        d["advisory_quality_histogram"] = []
        d["feedback_loop"] = {}
        d["suppression_breakdown"] = {}
    # Active episodes/steps
    ae = _load_json(_SD / "eidos_active_episodes.json") or {}
    d["active_episodes"] = len(ae) if isinstance(ae, dict) else 0
    ast = _load_json(_SD / "eidos_active_steps.json") or {}
    d["active_steps"] = len(ast) if isinstance(ast, dict) else 0

    # Distillation curriculum snapshot metrics.
    curriculum_latest = _load_json(_SD / "eidos_curriculum_latest.json")
    curriculum_stats = {}
    if isinstance(curriculum_latest, dict):
        stats = curriculum_latest.get("stats")
        if isinstance(stats, dict):
            curriculum_stats = stats

    severity = curriculum_stats.get("severity", {}) if isinstance(curriculum_stats.get("severity"), dict) else {}
    d["curriculum_rows_scanned"] = _as_int(curriculum_stats.get("rows_scanned"), 0)
    d["curriculum_cards_generated"] = _as_int(curriculum_stats.get("cards_generated"), 0)
    d["curriculum_high"] = _as_int(severity.get("high"), 0)
    d["curriculum_medium"] = _as_int(severity.get("medium"), 0)
    d["curriculum_low"] = _as_int(severity.get("low"), 0)
    d["curriculum_gaps"] = curriculum_stats.get("gaps", {}) if isinstance(curriculum_stats.get("gaps"), dict) else {}

    history_rows = _tail_jsonl(_SD / "eidos_curriculum_history.jsonl", 60)
    d["curriculum_history_points"] = len(history_rows)
    if history_rows:
        first_high = _as_int(history_rows[0].get("high"), d["curriculum_high"])
        d["curriculum_high_delta"] = d["curriculum_high"] - first_high
    else:
        d["curriculum_high_delta"] = 0
    return d


# ── Stage 8: Advisory ───────────────────────────────────────────────

def read_advisory(max_recent: int = 15) -> dict[str, Any]:
    d: dict[str, Any] = {"stage": 8, "name": "Advisory"}
    # Effectiveness summary
    eff = _load_json(_SD / "advisor" / "effectiveness.json") or {}
    d["total_advice_given"] = eff.get("total_advice_given", 0)
    d["total_followed"] = eff.get("total_followed", 0)
    d["total_helpful"] = eff.get("total_helpful", 0)
    d["followed_rate"] = round(d["total_followed"] / max(d["total_advice_given"], 1) * 100, 1)
    d["by_source"] = eff.get("by_source", {})
    # Metrics
    metrics = _load_json(_SD / "advisor" / "metrics.json") or {}
    d["cognitive_helpful_rate"] = metrics.get("cognitive_helpful_rate", 0)
    d["cognitive_helpful_known"] = metrics.get("cognitive_helpful_known", 0)
    d["last_updated"] = metrics.get("last_updated", "?")
    # Recent advice log entries
    d["recent_advice"] = _tail_jsonl(_SD / "advisor" / "advice_log.jsonl", max_recent)
    # Recent decision ledger
    d["recent_decisions"] = _tail_jsonl(_SD / "advisory_decision_ledger.jsonl", max_recent)
    # Decision ledger aggregates
    all_decisions = _tail_jsonl(_SD / "advisory_decision_ledger.jsonl", 200)
    d_outcomes: dict[str, int] = {}
    for entry in all_decisions:
        outcome = entry.get("outcome", "?")
        d_outcomes[outcome] = d_outcomes.get(outcome, 0) + 1
    d["decision_outcomes"] = d_outcomes
    d["decision_emit_rate"] = round(
        d_outcomes.get("emitted", 0) / max(len(all_decisions), 1) * 100, 1
    )
    d["decision_total"] = len(all_decisions)
    # Total advice log count
    d["advice_log_count"] = _count_jsonl(_SD / "advisor" / "advice_log.jsonl")
    # Implicit feedback summary
    feedback_path = _SD / "advisor" / "implicit_feedback.jsonl"
    fb_entries = _tail_jsonl(feedback_path, 200)
    fb_followed = sum(1 for e in fb_entries if e.get("signal") in {"followed", "helpful"})
    fb_ignored = sum(1 for e in fb_entries if e.get("signal") == "ignored")
    fb_unhelpful = sum(1 for e in fb_entries if e.get("signal") == "unhelpful")
    fb_not_followed = sum(1 for e in fb_entries if e.get("signal") == "not_followed")
    fb_eval_total = fb_followed + fb_ignored + fb_unhelpful + fb_not_followed
    d["feedback_total"] = len(fb_entries)
    d["feedback_followed"] = fb_followed
    d["feedback_ignored"] = fb_ignored
    d["feedback_unhelpful"] = fb_unhelpful
    d["feedback_not_followed"] = fb_not_followed
    d["feedback_eval_total"] = fb_eval_total
    d["feedback_follow_rate"] = round(
        fb_followed / max(fb_eval_total, 1) * 100, 1
    )
    # Per-tool follow rates
    tool_fb: dict[str, dict[str, int]] = {}
    for e in fb_entries:
        tool = e.get("tool", "?")
        if tool not in tool_fb:
            tool_fb[tool] = {
                "followed": 0,
                "ignored": 0,
                "unhelpful": 0,
                "not_followed": 0,
                "total": 0,
            }
        tool_fb[tool]["total"] += 1
        signal = e.get("signal")
        if signal in {"followed", "helpful"}:
            tool_fb[tool]["followed"] += 1
        elif signal == "ignored":
            tool_fb[tool]["ignored"] += 1
        elif signal == "unhelpful":
            tool_fb[tool]["unhelpful"] += 1
        elif signal == "not_followed":
            tool_fb[tool]["not_followed"] += 1
    d["feedback_by_tool"] = tool_fb

    # Calibrated helpfulness stream from deterministic watcher.
    helpfulness_summary = _load_json(_SD / "advisor" / "helpfulness_summary.json") or {}
    d["helpfulness_summary"] = helpfulness_summary if isinstance(helpfulness_summary, dict) else {}
    d["recent_helpfulness_events"] = _tail_jsonl(
        _SD / "advisor" / "helpfulness_events.jsonl", max_recent
    )
    return d


# ── Stage 9: Promotion ──────────────────────────────────────────────

def read_promotion(max_recent: int = 20) -> dict[str, Any]:
    d: dict[str, Any] = {"stage": 9, "name": "Promotion"}
    path = _SD / "promotion_log.jsonl"
    d["total_entries"] = _count_jsonl(path)
    d["log_size"] = _file_size(path)
    d["mtime"] = _file_mtime(path)
    recent = _tail_jsonl(path, max_recent)
    d["recent_promotions"] = []
    targets: dict[str, int] = {}
    results: dict[str, int] = {}
    for entry in recent:
        target = entry.get("target", "?")
        result = entry.get("result", "?")
        targets[target] = targets.get(target, 0) + 1
        results[result] = results.get(result, 0) + 1
        d["recent_promotions"].append({
            "ts": entry.get("ts", "?"),
            "key": (entry.get("key", "?")[:60]),
            "target": target,
            "result": result,
            "reason": entry.get("reason", ""),
        })
    d["target_distribution"] = targets
    d["result_distribution"] = results
    return d


# ── Stage 10: Chips ─────────────────────────────────────────────────

def read_chips(max_recent: int = 5) -> dict[str, Any]:
    d: dict[str, Any] = {"stage": 10, "name": "Chips"}
    chips_dir = _SD / "chip_insights"
    d["chips"] = []
    if chips_dir.exists():
        for p in sorted(chips_dir.iterdir()):
            if p.suffix == ".jsonl":
                chip_name = p.stem
                size = _file_size(p)
                mtime = _file_mtime(p)
                count = _count_jsonl(p)
                recent = _tail_jsonl(p, max_recent)
                d["chips"].append({
                    "name": chip_name,
                    "size": size,
                    "mtime": mtime,
                    "count": count,
                    "recent": recent,
                })
            elif p.is_dir():
                # Subdirectory chip (e.g., audio_learning/)
                total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                d["chips"].append({
                    "name": p.name,
                    "size": total,
                    "mtime": _file_mtime(p),
                    "count": sum(1 for _ in p.rglob("*.jsonl")),
                    "recent": [],
                })
    d["total_chips"] = len(d["chips"])
    d["total_size"] = sum(c["size"] for c in d["chips"])
    return d


# ── Stage 11: Predictions ───────────────────────────────────────────

def read_predictions(max_recent: int = 10) -> dict[str, Any]:
    d: dict[str, Any] = {"stage": 11, "name": "Predictions"}
    pred_path = _SD / "predictions.jsonl"
    outcomes_path = _SD / "outcomes.jsonl"
    links_path = _SD / "outcome_links.jsonl"
    d["predictions_count"] = _count_jsonl(pred_path)
    d["predictions_size"] = _file_size(pred_path)
    d["outcomes_count"] = _count_jsonl(outcomes_path)
    d["outcomes_size"] = _file_size(outcomes_path)
    d["links_count"] = _count_jsonl(links_path)
    d["links_size"] = _file_size(links_path)
    d["recent_outcomes"] = _tail_jsonl(outcomes_path, max_recent)
    # Prediction state
    ps = _load_json(_SD / "prediction_state.json") or {}
    d["prediction_state_keys"] = len(ps) if isinstance(ps, dict) else 0
    # Outcome predictor
    op = _load_json(_SD / "outcome_predictor.json") or {}
    d["predictor"] = op
    return d


# ── Stage 12: Tuneables ─────────────────────────────────────────────

def read_tuneables() -> dict[str, Any]:
    d: dict[str, Any] = {"stage": 12, "name": "Tuneables"}
    # Try runtime first, then versioned
    for label, p in [("runtime", _SD / "tuneables.json"),
                     ("versioned", Path(__file__).resolve().parent.parent.parent / "config" / "tuneables.json")]:
        if p.exists():
            data = _load_json(p) or {}
            d["source"] = label
            d["path"] = str(p)
            d["mtime"] = _file_mtime(p)
            d["sections"] = {}
            for section_name, section_data in data.items():
                if isinstance(section_data, dict):
                    d["sections"][section_name] = {
                        "key_count": len(section_data),
                        "keys": list(section_data.keys())[:10],
                    }
            break
    else:
        d["source"] = "none"
        d["sections"] = {}
    return d


# ── Aggregate reader ─────────────────────────────────────────────────

def read_all_stages(max_recent: int = 20) -> dict[int, dict[str, Any]]:
    """Read all 12 stages and return a dict keyed by stage number."""
    return {
        1: read_event_capture(),
        2: read_queue(),
        3: read_pipeline(),
        4: read_memory_capture(max_recent=max_recent),
        5: read_meta_ralph(max_recent=max_recent),
        6: read_cognitive(max_recent=max_recent),
        7: read_eidos(),
        8: read_advisory(max_recent=max_recent),
        9: read_promotion(max_recent=max_recent),
        10: read_chips(max_recent=min(max_recent, 5)),
        11: read_predictions(max_recent=max_recent),
        12: read_tuneables(),
    }
