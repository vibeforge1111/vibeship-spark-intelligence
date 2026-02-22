"""Single-cycle bridge worker execution + heartbeat helpers.

Updated to use the new processing pipeline for adaptive batch sizing,
priority processing, queue consumption, and deep learning extraction.
"""

from __future__ import annotations

import atexit
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, Optional, Tuple

from lib.bridge import update_spark_context
from lib.openclaw_paths import discover_openclaw_workspaces
from lib.memory_capture import process_recent_memory_events
from lib.tastebank import parse_like_message, add_item
from lib.queue import read_recent_events, EventType
from lib.pattern_detection import process_pattern_events
from lib.validation_loop import process_validation_events, process_outcome_validation
from lib.prediction_loop import process_prediction_cycle
from lib.content_learner import learn_from_edit_event
from lib.chips import process_chip_events
from lib.chip_merger import merge_chip_insights
from lib.context_sync import sync_context
from lib.advisory_quarantine import record_quarantine_item
from lib.diagnostics import log_debug
from lib.opportunity_scanner import scan_runtime_opportunities
from lib.runtime_hygiene import cleanup_runtime_artifacts


BRIDGE_HEARTBEAT_FILE = Path.home() / ".spark" / "bridge_worker_heartbeat.json"

# --- OpenClaw notification integration ---
SPARK_OPENCLAW_NOTIFY = os.environ.get("SPARK_OPENCLAW_NOTIFY", "1").strip().lower() not in {
    "0", "false", "no", "off"
}
_NOTIFY_COOLDOWN_S = 300  # 5 minutes
_last_notify_time: float = 0.0
BRIDGE_STEP_TIMEOUT_S = float(os.environ.get("SPARK_BRIDGE_STEP_TIMEOUT_S", "45"))
BRIDGE_DISABLE_TIMEOUTS = os.environ.get("SPARK_BRIDGE_DISABLE_TIMEOUTS", "0").strip().lower() in {
    "1", "true", "yes", "on"
}

# GC is a safety valve, but doing a full collection every cycle is often
# unnecessary overhead once obvious references are cleared.
# Default: collect every 3 cycles. Set SPARK_BRIDGE_GC_EVERY=1 to restore
# previous behavior.
try:
    _BRIDGE_GC_EVERY = int(os.environ.get("SPARK_BRIDGE_GC_EVERY", "3"))
except Exception:
    _BRIDGE_GC_EVERY = 3
_BRIDGE_GC_EVERY = max(1, min(100, _BRIDGE_GC_EVERY))
_BRIDGE_GC_COUNTER = 0


