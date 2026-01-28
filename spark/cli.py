#!/usr/bin/env python3
"""
Spark CLI - Command-line interface for Spark

Usage:
    python -m spark.cli status     # Show system status
    python -m spark.cli sync       # Sync insights to Mind
    python -m spark.cli queue      # Process offline queue
    python -m spark.cli learnings  # Show recent learnings
    python -m spark.cli promote    # Run promotion check
    python -m spark.cli write      # Write learnings to markdown
    python -m spark.cli health     # Health check
    python -m spark.cli memory     # Memory capture suggestions
"""

import sys
import json
import argparse
from pathlib import Path

from lib.cognitive_learner import get_cognitive_learner
from lib.mind_bridge import get_mind_bridge, sync_all_to_mind
from lib.markdown_writer import get_markdown_writer, write_all_learnings
from lib.promoter import get_promoter, check_and_promote
from lib.queue import get_queue_stats, read_recent_events, count_events
from lib.aha_tracker import get_aha_tracker
from lib.spark_voice import get_spark_voice
from lib.growth_tracker import get_growth_tracker
from lib.memory_capture import (
    process_recent_memory_events,
    list_pending as capture_list_pending,
    accept_suggestion as capture_accept,
    reject_suggestion as capture_reject,
)
from lib.capture_cli import format_pending


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
    print("📚 Cognitive Insights")
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
    print("🧠 Mind Bridge")
    print(f"   Mind Available: {'✓ Yes' if bridge_stats['mind_available'] else '✗ No'}")
    print(f"   Synced to Mind: {bridge_stats['synced_count']}")
    print(f"   Offline Queue: {bridge_stats['offline_queue_size']}")
    print(f"   Last Sync: {bridge_stats['last_sync'] or 'Never'}")
    print()
    
    # Queue stats
    queue_stats = get_queue_stats()
    print("📋 Event Queue")
    print(f"   Events: {queue_stats['event_count']}")
    print(f"   Size: {queue_stats['size_mb']} MB")
    print(f"   Needs Rotation: {'Yes' if queue_stats['needs_rotation'] else 'No'}")
    print()
    
    # Markdown writer stats
    writer = get_markdown_writer()
    writer_stats = writer.get_stats()
    print("📝 Markdown Output")
    print(f"   Directory: {writer_stats['learnings_dir']}")
    print(f"   Learnings Written: {writer_stats['learnings_count']}")
    print(f"   Errors Written: {writer_stats['errors_count']}")
    print()
    
    # Promoter stats
    promoter = get_promoter()
    promo_stats = promoter.get_promotion_status()
    print("📤 Promotions")
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
    print("💡 Surprises (Aha Moments)")
    print(f"   Total Captured: {aha_stats['total_captured']}")
    print(f"   Unexpected Successes: {aha_stats['unexpected_successes']}")
    print(f"   Unexpected Failures: {aha_stats['unexpected_failures']}")
    print(f"   Lessons Extracted: {aha_stats['lessons_extracted']}")
    if aha_stats['pending_surface'] > 0:
        print(f"   ⚠️  Pending to Show: {aha_stats['pending_surface']}")
    print()
    
    # Voice/personality stats
    voice_stats = voice.get_stats()
    print("🎭 Personality")
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


def cmd_learnings(args):
    """Show recent learnings."""
    cognitive = get_cognitive_learner()
    insights = list(cognitive.insights.values())
    
    # Sort by created_at
    insights.sort(key=lambda x: x.created_at, reverse=True)
    
    limit = args.limit or 10
    print(f"\n📚 Recent Cognitive Insights (showing {min(limit, len(insights))} of {len(insights)})\n")
    
    for insight in insights[:limit]:
        status = "✓ Promoted" if insight.promoted else f"{insight.reliability:.0%} reliable"
        print(f"[{insight.category.value}] {insight.insight}")
        print(f"   {status} | {insight.times_validated} validations | {insight.created_at[:10]}")
        print()


def cmd_promote(args):
    """Run promotion check."""
    dry_run = args.dry_run
    print(f"[SPARK] Checking for promotable insights (dry_run={dry_run})...")
    stats = check_and_promote(dry_run=dry_run)
    print(f"\nResults: {json.dumps(stats, indent=2)}")


def cmd_write(args):
    """Write learnings to markdown."""
    print("[SPARK] Writing learnings to markdown...")
    stats = write_all_learnings()
    print(f"\nResults: {json.dumps(stats, indent=2)}")


