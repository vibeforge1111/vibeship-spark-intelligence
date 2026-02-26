#!/usr/bin/env python3
# ruff: noqa: S603
"""spark_scheduler -- periodic X intelligence tasks.

Runs mention polling, engagement snapshots, daily research, and niche scans
on configurable intervals. No HTTP server; communicates health via heartbeat.

Design:
- Task-based scheduler with configurable intervals per task
- Sequential execution to respect X API rate limits
- Fail-safe: task failures logged and skipped
- Draft reply queue for human review (NO auto-posting)

Usage:
  python spark_scheduler.py
  python spark_scheduler.py --once
  python spark_scheduler.py --task mention_poll --force
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import re
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from lib.diagnostics import setup_component_logging, log_exception

logger = logging.getLogger("spark.scheduler")

SPARK_DIR = Path.home() / ".spark"
SCHEDULER_DIR = SPARK_DIR / "scheduler"
HEARTBEAT_FILE = SCHEDULER_DIR / "heartbeat.json"
# Back-compat path used by some status checks and older scripts.
LEGACY_HEARTBEAT_FILE = SPARK_DIR / "scheduler_heartbeat.json"
STATE_FILE = SCHEDULER_DIR / "state.json"
DRAFT_REPLIES_FILE = SPARK_DIR / "multiplier" / "draft_replies.json"
MULTIPLIER_DB_PATH = SPARK_DIR / "multiplier" / "scored_mentions.db"
TUNEABLES_FILE = SPARK_DIR / "tuneables.json"
OPENCLAW_HANDOFF_DIR = SPARK_DIR / "claw_integration"
OPENCLAW_HANDOFF_FILE = OPENCLAW_HANDOFF_DIR / "latest_trend_handoff.json"
OPENCLAW_WEBHOOK_URL = os.getenv("OPENCLAW_WEBHOOK_URL", "").strip()
CLAWDBOT_WEBHOOK_URL = os.getenv("CLAWDBOT_WEBHOOK_URL", "").strip()
TREND_BUILD_QUEUE_DIR = Path(
    os.getenv(
        "TREND_BUILD_QUEUE_DIR",
        str(Path.home() / ".openclaw" / "workspace" / "spark_build_queue"),
    )
)
OPENCLAW_WORKSPACE = Path(
    os.getenv(
        "SPARK_OPENCLAW_WORKSPACE",
        str(Path.home() / ".openclaw" / "workspace"),
    )
)
TREND_BUILD_QUEUE_FILE = TREND_BUILD_QUEUE_DIR / "latest_build_queue.json"
TREND_BUILD_DISPATCH_LOG = OPENCLAW_HANDOFF_DIR / "build_dispatch_log.jsonl"
TREND_MAX_QUEUED_ITEMS = int(os.getenv("TREND_MAX_QUEUED_ITEMS", "24"))
TREND_BUILD_QUEUE_MIN_CONFIDENCE = float(os.getenv("TREND_BUILD_QUEUE_MIN_CONFIDENCE", "0.62"))
TREND_BUILD_QUEUE_MIN_TREND_SCORE = float(os.getenv("TREND_BUILD_QUEUE_MIN_TREND_SCORE", "0.72"))
TREND_BUILD_QUEUE_MIN_EVIDENCE = int(os.getenv("TREND_BUILD_QUEUE_MIN_EVIDENCE", "10"))
TREND_NOTIFY_OPENCLAW = os.getenv("TREND_NOTIFY_OPENCLAW", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
    "y",
}
TREND_WAKE_OPENCLAW = os.getenv("TREND_WAKE_OPENCLAW", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
    "y",
}
TREND_ENGINE_DEFAULTS = {
    "skill": os.getenv("TREND_BUILD_TARGET_SKILL", "codex").strip().lower(),
    "mcp": os.getenv("TREND_BUILD_TARGET_MCP", "minimax").strip().lower(),
    "startup": os.getenv("TREND_BUILD_TARGET_STARTUP", "opus").strip().lower(),
}
TREND_BUILD_BUCKETS = {
    "skills": "skill",
    "mcps": "mcp",
    "startup_ideas": "startup",
}
TREND_BUILD_TYPE_ALIASES = {
    "startup_idea": "startup",
    "startup_ideas": "startup",
    "mcps": "mcp",
    "skills": "skill",
    "skill": "skill",
    "mcp": "mcp",
}
ENGINE_CANONICAL_MAP = {
    "gpt": "opus",
    "claude": "codex",
    "codex": "codex",
    "minimax": "minimax",
    "opus": "opus",
}

CHECK_INTERVAL = 60  # Main loop checks every 60s which tasks are due


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "enabled": True,
    "mention_poll_interval": 600,
    "engagement_snapshot_interval": 1800,
    "daily_research_interval": 86400,
    "niche_scan_interval": 21600,
    "advisory_review_interval": 43200,
    "mention_poll_enabled": True,
    "engagement_snapshot_enabled": True,
    "daily_research_enabled": True,
    "niche_scan_enabled": True,
    "advisory_review_enabled": True,
    "advisory_review_window_hours": 12,
    "memory_quality_observatory_enabled": True,
}


def load_scheduler_config() -> Dict[str, Any]:
    """Load scheduler config from tuneables.json -> 'scheduler' section."""
    config = dict(DEFAULT_CONFIG)
    try:
        if TUNEABLES_FILE.exists():
            data = json.loads(TUNEABLES_FILE.read_text(encoding="utf-8"))
            cfg = data.get("scheduler")
            if isinstance(cfg, dict):
                config.update(cfg)
    except Exception:
        pass
    return config


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def _canonical_engine(raw_engine: Any, fallback: str = "codex") -> str:
    """Normalize a requested model/engine name to a supported routing key."""
    if not raw_engine:
        return fallback
    normalized = str(raw_engine).strip().lower()
    if not normalized:
        return fallback
    if normalized.startswith("claude-"):
        normalized = "codex"
    if normalized.startswith("gpt-"):
        normalized = "opus"
    return ENGINE_CANONICAL_MAP.get(normalized, normalized)


def _slugify(value: str) -> str:
    """Create a safe filesystem-friendly slug."""
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "trend-work"


def _safe_float(raw: Any, default: float = 0.0) -> float:
    try:
        return float(raw)
    except Exception:
        return default


def _safe_int(raw: Any, default: int = 0) -> int:
    try:
        return int(raw)
    except Exception:
        return default


def _safe_bool(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def _normalize_build_type(item_type: Any, bucket: str) -> str:
    for candidate in (
        str(item_type or "").strip().lower(),
        str(bucket or "").strip().lower(),
    ):
        if candidate in TREND_BUILD_BUCKETS:
            return TREND_BUILD_BUCKETS[candidate]
        if candidate in TREND_BUILD_TYPE_ALIASES:
            return TREND_BUILD_TYPE_ALIASES[candidate]
    return "skill"


def _resolve_engine_for_item(item: Dict[str, Any], item_type: str) -> str:
    defaults = _canonical_engine(TREND_ENGINE_DEFAULTS.get(item_type, "codex"), "codex")
    explicit = item.get("assigned_engine")
    if not explicit:
        explicit = (
            item.get("default_agent")
            or item.get("target_engine")
            or item.get("build_plan", {}).get("target_engine")
        )
    return _canonical_engine(explicit, defaults)


def _resolve_target_path(item: Dict[str, Any], item_type: str) -> str:
    explicit_path = item.get("build_plan", {}).get("target_path")
    if isinstance(explicit_path, str) and explicit_path.strip():
        return str(Path(explicit_path).expanduser())

    name = item.get("name") or f"{_slugify(item.get('source_topic', 'trend'))}-{item_type}"
    plan_root = (
        item.get("build_plan", {}).get("automation_root")
        or str(Path.home() / "trend-builds")
    )
    return str(
        Path(plan_root).expanduser()
        / _canonical_engine(TREND_ENGINE_DEFAULTS.get(item_type, "codex"), "codex")
        / ({"skill": "skills", "mcp": "mcps", "startup": "startups"}.get(item_type, "items"))
        / name
    )


def _collect_build_queue_items(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates = result.get("build_candidates")
    if not isinstance(candidates, dict):
        return []

    jobs: List[Dict[str, Any]] = []
    for bucket, items in candidates.items():
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            item_type = _normalize_build_type(item.get("type"), bucket)
            item_confidence = _safe_float(item.get("confidence"), 0.0)
            trend_profile = item.get("trend_profile", {})
            if not isinstance(trend_profile, dict):
                trend_profile = {}
            if item_confidence < TREND_BUILD_QUEUE_MIN_CONFIDENCE:
                continue
            if _safe_float(trend_profile.get("trend_score"), 0.0) < TREND_BUILD_QUEUE_MIN_TREND_SCORE:
                continue
            if _safe_int(trend_profile.get("evidence_count"), 0) < TREND_BUILD_QUEUE_MIN_EVIDENCE:
                continue

            engine = _resolve_engine_for_item(item, item_type)
            item_slug = _slugify(item.get("name") or item.get("title") or item_type)
            run_payload = {
                "job_id": f"{item_type}-{int(time.time())}-{index}",
                "source_bucket": bucket,
                "build_type": item_type,
                "build_name": item.get("name") or f"{item_slug}_{item_type}",
                "title": item.get("title") or item.get("name") or item_slug,
                "assigned_engine": engine,
                "source_topic": item.get("source_topic", ""),
                "confidence": item_confidence,
                "trend_rank": _safe_int(
                    item.get("trend_profile", {}).get("trend_rank")
                    if isinstance(item.get("trend_profile"), dict)
                    else item.get("trend_rank"),
                    0,
                ),
                "target_path": _resolve_target_path(item, item_type),
                "priority": (
                    item.get("build_plan", {}).get("default_priority")
                    or item.get("priority", "medium")
                ),
                "why_build_now": item.get("why_build_now", ""),
                "launch_pack": item.get("launch_pack", {}),
                "trend_profile": item.get("trend_profile", {}),
                "build_plan": item.get("build_plan", {}),
                "one_shot_spawn": item.get("one_shot_spawn", {}),
                "source_payload": item,
            }
            jobs.append(run_payload)

    jobs.sort(key=lambda j: (j["assigned_engine"], -float(j.get("confidence", 0.0))))
    if len(jobs) <= TREND_MAX_QUEUED_ITEMS:
        return jobs
    return jobs[:TREND_MAX_QUEUED_ITEMS]


def _emit_build_queue(trend_payload: Dict[str, Any]) -> Dict[str, Any]:
    jobs = _collect_build_queue_items(trend_payload)
    build_stats = {
        "queued": len(jobs),
        "by_engine": {"codex": 0, "minimax": 0, "opus": 0},
        "skipped": max(0, len(_collect_build_queue_items(trend_payload)) - len(jobs)),
    }
    if not jobs:
        return {
            "queued": 0,
            "by_engine": build_stats["by_engine"],
            "skipped": 0,
            "manifest": None,
            "log_file": str(TREND_BUILD_DISPATCH_LOG),
        }

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts = time.time()
    for job in jobs:
        build_stats["by_engine"][job["assigned_engine"]] = (
            build_stats["by_engine"].get(job["assigned_engine"], 0) + 1
        )
        job["run_id"] = run_id
        job["scheduled_at"] = datetime.fromtimestamp(ts).isoformat()
        job["source_file"] = str(OPENCLAW_HANDOFF_FILE)

    manifest = {
        "run_id": run_id,
        "generated_at": datetime.fromtimestamp(ts).isoformat(),
        "source": "spark_scheduler.daily_research",
        "run_status": trend_payload.get("status"),
        "topics_processed": trend_payload.get("topics_processed", 0),
        "jobs": jobs,
        "stats": {
            "trends_evaluated": trend_payload.get("trends_evaluated", 0),
            "trends_selected": trend_payload.get("trends_selected", 0),
            "trends_filtered": trend_payload.get("trends_filtered", 0),
            "queue_count": len(jobs),
            "max_queue": TREND_MAX_QUEUED_ITEMS,
        },
    }

    TREND_BUILD_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_file = TREND_BUILD_QUEUE_DIR / f"trend_build_queue_{run_id}.json"
    try:
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        TREND_BUILD_QUEUE_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with TREND_BUILD_DISPATCH_LOG.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps({
                    "run_id": run_id,
                    "generated_at": manifest["generated_at"],
                    "queue_file": str(manifest_file),
                    "queue_count": len(jobs),
                })
                + "\n"
            )
        build_stats["manifest"] = str(manifest_file)
    except Exception as exc:
        logger.debug("Build queue emit failed: %s", exc)
        build_stats["manifest"] = None
        build_stats["error"] = str(exc)

    if TREND_NOTIFY_OPENCLAW:
        try:
            from lib.openclaw_notify import notify_agent, wake_agent
            notify_agent(
                (
                    f"Trend build queue generated ({run_id}): "
                    f"{len(jobs)} jobs -> "
                    f"codex {build_stats['by_engine'].get('codex', 0)}, "
                    f"minimax {build_stats['by_engine'].get('minimax', 0)}, "
                    f"opus {build_stats['by_engine'].get('opus', 0)}."
                ),
                priority="normal",
            )
            if TREND_WAKE_OPENCLAW and len(jobs) >= 1:
                wake_agent(
                    "Spark trend build jobs are ready. Review the latest_queue manifest in "
                    "~/.openclaw/workspace/spark_build_queue/latest_build_queue.json."
                )
        except Exception as exc:
            logger.debug("OpenClaw handoff notify failed: %s", exc)
            build_stats.setdefault("notifications", {})["openclaw_error"] = str(exc)

    build_stats["manifest"] = build_stats.get("manifest")
    return build_stats


def _load_state() -> Dict[str, Any]:
    """Load scheduler state from disk."""
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_state(state: Dict[str, Any]) -> None:
    """Persist scheduler state."""
    try:
        SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("Failed to save state: %s", e)


def write_scheduler_heartbeat(task_stats: Dict[str, Any]) -> None:
    """Write heartbeat file(s) for watchdog monitoring."""
    payload = json.dumps({"ts": time.time(), "stats": task_stats}, indent=2)
    try:
        SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_FILE.write_text(payload, encoding="utf-8")
    except Exception:
        pass

    # Keep legacy root-level heartbeat for existing tooling.
    try:
        LEGACY_HEARTBEAT_FILE.write_text(payload, encoding="utf-8")
    except Exception:
        pass


def _read_heartbeat_ts(path: Path) -> Optional[float]:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = float(data.get("ts", 0))
        return ts if ts > 0 else None
    except Exception:
        return None


def scheduler_heartbeat_age_s() -> Optional[float]:
    """Return heartbeat age in seconds, or None if missing."""
    now = time.time()
    candidates = [_read_heartbeat_ts(HEARTBEAT_FILE)]
    if HEARTBEAT_FILE == SCHEDULER_DIR / "heartbeat.json":
        candidates.append(_read_heartbeat_ts(LEGACY_HEARTBEAT_FILE))
    latest = max((ts for ts in candidates if ts), default=None)
    if latest is None:
        return None
    return max(0.0, now - latest)


def _post_json_to_webhook(url: str, payload: Dict[str, Any]) -> bool:
    """Post payload to a webhook if URL is configured."""
    if not url:
        return False
    try:
        data = json.dumps(payload, default=str).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:
        logger.debug("Failed webhook post to %s: %s", url, exc)
        return False


def _run_external_trend_builder() -> Dict[str, Any]:
    """Run trend research in the standalone spark-x-builder repo."""
    builder_root = Path(
        os.getenv(
            "SPARK_X_BUILDER_PATH",
            str(Path(__file__).resolve().parent.parent / "spark-x-builder"),
        )
    ).expanduser()
    script_path = builder_root / "scripts" / "daily_trend_research.py"
    if not script_path.exists():
        return {"error": f"Spark X Builder script missing: {script_path}"}

    proc = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(builder_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )

    raw_output = (proc.stdout or "").rstrip()
    if proc.returncode != 0:
        return {
            "error": f"trend_builder_exit={proc.returncode}",
            "stderr": (proc.stderr or "").strip()[:2000],
            "stdout": raw_output[-2000:],
        }

    start = raw_output.rfind("{")
    end = raw_output.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {"error": "trend_builder_no_json", "stdout": raw_output[-2000:]}

    payload_raw = raw_output[start:end + 1]
    try:
        payload = json.loads(payload_raw)
    except Exception:
        return {"error": "trend_builder_bad_json", "stdout": raw_output[-2000:]}

    payload["runner"] = {
        "repo": "spark-x-builder",
        "path": str(script_path.parent.parent),
        "command": " ".join([sys.executable, str(script_path)]),
    }
    return payload


def _emit_claw_handoff(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a stable handoff payload for OpenClaw/Clawdbot consumers."""
    handoff = {
        "generated_at": datetime.fromtimestamp(time.time(), tz=None).isoformat(),
        "source": "spark_scheduler.daily_research",
        "build_queue_file": str(TREND_BUILD_QUEUE_FILE),
        "status": payload.get("status"),
        "topics_processed": payload.get("topics_processed"),
        "queries_run": payload.get("queries_run"),
        "insights_extracted": payload.get("insights_extracted"),
        "recommendations": payload.get("recommendations"),
        "build_candidates": payload.get("build_candidates"),
        "report": payload.get("report"),
        "runner": payload.get("runner", {}),
    }

    try:
        OPENCLAW_HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
        OPENCLAW_HANDOFF_FILE.write_text(json.dumps(handoff, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug("Failed writing claw handoff: %s", exc)
        handoff["handoff_error"] = str(exc)
        return handoff

    delivered = {
        "openclaw_webhook_ok": _post_json_to_webhook(OPENCLAW_WEBHOOK_URL, handoff),
        "clawdbot_webhook_ok": _post_json_to_webhook(CLAWDBOT_WEBHOOK_URL, handoff),
    }
    handoff["deliveries"] = delivered
    return handoff


# ---------------------------------------------------------------------------
# Draft reply queue
# ---------------------------------------------------------------------------

def _save_draft_reply(decision: Dict[str, Any]) -> None:
    """Append a draft reply to the queue for human review."""
    try:
        DRAFT_REPLIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        drafts = []
        if DRAFT_REPLIES_FILE.exists():
            try:
                drafts = json.loads(DRAFT_REPLIES_FILE.read_text(encoding="utf-8"))
            except Exception:
                drafts = []

        drafts.append({
            "tweet_id": decision.get("tweet_id", ""),
            "author": decision.get("author", ""),
            "action": decision.get("action", ""),
            "reply_text": decision.get("reply_text", ""),
            "reasoning": decision.get("reasoning", ""),
            "multiplier_tier": decision.get("multiplier_tier", ""),
            "queued_at": time.time(),
            "posted": False,
        })
        # Keep max 200 entries
        drafts = drafts[-200:]
        DRAFT_REPLIES_FILE.write_text(json.dumps(drafts, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("Failed to save draft reply: %s", e)


def get_pending_drafts() -> List[Dict]:
    """Get unposted draft replies for human review."""
    try:
        if not DRAFT_REPLIES_FILE.exists():
            return []
        drafts = json.loads(DRAFT_REPLIES_FILE.read_text(encoding="utf-8"))
        return [d for d in drafts if not d.get("posted", False)]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Task: Mention Poll
# ---------------------------------------------------------------------------

def task_mention_poll(state: Dict[str, Any]) -> Dict[str, Any]:
    """Poll @mentions, score through Multiplier, queue draft replies."""
    from lib.x_client import get_x_client

    # Resolve spark-multiplier path
    multiplier_candidates = [
        Path(__file__).resolve().parent.parent / "spark-multiplier",
        Path(__file__).resolve().parent.parent / "spark-multiplier",
    ]
    multiplier_path = None
    for candidate in multiplier_candidates:
        if (candidate / "src" / "mention_monitor.py").exists():
            multiplier_path = candidate
            break

    if not multiplier_path:
        return {"error": "spark-multiplier not found"}

    if str(multiplier_path) not in sys.path:
        sys.path.insert(0, str(multiplier_path))

    from src.mention_monitor import MentionMonitor
    from src.models import MentionEvent
    from src.storage import Storage

    client = get_x_client()
    since_id = state.get("last_mention_id")
    raw_mentions = client.get_mentions(since_id=since_id, max_results=50)

    if not raw_mentions:
        return {"mentions_found": 0, "decisions": 0, "drafts_queued": 0}

    # Convert to MentionEvent objects
    mention_events = []
    for m in raw_mentions:
        mention_events.append(MentionEvent(
            tweet_id=m["tweet_id"],
            author=m.get("author", ""),
            text=m.get("text", ""),
            likes=m.get("likes", 0),
            retweets=m.get("retweets", 0),
            replies=m.get("replies", 0),
            author_followers=m.get("author_followers", 0),
            author_account_age_days=m.get("author_account_age_days", 0),
            created_at=m.get("created_at", ""),
            is_reply=m.get("is_reply", False),
            parent_tweet_id=m.get("parent_tweet_id", ""),
        ))

    # Process through Multiplier pipeline
    storage = Storage(db_path=MULTIPLIER_DB_PATH)
    monitor = MentionMonitor(storage=storage)
    decisions = monitor.process_mentions(mention_events)

    # Queue draft replies for human review
    drafts_queued = 0
    for d in decisions:
        if d.action in ("reward", "engage"):
            draft = {
                "tweet_id": d.tweet_id,
                "author": d.author,
                "action": d.action,
                "reply_text": d.reply_text,
                "reasoning": d.reasoning,
            }
            if d.multiplier:
                draft["multiplier_tier"] = d.multiplier.multiplier_tier
            _save_draft_reply(draft)
            drafts_queued += 1

    # Update since_id to newest mention
    if raw_mentions:
        newest_id = max(raw_mentions, key=lambda m: int(m["tweet_id"]))["tweet_id"]
        state["last_mention_id"] = newest_id

    logger.info(
        "mention_poll: %d mentions, %d decisions, %d drafts",
        len(raw_mentions), len(decisions), drafts_queued,
    )
    return {
        "mentions_found": len(raw_mentions),
        "decisions": len(decisions),
        "drafts_queued": drafts_queued,
    }


# ---------------------------------------------------------------------------
# Task: Engagement Snapshots
# ---------------------------------------------------------------------------

def task_engagement_snapshots(state: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch actual metrics for pending Pulse snapshots."""
    from lib.x_client import get_x_client
    from lib.engagement_tracker import get_engagement_tracker

    client = get_x_client()
    tracker = get_engagement_tracker()
    pending = tracker.get_pending_snapshots()

    if not pending:
        return {"pending": 0, "taken": 0}

    taken = 0
    for tweet_id, label in pending:
        metrics = client.get_tweet_by_id(tweet_id)
        if metrics:
            tracker.take_snapshot(
                tweet_id,
                likes=metrics.get("likes", 0),
                replies=metrics.get("replies", 0),
                retweets=metrics.get("retweets", 0),
                impressions=metrics.get("impressions", 0),
            )
            taken += 1

    tracker.cleanup_old(max_age_days=7)
    logger.info("engagement_snapshots: %d pending, %d taken", len(pending), taken)
    return {"pending": len(pending), "taken": taken}


# ---------------------------------------------------------------------------
# Task: Daily Research
# ---------------------------------------------------------------------------

def task_daily_research(state: Dict[str, Any]) -> Dict[str, Any]:
    """Delegate research and candidate generation to the standalone spark-x-builder."""
    del state  # state not required for external execution.

    result = _run_external_trend_builder()
    if "error" in result:
        logger.warning("daily_research: delegated run failed: %s", result.get("error"))
        return {"error": result.get("error"), "stdout": result.get("stdout", ""), "stderr": result.get("stderr", "")}

    handoff = _emit_claw_handoff(result)
    build_queue = _emit_build_queue(result)
    handoff["build_queue"] = build_queue
    build_candidates = result.get("build_candidates", {})
    logger.info(
        "daily_research: delegated run complete: %d candidates (S:%d M:%d U:%d), queue=%d delivered=%s",
        len(build_candidates.get("skills", []))
        + len(build_candidates.get("mcps", []))
        + len(build_candidates.get("startup_ideas", [])),
        len(build_candidates.get("skills", [])),
        len(build_candidates.get("mcps", [])),
        len(build_candidates.get("startup_ideas", [])),
        build_queue.get("queued", 0),
        handoff.get("deliveries", {}),
    )
    return {
        "status": result.get("status"),
        "insights": result.get("insights_extracted", 0),
        "recommendations": result.get("recommendations", 0),
        "topics_scanned": result.get("topics_processed", 0),
        "queries_run": result.get("queries_run", 0),
        "build_candidates": {
            "skills": len(build_candidates.get("skills", [])),
            "mcps": len(build_candidates.get("mcps", [])),
            "startups": len(build_candidates.get("startup_ideas", [])),
        },
        "build_queue": build_queue,
        "handoff_file": str(OPENCLAW_HANDOFF_FILE),
        "deliveries": handoff.get("deliveries", {}),
    }


# ---------------------------------------------------------------------------
# Task: Niche Scan
# ---------------------------------------------------------------------------

def task_niche_scan(state: Dict[str, Any]) -> Dict[str, Any]:
    """Update NicheNet with accounts from recent research."""
    from lib.niche_mapper import get_niche_mapper

    mapper = get_niche_mapper()
    report_file = SPARK_DIR / "research_reports" / "latest.json"

    if not report_file.exists():
        return {"accounts_updated": 0}

    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except Exception:
        return {"accounts_updated": 0}

    # Extract unique authors from insights
    updated = 0
    seen = set()
    for insight in report.get("all_insights", []):
        # Insights don't always have author info, but scan for mentions
        topic = insight.get("topic", "")
        text = insight.get("text", "")
        engagement = insight.get("engagement", 0)

        if engagement < 10:
            continue

        # Look for @mentions in the text
        import re
        mentions = re.findall(r"@(\w+)", text)
        for handle in mentions:
            if handle.lower() in seen:
                continue
            seen.add(handle.lower())
            relevance = min(0.8, 0.3 + engagement / 200)
            mapper.discover_account(
                handle=handle,
                topics=[topic],
                relevance=relevance,
                discovered_via="scheduler_niche_scan",
            )
            updated += 1

    stats = mapper.get_network_stats()
    logger.info("niche_scan: %d accounts updated, %d total tracked",
                updated, stats.get("tracked_accounts", 0))
    return {"accounts_updated": updated, "total_tracked": stats.get("tracked_accounts", 0)}


def task_advisory_review(state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a trace-backed advisory self-review report."""
    del state  # State not required for this task.

    # File-based gap guard: skip if a recent report exists (survives scheduler restarts)
    reports_dir = Path(__file__).resolve().parent / "docs" / "reports"
    min_gap_hours = 6
    if reports_dir.exists():
        import glob as _glob
        recent = sorted(_glob.glob(str(reports_dir / "*_advisory_self_review.md")))
        if recent:
            newest = Path(recent[-1])
            age_hours = (time.time() - newest.stat().st_mtime) / 3600
            if age_hours < min_gap_hours:
                logger.info("advisory_review: skipped (recent report %.1fh old, min gap %dh)", age_hours, min_gap_hours)
                return {"status": "skipped", "reason": f"recent report exists ({age_hours:.1f}h old)"}

    script = Path(__file__).resolve().parent / "scripts" / "advisory_self_review.py"
    if not script.exists():
        return {"error": f"missing script: {script}"}

    cfg = load_scheduler_config()
    window_h = int(cfg.get("advisory_review_window_hours", 12) or 12)
    cmd = [
        sys.executable,
        str(script),
        "--window-hours",
        str(max(1, window_h)),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(Path(__file__).resolve().parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        return {"error": f"self_review_failed: {stderr[:300]}"}

    line = (proc.stdout or "").strip().splitlines()
    msg = line[-1] if line else ""

    # Keep retrieval quality guardrails fresh at least daily.
    try:
        import glob as _glob

        observatory_enabled = _safe_bool(cfg.get("memory_quality_observatory_enabled", True), True)
        if not observatory_enabled:
            logger.info("memory_quality_observatory: disabled by scheduler config")
            logger.info("advisory_review: %s", msg or "ok")
            return {"status": "ok", "message": msg}

        observatory_script = Path(__file__).resolve().parent / "scripts" / "memory_quality_observatory.py"
        if observatory_script.exists():
            recent_obs = sorted(_glob.glob(str(reports_dir / "*_memory_quality_observatory.md")))
            run_observatory = True
            if recent_obs:
                newest_obs = Path(recent_obs[-1])
                obs_age_hours = (time.time() - newest_obs.stat().st_mtime) / 3600
                if obs_age_hours < 24:
                    run_observatory = False
                    logger.info(
                        "memory_quality_observatory: skipped (recent report %.1fh old, min gap 24h)",
                        obs_age_hours,
                    )
            if run_observatory:
                obs_proc = subprocess.run(
                    [sys.executable, str(observatory_script)],
                    cwd=str(Path(__file__).resolve().parent),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if obs_proc.returncode != 0:
                    logger.warning(
                        "memory_quality_observatory failed: %s",
                        (obs_proc.stderr or "").strip()[:300],
                    )
                else:
                    logger.info("memory_quality_observatory: refreshed")
    except Exception as exc:
        logger.warning("memory_quality_observatory integration failed: %s", exc)

    logger.info("advisory_review: %s", msg or "ok")
    return {"status": "ok", "message": msg}


# ---------------------------------------------------------------------------
# Task registry
# ---------------------------------------------------------------------------

TASKS = {
    "mention_poll": {
        "fn": task_mention_poll,
        "config_key_interval": "mention_poll_interval",
        "config_key_enabled": "mention_poll_enabled",
    },
    "engagement_snapshots": {
        "fn": task_engagement_snapshots,
        "config_key_interval": "engagement_snapshot_interval",
        "config_key_enabled": "engagement_snapshot_enabled",
    },
    "daily_research": {
        "fn": task_daily_research,
        "config_key_interval": "daily_research_interval",
        "config_key_enabled": "daily_research_enabled",
    },
    "niche_scan": {
        "fn": task_niche_scan,
        "config_key_interval": "niche_scan_interval",
        "config_key_enabled": "niche_scan_enabled",
    },
    "advisory_review": {
        "fn": task_advisory_review,
        "config_key_interval": "advisory_review_interval",
        "config_key_enabled": "advisory_review_enabled",
    },
}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_due_tasks(
    config: Dict[str, Any],
    state: Dict[str, Any],
    only_task: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Check which tasks are due, run them sequentially, update state."""
    now = time.time()
    combined_stats: Dict[str, Any] = {}

    for task_name, task_info in TASKS.items():
        if only_task and task_name != only_task:
            continue

        enabled = config.get(task_info["config_key_enabled"], True)
        if not enabled and not force:
            continue

        interval = config.get(task_info["config_key_interval"], 600)
        last_run = state.get(f"last_run_{task_name}", 0.0)

        if not force and (now - last_run) < interval:
            continue

        logger.info("Running task: %s", task_name)
        try:
            stats = task_info["fn"](state)
            state[f"last_run_{task_name}"] = time.time()
            state[f"last_result_{task_name}"] = "ok"
            combined_stats[task_name] = stats
        except Exception as e:
            state[f"last_result_{task_name}"] = f"error: {str(e)[:200]}"
            log_exception("scheduler", f"task {task_name} failed", e)
            combined_stats[task_name] = {"error": str(e)[:200]}

    _save_state(state)
    return combined_stats


def main():
    ap = argparse.ArgumentParser(description="Spark X Intelligence Scheduler")
    ap.add_argument("--once", action="store_true", help="Run all due tasks once then exit")
    ap.add_argument("--task", type=str, default=None, help="Run a specific task")
    ap.add_argument("--force", action="store_true", help="Run even if not due")
    args = ap.parse_args()

    setup_component_logging("scheduler")
    logger.info("Spark scheduler starting")

    config = load_scheduler_config()
    if not config.get("enabled", True):
        logger.info("Scheduler disabled in tuneables.json")
        return

    state = _load_state()
    stop_event = threading.Event()

    def _shutdown(signum=None, frame=None):
        logger.info("Scheduler shutting down")
        stop_event.set()

    try:
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)
    except Exception:
        pass

    # Single run mode
    if args.once or args.task:
        stats = run_due_tasks(
            config, state,
            only_task=args.task,
            force=args.force or bool(args.task),
        )
        write_scheduler_heartbeat(stats)
        logger.info("Single run complete: %s", json.dumps(stats, default=str))
        return

    # Daemon loop
    logger.info("Scheduler daemon started (check interval: %ds)", CHECK_INTERVAL)
    while not stop_event.is_set():
        try:
            config = load_scheduler_config()  # Hot reload
            stats = run_due_tasks(config, state)
            write_scheduler_heartbeat(stats)
            if stats:
                logger.info("Tasks completed: %s", list(stats.keys()))
        except Exception as e:
            log_exception("scheduler", "scheduler cycle failed", e)

        stop_event.wait(CHECK_INTERVAL)

    logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
