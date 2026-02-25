"""
Chip Insight Merger - Bridge chip insights into the cognitive learning pipeline.

Chips capture domain-specific insights that are stored separately.
This module merges high-value chip insights into the main cognitive system
so they can be validated, promoted, and injected into context.
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

from lib.cognitive_learner import get_cognitive_learner, CognitiveCategory
from lib.config_authority import resolve_section
from lib.exposure_tracker import record_exposures
from lib.queue import _tail_lines
from lib.chips.registry import get_registry


CHIP_INSIGHTS_DIR = Path.home() / ".spark" / "chip_insights"
MERGE_STATE_FILE = Path.home() / ".spark" / "chip_merge_state.json"
TUNEABLES_FILE = Path.home() / ".spark" / "tuneables.json"
LOW_QUALITY_COOLDOWN_S = 10 * 60  # 10 min (was 30min — still too slow for merge cycles)
MAX_REJECTED_TRACKING = 2000
DUPLICATE_CHURN_RATIO = 0.8
DUPLICATE_CHURN_MIN_PROCESSED = 10
DUPLICATE_CHURN_COOLDOWN_S = 30 * 60
LEARNING_DISTILLATIONS_FILE = Path.home() / ".spark" / "chip_learning_distillations.jsonl"

CHIP_TELEMETRY_BLOCKLIST = {"spark-core", "bench_core", "bench-core"}
TELEMETRY_MARKERS = (
    "post_tool",
    "pre_tool",
    "tool_name:",
    "event_type:",
    "status:",
    "cwd:",
    "file_path:",
    "user_prompt_signal",
    "tool_cycle",
    "command:",
)
TELEMETRY_OBSERVER_BLOCKLIST = {
    "tool_event",
    "pre_tool_event",
    "post_tool_event",
    "tool_cycle",
    "tool_failure",
    "pre_tool_use",
    "post_tool_use",
    "post_tool_use_failure",
    "user_prompt_signal",
    "user_prompt",
    "chip_level",
}
SCHEMA_TELEMETRY_FIELD_KEYS = {
    "tool_name",
    "tool",
    "command",
    "cwd",
    "file_path",
    "event_type",
    "status",
    "success",
    "duration_ms",
    "session_id",
    "project",
    "chip",
    "trigger",
}
ACTIONABLE_MARKERS = (
    "should",
    "avoid",
    "prefer",
    "because",
    "works better",
    "caused by",
    "due to",
    "next time",
    "use ",
    "do not ",
    "never ",
    "always ",
)
NON_LEARNING_PATTERNS = (
    re.compile(r"^[\[\(]?[a-z0-9 _-]+[\]\)]?\s*(post_tool|pre_tool|tool_failure|tool_event|user_prompt)\b", re.I),
    re.compile(r"(?i)\b(?:invoke-webrequest|get-process|start-sleep|\$erroractionpreference)\b"),
    re.compile(r"(?i)\b(?:c:\\\\users\\\\|/users/|/tmp/|\\.jsonl|\\.py|\\.md)\b"),
)


# Map chip domains to cognitive categories
CHIP_TO_CATEGORY = {
    "market-intel": CognitiveCategory.CONTEXT,
    "game_dev": CognitiveCategory.REASONING,
    "game-dev": CognitiveCategory.REASONING,
    "marketing": CognitiveCategory.CONTEXT,
    "vibecoding": CognitiveCategory.WISDOM,
    "biz-ops": CognitiveCategory.CONTEXT,
    "bench-core": CognitiveCategory.SELF_AWARENESS,
    "bench_core": CognitiveCategory.SELF_AWARENESS,
    "spark-core": CognitiveCategory.META_LEARNING,
}

DOMAIN_TO_CATEGORY = {
    "coding": CognitiveCategory.REASONING,
    "development": CognitiveCategory.REASONING,
    "debugging": CognitiveCategory.REASONING,
    "tools": CognitiveCategory.META_LEARNING,
    "engineering": CognitiveCategory.REASONING,
    "delivery": CognitiveCategory.WISDOM,
    "reliability": CognitiveCategory.WISDOM,
    "game_dev": CognitiveCategory.REASONING,
    "game": CognitiveCategory.REASONING,
    "marketing": CognitiveCategory.CONTEXT,
    "growth": CognitiveCategory.CONTEXT,
    "strategy": CognitiveCategory.CONTEXT,
    "pricing": CognitiveCategory.CONTEXT,
    "benchmarking": CognitiveCategory.SELF_AWARENESS,
}


def _load_merge_state() -> Dict[str, Any]:
    """Load the merge state tracking which insights have been merged."""
    if not MERGE_STATE_FILE.exists():
        return {
            "merged_hashes": [],
            "last_merge": None,
            "rejected_low_quality": {},
            "duplicate_churn_until": 0.0,
        }
    try:
        state = json.loads(MERGE_STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            return {
                "merged_hashes": [],
                "last_merge": None,
                "rejected_low_quality": {},
                "duplicate_churn_until": 0.0,
            }
        if not isinstance(state.get("merged_hashes"), list):
            state["merged_hashes"] = []
        if not isinstance(state.get("rejected_low_quality"), dict):
            state["rejected_low_quality"] = {}
        try:
            state["duplicate_churn_until"] = float(state.get("duplicate_churn_until") or 0.0)
        except Exception:
            state["duplicate_churn_until"] = 0.0
        return state
    except Exception:
        return {
            "merged_hashes": [],
            "last_merge": None,
            "rejected_low_quality": {},
            "duplicate_churn_until": 0.0,
        }


def _save_merge_state(state: Dict[str, Any]):
    """Save the merge state."""
    MERGE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MERGE_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _hash_insight(chip_id: str, content: str) -> str:
    """Create a stable dedupe hash for chip insight content."""
    import hashlib
    normalized = " ".join((content or "").strip().lower().split())
    raw = f"{chip_id.strip().lower()}|{normalized[:180]}".encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:12]


def _prune_rejected_state(entries: Dict[str, Any], now_ts: float) -> Dict[str, float]:
    """Keep recent low-quality rejections only."""
    kept: Dict[str, float] = {}
    for key, value in entries.items():
        try:
            ts = float(value)
        except Exception:
            continue
        if ts <= 0:
            continue
        if (now_ts - ts) <= LOW_QUALITY_COOLDOWN_S:
            kept[key] = ts
    if len(kept) > MAX_REJECTED_TRACKING:
        # Keep most recent signatures only.
        ordered = sorted(kept.items(), key=lambda kv: kv[1], reverse=True)[:MAX_REJECTED_TRACKING]
        kept = {k: v for k, v in ordered}
    return kept


def _load_merge_tuneables() -> Dict[str, float]:
    cfg: Dict[str, Any] = {}
    try:
        use_host_tuneables = True
        if (
            "pytest" in sys.modules
            and str(os.environ.get("SPARK_TEST_ALLOW_HOME_TUNEABLES", "")).strip().lower()
            not in {"1", "true", "yes", "on"}
        ):
            try:
                use_host_tuneables = TUNEABLES_FILE.resolve() != (Path.home() / ".spark" / "tuneables.json").resolve()
            except Exception:
                use_host_tuneables = False
        if use_host_tuneables:
            cfg = resolve_section("chip_merge", runtime_path=TUNEABLES_FILE).data
    except Exception:
        cfg = {}

    ratio = DUPLICATE_CHURN_RATIO
    min_processed = DUPLICATE_CHURN_MIN_PROCESSED
    cooldown_s = DUPLICATE_CHURN_COOLDOWN_S

    try:
        ratio = max(0.5, min(1.0, float(cfg.get("duplicate_churn_ratio", ratio))))
    except Exception:
        pass
    try:
        min_processed = max(5, min(1000, int(cfg.get("duplicate_churn_min_processed", min_processed))))
    except Exception:
        pass
    try:
        cooldown_s = max(60, min(24 * 3600, int(cfg.get("duplicate_churn_cooldown_s", cooldown_s))))
    except Exception:
        pass
    min_cognitive_value = 0.35
    min_actionability = 0.25
    min_transferability = 0.2
    min_statement_len = 28
    try:
        min_cognitive_value = max(0.0, min(1.0, float(cfg.get("min_cognitive_value", min_cognitive_value))))
    except Exception:
        pass
    try:
        min_actionability = max(0.0, min(1.0, float(cfg.get("min_actionability", min_actionability))))
    except Exception:
        pass
    try:
        min_transferability = max(0.0, min(1.0, float(cfg.get("min_transferability", min_transferability))))
    except Exception:
        pass
    try:
        min_statement_len = max(12, min(240, int(cfg.get("min_statement_len", min_statement_len))))
    except Exception:
        pass

    return {
        "duplicate_churn_ratio": float(ratio),
        "duplicate_churn_min_processed": int(min_processed),
        "duplicate_churn_cooldown_s": int(cooldown_s),
        "min_cognitive_value": float(min_cognitive_value),
        "min_actionability": float(min_actionability),
        "min_transferability": float(min_transferability),
        "min_statement_len": int(min_statement_len),
    }


def _norm_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _strip_chip_prefix(text: str) -> str:
    out = str(text or "").strip()
    # Remove common chip label prefixes: [X Intelligence], [Chip:*], etc.
    out = re.sub(r"^\[[^\]]{2,80}\]\s*", "", out)
    out = re.sub(r"^\[[^\]]{2,80}\]\s*", "", out)  # second pass for stacked tags
    return _norm_whitespace(out)


def _looks_like_telemetry(chip_id: str, text: str) -> bool:
    cid = str(chip_id or "").strip().lower()
    if cid in CHIP_TELEMETRY_BLOCKLIST:
        return True
    body = str(text or "").strip().lower()
    if not body:
        return True
    if any(marker in body for marker in TELEMETRY_MARKERS):
        return True
    for pattern in NON_LEARNING_PATTERNS:
        if pattern.search(body):
            return True
    return False


def _is_telemetry_observer(observer_name: str) -> bool:
    name = str(observer_name or "").strip().lower()
    return bool(name and name in TELEMETRY_OBSERVER_BLOCKLIST)


def _format_value(value: Any, max_len: int = 84) -> str:
    text = _norm_whitespace(str(value or ""))
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _field_based_learning_statement(chip_id: str, captured_data: Dict[str, Any]) -> str:
    fields = (captured_data or {}).get("fields") or {}
    if not isinstance(fields, dict) or not fields:
        return ""

    cid = str(chip_id or "").strip().lower().replace("_", "-")
    if cid in {"social-convo", "social-conversation"}:
        ranking = _format_value(fields.get("trigger_ranking") or "")
        q_vs_s = _format_value(fields.get("question_vs_statement") or "")
        topics = _format_value(fields.get("top_topics") or "")
        parts = []
        if ranking:
            parts.append(f"trigger_ranking={ranking}")
        if q_vs_s:
            parts.append(f"question_vs_statement={q_vs_s}")
        if topics:
            parts.append(f"top_topics={topics}")
        if parts:
            return f"Prefer conversation patterns backed by observed evidence ({', '.join(parts)})."

    # Generic fallback for structured fields that are not raw telemetry.
    ignore_keys = {"tool_name", "command", "status", "event_type", "cwd", "file_path", "success", "text", "tweet_text", "content"}
    keyvals = []
    for key, value in fields.items():
        k = str(key or "").strip().lower()
        if not k or k in ignore_keys:
            continue
        v = _format_value(value)
        if not v:
            continue
        keyvals.append(f"{k}={v}")
        if len(keyvals) >= 3:
            break
    if keyvals:
        if "engagement" in cid:
            return f"Use engagement evidence ({', '.join(keyvals)}) when deciding next actions."
        return f"Use observed domain signals ({', '.join(keyvals)}) when deciding next actions."
    return ""


def _payload_based_learning_statement(captured_data: Dict[str, Any], min_len: int) -> str:
    payload = (captured_data or {}).get("learning_payload") or {}
    if not isinstance(payload, dict):
        return ""

    decision = _norm_whitespace(payload.get("decision") or "")
    rationale = _norm_whitespace(payload.get("rationale") or "")
    expected = _norm_whitespace(payload.get("expected_outcome") or "")
    evidence_raw = payload.get("evidence") or []
    if not isinstance(evidence_raw, list):
        return ""

    evidence = []
    for item in evidence_raw:
        text = _norm_whitespace(item)
        if not text or len(text) < 6:
            continue
        lowered = text.lower()
        key = lowered.split("=", 1)[0].strip()
        if key in SCHEMA_TELEMETRY_FIELD_KEYS:
            continue
        if any(marker in lowered for marker in ("tool_name:", "event_type:", "cwd:", "file_path:")):
            continue
        evidence.append(text)
        if len(evidence) >= 3:
            break

    if len(decision) < 16 or len(rationale) < 20 or len(expected) < 12:
        return ""
    if not evidence:
        return ""

    text = (
        f"{decision} because {rationale} "
        f"Evidence ({', '.join(evidence)}). "
        f"Expected outcome: {expected}."
    )
    text = _norm_whitespace(text)
    if len(text) < int(min_len):
        return ""
    return text[:320]


def _distill_learning_statement(
    chip_id: str,
    content: str,
    captured_data: Dict[str, Any],
    min_len: int,
    observer_name: str = "",
) -> str:
    if _is_telemetry_observer(observer_name):
        return ""

    payload_statement = _payload_based_learning_statement(captured_data, min_len=min_len)
    if payload_statement:
        return payload_statement

    text = _strip_chip_prefix(content)
    if _looks_like_telemetry(chip_id, text):
        text = ""

    if text:
        # Reduce noisy metadata clauses while preserving learnable core.
        text = re.sub(r"\b(?:tool_name|event_type|status|cwd|file_path|command)\s*:\s*[^,;]+", "", text, flags=re.I)
        text = _norm_whitespace(text.strip(" ,;|"))

    if not text or len(text) < int(min_len):
        text = _field_based_learning_statement(chip_id, captured_data)

    text = _norm_whitespace(text)
    if len(text) < int(min_len):
        return ""

    lower = text.lower()
    if _looks_like_telemetry(chip_id, lower):
        return ""
    if not any(marker in lower for marker in ACTIONABLE_MARKERS):
        # Allow strong evidence-style distilled statements.
        if "evidence (" not in lower and "observed" not in lower:
            return ""
    return text[:320]


def _is_learning_quality_ok(quality: Dict[str, Any], limits: Dict[str, float]) -> bool:
    try:
        cognitive_value = float(quality.get("cognitive_value", 0.0) or 0.0)
    except Exception:
        cognitive_value = 0.0
    try:
        actionability = float(quality.get("actionability", 0.0) or 0.0)
    except Exception:
        actionability = 0.0
    try:
        transferability = float(quality.get("transferability", 0.0) or 0.0)
    except Exception:
        transferability = 0.0

    return (
        cognitive_value >= float(limits.get("min_cognitive_value", 0.35))
        and actionability >= float(limits.get("min_actionability", 0.25))
        and transferability >= float(limits.get("min_transferability", 0.2))
    )


def _infer_category(chip_id: str, captured_data: Dict[str, Any], content: str) -> CognitiveCategory:
    """Infer cognitive category for chips with robust fallback."""
    if chip_id in CHIP_TO_CATEGORY:
        return CHIP_TO_CATEGORY[chip_id]
    canonical = chip_id.replace("_", "-")
    if canonical in CHIP_TO_CATEGORY:
        return CHIP_TO_CATEGORY[canonical]

    # Try installed chip metadata (domains).
    try:
        chip = get_registry().get_chip(chip_id)
    except Exception:
        chip = None
    if chip and getattr(chip, "domains", None):
        for domain in chip.domains:
            key = str(domain).strip().lower().replace("-", "_")
            if key in DOMAIN_TO_CATEGORY:
                return DOMAIN_TO_CATEGORY[key]

    # Heuristic fallback from content.
    text = f"{chip_id} {content or ''}".lower()
    if any(k in text for k in ("prefer", "should", "avoid", "never", "always", "lesson")):
        return CognitiveCategory.WISDOM
    if any(k in text for k in ("error", "failed", "fix", "issue", "debug")):
        return CognitiveCategory.REASONING
    if any(k in text for k in ("user", "audience", "market", "customer", "campaign")):
        return CognitiveCategory.CONTEXT
    if any(k in text for k in ("confidence", "benchmark", "method", "self")):
        return CognitiveCategory.SELF_AWARENESS
    return CognitiveCategory.CONTEXT


def _tail_jsonl(path: Path, limit: int) -> List[Dict[str, Any]]:
    """Read the last N JSONL rows without loading the whole file."""
    if limit <= 0 or not path.exists():
        return []

    out: List[Dict[str, Any]] = []
    for raw in _tail_lines(path, limit):
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except Exception:
            continue
    return out


def _count_jsonl_lines(path: Path) -> int:
    """Count non-empty JSONL rows with streaming IO."""
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def load_chip_insights(chip_id: str = None, limit: int = 100) -> List[Dict]:
    """Load chip insights from disk."""
    insights = []

    if chip_id:
        files = [CHIP_INSIGHTS_DIR / f"{chip_id}.jsonl"]
    else:
        files = list(CHIP_INSIGHTS_DIR.glob("*.jsonl")) if CHIP_INSIGHTS_DIR.exists() else []

    for file_path in files:
        if not file_path.exists():
            continue
        try:
            # Tail-read avoids loading very large chip files into memory each cycle.
            insights.extend(_tail_jsonl(file_path, limit=limit))
        except Exception:
            continue

    # Sort by timestamp descending
    insights.sort(key=lambda i: i.get("timestamp", ""), reverse=True)
    return insights[:limit]


def merge_chip_insights(
    min_confidence: float = 0.7,
    min_quality_score: float = 0.7,
    limit: int = 50,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Merge high-confidence chip insights into the cognitive learning system.

    This is the key function that bridges domain-specific chip observations
    into the main learning pipeline where they can be validated and promoted.

    Args:
        min_confidence: Minimum confidence to consider for merging
        limit: Max insights to process per run
        dry_run: If True, don't actually merge, just report what would happen

    Returns:
        Stats about the merge operation
    """
    state = _load_merge_state()
    merged_hashes = set(state.get("merged_hashes", []))
    now_ts = time.time()
    rejected_low_quality = _prune_rejected_state(state.get("rejected_low_quality", {}), now_ts)

    stats = {
        "processed": 0,
        "merged": 0,
        "merged_distilled": 0,
        "skipped_low_confidence": 0,
        "skipped_low_quality": 0,
        "skipped_low_quality_cooldown": 0,
        "skipped_non_learning": 0,
        "skipped_duplicate": 0,
        "duplicate_ratio": 0.0,
        "throttled_duplicate_churn": 0,
        "throttle_remaining_s": 0,
        "throttle_active": False,
        "by_chip": {},
    }
    limits = _load_merge_tuneables()
    duplicate_churn_ratio = float(limits["duplicate_churn_ratio"])
    duplicate_churn_min_processed = int(limits["duplicate_churn_min_processed"])
    duplicate_churn_cooldown_s = int(limits["duplicate_churn_cooldown_s"])
    churn_until = float(state.get("duplicate_churn_until", 0.0) or 0.0)
    if not dry_run and churn_until > now_ts:
        stats["throttled_duplicate_churn"] = 1
        stats["throttle_remaining_s"] = int(max(0.0, churn_until - now_ts))
        state["last_stats"] = stats
        _save_merge_state(state)
        return stats

    cog = get_cognitive_learner()
    chip_insights = load_chip_insights(limit=limit)
    exposures_to_record = []

    for chip_insight in chip_insights:
        stats["processed"] += 1

        chip_id = chip_insight.get("chip_id", "unknown")
        content = chip_insight.get("content", "")
        confidence = chip_insight.get("confidence", 0.5)
        captured_data = chip_insight.get("captured_data", {})

        # Skip low confidence
        if confidence < min_confidence:
            stats["skipped_low_confidence"] += 1
            continue

        quality = (captured_data.get("quality_score") or {})
        quality_total = float(quality.get("total", confidence) or confidence)
        if quality_total < min_quality_score:
            raw_hash = _hash_insight(chip_id, content)
            previous = float(rejected_low_quality.get(raw_hash, 0.0) or 0.0)
            if previous > 0 and (now_ts - previous) < LOW_QUALITY_COOLDOWN_S:
                stats["skipped_low_quality_cooldown"] += 1
            else:
                stats["skipped_low_quality"] += 1
                rejected_low_quality[raw_hash] = now_ts
            continue

        # Distill chip row into learnable statement before merge.
        learning_statement = _distill_learning_statement(
            chip_id=chip_id,
            content=content,
            captured_data=captured_data,
            min_len=int(limits.get("min_statement_len", 28)),
            observer_name=str(chip_insight.get("observer_name") or ""),
        )
        if not learning_statement:
            stats["skipped_non_learning"] += 1
            continue
        if not _is_learning_quality_ok(quality, limits):
            distilled_hash = _hash_insight(chip_id, learning_statement)
            previous = float(rejected_low_quality.get(distilled_hash, 0.0) or 0.0)
            if previous > 0 and (now_ts - previous) < LOW_QUALITY_COOLDOWN_S:
                stats["skipped_low_quality_cooldown"] += 1
            else:
                stats["skipped_low_quality"] += 1
                rejected_low_quality[distilled_hash] = now_ts
            continue
        rejected_low_quality.pop(_hash_insight(chip_id, learning_statement), None)

        insight_hash = _hash_insight(chip_id, learning_statement)
        # Skip already merged (stable hash ignores timestamp churn)
        if insight_hash in merged_hashes:
            stats["skipped_duplicate"] += 1
            continue

        rejected_low_quality.pop(_hash_insight(chip_id, content), None)
        rejected_low_quality.pop(insight_hash, None)

        # Determine category with fallback inference.
        category = _infer_category(chip_id, captured_data, learning_statement)

        # Build context from captured data
        context_parts = [f"Chip: {chip_id}"]
        if captured_data.get("file_path"):
            context_parts.append(f"File: {captured_data['file_path']}")
        if captured_data.get("tool"):
            context_parts.append(f"Tool: {captured_data['tool']}")
        if captured_data.get("change_summary"):
            context_parts.append(captured_data["change_summary"])
        try:
            context_parts.append(f"quality={quality_total:.2f}")
        except Exception:
            pass
        context = " | ".join([p for p in context_parts if str(p).strip()])

        if not dry_run:
            # Add distilled statement through unified validation.
            from lib.validate_and_store import validate_and_store_insight
            store_result = validate_and_store_insight(
                text=learning_statement,
                category=category,
                context=context,
                confidence=max(float(confidence or 0.0), float(quality_total or 0.0)),
                source=f"chip:{chip_id}:distilled",
                record_exposure=False,
                return_details=True,
            )
            if isinstance(store_result, dict):
                added = bool(store_result.get("stored"))
                stored_statement = str(store_result.get("stored_text") or learning_statement)
                key = str(store_result.get("insight_key") or "")
            else:
                # Backward-compat for test monkeypatches returning bool.
                added = bool(store_result)
                stored_statement = learning_statement
                key = ""
            if not added:
                stats["skipped_non_learning"] += 1
                continue

            # Track for exposure recording
            if not key:
                key = cog._generate_key(category, stored_statement[:40].replace(" ", "_").lower())
            exposures_to_record.append({
                "insight_key": key,
                "category": category.value,
                "text": stored_statement,
            })

            # Append distillation audit trail.
            LEARNING_DISTILLATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with LEARNING_DISTILLATIONS_FILE.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "timestamp": datetime.now().isoformat(),
                            "chip_id": chip_id,
                            "category": category.value,
                            "learning_statement": learning_statement,
                            "stored_statement": stored_statement,
                            "source_content": content[:240],
                            "quality_score": quality,
                        }
                    )
                    + "\n"
                )

            merged_hashes.add(insight_hash)

        stats["merged"] += 1
        stats["merged_distilled"] += 1
        stats["by_chip"][chip_id] = stats["by_chip"].get(chip_id, 0) + 1

    # Batch record exposures
    if exposures_to_record and not dry_run:
        try:
            from lib.exposure_tracker import infer_latest_trace_id, infer_latest_session_id
            session_id = infer_latest_session_id()
            trace_id = infer_latest_trace_id(session_id)
        except Exception:
            session_id = None
            trace_id = None
        record_exposures(source="chip_merge", items=exposures_to_record, session_id=session_id, trace_id=trace_id)

    # Save state
    if not dry_run:
        duplicate_ratio = stats["skipped_duplicate"] / max(stats["processed"], 1)
        stats["duplicate_ratio"] = round(float(duplicate_ratio), 3)
        if (
            stats["processed"] >= duplicate_churn_min_processed
            and stats["merged"] == 0
            and duplicate_ratio >= duplicate_churn_ratio
        ):
            state["duplicate_churn_until"] = now_ts + duplicate_churn_cooldown_s
            stats["throttle_active"] = True
        elif churn_until <= now_ts:
            state["duplicate_churn_until"] = 0.0
        state["merged_hashes"] = list(merged_hashes)[-1000:]  # Keep last 1000
        state["rejected_low_quality"] = _prune_rejected_state(rejected_low_quality, now_ts)
        state["last_merge"] = datetime.now().isoformat()
        state["last_stats"] = stats
        _save_merge_state(state)

    return stats


def get_merge_stats() -> Dict[str, Any]:
    """Get statistics about chip merging."""
    state = _load_merge_state()

    # Count insights per chip
    chip_counts = {}
    if CHIP_INSIGHTS_DIR.exists():
        for f in CHIP_INSIGHTS_DIR.glob("*.jsonl"):
            try:
                chip_counts[f.stem] = _count_jsonl_lines(f)
            except Exception:
                continue
    learning_distillations = _count_jsonl_lines(LEARNING_DISTILLATIONS_FILE)

    return {
        "total_merged": len(state.get("merged_hashes", [])),
        "last_merge": state.get("last_merge"),
        "last_stats": state.get("last_stats"),
        "chip_insight_counts": chip_counts,
        "learning_distillation_count": learning_distillations,
    }


def _reload_chip_merge_from(_cfg):
    """Hot-reload callback — config is read fresh each merge call."""
    pass


try:
    from .tuneables_reload import register_reload as _cm_register

    _cm_register("chip_merge", _reload_chip_merge_from, label="chip_merger.reload")
except Exception:
    pass
