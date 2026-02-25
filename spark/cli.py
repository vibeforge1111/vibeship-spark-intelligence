#!/usr/bin/env python3
"""
Spark CLI - Command-line interface for Spark

Usage:
    python -m spark.cli status     # Show system status
    python -m spark.cli services   # Show daemon/service status
    python -m spark.cli up         # Start background services
    python -m spark.cli ensure     # Start missing services if not running
    python -m spark.cli down       # Stop background services
    python -m spark.cli sync       # Sync insights to Mind
    python -m spark.cli queue      # Process offline queue
    python -m spark.cli process    # Run bridge worker cycle / drain backlog
    python -m spark.cli validate   # Run validation scan
    python -m spark.cli learnings  # Show recent learnings
    python -m spark.cli promote    # Run promotion check
    python -m spark.cli write      # Write learnings to markdown
    python -m spark.cli health     # Health check
    python -m spark.cli memory     # Memory capture suggestions
    python -m spark.cli advisory   # Guided advisory setup (2 questions)
    python -m spark.cli outcome    # Record explicit outcome check-in
    python -m spark.cli advice-feedback  # Record explicit advice helpfulness
    python -m spark.cli eval       # Evaluate predictions vs outcomes
    python -m spark.cli validate-ingest  # Validate recent queue events
    python -m spark.cli project    # Project questioning + capture
    python -m spark.cli personality-evolution  # Inspect/apply/reset personality evolution V1
"""

import sys
import json
import argparse
import time
import os
from pathlib import Path

from lib.cognitive_learner import get_cognitive_learner
from lib.mind_bridge import get_mind_bridge, sync_all_to_mind
from lib.markdown_writer import get_markdown_writer, write_all_learnings
from lib.promoter import get_promoter, check_and_promote
from lib.queue import get_queue_stats, read_recent_events, count_events
from lib.aha_tracker import get_aha_tracker
from lib.spark_voice import get_spark_voice
from lib.growth_tracker import get_growth_tracker
from lib.context_sync import sync_context
from lib.service_control import (
    start_services,
    stop_services,
    service_status,
    format_status_lines,
)
from lib.bridge_cycle import run_bridge_cycle, write_bridge_heartbeat, bridge_heartbeat_age_s
from lib.pattern_detection import get_pattern_backlog
from lib.validation_loop import (
    process_validation_events,
    get_validation_backlog,
    get_validation_state,
    process_outcome_validation,
    get_insight_outcome_coverage,
)
from lib.prediction_loop import get_prediction_state
from lib.evaluation import evaluate_predictions
from lib.outcome_log import (
    append_outcome,
    build_explicit_outcome,
    link_outcome_to_insight,
    get_outcome_links,
    read_outcomes,
    get_unlinked_outcomes,
    get_outcome_stats,
)
from lib.outcome_checkin import list_checkins, record_checkin_request
from lib.ingest_validation import scan_queue_events, write_ingest_report
from lib.exposure_tracker import (
    read_recent_exposures,
    read_exposures_within,
    read_last_exposure,
    infer_latest_session_id,
)
from lib.project_profile import (
    load_profile,
    save_profile,
    ensure_questions,
    get_suggested_questions,
    record_answer,
    record_entry,
    infer_domain,
    set_phase,
    completion_score,
)
from lib.memory_banks import store_memory, sync_insights_to_banks, get_bank_stats
from lib.memory_store import purge_telemetry_memories
from lib.eidos.store import purge_telemetry_distillations
from lib.advisor import record_advice_feedback
from lib.advisory_preferences import (
    apply_preferences as apply_advisory_preferences,
    apply_quality_uplift as apply_advisory_quality_uplift,
    get_current_preferences as get_current_advisory_preferences,
    repair_profile_drift as repair_advisory_profile_drift,
    setup_questions as get_advisory_setup_questions,
)
from lib.outcome_log import append_outcome, make_outcome_id, auto_link_outcomes, get_linkable_candidates
from lib.memory_capture import (
    process_recent_memory_events,
    list_pending as capture_list_pending,
    accept_suggestion as capture_accept,
    reject_suggestion as capture_reject,
)
from lib.capture_cli import format_pending
from lib.memory_migrate import migrate as migrate_memory
from lib.personality_evolver import load_personality_evolver
from lib.doctor import run_doctor, format_doctor_human
from lib.onboard import run_onboard, show_onboard_status, reset_onboard

# Chips imports (lazy to avoid startup cost if not used)
def _get_chips_registry():
    from lib.chips import get_registry
    return get_registry()

def _get_chips_router():
    from lib.chips import get_router
    return get_router()

def _premium_tools_enabled() -> bool:
    """Return True only when premium integration surfaces are explicitly enabled."""
    return os.getenv("SPARK_PREMIUM_TOOLS", "").strip().lower() in {"1", "true", "yes", "on"}