def _premium_tools_enabled() -> bool:
    return str(os.environ.get("SPARK_PREMIUM_TOOLS", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _chips_disabled() -> bool:
    return str(os.environ.get("SPARK_ADVISORY_DISABLE_CHIPS", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _chips_enabled() -> bool:
    if _chips_disabled():
        return False
    if not _premium_tools_enabled():
        return False
    return str(os.environ.get("SPARK_CHIPS_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_float(name: str, default: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        value = default
    return max(lo, min(hi, value))


CHIP_MERGE_MIN_CONFIDENCE = _env_float("SPARK_CHIP_MERGE_MIN_CONFIDENCE", 0.55)
CHIP_MERGE_MIN_QUALITY = _env_float("SPARK_CHIP_MERGE_MIN_QUALITY", 0.55)


# Shared executor to avoid per-step threadpool construction overhead.
# Note: timeouts are "soft"; if a step blocks beyond timeout, the thread may
# remain busy. We use a small pool to allow subsequent steps to proceed.
_STEP_EXECUTOR: Optional[ThreadPoolExecutor] = None
_STEP_EXECUTOR_LOCK = Lock()
_STEP_EXECUTOR_WORKERS = max(2, int(os.environ.get("SPARK_BRIDGE_STEP_EXECUTOR_WORKERS", "4")))


def _shutdown_step_executor() -> None:
    global _STEP_EXECUTOR
    with _STEP_EXECUTOR_LOCK:
        if _STEP_EXECUTOR is None:
            return
        try:
            _STEP_EXECUTOR.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        _STEP_EXECUTOR = None


def _get_step_executor() -> ThreadPoolExecutor:
    global _STEP_EXECUTOR
    with _STEP_EXECUTOR_LOCK:
        if _STEP_EXECUTOR is None:
            _STEP_EXECUTOR = ThreadPoolExecutor(
                max_workers=_STEP_EXECUTOR_WORKERS,
                thread_name_prefix="spark_step",
            )
        return _STEP_EXECUTOR


atexit.register(_shutdown_step_executor)


def _run_step(name: str, fn: Callable[..., Any], *args: Any, timeout_s: Optional[float] = None, **kwargs: Any) -> Tuple[bool, Any, str]:
    """
    Run a bridge sub-step with a soft timeout.

    Returns:
      (ok, result, error_message)
    """
    timeout = BRIDGE_STEP_TIMEOUT_S if timeout_s is None else float(timeout_s)
    if BRIDGE_DISABLE_TIMEOUTS or timeout <= 0:
        try:
            return True, fn(*args, **kwargs), ""
        except Exception as e:
            return False, None, str(e)

    executor = _get_step_executor()
    future = executor.submit(fn, *args, **kwargs)
    try:
        return True, future.result(timeout=timeout), ""
    except FuturesTimeoutError:
        future.cancel()
        return False, None, f"timeout after {timeout:.0f}s"
    except Exception as e:
        return False, None, str(e)


def run_bridge_cycle(
    *,
    query: Optional[str] = None,
    memory_limit: int = 60,
    pattern_limit: int = 200,
) -> Dict[str, Any]:
    """Run one bridge_worker cycle and return stats.

    Uses the new processing pipeline for event consumption and deep learning,
    while keeping all existing subsystems (memory, tastebank, chips, etc.).

    Performance: Uses batch/deferred save mode on CognitiveLearner and
    MetaRalph to avoid writing large JSON files on every individual
    insight/roast (the #1 cause of CPU/memory leakage in the loop).
    """
    # Use lightweight TF-IDF embeddings instead of fastembed/ONNX (which causes 8GB+ RAM spike).
    # TF-IDF hashing: ~0MB overhead, 0.4ms/embed, no model download needed.
    import os
    os.environ.setdefault("SPARK_EMBED_BACKEND", "tfidf")

    # --- Hot-reload tuneables if file changed ---
    try:
        from lib.tuneables_reload import check_and_reload
        check_and_reload()
    except ImportError:
        pass
    except Exception:
        pass

    stats: Dict[str, Any] = {
        "timestamp": time.time(),
        "context_updated": False,
        "memory": {},
        "tastebank_saved": False,
        "pattern_processed": 0,
        "validation": {},
        "outcome_validation": {},
        "prediction": {},
        "content_learned": 0,
        "chips": {},
        "engagement_pulse": {},
        "chip_merge": {},
        "errors": [],
    }

    # --- Enable batch mode on heavy-I/O singletons ---
    # This defers all disk writes until end_batch(), preventing
    # hundreds of 500KB+ read-write cycles per bridge cycle.
    try:
        from lib.cognitive_learner import get_cognitive_learner
        cognitive = get_cognitive_learner()
        cognitive.begin_batch()
    except Exception:
        cognitive = None

    try:
        from lib.meta_ralph import get_meta_ralph
        meta_ralph = get_meta_ralph()
        meta_ralph.begin_batch()
    except Exception:
        meta_ralph = None

    try:
        # --- Context update ---
        ok, _result, error = _run_step("context", update_spark_context, query=query)
        if ok:
            stats["context_updated"] = True
        else:
            stats["errors"].append("context")
            log_debug("bridge_worker", f"context update failed ({error})", None)

        # --- Feedback loop: ingest agent self-reports ---
        try:
            from lib.feedback_loop import ingest_reports
            ok, feedback_stats, error = _run_step("feedback", ingest_reports)
            if ok and feedback_stats:
                stats["feedback"] = feedback_stats
        except Exception as e:
            log_debug("bridge_worker", f"feedback ingestion failed ({e})", None)

        # --- Memory capture ---
        ok, memory_stats, error = _run_step("memory", process_recent_memory_events, limit=memory_limit)
        if ok:
            stats["memory"] = memory_stats or {}
        else:
            stats["errors"].append("memory")
            log_debug("bridge_worker", f"memory capture failed ({error})", None)

        # --- Flush cognitive learner so memory-captured insights hit disk ---
        # Without this, batch mode defers all writes until the very end,
        # and any failure in later steps loses captured memories.
        if cognitive:
            try:
                cognitive.end_batch()
                cognitive.begin_batch()
            except Exception as e:
                log_debug("bridge_worker", f"mid-cycle cognitive flush failed ({e})", None)

        # --- Run the processing pipeline ---
        pipeline_metrics = None
        try:  # keep import error handling separate
            from lib.pipeline import run_processing_cycle
            ok, pipeline_metrics, error = _run_step("pipeline", run_processing_cycle)
            if ok and pipeline_metrics is not None:
                stats["pattern_processed"] = pipeline_metrics.events_processed
                stats["pipeline"] = pipeline_metrics.to_dict()
            else:
                stats["errors"].append("pipeline")
                log_debug("bridge_worker", f"pipeline processing failed ({error})", None)
        except Exception as e:
            stats["errors"].append("pipeline")
            log_debug("bridge_worker", "pipeline processing failed", e)
        # Fallback to old pattern detection if pipeline fails
        if pipeline_metrics is None:
            ok, fallback_count, error = _run_step("patterns_fallback", process_pattern_events, limit=pattern_limit)
            if ok:
                stats["pattern_processed"] = int(fallback_count or 0)
            else:
                stats["errors"].append("patterns_fallback")
                log_debug("bridge_worker", f"fallback pattern detection failed ({error})", None)

        # --- Get events (single source, used by all downstream) ---
        if pipeline_metrics and getattr(pipeline_metrics, "processed_events", None):
            events = pipeline_metrics.processed_events
            # Release reference from metrics to prevent memory accumulation
            pipeline_metrics.processed_events = []
        else:
            events = read_recent_events(40)
            # Fallback: if the queue head advanced to EOF (no active bytes) but the
            # pipeline didn't surface processed_events, downstream systems lose context.
            if not events:
                try:
                    from lib.queue import read_recent_events_raw
                    events = read_recent_events_raw(40)
                except Exception:
                    pass

        # --- Single-pass event classification ---
        # Instead of iterating events 5+ separate times, classify once
        # and build all derived lists in one pass.
        user_prompt_events = []
        edit_write_events = []
        chip_events = []
        project_path = None

        for ev in events:
            et = ev.event_type
            tool = (ev.tool_name or "").strip()

            # Tastebank + cognitive signals: user prompts
            if et == EventType.USER_PROMPT:
                user_prompt_events.append(ev)

            # Content learning + cognitive signals: Edit/Write (case-insensitive)
            if et == EventType.POST_TOOL and tool.lower() in ("edit", "write"):
                # Some adapters put tool_input in payload instead of top-level
                if not ev.tool_input and (ev.data or {}).get("payload", {}).get("tool_input"):
                    ev.tool_input = (ev.data or {}).get("payload", {}).get("tool_input", {})
                edit_write_events.append(ev)

            # Chip events: all events
            chip_events.append({
                "event_type": et.value if hasattr(et, 'value') else str(et),
                "tool_name": ev.tool_name,
                "tool_input": ev.tool_input or {},
                "data": ev.data or {},
                "cwd": (ev.data or {}).get("cwd"),
            })

            # Project path: first cwd found
            if project_path is None:
                cwd = (ev.data or {}).get("cwd")
                if cwd:
                    project_path = str(cwd)

        # --- Tastebank (uses classified user_prompt_events) ---
        try:
            for e in reversed(user_prompt_events[-10:]):
                payload = (e.data or {}).get("payload") or {}
                if payload.get("role") != "user":
                    continue
                txt = str(payload.get("text") or "").strip()
                parsed = parse_like_message(txt)
                if parsed:
                    add_item(**parsed)
                    stats["tastebank_saved"] = True
                    break
        except Exception as e:
            stats["errors"].append("tastebank")
            log_debug("bridge_worker", "tastebank capture failed", e)

        # --- Validation and prediction loops ---
        ok, validation_stats, error = _run_step("validation", process_validation_events, limit=pattern_limit)
        if ok:
            stats["validation"] = validation_stats or {}
        else:
            stats["errors"].append("validation")
            log_debug("bridge_worker", f"validation loop failed ({error})", None)

        # Explicit outcome-linked validation loop (was previously CLI-only).
        ok, outcome_stats, error = _run_step("outcome_validation", process_outcome_validation, limit=pattern_limit)
        if ok:
            stats["outcome_validation"] = outcome_stats or {}
        else:
            stats["errors"].append("outcome_validation")
            log_debug("bridge_worker", f"outcome validation failed ({error})", None)

        ok, prediction_stats, error = _run_step("prediction", process_prediction_cycle, limit=pattern_limit)
        if ok:
            stats["prediction"] = prediction_stats or {}
        else:
            stats["errors"].append("prediction")
            log_debug("bridge_worker", f"prediction loop failed ({error})", None)

        # --- Content learning (uses classified edit_write_events) ---
        try:
            content_count = 0
            for ev in edit_write_events:
                tool_input = ev.tool_input or {}
                payload = (ev.data or {}).get("payload") or {}
                file_path = (
                    tool_input.get("file_path")
                    or tool_input.get("path")
                    or payload.get("file_path")
                    or payload.get("path")
                    or ""
                )
                content = (
                    tool_input.get("new_string")
                    or tool_input.get("content")
                    or payload.get("new_string")
                    or payload.get("content")
                    or ""
                )
                if file_path and content and len(content) > 50:
                    patterns = learn_from_edit_event(file_path, content)
                    if patterns:
                        content_count += len(patterns)
            stats["content_learned"] = content_count
        except Exception as e:
            stats["errors"].append("content_learning")
            log_debug("bridge_worker", "content learning failed", e)

        # --- Cognitive signal extraction (uses classified lists) ---
        try:
            from lib.cognitive_signals import extract_cognitive_signals
            for ev in user_prompt_events:
                payload = (ev.data or {}).get("payload") or {}
                txt = str(payload.get("text") or "").strip()
                if txt and len(txt) >= 10:
                    ev_trace = (ev.data or {}).get("trace_id")
                    ev_source = (ev.data or {}).get("source", "")
                    extract_cognitive_signals(txt, ev.session_id, trace_id=ev_trace, source=ev_source)
            for ev in edit_write_events:
                ti = ev.tool_input or {}
                content = ti.get("content") or ti.get("new_string") or ""
                if content and len(content) > 50:
                    ev_trace = (ev.data or {}).get("trace_id")
                    ev_source = (ev.data or {}).get("source", "")
                    extract_cognitive_signals(content, ev.session_id, trace_id=ev_trace, source=ev_source)
        except Exception as e:
            stats["errors"].append("cognitive_signals")
            log_debug("bridge_worker", "cognitive signal extraction failed", e)

        # --- Wisdom promotion (upgrade high-confidence insights) ---
        try:
            wisdom_stats = cognitive.promote_to_wisdom()
            if wisdom_stats.get("promoted", 0) > 0:
                stats["wisdom_promotions"] = wisdom_stats["promoted"]
        except Exception:
            pass

        # --- Opportunity scanner (self-evolution loop) ---
        def _scan_opportunities() -> Dict[str, Any]:
            scan_session = "default"
            for ev in reversed(events or []):
                sid = str(getattr(ev, "session_id", "") or "").strip()
                if sid:
                    scan_session = sid
                    break
            return scan_runtime_opportunities(
                events or [],
                stats=stats,
                query=query or "",
                session_id=scan_session,
                persist=True,
            )

        ok, opportunity_stats, error = _run_step("opportunity_scanner", _scan_opportunities, timeout_s=15)
        if ok:
            stats["opportunity_scanner"] = opportunity_stats or {}
        else:
            stats["errors"].append("opportunity_scanner")
            # Preserve the error string in heartbeat so operators can trace failures without
            # enabling SPARK_DEBUG (stderr logs aren't always available on Windows services).
            stats["opportunity_scanner"] = {"enabled": True, "error": str(error or "")}
            log_debug("bridge_worker", f"opportunity scanner failed ({error})", None)

        chips_enabled = _chips_enabled()
        if chips_enabled:
            # TODO: Filter chips by project context (game-dev shouldn't fire during spark-checker work)
            # See: spark_reports/day1_fixes_plan.md for details

            # --- Chip processing (uses pre-built chip_events list, capped for speed) ---
            # Cap at 30 events to keep cycle time under 30s (was 60s+ with 67 events x 13 chips)
            capped_chip_events = chip_events[-30:] if len(chip_events) > 30 else chip_events
            ok, chip_stats, error = _run_step("chips", process_chip_events, capped_chip_events, project_path, timeout_s=30)
            if ok:
                stats["chips"] = chip_stats or {}
            else:
                stats["errors"].append("chips")
                log_debug("bridge_worker", f"chip processing failed ({error})", None)

            # --- Engagement Pulse: check for pending snapshots ---
            def _poll_engagement_pulse():
                from lib.engagement_tracker import get_engagement_tracker
                tracker = get_engagement_tracker()
                pending = tracker.get_pending_snapshots()
                tracker.cleanup_old(max_age_days=7)
                return {"pending_snapshots": len(pending), "tracked": len(tracker.tracked)}

            ok, pulse_stats, error = _run_step("engagement_pulse", _poll_engagement_pulse)
            if ok:
                stats["engagement_pulse"] = pulse_stats or {}
            else:
                stats["errors"].append("engagement_pulse")

            # --- Chip merger ---
            ok, merge_stats, error = _run_step(
                "chip_merge",
                merge_chip_insights,
                min_confidence=CHIP_MERGE_MIN_CONFIDENCE,
                min_quality_score=CHIP_MERGE_MIN_QUALITY,
                limit=20,
            )
            if ok:
                stats["chip_merge"] = {
                    "processed": merge_stats.get("processed", 0),
                    "merged": merge_stats.get("merged", 0),
                    "skipped_low_quality": merge_stats.get("skipped_low_quality", 0),
                    "skipped_low_quality_cooldown": merge_stats.get("skipped_low_quality_cooldown", 0),
                    "by_chip": merge_stats.get("by_chip", {}),
                }
            else:
                stats["errors"].append("chip_merge")
                log_debug("bridge_worker", f"chip merge failed ({error})", None)
        else:
            stats["chips"] = {"enabled": False, "reason": "premium chips/features disabled"}
            stats["engagement_pulse"] = {"enabled": False, "reason": "premium chips/features disabled"}
            stats["chip_merge"] = {"enabled": False, "reason": "premium chips/features disabled"}

        # --- Runtime hygiene ---
        ok, hygiene_stats, error = _run_step("runtime_hygiene", cleanup_runtime_artifacts)
        if ok:
            stats["runtime_hygiene"] = hygiene_stats or {}
        else:
            stats["errors"].append("runtime_hygiene")
            log_debug("bridge_worker", f"runtime hygiene failed ({error})", None)

        # --- Context sync ---
        ok, sync_result, error = _run_step("sync", sync_context)
        if ok:
            stats["sync"] = {
                "selected": getattr(sync_result, "selected", 0),
                "promoted": getattr(sync_result, "promoted_selected", 0),
                "targets": getattr(sync_result, "targets", {}),
            }
        else:
            stats["errors"].append("sync")
            log_debug("bridge_worker", f"context sync failed ({error})", None)

        # --- Auto-tuner: periodic source boost optimization ---
        try:
            from lib.auto_tuner import AutoTuner
            tuner = AutoTuner()
            if tuner.should_run():
                # Phase 1: Source boost optimization (existing)
                report = tuner.run()
                # Phase 2: Broader system health recommendations
                health = tuner.measure_system_health()
                recs = tuner.compute_recommendations(health)
                tune_mode = tuner._config.get("mode", "suggest")
                applied = tuner.apply_recommendations(recs, mode=tune_mode)
                stats["auto_tuner"] = {
                    "changes": len(report.changes),
                    "skipped": len(report.skipped),
                    "health_recs": len(recs),
                    "health_applied": len(applied),
                }
        except Exception as e:
            log_debug("bridge_worker", f"auto-tuner failed ({e})", None)

        # --- LLM-powered intelligence (Claude OAuth) ---
        # Only run when we have meaningful data to analyze
        patterns_found = stats.get("pattern_processed", 0)
        insights_merged = (stats.get("chip_merge") or {}).get("merged", 0)

        if patterns_found >= 5 or insights_merged >= 2:
            try:
                from lib.llm import synthesize_advisory, interpret_patterns
                from lib.cognitive_learner import get_cognitive_learner, CognitiveCategory

                # 1. Build rich pattern summaries from actual event data
                pattern_summaries = _build_pattern_summaries(
                    user_prompt_events or [], edit_write_events or [], stats
                )

                # 2. Get filtered, relevant insights (no benchmark noise)
                # Detect dominant source from this batch of events
                _source_counts: dict = {}
                for ev in (user_prompt_events or []) + (edit_write_events or []):
                    s = (ev.data or {}).get("source", "")
                    if s:
                        _source_counts[s] = _source_counts.get(s, 0) + 1
                dominant_source = max(_source_counts, key=_source_counts.get) if _source_counts else ""
                recent_insights = _get_filtered_insights(source=dominant_source)

                if recent_insights or pattern_summaries:
                    advisory = synthesize_advisory(
                        patterns=pattern_summaries,
                        insights=recent_insights[:10],
                    )
                    if advisory:
                        pruned_advisory, dropped = _prune_redundant_advisory(advisory, events or [])
                        if dropped:
                            log_debug("bridge_worker", f"Pruned {dropped} redundant advisory items", None)
                        if pruned_advisory.strip():
                            stats["llm_advisory"] = pruned_advisory
                            # Write advisory to SPARK_CONTEXT for agent consumption
                            _write_llm_advisory(pruned_advisory)
                            log_debug("bridge_worker", f"LLM advisory generated ({len(pruned_advisory)} chars)", None)
                        else:
                            log_debug("bridge_worker", "Skipped advisory after redundancy pruning (no actionable items)", None)

            except Exception as e:
                log_debug("bridge_worker", f"LLM advisory failed ({e})", None)
                stats["errors"].append("llm_advisory")

        # EIDOS distillation (less frequent — every 10th cycle with patterns)
        try:
            from lib.llm import distill_eidos
            cycle_count = stats.get("pipeline", {}).get("health", {}).get("queue_depth_before", 0)
            # Use a simple file counter
            _eidos_counter_file = Path.home() / ".spark" / "eidos_llm_counter.txt"
            counter = 0
            if _eidos_counter_file.exists():
                try:
                    counter = int(_eidos_counter_file.read_text().strip())
                except Exception:
                    counter = 0
            counter += 1
            _eidos_counter_file.write_text(str(counter))

            opp_stats = stats.get("opportunity_scanner") or {}
            opp_promotions = (opp_stats.get("promoted_candidates") or []) if isinstance(opp_stats, dict) else []
            if counter % 5 == 0 and (patterns_found > 0 or opp_promotions):
                # Gather behavioral observations
                observations = []
                if stats.get("llm_advisory"):
                    observations.append(f"Advisory: {stats['llm_advisory'][:200]}")
                chip_stats = stats.get("chips", {})
                if chip_stats.get("insights_captured"):
                    observations.append(f"Captured {chip_stats['insights_captured']} chip insights")
                if stats.get("auto_tuner", {}).get("health_recs"):
                    observations.append(f"Auto-tuner made {stats['auto_tuner']['health_recs']} recommendations")
                for cand in opp_promotions[:3]:
                    obs = str(cand.get("eidos_observation") or cand.get("statement") or "").strip()
                    if obs:
                        observations.append(obs[:240])

                if observations:
                    eidos_update = distill_eidos(observations)
                    if eidos_update:
                        ok, reason = _is_valid_eidos_distillation(eidos_update)
                        if ok:
                            stats["eidos_distillation"] = eidos_update
                            structured = _parse_structured_eidos(eidos_update)
                            if isinstance(structured, dict):
                                kept = [
                                    it for it in (structured.get("insights") or [])
                                    if isinstance(it, dict) and str(it.get("decision", "keep")).lower() == "keep"
                                ]
                                if kept:
                                    top = kept[0]
                                    try:
                                        stats["eidos_priority_top"] = float(top.get("priority_score") or 0.0)
                                    except Exception:
                                        stats["eidos_priority_top"] = 0.0
                                    emo = top.get("emotional_signal") if isinstance(top.get("emotional_signal"), dict) else {}
                                    stats["eidos_emotion_top"] = str(emo.get("type") or "neutral")

                            _append_eidos_update(eidos_update)
                            log_debug("bridge_worker", "EIDOS distillation complete", None)
                        else:
                            stats["eidos_distillation_skipped"] = reason
                            log_debug("bridge_worker", f"EIDOS distillation skipped ({reason})", None)

            # Periodic EIDOS pruning (every 50th cycle)
            if counter % 50 == 0:
                try:
                    from lib.eidos.store import get_store
                    pruned = get_store().prune_distillations()
                    total_pruned = sum(pruned.values())
                    if total_pruned > 0:
                        stats["eidos_pruned"] = pruned
                        log_debug("bridge_worker", f"EIDOS pruned {total_pruned} distillations: {pruned}", None)
                except Exception as prune_err:
                    log_debug("bridge_worker", f"EIDOS pruning failed ({prune_err})", None)
        except Exception as e:
            log_debug("bridge_worker", f"EIDOS distillation failed ({e})", None)

    finally:
        # --- Flush all deferred saves (single write per file) ---
        if cognitive:
            try:
                cognitive.end_batch()
            except Exception as e:
                log_debug("bridge_worker", "cognitive flush failed", e)
        if meta_ralph:
            try:
                meta_ralph.end_batch()
            except Exception as e:
                log_debug("bridge_worker", "meta_ralph flush failed", e)

        # --- Memory cleanup (prevent accumulation across cycles) ---
        # Clear event references to allow GC
        events = None
        user_prompt_events = None
        edit_write_events = None
        chip_events = None
        pipeline_metrics = None
        try:
            # Clear aggregator session pattern cache to prevent unbounded growth
            from lib.pattern_detection.aggregator import get_aggregator
            agg = get_aggregator()
            if hasattr(agg, '_session_patterns'):
                # Keep only last 5 sessions
                keys = list(agg._session_patterns.keys())
                if len(keys) > 5:
                    for k in keys[:-5]:
                        del agg._session_patterns[k]
        except Exception:
            pass
        import gc
        global _BRIDGE_GC_COUNTER
        _BRIDGE_GC_COUNTER += 1
        if _BRIDGE_GC_EVERY <= 1 or (_BRIDGE_GC_COUNTER % _BRIDGE_GC_EVERY) == 0:
            gc.collect()

    # --- OpenClaw notification (event-driven push) ---
    if SPARK_OPENCLAW_NOTIFY:
        _maybe_notify_openclaw(stats)

    # --- Observatory sync (non-critical, best-effort) ---
    try:
        from lib.observatory import maybe_sync_observatory
        maybe_sync_observatory(stats)
    except Exception:
        pass

    return stats


import re

# --- Noise patterns to filter from insights before LLM prompt ---
_INSIGHT_NOISE_PATTERNS = [
    "Strong reasoning on",       # depth forge benchmark scores
    "Weak reasoning on",         # depth forge benchmark scores
    "reasoning on '",            # depth forge benchmark scores
    "depth forge",               # depth forge benchmarks
    "Profile: ",                 # benchmark profile strings like *#%####%##
    "Strongest at depths",       # depth forge metrics
    "DEPTH score on",            # depth forge regression reports
    "DEPTH meta-analysis",       # depth forge meta-analysis
    "grade A", "grade B", "grade C", "grade D", "grade F",  # benchmark grades
    "free-tier",                 # polluted insight from old data
    "lets push git",             # raw user transcript fragments
    "remember: Do it",           # raw user transcript fragments
    "testing pipeline flow",     # generic test noise
]


def _looks_like_raw_transcript(text: str) -> bool:
    """Detect raw user transcript fragments that aren't real insights."""
    # Very informal language, questions, or commands pasted verbatim
    indicators = [
        text.count(",") > 3 and len(text) > 80,  # long rambling sentence
        "lets " in text.lower() and "push" in text.lower(),
        text.startswith("When using Bash"),
    ]
    return any(indicators)


def _is_noise_insight(text: str) -> bool:
    """Return True if insight is benchmark noise / not actionable."""
    t = text.lower()
    for pattern in _INSIGHT_NOISE_PATTERNS:
        if pattern.lower() in t:
            return True
    # Skip very short insights — too vague to be useful
    if len(text.strip()) < 30:
        return True
    # Skip raw transcript fragments
    if _looks_like_raw_transcript(text):
        return True
    # Skip insights with code blocks — usually raw examples, not distilled wisdom
    if "```" in text:
        return True
    # Skip insights that are just "Prefer X over Y" with raw data fragments
    if text.startswith("Prefer '") and "over '" in text:
        return True
    # Skip "User prefers:" followed by very short/vague content
    if text.startswith("User prefers:") and len(text) < 40:
        return True
    # Skip markdown tables and headers stored as insights
    if text.strip().startswith("|") or text.strip().startswith("##"):
        return True
    # Skip docstrings/code stored as insights
    if text.strip().startswith('"""') or text.strip().startswith("def ") or text.strip().startswith("class "):
        return True
    # Skip Python constants/assignments stored as insights
    if re.match(r'^[A-Z_]+ = ', text.strip()):
        return True
    return False


def _get_filtered_insights(limit: int = 10, source: str = "") -> list:
    """Get recent cognitive insights, filtered for relevance.

    Excludes depth forge benchmarks, Twitter API errors, and other noise
    that produces generic/hallucinated advisories.

    If source is specified, strongly prefer insights from that adapter.
    Untagged (legacy) insights are included but ranked lower.
    """
    from lib.cognitive_learner import get_cognitive_learner, CognitiveCategory

    cog = get_cognitive_learner()
    filtered = []

    # Prefer wisdom, context, and meta_learning categories — these are most actionable
    preferred_categories = [
        CognitiveCategory.WISDOM,
        CognitiveCategory.CONTEXT,
        CognitiveCategory.META_LEARNING,
        CognitiveCategory.USER_UNDERSTANDING,
    ]

    try:
        # First pass: get insights from matching source
        ranked = cog.get_ranked_insights(min_reliability=0.5, min_validations=2, limit=30, source=source)
        # If source filter yields too few, also get untagged insights
        if len(ranked) < limit:
            all_ranked = cog.get_ranked_insights(min_reliability=0.5, min_validations=2, limit=30)
            seen = {id(i) for i in ranked}
            for ins in all_ranked:
                if id(ins) not in seen and not getattr(ins, "source", ""):
                    ranked.append(ins)
        for ins in ranked:
            text = ins.insight if hasattr(ins, "insight") else str(ins)
            if _is_noise_insight(text):
                continue
            cat = ins.category if hasattr(ins, "category") else None
            # Boost preferred categories to front
            if cat in preferred_categories:
                filtered.insert(0, text)
            else:
                filtered.append(text)
            if len(filtered) >= limit:
                break
    except Exception:
        pass

    # Add self-awareness insights (filtered)
    try:
        for ins in cog.get_self_awareness_insights()[:5]:
            text = ins.insight if hasattr(ins, "insight") else str(ins)
            if not _is_noise_insight(text) and text not in filtered:
                filtered.append(text)
                if len(filtered) >= limit:
                    break
    except Exception:
        pass

    return filtered[:limit]


def _build_pattern_summaries(
    user_prompts: list, edit_events: list, stats: dict
) -> list:
    """Build descriptive pattern summaries from actual event data.

    Instead of just "16 patterns detected", produces things like:
    - "User edited lib/bridge_cycle.py, lib/llm.py (Python refactoring session)"
    - "Heavy use of exec tool (12 calls) — debugging/testing workflow"
    - "Error patterns: 3 failed tool calls (Read, exec)"
    """
    summaries = []

    # 1. Files being edited — shows what the session is about
    edited_files = set()
    for ev in edit_events:
        ti = ev.tool_input or {}
        fp = ti.get("file_path") or ti.get("path") or ""
        if fp:
            # Just filename, not full path
            from pathlib import PurePosixPath, PureWindowsPath
            try:
                name = PureWindowsPath(fp).name if "\\" in fp else PurePosixPath(fp).name
            except Exception:
                name = fp.split("/")[-1].split("\\")[-1]
            edited_files.add(name)
    if edited_files:
        files_str = ", ".join(sorted(edited_files)[:5])
        if len(edited_files) > 5:
            files_str += f" (+{len(edited_files)-5} more)"
        summaries.append(f"Files being edited: {files_str}")

    # 2. User prompt themes — what the human is asking about
    prompt_snippets = []
    for ev in user_prompts[-5:]:
        payload = (ev.data or {}).get("payload") or {}
        txt = str(payload.get("text") or "").strip()
        if txt and len(txt) > 10:
            # First 80 chars of each prompt
            prompt_snippets.append(txt[:80].replace("\n", " "))
    if prompt_snippets:
        summaries.append(f"Recent user requests: {'; '.join(prompt_snippets[:3])}")

    # 3. Pipeline stats with context
    pm = stats.get("pipeline", {})
    ly = pm.get("learning_yield", {})
    if ly.get("error_patterns_found"):
        summaries.append(f"{ly['error_patterns_found']} error patterns detected in this cycle")
    if ly.get("tool_effectiveness_updates"):
        summaries.append(f"{ly['tool_effectiveness_updates']} tool effectiveness observations")

    # 4. Feedback loop stats
    fb = stats.get("feedback", {})
    if fb:
        summaries.append(f"Agent feedback: {fb}")

    # 5. Content learning
    cl = stats.get("content_learned", 0)
    if cl > 0:
        summaries.append(f"{cl} code patterns learned from edits")

    return summaries


def _write_llm_advisory(advisory: str) -> None:
    """Write LLM-generated advisory to SPARK_CONTEXT supplement."""
    try:
        advisory_file = Path.home() / ".spark" / "llm_advisory.md"
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = f"# Spark Advisory ({timestamp})\n\n{advisory}\n"
        advisory_file.write_text(content, encoding="utf-8")

        for workspace in discover_openclaw_workspaces(include_nonexistent=True):
            ctx_file = workspace / "SPARK_ADVISORY.md"
            ctx_file.parent.mkdir(parents=True, exist_ok=True)
            ctx_file.write_text(content, encoding="utf-8")
    except Exception as e:
        log_debug("bridge_worker", f"Failed to write advisory: {e}", None)


_EIDOS_NOISE_PATTERNS = [
    # API/infra errors
    "invalid api key",
    "usage limit reached",
    "rate limit",
    "quota exceeded",
    "authentication failed",
    "insufficient credits",
    "service unavailable",
    # Tautologies and generic advice
    "try a different approach",
    "step back and",
    "try something else",
    "try another approach",
    "when repeated",
    "without progress",
    "always validate",
    "always verify",
    "be careful",
    "consider alternatives",
    "consider other options",
]


def _parse_structured_eidos(text: str) -> dict[str, Any] | None:
    try:
        obj = json.loads((text or "").strip())
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    insights = obj.get("insights")
    if not isinstance(insights, list) or not insights:
        return None
    return obj


def _is_valid_eidos_distillation(text: str) -> tuple[bool, str]:
    t = (text or "").strip()
    if len(t) < 24:
        return False, "too_short"

    low = t.lower()
    for p in _EIDOS_NOISE_PATTERNS:
        if p in low:
            return False, f"noise:{p}"

    structured = _parse_structured_eidos(t)
    if structured is not None:
        kept = [it for it in (structured.get("insights") or []) if isinstance(it, dict) and str(it.get("decision", "keep")).lower() == "keep"]
        if not kept:
            return False, "all_dropped"
        return True, "ok_structured"

    # Require either sentence-like shape or lightweight list structure.
    if not any(ch in t for ch in (".", "\n", ":", ";")):
        return False, "not_structured"

    return True, "ok"


def _append_eidos_update(update: str) -> None:
    """Append EIDOS distillation to the EIDOS log."""
    try:
        ok, reason = _is_valid_eidos_distillation(update)
        if not ok:
            record_quarantine_item(
                source="eidos",
                stage="append_eidos_update",
                reason=f"validator:{reason}",
                text=update,
            )
            log_debug("bridge_worker", f"Skipped EIDOS distillation ({reason})", None)
            return

        # Run advisory quality transformer for deeper filtering
        adv_quality_dict = {}
        try:
            from lib.distillation_transformer import transform_for_advisory
            adv_q = transform_for_advisory(update, source="eidos")
            adv_quality_dict = adv_q.to_dict()
            if adv_q.suppressed:
                record_quarantine_item(
                    source="eidos",
                    stage="append_eidos_update",
                    reason=f"transformer_suppressed:{adv_q.suppression_reason}",
                    text=update,
                    advisory_quality=adv_quality_dict,
                    advisory_readiness=adv_quality_dict.get("unified_score"),
                )
                log_debug("bridge_worker", f"EIDOS distillation suppressed by transformer ({adv_q.suppression_reason})", None)
                return
        except Exception:
            pass  # Don't block EIDOS storage if transformer fails
        advisory_readiness = float((adv_quality_dict or {}).get("unified_score") or 0.0)

        eidos_file = Path.home() / ".spark" / "eidos_distillations.jsonl"
        from datetime import datetime

        structured = _parse_structured_eidos(update)
        if structured is not None:
            kept = []
            for it in (structured.get("insights") or []):
                if not isinstance(it, dict):
                    continue
                if str(it.get("decision", "keep")).lower() != "keep":
                    continue
                action = str(it.get("action") or "").strip()
                # Reject short/empty actions and tautology patterns
                if len(action) < 15:
                    continue
                action_low = action.lower()
                if any(p in action_low for p in _EIDOS_NOISE_PATTERNS):
                    continue
                kept.append(it)
            if not kept:
                record_quarantine_item(
                    source="eidos",
                    stage="append_eidos_update",
                    reason="no_keep_actions",
                    text=update,
                    advisory_quality=adv_quality_dict,
                    advisory_readiness=advisory_readiness,
                )
                log_debug("bridge_worker", "All EIDOS insights filtered by quality gate", None)
                return
            summary_parts = []
            for it in kept[:3]:
                action = str(it.get("action") or "").strip()
                context = str(it.get("usage_context") or "").strip()
                if action:
                    summary_parts.append(f"{action} ({context})" if context else action)
            entry = {
                "timestamp": datetime.now().isoformat(),
                "schema": structured.get("schema") or "spark.eidos.v1",
                "insights": kept[:3],
                "distillation_summary": " | ".join(summary_parts)[:1200],
                "advisory_quality": adv_quality_dict,
                "advisory_readiness": round(min(max(advisory_readiness, 0.0), 1.0), 4),
            }
        else:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "distillation": update,
                "advisory_quality": adv_quality_dict,
                "advisory_readiness": round(min(max(advisory_readiness, 0.0), 1.0), 4),
            }

        with open(eidos_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        log_debug("bridge_worker", f"Failed to append EIDOS update: {e}", None)


_GENERIC_ADVISORY_PHRASES = [
    "check if services are running",
    "verify pipeline flow",
    "review recent changes",
    "check logs",
    "run tests",
    "validate integration",
    "consider adding",
    "monitor",
    "insufficient data",
]

def _is_generic_advisory(text: str) -> bool:
    """Return True if advisory is too generic to be worth pushing."""
    t = text.lower()
    matches = sum(1 for phrase in _GENERIC_ADVISORY_PHRASES if phrase in t)
    # If more than half the recommendations match generic phrases, skip
    lines = [l for l in text.strip().split('\n') if l.strip().startswith(('1.', '2.', '3.', '4.', '5.'))]
    if not lines:
        return matches >= 2
    generic_lines = sum(1 for l in lines if any(p in l.lower() for p in _GENERIC_ADVISORY_PHRASES))
    return generic_lines > len(lines) / 2


def _recent_exec_commands(events: list, limit: int = 12) -> list[str]:
    """Extract recent exec commands from this cycle's events (newest first)."""
    cmds: list[str] = []
    for ev in reversed(events or []):
        try:
            if ev.event_type != EventType.POST_TOOL:
                continue
            if (ev.tool_name or "").strip().lower() != "exec":
                continue
            ti = ev.tool_input or {}
            cmd = str(ti.get("command") or "").strip().lower()
            if cmd:
                cmds.append(cmd)
            if len(cmds) >= limit:
                break
        except Exception:
            continue
    return cmds


def _line_matches_recent_action(line: str, recent_cmds: list[str]) -> bool:
    """Return True when an advisory line recommends something already done recently."""
    l = line.lower()

    # 1) Direct command repetition via backticks: `openclaw session-status`
    for cmd in re.findall(r"`([^`]+)`", line):
        c = cmd.strip().lower()
        if not c:
            continue
        if any(c in rc or rc in c for rc in recent_cmds):
            return True

    # 2) High-signal heuristic for codex usage checks already completed
    if any("session-status" in rc for rc in recent_cmds):
        if "session-status" in l or ("codex" in l and "usage" in l):
            return True

    return False


def _prune_redundant_advisory(advisory: str, events: list) -> tuple[str, int]:
    """Drop advisory bullets that repeat actions already done in the recent window."""
    if not advisory.strip():
        return advisory, 0

    recent_cmds = _recent_exec_commands(events)
    if not recent_cmds:
        return advisory, 0

    lines = advisory.splitlines()
    kept: list[str] = []
    dropped = 0

    for line in lines:
        stripped = line.strip()
        is_bullet = bool(re.match(r"^\d+\.\s+", stripped))
        if is_bullet and _line_matches_recent_action(stripped, recent_cmds):
            dropped += 1
            continue
        kept.append(line)

    # Re-number numbered bullets after pruning to keep output clean.
    out: list[str] = []
    bullet_i = 1
    for line in kept:
        stripped = line.strip()
        if re.match(r"^\d+\.\s+", stripped):
            text = re.sub(r"^\d+\.\s+", "", stripped)
            out.append(f"{bullet_i}. {text}")
            bullet_i += 1
        else:
            out.append(line)

    return "\n".join(out).strip() + "\n", dropped


def _maybe_notify_openclaw(stats: Dict[str, Any]) -> None:
    """Push a wake event to OpenClaw if this cycle found something significant."""
    global _last_notify_time

    now = time.time()
    if now - _last_notify_time < _NOTIFY_COOLDOWN_S:
        return

    findings: list[str] = []

    # Check pipeline / pattern processing
    pattern_count = int(stats.get("pattern_processed") or 0)
    if pattern_count > 0:
        findings.append(f"{pattern_count} patterns processed")

    # Check chip merge for high-quality merges
    chip_merge = stats.get("chip_merge") or {}
    merged = int(chip_merge.get("merged") or 0)
    if merged > 0:
        findings.append(f"{merged} insights merged")

    # Check auto-tuner adjustments
    auto_tuner = stats.get("auto_tuner") or {}
    tuner_changes = int(auto_tuner.get("changes") or 0) + int(auto_tuner.get("health_applied") or 0)
    if tuner_changes > 0:
        findings.append(f"auto-tuner made {tuner_changes} adjustments")

    # Check validation for contradictions / surprises
    validation = stats.get("validation") or {}
    surprises = int(validation.get("surprises") or 0)
    if surprises > 0:
        findings.append(f"{surprises} contradictions detected")

    # Check content learning
    content_learned = int(stats.get("content_learned") or 0)
    if content_learned >= 3:
        findings.append(f"{content_learned} content patterns learned")

    # Check LLM advisory generation (with quality gate)
    advisory_text = str(stats.get("llm_advisory") or "")
    if advisory_text and not _is_generic_advisory(advisory_text):
        short = advisory_text[:300].rsplit('\n', 1)[0] if len(advisory_text) > 300 else advisory_text
        findings.append(f"Advisory: {short}")

    # Check EIDOS distillation
    if stats.get("eidos_distillation"):
        findings.append("EIDOS identity updated")

    # Check Opportunity Scanner loop output
    opp = stats.get("opportunity_scanner") or {}
    opp_count = int(opp.get("opportunities_found") or 0)
    if opp_count > 0:
        findings.append(f"opportunity scanner found {opp_count} self-improvement prompts")

    if not findings:
        return

    try:
        from lib.openclaw_notify import notify_agent, wake_agent

        summary = "Spark bridge cycle: " + ", ".join(findings)
        notify_agent(summary, priority="normal")
        wake_agent(
            f"🔮 Spark found something — read SPARK_CONTEXT.md and SPARK_NOTIFICATIONS.md. Summary: {summary}"
        )
        _last_notify_time = now
    except Exception as e:
        log_debug("bridge_worker", f"openclaw notify failed: {e}", None)


def write_bridge_heartbeat(stats: Dict[str, Any]) -> bool:
    """Write a heartbeat file so other services can detect liveness."""
    try:
        BRIDGE_HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": time.time(),
            "stats": {
                "context_updated": bool(stats.get("context_updated")),
                "pattern_processed": int(stats.get("pattern_processed") or 0),
                "content_learned": int(stats.get("content_learned") or 0),
                "memory": stats.get("memory") or {},
                "validation": stats.get("validation") or {},
                "outcome_validation": stats.get("outcome_validation") or {},
                "chips": stats.get("chips") or {},
                "chip_merge": stats.get("chip_merge") or {},
                "sync": stats.get("sync") or {},
                "llm_advisory": bool(stats.get("llm_advisory")),
                "eidos_distillation": bool(stats.get("eidos_distillation")),
                "opportunity_scanner": stats.get("opportunity_scanner") or {},
                "errors": stats.get("errors") or [],
            },
        }
        BRIDGE_HEARTBEAT_FILE.write_text(json.dumps(payload), encoding="utf-8")
        return True
    except Exception as e:
        log_debug("bridge_worker", "heartbeat write failed", e)
        return False


def read_bridge_heartbeat() -> Optional[Dict[str, Any]]:
    """Read bridge worker heartbeat (if any)."""
    if not BRIDGE_HEARTBEAT_FILE.exists():
        return None
    try:
        return json.loads(BRIDGE_HEARTBEAT_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log_debug("bridge_worker", "heartbeat read failed", e)
        return None


def bridge_heartbeat_age_s() -> Optional[float]:
    """Return heartbeat age in seconds, or None if missing."""
    data = read_bridge_heartbeat()
    if not data:
        return None
    try:
        ts = float(data.get("ts") or 0.0)
    except Exception:
        return None
    if ts <= 0:
        return None
    return max(0.0, time.time() - ts)