def cmd_health(args):
    """Health check."""
    print("\n🏥 Health Check\n")
    
    # Check cognitive learner
    try:
        cognitive = get_cognitive_learner()
        print("✓ Cognitive Learner: OK")
    except Exception as e:
        print(f"✗ Cognitive Learner: {e}")
    
    # Check Mind connection
    bridge = get_mind_bridge()
    if bridge._check_mind_health():
        print("✓ Mind API: OK")
    else:
        print("✗ Mind API: Not available (will queue offline)")
    
    # Check queue
    try:
        stats = get_queue_stats()
        print(f"✓ Event Queue: OK ({stats['event_count']} events)")
    except Exception as e:
        print(f"✗ Event Queue: {e}")
    
    # Check learnings dir
    writer = get_markdown_writer()
    if writer.learnings_dir.exists():
        print(f"✓ Learnings Dir: OK ({writer.learnings_dir})")
    else:
        print(f"? Learnings Dir: Will be created on first write")
    
    print()


def cmd_events(args):
    """Show recent events."""
    limit = args.limit or 20
    events = read_recent_events(limit)
    
    print(f"\n📋 Recent Events (showing {len(events)} of {count_events()})\n")
    
    for event in events:
        tool_str = f" [{event.tool_name}]" if event.tool_name else ""
        error_str = f" ERROR: {event.error[:50]}..." if event.error else ""
        print(f"[{event.event_type.value}]{tool_str}{error_str}")


def cmd_capture(args):
    """Portable memory capture: scan → suggest → accept/reject."""
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
        print("✓ Accepted" if ok else "✗ Not found / not pending")
        return

    if args.reject:
        ok = capture_reject(args.reject)
        print("✓ Rejected" if ok else "✗ Not found / not pending")
        return

    if args.list:
        items = capture_list_pending(limit=args.limit)
        print("\n" + format_pending(items) + "\n")


def cmd_surprises(args):
    """Show surprise moments (aha!)."""
    aha = get_aha_tracker()
    
    if args.insights:
        # Show insights/analysis
        insights = aha.get_insights()
        print("\n💡 Surprise Analysis\n")
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
            print("\n💡 Surfacing Surprises:\n")
            for s in pending:
                print(s)
                print()
        else:
            print("\nNo pending surprises to surface.")
        return
    
    # Show recent surprises
    limit = args.limit or 10
    surprises = aha.get_recent_surprises(limit)
    
    print(f"\n💡 Recent Surprises (showing {len(surprises)})\n")
    
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
        print(f"\n🎭 Spark's Opinions ({len(opinions)} total)\n")
        for o in opinions:
            strength = "strongly" if o.strength > 0.8 else "tends to"
            print(f"   [{o.topic}] {strength} prefer {o.preference}")
            print(f"      Reason: {o.reason}")
            print(f"      Strength: {o.strength:.0%}")
            print()
        return
    
    if args.growth:
        moments = voice.get_recent_growth(args.limit or 5)
        print(f"\n📈 Growth Moments ({len(moments)})\n")
        for m in moments:
            print(f"   Before: {m.before}")
            print(f"   After: {m.after}")
            print(f"   Trigger: {m.trigger}")
            print()
        return
    
    # Default: show status
    stats = voice.get_stats()
    print("\n🎭 Spark Voice Status\n")
    print(f"   {voice.get_status_voice()}")
    print()
    print(f"   Age: {stats['age_days']} days")
    print(f"   Interactions: {stats['interactions']}")
    print(f"   Opinions: {stats['opinions_formed']} ({stats['strong_opinions']} strong)")
    print(f"   Growth moments: {stats['growth_moments']}")
    print()