def _configure_output():
    """Ensure UTF-8 output on Windows terminals to avoid UnicodeEncodeError."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def cmd_status(args):
    """Show overall system status."""
    voice = get_spark_voice()
    
    print("\n" + "=" * 60)
    print("  SPARK - Self-Evolving Intelligence Layer")
    print("=" * 60)
    print(f"\n  {voice.get_status_voice()}\n")
    
    # Cognitive learner stats
    cognitive = get_cognitive_learner()
    cognitive_stats = cognitive.get_stats()
    print("ðŸ“š Cognitive Insights")
    print(f"   Total: {cognitive_stats['total_insights']}")
    print(f"   Avg Reliability: {cognitive_stats['avg_reliability']:.0%}")
    print(f"   Promoted: {cognitive_stats['promoted_count']}")
    print(f"   By Category:")
    for cat, count in cognitive_stats['by_category'].items():
        print(f"      - {cat}: {count}")
    print()
    
    # Mind bridge stats
    bridge = get_mind_bridge()
    bridge_stats = bridge.get_stats()
    print("ðŸ§  Mind Bridge")
    print(f"   Mind Available: {'âœ“ Yes' if bridge_stats['mind_available'] else 'âœ— No'}")
    print(f"   Synced to Mind: {bridge_stats['synced_count']}")
    print(f"   Offline Queue: {bridge_stats['offline_queue_size']}")
    print(f"   Last Sync: {bridge_stats['last_sync'] or 'Never'}")
    print()
    
    # Queue stats
    queue_stats = get_queue_stats()
    print("ðŸ“‹ Event Queue")
    print(f"   Events: {queue_stats['event_count']}")
    print(f"   Size: {queue_stats['size_mb']} MB")
    print(f"   Needs Rotation: {'Yes' if queue_stats['needs_rotation'] else 'No'}")
    print(f"   Pattern Backlog: {get_pattern_backlog()}")
    print(f"   Validation Backlog: {get_validation_backlog()}")
    ingest_stats = scan_queue_events(limit=200)
    processed = ingest_stats.get("processed", 0) or 0
    invalid = ingest_stats.get("invalid", 0) or 0
    if processed:
        valid = ingest_stats.get("valid", 0) or 0
        print(f"   Ingest Valid (last {processed}): {valid}/{processed} ({invalid} invalid)")
    print()

    # Project intelligence
    try:
        profile = load_profile(Path.cwd())
        score = completion_score(profile)
        print("ðŸŽ¯ Project Intelligence")
        print(f"   Domain: {profile.get('domain')}  Phase: {profile.get('phase')}")
        print(f"   Completion Score: {score['score']}/100")
        print(f"   Done: {profile.get('done') or 'not set'}")
        print()
    except Exception:
        pass

    # Worker heartbeat
    hb_age = bridge_heartbeat_age_s()
    print("Ã¢Å¡â„¢ Workers")
    if hb_age is None:
        print("   bridge_worker: Unknown (no heartbeat)")
    else:
        status = "OK" if hb_age <= 90 else "Stale"
        print(f"   bridge_worker: {status} (last {int(hb_age)}s ago)")
    print()

    # Validation loop
    vstate = get_validation_state()
    last_ts = vstate.get("last_run_ts")
    last_stats = vstate.get("last_stats") or {}
    if last_ts:
        age_s = max(0, int(time.time() - float(last_ts)))
        print("âœ… Validation Loop")
        print(f"   Last Run: {age_s}s ago")
        print(
            f"   Last Stats: +{last_stats.get('validated', 0)} / -{last_stats.get('contradicted', 0)} "
            f"(surprises {last_stats.get('surprises', 0)})"
        )
    else:
        print("âœ… Validation Loop")
        print("   Last Run: Never")
    print()

    # Prediction loop
    pstate = get_prediction_state()
    plast_ts = pstate.get("last_run_ts")
    plast_stats = pstate.get("last_stats") or {}
    pkpis = pstate.get("kpis") or {}
    if plast_ts:
        age_s = max(0, int(time.time() - float(plast_ts)))
        print("ðŸ§­ Prediction Loop")
        print(f"   Last Run: {age_s}s ago")
        print(
            f"   Last Stats: preds {plast_stats.get('predictions', 0)}, "
            f"outcomes {plast_stats.get('outcomes', 0)}, "
            f"+{plast_stats.get('validated', 0)} / -{plast_stats.get('contradicted', 0)} "
            f"(matched {plast_stats.get('matched', 0)}, surprises {plast_stats.get('surprises', 0)})"
        )
        if pkpis:
            print(
                f"   KPIs ({pkpis.get('window_days', 7)}d): "
                f"ratio {pkpis.get('prediction_to_outcome_ratio', 0):.2f}, "
                f"unlinked {pkpis.get('unlinked_outcomes', 0)}, "
                f"coverage {pkpis.get('coverage', 0):.1%}, "
                f"validated/100 {pkpis.get('validated_per_100_predictions', 0):.1f}"
            )
    else:
        print("ðŸ§­ Prediction Loop")
        print("   Last Run: Never")
    print()
    
    # Markdown writer stats
    writer = get_markdown_writer()
    writer_stats = writer.get_stats()
    print("ðŸ“ Markdown Output")
    print(f"   Directory: {writer_stats['learnings_dir']}")
    print(f"   Learnings Written: {writer_stats['learnings_count']}")
    print(f"   Errors Written: {writer_stats['errors_count']}")
    print()
    
    # Promoter stats
    promoter = get_promoter()
    promo_stats = promoter.get_promotion_status()
    print("ðŸ“¤ Promotions")
    print(f"   Ready for Promotion: {promo_stats['ready_for_promotion']}")
    print(f"   Already Promoted: {promo_stats['promoted_count']}")
    if promo_stats['by_target']:
        print(f"   By Target:")
        for target, count in promo_stats['by_target'].items():
            print(f"      - {target}: {count}")
    print()
    
    # Aha tracker stats
    aha = get_aha_tracker()
    aha_stats = aha.get_stats()
    print("ðŸ’¡ Surprises (Aha Moments)")
    print(f"   Total Captured: {aha_stats['total_captured']}")
    print(f"   Unexpected Successes: {aha_stats['unexpected_successes']}")
    print(f"   Unexpected Failures: {aha_stats['unexpected_failures']}")
    print(f"   Lessons Extracted: {aha_stats['lessons_extracted']}")
    if aha_stats['pending_surface'] > 0:
        print(f"   âš ï¸  Pending to Show: {aha_stats['pending_surface']}")
    print()
    
    # Voice/personality stats
    voice_stats = voice.get_stats()
    print("ðŸŽ­ Personality")
    print(f"   Age: {voice_stats['age_days']} days")
    print(f"   Interactions: {voice_stats['interactions']}")
    print(f"   Opinions Formed: {voice_stats['opinions_formed']}")
    print(f"   Growth Moments: {voice_stats['growth_moments']}")
    if voice_stats['strong_opinions'] > 0:
        print(f"   Strong Opinions: {voice_stats['strong_opinions']}")
    print()
    
    print("=" * 60)


def cmd_sync(args):
    """Sync insights to Mind."""
    print("[SPARK] Syncing to Mind...")
    stats = sync_all_to_mind()
    print(f"\nResults: {json.dumps(stats, indent=2)}")


def cmd_queue(args):
    """Process offline queue."""
    bridge = get_mind_bridge()
    print("[SPARK] Processing offline queue...")
    count = bridge.process_offline_queue()
    print(f"Processed: {count} items")


def cmd_process(args):
    """Run one bridge worker cycle or drain backlog."""
    iterations = 0
    processed = 0
    start = time.time()

    max_iterations = args.max_iterations
    timeout_s = args.timeout

    while True:
        stats = run_bridge_cycle(
            query=args.query,
            memory_limit=args.memory_limit,
            pattern_limit=args.pattern_limit,
        )
        write_bridge_heartbeat(stats)
        iterations += 1
        processed += int(stats.get("pattern_processed") or 0)

        errors = stats.get("errors") or []
        if errors:
            print(f"[SPARK] Cycle errors: {', '.join(errors)}")

        backlog = get_pattern_backlog()
        if not args.drain:
            break
        if backlog <= 0:
            break
        if max_iterations and iterations >= max_iterations:
            break
        if timeout_s and (time.time() - start) >= timeout_s:
            break
        if stats.get("pattern_processed", 0) <= 0 and not errors:
            break
        time.sleep(max(0.5, float(args.interval)))

    print(f"[SPARK] bridge_worker cycles: {iterations}, patterns processed: {processed}")


def cmd_validate(args):
    """Run validation loop scan on recent events."""
    stats = process_validation_events(limit=args.limit)
    print("[SPARK] Validation scan")
    print(f"  processed: {stats.get('processed', 0)}")
    print(f"  validated: {stats.get('validated', 0)}")
    print(f"  contradicted: {stats.get('contradicted', 0)}")
    print(f"  surprises: {stats.get('surprises', 0)}")


def cmd_learnings(args):
    """Show recent learnings."""
    cognitive = get_cognitive_learner()
    insights = list(cognitive.insights.values())
    
    # Sort by created_at
    insights.sort(key=lambda x: x.created_at, reverse=True)
    
    limit = args.limit or 10
    print(f"\nðŸ“š Recent Cognitive Insights (showing {min(limit, len(insights))} of {len(insights)})\n")
    
    for insight in insights[:limit]:
        status = "âœ“ Promoted" if insight.promoted else f"{insight.reliability:.0%} reliable"
        print(f"[{insight.category.value}] {insight.insight}")
        print(f"   {status} | {insight.times_validated} validations | {insight.created_at[:10]}")
        print()


def cmd_promote(args):
    """Run promotion check."""
    dry_run = args.dry_run
    print(f"[SPARK] Checking for promotable insights (dry_run={dry_run})...")
    stats = check_and_promote(dry_run=dry_run, include_project=(not args.no_project))
    print(f"\nResults: {json.dumps(stats, indent=2)}")


def cmd_write(args):
    """Write learnings to markdown."""
    print("[SPARK] Writing learnings to markdown...")
    stats = write_all_learnings()
    print(f"\nResults: {json.dumps(stats, indent=2)}")


def cmd_sync_context(args):
    """Sync bootstrap context to platform outputs."""
    project_dir = Path(args.project).expanduser() if args.project else None
    stats = sync_context(
        project_dir=project_dir,
        min_reliability=args.min_reliability,
        min_validations=args.min_validations,
        limit=args.limit,
        include_promoted=(not args.no_promoted),
        diagnose=args.diagnose,
    )
    out = {
        "selected": stats.selected,
        "promoted_selected": stats.promoted_selected,
        "targets": stats.targets,
    }
    if args.diagnose:
        out["diagnostics"] = stats.diagnostics or {}
    print(json.dumps(out, indent=2))


def cmd_decay(args):
    """Preview or apply decay-based pruning."""
    cognitive = get_cognitive_learner()
    if args.apply:
        pruned = cognitive.prune_stale(max_age_days=args.max_age_days, min_effective=args.min_effective)
        print(f"[SPARK] Pruned {pruned} stale insights")
        return

    candidates = cognitive.get_prune_candidates(
        max_age_days=args.max_age_days,
        min_effective=args.min_effective,
        limit=args.limit,
    )
    print("[SPARK] Decay dry-run")
    print(f"  candidates: {len(candidates)} (showing up to {args.limit})")
    for c in candidates:
        print(f"- [{c['category']}] {c['insight']}")
        print(f"  age={c['age_days']}d effective={c['effective_reliability']} raw={c['reliability']} v={c['validations']} x={c['contradictions']}")


def cmd_health(args):
    """Health check."""
    use_json = getattr(args, "json", False)
    checks = []

    # Check cognitive learner
    try:
        cognitive = get_cognitive_learner()
        checks.append({"name": "cognitive_learner", "ok": True})
    except Exception as e:
        checks.append({"name": "cognitive_learner", "ok": False, "error": str(e)})

    # Check Mind connection
    try:
        bridge = get_mind_bridge()
        mind_ok = bridge._check_mind_health()
        checks.append({"name": "mind_api", "ok": mind_ok})
    except Exception as e:
        checks.append({"name": "mind_api", "ok": False, "error": str(e)})

    # Check queue
    try:
        stats = get_queue_stats()
        checks.append({"name": "event_queue", "ok": True, "events": stats["event_count"]})
    except Exception as e:
        checks.append({"name": "event_queue", "ok": False, "error": str(e)})

    # Check bridge worker heartbeat
    hb_age = bridge_heartbeat_age_s()
    bridge_ok = hb_age is not None and hb_age <= 90
    checks.append({"name": "bridge_worker", "ok": bridge_ok, "heartbeat_age_s": int(hb_age) if hb_age else None})

    # Check learnings dir
    writer = get_markdown_writer()
    checks.append({"name": "learnings_dir", "ok": writer.learnings_dir.exists(), "path": str(writer.learnings_dir)})

    all_ok = all(c["ok"] for c in checks)

    if use_json:
        print(json.dumps({"ok": all_ok, "command": "health", "checks": checks}, indent=2))
    else:
        print("\n  Health Check\n")
        for c in checks:
            icon = "[+]" if c["ok"] else "[X]"
            detail = ""
            if c.get("events"):
                detail = f" ({c['events']} events)"
            if c.get("heartbeat_age_s") is not None:
                detail = f" ({c['heartbeat_age_s']}s ago)"
            if c.get("error"):
                detail = f" - {c['error']}"
            print(f"  {icon} {c['name']}{detail}")
        print()

    sys.exit(0 if all_ok else 1)


def cmd_doctor(args):
    """Comprehensive system diagnostics and optional repair."""
    deep = getattr(args, "deep", False)
    repair = getattr(args, "repair", False)
    use_json = getattr(args, "json", False)

    result = run_doctor(deep=deep, repair=repair)

    if use_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(format_doctor_human(result))

    # Exit codes per blueprint: 0=healthy, 1=issues, 3=partial repair
    if result.ok:
        sys.exit(0)
    elif repair and result.repaired_count > 0:
        sys.exit(3)
    else:
        sys.exit(1)


def cmd_onboard(args):
    """First-time onboarding wizard."""
    use_json = getattr(args, "json", False)
    subcmd = getattr(args, "onboard_cmd", None)

    if subcmd == "status":
        result = show_onboard_status()
        if use_json:
            result.setdefault("ok", True)
            result.setdefault("command", "onboard status")
            print(json.dumps(result, indent=2))
        else:
            print(f"\n  Onboarding: {result.get('status', 'unknown')}")
            if result.get("progress"):
                print(f"  Progress: {result['progress']}")
            if result.get("agent"):
                print(f"  Agent: {result['agent']}")
            print()
        return

    if subcmd == "reset":
        result = reset_onboard()
        if use_json:
            result.setdefault("ok", True)
            result.setdefault("command", "onboard reset")
            print(json.dumps(result, indent=2))
        else:
            print(f"\n  {result['message']}\n")
        return

    # Main onboard flow
    agent = getattr(args, "agent", "") or ""
    quick = getattr(args, "quick", False)
    auto_yes = getattr(args, "yes", False)

    result = run_onboard(agent=agent, quick=quick, auto_yes=auto_yes, use_json=use_json)

    if use_json:
        print(json.dumps(result, indent=2))

    if result.get("ok"):
        sys.exit(0)
    else:
        sys.exit(1)


def cmd_logs(args):
    """View service logs."""
    use_json = getattr(args, "json", False)
    log_dir = Path(os.environ.get("SPARK_LOG_DIR", Path.home() / ".spark" / "logs"))
    service = getattr(args, "service", None)
    tail_n = getattr(args, "tail", 50)
    follow = getattr(args, "follow", False)

    if not log_dir.exists():
        if use_json:
            print(json.dumps({"ok": False, "error": f"No log directory at {log_dir}"}, indent=2))
        else:
            print(f"  No log directory found at {log_dir}")
            print("  Start services first: spark up")
        sys.exit(1)

    # Determine which files to read
    if service:
        targets = [log_dir / f"{service}.log"]
    else:
        targets = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

    if not targets:
        if use_json:
            print(json.dumps({"ok": True, "logs": []}, indent=2))
        else:
            print("  No log files found.")
        sys.exit(0)

    json_logs = []
    for log_file in targets:
        if not log_file.exists():
            if not use_json:
                print(f"  [{log_file.stem}] No log file")
            continue

        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as e:
            if not use_json:
                print(f"  [{log_file.stem}] Error reading: {e}")
            continue

        # Apply --since filter
        since = getattr(args, "since", None)
        if since:
            cutoff = _parse_since(since)
            if cutoff:
                lines = [l for l in lines if _line_after(l, cutoff)]

        # Tail
        if tail_n and len(lines) > tail_n:
            lines = lines[-tail_n:]

        if use_json:
            json_logs.append({"service": log_file.stem, "lines": lines, "count": len(lines)})
        elif lines:
            print(f"\n  === {log_file.stem} ({len(lines)} lines) ===")
            for line in lines:
                print(f"  {line}")

    if use_json:
        print(json.dumps({"ok": True, "command": "logs", "logs": json_logs}, indent=2))
    else:
        if follow:
            print("\n  [--follow is not yet implemented -- showing latest snapshot]")
        print()


def _parse_since(since_str: str) -> float | None:
    """Parse a relative time string like '1h', '30m', '2d' to epoch timestamp."""
    import re
    m = re.match(r"^(\d+)([smhd])$", since_str.strip())
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return time.time() - val * multipliers.get(unit, 1)


def _line_after(line: str, cutoff: float) -> bool:
    """Heuristic: check if a log line timestamp is after cutoff.

    Most Spark service logs do not include timestamps in a consistent format,
    so we attempt a few common patterns and default to including the line
    if we cannot parse it (safer than silently dropping content).
    """
    import re
    # Try ISO-style: 2026-02-24T12:34:56 or 2026-02-24 12:34:56
    m = re.match(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", line)
    if m:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
            return dt.timestamp() >= cutoff
        except (ValueError, OSError):
            pass
    # Try epoch float at start of line
    m = re.match(r"^(\d{10,13}(?:\.\d+)?)\b", line)
    if m:
        try:
            ts = float(m.group(1))
            if ts > 1e12:  # milliseconds
                ts /= 1000
            return ts >= cutoff
        except (ValueError, OverflowError):
            pass
    # Cannot parse — include the line
    return True


def cmd_config(args):
    """Get, set, or inspect tuneables configuration."""
    runtime_path = Path.home() / ".spark" / "tuneables.json"
    versioned_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"

    def _load_json(p):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8-sig"))
        return {}

    def _resolve_dot(data, key):
        """Resolve dot-path like 'advisor.max_emit' -> nested value."""
        parts = key.split(".")
        cur = data
        for part in parts:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None, False
        return cur, True

    def _set_dot(data, key, value):
        """Set a value at dot-path, creating intermediate dicts."""
        parts = key.split(".")
        cur = data
        for part in parts[:-1]:
            if part not in cur or not isinstance(cur[part], dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value

    def _del_dot(data, key):
        """Delete a value at dot-path. Returns True if found."""
        parts = key.split(".")
        cur = data
        for part in parts[:-1]:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return False
        if isinstance(cur, dict) and parts[-1] in cur:
            del cur[parts[-1]]
            return True
        return False

    sub = getattr(args, "config_cmd", None)

    if sub == "get":
        key = args.key
        runtime = _load_json(runtime_path)
        val, found = _resolve_dot(runtime, key)
        if not found:
            # Fall back to versioned defaults
            versioned = _load_json(versioned_path)
            val, found = _resolve_dot(versioned, key)
        if not found:
            print(f"  Key not found: {key}")
            sys.exit(1)
        if isinstance(val, (dict, list)):
            print(json.dumps(val, indent=2))
        else:
            print(val)

    elif sub == "set":
        key = args.key
        raw = args.value
        # Auto-parse types
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            value = raw

        runtime = _load_json(runtime_path)
        # Backup before write
        if runtime_path.exists():
            backup = runtime_path.with_suffix(".json.bak")
            backup.write_text(runtime_path.read_text(encoding="utf-8"), encoding="utf-8")
        _set_dot(runtime, key, value)
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(json.dumps(runtime, indent=2), encoding="utf-8")
        print(f"  {key} = {json.dumps(value)}")
        print(f"  Saved to {runtime_path}")

    elif sub == "unset":
        key = args.key
        runtime = _load_json(runtime_path)
        if not _del_dot(runtime, key):
            print(f"  Key not found in runtime config: {key}")
            sys.exit(1)
        # Backup before write
        backup = runtime_path.with_suffix(".json.bak")
        if runtime_path.exists():
            backup.write_text(runtime_path.read_text(encoding="utf-8"), encoding="utf-8")
        runtime_path.write_text(json.dumps(runtime, indent=2), encoding="utf-8")
        print(f"  Removed: {key}")

    elif sub == "validate":
        runtime = _load_json(runtime_path)
        versioned = _load_json(versioned_path)
        known_sections = set(versioned.keys())
        runtime_sections = set(runtime.keys())
        unknown = runtime_sections - known_sections
        errors = []
        if unknown:
            errors.append(f"Unknown sections in runtime: {', '.join(sorted(unknown))}")
        if errors:
            print("  Validation issues:")
            for e in errors:
                print(f"    - {e}")
            sys.exit(1)
        else:
            print(f"  Config valid ({len(runtime_sections)} sections, {len(known_sections)} known)")

    elif sub == "diff":
        runtime = _load_json(runtime_path)
        versioned = _load_json(versioned_path)
        diffs = []
        for section in sorted(set(list(runtime.keys()) + list(versioned.keys()))):
            r_val = runtime.get(section, {})
            v_val = versioned.get(section, {})
            if not isinstance(r_val, dict) or not isinstance(v_val, dict):
                if r_val != v_val:
                    diffs.append((section, v_val, r_val))
                continue
            for key in sorted(set(list(r_val.keys()) + list(v_val.keys()))):
                rv = r_val.get(key)
                vv = v_val.get(key)
                if rv != vv:
                    diffs.append((f"{section}.{key}", vv, rv))
        if not diffs:
            print("  No differences between runtime and versioned config.")
        else:
            print(f"  {len(diffs)} difference(s):")
            for path, ver, run in diffs:
                ver_s = json.dumps(ver) if ver is not None else "(missing)"
                run_s = json.dumps(run) if run is not None else "(missing)"
                print(f"    {path}")
                print(f"      versioned: {ver_s}")
                print(f"      runtime:   {run_s}")

    elif sub == "show":
        runtime = _load_json(runtime_path)
        if getattr(args, "json", False):
            print(json.dumps({"ok": True, "command": "config", "config": runtime}, indent=2))
        else:
            print(f"  Runtime config: {runtime_path}")
            print(f"  Versioned config: {versioned_path}")
            print(f"  Sections: {', '.join(sorted(runtime.keys())) if runtime else '(empty)'}")
            for section in sorted(runtime.keys()):
                vals = runtime[section]
                if isinstance(vals, dict):
                    print(f"\n  [{section}] ({len(vals)} keys)")
                    for k, v in sorted(vals.items()):
                        print(f"    {k} = {json.dumps(v)}")
                else:
                    print(f"\n  [{section}] = {json.dumps(vals)}")

    else:
        # Default: show summary
        runtime = _load_json(runtime_path)
        print(f"  Runtime: {runtime_path} ({'exists' if runtime_path.exists() else 'not found'})")
        print(f"  Versioned: {versioned_path} ({'exists' if versioned_path.exists() else 'not found'})")
        if runtime:
            print(f"  Sections: {', '.join(sorted(runtime.keys()))}")
        print("  Use: spark config get <key> | set <key> <value> | unset <key> | diff | validate | show")


def cmd_run(args):
    """Convenience wrapper: start services, run health check, optionally sync context."""
    use_json = getattr(args, "json", False)
    steps = []

    # Step 1: Start services
    if not use_json:
        print("\n  [1/3] Starting services...")
    lite_env = os.environ.get("SPARK_LITE", "").lower() in ("1", "true", "yes")
    lite = bool(getattr(args, "lite", False)) or lite_env
    try:
        results = start_services(
            include_mind=True,
            include_pulse=not lite,
            include_watchdog=True,
        )
        steps.append({"step": "services", "ok": True, "detail": results})
        if not use_json:
            for name, result in results.items():
                print(f"    {name}: {result}")
    except Exception as e:
        steps.append({"step": "services", "ok": False, "error": str(e)})
        if not use_json:
            print(f"    Error starting services: {e}")

    # Step 2: Health check
    if not use_json:
        print("  [2/3] Running health check...")
    try:
        from lib.doctor import run_doctor
        doc_result = run_doctor(deep=False)
        ok = doc_result.ok
        issues = [c.message for c in doc_result.checks if c.status in ("fail", "warn")]
        steps.append({"step": "health", "ok": ok, "command": "run", "issues": issues})
        if not use_json:
            status_icon = "[+]" if ok else "[!]"
            print(f"    {status_icon} {'Healthy' if ok else f'{len(issues)} issue(s)'}")
            for iss in issues[:3]:
                print(f"      - {iss}")
    except Exception as e:
        steps.append({"step": "health", "ok": False, "error": str(e)})
        if not use_json:
            print(f"    Error running health check: {e}")

    # Step 3: Sync context (optional)
    if getattr(args, "sync", True):
        if not use_json:
            print("  [3/3] Syncing context...")
        try:
            project_dir = Path.cwd()
            sync_context(project_dir=project_dir)
            steps.append({"step": "sync_context", "ok": True, "project": str(project_dir)})
            if not use_json:
                print(f"    Synced: {project_dir}")
        except Exception as e:
            steps.append({"step": "sync_context", "ok": False, "error": str(e)})
            if not use_json:
                print(f"    Error syncing: {e}")
    else:
        steps.append({"step": "sync_context", "ok": True, "skipped": True})

    all_ok = all(s["ok"] for s in steps)
    if use_json:
        print(json.dumps({"ok": all_ok, "command": "run", "steps": steps}, indent=2))
    else:
        print(f"\n  {'Ready!' if all_ok else 'Started with issues — run spark doctor for details.'}\n")
    sys.exit(0 if all_ok else 1)


def cmd_update(args):
    """Pull latest Spark, install deps, restart services."""
    import subprocess

    use_json = getattr(args, "json", False)
    no_restart = getattr(args, "no_restart", False)
    check_only = getattr(args, "check", False)
    repo_root = Path(__file__).resolve().parent.parent

    result = {"ok": True, "command": "update", "updated": False, "commits": [], "services_restarted": False}

    def _git(*cmd):
        r = subprocess.run(["git"] + list(cmd), capture_output=True, text=True, cwd=str(repo_root))
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    # Get current state
    rc, branch, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        result["ok"] = False
        result["error"] = "Not a git repository"
        if use_json:
            print(json.dumps(result, indent=2))
        else:
            print("\n  [X] Not a git repository\n")
        sys.exit(1)

    rc, old_sha, _ = _git("rev-parse", "HEAD")

    # Check for uncommitted changes
    rc, diff_out, _ = _git("status", "--porcelain")
    has_local_changes = bool(diff_out)

    # Fetch latest
    if not use_json:
        print(f"\n  Checking for updates on {branch}...")
    rc, _, fetch_err = _git("fetch", "origin", branch)
    if rc != 0:
        result["ok"] = False
        result["error"] = f"Fetch failed: {fetch_err}"
        if use_json:
            print(json.dumps(result, indent=2))
        else:
            print(f"  [X] Fetch failed: {fetch_err}\n")
        sys.exit(1)

    # Count commits behind
    rc, count_str, _ = _git("rev-list", "--count", f"HEAD..origin/{branch}")
    behind = int(count_str) if rc == 0 and count_str.isdigit() else 0

    if behind == 0:
        result["updated"] = False
        if use_json:
            print(json.dumps(result, indent=2))
        else:
            print("  [+] Already up to date.\n")
        sys.exit(0)

    # Check-only mode: report and exit
    if check_only:
        rc, log_out, _ = _git("log", "--oneline", f"HEAD..origin/{branch}")
        commits = [line for line in log_out.splitlines() if line.strip()]
        result["behind"] = behind
        result["commits"] = commits
        if use_json:
            print(json.dumps(result, indent=2))
        else:
            print(f"  {behind} update(s) available:")
            for c in commits[:10]:
                print(f"    {c}")
            if behind > 10:
                print(f"    ... and {behind - 10} more")
            print()
        sys.exit(0)

    # Warn about local changes
    if has_local_changes and not use_json:
        print("  [!] You have uncommitted changes. They will be preserved (pull uses merge).")

    # Confirmation gate (skip for --yes or --json)
    auto_yes = getattr(args, "yes", False)
    if not auto_yes and not use_json:
        try:
            answer = input(f"  Pull {behind} update(s) and install deps? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("y", "yes"):
            print("  Cancelled.\n")
            sys.exit(0)

    # Pull
    if not use_json:
        print(f"  Pulling {behind} update(s)...")
    rc, pull_out, pull_err = _git("pull", "origin", branch)
    if rc != 0:
        result["ok"] = False
        result["error"] = f"Pull failed: {pull_err}"
        if use_json:
            print(json.dumps(result, indent=2))
        else:
            print(f"  [X] Pull failed: {pull_err}\n")
        sys.exit(1)

    # Show what changed
    rc, new_sha, _ = _git("rev-parse", "HEAD")
    rc, log_out, _ = _git("log", "--oneline", f"{old_sha}..{new_sha}")
    commits = [line for line in log_out.splitlines() if line.strip()]
    result["updated"] = True
    result["commits"] = commits

    if not use_json:
        print(f"  [+] Updated ({len(commits)} commit(s)):")
        for c in commits[:10]:
            print(f"    {c}")
        if len(commits) > 10:
            print(f"    ... and {len(commits) - 10} more")

    # Install deps
    if not use_json:
        print("  Installing dependencies...")
    pip_result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".[services]", "--quiet"],
        capture_output=True, text=True, cwd=str(repo_root),
    )
    if pip_result.returncode != 0:
        result["dep_error"] = pip_result.stderr.strip()
        if not use_json:
            print(f"  [!] Dependency install warning: {pip_result.stderr.strip()[:200]}")

    # Restart services if running
    if not no_restart:
        try:
            status = service_status(include_pulse_probe=False)
            running = [name for name, info in status.items() if info.get("running")]
            if running:
                if not use_json:
                    print("  Restarting services...")
                stop_services()
                start_services()
                result["services_restarted"] = True
                if not use_json:
                    print(f"  [+] Services restarted ({len(running)} services)")
            else:
                if not use_json:
                    print("  No services were running (skipping restart).")
        except Exception as e:
            result["restart_error"] = str(e)
            if not use_json:
                print(f"  [!] Service restart error: {e}")

    if use_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"\n  Spark updated to latest.\n")
    sys.exit(0 if result["ok"] else 1)


def cmd_services(args):
    """Show daemon/service status."""
    use_json = getattr(args, "json", False)
    status = service_status(bridge_stale_s=args.bridge_stale_s)

    if use_json:
        print(json.dumps({"ok": True, "command": "services", "services": status}, indent=2))
    else:
        print("")
        for line in format_status_lines(status, bridge_stale_s=args.bridge_stale_s):
            print(line)
        print("")


def _should_start_watchdog(args) -> bool:
    if args.no_watchdog:
        return False
    return os.environ.get("SPARK_NO_WATCHDOG", "") == ""


def cmd_up(args):
    """Start Spark background services."""
    lite_env = os.environ.get("SPARK_LITE", "").lower() in ("1", "true", "yes")
    lite = bool(getattr(args, "lite", False)) or lite_env
    include_watchdog = _should_start_watchdog(args)
    results = start_services(
        bridge_interval=args.bridge_interval,
        bridge_query=args.bridge_query,
        watchdog_interval=args.watchdog_interval,
        include_mind=not args.no_mind,
        include_pulse=(not args.no_pulse) and (not lite),
        include_watchdog=include_watchdog,
        bridge_stale_s=args.bridge_stale_s,
    )

    print("")
    print("[spark] starting services")
    for name, result in results.items():
        print(f"  {name}: {result}")
    print("")

    if args.sync_context:
        project_dir = Path(args.project).expanduser() if args.project else Path.cwd()
        sync_context(project_dir=project_dir)
        print(f"[spark] sync-context: {project_dir}")


def cmd_ensure(args):
    """Ensure Spark services are running (start any missing)."""
    cmd_up(args)


def cmd_down(args):
    """Stop Spark background services."""
    results = stop_services()
    print("")
    print("[spark] stopping services")
    for name, result in results.items():
        print(f"  {name}: {result}")
    print("")


def cmd_events(args):
    """Show recent events."""
    limit = args.limit or 20
    events = read_recent_events(limit)
    
    print(f"\nðŸ“‹ Recent Events (showing {len(events)} of {count_events()})\n")
    
    for event in events:
        tool_str = f" [{event.tool_name}]" if event.tool_name else ""
        error_str = f" ERROR: {event.error[:50]}..." if event.error else ""
        print(f"[{event.event_type.value}]{tool_str}{error_str}")


def cmd_opportunities(args):
    """Opportunity Scanner inbox: list/accept/dismiss self-opportunities."""
    from lib.opportunity_inbox import (
        load_self_opportunities,
        resolve_opportunity,
        record_decision,
        decisions_by_opportunity_id,
        write_task_file,
    )

    sub = getattr(args, "opps_cmd", None) or "list"
    if sub == "list":
        rows = load_self_opportunities(
            limit=int(args.limit or 20),
            scope_type=args.scope_type,
            scope_id=args.scope_id,
            project_id=args.project_id,
            operation=args.operation,
            since_hours=args.since_hours,
        )
        latest = decisions_by_opportunity_id()
        if not args.all:
            filtered = []
            for r in rows:
                oid = str(r.get("opportunity_id") or "").strip()
                st = latest.get(oid)
                if st and st.action in {"accept", "dismiss"}:
                    continue
                filtered.append(r)
            rows = filtered

        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=True))
            return

        print(f"[SPARK] Opportunities (showing {len(rows)})")
        for r in rows:
            oid = str(r.get("opportunity_id") or "").strip()
            short = oid[-12:] if len(oid) > 12 else oid
            st = latest.get(oid)
            status = (st.action if st else "").upper()
            scope = f"{r.get('scope_type') or ''}:{r.get('scope_id') or ''}".strip(":")
            cat = str(r.get("category") or "")
            pri = str(r.get("priority") or "")
            src = str(r.get("source") or "")
            prov = str(r.get("llm_provider") or "")
            q = str(r.get("question") or "").strip().replace("\n", " ")
            if len(q) > 140:
                q = q[:137] + "..."
            meta = f"{cat}/{pri} {src}{('/' + prov) if prov else ''}"
            if status:
                meta = f"{meta} [{status}]"
            print(f"- {short} | {scope} | {meta}")
            print(f"  Q: {q}")

    elif sub in {"accept", "dismiss"}:
        prefix = getattr(args, "id", None) or ""
        row = resolve_opportunity(prefix)
        if not row:
            print(f"[SPARK] Opportunity not found for id/prefix: {prefix}")
            return
        oid = str(row.get("opportunity_id") or "").strip()
        action = "accept" if sub == "accept" else "dismiss"
        note = str(getattr(args, "note", "") or "").strip()
        record_decision(
            action=action,
            opportunity_id=oid,
            question=str(row.get("question") or ""),
            note=note,
            scope_type=row.get("scope_type"),
            scope_id=row.get("scope_id"),
            project_id=row.get("project_id"),
            operation=row.get("operation"),
        )
        if action == "accept":
            out_path = write_task_file(row)
            print(f"[SPARK] Accepted {oid} -> {out_path}")
        else:
            print(f"[SPARK] Dismissed {oid}")
    else:
        print("[SPARK] Unknown opportunities subcommand. Use: spark opportunities list|accept|dismiss")


def cmd_capture(args):
    """Portable memory capture: scan â†’ suggest â†’ accept/reject."""
    if args.scan or (not args.list and not args.accept and not args.reject):
        stats = process_recent_memory_events(limit=80)
        print("[SPARK] Memory capture scan")
        print(f"  auto_saved: {stats['auto_saved']}")
        print(f"  explicit_saved: {stats['explicit_saved']}")
        print(f"  suggested: {stats['suggested']}")
        print(f"  pending_total: {stats['pending_total']}")
        print()

    if args.accept:
        ok = capture_accept(args.accept)
        print("âœ“ Accepted" if ok else "âœ— Not found / not pending")
    return


def cmd_outcome(args):
    """Record an explicit outcome check-in."""
    if args.pending:
        items = list_checkins(limit=args.limit)
        if not items:
            print("[SPARK] No pending check-ins found.")
            return
        print("[SPARK] Recent check-in requests:")
        for item in items:
            ts = item.get("created_at")
            sid = item.get("session_id") or "unknown"
            event = item.get("event") or "unknown"
            print(f"   - {sid} ({event}) @ {ts}")
        return

    result = args.result
    text = args.text
    tool = args.tool

    if not result:
        try:
            result = input("Outcome (yes/no/partial): ").strip()
        except Exception:
            result = "unknown"
    if text is None:
        try:
            text = input("Notes (optional): ").strip()
        except Exception:
            text = ""

    row, polarity = build_explicit_outcome(
        result=result,
        text=text or "",
        tool=tool,
        created_at=args.time,
    )
    if args.session_id:
        row["session_id"] = args.session_id
    link_keys = []
    if args.link_key:
        link_keys.extend([k for k in args.link_key if k])
    link_count = int(args.link_count or 0)
    if args.link_latest:
        link_count = max(link_count, 1)
    if link_count > 0:
        exposures = read_recent_exposures(limit=link_count)
        if row.get("session_id"):
            same = [ex for ex in exposures if ex.get("session_id") == row.get("session_id")]
            if same:
                exposures = same
        for ex in exposures:
            key = ex.get("insight_key")
            if key:
                link_keys.append(key)
        row["linked_texts"] = [ex.get("text") for ex in exposures if ex.get("text")]
    else:
        auto_link = args.auto_link or os.environ.get("SPARK_OUTCOME_AUTO_LINK") == "1"
        if auto_link:
            if not row.get("session_id"):
                sid = infer_latest_session_id()
                if sid:
                    row["session_id"] = sid
            window_s = float(args.link_window_mins or 30) * 60
            now_ts = float(args.time or 0) or None
            exposures = read_exposures_within(max_age_s=window_s, now=now_ts, limit=200)
            if not exposures:
                last = read_last_exposure()
                if last:
                    exposures = [last]
            if row.get("session_id"):
                same = [ex for ex in exposures if ex.get("session_id") == row.get("session_id")]
                if same:
                    exposures = same
            for ex in exposures:
                key = ex.get("insight_key")
                if key:
                    link_keys.append(key)
            if exposures:
                row["linked_texts"] = [ex.get("text") for ex in exposures if ex.get("text")]
    if link_keys:
        deduped = []
        for k in link_keys:
            if k and k not in deduped:
                deduped.append(k)
        row["linked_insights"] = deduped
    append_outcome(row)
    print(f"[SPARK] Outcome recorded: {row.get('result')} (polarity={polarity})")


def cmd_advice_feedback(args):
    """Record explicit feedback on advice helpfulness."""
    if args.pending:
        from lib.advice_feedback import list_requests
        items = list_requests(limit=args.limit or 5)
        if not items:
            print("[SPARK] No pending advice feedback requests.")
            return
        print(f"[SPARK] Advice Feedback Requests ({len(items)}):")
        for row in items:
            tool = row.get("tool") or "unknown"
            ts = row.get("created_at")
            print(f"  - tool={tool} ts={ts}")
        return
    if args.analyze:
        from lib.advice_feedback import analyze_feedback
        summary = analyze_feedback(min_samples=args.min_samples or 3, write_summary=True)
        if summary.get("total_feedback", 0) == 0:
            print("[SPARK] No advice feedback yet.")
            return
        print("[SPARK] Advice Feedback Summary")
        print(f"  Total feedback: {summary.get('total_feedback')}")
        print(f"  Helpful rate: {summary.get('helpful_rate'):.0%}")
        print(f"  Helpful known: {summary.get('helpful_known')}")
        if summary.get("by_tool"):
            print("  By tool (top):")
            for row in summary["by_tool"][:5]:
                print(f"    - {row['key']}: {row['helpful_rate']:.0%} ({row['helpful_known']} samples)")
        if summary.get("by_source"):
            print("  By source (top):")
            for row in summary["by_source"][:5]:
                print(f"    - {row['key']}: {row['helpful_rate']:.0%} ({row['helpful_known']} samples)")
        if summary.get("recommendations"):
            print("  Recommendations:")
            for rec in summary["recommendations"][:5]:
                print(f"    - {rec}")
        return

    helpful_map = {
        "yes": True,
        "no": False,
        "unknown": None,
    }
    helpful = helpful_map.get(args.helpful)
    followed = args.followed != "no"

    result = record_advice_feedback(
        helpful=helpful,
        notes=args.notes or "",
        tool=args.tool,
        advice_id=args.advice_id,
        followed=followed,
    )

    if result.get("status") == "ok":
        ids = result.get("advice_ids") or []
        tool = result.get("tool") or args.tool or ""
        print(f"[SPARK] Advice feedback recorded for {len(ids)} item(s){' on ' + tool if tool else ''}.")
    else:
        print(f"[SPARK] Advice feedback failed: {result.get('message')}")


def cmd_eval(args):
    """Evaluate prediction accuracy against outcomes."""
    max_age_s = float(args.days) * 24 * 3600
    stats = evaluate_predictions(max_age_s=max_age_s, sim_threshold=args.sim)
    print("[SPARK] Evaluation")
    print(f"   Predictions: {stats['predictions']}")
    print(f"   Outcomes: {stats['outcomes']}")
    print(f"   Matched: {stats['matched']}")
    print(f"   Validated: {stats['validated']}")
    print(f"   Contradicted: {stats['contradicted']}")
    print(f"   Precision: {stats['precision']:.0%}")
    print(f"   Outcome Coverage: {stats['outcome_coverage']:.0%}")


def cmd_outcome_link(args):
    """Link an outcome to an insight for validation."""
    outcome_id = args.outcome_id
    insight_key = args.insight_key
    chip_id = args.chip_id
    confidence = float(args.confidence or 1.0)
    notes = args.notes or ""

    link = link_outcome_to_insight(
        outcome_id=outcome_id,
        insight_key=insight_key,
        chip_id=chip_id,
        confidence=confidence,
        notes=notes,
    )
    print(f"[SPARK] Link created: {link.get('link_id')}")
    print(f"   Outcome: {outcome_id}")
    print(f"   Insight: {insight_key}")
    if chip_id:
        print(f"   Chip: {chip_id}")


def cmd_outcome_stats(args):
    """Show outcome-insight coverage statistics."""
    chip_id = args.chip_id if hasattr(args, 'chip_id') else None

    # Get general outcome stats
    stats = get_outcome_stats(chip_id=chip_id)
    coverage = get_insight_outcome_coverage()

    print("[SPARK] Outcome Statistics")
    print(f"   Total Outcomes: {stats['total_outcomes']}")
    print(f"   By Polarity: +{stats['by_polarity'].get('pos', 0)} / -{stats['by_polarity'].get('neg', 0)} / ~{stats['by_polarity'].get('neutral', 0)}")
    print(f"   Total Links: {stats['total_links']}")
    print(f"   Validated Links: {stats['validated_links']}")
    print(f"   Unlinked Outcomes: {stats['unlinked']}")
    print()
    print("[SPARK] Insight Coverage")
    print(f"   Total Insights: {coverage['total_insights']}")
    print(f"   With Outcomes: {coverage['insights_with_outcomes']}")
    print(f"   Validated: {coverage['insights_validated']}")
    print(f"   Coverage: {coverage['outcome_coverage']:.1%}")
    print(f"   Validation Rate: {coverage['validation_rate']:.1%}")
    print()
    pstate = get_prediction_state()
    kpis = pstate.get("kpis") or {}
    if kpis:
        print("[SPARK] Prediction/Outcome Loop KPIs")
        print(f"   Window: {kpis.get('window_days')} days")
        print(f"   Predictions: {kpis.get('predictions')}")
        print(f"   Outcomes: {kpis.get('outcomes')}")
        print(f"   Prediction:Outcome Ratio: {kpis.get('prediction_to_outcome_ratio'):.3f}")
        print(f"   Unlinked Outcomes: {kpis.get('unlinked_outcomes')}")
        print(f"   Coverage: {kpis.get('coverage', 0):.1%}")
        print(f"   Validated per 100 Predictions: {kpis.get('validated_per_100_predictions'):.2f}")


def cmd_outcome_validate(args):
    """Run outcome-based validation on insights."""
    limit = int(args.limit or 100)
    stats = process_outcome_validation(limit=limit)

    print("[SPARK] Outcome Validation")
    print(f"   Processed: {stats['processed']}")
    print(f"   Validated: {stats['validated']}")
    print(f"   Contradicted: {stats['contradicted']}")
    print(f"   Surprises: {stats['surprises']}")


def cmd_outcome_unlinked(args):
    """List outcomes without insight links."""
    limit = int(args.limit or 20)
    outcomes = get_unlinked_outcomes(limit=limit)

    if not outcomes:
        print("[SPARK] No unlinked outcomes found.")
        return

    print(f"[SPARK] Unlinked Outcomes ({len(outcomes)}):")
    for o in outcomes:
        oid = o.get("outcome_id", "?")[:10]
        pol = o.get("polarity", "?")
        text = (o.get("text") or "")[:60]
        print(f"   [{pol:^7}] {oid}... {text}")


def cmd_outcome_links(args):
    """List outcome-insight links."""
    insight_key = args.insight_key if hasattr(args, 'insight_key') else None
    chip_id = args.chip_id if hasattr(args, 'chip_id') else None
    limit = int(args.limit or 50)

    links = get_outcome_links(insight_key=insight_key, chip_id=chip_id, limit=limit)

    if not links:
        print("[SPARK] No links found.")
        return

    print(f"[SPARK] Outcome-Insight Links ({len(links)}):")
    for link in links:
        lid = link.get("link_id", "?")[:8]
        oid = link.get("outcome_id", "?")[:8]
        ikey = link.get("insight_key", "?")[:30]
        validated = "Y" if link.get("validated") else "N"
        result = link.get("validation_result", "-")
        print(f"   {lid}... {oid}... -> {ikey} [validated={validated} result={result}]")


def cmd_auto_link(args):
    """Auto-link unlinked outcomes to matching insights."""
    min_sim = float(getattr(args, 'min_similarity', 0.25) or 0.25)
    limit = int(getattr(args, 'limit', 50) or 50)
    dry_run = getattr(args, 'dry_run', False)
    preview = getattr(args, 'preview', False)

    if preview:
        candidates = get_linkable_candidates(limit=limit)
        if not candidates:
            print("[SPARK] No linkable candidates found.")
            return
        print(f"[SPARK] Linkable candidates ({len(candidates)}):")
        for c in candidates:
            print(f"   [{c['similarity']:.2f}] {c['outcome_preview'][:40]}...")
            print(f"         -> {c['insight_preview'][:50]}...")
        return

    stats = auto_link_outcomes(min_similarity=min_sim, limit=limit, dry_run=dry_run)

    mode = "DRY RUN" if dry_run else "APPLIED"
    print(f"[SPARK] Auto-Link Outcomes ({mode})")
    print(f"   Processed: {stats['processed']}")
    print(f"   Linked: {stats['linked']}")
    print(f"   Skipped: {stats['skipped']}")

    if stats.get('matches') and len(stats['matches']) > 0:
        print(f"\n   Top matches:")
        for m in stats['matches'][:5]:
            print(f"   [{m['similarity']:.2f}] {m['outcome_preview'][:35]}... -> {m['insight_preview'][:35]}...")


def cmd_sync_banks(args):
    """Sync high-value cognitive insights to memory banks."""
    min_rel = float(getattr(args, 'min_reliability', 0.7) or 0.7)
    dry_run = getattr(args, 'dry_run', False)
    categories = None
    if hasattr(args, 'categories') and args.categories:
        categories = args.categories.split(',')

    stats = sync_insights_to_banks(min_reliability=min_rel, categories=categories, dry_run=dry_run)

    mode = "DRY RUN" if dry_run else "APPLIED"
    print(f"[SPARK] Sync Insights to Banks ({mode})")
    print(f"   Processed: {stats['processed']}")
    print(f"   Synced: {stats['synced']}")
    print(f"   Skipped (low reliability): {stats['skipped']}")
    print(f"   Duplicates: {stats['duplicates']}")

    if stats.get('entries') and len(stats['entries']) > 0:
        print(f"\n   Synced entries ({len(stats['entries'])}):")
        for e in stats['entries'][:10]:
            print(f"   [{e['reliability']:.0%}] {e['category']}: {e['preview'][:50]}...")


def cmd_bank_stats(args):
    """Show memory bank statistics."""
    stats = get_bank_stats()

    print("[SPARK] Memory Bank Stats")
    print(f"   Global entries: {stats['global_entries']}")
    print(f"   Project files: {stats['project_files']}")

    if stats['project_counts']:
        print("\n   Projects:")
        for name, count in stats['project_counts'].items():
            print(f"      - {name}: {count}")

    if stats['by_category']:
        print("\n   By category:")
        for cat, count in stats['by_category'].items():
            print(f"      - {cat}: {count}")


def cmd_memory_purge_telemetry(args):
    """Purge telemetry noise from the SQLite memory store."""
    stats = purge_telemetry_memories(dry_run=bool(getattr(args, "dry_run", False)))
    mode = "DRY RUN" if getattr(args, "dry_run", False) else "APPLIED"
    print(f"[SPARK] Memory Store Telemetry Purge ({mode})")
    print(f"   Removed: {stats.get('removed', 0)}")
    preview = stats.get("preview") or []
    if preview:
        print("   Preview:")
        for item in preview[:10]:
            print(f"      - {item}")


def cmd_eidos_purge_telemetry(args):
    """Purge telemetry noise from EIDOS distillations."""
    stats = purge_telemetry_distillations(dry_run=bool(getattr(args, "dry_run", False)))
    mode = "DRY RUN" if getattr(args, "dry_run", False) else "APPLIED"
    print(f"[SPARK] EIDOS Distillation Telemetry Purge ({mode})")
    print(f"   Scanned: {stats.get('scanned', 0)}")
    print(f"   Removed: {stats.get('removed', 0)}")
    preview = stats.get("preview") or []
    if preview:
        print("   Preview:")
        for item in preview[:10]:
            print(f"      - {item}")


def cmd_validate_ingest(args):
    """Validate recent queue events for schema issues."""
    stats = scan_queue_events(limit=args.limit)
    if not args.no_write:
        write_ingest_report(stats)
    print("[SPARK] Ingest validation")
    print(f"   Processed: {stats['processed']}")
    print(f"   Valid: {stats['valid']}")
    print(f"   Invalid: {stats['invalid']}")
    if stats["reasons"]:
        print("   Reasons:")
        for k, v in stats["reasons"].items():
            print(f"     - {k}: {v}")


def _print_project_questions(profile, limit: int = 5):
    suggested = get_suggested_questions(profile, limit=limit)
    if not suggested:
        print("[SPARK] No unanswered questions.")
        return
    print("[SPARK] Suggested questions:")
    for q in suggested:
        cat = q.get("category") or "general"
        qid = q.get("id") or "unknown"
        text = q.get("question") or ""
        print(f"   - [{cat}] {qid}: {text}")


def cmd_project_init(args):
    profile = load_profile(Path(args.project) if args.project else None)
    if args.domain:
        profile["domain"] = args.domain
        save_profile(profile)
    if not profile.get("domain"):
        profile["domain"] = infer_domain(Path(args.project) if args.project else None)
        save_profile(profile)
    added = ensure_questions(profile)
    print(f"[SPARK] Project: {profile.get('project_key')}  Domain: {profile.get('domain')}")
    if added:
        print(f"[SPARK] Added {added} domain questions")
    _print_project_questions(profile, args.limit)


def cmd_project_status(args):
    profile = load_profile(Path(args.project) if args.project else None)
    score = completion_score(profile)
    print(f"[SPARK] Project: {profile.get('project_key')}")
    print(f"   Domain: {profile.get('domain')}")
    print(f"   Phase: {profile.get('phase')}")
    print(f"   Completion Score: {score['score']}/100")
    print(f"   Goals: {len(profile.get('goals') or [])}")
    print(f"   Done: {'set' if profile.get('done') else 'not set'}")
    print(f"   Milestones: {len(profile.get('milestones') or [])}")
    print(f"   Decisions: {len(profile.get('decisions') or [])}")
    print(f"   Insights: {len(profile.get('insights') or [])}")
    print(f"   Feedback: {len(profile.get('feedback') or [])}")
    print(f"   Risks: {len(profile.get('risks') or [])}")
    print(f"   References: {len(profile.get('references') or [])}")
    print(f"   Transfers: {len(profile.get('transfers') or [])}")
    questions = profile.get("questions") or []
    answered = len([q for q in questions if q.get("answered_at")])
    print(f"   Questions answered: {answered}/{len(questions)}")


def cmd_project_questions(args):
    profile = load_profile(Path(args.project) if args.project else None)
    ensure_questions(profile)
    _print_project_questions(profile, args.limit)


def cmd_project_answer(args):
    profile = load_profile(Path(args.project) if args.project else None)
    ensure_questions(profile)
    entry = record_answer(profile, args.id, args.text or "")
    if not entry:
        print("[SPARK] Answer not recorded (missing id or text).")
        return
    # Store as project-scoped memory for retrieval
    qtext = ""
    for q in profile.get("questions") or []:
        if q.get("id") == args.id:
            qtext = q.get("question") or ""
            break
    note = f"{qtext} Answer: {args.text}".strip() if qtext else (args.text or "").strip()
    if note:
        store_memory(note, category=f"project_answer:{entry.get('category') or 'general'}")
    print("[SPARK] Answer recorded.")


def cmd_project_capture(args):
    profile = load_profile(Path(args.project) if args.project else None)
    entry_type = args.type
    text = (args.text or "").strip()
    if not text:
        print("[SPARK] Missing --text")
        return
    meta = {}
    if args.status:
        meta["status"] = args.status
    if args.why:
        meta["why"] = args.why
    if args.impact:
        meta["impact"] = args.impact
    if args.evidence:
        meta["evidence"] = args.evidence

    if entry_type == "done":
        profile["done"] = text
        save_profile(profile)
    entry = record_entry(profile, entry_type, text, meta=meta)

    category_map = {
        "goal": "project_goal",
        "done": "project_done",
        "milestone": "project_milestone",
        "decision": "project_decision",
        "insight": "project_insight",
        "feedback": "project_feedback",
        "risk": "project_risk",
        "reference": "project_reference",
        "transfer": "project_transfer",
    }
    store_memory(text, category=category_map.get(entry_type, "project_note"))

    # If milestone or done is marked complete, record an outcome for validation.
    status = (args.status or "").strip().lower()
    if entry_type == "done" or (entry_type == "milestone" and status in ("done", "complete", "completed")):
        sid = infer_latest_session_id()
        outcome_text = f"{entry_type} complete: {text}"
        append_outcome({
            "outcome_id": make_outcome_id(profile.get("project_key") or "project", entry.get("entry_id") or "", "done"),
            "event_type": "project_outcome",
            "text": outcome_text,
            "polarity": "pos",
            "created_at": time.time(),
            "project_key": profile.get("project_key"),
            "domain": profile.get("domain"),
            "entity_id": entry.get("entry_id"),
            "session_id": sid,
        })
    else:
        project_key = profile.get("project_key") or "project"
        if entry_type == "reference":
            record_checkin_request(
                session_id=f"project:{project_key}",
                event="project_transfer",
                reason=f"Transfer from reference: {text[:140]}",
            )
        elif entry_type in ("decision", "milestone", "transfer"):
            record_checkin_request(
                session_id=f"project:{project_key}",
                event=f"project_{entry_type}",
                reason=text[:160],
            )
    print(f"[SPARK] Captured {entry_type}.")


def cmd_project_phase(args):
    profile = load_profile(Path(args.project) if args.project else None)
    if args.set_phase:
        set_phase(profile, args.set_phase)
        ensure_questions(profile)
        print(f"[SPARK] Phase set: {profile.get('phase')}")
    else:
        print(f"[SPARK] Phase: {profile.get('phase')}")

def cmd_surprises(args):
    """Show surprise moments (aha!)."""
    aha = get_aha_tracker()
    
    if args.insights:
        # Show insights/analysis
        insights = aha.get_insights()
        print("\nðŸ’¡ Surprise Analysis\n")
        for key, value in insights.items():
            if key != "recommendations":
                print(f"   {key}: {value}")
        if insights.get("recommendations"):
            print("\n   Recommendations:")
            for r in insights["recommendations"]:
                print(f"      - {r}")
        print()
        return
    
    if args.surface:
        # Surface pending surprises
        pending = aha.surface_all_pending()
        if pending:
            print("\nðŸ’¡ Surfacing Surprises:\n")
            for s in pending:
                print(s)
                print()
        else:
            print("\nNo pending surprises to surface.")
        return
    
    # Show recent surprises
    limit = args.limit or 10
    surprises = aha.get_recent_surprises(limit)
    
    print(f"\nðŸ’¡ Recent Surprises (showing {len(surprises)})\n")
    
    for s in surprises:
        print(s.format_visible())
        print()
    
    if not surprises:
        print("   No surprises captured yet.")
        print("   Surprises happen when predictions don't match outcomes.")
        print()


def cmd_voice(args):
    """Show or interact with Spark's personality."""
    voice = get_spark_voice()
    
    if args.introduce:
        print("\n" + voice.introduce())
        return
    
    if args.opinions:
        opinions = voice.get_strong_opinions() if args.strong else voice.get_opinions()
        print(f"\nðŸŽ­ Spark's Opinions ({len(opinions)} total)\n")
        for o in opinions:
            strength = "strongly" if o.strength > 0.8 else "tends to"
            print(f"   [{o.topic}] {strength} prefer {o.preference}")
            print(f"      Reason: {o.reason}")
            print(f"      Strength: {o.strength:.0%}")
            print()
        return
    
    if args.growth:
        moments = voice.get_recent_growth(args.limit or 5)
        print(f"\nðŸ“ˆ Growth Moments ({len(moments)})\n")
        for m in moments:
            print(f"   Before: {m.before}")
            print(f"   After: {m.after}")
            print(f"   Trigger: {m.trigger}")
            print()
        return
    
    # Default: show status
    stats = voice.get_stats()
    print("\nðŸŽ­ Spark Voice Status\n")
    print(f"   {voice.get_status_voice()}")
    print()
    print(f"   Age: {stats['age_days']} days")
    print(f"   Interactions: {stats['interactions']}")
    print(f"   Opinions: {stats['opinions_formed']} ({stats['strong_opinions']} strong)")
    print(f"   Growth moments: {stats['growth_moments']}")
    print()


def cmd_personality_evolution(args):
    """Inspect/apply/reset bounded user-guided personality evolution state."""
    evolver = load_personality_evolver(
        state_path=(Path(args.state_path).expanduser() if getattr(args, "state_path", None) else None)
    )

    if args.evolution_cmd in (None, "inspect"):
        print(
            json.dumps(
                {
                    "enabled": evolver.enabled,
                    "observer_mode": evolver.observer_mode,
                    "state_path": str(evolver.state_path),
                    "state": evolver.state,
                    "style_profile": evolver.emit_style_profile(),
                },
                indent=2,
            )
        )
        return

    if args.evolution_cmd == "apply":
        if args.signals:
            signals = json.loads(args.signals)
        elif args.signals_file:
            signals = json.loads(Path(args.signals_file).expanduser().read_text(encoding="utf-8"))
        else:
            raise SystemExit("Missing --signals or --signals-file")
        result = evolver.ingest_signals(signals, persist=True)
        print(json.dumps(result, indent=2))
        return

    if args.evolution_cmd == "reset":
        if not args.yes:
            raise SystemExit("Refusing reset without --yes")
        state = evolver.reset_state(persist=True)
        print(json.dumps({"reset": True, "state": state}, indent=2))
        return


def cmd_bridge(args):
    """Bridge learnings to operational context."""
    from lib.bridge import (
        generate_active_context, 
        update_spark_context, 
        auto_promote_insights,
        bridge_status
    )
    
    if args.update:
        update_spark_context(query=args.query)
        print("âœ“ Updated SPARK_CONTEXT.md with active learnings")
    elif args.promote:
        count = auto_promote_insights()
        if count > 0:
            print(f"âœ“ Promoted {count} high-value insights to MEMORY.md")
        else:
            print("No insights ready for promotion yet")
    elif args.status:
        status = bridge_status()
        print(f"\n  Bridge Status")
        print(f"  {'â”€' * 30}")
        print(f"  High-value insights: {status['high_value_insights']}")
        print(f"  Lessons learned: {status['lessons_learned']}")
        print(f"  Strong opinions: {status['strong_opinions']}")
        print(f"  Context file: {'âœ“' if status['context_exists'] else 'âœ—'}")
        print(f"  Memory file: {'âœ“' if status['memory_exists'] else 'âœ—'}")
        print()
    else:
        # Default: show active context
        print(generate_active_context())