def cmd_bridge(args):
    """Bridge learnings to operational context."""
    from lib.bridge import (
        generate_active_context, 
        update_spark_context, 
        auto_promote_insights,
        propose_daily_digest,
        propose_user_updates,
        bridge_status,
    )

    if args.update:
        update_spark_context(query=args.query)
        print("✓ Updated SPARK_CONTEXT.md with active learnings")
    elif args.promote:
        count = auto_promote_insights(apply=args.apply)
        if count > 0:
            if args.apply:
                print(f"✓ Applied {count} promotions to MEMORY.md")
            else:
                print(f"✓ Proposed {count} promotions (patches written under <workspace>/.spark/proposals)")
        else:
            print("No insights ready for promotion yet")
    elif args.digest:
        r = propose_daily_digest(apply=args.apply)
        if r.get("patch_path"):
            print(f"✓ Proposed daily digest patch: {r['patch_path']}")
        elif r.get("applied"):
            print("✓ Applied daily digest to today's memory file")
        else:
            print(f"No digest change: {r.get('reason')}")
    elif args.user:
        r = propose_user_updates(apply=args.apply)
        if r.get("patch_path"):
            print(f"✓ Proposed USER.md patch: {r['patch_path']}")
        elif r.get("applied"):
            print("✓ Applied USER.md updates")
        else:
            print(f"No USER.md change: {r.get('reason')}")
    elif args.status:
        status = bridge_status()
        print(f"\n  Bridge Status")
        print(f"  {'─' * 30}")
        print(f"  High-value insights: {status['high_value_insights']}")
        print(f"  Lessons learned: {status['lessons_learned']}")
        print(f"  Strong opinions: {status['strong_opinions']}")
        print(f"  Context file: {'✓' if status['context_exists'] else '✗'}")
        print(f"  Memory file: {'✓' if status['memory_exists'] else '✗'}")
        print()
    else:
        # Default: show active context
        print(generate_active_context())


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
        print("✓ Applied memorySearch:")
        print(applied)
        print("\nNext: run `clawdbot memory index --agent main` (or use `spark memory --status`).")
        return

    print("Use --list, --show, --status, or --set <mode>.")



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
        print("\n📅 Timeline\n")
        for item in timeline:
            date = item['timestamp'][:10]
            print(f"   [{date}] {item['title']}")
    print()
    
    # Show delta if requested
    if args.delta:
        delta = growth.get_growth_delta(args.delta)
        print(f"\n📊 Change over last {args.delta}h:")
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
    
    print(f"\n✓ Learned [{category.value}]: {insight.insight}")
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
Commands:
  status      Show overall system status
  sync        Sync cognitive insights to Mind
  queue       Process offline queue
  learnings   Show recent cognitive insights
  promote     Run promotion check
  write       Write learnings to markdown files
  health      Run health check
  events      Show recent events from queue
  capture     Memory capture suggestions (portable)

Examples:
  spark status
  spark sync
  spark promote --dry-run
  spark learnings --limit 20
  spark capture --list
  spark capture --accept <id>
"""
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # status
    subparsers.add_parser("status", help="Show overall system status")
    
    # sync
    subparsers.add_parser("sync", help="Sync insights to Mind")
    
    # queue
    subparsers.add_parser("queue", help="Process offline queue")
    
    # learnings
    learnings_parser = subparsers.add_parser("learnings", help="Show recent learnings")
    learnings_parser.add_argument("--limit", "-n", type=int, default=10, help="Number to show")
    
    # promote
    promote_parser = subparsers.add_parser("promote", help="Run promotion check")
    promote_parser.add_argument("--dry-run", action="store_true", help="Don't actually promote")
    
    # write
    subparsers.add_parser("write", help="Write learnings to markdown")
    
    # health
    subparsers.add_parser("health", help="Health check")
    
    # events
    events_parser = subparsers.add_parser("events", help="Show recent events")
    events_parser.add_argument("--limit", "-n", type=int, default=20, help="Number to show")
    
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
    
    # voice
    voice_parser = subparsers.add_parser("voice", help="Spark's personality")
    voice_parser.add_argument("--introduce", "-i", action="store_true", help="Introduce Spark")
    voice_parser.add_argument("--opinions", "-o", action="store_true", help="Show opinions")
    voice_parser.add_argument("--strong", action="store_true", help="Only strong opinions")
    voice_parser.add_argument("--growth", "-g", action="store_true", help="Show growth moments")
    voice_parser.add_argument("--limit", "-n", type=int, default=5, help="Number to show")
    
    # timeline
    timeline_parser = subparsers.add_parser("timeline", help="Show growth timeline")
    timeline_parser.add_argument("--limit", "-n", type=int, default=10, help="Number of events")
    timeline_parser.add_argument("--delta", "-d", type=int, help="Show change over N hours")
    
    # bridge - connect learnings to behavior
    bridge_parser = subparsers.add_parser("bridge", help="Bridge learnings to operational context")
    bridge_parser.add_argument("--update", "-u", action="store_true", help="Update SPARK_CONTEXT.md")
    bridge_parser.add_argument("--promote", "-p", action="store_true", help="Promote insights to MEMORY.md (default: proposal-only)")
    bridge_parser.add_argument("--digest", action="store_true", help="Propose/apply a daily digest into memory/YYYY-MM-DD.md")
    bridge_parser.add_argument("--user", action="store_true", help="Propose/apply stable preferences into USER.md")
    bridge_parser.add_argument("--apply", action="store_true", help="Actually edit files (otherwise writes patch proposals)")
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
    
    args = parser.parse_args()
    
    if not args.command:
        # Default to status
        cmd_status(args)
        return
    
    commands = {
        "status": cmd_status,
        "sync": cmd_sync,
        "queue": cmd_queue,
        "learnings": cmd_learnings,
        "promote": cmd_promote,
        "write": cmd_write,
        "health": cmd_health,
        "events": cmd_events,
        "capture": cmd_capture,
        "learn": cmd_learn,
        "surprises": cmd_surprises,
        "voice": cmd_voice,
        "timeline": cmd_timeline,
        "bridge": cmd_bridge,
        "memory": cmd_memory,
    }
    
    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