def cmd_importance(args):
    """Test and visualize importance scoring."""
    from lib.importance_scorer import get_importance_scorer, ImportanceTier

    scorer = get_importance_scorer(domain=args.domain)

    if args.feedback:
        # Show feedback statistics
        stats = scorer.get_feedback_stats()
        print(f"\n{'=' * 60}")
        print(f"  Importance Prediction Feedback")
        print(f"{'=' * 60}")
        print(f"\n  Total Predictions: {stats['total']}")
        print(f"  Correct: {stats['correct']}")
        print(f"  Accuracy: {stats['accuracy']:.1%}")

        if stats.get("by_tier"):
            print(f"\n  By Tier:")
            for tier, tier_stats in stats["by_tier"].items():
                tier_acc = tier_stats["correct"] / tier_stats["total"] if tier_stats["total"] > 0 else 0
                print(f"    {tier}: {tier_stats['correct']}/{tier_stats['total']} ({tier_acc:.1%})")
        print()
        return

    if args.text:
        # Score a single text
        if args.semantic:
            score = scorer.score_with_semantics(args.text, context={"source": args.source} if args.source else None)
        else:
            score = scorer.score(args.text, context={"source": args.source} if args.source else None)

        tier_colors = {
            "critical": "ðŸ”´",
            "high": "ðŸŸ ",
            "medium": "ðŸŸ¡",
            "low": "âšª",
            "ignore": "âš«",
        }

        print(f"\n{'=' * 60}")
        print(f"  Importance Scoring Result {'(with semantics)' if args.semantic else ''}")
        print(f"{'=' * 60}")
        print(f"\n  Text: {args.text[:100]}{'...' if len(args.text) > 100 else ''}")
        print(f"\n  {tier_colors[score.tier.value]} Tier: {score.tier.value.upper()}")
        print(f"  Score: {score.score:.2f}")
        print(f"  Domain Relevance: {score.domain_relevance:.2f}")

        if score.first_mention_elevation:
            print(f"  First Mention: YES (elevated)")

        if score.question_match:
            print(f"  Question Match: {score.question_match}")

        if score.reasons:
            print(f"\n  Reasons:")
            for r in score.reasons:
                print(f"    - {r}")

        if score.signals_detected:
            print(f"\n  Signals Detected:")
            for s in score.signals_detected:
                print(f"    - {s}")

        print(f"\n  Should Learn: {'YES' if score.tier in (ImportanceTier.CRITICAL, ImportanceTier.HIGH, ImportanceTier.MEDIUM) else 'NO'}")
        print(f"  Should Promote: {'YES' if score.tier in (ImportanceTier.CRITICAL, ImportanceTier.HIGH) else 'NO'}")
        print()
        return

    if args.examples:
        # Show example scorings
        examples = [
            ("Remember this: always use forward slashes on Windows", "explicit_remember"),
            ("I prefer dark mode for all my apps", "preference"),
            ("No, I meant use the other approach", "correction"),
            ("The balance is set to 300 for better gameplay feel", "domain_decision"),
            ("Okay, got it", "acknowledgment"),
            ("Bash -> Edit -> Write sequence works", "tool_sequence"),
            ("This works because the offset compensates for physics drift", "reasoning"),
            ("Ship fast, iterate faster", "principle"),
        ]

        print(f"\n{'=' * 60}")
        print(f"  Importance Scoring Examples")
        print(f"{'=' * 60}")

        for text, expected in examples:
            score = scorer.score(text)
            tier_colors = {
                "critical": "ðŸ”´",
                "high": "ðŸŸ ",
                "medium": "ðŸŸ¡",
                "low": "âšª",
                "ignore": "âš«",
            }
            print(f"\n  {tier_colors[score.tier.value]} [{score.tier.value.upper():8}] ({score.score:.2f})")
            print(f"    \"{text[:60]}{'...' if len(text) > 60 else ''}\"")
            if score.signals_detected:
                print(f"    Signals: {', '.join(score.signals_detected[:3])}")
        print()
        return

    # Default: show scorer stats
    print(f"\n{'=' * 60}")
    print(f"  Importance Scorer Status")
    print(f"{'=' * 60}")
    print(f"\n  Active Domain: {scorer.active_domain or '(none)'}")
    print(f"  Seen Signals: {len(scorer.seen_signals)}")
    print(f"  Question Answers: {len(scorer.question_answers)}")
    print(f"\n  Use --text \"your text\" to score specific text")
    print(f"  Use --examples to see example scorings")
    print()


def cmd_curiosity(args):
    """Explore knowledge gaps and questions. (DEPRECATED: not wired into production pipeline)"""
    import warnings
    warnings.warn("curiosity_engine is deprecated — not wired into production advisory pipeline", DeprecationWarning)
    from lib.curiosity_engine import get_curiosity_engine

    engine = get_curiosity_engine()

    if args.questions:
        gaps = engine.get_open_questions(limit=args.limit or 10)
        print(f"\n{'=' * 60}")
        print(f"  Open Questions ({len(gaps)})")
        print(f"{'=' * 60}")
        for gap in gaps:
            print(f"\n  [{gap.gap_type.value.upper()}] {gap.question}")
            print(f"    Topic: {gap.topic}")
            print(f"    Priority: {gap.priority:.2f}")
            if gap.source_insight:
                print(f"    From: {gap.source_insight[:60]}...")
        print()
        return

    if args.fill:
        gap_id = args.fill
        answer = args.answer or ""
        valuable = not args.not_valuable
        engine.fill_gap(gap_id, answer, valuable)
        print(f"[SPARK] Gap {gap_id} filled. Valuable: {valuable}")
        return

    # Default: show stats
    stats = engine.get_stats()
    print(f"\n{'=' * 60}")
    print(f"  Curiosity Engine Status")
    print(f"{'=' * 60}")
    print(f"\n  Total Gaps: {stats['total_gaps']}")
    print(f"  Filled: {stats['filled']}")
    print(f"  Unfilled: {stats['unfilled']}")
    print(f"  Valuable Answers: {stats['valuable_answers']}")
    print(f"  Value Rate: {stats['value_rate']:.1%}")
    print(f"\n  Use --questions to see open questions")
    print()


def cmd_hypotheses(args):
    """Track and validate hypotheses."""
    from lib.hypothesis_tracker import get_hypothesis_tracker

    tracker = get_hypothesis_tracker()

    if args.testable:
        hypotheses = tracker.get_testable_hypotheses(limit=args.limit or 5)
        print(f"\n{'=' * 60}")
        print(f"  Testable Hypotheses ({len(hypotheses)})")
        print(f"{'=' * 60}")
        for h in hypotheses:
            print(f"\n  [{h.state.value.upper()}] {h.statement[:80]}")
            print(f"    ID: {h.hypothesis_id}")
            print(f"    Confidence: {h.confidence:.2f}")
            print(f"    Predictions: {len(h.predictions)} ({h.sample_size} with outcomes)")
            print(f"    Accuracy: {h.accuracy:.1%}")
        print()
        return

    if args.pending:
        pending = tracker.get_pending_predictions()
        print(f"\n{'=' * 60}")
        print(f"  Pending Predictions ({len(pending)})")
        print(f"{'=' * 60}")
        for h_id, idx, h, p in pending[:args.limit or 10]:
            print(f"\n  Hypothesis: {h.statement[:60]}...")
            print(f"    Prediction: {p.prediction_text}")
            print(f"    Context: {p.context[:40]}...")
            print(f"    ID: {h_id}:{idx}")
        print()
        return

    if args.outcome:
        parts = args.outcome.split(":")
        if len(parts) != 2:
            print("[SPARK] Invalid format. Use: --outcome <hypothesis_id>:<prediction_index>")
            return
        h_id, idx = parts[0], int(parts[1])
        correct = args.correct
        tracker.record_outcome(h_id, idx, correct, args.notes or "")
        print(f"[SPARK] Outcome recorded: {'correct' if correct else 'incorrect'}")
        return

    # Default: show stats
    stats = tracker.get_stats()
    print(f"\n{'=' * 60}")
    print(f"  Hypothesis Tracker Status")
    print(f"{'=' * 60}")
    print(f"\n  Total Hypotheses: {stats['total_hypotheses']}")
    print(f"  Total Predictions: {stats['total_predictions']}")
    print(f"  Outcomes Recorded: {stats['outcomes_recorded']}")
    print(f"  Pending Outcomes: {stats['pending_outcomes']}")
    print(f"  Validated: {stats['validated_count']}")
    if stats['validated_count'] > 0:
        print(f"  Avg Validated Accuracy: {stats['avg_validated_accuracy']:.1%}")
    print(f"\n  By State:")
    for state, count in stats['by_state'].items():
        print(f"    {state}: {count}")
    print()


def cmd_contradictions(args):
    """View and resolve contradictions."""
    from lib.contradiction_detector import get_contradiction_detector

    detector = get_contradiction_detector()

    if args.unresolved:
        unresolved = detector.get_unresolved()
        print(f"\n{'=' * 60}")
        print(f"  Unresolved Contradictions ({len(unresolved)})")
        print(f"{'=' * 60}")
        for idx, c in unresolved[:args.limit or 10]:
            print(f"\n  [{idx}] {c.contradiction_type.value.upper()} (confidence: {c.confidence:.2f})")
            print(f"    Existing: {c.existing_text[:60]}...")
            print(f"    New: {c.new_text[:60]}...")
        print()
        return

    if args.resolve is not None:
        idx = args.resolve
        res_type = args.resolution_type or "context"
        res = args.resolution or ""
        detector.resolve(idx, res_type, res)
        print(f"[SPARK] Contradiction {idx} resolved as: {res_type}")
        return

    # Default: show stats
    stats = detector.get_stats()
    print(f"\n{'=' * 60}")
    print(f"  Contradiction Detector Status")
    print(f"{'=' * 60}")
    print(f"\n  Total Detected: {stats['total']}")
    print(f"  Resolved: {stats['resolved']}")
    print(f"  Unresolved: {stats['unresolved']}")
    print(f"\n  By Type:")
    for t, count in stats.get('by_type', {}).items():
        print(f"    {t}: {count}")
    if stats.get('resolution_types'):
        print(f"\n  Resolution Types:")
        for t, count in stats['resolution_types'].items():
            print(f"    {t}: {count}")
    print()


def cmd_eidos(args):
    """EIDOS - Self-evolving intelligence system."""
    from lib.eidos import (
        get_store, get_control_plane, get_distillation_engine,
        Episode, Step, Distillation, Policy,
        Phase, Outcome, DistillationType,
        get_metrics_calculator, get_evidence_store,
        run_full_migration, validate_migration,
        get_deferred_tracker
    )

    store = get_store()

    # Metrics command
    if args.metrics:
        calc = get_metrics_calculator()
        metrics = calc.all_metrics()

        print(f"\n{'=' * 60}")
        print(f"  EIDOS Intelligence Metrics")
        print(f"{'=' * 60}")

        # North Star
        ns = metrics["north_star"]
        status = "[OK]" if ns["status"] == "on_track" else "[!!]"
        print(f"\n  {status} COMPOUNDING RATE: {ns['compounding_rate_pct']}% (target: {ns['target']}%)")

        # Effectiveness
        eff = metrics["effectiveness"]
        print(f"\n  Memory Effectiveness:")
        print(f"    With memory:    {eff['with_memory']['rate_pct']}% ({eff['with_memory']['successes']}/{eff['with_memory']['episodes']})")
        print(f"    Without memory: {eff['without_memory']['rate_pct']}% ({eff['without_memory']['successes']}/{eff['without_memory']['episodes']})")
        print(f"    Advantage:      {eff['memory_advantage_pct']}%")

        # Loop Suppression
        loops = metrics["loop_suppression"]
        print(f"\n  Loop Suppression:")
        print(f"    Avg retries: {loops['avg_retries']} (target: <{loops['target_max']})")
        print(f"    Max retries: {loops['max_retries']}")

        # Weekly
        weekly = metrics["weekly"]
        print(f"\n  This Week:")
        print(f"    Episodes: {weekly['episodes']} ({weekly['success_rate_pct']}% success)")
        print(f"    New rules: {weekly['new_heuristics']} heuristics, {weekly['new_sharp_edges']} sharp edges")
        print()
        return

    # Evidence command
    if args.evidence:
        ev_store = get_evidence_store()
        ev_stats = ev_store.get_stats()

        print(f"\n{'=' * 60}")
        print(f"  EIDOS Evidence Store")
        print(f"{'=' * 60}")
        print(f"\n  Total Items: {ev_stats['total_items']}")
        print(f"  Total Size: {ev_stats['total_bytes'] / 1024:.1f} KB")
        print(f"  Expiring in 24h: {ev_stats['expiring_in_24h']}")
        print(f"  Permanent: {ev_stats['permanent']}")

        if ev_stats['by_type']:
            print(f"\n  By Type:")
            for t, data in ev_stats['by_type'].items():
                print(f"    {t}: {data['count']} ({data['bytes'] / 1024:.1f} KB)")
        print()
        return

    # Migrate command
    if args.migrate:
        print(f"\n{'=' * 60}")
        print(f"  EIDOS Migration")
        print(f"{'=' * 60}")

        dry_run = args.dry_run
        if dry_run:
            print("\n  [DRY RUN] No changes will be made.\n")

        results = run_full_migration(dry_run=dry_run)

        print(f"  Insights migrated: {results['insights']['insights_migrated']}")
        print(f"  Insights skipped:  {results['insights']['insights_skipped']}")
        print(f"  Patterns archived: {results['patterns_archived']}")
        print(f"  Policies created:  {results['policies_created']}")

        if results['insights']['errors']:
            print(f"\n  Errors:")
            for err in results['insights']['errors'][:5]:
                print(f"    - {err}")

        print(f"\n  Duration: {results['duration_seconds']:.1f}s")
        print()
        return

    # Validate migration command
    if args.validate_migration:
        results = validate_migration()

        print(f"\n{'=' * 60}")
        print(f"  EIDOS Migration Validation")
        print(f"{'=' * 60}")
        print(f"\n  Tables exist: {results['eidos_tables_exist']}")
        print(f"  Distillations: {results['distillations_count']}")
        print(f"  Policies: {results['policies_count']}")
        print(f"  Episodes: {results['episodes_count']}")
        print(f"  Steps: {results['steps_count']}")
        print(f"  Backup exists: {results['backup_exists']}")
        print(f"  Patterns archived: {results['patterns_archived']}")

        status = "[OK]" if results['valid'] else "[!!]"
        print(f"\n  {status} Migration valid: {results['valid']}")
        print()
        return

    # Deferred validations command
    if args.deferred:
        tracker = get_deferred_tracker()
        stats = tracker.get_stats()

        print(f"\n{'=' * 60}")
        print(f"  Deferred Validations")
        print(f"{'=' * 60}")
        print(f"\n  Total: {stats['total']}")
        print(f"  Resolved: {stats['resolved']}")
        print(f"  Pending: {stats['pending']}")
        print(f"  Overdue: {stats['overdue']}")

        if stats['by_reason']:
            print(f"\n  By Reason:")
            for reason, data in stats['by_reason'].items():
                print(f"    {reason}: {data['total']} ({data['resolved']} resolved)")

        # Show overdue items
        overdue = tracker.get_overdue()
        if overdue:
            print(f"\n  Overdue Items:")
            for d in overdue[:5]:
                hours = (time.time() - d.deferred_at) / 3600
                print(f"    - {d.step_id}: {d.reason} ({hours:.1f}h ago)")
        print()
        return

    if args.stats:
        stats = store.get_stats()
        print(f"\n{'=' * 60}")
        print(f"  EIDOS Intelligence Store")
        print(f"{'=' * 60}")
        print(f"\n  Episodes: {stats['episodes']}")
        print(f"  Steps: {stats['steps']}")
        print(f"  Distillations: {stats['distillations']}")
        print(f"  Policies: {stats['policies']}")
        print(f"  Success Rate: {stats['success_rate']:.1%}")
        print(f"  High-Confidence Distillations: {stats['high_confidence_distillations']}")
        print(f"\n  Database: {stats['db_path']}")
        print()
        return

    if args.episodes:
        episodes = store.get_recent_episodes(limit=args.limit or 10)
        print(f"\n{'=' * 60}")
        print(f"  Recent Episodes ({len(episodes)})")
        print(f"{'=' * 60}")
        for ep in episodes:
            status_icon = {
                "success": "âœ“",
                "failure": "âœ—",
                "partial": "~",
                "escalated": "â†‘",
                "in_progress": "..."
            }.get(ep.outcome.value, "?")
            print(f"\n  [{status_icon}] {ep.goal[:60]}")
            print(f"      ID: {ep.episode_id}")
            print(f"      Phase: {ep.phase.value} | Outcome: {ep.outcome.value}")
            print(f"      Steps: {ep.step_count}/{ep.budget.max_steps}")
        print()
        return

    if args.distillations:
        dtype = None
        if args.type:
            dtype = DistillationType(args.type)
            distillations = store.get_distillations_by_type(dtype, limit=args.limit or 20)
        else:
            distillations = store.get_high_confidence_distillations(
                min_confidence=0.5, limit=args.limit or 20
            )
        print(f"\n{'=' * 60}")
        print(f"  Distillations ({len(distillations)})")
        print(f"{'=' * 60}")
        for d in distillations:
            type_icon = {
                "heuristic": "â†’",
                "sharp_edge": "âš ",
                "anti_pattern": "âœ—",
                "playbook": "ðŸ“‹",
                "policy": "ðŸ“œ"
            }.get(d.type.value, "â€¢")
            print(f"\n  [{type_icon}] {d.statement[:70]}")
            print(f"      Confidence: {d.confidence:.2f} | Used: {d.times_used} | Helped: {d.times_helped}")
            if d.domains:
                print(f"      Domains: {', '.join(d.domains[:3])}")
        print()
        return

    if args.policies:
        policies = store.get_all_policies()
        print(f"\n{'=' * 60}")
        print(f"  Policies ({len(policies)})")
        print(f"{'=' * 60}")
        for p in policies:
            print(f"\n  [{p.scope}:{p.priority}] {p.statement[:60]}")
            print(f"      Source: {p.source}")
        print()
        return

    if args.steps:
        episode_id = args.episode
        if episode_id:
            steps = store.get_episode_steps(episode_id)
        else:
            steps = store.get_recent_steps(limit=args.limit or 20)
        print(f"\n{'=' * 60}")
        print(f"  Steps ({len(steps)})")
        print(f"{'=' * 60}")
        for s in steps:
            eval_icon = {
                "pass": "âœ“",
                "fail": "âœ—",
                "partial": "~",
                "unknown": "?"
            }.get(s.evaluation.value, "?")
            print(f"\n  [{eval_icon}] {s.intent[:50]}")
            print(f"      Decision: {s.decision[:50]}")
            print(f"      Confidence: {s.confidence_before:.2f} â†’ {s.confidence_after:.2f}")
            if s.lesson:
                print(f"      Lesson: {s.lesson[:50]}")
        print()
        return

    # Default: show overview
    stats = store.get_stats()
    print(f"\n{'=' * 60}")
    print(f"  EIDOS: Self-Evolving Intelligence")
    print(f"{'=' * 60}")
    print(f"""
  EIDOS forces learning through:
  â€¢ Decision packets (not just logs)
  â€¢ Prediction â†’ Outcome â†’ Evaluation loops
  â€¢ Memory binding (retrieval required)
  â€¢ Distillation (experience â†’ rules)

  Current State:
    Episodes: {stats['episodes']}
    Steps: {stats['steps']}
    Distillations: {stats['distillations']}
    Policies: {stats['policies']}

  Commands:
    --stats         Show detailed statistics
    --episodes      List recent episodes
    --distillations List distillations
    --policies      List policies
    --steps         List recent steps
    --episode <id>  Show steps for specific episode
""")


def _pick_advisory_option(question: dict, current_value: str) -> str:
    options = question.get("options") or []
    if not options:
        return str(current_value or "")

    current = str(current_value or "").strip().lower()
    default_idx = 1
    for idx, opt in enumerate(options, start=1):
        value = str(opt.get("value") or "").strip().lower()
        if value == current:
            default_idx = idx
            break

    print()
    print(question.get("question") or "Choose an option:")
    for idx, opt in enumerate(options, start=1):
        label = str(opt.get("label") or opt.get("value") or f"Option {idx}")
        description = str(opt.get("description") or "").strip()
        marker = " (current)" if idx == default_idx else ""
        print(f"  {idx}. {label}{marker}")
        if description:
            print(f"     {description}")

    if not sys.stdin.isatty():
        return str(options[default_idx - 1].get("value") or current_value)

    while True:
        raw = input(f"Select [default {default_idx}]: ").strip()
        if not raw:
            return str(options[default_idx - 1].get("value") or current_value)
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(options):
                return str(options[choice - 1].get("value") or current_value)
        print("Invalid selection. Enter the option number.")


def _print_advisory_preferences(preferences: dict) -> None:
    effective = preferences.get("effective") if isinstance(preferences.get("effective"), dict) else {}
    runtime = preferences.get("runtime") if isinstance(preferences.get("runtime"), dict) else {}
    drift = preferences.get("drift") if isinstance(preferences.get("drift"), dict) else {}
    memory_mode = str(preferences.get("memory_mode") or "standard")
    guidance_style = str(preferences.get("guidance_style") or "balanced")
    replay_on = bool(effective.get("replay_enabled", memory_mode != "off"))
    runtime_available = bool(runtime.get("available"))
    runtime_on = bool(runtime.get("engine_enabled")) and bool(runtime.get("emitter_enabled"))
    advisory_on = runtime_on and replay_on if runtime_available else replay_on

    print("[SPARK] Advisory Preferences")
    print(f"  advisory_on: {'yes' if advisory_on else 'no'}")
    if runtime_available:
        print(f"  advisory_runtime: {'up' if runtime_on else 'down'}")
    print(f"  replay_advisory: {'on' if replay_on else 'off'}")
    print(f"  memory_mode: {memory_mode}")
    print(f"  guidance_style: {guidance_style}")
    if "max_items" in effective:
        print(f"  max_items: {effective.get('max_items')}")
    if "min_rank_score" in effective:
        print(f"  min_rank_score: {effective.get('min_rank_score')}")
    if runtime_available and "synth_tier" in runtime:
        print(f"  synth_tier: {runtime.get('synth_tier')}")
    if drift.get("has_drift"):
        print(f"  profile_drift: yes ({drift.get('count', 0)} overrides)")
    else:
        print("  profile_drift: no")


def _get_advisory_runtime_state() -> dict:
    """Best-effort runtime status for end-to-end advisory ON/OFF reporting."""
    try:
        from lib.advisory_engine import get_engine_status

        status = get_engine_status()
    except Exception:
        return {"available": False}

    if not isinstance(status, dict):
        return {"available": False}
    emitter = status.get("emitter") if isinstance(status.get("emitter"), dict) else {}
    synth = status.get("synthesizer") if isinstance(status.get("synthesizer"), dict) else {}
    return {
        "available": True,
        "engine_enabled": bool(status.get("enabled")),
        "emitter_enabled": bool(emitter.get("enabled")),
        "synth_tier": str(synth.get("tier_label") or ""),
        "synth_ai_available": bool(synth.get("ai_available")),
        "preferred_provider": str(synth.get("preferred_provider") or "auto"),
        "providers": synth.get("providers") if isinstance(synth.get("providers"), dict) else {},
        "minimax_model": str(synth.get("minimax_model") or ""),
    }


def _with_advisory_runtime(preferences: dict) -> dict:
    out = dict(preferences or {})
    out["runtime"] = _get_advisory_runtime_state()
    return out


_ADVISORY_PROVIDER_META = {
    "auto": {
        "service": "Auto",
        "key_envs": [],
        "note": "Tries available providers in order.",
    },
    "ollama": {
        "service": "Ollama",
        "key_envs": [],
        "note": "Local model service; no API key needed.",
    },
    "minimax": {
        "service": "MiniMax",
        "key_envs": ["MINIMAX_API_KEY", "SPARK_MINIMAX_API_KEY"],
        "note": "Recommended model: MiniMax-M2.5",
    },
    "openai": {
        "service": "OpenAI",
        "key_envs": ["OPENAI_API_KEY", "CODEX_API_KEY"],
        "note": "Use a valid OpenAI-compatible key.",
    },
    "anthropic": {
        "service": "Anthropic",
        "key_envs": ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
        "note": "Use a valid Anthropic key.",
    },
    "gemini": {
        "service": "Google Gemini",
        "key_envs": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "note": "Use a valid Google AI key.",
    },
}


def _advisory_provider_meta(provider: str) -> dict:
    key = str(provider or "auto").strip().lower()
    return _ADVISORY_PROVIDER_META.get(key, _ADVISORY_PROVIDER_META["auto"])


def _advisory_doctor_snapshot() -> dict:
    prefs = _with_advisory_runtime(get_current_advisory_preferences())
    effective = prefs.get("effective") if isinstance(prefs.get("effective"), dict) else {}
    drift = prefs.get("drift") if isinstance(prefs.get("drift"), dict) else {}
    runtime = prefs.get("runtime") if isinstance(prefs.get("runtime"), dict) else {}

    replay_on = bool(effective.get("replay_enabled", prefs.get("memory_mode") != "off"))
    runtime_up = bool(runtime.get("engine_enabled")) and bool(runtime.get("emitter_enabled"))
    advisory_on = replay_on and runtime_up if runtime.get("available") else replay_on

    recommendations = []
    if not runtime_up:
        recommendations.append("spark up")
    if not replay_on:
        recommendations.append("spark advisory on")
    if drift.get("has_drift"):
        recommendations.append("spark advisory repair")
    preferred = str(runtime.get("preferred_provider") or "auto")
    if not bool(runtime.get("synth_ai_available")):
        if preferred == "minimax":
            recommendations.append("Set MINIMAX_API_KEY (or SPARK_MINIMAX_API_KEY), then rerun doctor")
        else:
            recommendations.append("spark advisory quality --profile enhanced --provider ollama")
    if not recommendations:
        recommendations.append("No action needed")

    return {
        "ok": True,
        "advisory_on": advisory_on,
        "runtime_up": runtime_up,
        "replay_on": replay_on,
        "memory_mode": prefs.get("memory_mode"),
        "guidance_style": prefs.get("guidance_style"),
        "drift": drift,
        "runtime": runtime,
        "preferred_provider": preferred,
        "provider_meta": _advisory_provider_meta(preferred),
        "recommendations": recommendations,
        "preferences": prefs,
    }


def cmd_advisory(args):
    """Configure advisory preferences (memory replay + guidance style)."""
    advisory_cmd = str(getattr(args, "advisory_cmd", "") or "setup").strip().lower()

    if advisory_cmd == "doctor":
        snapshot = _advisory_doctor_snapshot()
        if getattr(args, "json", False):
            print(json.dumps(snapshot, indent=2))
            return
        print("[SPARK] Advisory Doctor")
        print(f"  advisory_on: {'yes' if snapshot.get('advisory_on') else 'no'}")
        print(f"  runtime_up: {'yes' if snapshot.get('runtime_up') else 'no'}")
        print(f"  replay_on: {'yes' if snapshot.get('replay_on') else 'no'}")
        print(f"  memory_mode: {snapshot.get('memory_mode')}")
        print(f"  guidance_style: {snapshot.get('guidance_style')}")
        drift = snapshot.get("drift") if isinstance(snapshot.get("drift"), dict) else {}
        if drift.get("has_drift"):
            print(f"  profile_drift: yes ({drift.get('count', 0)} overrides)")
        else:
            print("  profile_drift: no")
        runtime = snapshot.get("runtime") if isinstance(snapshot.get("runtime"), dict) else {}
        print(f"  synth_tier: {runtime.get('synth_tier', 'unknown')}")
        print(f"  synth_ai_available: {'yes' if runtime.get('synth_ai_available') else 'no'}")
        provider = str(snapshot.get("preferred_provider") or "auto")
        meta = snapshot.get("provider_meta") if isinstance(snapshot.get("provider_meta"), dict) else {}
        print(f"  preferred_provider: {provider} ({meta.get('service', 'Unknown')})")
        key_envs = meta.get("key_envs") if isinstance(meta.get("key_envs"), list) else []
        if key_envs:
            print(f"  api_key_env: {' | '.join(key_envs)}")
        if provider == "minimax" and runtime.get("minimax_model"):
            print(f"  minimax_model: {runtime.get('minimax_model')}")
        recs = snapshot.get("recommendations") or []
        print("  recommended_next:")
        for rec in recs:
            print(f"    - {rec}")
        return

    if advisory_cmd == "show":
        current = _with_advisory_runtime(get_current_advisory_preferences())
        if getattr(args, "json", False):
            print(json.dumps(current, indent=2))
            return
        _print_advisory_preferences(current)
        return

    source = str(getattr(args, "source", "") or f"spark_cli_{advisory_cmd}")
    if advisory_cmd == "repair":
        result = repair_advisory_profile_drift(source=source)
        before = result.get("before_drift") if isinstance(result.get("before_drift"), dict) else {}
        after = result.get("after_drift") if isinstance(result.get("after_drift"), dict) else {}
        print("[SPARK] Advisory Profile Repair")
        print(f"  before_drift: {'yes' if before.get('has_drift') else 'no'} ({before.get('count', 0)} overrides)")
        print(f"  after_drift: {'yes' if after.get('has_drift') else 'no'} ({after.get('count', 0)} overrides)")
        _print_advisory_preferences(_with_advisory_runtime(result.get("applied", {})))
        return

    if advisory_cmd == "quality":
        provider = getattr(args, "provider", "auto")
        result = apply_advisory_quality_uplift(
            profile=getattr(args, "profile", "enhanced"),
            preferred_provider=provider,
            minimax_model=getattr(args, "minimax_model", None),
            ai_timeout_s=getattr(args, "ai_timeout_s", None),
            source=source,
        )
        runtime = result.get("runtime") if isinstance(result.get("runtime"), dict) else {}
        synth = runtime.get("synthesizer") if isinstance(runtime.get("synthesizer"), dict) else {}
        meta = _advisory_provider_meta(str(provider))
        print("[SPARK] Advisory Quality Uplift")
        print(f"  profile: {result.get('profile')}")
        print(f"  preferred_provider: {result.get('preferred_provider')} ({meta.get('service')})")
        print(f"  ai_timeout_s: {result.get('ai_timeout_s')}")
        if result.get("minimax_model"):
            print(f"  minimax_model: {result.get('minimax_model')}")
        print(f"  synth_tier: {synth.get('tier_label', 'unknown')}")
        print(f"  ai_available: {'yes' if synth.get('ai_available') else 'no'}")
        key_envs = meta.get("key_envs") if isinstance(meta.get("key_envs"), list) else []
        if key_envs:
            print(f"  api_key_env: {' | '.join(key_envs)}")
        warnings = result.get("warnings") or []
        if warnings:
            print(f"  warnings: {', '.join(str(w) for w in warnings)}")
        return

    if advisory_cmd == "setup":
        current = get_current_advisory_preferences()
        setup = get_advisory_setup_questions(current=current)
        questions = setup.get("questions") if isinstance(setup, dict) else []
        memory_mode = current.get("memory_mode", "standard")
        guidance_style = current.get("guidance_style", "balanced")
        if isinstance(questions, list) and questions:
            memory_mode = _pick_advisory_option(questions[0], str(memory_mode))
            if len(questions) > 1:
                guidance_style = _pick_advisory_option(questions[1], str(guidance_style))
        result = apply_advisory_preferences(
            memory_mode=memory_mode,
            guidance_style=guidance_style,
            source=source,
        )
        _print_advisory_preferences(_with_advisory_runtime(result))
        return

    if advisory_cmd == "set":
        memory_mode = getattr(args, "memory_mode", None)
        guidance_style = getattr(args, "guidance_style", None)
        # User-friendly default: "set" with no args means turn advisory on with baseline defaults.
        if memory_mode is None and guidance_style is None:
            memory_mode = "standard"
            guidance_style = "balanced"
        result = apply_advisory_preferences(
            memory_mode=memory_mode,
            guidance_style=guidance_style,
            source=source,
        )
        _print_advisory_preferences(_with_advisory_runtime(result))
        return

    if advisory_cmd == "on":
        memory_mode = str(getattr(args, "memory_mode", None) or "standard")
        guidance_style = getattr(args, "guidance_style", None)
        result = apply_advisory_preferences(
            memory_mode=memory_mode,
            guidance_style=guidance_style,
            source=source,
        )
        _print_advisory_preferences(_with_advisory_runtime(result))
        return

    if advisory_cmd == "off":
        result = apply_advisory_preferences(
            memory_mode="off",
            guidance_style=getattr(args, "guidance_style", None),
            source=source,
        )
        _print_advisory_preferences(_with_advisory_runtime(result))
        return

    print("Use: spark advisory [setup|show|set|on|off|repair|doctor|quality]")


def cmd_memory(args):
    """Configure/view Clawdbot semantic memory (embeddings provider)."""
    from lib.clawdbot_memory_setup import (
        get_current_memory_search,
        apply_memory_mode,
        run_memory_status,
        recommended_modes,
    )

    if args.list:
        modes = recommended_modes()
        print("\nMemory provider options:")
        for k, v in modes.items():
            print(f"  - {k:7}  cost={v['cost']}, privacy={v['privacy']}, setup={v['setup']}")
        print("\nTip: Codex OAuth doesn't include embeddings; local/remote/openai/gemini solve it.")
        return

    if args.show:
        ms = get_current_memory_search()
        print("\nCurrent Clawdbot agents.defaults.memorySearch:")
        print(ms if ms else "(not set)")
        return

    if args.status:
        print(run_memory_status(agent=args.agent))
        return

    if args.set_mode:
        applied = apply_memory_mode(
            args.set_mode,
            local_model_path=args.local_model_path,
            remote_base_url=args.remote_base_url,
            remote_api_key=args.remote_api_key,
            model=args.model,
            fallback=args.fallback,
            restart=not args.no_restart,
        )
        print("âœ“ Applied memorySearch:")
        print(applied)
        print("\nNext: run `clawdbot memory index --agent main` (or use `spark memory --status`).")
        return

    print("Use --list, --show, --status, or --set <mode>.")


def cmd_memory_migrate(args):
    """Backfill JSONL memory banks into the SQLite memory store."""
    stats = migrate_memory()
    print(json.dumps(stats, indent=2))


def cmd_chips(args):
    """Manage Spark chips - domain-specific intelligence modules."""
    from pathlib import Path
    from lib.chips import get_registry, get_runtime

    registry = get_registry()
    runtime = get_runtime()

    def _insight_count(chip_id: str) -> int:
        path = Path.home() / ".spark" / "chip_insights" / f"{chip_id}.jsonl"
        if not path.exists():
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except Exception:
            return 0

    if args.action == "list":
        chips = registry.get_installed()
        if not chips:
            print("\n[SPARK] No chips installed.")
            print("        Use 'spark chips install <path>' to install a chip.")
            return

        print(f"\n{'=' * 50}")
        print("  SPARK CHIPS - Domain Intelligence")
        print(f"{'=' * 50}\n")

        active_ids = {c.id for c in registry.get_active_chips()}
        active = [c for c in chips if c.id in active_ids]
        inactive = [c for c in chips if c.id not in active_ids]

        if active:
            print("Active Chips:")
            for chip in active:
                print(f"  [*] {chip.id} v{chip.version}")
                print(f"      {chip.name}")
                if chip.domains:
                    print(f"      Domains: {', '.join(chip.domains[:5])}")

        if inactive:
            print("\nInactive Chips:")
            for chip in inactive:
                print(f"  [ ] {chip.id} v{chip.version}")
                print(f"      {chip.name}")

        print()

    elif args.action == "install":
        if not args.path:
            print("[SPARK] Use --path to specify chip YAML file")
            return

        path = Path(args.path).expanduser()
        if not path.exists():
            print(f"[SPARK] File not found: {path}")
            return

        try:
            chip = registry.install(path)
            if not chip:
                print(f"[SPARK] Install failed: {path}")
                return
            print(f"[SPARK] Installed chip: {chip.id} v{chip.version}")
            print(f"        Name: {chip.name}")
            print(f"        Use 'spark chips activate {chip.id}' to enable")
        except Exception as e:
            print(f"[SPARK] Install failed: {e}")

    elif args.action == "uninstall":
        if not args.chip_id:
            print("[SPARK] Specify chip ID to uninstall")
            return

        if registry.uninstall(args.chip_id):
            print(f"[SPARK] Uninstalled chip: {args.chip_id}")
        else:
            print(f"[SPARK] Chip not found: {args.chip_id}")

    elif args.action == "activate":
        if not args.chip_id:
            print("[SPARK] Specify chip ID to activate")
            return

        if registry.activate(args.chip_id):
            print(f"[SPARK] Activated chip: {args.chip_id}")
        else:
            print(f"[SPARK] Chip not found: {args.chip_id}")

    elif args.action == "deactivate":
        if not args.chip_id:
            print("[SPARK] Specify chip ID to deactivate")
            return

        if registry.deactivate(args.chip_id):
            print(f"[SPARK] Deactivated chip: {args.chip_id}")
        else:
            print(f"[SPARK] Chip not found: {args.chip_id}")

    elif args.action == "status":
        chip_id = args.chip_id
        if not chip_id:
            # Show overall status
            stats = registry.get_stats()
            print(f"\n[SPARK] Chips Status")
            print(f"  Installed: {stats['total_installed']}")
            print(f"  Active: {stats['total_active']}")
            return

        chip = registry.get_chip(chip_id)
        if not chip:
            print(f"[SPARK] Chip not found: {chip_id}")
            return

        active = registry.is_active(chip_id)
        print(f"\n[SPARK] Chip: {chip.id}")
        print(f"  Name: {chip.name}")
        print(f"  Version: {chip.version}")
        print(f"  Active: {'Yes' if active else 'No'}")
        if chip.source_path:
            print(f"  Source: {chip.source_path}")
        print(f"  Insights Stored: {_insight_count(chip_id)}")

        print(f"\n  Stats:")
        if chip.domains:
            print(f"    Domains: {', '.join(chip.domains[:5])}")
        print(f"    Triggers: {len(chip.triggers)}")
        print(f"    Observers: {len(chip.observers)}")
        print(f"    Learners: {len(chip.learners)}")
        print(f"    Outcomes: {len(chip.outcomes_positive)}+ / {len(chip.outcomes_negative)}- / {len(chip.outcomes_neutral)}~")

    elif args.action == "insights":
        chip_id = args.chip_id
        if not chip_id:
            print("[SPARK] Specify chip ID to view insights")
            return

        insights = runtime.get_insights(chip_id, limit=args.limit or 10)

        if not insights:
            print(f"\n[SPARK] No insights for chip: {chip_id}")
            return

        print(f"\n[SPARK] Insights from {chip_id} (showing {len(insights)})\n")
        for i in insights:
            print(f"  {i.content}")
            print(f"      Confidence: {i.confidence:.0%} | Time: {i.timestamp[:19]}")
            print()

    elif args.action == "test":
        chip_id = args.chip_id
        if not chip_id:
            print("[SPARK] Specify chip ID to test")
            return

        chip = registry.get_chip(chip_id)
        if not chip:
            print(f"[SPARK] Chip not found: {chip_id}")
            return

        # Test with sample event
        test_text = args.test_text or "This is a test event"
        test_event = {
            "session_id": "test-session",
            "tool_name": "cli_test",
            "input": test_text,
        }

        insights = runtime.process_event_for_chips(test_event, [chip])

        print(f"\n[SPARK] Test chip: {chip_id}")
        print(f"  Input: {test_text[:80]}...")
        print(f"  Insights generated: {len(insights)}")
        for ins in insights:
            print(f"    - {ins.content[:100]}")

    elif args.action == "questions":
        # Phase 5: Show questions from active chips
        chip_id = args.chip_id
        phase = getattr(args, 'phase', None)

        if chip_id:
            # Show questions for a specific chip
            chip = registry.get_chip(chip_id)
            if not chip:
                print(f"[SPARK] Chip not found: {chip_id}")
                return

            if not chip.questions:
                print(f"[SPARK] Chip {chip_id} has no questions defined")
                return

            print(f"\n[SPARK] Questions from {chip_id}:\n")
            for q in chip.questions:
                phase_tag = f" [{q.get('phase')}]" if q.get("phase") else ""
                affects = ", ".join(q.get("affects_learning", [])[:3]) if q.get("affects_learning") else "general"
                print(f"  [{q.get('category', 'general')}]{phase_tag} {q.get('question', '')}")
                print(f"      ID: {q.get('id')} | Affects: {affects}")
                print()
        else:
            # Show questions from all active chips
            questions = registry.get_active_questions(phase=phase)
            if not questions:
                print("[SPARK] No questions from active chips.")
                print("        Activate chips with 'spark chips activate <chip_id>'")
                return

            print(f"\n[SPARK] Questions from Active Chips:\n")
            for q in questions:
                phase_tag = f" [{q['phase']}]" if q.get('phase') else ""
                affects = ", ".join(q.get('affects_learning', [])[:3]) or "general"
                print(f"  [{q.get('category', 'general')}]{phase_tag} {q.get('question', '')}")
                print(f"      ID: {q.get('id')} | Chip: {q.get('chip_id')} | Affects: {affects}")
                print()

    else:
        print("Unknown action. Use: list, install, uninstall, activate, deactivate, status, insights, test, questions")


def cmd_timeline(args):
    """Show growth timeline."""
    growth = get_growth_tracker()
    
    # Record current snapshot
    cognitive = get_cognitive_learner()
    aha = get_aha_tracker()
    cog_stats = cognitive.get_stats()
    aha_stats = aha.get_stats()
    
    growth.record_snapshot(
        insights_count=cog_stats['total_insights'],
        promoted_count=cog_stats['promoted_count'],
        aha_count=aha_stats['total_captured'],
        avg_reliability=cog_stats['avg_reliability'],
        categories_active=len([c for c, n in cog_stats['by_category'].items() if n > 0]),
        events_processed=count_events(),
    )
    
    print("\n" + growth.get_growth_narrative())
    print()
    
    # Show timeline
    timeline = growth.get_timeline(args.limit or 10)
    if timeline:
        print("\nðŸ“… Timeline\n")
        for item in timeline:
            date = item['timestamp'][:10]
            print(f"   [{date}] {item['title']}")
    print()
    
    # Show delta if requested
    if args.delta:
        delta = growth.get_growth_delta(args.delta)
        print(f"\nðŸ“Š Change over last {args.delta}h:")
        print(f"   Insights: +{delta.get('insights_delta', 0)}")
        print(f"   Reliability: {delta.get('reliability_delta', 0):+.0%}")
        print(f"   Aha moments: +{delta.get('aha_delta', 0)}")
        print()


def cmd_learn(args):
    """Manually learn an insight."""
    from lib.cognitive_learner import CognitiveCategory
    
    category_map = {
        "self": CognitiveCategory.SELF_AWARENESS,
        "self_awareness": CognitiveCategory.SELF_AWARENESS,
        "user": CognitiveCategory.USER_UNDERSTANDING,
        "user_understanding": CognitiveCategory.USER_UNDERSTANDING,
        "reasoning": CognitiveCategory.REASONING,
        "context": CognitiveCategory.CONTEXT,
        "wisdom": CognitiveCategory.WISDOM,
        "meta": CognitiveCategory.META_LEARNING,
        "meta_learning": CognitiveCategory.META_LEARNING,
        "communication": CognitiveCategory.COMMUNICATION,
        "creativity": CognitiveCategory.CREATIVITY,
    }
    
    cat_key = args.category.lower()
    if cat_key not in category_map:
        print(f"Unknown category: {args.category}")
        print(f"Valid: {', '.join(category_map.keys())}")
        return
    
    category = category_map[cat_key]
    cognitive = get_cognitive_learner()
    
    insight = cognitive.add_insight(
        category=category,
        insight=args.insight,
        context=args.context or "",
        confidence=args.reliability
    )
    
    print(f"\nâœ“ Learned [{category.value}]: {insight.insight}")
    print(f"  Reliability: {insight.reliability:.0%}")
    if args.context:
        print(f"  Context: {args.context}")
    print()
    
    # Auto-sync if requested
    if args.sync:
        print("[SPARK] Syncing to Mind...")
        stats = sync_all_to_mind()
        print(f"Synced: {stats['synced']}, Queued: {stats['queued']}")


def main():
    _configure_output()
    parser = argparse.ArgumentParser(
        description="Spark CLI - Self-evolving intelligence layer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Getting Started:
  onboard     First-time setup wizard (start here!)
  run         Start services + health check in one step
  update      Pull latest Spark and restart services
  doctor      Diagnose and repair system issues
  health      Quick health check (5 subsystems)
  status      Show overall system status

Services:
  up          Start background services
  down        Stop background services
  services    Show daemon/service status
  logs        View service logs (--service, --tail, --since)

Configuration:
  config      Get/set/diff tuneables (config get advisor.max_items)
  advisory    Configure advisory preferences

Intelligence:
  learnings   Show recent cognitive insights
  promote     Run promotion check
  capture     Memory capture suggestions
  process     Run bridge worker cycle / drain backlog

Examples:
  spark onboard                         # First-time setup
  spark run                             # Start everything + health check
  spark update                          # Pull latest + restart services
  spark update --check                  # Check if updates available
  spark doctor --deep                   # Full diagnostics
  spark health --json                   # Machine-readable health
  spark config get meta_ralph.quality_threshold
  spark config diff                     # Runtime vs versioned config
  spark logs -s sparkd --tail 100       # Last 100 sparkd log lines
  spark services --json                 # Service status as JSON
  spark advisory doctor                 # Advisory system diagnostics
  spark learnings --limit 20            # Recent learnings
"""
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    def _add_up_args(p):
        p.add_argument("--bridge-interval", type=int, default=30, help="bridge_worker interval (seconds)")
        p.add_argument("--bridge-query", default=None, help="optional fixed query for bridge_worker")
        p.add_argument("--watchdog-interval", type=int, default=60, help="watchdog interval (seconds)")
        p.add_argument("--bridge-stale-s", type=int, default=90, help="bridge_worker stale threshold (seconds)")
        p.add_argument("--lite", action="store_true", help="skip Pulse dashboard")
        p.add_argument("--no-mind", action="store_true", help="do not start mind server")
        p.add_argument("--no-watchdog", action="store_true", help="do not start watchdog")
        p.add_argument("--no-pulse", action="store_true", help="do not start spark pulse")
        p.add_argument("--sync-context", action="store_true", help="run sync-context after start")
        p.add_argument("--project", "-p", default=None, help="project root for sync-context")

    # === GETTING STARTED (beginner-first) ===

    # onboard - first-time wizard
    onboard_parser = subparsers.add_parser("onboard", help="First-time setup wizard (start here!)")
    onboard_parser.add_argument("--agent", choices=["claude", "cursor", "openclaw"], help="Agent type for hook setup")
    onboard_parser.add_argument("--quick", action="store_true", help="Non-interactive fast path (lite mode)")
    onboard_parser.add_argument("--yes", "-y", action="store_true", help="Auto-confirm prompts")
    onboard_parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    onboard_sub = onboard_parser.add_subparsers(dest="onboard_cmd")
    onboard_status = onboard_sub.add_parser("status", help="Show onboarding progress")
    onboard_status.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    onboard_reset = onboard_sub.add_parser("reset", help="Reset onboarding state")
    onboard_reset.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # run - convenience start + health + sync
    run_parser = subparsers.add_parser("run", help="Start services + health check in one step")
    run_parser.add_argument("--lite", action="store_true", help="Lite mode (skip Pulse dashboard)")
    run_parser.add_argument("--no-sync", dest="sync", action="store_false", help="Skip context sync step")
    run_parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # update - pull latest and restart
    update_parser = subparsers.add_parser("update", help="Pull latest Spark and restart services")
    update_parser.add_argument("--no-restart", action="store_true", help="Skip service restart after update")
    update_parser.add_argument("--check", action="store_true", help="Check for updates without installing")
    update_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    update_parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # doctor - comprehensive diagnostics and repair
    doctor_parser = subparsers.add_parser("doctor", help="Diagnose and repair system issues")
    doctor_parser.add_argument("--deep", action="store_true", help="Run deep checks (port conflicts, recent events)")
    doctor_parser.add_argument("--repair", "--fix", action="store_true", help="Attempt safe auto-repair of issues")
    doctor_parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # health
    health_parser = subparsers.add_parser("health", help="Quick health check (5 subsystems)")
    health_parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # status
    subparsers.add_parser("status", help="Show overall system status")

    # === SERVICES ===

    # up
    up_parser = subparsers.add_parser("up", help="Start background services")
    _add_up_args(up_parser)

    # down
    subparsers.add_parser("down", help="Stop background services")

    # services
    services_parser = subparsers.add_parser("services", help="Show daemon/service status")
    services_parser.add_argument("--bridge-stale-s", type=int, default=90, help="bridge_worker stale threshold (seconds)")
    services_parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # ensure
    ensure_parser = subparsers.add_parser("ensure", help="Start missing services if not running")
    _add_up_args(ensure_parser)

    # logs - unified log access
    logs_parser = subparsers.add_parser("logs", help="View service logs")
    logs_parser.add_argument("--service", "-s", choices=["sparkd", "bridge_worker", "mind", "pulse", "watchdog", "scheduler"],
                             help="Show logs for specific service")
    logs_parser.add_argument("--tail", "-n", type=int, default=50, help="Number of lines to show (default: 50)")
    logs_parser.add_argument("--follow", "-f", action="store_true", help="Follow log output (live tail)")
    logs_parser.add_argument("--since", help="Show logs since time (e.g., 1h, 30m, 2d)")
    logs_parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # === CONFIGURATION ===

    # config - tuneables management
    config_parser = subparsers.add_parser("config", help="Get/set/diff tuneables configuration")
    config_sub = config_parser.add_subparsers(dest="config_cmd")
    config_get = config_sub.add_parser("get", help="Get a config value by dot-path (e.g., advisor.max_emit)")
    config_get.add_argument("key", help="Dot-path key (e.g., meta_ralph.quality_threshold)")
    config_set = config_sub.add_parser("set", help="Set a config value")
    config_set.add_argument("key", help="Dot-path key")
    config_set.add_argument("value", help="Value to set (auto-parsed: numbers, booleans, JSON)")
    config_unset = config_sub.add_parser("unset", help="Remove a key from runtime config")
    config_unset.add_argument("key", help="Dot-path key to remove")
    config_sub.add_parser("validate", help="Validate runtime config against known sections")
    config_sub.add_parser("diff", help="Show differences between runtime and versioned config")
    config_show = config_sub.add_parser("show", help="Show full runtime config")
    config_show.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # === INTELLIGENCE ===

    # sync
    subparsers.add_parser("sync", help="Sync insights to Mind")

    # queue
    subparsers.add_parser("queue", help="Process offline queue")

    # process
    process_parser = subparsers.add_parser("process", help="Run bridge worker cycle or drain backlog")
    process_parser.add_argument("--drain", action="store_true", help="Loop until pattern backlog is cleared")
    process_parser.add_argument("--interval", type=float, default=1.0, help="Seconds between cycles when draining")
    process_parser.add_argument("--timeout", type=float, default=300.0, help="Max seconds to run when draining")
    process_parser.add_argument("--max-iterations", type=int, default=100, help="Max cycles when draining")
    process_parser.add_argument("--pattern-limit", type=int, default=200, help="Events per cycle for pattern detection")
    process_parser.add_argument("--memory-limit", type=int, default=60, help="Events per cycle for memory capture")
    process_parser.add_argument("--query", default=None, help="Optional fixed query for context")

    # validate
    validate_parser = subparsers.add_parser("validate", help="Run validation scan on recent events")
    validate_parser.add_argument("--limit", "-n", type=int, default=200, help="Events to scan")

    # learnings
    learnings_parser = subparsers.add_parser("learnings", help="Show recent learnings")
    learnings_parser.add_argument("--limit", "-n", type=int, default=10, help="Number to show")

    # promote
    promote_parser = subparsers.add_parser("promote", help="Run promotion check")
    promote_parser.add_argument("--dry-run", action="store_true", help="Don't actually promote")
    promote_parser.add_argument("--no-project", action="store_true", help="Skip PROJECT.md update")

    # write
    subparsers.add_parser("write", help="Write learnings to markdown")

    # sync-context
    sync_ctx = subparsers.add_parser("sync-context", help="Sync bootstrap context to outputs")
    sync_ctx.add_argument("--project", "-p", default=None, help="Project root for file outputs")
    sync_ctx.add_argument("--min-reliability", type=float, default=0.7, help="Minimum reliability")
    sync_ctx.add_argument("--min-validations", type=int, default=3, help="Minimum validations")
    sync_ctx.add_argument("--limit", type=int, default=12, help="Max items")
    sync_ctx.add_argument("--no-promoted", action="store_true", help="Skip promoted learnings from docs")
    sync_ctx.add_argument("--diagnose", action="store_true", help="Include selection diagnostics in output")

    # decay
    decay = subparsers.add_parser("decay", help="Preview or apply decay-based pruning")
    decay.add_argument("--max-age-days", type=float, default=180.0, help="Min age in days to consider stale")
    decay.add_argument("--min-effective", type=float, default=0.2, help="Min effective reliability to keep")
    decay.add_argument("--limit", type=int, default=20, help="Max candidates to show in dry-run")
    decay.add_argument("--apply", action="store_true", help="Actually prune stale insights")

    # events
    events_parser = subparsers.add_parser("events", help="Show recent events")
    events_parser.add_argument("--limit", "-n", type=int, default=20, help="Number to show")

    # opportunities
    opps_parser = subparsers.add_parser("opportunities", help="Review and act on Opportunity Scanner outputs")
    opps_sub = opps_parser.add_subparsers(dest="opps_cmd")

    opps_list = opps_sub.add_parser("list", help="List recent self-opportunities")
    opps_list.add_argument("--limit", "-n", type=int, default=20, help="Max to show")
    opps_list.add_argument("--since-hours", type=float, default=None, help="Only show opportunities newer than this")
    opps_list.add_argument("--scope-type", choices=["project", "operation", "spark_global"], help="Filter by scope_type")
    opps_list.add_argument("--scope-id", help="Filter by scope_id (project key, operation name, or global)")
    opps_list.add_argument("--project-id", help="Filter by project_id")
    opps_list.add_argument("--operation", help="Filter by operation tag")
    opps_list.add_argument("--all", action="store_true", help="Include accepted/dismissed items")
    opps_list.add_argument("--json", action="store_true", help="Emit JSON")

    opps_accept = opps_sub.add_parser("accept", help="Accept an opportunity and generate a task file")
    opps_accept.add_argument("id", help="opportunity_id (full or prefix)")
    opps_accept.add_argument("--note", "-n", default="", help="Optional note")

    opps_dismiss = opps_sub.add_parser("dismiss", help="Dismiss an opportunity to reduce repeats")
    opps_dismiss.add_argument("id", help="opportunity_id (full or prefix)")
    opps_dismiss.add_argument("--note", "-n", default="", help="Optional note")

    # advisory - user-facing advisory configuration
    advisory_parser = subparsers.add_parser(
        "advisory",
        help="Configure advisory memory/guidance preferences",
    )
    advisory_sub = advisory_parser.add_subparsers(dest="advisory_cmd")

    advisory_setup = advisory_sub.add_parser("setup", help="Run guided 2-question setup")
    advisory_setup.add_argument("--source", default="spark_cli_setup", help="Source label for metadata")

    advisory_show = advisory_sub.add_parser("show", help="Show current advisory preferences")
    advisory_show.add_argument("--json", action="store_true", help="Emit JSON output")

    advisory_doctor = advisory_sub.add_parser("doctor", help="Diagnose advisory runtime and profile drift")
    advisory_doctor.add_argument("--json", action="store_true", help="Emit JSON output")

    advisory_set = advisory_sub.add_parser("set", help="Set advisory preferences directly")
    advisory_set.add_argument("--memory-mode", choices=["off", "standard", "replay"], help="Memory replay mode")
    advisory_set.add_argument(
        "--guidance-style",
        choices=["concise", "balanced", "coach"],
        help="Advisory guidance style",
    )
    advisory_set.add_argument("--source", default="spark_cli_set", help="Source label for metadata")

    advisory_on = advisory_sub.add_parser("on", help="Enable advisory defaults")
    advisory_on.add_argument(
        "--memory-mode",
        choices=["standard", "replay"],
        default="standard",
        help="On mode profile (default: standard)",
    )
    advisory_on.add_argument(
        "--guidance-style",
        choices=["concise", "balanced", "coach"],
        help="Advisory guidance style",
    )
    advisory_on.add_argument("--source", default="spark_cli_on", help="Source label for metadata")

    advisory_off = advisory_sub.add_parser("off", help="Disable replay advisory")
    advisory_off.add_argument(
        "--guidance-style",
        choices=["concise", "balanced", "coach"],
        help="Optional style to persist while disabled",
    )
    advisory_off.add_argument("--source", default="spark_cli_off", help="Source label for metadata")

    advisory_repair = advisory_sub.add_parser("repair", help="Re-apply profile defaults and clear drift")
    advisory_repair.add_argument("--source", default="spark_cli_repair", help="Source label for metadata")

    advisory_quality = advisory_sub.add_parser("quality", help="Configure AI synthesis quality profile")
    advisory_quality.add_argument(
        "--profile",
        choices=["balanced", "enhanced", "max"],
        default="enhanced",
        help="Quality profile (default: enhanced)",
    )
    advisory_quality.add_argument(
        "--provider",
        choices=["auto", "ollama", "openai", "minimax", "anthropic", "gemini"],
        default="auto",
        help="Preferred synth provider (default: auto)",
    )
    advisory_quality.add_argument(
        "--minimax-model",
        default="MiniMax-M2.5",
        help="MiniMax model to use when provider=minimax (default: MiniMax-M2.5)",
    )
    advisory_quality.add_argument("--ai-timeout-s", type=float, help="Override synth AI timeout seconds")
    advisory_quality.add_argument("--source", default="spark_cli_quality", help="Source label for metadata")

    # outcome
    outcome_parser = subparsers.add_parser("outcome", help="Record explicit outcome check-in")
    outcome_parser.add_argument("--result", choices=["yes", "no", "partial", "mixed", "success", "failure"], help="Outcome result")
    outcome_parser.add_argument("--text", "-t", default=None, help="Optional notes")
    outcome_parser.add_argument("--tool", help="Associated tool or topic")
    outcome_parser.add_argument("--time", type=float, default=None, help="Unix timestamp override")
    outcome_parser.add_argument("--pending", action="store_true", help="List recent check-in requests")
    outcome_parser.add_argument("--limit", type=int, default=5, help="How many pending items to show")
    outcome_parser.add_argument("--link-latest", action="store_true", help="Link to most recent exposure")
    outcome_parser.add_argument("--link-count", type=int, default=0, help="Link to last N exposures")
    outcome_parser.add_argument("--link-key", action="append", help="Explicit insight_key to link")
    outcome_parser.add_argument("--auto-link", action="store_true", help="Auto-link exposures within a time window")
    outcome_parser.add_argument("--link-window-mins", type=float, default=30.0, help="Auto-link window in minutes")
    outcome_parser.add_argument("--session-id", help="Attach session_id to outcome")

    # advice-feedback
    advice_fb = subparsers.add_parser("advice-feedback", help="Record explicit advice helpfulness")
    advice_fb.add_argument("--tool", help="Tool name to match recent advice")
    advice_fb.add_argument("--advice-id", help="Explicit advice_id to mark")
    advice_fb.add_argument("--helpful", choices=["yes", "no", "unknown"], default="yes", help="Was the advice helpful?")
    advice_fb.add_argument("--followed", choices=["yes", "no"], default="yes", help="Was the advice followed?")
    advice_fb.add_argument("--notes", "-n", help="Optional notes/evidence")
    advice_fb.add_argument("--pending", action="store_true", help="List recent advice feedback requests")
    advice_fb.add_argument("--analyze", action="store_true", help="Summarize advice feedback backlog")
    advice_fb.add_argument("--min-samples", type=int, default=3, help="Min samples for recommendations")
    advice_fb.add_argument("--limit", type=int, default=5, help="How many requests to show")

    # eval
    eval_parser = subparsers.add_parser("eval", help="Evaluate predictions against outcomes")
    eval_parser.add_argument("--days", type=float, default=7.0, help="Lookback window in days")
    eval_parser.add_argument("--sim", type=float, default=0.72, help="Similarity threshold (0-1)")

    # outcome-link: Link an outcome to an insight
    outcome_link_parser = subparsers.add_parser("outcome-link", help="Link outcome to insight")
    outcome_link_parser.add_argument("outcome_id", help="Outcome ID to link")
    outcome_link_parser.add_argument("insight_key", help="Insight key to link to")
    outcome_link_parser.add_argument("--chip-id", help="Optional chip ID for scoping")
    outcome_link_parser.add_argument("--confidence", type=float, default=1.0, help="Link confidence (0-1)")
    outcome_link_parser.add_argument("--notes", help="Optional notes")

    # outcome-stats: Show outcome coverage statistics
    outcome_stats_parser = subparsers.add_parser("outcome-stats", help="Outcome-insight coverage stats")
    outcome_stats_parser.add_argument("--chip-id", help="Filter by chip ID")

    # outcome-validate: Run outcome-based validation
    outcome_validate_parser = subparsers.add_parser("outcome-validate", help="Validate insights using outcomes")
    outcome_validate_parser.add_argument("--limit", "-n", type=int, default=100, help="Max links to process")

    # outcome-unlinked: List outcomes without links
    outcome_unlinked_parser = subparsers.add_parser("outcome-unlinked", help="List unlinked outcomes")
    outcome_unlinked_parser.add_argument("--limit", "-n", type=int, default=20, help="Max to show")

    # outcome-links: List outcome-insight links
    outcome_links_parser = subparsers.add_parser("outcome-links", help="List outcome-insight links")
    outcome_links_parser.add_argument("--insight-key", help="Filter by insight key")
    outcome_links_parser.add_argument("--chip-id", help="Filter by chip ID")
    outcome_links_parser.add_argument("--limit", "-n", type=int, default=50, help="Max to show")

    # auto-link: Auto-link outcomes to insights
    auto_link_parser = subparsers.add_parser("auto-link", help="Auto-link unlinked outcomes to matching insights")
    auto_link_parser.add_argument("--min-similarity", type=float, default=0.25, help="Min similarity threshold (0-1)")
    auto_link_parser.add_argument("--limit", "-n", type=int, default=50, help="Max outcomes to process")
    auto_link_parser.add_argument("--dry-run", action="store_true", help="Preview without creating links")
    auto_link_parser.add_argument("--preview", action="store_true", help="Show linkable candidates only")

    # sync-banks: Sync insights to memory banks
    sync_banks_parser = subparsers.add_parser("sync-banks", help="Sync high-value insights to memory banks")
    sync_banks_parser.add_argument("--min-reliability", type=float, default=0.7, help="Min reliability threshold (0-1)")
    sync_banks_parser.add_argument("--categories", help="Comma-separated categories to sync")
    sync_banks_parser.add_argument("--dry-run", action="store_true", help="Preview without syncing")

    # bank-stats: Show memory bank statistics
    subparsers.add_parser("bank-stats", help="Show memory bank statistics")

    # memory-purge-telemetry: Remove telemetry from SQLite memory store
    mem_purge = subparsers.add_parser("memory-purge-telemetry", help="Purge telemetry from memory store")
    mem_purge.add_argument("--dry-run", action="store_true", help="Preview without deleting")

    # eidos-purge-telemetry: Remove telemetry distillations from EIDOS store
    eidos_purge = subparsers.add_parser("eidos-purge-telemetry", help="Purge telemetry from EIDOS distillations")
    eidos_purge.add_argument("--dry-run", action="store_true", help="Preview without deleting")

    # validate-ingest
    ingest_parser = subparsers.add_parser("validate-ingest", help="Validate recent queue events")
    ingest_parser.add_argument("--limit", "-n", type=int, default=200, help="Events to scan")
    ingest_parser.add_argument("--no-write", action="store_true", help="Skip writing ingest report file")
    
    # learn
    learn_parser = subparsers.add_parser("learn", help="Manually learn an insight")
    learn_parser.add_argument("category", help="Category (self, user, reasoning, context, wisdom, meta, communication, creativity)")
    learn_parser.add_argument("insight", help="The insight text")
    learn_parser.add_argument("--context", "-c", help="Additional context")
    learn_parser.add_argument("--reliability", "-r", type=float, default=0.7, help="Initial reliability (0-1)")
    learn_parser.add_argument("--sync", "-s", action="store_true", help="Sync to Mind after learning")
    
    # surprises
    surprises_parser = subparsers.add_parser("surprises", help="Show aha moments")
    surprises_parser.add_argument("--limit", "-n", type=int, default=10, help="Number to show")
    surprises_parser.add_argument("--insights", "-i", action="store_true", help="Show analysis/insights")
    surprises_parser.add_argument("--surface", "-s", action="store_true", help="Surface pending surprises")

    # importance
    importance_parser = subparsers.add_parser("importance", help="Test and visualize importance scoring")
    importance_parser.add_argument("--text", "-t", help="Text to score for importance")
    importance_parser.add_argument("--domain", "-d", help="Active domain (game_dev, fintech, marketing, product)")
    importance_parser.add_argument("--source", help="Context source (user_correction, etc.)")
    importance_parser.add_argument("--examples", "-e", action="store_true", help="Show example scorings")
    importance_parser.add_argument("--semantic", "-s", action="store_true", help="Use semantic intelligence (embeddings)")
    importance_parser.add_argument("--feedback", "-f", action="store_true", help="Show feedback/accuracy statistics")

    # curiosity - knowledge gaps and questions
    curiosity_parser = subparsers.add_parser("curiosity", help="Explore knowledge gaps and open questions")
    curiosity_parser.add_argument("--questions", "-q", action="store_true", help="Show open questions")
    curiosity_parser.add_argument("--fill", help="Fill a gap by ID")
    curiosity_parser.add_argument("--answer", "-a", help="Answer text when filling a gap")
    curiosity_parser.add_argument("--not-valuable", action="store_true", help="Mark answer as not valuable")
    curiosity_parser.add_argument("--limit", "-n", type=int, default=10, help="Max items to show")

    # hypotheses - track and validate hypotheses
    hypotheses_parser = subparsers.add_parser("hypotheses", help="Track and validate hypotheses")
    hypotheses_parser.add_argument("--testable", "-t", action="store_true", help="Show testable hypotheses")
    hypotheses_parser.add_argument("--pending", "-p", action="store_true", help="Show pending predictions")
    hypotheses_parser.add_argument("--outcome", help="Record outcome: <hypothesis_id>:<prediction_index>")
    hypotheses_parser.add_argument("--correct", action="store_true", help="Mark prediction as correct")
    hypotheses_parser.add_argument("--notes", help="Notes for outcome")
    hypotheses_parser.add_argument("--limit", "-n", type=int, default=10, help="Max items to show")

    # contradictions - view and resolve contradictions
    contradictions_parser = subparsers.add_parser("contradictions", help="View and resolve contradictions")
    contradictions_parser.add_argument("--unresolved", "-u", action="store_true", help="Show unresolved contradictions")
    contradictions_parser.add_argument("--resolve", type=int, help="Resolve contradiction by index")
    contradictions_parser.add_argument("--resolution-type", choices=["update", "context", "keep_both", "discard_new"],
                                       help="How to resolve")
    contradictions_parser.add_argument("--resolution", help="Resolution notes")
    contradictions_parser.add_argument("--limit", "-n", type=int, default=10, help="Max items to show")

    # eidos - self-evolving intelligence system
    eidos_parser = subparsers.add_parser("eidos", help="EIDOS - Self-evolving intelligence with decision packets")
    eidos_parser.add_argument("--stats", "-s", action="store_true", help="Show detailed statistics")
    eidos_parser.add_argument("--episodes", "-e", action="store_true", help="List recent episodes")
    eidos_parser.add_argument("--distillations", "-d", action="store_true", help="List distillations (extracted rules)")
    eidos_parser.add_argument("--type", choices=["heuristic", "sharp_edge", "anti_pattern", "playbook", "policy"],
                              help="Filter distillations by type")
    eidos_parser.add_argument("--policies", "-p", action="store_true", help="List operating policies")
    eidos_parser.add_argument("--steps", action="store_true", help="List recent steps (decision packets)")
    eidos_parser.add_argument("--episode", help="Show steps for specific episode ID")
    eidos_parser.add_argument("--metrics", "-m", action="store_true", help="Show compounding rate and intelligence metrics")
    eidos_parser.add_argument("--evidence", action="store_true", help="Show evidence store statistics")
    eidos_parser.add_argument("--migrate", action="store_true", help="Run migration from old Spark to EIDOS")
    eidos_parser.add_argument("--validate-migration", action="store_true", help="Validate migration completed successfully")
    eidos_parser.add_argument("--deferred", action="store_true", help="Show deferred validations status")
    eidos_parser.add_argument("--dry-run", action="store_true", help="For migrate: preview without making changes")
    eidos_parser.add_argument("--limit", "-n", type=int, default=10, help="Max items to show")

    # voice
    voice_parser = subparsers.add_parser("voice", help="Spark's personality")
    voice_parser.add_argument("--introduce", "-i", action="store_true", help="Introduce Spark")
    voice_parser.add_argument("--opinions", "-o", action="store_true", help="Show opinions")
    voice_parser.add_argument("--strong", action="store_true", help="Only strong opinions")
    voice_parser.add_argument("--growth", "-g", action="store_true", help="Show growth moments")
    voice_parser.add_argument("--limit", "-n", type=int, default=5, help="Number to show")
    
    # personality-evolution - safe bounded style adaptation controls
    personality_parser = subparsers.add_parser("personality-evolution", help="Inspect/apply/reset personality evolution V1")
    personality_parser.add_argument("--state-path", help="Optional custom state file path")
    personality_sub = personality_parser.add_subparsers(dest="evolution_cmd")

    personality_sub.add_parser("inspect", help="Show current evolution state")

    personality_apply = personality_sub.add_parser("apply", help="Apply explicit user-guided signals")
    personality_apply.add_argument("--signals", help="Signals payload as JSON")
    personality_apply.add_argument("--signals-file", help="Path to signals JSON file")

    personality_reset = personality_sub.add_parser("reset", help="Reset evolution state to defaults")
    personality_reset.add_argument("--yes", action="store_true", help="Confirm reset")

    # timeline
    timeline_parser = subparsers.add_parser("timeline", help="Show growth timeline")
    timeline_parser.add_argument("--limit", "-n", type=int, default=10, help="Number of events")
    timeline_parser.add_argument("--delta", "-d", type=int, help="Show change over N hours")
    
    # bridge - connect learnings to behavior
    bridge_parser = subparsers.add_parser("bridge", help="Bridge learnings to operational context")
    bridge_parser.add_argument("--update", "-u", action="store_true", help="Update SPARK_CONTEXT.md")
    bridge_parser.add_argument("--promote", "-p", action="store_true", help="Auto-promote insights to MEMORY.md")
    bridge_parser.add_argument("--status", "-s", action="store_true", help="Show bridge status")
    bridge_parser.add_argument("--query", help="Optional: tailor context to a specific task")

    # capture - portable memory capture suggestions (keyword + intent hybrid)
    capture_parser = subparsers.add_parser("capture", help="Capture important statements into Spark learnings")
    capture_parser.add_argument("--scan", action="store_true", help="Scan recent events and update suggestions")
    capture_parser.add_argument("--list", action="store_true", help="List pending suggestions")
    capture_parser.add_argument("--accept", help="Accept a pending suggestion by id")
    capture_parser.add_argument("--reject", help="Reject a pending suggestion by id")
    capture_parser.add_argument("--limit", "-n", type=int, default=10, help="How many to list")

    # memory - configure Clawdbot semantic memory provider
    mem_parser = subparsers.add_parser("memory", help="Configure/view Clawdbot memory search (embeddings)")
    mem_parser.add_argument("--list", action="store_true", help="List recommended provider modes")
    mem_parser.add_argument("--show", action="store_true", help="Show current memorySearch config")
    mem_parser.add_argument("--status", action="store_true", help="Run clawdbot memory status --deep")
    mem_parser.add_argument("--agent", default="main", help="Agent id for status (default: main)")
    mem_parser.add_argument("--set", dest="set_mode", choices=["off", "local", "remote", "openai", "gemini"], help="Set provider mode")
    mem_parser.add_argument("--model", help="Embedding model name (remote/openai/gemini)")
    mem_parser.add_argument("--fallback", default="none", help="Fallback provider (default: none)")
    mem_parser.add_argument("--local-model-path", help="Path to local GGUF embedding model (local mode)")
    mem_parser.add_argument("--remote-base-url", help="OpenAI-compatible baseUrl (remote mode)")
    mem_parser.add_argument("--remote-api-key", help="API key for remote baseUrl (remote mode)")
    mem_parser.add_argument("--no-restart", action="store_true", help="Don't restart Clawdbot gateway")

    # memory-migrate
    subparsers.add_parser("memory-migrate", help="Backfill JSONL memories into SQLite store")

    # project - questioning and capture
    project_parser = subparsers.add_parser("project", help="Project questioning and capture")
    project_sub = project_parser.add_subparsers(dest="project_cmd")

    project_init = project_sub.add_parser("init", help="Initialize or update project profile")
    project_init.add_argument("--domain", help="Set project domain (game_dev, marketing, org, product, engineering)")
    project_init.add_argument("--project", help="Project root path")
    project_init.add_argument("--limit", type=int, default=5, help="How many questions to show")

    project_status = project_sub.add_parser("status", help="Show project profile summary")
    project_status.add_argument("--project", help="Project root path")

    project_questions = project_sub.add_parser("questions", help="Show suggested project questions")
    project_questions.add_argument("--project", help="Project root path")
    project_questions.add_argument("--limit", type=int, default=5, help="How many questions to show")

    project_answer = project_sub.add_parser("answer", help="Answer a project question")
    project_answer.add_argument("id", help="Question id")
    project_answer.add_argument("--text", "-t", required=True, help="Answer text")
    project_answer.add_argument("--project", help="Project root path")

    project_capture = project_sub.add_parser("capture", help="Capture a project insight/decision/milestone")
    project_capture.add_argument("--type", required=True, choices=["goal", "done", "milestone", "decision", "insight", "feedback", "risk", "reference", "transfer"], help="Capture type")
    project_capture.add_argument("--text", "-t", required=True, help="Capture text")
    project_capture.add_argument("--project", help="Project root path")
    project_capture.add_argument("--status", help="Status (for milestones)")
    project_capture.add_argument("--why", help="Decision rationale")
    project_capture.add_argument("--impact", help="Impact")
    project_capture.add_argument("--evidence", help="Evidence or feedback source")

    project_phase = project_sub.add_parser("phase", help="Get or set project phase")
    project_phase.add_argument("--set", dest="set_phase", help="Set phase (discovery/prototype/polish/launch)")
    project_phase.add_argument("--project", help="Project root path")

    # chips - domain-specific intelligence
    chips_parser = subparsers.add_parser("chips", help="Manage Spark chips - domain-specific intelligence")
    chips_parser.add_argument("action", nargs="?", default="list",
                              choices=["list", "install", "uninstall", "activate", "deactivate", "status", "insights", "test", "questions"],
                              help="Action to perform")
    chips_parser.add_argument("chip_id", nargs="?", help="Chip ID (for activate/deactivate/status/insights/test/questions)")
    chips_parser.add_argument("--path", "-p", help="Path to chip YAML file (for install)")
    chips_parser.add_argument("--source", choices=["official", "community", "custom"], default="custom",
                              help="Chip source (for install)")
    chips_parser.add_argument("--limit", "-n", type=int, default=10, help="Number of insights to show")
    chips_parser.add_argument("--test-text", "-t", help="Test text for chip testing")
    chips_parser.add_argument("--phase", choices=["discovery", "prototype", "polish", "launch"],
                              help="Filter questions by phase (for questions)")

    args = parser.parse_args()

    if not args.command:
        # Default to status
        cmd_status(args)
        return
    
    commands = {
        "status": cmd_status,
        "services": cmd_services,
        "up": cmd_up,
        "ensure": cmd_ensure,
        "down": cmd_down,
        "sync": cmd_sync,
        "queue": cmd_queue,
        "process": cmd_process,
        "validate": cmd_validate,
        "learnings": cmd_learnings,
        "promote": cmd_promote,
        "write": cmd_write,
        "sync-context": cmd_sync_context,
        "decay": cmd_decay,
        "health": cmd_health,
        "doctor": cmd_doctor,
        "onboard": cmd_onboard,
        "logs": cmd_logs,
        "config": cmd_config,
        "run": cmd_run,
        "update": cmd_update,
        "events": cmd_events,
        "opportunities": cmd_opportunities,
        "advisory": cmd_advisory,
        "outcome": cmd_outcome,
        "advice-feedback": cmd_advice_feedback,
        "outcome-link": cmd_outcome_link,
        "outcome-stats": cmd_outcome_stats,
        "outcome-validate": cmd_outcome_validate,
        "outcome-unlinked": cmd_outcome_unlinked,
        "outcome-links": cmd_outcome_links,
        "auto-link": cmd_auto_link,
        "sync-banks": cmd_sync_banks,
        "bank-stats": cmd_bank_stats,
        "memory-purge-telemetry": cmd_memory_purge_telemetry,
        "eidos-purge-telemetry": cmd_eidos_purge_telemetry,
        "eval": cmd_eval,
        "validate-ingest": cmd_validate_ingest,
        "capture": cmd_capture,
        "learn": cmd_learn,
        "surprises": cmd_surprises,
        "importance": cmd_importance,
        "curiosity": cmd_curiosity,
        "hypotheses": cmd_hypotheses,
        "contradictions": cmd_contradictions,
        "eidos": cmd_eidos,
        "voice": cmd_voice,
        "personality-evolution": cmd_personality_evolution,
        "timeline": cmd_timeline,
        "bridge": cmd_bridge,
        "memory": cmd_memory,
        "memory-migrate": cmd_memory_migrate,
        "chips": cmd_chips,
        "project": None,
    }

    if args.command == "project":
        if args.project_cmd == "init":
            cmd_project_init(args)
        elif args.project_cmd == "status":
            cmd_project_status(args)
        elif args.project_cmd == "questions":
            cmd_project_questions(args)
        elif args.project_cmd == "answer":
            cmd_project_answer(args)
        elif args.project_cmd == "capture":
            cmd_project_capture(args)
        elif args.project_cmd == "phase":
            cmd_project_phase(args)
        else:
            project_parser.print_help()
        return

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
