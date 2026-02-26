"""
Spark Advisor: The Missing Link Between Learning and Action

This module closes the critical gap in Spark's architecture:
  Storage → Analysis → [ADVISOR] → Decision Impact

The Problem:
  - Spark captures insights beautifully (cognitive_learner, aha_tracker)
  - Spark stores them persistently (Mind sync, JSON files)
  - But insights are NEVER USED during actual task execution

The Solution:
  - Advisor queries relevant insights BEFORE actions
  - Advisor tracks whether advice was followed
  - Advisor learns which advice actually helps

KISS Principle: Single file, simple API, maximum impact.
"""

import hashlib
import json
import logging
import math
import os
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .advisory_quarantine import record_quarantine_item

# Import existing Spark components
from .cognitive_learner import get_cognitive_learner
from .distillation_transformer import transform_for_advisory as _transform_distillation
from .memory_banks import infer_project_key
from .memory_banks import retrieve as bank_retrieve
from .mind_bridge import HAS_REQUESTS, get_mind_bridge

# EIDOS integration for distillation retrieval
try:
    from .eidos import StructuralRetriever, get_retriever
    HAS_EIDOS = True
except ImportError:
    HAS_EIDOS = False
    get_retriever = None
    StructuralRetriever = None


# ============= Configuration =============
ADVISOR_DIR = Path.home() / ".spark" / "advisor"
ADVICE_LOG = ADVISOR_DIR / "advice_log.jsonl"
EFFECTIVENESS_FILE = ADVISOR_DIR / "effectiveness.json"
ADVISOR_METRICS = ADVISOR_DIR / "metrics.json"
RECENT_ADVICE_LOG = ADVISOR_DIR / "recent_advice.jsonl"
EFFECTIVENESS_SCHEMA_VERSION = 2
RECENT_ADVICE_MAX_AGE_S = 1200  # 20 min (was 15 min) - Ralph Loop tuning for better acted-on rate
RECENT_ADVICE_MAX_LINES = 200
CHIP_INSIGHTS_DIR = Path.home() / ".spark" / "chip_insights"
CHIP_ADVICE_FILE_TAIL = 40
CHIP_ADVICE_MAX_FILES = 6
CHIP_ADVICE_LIMIT = 4
CHIP_ADVICE_MIN_SCORE = 0.7
CHIP_TELEMETRY_BLOCKLIST = {"spark-core", "bench_core"}
CHIP_TELEMETRY_MARKERS = (
    "post_tool",
    "pre_tool",
    "tool_name:",
    "file_path:",
    "event_type:",
    "user_prompt_signal",
    "status: success",
    "cwd:",
)
_LOW_SIGNAL_STRUGGLE_PATTERNS = (
    re.compile(r"\bi struggle with\s+(?:tool[_\s-]*)?\d+[_\s-]*error\s+tasks\b", re.I),
    re.compile(r"\bi struggle with\s+[a-z0-9_]+_error\s+tasks\b", re.I),
    re.compile(r"\bi struggle with\s+[a-z0-9_]+\s+fails with other(?:\s+\(recovered\))?\s+tasks\b", re.I),
)
_TRANSCRIPT_ARTIFACT_PATTERNS = (
    re.compile(r"^\s*said it like this[:\s]", re.I),
    re.compile(r"^\s*another reply is[:\s]", re.I),
    re.compile(r"^\s*user wanted[:\s]", re.I),
    re.compile(r"^\s*#\s*spark\s", re.I),
)
RECENT_OUTCOMES_MAX = 5000
# Defaults — overridden by config-authority resolution in _load_advisor_config().
REPLAY_ADVISORY_ENABLED = True
REPLAY_MIN_STRICT_SAMPLES = 4
REPLAY_MIN_IMPROVEMENT_DELTA = 0.20
REPLAY_MAX_RECORDS = 3500
REPLAY_MAX_AGE_S = 21 * 86400
REPLAY_STRICT_WINDOW_S = 1200
REPLAY_MIN_CONTEXT_MATCH = 0.12
REPLAY_MODE = "replay"
GUIDANCE_STYLE = "balanced"

# Thresholds — overridden by config-authority resolution in _load_advisor_config().
MIN_RELIABILITY_FOR_ADVICE = 0.5
MIN_VALIDATIONS_FOR_STRONG_ADVICE = 2
MAX_ADVICE_ITEMS = 8
ADVICE_CACHE_TTL_SECONDS = 120
MIN_RANK_SCORE = 0.35
CATEGORY_EFFECTIVENESS_MIN_SURFACE = 6
CATEGORY_EFFECTIVENESS_DECAY_SECONDS = 14 * 24 * 3600
CATEGORY_EFFECTIVENESS_STALE_SECONDS = 180 * 24 * 3600
AUTO_TUNER_SOURCE_BOOSTS: Dict[str, float] = {}
MIND_MAX_STALE_SECONDS: float = 0.0
MIND_STALE_ALLOW_IF_EMPTY: bool = True
MIND_MIN_SALIENCE: float = 0.5
MIND_RESERVE_SLOTS: int = 1
MIND_RESERVE_MIN_RANK: float = 0.45
RETRIEVAL_ROUTE_LOG = ADVISOR_DIR / "retrieval_router.jsonl"
RETRIEVAL_ROUTE_LOG_MAX = 800

DEFAULT_RETRIEVAL_PROFILES: Dict[str, Dict[str, Any]] = {
    "1": {
        "profile": "local_free",
        "mode": "auto",  # auto | embeddings_only | hybrid_agentic
        "gate_strategy": "minimal",  # minimal | extended
        "semantic_limit": 8,
        "max_queries": 2,
        "agentic_query_limit": 2,
        "agentic_deadline_ms": 500,
        "agentic_rate_limit": 0.10,
        "agentic_rate_window": 50,
        "fast_path_budget_ms": 250,
        # Latency-tail guard: if primary semantic retrieval already exceeded budget, do not add
        # additional agentic facet queries (unless high-risk terms are present).
        "deny_escalation_when_over_budget": True,
        "prefilter_enabled": True,
        "prefilter_max_insights": 300,
        "prefilter_drop_low_signal": True,
        "lexical_weight": 0.25,
        "intent_coverage_weight": 0.0,
        "support_boost_weight": 0.0,
        "reliability_weight": 0.0,
        "semantic_context_min": 0.15,
        "semantic_lexical_min": 0.03,
        "semantic_intent_min": 0.0,
        "semantic_strong_override": 0.90,
        "bm25_k1": 1.2,
        "bm25_b": 0.75,
        "bm25_mix": 0.75,  # blend: bm25 vs overlap
        "complexity_threshold": 3,  # used only by extended gate
        "min_results_no_escalation": 3,
        "min_top_score_no_escalation": 0.68,
        "escalate_on_weak_primary": False,
        "escalate_on_high_risk": True,
        "escalate_on_trigger": False,  # ignored by minimal gate
        "domain_profile_enabled": True,
        "domain_profiles": {
            "memory": {
                "semantic_limit": 10,
                "lexical_weight": 0.32,
                "intent_coverage_weight": 0.05,
                "support_boost_weight": 0.05,
                "reliability_weight": 0.03,
                "semantic_intent_min": 0.02,
                "min_results_no_escalation": 4,
                "min_top_score_no_escalation": 0.70,
            },
            "coding": {
                "semantic_limit": 9,
                "lexical_weight": 0.30,
                "intent_coverage_weight": 0.04,
                "support_boost_weight": 0.04,
                "reliability_weight": 0.02,
                "semantic_intent_min": 0.01,
            },
        },
    },
    "2": {
        "profile": "balanced_spend",
        "mode": "auto",
        "gate_strategy": "minimal",
        "semantic_limit": 10,
        "max_queries": 3,
        "agentic_query_limit": 3,
        "agentic_deadline_ms": 700,
        "agentic_rate_limit": 0.20,
        "agentic_rate_window": 80,
        "fast_path_budget_ms": 250,
        "deny_escalation_when_over_budget": True,
        "prefilter_enabled": True,
        "prefilter_max_insights": 500,
        "prefilter_drop_low_signal": True,
        "lexical_weight": 0.30,
        "intent_coverage_weight": 0.0,
        "support_boost_weight": 0.0,
        "reliability_weight": 0.0,
        "semantic_context_min": 0.15,
        "semantic_lexical_min": 0.03,
        "semantic_intent_min": 0.0,
        "semantic_strong_override": 0.90,
        "bm25_k1": 1.2,
        "bm25_b": 0.75,
        "bm25_mix": 0.75,
        "complexity_threshold": 2,  # used only by extended gate
        "min_results_no_escalation": 4,
        "min_top_score_no_escalation": 0.72,
        "escalate_on_weak_primary": False,
        "escalate_on_high_risk": True,
        "escalate_on_trigger": False,
        "domain_profile_enabled": True,
        "domain_profiles": {
            "memory": {
                "semantic_limit": 12,
                "max_queries": 4,
                "agentic_query_limit": 4,
                "lexical_weight": 0.40,
                "intent_coverage_weight": 0.10,
                "support_boost_weight": 0.10,
                "reliability_weight": 0.05,
                "semantic_intent_min": 0.03,
                "min_results_no_escalation": 4,
                "min_top_score_no_escalation": 0.74,
            },
            "coding": {
                "semantic_limit": 11,
                "lexical_weight": 0.34,
                "intent_coverage_weight": 0.06,
                "support_boost_weight": 0.08,
                "reliability_weight": 0.04,
                "semantic_intent_min": 0.02,
            },
        },
    },
    "3": {
        "profile": "quality_max",
        "mode": "hybrid_agentic",
        "gate_strategy": "extended",
        "semantic_limit": 12,
        "max_queries": 4,
        "agentic_query_limit": 4,
        "agentic_deadline_ms": 1400,
        "agentic_rate_limit": 1.0,
        "agentic_rate_window": 80,
        "fast_path_budget_ms": 350,
        "deny_escalation_when_over_budget": False,
        "prefilter_enabled": True,
        "prefilter_max_insights": 800,
        "prefilter_drop_low_signal": True,
        "lexical_weight": 0.35,
        "intent_coverage_weight": 0.10,
        "support_boost_weight": 0.10,
        "reliability_weight": 0.10,
        "semantic_context_min": 0.12,
        "semantic_lexical_min": 0.02,
        "semantic_intent_min": 0.02,
        "semantic_strong_override": 0.88,
        "bm25_k1": 1.2,
        "bm25_b": 0.75,
        "bm25_mix": 0.75,
        "complexity_threshold": 1,
        "min_results_no_escalation": 5,
        "min_top_score_no_escalation": 0.78,
        "escalate_on_weak_primary": True,
        "escalate_on_high_risk": True,
        "escalate_on_trigger": True,
        "domain_profile_enabled": True,
        "domain_profiles": {
            "memory": {
                "semantic_limit": 14,
                "max_queries": 5,
                "agentic_query_limit": 5,
                "lexical_weight": 0.42,
                "intent_coverage_weight": 0.12,
                "support_boost_weight": 0.12,
                "reliability_weight": 0.06,
                "semantic_intent_min": 0.03,
                "min_results_no_escalation": 5,
                "min_top_score_no_escalation": 0.80,
            },
            "coding": {
                "semantic_limit": 13,
                "lexical_weight": 0.36,
                "intent_coverage_weight": 0.08,
                "support_boost_weight": 0.10,
                "reliability_weight": 0.05,
                "semantic_intent_min": 0.02,
            },
        },
    },
}

# Live routing tuneables are loaded from ~/.spark/tuneables.json -> "retrieval".
# Historically, some reports referenced "advisor.retrieval_policy.*" which is a benchmark-only
# overlay (or in-process override) and not read from tuneables.json at runtime. Keep a light
# guardrail to prevent silent misconfiguration.
_WARNED_DEPRECATED_ADVISOR_RETRIEVAL_POLICY = False

DEFAULT_COMPLEXITY_HINTS = (
    "root cause",
    "multi hop",
    "multi-hop",
    "compare",
    "timeline",
    "repeated",
    "pattern",
    "tradeoff",
    "impact",
    "synthesis",
    "across",
    "between",
)

DEFAULT_HIGH_RISK_HINTS = (
    "auth",
    "token",
    "security",
    "prod",
    "production",
    "migration",
    "rollback",
    "deploy",
    "bridge",
    "session",
    "memory retrieval",
)
X_SOCIAL_MARKERS: Tuple[str, ...] = (
    "tweet",
    "retweet",
    "reply",
    "replies",
    "thread",
    "threaded",
    "hashtag",
    "x_post",
    "x post",
    "xpost",
    "x-post",
    "x.com",
    "twitter",
    "social network",
    "social networks",
    "social feed",
    "social media",
    "engagement",
    "follower",
    "followers",
    "timeline",
)
RETRIEVAL_DOMAIN_MARKERS: Dict[str, Tuple[str, ...]] = {
    "x_social": (
        "tweet",
        "x_post",
        "x post",
        "xpost",
        "x-post",
        "retweet",
        "reply",
        "replies",
        "hashtag",
        "social",
        "engagement",
        "follower",
        "followers",
        "tweeting",
        "social media",
        "thread",
    ),
    "memory": (
        "memory",
        "retrieval",
        "distillation",
        "cross-session",
        "session",
        "stale",
        "index",
        "embedding",
        "insight",
    ),
    "coding": (
        "code",
        "coding",
        "debug",
        "refactor",
        "function",
        "module",
        "python",
        "typescript",
        "javascript",
        "compile",
        "stack trace",
        "traceback",
    ),
    "marketing": (
        "marketing",
        "campaign",
        "conversion",
        "audience",
        "brand",
        "positioning",
        "launch",
        "pricing",
        "growth",
    ),
    "strategy": (
        "strategy",
        "roadmap",
        "prioritize",
        "tradeoff",
        "go-to-market",
        "gtm",
        "moat",
        "position",
        "risk",
    ),
    "ui_design": (
        "ui",
        "ux",
        "layout",
        "visual",
        "design",
        "mobile",
        "desktop",
        "component",
        "typography",
        "color",
    ),
    "testing": (
        "test",
        "pytest",
        "unit test",
        "integration test",
        "assert",
        "coverage",
        "regression",
        "benchmark",
    ),
    "research": (
        "research",
        "compare",
        "evaluate",
        "analysis",
        "survey",
        "paper",
        "source",
        "evidence",
    ),
    "conversation": (
        "coach",
        "coaching",
        "advice",
        "self-improvement",
        "habit",
        "reflection",
        "mindset",
        "communication",
        "feedback",
    ),
    "prompting": (
        "prompt",
        "instruction",
        "system prompt",
        "few-shot",
        "token budget",
        "chain of thought",
    ),
}
RETRIEVAL_TOOL_DOMAIN_HINTS: Dict[str, str] = {
    "x_post": "x_social",
    "tweet": "x_social",
    "reply": "x_social",
    "edit": "coding",
    "bash": "coding",
    "read": "coding",
    "write": "coding",
    "multi_edit": "coding",
    "grep": "coding",
    "search_files": "coding",
    "pytest": "testing",
    "test": "testing",
}
RETRIEVAL_DOMAIN_PROFILE_KEYS = {
    "mode",
    "gate_strategy",
    "semantic_limit",
    "semantic_context_min",
    "semantic_lexical_min",
    "semantic_strong_override",
    "max_queries",
    "agentic_query_limit",
    "agentic_deadline_ms",
    "agentic_rate_limit",
    "agentic_rate_window",
    "fast_path_budget_ms",
    "deny_escalation_when_over_budget",
    "prefilter_enabled",
    "prefilter_max_insights",
    "prefilter_drop_low_signal",
    "lexical_weight",
    "intent_coverage_weight",
    "support_boost_weight",
    "reliability_weight",
    "bm25_k1",
    "bm25_b",
    "bm25_mix",
    "semantic_intent_min",
    "complexity_threshold",
    "min_results_no_escalation",
    "min_top_score_no_escalation",
    "escalate_on_weak_primary",
    "escalate_on_high_risk",
    "escalate_on_trigger",
}
_INTENT_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "so",
    "that",
    "the",
    "then",
    "to",
    "we",
    "with",
}
_METADATA_TELEMETRY_HINTS = (
    "event_type",
    "tool_name",
    "file_path",
    "status:",
    "user_prompt_signal",
    "source: spark_advisory",
)
MEMORY_EMOTION_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "advisory_rerank_weight": 0.15,
    "advisory_min_state_similarity": 0.30,
}


def _parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _coerce_advisory_category_value(raw: Any, *, fallback: str = "general") -> str:
    category = str(raw or "").strip().lower()
    if not category or category == "none":
        category = str(fallback or "general").strip().lower() or "general"
    if category.startswith("eidos"):
        category = category.replace(":", "_")
    return category[:64]


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _clamp_01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _norm_retrieval_domain(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "general"
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return "general"
    aliases = {
        "ui": "ui_design",
        "ux": "ui_design",
        "social": "x_social",
        "xsocial": "x_social",
        "x_social": "x_social",
    }
    return aliases.get(text, text)


def _parse_iso_ts(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return float(datetime.fromisoformat(text).timestamp())
    except Exception:
        return None


def _chips_disabled() -> bool:
    return not _chips_enabled()


def _chips_enabled() -> bool:
    """Check if chip insights are enabled.

    Advisor uses default-ON semantics for local OSS dev (empty env = enabled).
    This differs from bridge_cycle/chips which use default-OFF via feature_flags.
    Reads env directly since this is called per-request and must reflect current state.
    """
    if str(os.environ.get("SPARK_ADVISORY_DISABLE_CHIPS", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return False
    chips_raw = str(os.environ.get("SPARK_CHIPS_ENABLED", "")).strip().lower()
    premium_raw = str(os.environ.get("SPARK_PREMIUM_TOOLS", "")).strip().lower()
    truthy = {"1", "true", "yes", "on"}
    chips_switch = True if not chips_raw else chips_raw in truthy
    premium_switch = True if not premium_raw else premium_raw in truthy
    return chips_switch and premium_switch


def _premium_tools_enabled() -> bool:
    """Check if premium tools are enabled. Reads env directly per-request."""
    return str(os.environ.get("SPARK_PREMIUM_TOOLS", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }


def _load_advisor_config() -> None:
    """Load advisor tuneables from ~/.spark/tuneables.json → "advisor" section.

    Overrides module-level constants so all existing code picks up the values
    without any other changes.  Called once at module load.
    """
    global MIN_RELIABILITY_FOR_ADVICE, MIN_VALIDATIONS_FOR_STRONG_ADVICE
    global MAX_ADVICE_ITEMS, ADVICE_CACHE_TTL_SECONDS, MIN_RANK_SCORE
    global AUTO_TUNER_SOURCE_BOOSTS
    global MIND_MAX_STALE_SECONDS, MIND_STALE_ALLOW_IF_EMPTY, MIND_MIN_SALIENCE
    global MIND_RESERVE_SLOTS, MIND_RESERVE_MIN_RANK
    global REPLAY_ADVISORY_ENABLED, REPLAY_MIN_STRICT_SAMPLES, REPLAY_MIN_IMPROVEMENT_DELTA
    global REPLAY_MAX_RECORDS, REPLAY_MAX_AGE_S, REPLAY_STRICT_WINDOW_S, REPLAY_MIN_CONTEXT_MATCH
    global REPLAY_MODE, GUIDANCE_STYLE
    AUTO_TUNER_SOURCE_BOOSTS = {}
    try:
        # Tests should be deterministic and not depend on user-local ~/.spark state.
        # However, some unit tests *do* validate this loader by monkeypatching Path.home().
        # So we only skip when running under pytest AND Path.home() still points at the
        # real user profile directory (not a monkeypatched temp dir).
        if "pytest" in sys.modules and str(os.environ.get("SPARK_TEST_ALLOW_HOME_TUNEABLES", "")).strip().lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            try:
                real_home = Path(os.path.expanduser("~")).resolve()
                current_home = Path.home().resolve()
                if current_home == real_home:
                    return
            except Exception:
                return
        from .config_authority import env_bool, env_float, env_int, resolve_section
        tuneables = Path.home() / ".spark" / "tuneables.json"
        if not tuneables.exists():
            return
        cfg = resolve_section(
            "advisor",
            runtime_path=tuneables,
            env_overrides={
                "replay_enabled": env_bool("SPARK_ADVISORY_REPLAY_ENABLED"),
                "replay_min_strict": env_int("SPARK_ADVISORY_REPLAY_MIN_STRICT"),
                "replay_min_delta": env_float("SPARK_ADVISORY_REPLAY_MIN_DELTA"),
                "replay_max_records": env_int("SPARK_ADVISORY_REPLAY_MAX_RECORDS"),
                "replay_max_age_s": env_int("SPARK_ADVISORY_REPLAY_MAX_AGE_S"),
                "replay_strict_window_s": env_int("SPARK_ADVISORY_REPLAY_STRICT_WINDOW_S"),
                "replay_min_context": env_float("SPARK_ADVISORY_REPLAY_MIN_CONTEXT"),
                "mind_max_stale_s": env_float("SPARK_ADVISOR_MIND_MAX_STALE_S"),
                "mind_stale_allow_if_empty": env_bool("SPARK_ADVISOR_MIND_STALE_ALLOW_IF_EMPTY"),
                "mind_min_salience": env_float("SPARK_ADVISOR_MIND_MIN_SALIENCE"),
                "mind_reserve_slots": env_int("SPARK_ADVISOR_MIND_RESERVE_SLOTS"),
                "mind_reserve_min_rank": env_float("SPARK_ADVISOR_MIND_RESERVE_MIN_RANK"),
            },
        ).data
        if not isinstance(cfg, dict):
            cfg = {}
        auto_cfg = resolve_section("auto_tuner", runtime_path=tuneables).data
        if isinstance(auto_cfg, dict):
            raw_boosts = auto_cfg.get("source_boosts")
            if isinstance(raw_boosts, dict):
                parsed: Dict[str, float] = {}
                for raw_source, raw_boost in raw_boosts.items():
                    source = str(raw_source or "").strip().lower()
                    if not source:
                        continue
                    try:
                        boost = float(raw_boost)
                    except Exception:
                        continue
                    if not math.isfinite(boost):
                        continue
                    parsed[source] = max(0.0, min(2.0, boost))
                AUTO_TUNER_SOURCE_BOOSTS = parsed
        # Fall back to top-level "values" for advice_cache_ttl (backward compat)
        values_cfg = resolve_section("values", runtime_path=tuneables).data
        if isinstance(values_cfg, dict) and "advice_cache_ttl" in values_cfg and "cache_ttl" not in cfg:
            cfg["cache_ttl"] = values_cfg["advice_cache_ttl"]
        if "min_reliability" in cfg:
            MIN_RELIABILITY_FOR_ADVICE = float(cfg["min_reliability"])
        if "min_validations_strong" in cfg:
            MIN_VALIDATIONS_FOR_STRONG_ADVICE = int(cfg["min_validations_strong"])
        if "max_items" in cfg:
            MAX_ADVICE_ITEMS = int(cfg["max_items"])
        if "cache_ttl" in cfg:
            ADVICE_CACHE_TTL_SECONDS = int(cfg["cache_ttl"])
        if "min_rank_score" in cfg:
            MIN_RANK_SCORE = float(cfg["min_rank_score"])
        if "mind_max_stale_s" in cfg:
            MIND_MAX_STALE_SECONDS = max(0.0, float(cfg["mind_max_stale_s"] or 0.0))
        if "mind_stale_allow_if_empty" in cfg:
            MIND_STALE_ALLOW_IF_EMPTY = _parse_bool(
                cfg.get("mind_stale_allow_if_empty"),
                MIND_STALE_ALLOW_IF_EMPTY,
            )
        if "mind_min_salience" in cfg:
            MIND_MIN_SALIENCE = max(0.0, min(1.0, float(cfg["mind_min_salience"])))
        if "mind_reserve_slots" in cfg:
            MIND_RESERVE_SLOTS = max(0, min(4, int(cfg.get("mind_reserve_slots") or 0)))
        if "mind_reserve_min_rank" in cfg:
            MIND_RESERVE_MIN_RANK = max(0.0, min(1.0, float(cfg.get("mind_reserve_min_rank") or 0.0)))

        if "replay_mode" in cfg:
            mode = str(cfg.get("replay_mode") or "").strip().lower()
            if mode in {"off", "standard", "replay"}:
                REPLAY_MODE = mode
                REPLAY_ADVISORY_ENABLED = mode != "off"
        if "guidance_style" in cfg:
            style = str(cfg.get("guidance_style") or "").strip().lower()
            if style in {"concise", "balanced", "coach"}:
                GUIDANCE_STYLE = style
        if "replay_enabled" in cfg:
            REPLAY_ADVISORY_ENABLED = _parse_bool(
                cfg.get("replay_enabled"),
                REPLAY_ADVISORY_ENABLED,
            )
            if not REPLAY_ADVISORY_ENABLED:
                REPLAY_MODE = "off"
            elif REPLAY_MODE == "off":
                REPLAY_MODE = "replay"
        if "replay_min_strict" in cfg:
            REPLAY_MIN_STRICT_SAMPLES = max(1, int(cfg.get("replay_min_strict") or 1))
        if "replay_min_delta" in cfg:
            REPLAY_MIN_IMPROVEMENT_DELTA = max(
                0.0, min(0.95, float(cfg.get("replay_min_delta") or 0.0))
            )
        if "replay_max_records" in cfg:
            REPLAY_MAX_RECORDS = max(200, int(cfg.get("replay_max_records") or 200))
        if "replay_max_age_s" in cfg:
            REPLAY_MAX_AGE_S = max(3600, int(cfg.get("replay_max_age_s") or 3600))
        if "replay_strict_window_s" in cfg:
            REPLAY_STRICT_WINDOW_S = max(60, int(cfg.get("replay_strict_window_s") or 60))
        if "replay_min_context" in cfg:
            REPLAY_MIN_CONTEXT_MATCH = max(
                0.0, min(1.0, float(cfg.get("replay_min_context") or 0.0))
            )
    except Exception:
        pass  # Fail silently — keep hard-coded defaults


_load_advisor_config()


def _compose_source_quality_with_boosts(base_quality: Dict[str, float]) -> Dict[str, float]:
    merged: Dict[str, float] = {}
    for source, raw_value in dict(base_quality or {}).items():
        try:
            value = float(raw_value)
        except Exception:
            continue
        if not math.isfinite(value):
            continue
        merged[str(source)] = max(0.0, min(2.0, value))

    for source, raw_boost in dict(AUTO_TUNER_SOURCE_BOOSTS or {}).items():
        normalized = str(source or "").strip().lower()
        if not normalized:
            continue
        try:
            boost = float(raw_boost)
        except Exception:
            continue
        if not math.isfinite(boost):
            continue
        base = float(merged.get(normalized, 0.50))
        merged[normalized] = max(0.0, min(2.0, base * max(0.0, min(2.0, boost))))
    return merged


def _refresh_live_advisor_source_boosts() -> None:
    instance = globals().get("_advisor")
    if instance is None:
        return
    try:
        base_quality = getattr(instance, "_SOURCE_QUALITY", {}) or {}
        instance._SOURCE_BOOST = _compose_source_quality_with_boosts(base_quality)
    except Exception:
        pass


def _reload_advisor_from(cfg: Dict[str, Any]) -> None:
    """Hot-reload advisor tuneables from coordinator-supplied dict.

    Ignores the cfg dict and re-reads from file, because _load_advisor_config
    reads multiple sections (advisor, advisory_preferences, retrieval).
    """
    _load_advisor_config()
    _refresh_live_advisor_source_boosts()


try:
    from lib.tuneables_reload import register_reload as _advisor_register
    _advisor_register("advisor", _reload_advisor_from, label="advisor.reload_from")
    _advisor_register("auto_tuner", _reload_advisor_from, label="advisor.reload_from.auto_tuner")
except ImportError:
    pass


def reload_advisor_config() -> Dict[str, Any]:
    """Reload advisor tuneables and return the effective replay/user preference subset."""
    _load_advisor_config()
    _refresh_live_advisor_source_boosts()
    return {
        "replay_mode": REPLAY_MODE,
        "guidance_style": GUIDANCE_STYLE,
        "replay_enabled": bool(REPLAY_ADVISORY_ENABLED),
        "replay_min_strict": int(REPLAY_MIN_STRICT_SAMPLES),
        "replay_min_delta": float(REPLAY_MIN_IMPROVEMENT_DELTA),
        "replay_max_records": int(REPLAY_MAX_RECORDS),
        "replay_max_age_s": int(REPLAY_MAX_AGE_S),
        "replay_strict_window_s": int(REPLAY_STRICT_WINDOW_S),
        "replay_min_context": float(REPLAY_MIN_CONTEXT_MATCH),
        "max_items": int(MAX_ADVICE_ITEMS),
        "min_rank_score": float(MIN_RANK_SCORE),
        "source_boosts": dict(AUTO_TUNER_SOURCE_BOOSTS),
    }


def _maybe_warn_deprecated_advisor_retrieval_policy(
    advisor_policy: Optional[Dict[str, Any]],
    retrieval_keys_present: Optional[set],
    effective_policy: Dict[str, Any],
) -> None:
    """Warn if user sets advisor.retrieval_policy.* in tuneables.json expecting it to apply."""
    global _WARNED_DEPRECATED_ADVISOR_RETRIEVAL_POLICY
    if _WARNED_DEPRECATED_ADVISOR_RETRIEVAL_POLICY:
        return
    if not isinstance(advisor_policy, dict):
        return

    keys = (
        "semantic_context_min",
        "semantic_lexical_min",
        "semantic_intent_min",
        "semantic_strong_override",
        "lexical_weight",
        "intent_coverage_weight",
        "support_boost_weight",
        "reliability_weight",
    )
    present = [k for k in keys if k in advisor_policy]
    if not present:
        return

    retrieval_keys_present = retrieval_keys_present if isinstance(retrieval_keys_present, set) else set()
    has_all_in_retrieval = all(k in retrieval_keys_present for k in present)

    mismatches: List[str] = []
    for k in present:
        try:
            want = float(advisor_policy.get(k))
            got = float(effective_policy.get(k))
        except Exception:
            continue
        if abs(want - got) > 1e-12:
            mismatches.append(f"{k}={want} (effective={got})")

    # If tuneables.json already sets retrieval.* for these keys and values match, avoid noisy warnings.
    if has_all_in_retrieval and not mismatches:
        return

    _WARNED_DEPRECATED_ADVISOR_RETRIEVAL_POLICY = True
    details = "; ".join(mismatches) if mismatches else ", ".join(present)
    sys.stderr.write(
        "[SPARK][warn] 'advisor.retrieval_policy.*' in ~/.spark/tuneables.json is ignored by runtime. "
        "Routing is loaded from the 'retrieval' section (prefer 'retrieval.overrides.*'). "
        f"Detected: {details}\n"
    )


def _tail_jsonl(path: Path, count: int) -> List[str]:
    """Tail-read JSONL lines without loading entire file in memory."""
    if count <= 0 or not path.exists():
        return []
    chunk_size = 64 * 1024
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            buffer = b""
            lines: List[bytes] = []
            while pos > 0 and len(lines) <= count:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                data = f.read(read_size)
                buffer = data + buffer
                if b"\n" in buffer:
                    parts = buffer.split(b"\n")
                    buffer = parts[0]
                    lines = parts[1:] + lines
            if buffer:
                lines = [buffer] + lines
        out = [
            ln.decode("utf-8", errors="replace").rstrip("\r")
            for ln in lines
            if ln != b""
        ]
        return out[-count:]
    except Exception:
        return []


# Avoid doing a read+rewrite of the entire bounded file on every append.
# We compact at most once per TTL per path.
_COMPACT_TTL_S = 30.0
_LAST_COMPACT_TS: Dict[str, float] = {}
_COMPACT_LOCK = threading.Lock()

_advisor_log = logging.getLogger("spark.advisor")


def _append_jsonl_capped(path: Path, entry: Dict[str, Any], max_lines: int) -> None:
    """Append JSONL entry and keep file bounded.

    Optimized for the hot path:
    - Always append-only
    - Only compact (rewrite to last N lines) when needed AND rate-limited
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        if max_lines <= 0:
            return

        now = time.time()
        key = str(path)
        with _COMPACT_LOCK:
            last = float(_LAST_COMPACT_TS.get(key, 0.0) or 0.0)
            if (now - last) < _COMPACT_TTL_S:
                return

            # Only compact when we likely exceeded the cap.
            probe = _tail_jsonl(path, max_lines + 1)
            if len(probe) <= max_lines:
                _LAST_COMPACT_TS[key] = now
                return

            # Rewrite to the last max_lines.
            path.write_text("\n".join(probe[-max_lines:]) + "\n", encoding="utf-8")
            _LAST_COMPACT_TS[key] = now
    except Exception as e:
        _advisor_log.debug("JSONL append/compact failed for %s: %s", path, e)


def record_recent_delivery(
    *,
    tool: str,
    advice_list: List["Advice"],
    trace_id: Optional[str] = None,
    route: str = "",
    delivered: bool = True,
    categories: Optional[List[str]] = None,
    advisory_readiness: Optional[List[float]] = None,
    advisory_quality: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Record advice that was actually surfaced to the agent.

    This is intentionally separate from retrieval logging: advisory_engine may retrieve
    many candidates but only emit a small subset; recent_advice should reflect delivery.
    """
    if not tool or not advice_list:
        return
    advice_ids = [a.advice_id for a in advice_list]
    run_seed = f"{tool}|{str(trace_id or '').strip()}|{','.join(sorted(str(x) for x in advice_ids if str(x).strip()))}"
    run_id = hashlib.sha1(run_seed.encode("utf-8", errors="ignore")).hexdigest()[:20]
    advisory_readiness = advisory_readiness or []
    advisory_quality = advisory_quality or []
    categories = categories or []
    cat_items = [_coerce_advisory_category_value(c, fallback="general") for c in categories] if categories else []
    if not cat_items:
        cat_items = ["general"] * len(advice_ids)
    if len(cat_items) < len(advice_ids):
        cat_items.extend(["general"] * (len(advice_ids) - len(cat_items)))
    if len(cat_items) > len(advice_ids):
        cat_items = cat_items[: len(advice_ids)]
    advisory_readiness = [float(r) if r is not None else 0.0 for r in advisory_readiness]
    if len(advisory_readiness) < len(advice_ids):
        advisory_readiness.extend([0.0] * (len(advice_ids) - len(advisory_readiness)))
    if len(advisory_readiness) > len(advice_ids):
        advisory_readiness = advisory_readiness[: len(advice_ids)]
    advisory_quality = [q if isinstance(q, dict) else {} for q in advisory_quality]
    if len(advisory_quality) < len(advice_ids):
        advisory_quality.extend([{}] * (len(advice_ids) - len(advisory_quality)))
    if len(advisory_quality) > len(advice_ids):
        advisory_quality = advisory_quality[: len(advice_ids)]
    category_summary: Dict[str, Dict[str, Any]] = {}
    for idx, (cat, readiness) in enumerate(zip(cat_items, advisory_readiness)):
        cat_key = str(cat or "general").strip().lower() or "general"
        c_sum = category_summary.setdefault(
            cat_key,
            {
                "count": 0,
                "readiness_sum": 0.0,
                "readiness_max": 0.0,
                "readiness_min": 1.0,
                "quality_sum": 0.0,
                "quality_count": 0,
            },
        )
        c_sum["count"] += 1
        c_sum["readiness_sum"] += float(readiness or 0.0)
        c_sum["readiness_max"] = max(c_sum["readiness_max"], float(readiness or 0.0))
        c_sum["readiness_min"] = min(c_sum["readiness_min"], float(readiness or 0.0))
        quality = advisory_quality[idx] if idx < len(advisory_quality) else {}
        quality_score = float(quality.get("unified_score", 0.0) or 0.0) if isinstance(quality, dict) else 0.0
        quality_score = max(0.0, min(1.0, quality_score))
        c_sum["quality_sum"] += quality_score
        c_sum["quality_count"] += 1

    now = time.time()
    recent = {
        "ts": time.time(),
        "tool": tool,
        "trace_id": trace_id,
        "run_id": run_id,
        "advice_ids": advice_ids,
        "advice_texts": [a.text[:160] for a in advice_list],
        "insight_keys": [a.insight_key for a in advice_list],
        "sources": [a.source for a in advice_list],
        "categories": [str(c).strip().lower() for c in cat_items],
        "advisory_readiness": [round(max(0.0, min(1.0, float(r))), 4) for r in advisory_readiness],
        "advisory_quality": [
            {
                "unified_score": round(max(0.0, min(1.0, float(q.get("unified_score", 0.0) or 0.0))), 4),
                "domain": str(q.get("domain", "general") or "general").strip().lower(),
            }
            for q in advisory_quality
        ],
        "delivered": bool(delivered),
        "route": str(route or ""),
        "category_summary": category_summary,
        "recorded_at": now,
    }
    # Keep this bounded but roomy enough for short windows + debugging.
    _append_jsonl_capped(RECENT_ADVICE_LOG, recent, max_lines=max(500, RECENT_ADVICE_MAX_LINES * 10))


# ============= Data Classes =============
@dataclass
class Advice:
    """A piece of advice derived from learnings."""
    advice_id: str
    insight_key: str
    text: str
    confidence: float
    source: str  # "cognitive", "mind", "pattern", "surprise"
    context_match: float  # How well it matches current context
    reason: str = ""  # Task #13: WHY this advice matters (evidence/context)
    category: str = "general"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    # Emotional priority metadata from pipeline distillation (0.0-1.0).
    # Bridges emotional salience into final ranking without dominating it.
    emotional_priority: float = 0.0
    # Embedded advisory quality dimensions from distillation_transformer.
    # When present, used directly by _rank_score() instead of re-computing.
    advisory_quality: Dict[str, Any] = field(default_factory=dict)
    advisory_readiness: float = 0.0


@dataclass
class AdviceOutcome:
    """Tracks whether advice was followed and if it helped."""
    advice_id: str
    was_followed: bool
    was_helpful: Optional[bool] = None
    outcome_notes: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ============= Core Advisor =============
class SparkAdvisor:
    """
    The advisor that makes learnings actionable.

    Usage:
        advisor = get_advisor()

        # Before action: get relevant advice
        advice = advisor.advise("Edit", {"file": "main.py"}, "fixing bug")

        # After action: report outcome
        advisor.report_outcome(advice.advice_id, followed=True, helpful=True)
    """

    def __init__(self):
        ADVISOR_DIR.mkdir(parents=True, exist_ok=True)
        self.cognitive = get_cognitive_learner()
        self.mind = get_mind_bridge()
        self.effectiveness = self._load_effectiveness()
        self._cache: Dict[str, Tuple[List[Advice], float]] = {}
        self.retrieval_policy = self._load_retrieval_policy()
        self._agentic_route_history: List[bool] = []
        self._memory_emotion_cfg_cache: Dict[str, Any] = dict(MEMORY_EMOTION_DEFAULTS)
        self._memory_emotion_cfg_mtime: Optional[float] = None
        self._last_minimax_rerank_ts: float = 0.0
        # Legacy benchmark/profile tooling mutates this map directly.
        self._SOURCE_BOOST: Dict[str, float] = _compose_source_quality_with_boosts(self._SOURCE_QUALITY)

        # Prefilter cache: avoid per-query regex tokenization across large insight sets.
        # key -> (blob_hash, token_set, blob_lower)
        self._prefilter_cache: Dict[str, Tuple[str, set, str]] = {}

        # Preload cross-encoder model in background thread so first advise()
        # call doesn't block for 10+ seconds waiting for model load.
        try:
            from .cross_encoder_reranker import preload_reranker
            preload_reranker()
        except Exception:
            pass  # Cross-encoder is optional

    @staticmethod
    def _coerce_category_bucket(raw: Any) -> Dict[str, Any]:
        """Normalize per-category effectiveness bucket into a stable schema."""
        def _as_int(value: Any, default: int = 0) -> int:
            try:
                return max(0, int(value))
            except Exception:
                return default

        def _as_float(value: Any, default: float = 0.0) -> float:
            try:
                return float(value)
            except Exception:
                return default

        bucket = {
            "surfaced": 0,
            "total": 0,
            "helpful": 0,
            "readiness_sum": 0.0,
            "readiness_count": 0,
            "quality_sum": 0.0,
            "quality_count": 0,
            "last_ts": 0.0,
        }

        if isinstance(raw, dict):
            bucket["surfaced"] = _as_int(raw.get("surfaced", raw.get("offered", 0)))
            bucket["total"] = _as_int(raw.get("total", 0))
            bucket["helpful"] = _as_int(raw.get("helpful", 0))
            bucket["readiness_sum"] = _as_float(raw.get("readiness_sum", 0.0))
            bucket["readiness_count"] = _as_int(raw.get("readiness_count", 0))
            bucket["quality_sum"] = _as_float(raw.get("quality_sum", 0.0))
            bucket["quality_count"] = _as_int(raw.get("quality_count", 0))
            bucket["last_ts"] = _as_float(raw.get("last_ts", 0.0))
        elif isinstance(raw, (int, float)):
            # Preserve compatibility with legacy serialized formats.
            bucket["surfaced"] = _as_int(raw, 0)

        # Keep invariants.
        bucket["helpful"] = min(bucket["helpful"], bucket["total"])
        bucket["readiness_sum"] = max(0.0, bucket["readiness_sum"])
        bucket["quality_sum"] = max(0.0, bucket["quality_sum"])
        bucket["readiness_count"] = max(0, bucket["readiness_count"])
        bucket["quality_count"] = max(0, bucket["quality_count"])
        return bucket

    def _decayed_category_bucket(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Decay stale category counters to avoid over-weighting stale historical signal."""
        bucket = dict(self._coerce_category_bucket(row))
        last_ts = float(bucket.get("last_ts", 0.0) or 0.0)
        if last_ts <= 0:
            if bucket["surfaced"] > 0:
                # Legacy rows without timestamps should remain usable while aging starts now.
                bucket["last_ts"] = time.time()
            return bucket

        age = max(0.0, time.time() - last_ts)
        stale_window = max(1.0, float(CATEGORY_EFFECTIVENESS_STALE_SECONDS))
        if age >= stale_window:
            return {
                "surfaced": 0,
                "total": 0,
                "helpful": 0,
                "readiness_sum": 0.0,
                "readiness_count": 0,
                "quality_sum": 0.0,
                "quality_count": 0,
                "last_ts": bucket.get("last_ts", 0.0),
            }

        decay = 0.5 ** (age / max(1.0, float(CATEGORY_EFFECTIVENESS_DECAY_SECONDS)))
        if decay >= 0.999:
            return bucket

        def _decay_count(value: float) -> int:
            return int(round(float(value) * decay))

        bucket["surfaced"] = max(0, _decay_count(bucket["surfaced"]))
        bucket["total"] = max(0, _decay_count(bucket["total"]))
        bucket["helpful"] = max(0, _decay_count(bucket["helpful"]))
        bucket["readiness_sum"] = float(bucket["readiness_sum"]) * decay
        bucket["readiness_count"] = max(0, _decay_count(bucket["readiness_count"]))
        bucket["quality_sum"] = float(bucket["quality_sum"]) * decay
        bucket["quality_count"] = max(0, _decay_count(bucket["quality_count"]))
        bucket["helpful"] = min(bucket["helpful"], bucket["total"])
        bucket["readiness_sum"] = max(0.0, bucket["readiness_sum"])
        bucket["quality_sum"] = max(0.0, bucket["quality_sum"])
        return bucket

    def _load_effectiveness(self) -> Dict[str, Any]:
        """Load effectiveness tracking data."""
        if EFFECTIVENESS_FILE.exists():
            try:
                data = json.loads(EFFECTIVENESS_FILE.read_text(encoding="utf-8"))
                return self._normalize_effectiveness(data)
            except Exception:
                pass
        return self._normalize_effectiveness({
            "total_advice_given": 0,
            "total_followed": 0,
            "total_helpful": 0,
            "by_source": {},
            "by_category": {},
            "recent_outcomes": {},
            "schema_version": EFFECTIVENESS_SCHEMA_VERSION,
        })

    def _normalize_effectiveness(self, data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Normalize and enforce invariants for effectiveness counters."""
        src = data if isinstance(data, dict) else {}
        schema_version = int(src.get("schema_version", 1) or 1)

        def _as_int(value: Any) -> int:
            try:
                return max(0, int(value))
            except Exception:
                return 0

        total_advice_given = _as_int(src.get("total_advice_given", 0))
        total_followed = _as_int(src.get("total_followed", 0))
        total_helpful = _as_int(src.get("total_helpful", 0))

        # Invariants: helpful <= followed <= advice_given.
        total_followed = min(total_followed, total_advice_given)
        total_helpful = min(total_helpful, total_followed)

        by_source: Dict[str, Dict[str, int]] = {}
        for key, row in (src.get("by_source") or {}).items():
            if not isinstance(row, dict):
                continue
            total = _as_int(row.get("total", 0))
            helpful = min(_as_int(row.get("helpful", 0)), total)
            by_source[str(key)] = {"total": total, "helpful": helpful}

        by_category = {}
        now = time.time()
        raw_by_category = src.get("by_category")
        if isinstance(raw_by_category, dict):
            for cat, row in raw_by_category.items():
                category = str(cat or "").strip().lower()
                if not category:
                    continue
                bucket = self._coerce_category_bucket(row)
                if schema_version < EFFECTIVENESS_SCHEMA_VERSION and bucket["last_ts"] <= 0 and bucket["surfaced"] > 0:
                    bucket["last_ts"] = now
                by_category[category] = self._decayed_category_bucket(bucket)

        recent_outcomes: Dict[str, Dict[str, Any]] = {}
        raw_recent = src.get("recent_outcomes") or {}
        if isinstance(raw_recent, dict):
            for advice_id, row in raw_recent.items():
                if not advice_id or not isinstance(row, dict):
                    continue
                ts_raw = row.get("ts")
                try:
                    ts = float(ts_raw)
                except Exception:
                    ts = 0.0
                recent_outcomes[str(advice_id)] = {
                    "followed_counted": bool(row.get("followed_counted")),
                    "helpful_counted": bool(row.get("helpful_counted")),
                    "ts": ts,
                }

        # Keep recent outcomes bounded by recency.
        if len(recent_outcomes) > RECENT_OUTCOMES_MAX:
            keep = sorted(
                recent_outcomes.items(),
                key=lambda item: float(item[1].get("ts", 0.0)),
                reverse=True,
            )[:RECENT_OUTCOMES_MAX]
            recent_outcomes = dict(keep)

        return {
            "total_advice_given": total_advice_given,
            "total_followed": total_followed,
            "total_helpful": total_helpful,
            "by_source": by_source,
            "by_category": by_category,
            "recent_outcomes": recent_outcomes,
            "schema_version": EFFECTIVENESS_SCHEMA_VERSION,
            "schema_last_migrated_at": now,
        }

    def _load_metrics(self) -> Dict[str, Any]:
        if ADVISOR_METRICS.exists():
            try:
                return json.loads(ADVISOR_METRICS.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "total_retrievals": 0,
            "cognitive_retrievals": 0,
            "cognitive_surface_rate": 0.0,
            "cognitive_helpful_known": 0,
            "cognitive_helpful_true": 0,
            "cognitive_helpful_rate": None,
        }

    def _save_metrics(self, metrics: Dict[str, Any]) -> None:
        try:
            ADVISOR_METRICS.parent.mkdir(parents=True, exist_ok=True)
            ADVISOR_METRICS.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _record_cognitive_surface(self, advice_list: List["Advice"]) -> None:
        try:
            metrics = self._load_metrics()
            total = int(metrics.get("total_retrievals", 0)) + 1
            cognitive_sources = {
                "cognitive",
                "semantic",
                "semantic-hybrid",
                "semantic-agentic",
                "trigger",
                "chip",
            }
            has_cognitive = any(a.source in cognitive_sources for a in advice_list)
            cognitive = int(metrics.get("cognitive_retrievals", 0)) + (1 if has_cognitive else 0)
            metrics["total_retrievals"] = total
            metrics["cognitive_retrievals"] = cognitive
            metrics["cognitive_surface_rate"] = round(cognitive / max(total, 1), 4)
            metrics["last_updated"] = datetime.now().isoformat()
            self._save_metrics(metrics)
        except Exception:
            pass

    def _record_cognitive_helpful(self, advice_id: str, was_helpful: Optional[bool]) -> None:
        if was_helpful is None:
            return
        try:
            entry = self._find_recent_advice_by_id(advice_id)
            if not entry:
                return
            advice_ids = entry.get("advice_ids") or []
            sources = entry.get("sources") or []
            idx = advice_ids.index(advice_id) if advice_id in advice_ids else -1
            source = sources[idx] if 0 <= idx < len(sources) else None
            if source not in {"cognitive", "semantic", "semantic-hybrid", "semantic-agentic", "trigger"}:
                return

            metrics = self._load_metrics()
            metrics["cognitive_helpful_known"] = int(metrics.get("cognitive_helpful_known", 0)) + 1
            if was_helpful is True:
                metrics["cognitive_helpful_true"] = int(metrics.get("cognitive_helpful_true", 0)) + 1
            known = max(1, int(metrics.get("cognitive_helpful_known", 0)))
            metrics["cognitive_helpful_rate"] = round(
                int(metrics.get("cognitive_helpful_true", 0)) / known, 4
            )
            metrics["last_updated"] = datetime.now().isoformat()
            self._save_metrics(metrics)
        except Exception:
            pass

    def _save_effectiveness(self):
        """Save effectiveness data with atomic write to prevent race conditions.

        Uses read-modify-write pattern:
        1. Read current disk state
        2. Merge with in-memory deltas
        3. Write atomically via temp file
        """
        import os
        import tempfile

        try:
            # Read current disk state to merge (handles multiple processes)
            disk_data = self._load_effectiveness()
            mem_data = self._normalize_effectiveness(self.effectiveness)

            # Merge: take max of counters (monotonically increasing)
            merged = {
                "schema_version": EFFECTIVENESS_SCHEMA_VERSION,
                "schema_last_migrated_at": time.time(),
                "total_advice_given": max(
                    disk_data.get("total_advice_given", 0),
                    mem_data.get("total_advice_given", 0)
                ),
                "total_followed": max(
                    disk_data.get("total_followed", 0),
                    mem_data.get("total_followed", 0)
                ),
                "total_helpful": max(
                    disk_data.get("total_helpful", 0),
                    mem_data.get("total_helpful", 0)
                ),
                "by_source": {},
                "by_category": {},
                "recent_outcomes": {},
            }

            # Merge by_source
            for src in set(list(disk_data.get("by_source", {}).keys()) +
                          list(mem_data.get("by_source", {}).keys())):
                disk_src = disk_data.get("by_source", {}).get(src, {})
                mem_src = mem_data.get("by_source", {}).get(src, {})
                merged["by_source"][src] = {
                    "total": max(disk_src.get("total", 0), mem_src.get("total", 0)),
                    "helpful": max(disk_src.get("helpful", 0), mem_src.get("helpful", 0)),
                }

            # Merge per-category buckets conservatively (monotonic-safe fields).
            merged["by_category"] = {}
            disk_cat = disk_data.get("by_category") or {}
            mem_cat = mem_data.get("by_category") or {}
            for cat in set(list(disk_cat.keys()) + list(mem_cat.keys())):
                disk_bucket = self._coerce_category_bucket(disk_cat.get(cat, {}))
                mem_bucket = self._coerce_category_bucket(mem_cat.get(cat, {}))
                merged["by_category"][str(cat)] = {
                    "surfaced": max(disk_bucket["surfaced"], mem_bucket["surfaced"]),
                    "total": max(disk_bucket["total"], mem_bucket["total"]),
                    "helpful": max(disk_bucket["helpful"], mem_bucket["helpful"]),
                    "readiness_sum": max(
                        disk_bucket["readiness_sum"],
                        mem_bucket["readiness_sum"],
                    ),
                    "readiness_count": max(
                        disk_bucket["readiness_count"],
                        mem_bucket["readiness_count"],
                    ),
                    "quality_sum": max(
                        disk_bucket["quality_sum"],
                        mem_bucket["quality_sum"],
                    ),
                    "quality_count": max(
                        disk_bucket["quality_count"],
                        mem_bucket["quality_count"],
                    ),
                    "last_ts": max(disk_bucket["last_ts"], mem_bucket["last_ts"]),
                }

            # Merge per-advice outcome index to avoid repeated counter inflation.
            recent_outcomes = dict(disk_data.get("recent_outcomes", {}))
            recent_outcomes.update(mem_data.get("recent_outcomes", {}))
            merged["recent_outcomes"] = recent_outcomes
            merged = self._normalize_effectiveness(merged)

            # Update in-memory state with merged values
            self.effectiveness = merged

            # Atomic write: write to temp file then rename
            EFFECTIVENESS_FILE.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(
                dir=EFFECTIVENESS_FILE.parent,
                prefix=".effectiveness_",
                suffix=".tmp"
            )
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(merged, f, indent=2)
                # Atomic replace (os.replace works on Windows without separate unlink)
                os.replace(temp_path, str(EFFECTIVENESS_FILE))
            except Exception:
                # Clean up temp file on error
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
        except Exception:
            # Fallback to simple write if atomic fails
            fallback = self._normalize_effectiveness(self.effectiveness)
            self.effectiveness = fallback
            EFFECTIVENESS_FILE.write_text(json.dumps(fallback, indent=2), encoding="utf-8")

    def _mark_outcome_counted(
        self,
        advice_id: str,
        was_followed: bool,
        was_helpful: Optional[bool],
        category: Optional[str] = None,
    ) -> Tuple[bool, bool]:
        """Return whether aggregate counters should increment for this advice_id."""
        outcomes = self.effectiveness.setdefault("recent_outcomes", {})
        key = str(advice_id or "").strip()
        now = time.time()

        # If advice_id is missing, keep legacy behavior.
        if not key:
            return bool(was_followed), bool(was_helpful)

        entry = outcomes.get(key) or {}
        followed_counted = bool(entry.get("followed_counted"))
        helpful_counted = bool(entry.get("helpful_counted"))

        inc_followed = bool(was_followed) and not followed_counted
        inc_helpful = bool(was_helpful) and not helpful_counted

        if was_followed:
            entry["followed_counted"] = True
        if was_helpful:
            entry["helpful_counted"] = True
        entry["ts"] = now
        outcomes[key] = entry

        # Category-level aggregates help surface what categories are actually acting.
        if category:
            cat = self._coerce_advisory_category(category, fallback="general")
            cat_bucket = self._coerce_category_bucket(
                self.effectiveness.setdefault("by_category", {}).get(cat, {})
            )
            if inc_followed:
                cat_bucket["total"] += 1
            if inc_helpful:
                cat_bucket["helpful"] += 1
            cat_bucket["last_ts"] = now
            if cat_bucket["total"]:
                cat_bucket["helpful"] = min(cat_bucket["helpful"], cat_bucket["total"])
            self.effectiveness["by_category"][cat] = cat_bucket

        # Keep bounded to avoid unbounded growth.
        if len(outcomes) > RECENT_OUTCOMES_MAX:
            oldest = min(outcomes.items(), key=lambda item: float(item[1].get("ts", 0.0)))[0]
            outcomes.pop(oldest, None)

        return inc_followed, inc_helpful

    def _generate_advice_id(
        self,
        text: str,
        *,
        insight_key: Optional[str] = None,
        source: Optional[str] = None,
    ) -> str:
        """Generate a stable advice ID.

        Important: this must be deterministic across sessions so we can:
        - dedupe repeats reliably (avoid advice spam)
        - attribute outcomes to the right learning over time

        When we have a durable `insight_key` for durable sources (cognitive/mind/bank/etc),
        prefer that as the stable ID anchor (so minor text edits don't reset the ID).
        """

        def _norm_text(value: str) -> str:
            t = str(value or "").strip().lower()
            t = re.sub(r"\s+", " ", t).strip()
            return t[:400]

        src = str(source or "").strip().lower()
        # Canonicalize semantic retrieval route labels back to the underlying learning store.
        # Otherwise the same insight would churn IDs when retrieval strategy changes.
        if src.startswith("semantic") or src == "trigger":
            src = "cognitive"

        key = str(insight_key or "").strip()
        if key and src in {"cognitive", "bank", "mind", "chip", "skill", "niche", "convo", "eidos", "engagement"}:
            return f"{src}:{key}"

        payload = "|".join([src, key, _norm_text(text)])
        return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:12]

    @staticmethod
    def _coerce_advisory_category(raw: Any, *, fallback: str = "general") -> str:
        return _coerce_advisory_category_value(raw, fallback=fallback)

    def _category_boost_from_effectiveness(self, category: str) -> float:
        """Compute a bounded multiplier for category-level demonstrated utility."""
        if not isinstance(self.effectiveness, dict):
            return 1.0
        cat = self._coerce_advisory_category(category, fallback="general")
        buckets = self.effectiveness.get("by_category") or {}
        if not isinstance(buckets, dict):
            return 1.0
        row = self._coerce_category_bucket(buckets.get(cat, {}))
        surfaced = float(row.get("surfaced", 0) or 0.0)
        if surfaced <= 0:
            return 1.0
        total = float(row.get("total", 0) or 0.0)
        helpful = float(row.get("helpful", 0) or 0.0)
        readiness_sum = float(row.get("readiness_sum", 0.0) or 0.0)
        readiness_count = float(row.get("readiness_count", 0) or 0.0)
        quality_sum = float(row.get("quality_sum", 0.0) or 0.0)
        quality_count = float(row.get("quality_count", 0) or 0.0)
        if total <= 0 and readiness_count <= 0 and quality_count <= 0:
            return 1.0

        follow_rate = total / surfaced
        helpful_rate = helpful / total if total > 0 else 0.0
        readiness_avg = readiness_sum / max(1.0, readiness_count)
        quality_avg = quality_sum / max(1.0, quality_count)

        evidence = min(1.0, surfaced / max(1, CATEGORY_EFFECTIVENESS_MIN_SURFACE))
        signal = (
            (0.35 * follow_rate)
            + (0.35 * helpful_rate)
            + (0.15 * readiness_avg)
            + (0.15 * quality_avg)
        )
        multiplier = 0.85 + (0.35 * evidence * signal)

        last_ts = float(row.get("last_ts", 0.0) or 0.0)
        if last_ts > 0:
            age = max(0.0, time.time() - last_ts)
            recency = 1.0 - min(age / max(1.0, float(CATEGORY_EFFECTIVENESS_DECAY_SECONDS)), 0.20)
            multiplier *= max(0.9, recency)

        return max(0.9, min(1.2, multiplier))

    def _advice_category(self, advice: Advice) -> str:
        if advice is not None and str(getattr(advice, "category", "") or "").strip():
            return self._coerce_advisory_category(advice.category)

        source = str(getattr(advice, "source", "") or "").strip().lower()
        if source in {"semantic", "semantic-hybrid", "semantic-agentic", "trigger"}:
            source = "cognitive"
        key = str(getattr(advice, "insight_key", "") or "")
        if key:
            prefix = str(key.split(":", 1)[0]).strip().lower()
            if prefix:
                source = source or prefix
                if prefix in {"eidos", "mind", "bank", "chip", "niche", "convo", "engagement", "replay", "opportunity", "skill"}:
                    source = prefix
                elif prefix == "cognitive":
                    source = "cognitive"
        if source:
            return self._coerce_advisory_category(source)

        adv_q = getattr(advice, "advisory_quality", None)
        if isinstance(adv_q, dict):
            domain = adv_q.get("domain")
            if domain:
                return self._coerce_advisory_category(domain)

        return "general"

    @staticmethod
    def _advice_quality_summary(advice: Advice) -> Dict[str, Any]:
        adv_q = getattr(advice, "advisory_quality", None)
        if isinstance(adv_q, dict):
            return {
                "unified_score": round(max(0.0, min(1.0, float(adv_q.get("unified_score", 0.0) or 0.0))), 4),
                "domain": str(adv_q.get("domain", "general") or "general").strip().lower(),
            }
        return {"unified_score": 0.0, "domain": "general"}

    @staticmethod
    def _advice_readiness_score(advice: Advice) -> float:
        return float(getattr(advice, "advisory_readiness", 0.0) or 0.0)

    def _cache_key(
        self,
        tool: str,
        context: str,
        tool_input: Optional[Dict[str, Any]] = None,
        task_context: str = "",
        include_mind: bool = False,
    ) -> str:
        """Generate stable cache key with collision-resistant hashing."""
        keys = ("command", "file_path", "path", "url", "pattern", "query")
        hint = {}
        if isinstance(tool_input, dict):
            for k in keys:
                v = tool_input.get(k)
                if v is not None:
                    hint[k] = str(v)[:200]
        payload = {
            "tool": (tool or "").strip().lower(),
            "context": (context or "").strip().lower(),
            "task_context": (task_context or "").strip().lower(),
            "input_hint": hint,
            "include_mind": bool(include_mind),
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha1(encoded.encode("utf-8", errors="replace")).hexdigest()[:16]
        return f"{payload['tool']}:{digest}"

    def _get_cached_advice(self, key: str) -> Optional[List[Advice]]:
        """Get cached advice if still valid."""
        if key in self._cache:
            advice, timestamp = self._cache[key]
            if time.time() - timestamp < ADVICE_CACHE_TTL_SECONDS:
                return advice
            del self._cache[key]
        return None

    def _cache_advice(self, key: str, advice: List[Advice]):
        """Cache advice for reuse."""
        self._cache[key] = (advice, time.time())
        # Keep cache bounded
        if len(self._cache) > 100:
            oldest = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest]

    # ============= Retrieval Policy =============

    def _sanitize_domain_profiles(self, raw: Any) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        if not isinstance(raw, dict):
            return out
        for domain_raw, profile_raw in raw.items():
            if not isinstance(profile_raw, dict):
                continue
            domain = _norm_retrieval_domain(domain_raw)
            profile: Dict[str, Any] = {}
            for key, value in profile_raw.items():
                if key in RETRIEVAL_DOMAIN_PROFILE_KEYS:
                    profile[key] = value
            if profile:
                out[domain] = profile
        return out

    def _detect_retrieval_domain(self, tool_name: str, context: str) -> str:
        tool = str(tool_name or "").strip().lower()
        body = str(context or "").strip().lower()
        combined = f"{tool} {body}".strip()
        if not combined:
            return "general"

        for domain, markers in RETRIEVAL_DOMAIN_MARKERS.items():
            if any(marker in combined for marker in markers):
                return domain
        hinted = RETRIEVAL_TOOL_DOMAIN_HINTS.get(tool)
        if hinted:
            return hinted
        return "general"

    def _effective_retrieval_policy(self, tool_name: str, context: str) -> Dict[str, Any]:
        policy = dict(self.retrieval_policy or {})
        active_domain = self._detect_retrieval_domain(tool_name, context)
        policy["active_domain"] = active_domain
        policy["profile_domain"] = "default"
        enabled = _parse_bool(policy.get("domain_profile_enabled", True), True)
        policy["domain_profile_enabled"] = enabled
        if not enabled:
            return policy

        domain_profiles = policy.get("domain_profiles") or {}
        if not isinstance(domain_profiles, dict):
            return policy
        overrides = domain_profiles.get(active_domain)
        if overrides is None:
            overrides = domain_profiles.get("default")
            if isinstance(overrides, dict):
                policy["profile_domain"] = "default"
        else:
            policy["profile_domain"] = active_domain
        if isinstance(overrides, dict):
            policy.update(overrides)
        return policy

    def _load_retrieval_policy(self) -> Dict[str, Any]:
        """Load retrieval routing policy from tuneables + env via config-authority."""
        level = "1"
        policy: Dict[str, Any] = {}

        # Resolve retrieval section via config-authority (handles env overrides).
        retrieval_cfg: Dict[str, Any] = {}
        try:
            from .config_authority import env_bool, env_float, env_int, env_str, resolve_section
            retrieval_cfg = resolve_section(
                "retrieval",
                env_overrides={
                    "mode": env_str("SPARK_RETRIEVAL_MODE"),
                    "level": env_str("SPARK_RETRIEVAL_LEVEL"),
                    "minimax_fast_rerank": env_bool("SPARK_ADVISORY_MINIMAX_FAST_RERANK"),
                    "minimax_fast_rerank_top_k": env_int("SPARK_ADVISORY_MINIMAX_TOP_K"),
                    "minimax_fast_rerank_min_items": env_int("SPARK_ADVISORY_MINIMAX_MIN_ITEMS"),
                    "minimax_fast_rerank_min_complexity": env_int("SPARK_ADVISORY_MINIMAX_MIN_COMPLEXITY"),
                    "minimax_fast_rerank_high_volume_min_items": env_int("SPARK_ADVISORY_MINIMAX_HIGH_VOLUME_ITEMS"),
                    "minimax_fast_rerank_require_agentic": env_bool("SPARK_ADVISORY_MINIMAX_REQUIRE_AGENTIC"),
                    "minimax_fast_rerank_model": env_str("SPARK_ADVISORY_MINIMAX_MODEL"),
                    "minimax_fast_rerank_timeout_s": env_float("SPARK_ADVISORY_MINIMAX_TIMEOUT_S"),
                    "minimax_fast_rerank_cooldown_s": env_float("SPARK_ADVISORY_MINIMAX_COOLDOWN_S"),
                },
            ).data
        except Exception:
            pass

        # Determine level from resolved config.
        level = str(retrieval_cfg.get("level") or "1").strip()
        if level not in DEFAULT_RETRIEVAL_PROFILES:
            level = "1"
        policy = dict(DEFAULT_RETRIEVAL_PROFILES[level])
        policy["level"] = level

        # Apply overrides from tuneables.json -> retrieval section (file-based).
        advisor_policy: Optional[Dict[str, Any]] = None
        retrieval_keys_present: set = set()
        try:
            tuneables = Path.home() / ".spark" / "tuneables.json"
            if tuneables.exists():
                data = json.loads(tuneables.read_text(encoding="utf-8-sig"))
                advisor = data.get("advisor") or {}
                if isinstance(advisor, dict):
                    ap = advisor.get("retrieval_policy")
                    if isinstance(ap, dict):
                        advisor_policy = ap
                retrieval = data.get("retrieval") or {}
                if isinstance(retrieval, dict):
                    lvl = str(retrieval.get("level") or level).strip()
                    if lvl in DEFAULT_RETRIEVAL_PROFILES:
                        level = lvl
                        policy = dict(DEFAULT_RETRIEVAL_PROFILES[level])
                        policy["level"] = level
                    profile_overrides = retrieval.get("profiles") or {}
                    if isinstance(profile_overrides, dict):
                        by_level = profile_overrides.get(level) or {}
                        if isinstance(by_level, dict):
                            policy.update(by_level)
                    domain_profiles = retrieval.get("domain_profiles")
                    if isinstance(domain_profiles, dict):
                        policy["domain_profiles"] = domain_profiles
                    overrides = retrieval.get("overrides") or {}
                    if isinstance(overrides, dict):
                        minimax_keys = {
                            "minimax_fast_rerank", "minimax_fast_rerank_top_k",
                            "minimax_fast_rerank_min_items", "minimax_fast_rerank_min_complexity",
                            "minimax_fast_rerank_high_volume_min_items",
                            "minimax_fast_rerank_require_agentic", "minimax_fast_rerank_model",
                            "minimax_fast_rerank_timeout_s", "minimax_fast_rerank_cooldown_s",
                        }
                        tracked = {
                            "semantic_context_min", "semantic_lexical_min",
                            "semantic_strong_override", "lexical_weight",
                            "semantic_intent_min", "intent_coverage_weight",
                            "support_boost_weight", "reliability_weight",
                        } | minimax_keys
                        for key in tracked:
                            if key in overrides:
                                retrieval_keys_present.add(key)
                        policy.update(overrides)
                    for key in (
                        "mode", "gate_strategy", "semantic_limit",
                        "semantic_context_min", "semantic_lexical_min",
                        "semantic_strong_override", "max_queries",
                        "agentic_query_limit", "agentic_deadline_ms",
                        "agentic_rate_limit", "agentic_rate_window",
                        "fast_path_budget_ms", "deny_escalation_when_over_budget",
                        "prefilter_enabled", "prefilter_max_insights",
                        "prefilter_drop_low_signal", "lexical_weight",
                        "intent_coverage_weight", "support_boost_weight",
                        "reliability_weight", "bm25_k1", "bm25_b", "bm25_mix",
                        "semantic_intent_min", "complexity_threshold",
                        "min_results_no_escalation", "min_top_score_no_escalation",
                        "escalate_on_weak_primary", "escalate_on_high_risk",
                        "escalate_on_trigger", "domain_profile_enabled",
                        "domain_profiles",
                    ):
                        if key in retrieval:
                            policy[key] = retrieval.get(key)
                            retrieval_keys_present.add(key)
        except Exception:
            pass

        _maybe_warn_deprecated_advisor_retrieval_policy(
            advisor_policy=advisor_policy,
            retrieval_keys_present=retrieval_keys_present,
            effective_policy=policy,
        )

        # Apply resolved config-authority values for minimax + mode (env wins).
        if retrieval_cfg:
            env_mode = str(retrieval_cfg.get("mode") or "").strip().lower()
            if env_mode in {"auto", "embeddings_only", "hybrid_agentic"}:
                policy["mode"] = env_mode
            for mk in (
                "minimax_fast_rerank", "minimax_fast_rerank_top_k",
                "minimax_fast_rerank_min_items", "minimax_fast_rerank_min_complexity",
                "minimax_fast_rerank_high_volume_min_items",
                "minimax_fast_rerank_require_agentic", "minimax_fast_rerank_model",
                "minimax_fast_rerank_timeout_s", "minimax_fast_rerank_cooldown_s",
            ):
                if mk in retrieval_cfg:
                    policy[mk] = retrieval_cfg[mk]

        # Normalize types.
        policy["mode"] = str(policy.get("mode") or "auto").strip().lower()
        if policy["mode"] not in {"auto", "embeddings_only", "hybrid_agentic"}:
            policy["mode"] = "auto"
        policy["gate_strategy"] = str(policy.get("gate_strategy") or "minimal").strip().lower()
        if policy["gate_strategy"] not in {"minimal", "extended"}:
            policy["gate_strategy"] = "minimal"
        policy["semantic_limit"] = max(4, int(policy.get("semantic_limit", 8) or 8))
        policy["semantic_context_min"] = max(
            0.0, min(1.0, float(policy.get("semantic_context_min", 0.15) or 0.15))
        )
        policy["semantic_lexical_min"] = max(
            0.0, min(1.0, float(policy.get("semantic_lexical_min", 0.03) or 0.03))
        )
        policy["semantic_strong_override"] = max(
            0.0, min(1.0, float(policy.get("semantic_strong_override", 0.90) or 0.90))
        )
        policy["max_queries"] = max(1, int(policy.get("max_queries", 2) or 2))
        policy["agentic_query_limit"] = max(1, int(policy.get("agentic_query_limit", 2) or 2))
        deadline_raw = policy.get("agentic_deadline_ms", 700)
        if deadline_raw is None:
            deadline_raw = 700
        policy["agentic_deadline_ms"] = max(0, int(deadline_raw))

        rate_raw = policy.get("agentic_rate_limit", 0.2)
        if rate_raw is None:
            rate_raw = 0.2
        policy["agentic_rate_limit"] = max(0.0, min(1.0, float(rate_raw)))
        policy["agentic_rate_window"] = max(10, int(policy.get("agentic_rate_window", 80) or 80))
        policy["fast_path_budget_ms"] = max(50, int(policy.get("fast_path_budget_ms", 250) or 250))
        policy["deny_escalation_when_over_budget"] = bool(
            policy.get("deny_escalation_when_over_budget", True)
        )
        policy["prefilter_enabled"] = bool(policy.get("prefilter_enabled", True))
        prefilter_raw = policy.get("prefilter_max_insights", 500)
        if prefilter_raw is None:
            prefilter_raw = 500
        policy["prefilter_max_insights"] = max(20, int(prefilter_raw))
        policy["prefilter_drop_low_signal"] = bool(policy.get("prefilter_drop_low_signal", True))
        policy["lexical_weight"] = max(0.0, min(1.0, float(policy.get("lexical_weight", 0.25) or 0.25)))
        policy["intent_coverage_weight"] = max(
            0.0, min(1.0, float(policy.get("intent_coverage_weight", 0.0) or 0.0))
        )
        policy["support_boost_weight"] = max(
            0.0, min(1.0, float(policy.get("support_boost_weight", 0.0) or 0.0))
        )
        policy["reliability_weight"] = max(
            0.0, min(1.0, float(policy.get("reliability_weight", 0.0) or 0.0))
        )
        policy["minimax_fast_rerank"] = _parse_bool(policy.get("minimax_fast_rerank", True), True)
        policy["minimax_fast_rerank_top_k"] = max(4, int(policy.get("minimax_fast_rerank_top_k", 16) or 16))
        policy["minimax_fast_rerank_min_items"] = max(6, int(policy.get("minimax_fast_rerank_min_items", 12) or 12))
        policy["minimax_fast_rerank_min_complexity"] = max(0, int(policy.get("minimax_fast_rerank_min_complexity", 1) or 1))
        policy["minimax_fast_rerank_high_volume_min_items"] = max(
            0, int(policy.get("minimax_fast_rerank_high_volume_min_items", 0) or 0)
        )
        policy["minimax_fast_rerank_require_agentic"] = _parse_bool(
            policy.get("minimax_fast_rerank_require_agentic", False), False
        )
        policy["minimax_fast_rerank_model"] = str(
            policy.get("minimax_fast_rerank_model", os.getenv("SPARK_MINIMAX_MODEL", "MiniMax-M2.5")) or "MiniMax-M2.5"
        ).strip() or "MiniMax-M2.5"
        policy["minimax_fast_rerank_timeout_s"] = max(
            2.0, float(policy.get("minimax_fast_rerank_timeout_s", 7.0) or 7.0)
        )
        policy["minimax_fast_rerank_cooldown_s"] = max(
            0.0, float(policy.get("minimax_fast_rerank_cooldown_s", 30.0) or 30.0)
        )
        policy["bm25_k1"] = max(0.1, float(policy.get("bm25_k1", 1.2) or 1.2))
        policy["bm25_b"] = max(0.0, min(1.0, float(policy.get("bm25_b", 0.75) or 0.75)))
        policy["bm25_mix"] = max(0.0, min(1.0, float(policy.get("bm25_mix", 0.75) or 0.75)))
        policy["semantic_intent_min"] = max(
            0.0, min(1.0, float(policy.get("semantic_intent_min", 0.0) or 0.0))
        )
        policy["complexity_threshold"] = max(1, int(policy.get("complexity_threshold", 2) or 2))
        policy["min_results_no_escalation"] = max(1, int(policy.get("min_results_no_escalation", 3) or 3))
        policy["min_top_score_no_escalation"] = max(
            0.0, min(1.0, float(policy.get("min_top_score_no_escalation", 0.7) or 0.7))
        )
        policy["escalate_on_weak_primary"] = bool(policy.get("escalate_on_weak_primary", True))
        policy["escalate_on_high_risk"] = bool(policy.get("escalate_on_high_risk", True))
        policy["escalate_on_trigger"] = bool(policy.get("escalate_on_trigger", True))
        policy["domain_profile_enabled"] = _parse_bool(policy.get("domain_profile_enabled", True), True)
        policy["domain_profiles"] = self._sanitize_domain_profiles(policy.get("domain_profiles") or {})
        policy["complexity_hints"] = list(DEFAULT_COMPLEXITY_HINTS)
        policy["high_risk_hints"] = list(DEFAULT_HIGH_RISK_HINTS)
        return policy

    def _load_memory_emotion_cfg(self) -> Dict[str, Any]:
        tuneables = Path.home() / ".spark" / "tuneables.json"
        current_mtime: Optional[float] = None
        try:
            if tuneables.exists():
                current_mtime = float(tuneables.stat().st_mtime)
        except Exception:
            current_mtime = None

        if self._memory_emotion_cfg_mtime == current_mtime:
            return dict(self._memory_emotion_cfg_cache)

        cfg = dict(MEMORY_EMOTION_DEFAULTS)
        try:
            from .config_authority import env_bool, env_float, resolve_section
            section = resolve_section(
                "memory_emotion",
                env_overrides={
                    "enabled": env_bool("SPARK_ADVISORY_MEMORY_EMOTION_ENABLED"),
                    "retrieval_state_match_weight": env_float("SPARK_ADVISORY_MEMORY_EMOTION_WEIGHT"),
                    "retrieval_min_state_similarity": env_float("SPARK_ADVISORY_MEMORY_EMOTION_MIN_SIM"),
                },
            ).data
            cfg["enabled"] = _parse_bool(section.get("enabled"), cfg["enabled"])
            cfg["advisory_rerank_weight"] = _safe_float(
                section.get("retrieval_state_match_weight"),
                cfg["advisory_rerank_weight"],
            )
            cfg["advisory_min_state_similarity"] = _safe_float(
                section.get("retrieval_min_state_similarity"),
                cfg["advisory_min_state_similarity"],
            )
        except Exception:
            pass

        cfg["advisory_rerank_weight"] = max(0.0, float(cfg.get("advisory_rerank_weight", 0.0)))
        cfg["advisory_min_state_similarity"] = _clamp_01(
            _safe_float(cfg.get("advisory_min_state_similarity"), MEMORY_EMOTION_DEFAULTS["advisory_min_state_similarity"])
        )
        cfg["enabled"] = _parse_bool(cfg.get("enabled"), True)
        self._memory_emotion_cfg_cache = dict(cfg)
        self._memory_emotion_cfg_mtime = current_mtime
        return dict(cfg)

    def _current_emotion_state_for_rerank(self) -> Optional[Dict[str, Any]]:
        try:
            from .spark_emotions import SparkEmotions

            state = (SparkEmotions().status() or {}).get("state") or {}
            if not isinstance(state, dict):
                return None
            return {
                "primary_emotion": str(state.get("primary_emotion") or "steady"),
                "mode": str(state.get("mode") or "real_talk"),
                "warmth": _clamp_01(_safe_float(state.get("warmth"), 0.0)),
                "energy": _clamp_01(_safe_float(state.get("energy"), 0.0)),
                "confidence": _clamp_01(_safe_float(state.get("confidence"), 0.0)),
                "calm": _clamp_01(_safe_float(state.get("calm"), 0.0)),
                "playfulness": _clamp_01(_safe_float(state.get("playfulness"), 0.0)),
                "strain": _clamp_01(_safe_float(state.get("strain"), 0.0)),
            }
        except Exception:
            return None

    def _extract_insight_emotion_state(self, insight: Any) -> Dict[str, Any]:
        if insight is None:
            return {}
        direct = getattr(insight, "emotion_state", None)
        if isinstance(direct, dict):
            return direct
        meta = getattr(insight, "meta", None)
        if isinstance(meta, dict):
            emo = meta.get("emotion")
            if isinstance(emo, dict):
                return emo
        if isinstance(insight, dict):
            if isinstance(insight.get("emotion_state"), dict):
                return insight.get("emotion_state") or {}
            meta_raw = insight.get("meta")
            if isinstance(meta_raw, dict) and isinstance(meta_raw.get("emotion"), dict):
                return meta_raw.get("emotion") or {}
        return {}

    def _emotion_state_similarity(
        self,
        active_state: Optional[Dict[str, Any]],
        stored_state: Optional[Dict[str, Any]],
    ) -> float:
        if not isinstance(active_state, dict) or not isinstance(stored_state, dict):
            return 0.0
        if not active_state or not stored_state:
            return 0.0

        emotion_match = 1.0 if (
            str(active_state.get("primary_emotion") or "").strip()
            and str(active_state.get("primary_emotion") or "").strip()
            == str(stored_state.get("primary_emotion") or "").strip()
        ) else 0.0
        mode_match = 1.0 if (
            str(active_state.get("mode") or "").strip()
            and str(active_state.get("mode") or "").strip()
            == str(stored_state.get("mode") or "").strip()
        ) else 0.0

        axis_scores: List[float] = []
        for axis in ("strain", "calm", "energy", "confidence", "warmth", "playfulness"):
            if axis not in active_state or axis not in stored_state:
                continue
            a = _clamp_01(_safe_float(active_state.get(axis), 0.0))
            b = _clamp_01(_safe_float(stored_state.get(axis), 0.0))
            axis_scores.append(max(0.0, 1.0 - abs(a - b)))

        axis_similarity = sum(axis_scores) / len(axis_scores) if axis_scores else 0.0
        return _clamp_01((0.50 * axis_similarity) + (0.35 * emotion_match) + (0.15 * mode_match))

    def _analyze_query_complexity(self, tool_name: str, context: str) -> Dict[str, Any]:
        """Estimate when agentic retrieval is worth the added latency/cost."""
        text = str(context or "").strip().lower()
        tokens = [t for t in re.findall(r"[a-z0-9_]+", text) if t]
        score = 0
        reasons: List[str] = []

        if len(tokens) >= 18:
            score += 1
            reasons.append("long_query")
        if "?" in context:
            score += 1
            reasons.append("question_form")

        complexity_hits = [k for k in self.retrieval_policy.get("complexity_hints", []) if k in text]
        if complexity_hits:
            score += min(2, len(complexity_hits))
            reasons.append("complexity_terms")

        high_risk_hits = [k for k in self.retrieval_policy.get("high_risk_hints", []) if k in text]
        if high_risk_hits:
            score += 1
            reasons.append("risk_terms")

        tool = str(tool_name or "").strip().lower()
        if tool in {"bash", "edit", "write", "task"}:
            score += 1
            reasons.append("high_impact_tool")

        threshold = int(self.retrieval_policy.get("complexity_threshold", 2) or 2)
        return {
            "score": score,
            "threshold": threshold,
            "requires_agentic": score >= threshold,
            "complexity_hits": complexity_hits[:4],
            "high_risk_hits": high_risk_hits[:4],
            "reasons": reasons,
        }

    def _should_use_minimax_fast_rerank(
        self,
        tool_name: str,
        context: str,
        advice_count: int,
        policy: Dict[str, Any],
    ) -> Tuple[bool, Dict[str, Any]]:
        """Decide whether minimax rerank should run for this query."""
        policy = policy or {}
        if not bool(policy.get("minimax_fast_rerank", False)):
            return False, {
                "decision": "skip",
                "reason": "disabled",
                "analysis": {"score": 0, "threshold": 0, "requires_agentic": False},
                "used": False,
            }

        min_items = max(6, int(policy.get("minimax_fast_rerank_min_items", 12) or 12))
        if advice_count < min_items:
            return False, {
                "decision": "skip",
                "reason": "below_min_items",
                "analysis": {"score": 0, "threshold": 0, "requires_agentic": False},
                "used": False,
                "advice_count": advice_count,
                "min_items": min_items,
            }

        analysis = self._analyze_query_complexity(tool_name, context)
        complexity_min = max(0, int(policy.get("minimax_fast_rerank_min_complexity", 1) or 1))
        high_volume_min_items = max(0, int(policy.get("minimax_fast_rerank_high_volume_min_items", 0) or 0))
        require_agentic = _parse_bool(policy.get("minimax_fast_rerank_require_agentic", False), False)

        if require_agentic and not analysis.get("requires_agentic"):
            return False, {
                "decision": "skip",
                "reason": "agentic_only",
                "analysis": analysis,
                "used": False,
                "complexity_min": complexity_min,
            }

        if high_volume_min_items and advice_count >= high_volume_min_items:
            return True, {
                "decision": "use",
                "reason": "high_volume_override",
                "analysis": analysis,
                "used": True,
                "high_volume_min_items": high_volume_min_items,
            }

        if analysis.get("score", 0) >= complexity_min:
            return True, {
                "decision": "use",
                "reason": "complexity_threshold",
                "analysis": analysis,
                "used": True,
                "complexity_min": complexity_min,
            }

        return False, {
            "decision": "skip",
            "reason": "low_complexity",
            "analysis": analysis,
            "used": False,
            "complexity_min": complexity_min,
        }

    def _log_retrieval_route(
        self,
        entry: Dict[str, Any],
        *,
        trace_id: Optional[str] = None,
    ) -> None:
        payload = dict(entry or {})
        payload.setdefault("trace_id", str(trace_id or "").strip() or None)
        payload["ts"] = time.time()
        _append_jsonl_capped(RETRIEVAL_ROUTE_LOG, payload, RETRIEVAL_ROUTE_LOG_MAX)

    def _record_agentic_route(self, used_agentic: bool, window: int) -> None:
        self._agentic_route_history.append(bool(used_agentic))
        max_window = max(10, int(window or 80))
        if len(self._agentic_route_history) > max_window:
            self._agentic_route_history = self._agentic_route_history[-max_window:]

    def _agentic_recent_rate(self, window: int) -> float:
        max_window = max(10, int(window or 80))
        if not self._agentic_route_history:
            return 0.0
        sample = self._agentic_route_history[-max_window:]
        return sum(1 for x in sample if x) / max(1, len(sample))

    def _allow_agentic_escalation(self, rate_limit: float, window: int) -> bool:
        if rate_limit >= 1.0:
            return True
        return self._agentic_recent_rate(window) < max(0.0, float(rate_limit))

    def _insight_blob(self, key: str, insight: Any) -> str:
        parts = [str(key or "")]
        for attr in ("insight", "context", "category", "project", "tool", "source", "scope"):
            val = getattr(insight, attr, None)
            if val:
                parts.append(str(val))
        if isinstance(insight, dict):
            for field in ("insight", "context", "category", "project", "tool", "source", "scope"):
                val = insight.get(field)
                if val:
                    parts.append(str(val))
        return " ".join(parts).lower()

    def _prefilter_cached_blob_tokens(self, key: str, insight: Any) -> Tuple[set, str]:
        """Return (tokens, blob_lower) for an insight, cached by blob hash."""
        blob = self._insight_blob(key, insight)
        blob_hash = hashlib.sha1(blob.encode("utf-8", errors="replace")).hexdigest()[:16]
        cached = self._prefilter_cache.get(key)
        if cached and cached[0] == blob_hash:
            return cached[1], cached[2]
        tokens = {t for t in re.findall(r"[a-z0-9_]+", blob) if len(t) >= 3}
        self._prefilter_cache[key] = (blob_hash, tokens, blob)
        # Keep cache bounded (avoid unbounded growth if keys churn).
        if len(self._prefilter_cache) > 5000:
            # Drop an arbitrary 20% slice.
            for k in list(self._prefilter_cache.keys())[:1000]:
                self._prefilter_cache.pop(k, None)
        return tokens, blob

    # Intent → allowed action_domains mapping for pre-retrieval filtering.
    # "general" is always allowed as a fallback domain.
    _INTENT_DOMAIN_MAP: Dict[str, set] = {
        "auth_security":             {"code", "system", "general"},
        "deployment_ops":            {"code", "system", "general"},
        "testing_validation":        {"code", "general"},
        "schema_contracts":          {"code", "general"},
        "performance_latency":       {"code", "system", "general"},
        "tool_reliability":          {"code", "system", "general"},
        "knowledge_alignment":       {"code", "system", "general"},
        "team_coordination":         {"general"},
        "orchestration_execution":   {"code", "system", "general"},
        "stakeholder_alignment":     {"general"},
        "research_decision_support": {"code", "general"},
        "emergent_other":            {"code", "system", "general"},
    }

    def _insight_readiness_score(self, insight: Any) -> float:
        """Readiness score for an insight at retrieval time."""
        ready = float(getattr(insight, "advisory_readiness", 0.0) or 0.0)
        if ready:
            return max(0.0, min(1.0, ready))
        adv_q = getattr(insight, "advisory_quality", None) or {}
        if isinstance(adv_q, dict):
            return max(0.0, min(1.0, float(adv_q.get("unified_score", 0.0) or 0.0)))
        return 0.0

    @staticmethod
    def _coerce_payload_readiness(payload: Any, fallback: float = 0.0) -> float:
        """Extract advisory_readiness from mind payloads with graceful fallback."""
        try:
            if not isinstance(payload, dict):
                return max(0.0, min(1.0, float(fallback or 0.0)))
            direct = payload.get("advisory_readiness")
            if direct is not None:
                return max(0.0, min(1.0, float(direct)))
            adv_q = payload.get("advisory_quality")
            if isinstance(adv_q, dict):
                unified = adv_q.get("unified_score")
                if unified is not None:
                    return max(0.0, min(1.0, float(unified)))
                if adv_q.get("domain"):
                    return 0.55
        except Exception:
            pass
        try:
            return max(0.0, min(1.0, float(fallback or 0.0)))
        except Exception:
            return 0.0

    def _prefilter_insights_for_retrieval(
        self,
        insights: Dict[str, Any],
        tool_name: str,
        context: str,
        max_items: int,
    ) -> Dict[str, Any]:
        if not insights:
            return insights
        limit = max(20, int(max_items or 500))
        drop_low_signal = bool((self.retrieval_policy or {}).get("prefilter_drop_low_signal", True))

        # --- Phase 1: Intent-based domain filtering ---
        allowed_domains = self._get_allowed_domains(tool_name, context)
        domain_filtered: Dict[str, Any] = {}
        for key, insight in insights.items():
            action_domain = getattr(insight, "action_domain", "") or "general"
            if action_domain in allowed_domains:
                domain_filtered[key] = insight
        # Fallback: if domain filtering is too aggressive (<20 items), include all
        if len(domain_filtered) < 20:
            domain_filtered = insights
        working_set = domain_filtered

        # --- Phase 2: Low-signal drop + keyword scoring (existing logic) ---
        if len(working_set) <= limit:
            if not drop_low_signal:
                return {
                    key: insight
                    for _, key, insight in sorted(
                        [(self._insight_readiness_score(insight), key, insight) for key, insight in working_set.items()],
                        key=lambda row: row[0],
                        reverse=True,
                    )
                }
            filtered: Dict[str, Any] = {}
            for key, insight in working_set.items():
                _, blob = self._prefilter_cached_blob_tokens(str(key), insight)
                if self._should_drop_low_signal_candidate(blob):
                    continue
                filtered[key] = insight
            sorted_filtered = {
                key: insight
                for _, key, insight in sorted(
                    [(self._insight_readiness_score(insight), key, insight) for key, insight in filtered.items()],
                    key=lambda row: row[0],
                    reverse=True,
                )
            }
            return sorted_filtered or working_set

        query_tokens = self._intent_terms(context)
        if not query_tokens:
            query_tokens = {t for t in re.findall(r"[a-z0-9_]+", (context or "").lower()) if len(t) >= 3}
        tool = str(tool_name or "").strip().lower()
        scored: List[Tuple[float, str, Any]] = []
        fallback: List[Tuple[float, str, Any]] = []
        for key, insight in working_set.items():
            blob_tokens, blob = self._prefilter_cached_blob_tokens(str(key), insight)
            if drop_low_signal and self._should_drop_low_signal_candidate(blob):
                continue
            blob_terms = {t for t in blob_tokens if t not in _INTENT_STOPWORDS}
            overlap = len(query_tokens & blob_terms) if query_tokens else 0
            intent_coverage = (overlap / max(1, len(query_tokens))) if query_tokens else 0.0
            metadata_boost = 2.0 if tool and tool in blob else 0.0
            reliability = float(getattr(insight, "reliability", 0.5) or 0.5)
            readiness = self._insight_readiness_score(insight)
            score = (overlap * 3.5) + (intent_coverage * 2.0) + metadata_boost + reliability + (readiness * 1.4)
            if overlap > 0 or metadata_boost > 0 or intent_coverage >= 0.2:
                scored.append((score, key, insight))
            else:
                fallback.append((reliability + (readiness * 0.6), key, insight))

        ranked: List[Tuple[float, str, Any]] = sorted(scored, key=lambda row: row[0], reverse=True)
        if len(ranked) < limit:
            ranked.extend(sorted(fallback, key=lambda row: row[0], reverse=True)[: max(0, limit - len(ranked))])

        selected = ranked[:limit]
        if not selected:
            return working_set
        return {key: insight for _, key, insight in selected}

    def _get_allowed_domains(self, tool_name: str, context: str) -> set:
        """Determine which action_domains are allowed for this tool+context."""
        try:
            from .advisory_intent_taxonomy import map_intent
            intent_result = map_intent(context or "", tool_name or "")
            intent_family = intent_result.get("intent_family", "emergent_other")
        except Exception:
            intent_family = "emergent_other"
        return self._INTENT_DOMAIN_MAP.get(intent_family, {"code", "system", "general"})

    def _mind_retrieval_allowed(self, include_mind: bool, pre_mind_count: int) -> bool:
        """Gate Mind retrieval for freshness while preserving empty-result fallback."""
        if not include_mind or not HAS_REQUESTS or self.mind is None:
            return False
        if MIND_MAX_STALE_SECONDS <= 0:
            return True

        stats = {}
        try:
            if hasattr(self.mind, "get_stats"):
                stats = self.mind.get_stats() or {}
        except Exception:
            # Don't block retrieval if stats are temporarily unavailable.
            return True

        last_sync_ts = _parse_iso_ts(stats.get("last_sync"))
        if last_sync_ts is None:
            return bool(MIND_STALE_ALLOW_IF_EMPTY and pre_mind_count <= 0)

        age_s = max(0.0, time.time() - last_sync_ts)
        if age_s <= MIND_MAX_STALE_SECONDS:
            return True
        return bool(MIND_STALE_ALLOW_IF_EMPTY and pre_mind_count <= 0)

    # ============= Core Advice Generation =============

    def advise(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        task_context: str = "",
        include_mind: bool = True,
        track_retrieval: bool = True,
        log_recent: bool = True,
        trace_id: Optional[str] = None,
    ) -> List[Advice]:
        """
        Get relevant advice before executing an action.

        This is the KEY function that closes the learning gap.

        Args:
            tool_name: The tool about to be used (e.g., "Edit", "Bash")
            tool_input: The input to the tool
            task_context: Optional description of what we're trying to do
            include_mind: Whether to query Mind for additional context
            track_retrieval: Whether to track this retrieval for outcome measurement.
                Set to False for sampling/analysis to avoid polluting metrics.
            log_recent: Whether to write to recent_advice.jsonl for outcome linkage.
                For advisory_engine paths, prefer recording only *delivered* advice via
                record_recent_delivery().
            trace_id: Optional trace_id for linking advice retrievals to traces.

        Returns:
            List of Advice objects, sorted by relevance
        """
        # Build context string for matching
        context_parts = [tool_name]
        if tool_input:
            context_parts.append(str(tool_input)[:200])
        if task_context:
            context_parts.append(task_context)
        context_raw = " ".join(context_parts).strip()
        context = context_raw.lower()

        # Build semantic context: include key tool_input values so trigger
        # rules can match against actual commands/paths, not just task_context.
        _input_hint = ""
        if tool_input and isinstance(tool_input, dict):
            for _k in ("command", "file_path", "url", "pattern", "query"):
                if _k in tool_input:
                    _input_hint = str(tool_input[_k])[:200]
                    break
        semantic_parts = [tool_name]
        if _input_hint:
            semantic_parts.append(_input_hint)
        if task_context:
            semantic_parts.append(task_context)
        semantic_context = " ".join(semantic_parts).strip() if (task_context or _input_hint) else context_raw

        # Check cache
        cache_key = self._cache_key(
            tool_name,
            context_raw,
            tool_input=tool_input,
            task_context=task_context,
            include_mind=include_mind,
        )
        cached = self._get_cached_advice(cache_key)
        if cached:
            # Even on cache hits, emit observability/attribution when requested.
            # Otherwise outcome tracking can mismatch traces (same advice_id reused
            # across tool calls but Meta-Ralph sees only the first retrieval).
            if track_retrieval:
                try:
                    self._record_cognitive_surface(cached)
                except Exception:
                    pass
                try:
                    self._log_advice(cached, tool_name, context, trace_id=trace_id, log_recent=log_recent)
                except Exception:
                    pass
                try:
                    from .meta_ralph import get_meta_ralph

                    ralph = get_meta_ralph()
                    for adv in cached:
                        ralph.track_retrieval(
                            adv.advice_id,
                            adv.text,
                            insight_key=adv.insight_key,
                            source=adv.source,
                            trace_id=trace_id,
                        )
                except Exception:
                    pass
            return cached

        advice_list: List[Advice] = []

        # 1. Query memory banks (fast local)
        advice_list.extend(self._get_bank_advice(context))

        # 2. Query cognitive insights (semantic + keyword fallback)
        try:
            cognitive_advice = self._get_cognitive_advice(
                tool_name,
                context,
                semantic_context,
                trace_id=trace_id,
            )
        except TypeError as exc:
            msg = str(exc)
            if "unexpected keyword argument 'trace_id'" in msg or "positional arguments but" in msg:
                # Backward-compatible call shape for tests/overrides that still
                # implement the pre-trace_id signature.
                cognitive_advice = self._get_cognitive_advice(tool_name, context, semantic_context)
            else:
                raise
        advice_list.extend(cognitive_advice)

        # 2.5. Query chip insights (domain-specific intelligence).
        advice_list.extend(self._get_chip_advice(context))

        # 3. Query Mind if available
        if self._mind_retrieval_allowed(include_mind=include_mind, pre_mind_count=len(advice_list)):
            advice_list.extend(self._get_mind_advice(context))

        # 4. Get tool-specific learnings
        advice_list.extend(self._get_tool_specific_advice(tool_name))

        # 5. Get opportunity-scanner prompts (Socratic opportunity lens)
        advice_list.extend(
            self._get_opportunity_advice(
                tool_name=tool_name,
                context_raw=context_raw,
                task_context=task_context,
            )
        )

        # 6. Get surprise-based cautions
        advice_list.extend(self._get_surprise_advice(tool_name, context))

        # 7. Get skill-based hints
        advice_list.extend(self._get_skill_advice(context))

        # 8. Get EIDOS distillations (extracted rules from patterns)
        if HAS_EIDOS:
            advice_list.extend(self._get_eidos_advice(tool_name, context))

        # 9. Get conversation intelligence advice (ConvoIQ)
        advice_list.extend(self._get_convo_advice(tool_name, context))

        # 10. Get engagement pulse advice
        advice_list.extend(self._get_engagement_advice(tool_name, context))

        # 11. Get niche intelligence advice
        advice_list.extend(self._get_niche_advice(tool_name, context))

        # 12. Replay counterfactual advisory (past outcome-backed alternatives)
        advice_list.extend(
            self._get_replay_counterfactual_advice(
                tool_name=tool_name,
                context_raw=context_raw,
                existing_advice=advice_list,
            )
        )

        # Global domain guard: do not let X-social specific learnings leak
        # into non-social tasks from non-semantic sources (chip/mind/cognitive/etc.).
        advice_list = self._filter_cross_domain_advice(advice_list, context)
        advice_list = [a for a in advice_list if not self._should_drop_advice(a, tool_name=tool_name)]
        for a in advice_list:
            a.category = self._advice_category(a)

        # Sort by relevance (confidence * context_match * effectiveness_boost)
        advice_list = self._rank_advice(advice_list)

        # Fast LLM-assisted rerank for shortlists where ranking quality can materially
        # improve relevance without requiring full cross-encoder cost.
        policy = self._effective_retrieval_policy(tool_name=tool_name, context=context)
        min_candidates = max(MAX_ADVICE_ITEMS, int(policy.get("minimax_fast_rerank_min_items", 12) or 12))
        if len(advice_list) > min_candidates:
            should_use_minimax, rerank_gate_meta = self._should_use_minimax_fast_rerank(
                tool_name=tool_name,
                context=context,
                advice_count=len(advice_list),
                policy=policy,
            )
            if should_use_minimax:
                advice_list, rerank_meta = self._minimax_fast_rerank(
                    semantic_context,
                    advice_list,
                    policy,
                    trace_id=trace_id,
                )
                # Optional telemetry (lightweight + no extra IO path).
                self._log_retrieval_route(
                    {
                        "tool": tool_name,
                        "trace_id": str(trace_id or "").strip(),
                        "route": "minimax_fast_rerank",
                        "routed": rerank_meta.get("used", False),
                        "reason": str(rerank_meta.get("reason", "")),
                        "model": str(rerank_meta.get("model", "")),
                        "top_k": int(rerank_meta.get("top_k", 0)),
                        "order_len": int(rerank_meta.get("order_len", 0)),
                        "elapsed_ms": int(rerank_meta.get("elapsed_ms", 0)),
                        "complexity_score": int((rerank_gate_meta.get("analysis") or {}).get("score", 0)),
                        "complexity_threshold": int((rerank_gate_meta.get("analysis") or {}).get("threshold", 0)),
                    }
                )
            else:
                self._log_retrieval_route(
                    {
                        "tool": tool_name,
                        "trace_id": str(trace_id or "").strip(),
                        "route": "minimax_fast_rerank",
                        "routed": False,
                        "reason": str(rerank_gate_meta.get("reason", "")),
                        "decision": str(rerank_gate_meta.get("decision", "")),
                        "complexity_score": int((rerank_gate_meta.get("analysis") or {}).get("score", 0)),
                        "complexity_threshold": int((rerank_gate_meta.get("analysis") or {}).get("threshold", 0)),
                        "requires_agentic": bool((rerank_gate_meta.get("analysis") or {}).get("requires_agentic", False)),
                        "min_items": int(rerank_gate_meta.get("min_items", 0) or 0),
                        "high_volume_min_items": int(rerank_gate_meta.get("high_volume_min_items", 0) or 0),
                        "complexity_min": int(rerank_gate_meta.get("complexity_min", 0) or 0),
                        "advice_count": int(rerank_gate_meta.get("advice_count", 0) or len(advice_list)),
                    }
                )

        # Cross-encoder reranking (Phase 2): rerank top candidates using
        # full query-document relevance scoring for higher precision.
        if len(advice_list) > MAX_ADVICE_ITEMS:
            advice_list = self._cross_encoder_rerank(semantic_context, advice_list)

        # Drop low-quality items — prefer fewer, higher-quality results
        advice_list = [a for a in advice_list if self._rank_score(a) >= MIN_RANK_SCORE]
        advice_list = self._apply_mind_slot_reserve(advice_list, max_items=MAX_ADVICE_ITEMS)

        # Limit to top N
        advice_list = advice_list[:MAX_ADVICE_ITEMS]

        # Log advice given (only for operational use, not sampling)
        if track_retrieval:
            self._record_cognitive_surface(advice_list)
            self._log_advice(advice_list, tool_name, context, trace_id=trace_id, log_recent=log_recent)

            # Track retrievals in Meta-Ralph for outcome tracking
            try:
                from .meta_ralph import get_meta_ralph
                ralph = get_meta_ralph()
                for adv in advice_list:
                    ralph.track_retrieval(
                        adv.advice_id,
                        adv.text,
                        insight_key=adv.insight_key,
                        source=adv.source,
                        trace_id=trace_id,
                    )
            except Exception:
                pass  # Don't break advice flow if tracking fails

        # Safety filter: remove any advice containing harmful patterns
        try:
            from .promoter import is_unsafe_insight
            advice_list = [a for a in advice_list if not is_unsafe_insight(a.text)]
        except Exception:
            pass  # Don't break advice flow if safety check fails

        # Cache for reuse
        self._cache_advice(cache_key, advice_list)

        return advice_list

    def _get_cognitive_advice(
        self,
        tool_name: str,
        context: str,
        semantic_context: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> List[Advice]:
        """Get advice from cognitive insights (semantic-first with keyword fallback)."""
        semantic = self._get_semantic_cognitive_advice(
            tool_name=tool_name,
            context=semantic_context or context,
            trace_id=trace_id,
        )
        keyword = self._get_cognitive_advice_keyword(tool_name, context)

        if not semantic:
            return keyword

        # Merge, preferring semantic results
        seen = {a.insight_key for a in semantic if a.insight_key}
        merged = list(semantic)
        for a in keyword:
            if a.insight_key and a.insight_key in seen:
                continue
            merged.append(a)
        return merged

    # -- LLM area hooks (opt-in via llm_areas tuneable section) --

    @staticmethod
    def _llm_area_retrieval_rewrite(query: str, tool_name: str) -> str:
        """LLM area: rewrite retrieval query for better recall.

        When disabled (default), returns query unchanged.
        """
        try:
            from .llm_area_prompts import format_prompt
            from .llm_dispatch import llm_area_call

            prompt = format_prompt(
                "retrieval_rewrite",
                query=query[:300],
                tool_name=tool_name or "unknown",
            )
            result = llm_area_call("retrieval_rewrite", prompt, fallback=query)
            if result.used_llm and result.text and result.text != query:
                return result.text
            return query
        except Exception:
            return query

    @staticmethod
    def _llm_area_retrieval_explain(
        base_reason: str,
        insight_text: str,
        query: str,
        context_match: float,
    ) -> str:
        """LLM area: annotate retrieval result with relevance explanation.

        When disabled (default), returns base_reason unchanged.
        """
        try:
            from .llm_area_prompts import format_prompt
            from .llm_dispatch import llm_area_call

            prompt = format_prompt(
                "retrieval_explain",
                insight=insight_text[:300],
                query=query[:200],
                match_score=f"{context_match:.2f}",
                base_reason=base_reason[:200],
            )
            result = llm_area_call("retrieval_explain", prompt, fallback=base_reason)
            if result.used_llm and result.text:
                return result.text
            return base_reason
        except Exception:
            return base_reason

    def _get_semantic_cognitive_advice(
        self,
        tool_name: str,
        context: str,
        trace_id: Optional[str] = None,
    ) -> List[Advice]:
        """Retrieve cognitive advice with policy-driven semantic/agentic routing."""
        try:
            from .semantic_retriever import get_semantic_retriever
        except Exception:
            return []

        retriever = get_semantic_retriever()
        if not retriever:
            return []
        insights = dict(getattr(self.cognitive, "insights", {}) or {})
        if not insights:
            return []

        route_start = time.perf_counter()
        policy = self._effective_retrieval_policy(tool_name=tool_name, context=context)
        active_domain = str(policy.get("active_domain") or "general")
        profile_domain = str(policy.get("profile_domain") or "default")
        mode = str(policy.get("mode") or "auto").strip().lower()
        gate_strategy = str(policy.get("gate_strategy") or "minimal").strip().lower()
        semantic_limit = int(policy.get("semantic_limit", 8) or 8)
        max_queries = int(policy.get("max_queries", 2) or 2)
        agentic_query_limit = int(policy.get("agentic_query_limit", 2) or 2)
        agentic_deadline_ms = int(policy.get("agentic_deadline_ms", 700))
        agentic_rate_limit = float(policy.get("agentic_rate_limit", 0.2))
        agentic_rate_window = int(policy.get("agentic_rate_window", 80) or 80)
        fast_path_budget_ms = int(policy.get("fast_path_budget_ms", 250) or 250)
        prefilter_enabled = bool(policy.get("prefilter_enabled", True))
        prefilter_max_insights = int(policy.get("prefilter_max_insights", 500))
        lexical_weight = float(policy.get("lexical_weight", 0.25) or 0.25)
        semantic_context_min = float(policy.get("semantic_context_min", 0.15) or 0.15)
        semantic_lexical_min = float(policy.get("semantic_lexical_min", 0.03) or 0.03)
        semantic_intent_min = float(policy.get("semantic_intent_min", 0.0) or 0.0)
        semantic_strong_override = float(policy.get("semantic_strong_override", 0.90) or 0.90)
        bm25_k1 = float(policy.get("bm25_k1", 1.2) or 1.2)
        bm25_b = float(policy.get("bm25_b", 0.75) or 0.75)
        bm25_mix = float(policy.get("bm25_mix", 0.75) or 0.75)
        intent_coverage_weight = float(policy.get("intent_coverage_weight", 0.0) or 0.0)
        support_boost_weight = float(policy.get("support_boost_weight", 0.0) or 0.0)
        reliability_weight = float(policy.get("reliability_weight", 0.0) or 0.0)
        emotion_cfg = self._load_memory_emotion_cfg()
        emotion_state_enabled = bool(emotion_cfg.get("enabled", True))
        emotion_state_weight = (
            float(emotion_cfg.get("advisory_rerank_weight", MEMORY_EMOTION_DEFAULTS["advisory_rerank_weight"]) or 0.0)
            if emotion_state_enabled
            else 0.0
        )
        emotion_min_state_similarity = float(
            emotion_cfg.get(
                "advisory_min_state_similarity",
                MEMORY_EMOTION_DEFAULTS["advisory_min_state_similarity"],
            )
            or MEMORY_EMOTION_DEFAULTS["advisory_min_state_similarity"]
        )
        active_emotion_state = (
            self._current_emotion_state_for_rerank()
            if emotion_state_enabled and emotion_state_weight > 0.0
            else None
        )

        analysis = self._analyze_query_complexity(tool_name, context)
        high_risk_hits = list(analysis.get("high_risk_hits") or [])
        high_risk = bool(high_risk_hits)
        active_insights = insights
        if prefilter_enabled:
            active_insights = self._prefilter_insights_for_retrieval(
                insights,
                tool_name=tool_name,
                context=context,
                max_items=prefilter_max_insights,
            )

        should_escalate = False
        escalate_reasons: List[str] = []
        primary_results: List[Any] = []

        # LLM area: retrieval_rewrite — enhance query before retrieval
        context = self._llm_area_retrieval_rewrite(context, tool_name)

        primary_start = time.perf_counter()
        try:
            primary_results = list(retriever.retrieve(context, active_insights, limit=semantic_limit))
        except Exception:
            primary_results = []
        primary_elapsed_ms = int((time.perf_counter() - primary_start) * 1000)
        primary_over_budget = primary_elapsed_ms > fast_path_budget_ms
        if primary_over_budget:
            escalate_reasons.append("fast_path_budget_exceeded")

        primary_count = len(primary_results)
        primary_top_score = max((float(getattr(r, "fusion_score", 0.0) or 0.0) for r in primary_results), default=0.0)
        primary_trigger_hit = any(str(getattr(r, "source_type", "") or "") == "trigger" for r in primary_results)

        if mode == "hybrid_agentic":
            should_escalate = True
            escalate_reasons.append("forced_hybrid_agentic_mode")
        elif mode == "embeddings_only":
            should_escalate = False
            escalate_reasons.append("forced_embeddings_only_mode")
        else:
            if bool(policy.get("escalate_on_high_risk", True)) and high_risk:
                should_escalate = True
                escalate_reasons.append("high_risk_terms")
            if bool(policy.get("escalate_on_weak_primary", True)):
                if primary_count < int(policy.get("min_results_no_escalation", 3) or 3):
                    should_escalate = True
                    escalate_reasons.append("weak_primary_count")
                if primary_top_score < float(policy.get("min_top_score_no_escalation", 0.7) or 0.7):
                    should_escalate = True
                    escalate_reasons.append("weak_primary_score")
            if not primary_results:
                should_escalate = True
                escalate_reasons.append("empty_primary")
            if gate_strategy == "extended":
                if analysis.get("requires_agentic"):
                    should_escalate = True
                    escalate_reasons.append("query_complexity")
                if bool(policy.get("escalate_on_trigger", True)) and primary_trigger_hit:
                    should_escalate = True
                    escalate_reasons.append("trigger_signal")

        if should_escalate and mode == "auto":
            if not self._allow_agentic_escalation(rate_limit=agentic_rate_limit, window=agentic_rate_window):
                should_escalate = False
                escalate_reasons.append("agentic_rate_cap")

        # Latency-tail guard: if the primary semantic retrieval already exceeded the fast-path budget,
        # do not add agentic facet queries unless this is a high-risk query.
        if (
            should_escalate
            and mode == "auto"
            and primary_over_budget
            and bool(policy.get("deny_escalation_when_over_budget", True))
            and not high_risk
        ):
            should_escalate = False
            escalate_reasons.append("deny_over_budget")

        facet_queries: List[str] = []
        facet_queries_executed: List[str] = []
        agentic_timed_out = False
        if should_escalate and mode != "embeddings_only":
            facet_queries = self._extract_agentic_queries(context, limit=agentic_query_limit)
            facet_queries = facet_queries[: max(0, max_queries - 1)]
        deadline_ts = (time.perf_counter() + (agentic_deadline_ms / 1000.0)) if should_escalate and agentic_deadline_ms > 0 else None

        merged: Dict[str, Dict[str, Any]] = {}

        def _merge_result(row: Any, query_tag: str) -> None:
            key = row.insight_key or self._generate_advice_id(row.insight_text)
            bucket = merged.get(key)
            if bucket is None:
                bucket = {
                    "row": row,
                    "support_count": 0,
                    "query_tags": set(),
                }
                merged[key] = bucket
            if query_tag not in bucket["query_tags"]:
                bucket["query_tags"].add(query_tag)
                bucket["support_count"] += 1
            prev = bucket.get("row")
            if prev is None or float(getattr(row, "fusion_score", 0.0) or 0.0) > float(getattr(prev, "fusion_score", 0.0) or 0.0):
                bucket["row"] = row

        for r in primary_results:
            _merge_result(r, "primary")

        for q in facet_queries:
            if deadline_ts is not None and time.perf_counter() >= deadline_ts:
                agentic_timed_out = True
                escalate_reasons.append("agentic_deadline")
                break
            try:
                query_results = retriever.retrieve(q, active_insights, limit=semantic_limit)
                facet_queries_executed.append(q)
            except Exception:
                continue
            for r in query_results:
                _merge_result(r, q)

        if not merged:
            self._log_retrieval_route(
                {
                    "tool": tool_name,
                    "trace_id": str(trace_id or "").strip(),
                    "profile_level": policy.get("level"),
                    "profile_name": policy.get("profile"),
                    "active_domain": active_domain,
                    "profile_domain": profile_domain,
                    "domain_profile_enabled": bool(policy.get("domain_profile_enabled", True)),
                    "mode": mode,
                    "route": "empty",
                    "escalated": should_escalate,
                    "primary_count": primary_count,
                    "primary_top_score": round(primary_top_score, 4),
                    "facets_used": len(facet_queries_executed),
                    "facets_planned": len(facet_queries),
                    "agentic_timed_out": agentic_timed_out,
                    "active_insights": len(active_insights),
                    "fast_path_budget_ms": fast_path_budget_ms,
                    "fast_path_elapsed_ms": primary_elapsed_ms,
                    "fast_path_over_budget": primary_over_budget,
                    "complexity_score": analysis.get("score"),
                    "complexity_threshold": analysis.get("threshold"),
                    "reasons": escalate_reasons[:6],
                    "route_elapsed_ms": int((time.perf_counter() - route_start) * 1000),
                }
            )
            self._record_agentic_route(False, agentic_rate_window)
            return []

        used_agentic = bool(facet_queries_executed)
        semantic_source = "semantic-agentic" if used_agentic else "semantic"
        merged_items = list(merged.items())
        lexical_scores = self._hybrid_lexical_scores(
            query=context,
            docs=[str(getattr((bucket.get("row") or None), "insight_text", "") or "") for _, bucket in merged_items],
            bm25_mix=bm25_mix,
            k1=bm25_k1,
            b=bm25_b,
        )
        query_terms = self._intent_terms(context)
        max_support_count = max(
            (int(bucket.get("support_count") or 1) for _, bucket in merged_items),
            default=1,
        )
        rank_features: Dict[str, Dict[str, float]] = {}
        scored: List[Tuple[Any, float]] = []
        emotion_state_match_count = 0
        for idx, (insight_key, bucket) in enumerate(merged_items):
            row = bucket.get("row")
            if row is None:
                continue
            base = float(getattr(row, "fusion_score", 0.0) or 0.0)
            lex = lexical_scores[idx] if idx < len(lexical_scores) else 0.0
            text = str(getattr(row, "insight_text", "") or "")
            if self._should_drop_low_signal_candidate(text):
                continue
            intent_coverage = self._intent_coverage_score(query_terms, text)
            support_count = max(1, int(bucket.get("support_count") or 1))
            support_norm = (support_count - 1) / max(1, max_support_count - 1) if max_support_count > 1 else 0.0
            source_insight = active_insights.get(insight_key)
            reliability = float(getattr(source_insight, "reliability", getattr(row, "outcome_score", 0.5)) or 0.5)
            emotion_similarity = 0.0
            if active_emotion_state and source_insight is not None:
                emotion_similarity = self._emotion_state_similarity(
                    active_emotion_state,
                    self._extract_insight_emotion_state(source_insight),
                )
                if emotion_similarity < emotion_min_state_similarity:
                    emotion_similarity = 0.0
            emotion_boost = emotion_state_weight * emotion_similarity
            if emotion_similarity > 0.0:
                emotion_state_match_count += 1
            rank_features[insight_key] = {
                "lex": lex,
                "intent_coverage": intent_coverage,
                "support_count": float(support_count),
                "support_norm": support_norm,
                "reliability": reliability,
                "emotion_similarity": emotion_similarity,
                "emotion_boost": emotion_boost,
            }
            rerank_score = (
                base
                + (lexical_weight * lex)
                + (intent_coverage_weight * intent_coverage)
                + (support_boost_weight * support_norm)
                + (reliability_weight * reliability)
                + emotion_boost
            )
            scored.append((row, rerank_score))
        ranked = sorted(
            scored,
            key=lambda pair: pair[1],
            reverse=True,
        )
        ranked_rows = [row for row, _ in ranked]

        route_reason = " + ".join(escalate_reasons[:3]) if used_agentic else "primary_semantic_only"
        advice: List[Advice] = []
        filtered_low_match = 0
        filtered_domain_mismatch = 0
        for r in ranked_rows[:semantic_limit]:
            is_social_query = self._is_x_social_query(context)
            if hasattr(self.cognitive, "is_noise_insight") and self.cognitive.is_noise_insight(r.insight_text):
                continue
            insight_key = str(getattr(r, "insight_key", "") or "")
            features = rank_features.get(insight_key, {})
            confidence = max(0.6, float(getattr(r, "fusion_score", 0.0) or 0.0))
            if str(getattr(r, "source_type", "") or "") == "trigger":
                confidence = max(0.8, confidence)
            support_count = int(features.get("support_count", 1.0) or 1.0)
            if support_count > 1:
                confidence = min(0.98, confidence + min(0.12, 0.04 * float(support_count - 1)))
            source = "trigger" if str(getattr(r, "source_type", "") or "") == "trigger" else semantic_source
            if (not is_social_query) and self._is_x_social_insight(str(getattr(r, "insight_text", "") or "")):
                filtered_domain_mismatch += 1
                continue
            semantic_sim = float(getattr(r, "semantic_sim", 0.0) or 0.0)
            trigger_conf = float(getattr(r, "trigger_conf", 0.0) or 0.0)
            insight_text = str(getattr(r, "insight_text", "") or "")
            lexical_match = self._lexical_overlap_score(context, insight_text)
            intent_coverage = float(features.get("intent_coverage", self._intent_coverage_score(query_terms, insight_text)))
            if source != "trigger":
                has_context_match = semantic_sim >= semantic_context_min
                has_lexical_match = lexical_match >= semantic_lexical_min
                has_intent_match = intent_coverage >= semantic_intent_min
                strong_override = semantic_sim >= semantic_strong_override
                if not (has_context_match or has_lexical_match or has_intent_match or strong_override):
                    filtered_low_match += 1
                    continue
            context_match = max(semantic_sim, lexical_match, intent_coverage, trigger_conf)
            if source == "trigger":
                context_match = max(0.7, context_match)
            base_reason = str(getattr(r, "why", "") or "").strip()
            if source == "trigger":
                reason = base_reason or "Trigger match"
            elif used_agentic:
                reason = base_reason or f"Hybrid-agentic route: {route_reason}"
            else:
                reason = base_reason or "Semantic route (embeddings primary)"

            # LLM area: retrieval_explain — annotate result with relevance explanation
            reason = self._llm_area_retrieval_explain(
                reason, r.insight_text, context, context_match,
            )

            # Propagate advisory_quality from cognitive insight if available
            _adv_q = {}
            if r.insight_key and r.insight_key in insights:
                _cog = insights[r.insight_key]
                _adv_q = getattr(_cog, "advisory_quality", None) or {}

            advice.append(
                Advice(
                    advice_id=self._generate_advice_id(
                        r.insight_text, insight_key=r.insight_key, source=source
                    ),
                    insight_key=r.insight_key,
                    text=r.insight_text,
                    confidence=confidence,
                    source=source,
                    context_match=context_match,
                    reason=reason,
                    advisory_quality=_adv_q,
                )
            )

        self._log_retrieval_route(
            {
                "tool": tool_name,
                "trace_id": str(trace_id or "").strip(),
                "profile_level": policy.get("level"),
                "profile_name": policy.get("profile"),
                "active_domain": active_domain,
                "profile_domain": profile_domain,
                "domain_profile_enabled": bool(policy.get("domain_profile_enabled", True)),
                "mode": mode,
                "gate_strategy": gate_strategy,
                "route": semantic_source,
                "escalated": used_agentic,
                "primary_count": primary_count,
                "primary_top_score": round(primary_top_score, 4),
                "returned_count": len(advice),
                "facets_used": len(facet_queries_executed),
                "facets_planned": len(facet_queries),
                "agentic_timed_out": agentic_timed_out,
                "agentic_rate_limit": agentic_rate_limit,
                "agentic_recent_rate": round(self._agentic_recent_rate(agentic_rate_window), 4),
                "active_insights": len(active_insights),
                "lexical_weight": lexical_weight,
                "intent_coverage_weight": intent_coverage_weight,
                "support_boost_weight": support_boost_weight,
                "reliability_weight": reliability_weight,
                "emotion_state_enabled": emotion_state_enabled,
                "emotion_state_weight": emotion_state_weight,
                "emotion_min_state_similarity": emotion_min_state_similarity,
                "emotion_state_active": bool(active_emotion_state),
                "emotion_state_match_count": emotion_state_match_count,
                "semantic_context_min": semantic_context_min,
                "semantic_lexical_min": semantic_lexical_min,
                "semantic_intent_min": semantic_intent_min,
                "semantic_strong_override": semantic_strong_override,
                "max_support_count": max_support_count,
                "filtered_low_match": filtered_low_match,
                "filtered_domain_mismatch": filtered_domain_mismatch,
                "bm25_k1": bm25_k1,
                "bm25_b": bm25_b,
                "bm25_mix": bm25_mix,
                "fast_path_budget_ms": fast_path_budget_ms,
                "fast_path_elapsed_ms": primary_elapsed_ms,
                "fast_path_over_budget": primary_over_budget,
                "complexity_score": analysis.get("score"),
                "complexity_threshold": analysis.get("threshold"),
                "complexity_hits": analysis.get("complexity_hits") or [],
                "high_risk_hits": analysis.get("high_risk_hits") or [],
                "reasons": escalate_reasons[:6],
                "route_elapsed_ms": int((time.perf_counter() - route_start) * 1000),
            }
        )
        self._record_agentic_route(used_agentic, agentic_rate_window)
        return advice

    def _extract_agentic_queries(self, context: str, limit: int = 3) -> List[str]:
        """Extract compact facet queries from context for lightweight agentic retrieval."""
        tokens = []
        for raw in context.lower().replace("/", " ").replace("_", " ").split():
            t = raw.strip(".,:;()[]{}'\"`")
            if len(t) < 4:
                continue
            if t in {"with", "from", "that", "this", "into", "have", "should", "would", "could", "where", "when", "while"}:
                continue
            if not any(ch.isalnum() for ch in t):
                continue
            tokens.append(t)

        seen = set()
        facets: List[str] = []
        for t in tokens:
            if t in seen:
                continue
            seen.add(t)
            facets.append(t)
            if len(facets) >= limit:
                break

        return [f"{t} failure pattern and fix" for t in facets]

    def _is_x_social_query(self, text: str) -> bool:
        body = str(text or "").strip().lower()
        if not body:
            return False
        normalized = re.sub(r"[\s_]+", " ", body)
        return any(marker in normalized for marker in X_SOCIAL_MARKERS)

    def _is_x_social_insight(self, text: str) -> bool:
        body = str(text or "").strip().lower()
        if not body:
            return False
        normalized = re.sub(r"[\s_]+", " ", body)
        return any(marker in normalized for marker in X_SOCIAL_MARKERS) or any(
            token in body
            for token in (
                "multiplier granted",
                "tweet reply",
            )
        )

    def _intent_terms(self, text: str) -> set:
        tokens = {t for t in re.findall(r"[a-z0-9_]+", str(text or "").lower()) if len(t) >= 3}
        return {t for t in tokens if t not in _INTENT_STOPWORDS and not t.isdigit()}

    def _intent_coverage_score(self, query_terms: set, text: str) -> float:
        if not query_terms:
            return 0.0
        doc_terms = self._intent_terms(text)
        if not doc_terms:
            return 0.0
        overlap = len(query_terms & doc_terms)
        return overlap / max(1, len(query_terms))

    def _should_drop_low_signal_candidate(self, text: str) -> bool:
        body = str(text or "").strip()
        if not body:
            return True
        lowered = body.lower()
        if self._is_low_signal_struggle_text(lowered):
            return True
        if self._is_transcript_artifact(body):
            return True
        if self._is_metadata_pattern(body):
            return True
        return any(marker in lowered for marker in _METADATA_TELEMETRY_HINTS)

    def _filter_cross_domain_advice(self, advice_list: List[Advice], context: str) -> List[Advice]:
        """Drop advice that is explicitly marked to another advisory domain."""
        allowed = self._get_allowed_domains("", context)
        if not allowed:
            return list(advice_list)
        if allowed == {"general"}:
            return list(advice_list)
        is_social_context = self._is_x_social_query(context)

        out: List[Advice] = []
        for advice in advice_list:
            adv_q = getattr(advice, "advisory_quality", None) or {}
            if isinstance(adv_q, dict):
                adv_domain = str(adv_q.get("domain", "general") or "general").lower()
            else:
                adv_domain = "general"

            if (not is_social_context) and self._is_x_social_insight(advice.text or ""):
                continue

            if adv_domain in ("", "general"):
                out.append(advice)
                continue
            if adv_domain in allowed:
                out.append(advice)
                continue
            text = (advice.text or "").lower()
            if any(x in text for x in ("troubleshoot", "failure", "regression", "safety", "rollback")):
                # Cross-cutting reliability and safety advisories are often reusable.
                out.append(advice)
        return out

    def _lexical_overlap_score(self, query: str, text: str) -> float:
        """Simple lexical overlap score [0..1] for hybrid rerank."""
        q = {t for t in re.findall(r"[a-z0-9_]+", query.lower()) if len(t) >= 3}
        d = {t for t in re.findall(r"[a-z0-9_]+", text.lower()) if len(t) >= 3}
        if not q or not d:
            return 0.0
        inter = len(q & d)
        union = max(len(q | d), 1)
        return inter / union

    def _bm25_normalized_scores(self, query: str, docs: List[str], k1: float = 1.2, b: float = 0.75) -> List[float]:
        """Compute normalized BM25 scores [0..1] for a query over docs."""
        if not docs:
            return []
        query_tokens = [t for t in re.findall(r"[a-z0-9_]+", query.lower()) if len(t) >= 3]
        if not query_tokens:
            return [0.0 for _ in docs]

        doc_tokens = [[t for t in re.findall(r"[a-z0-9_]+", str(doc).lower()) if len(t) >= 3] for doc in docs]
        n_docs = len(doc_tokens)
        avgdl = sum(len(toks) for toks in doc_tokens) / max(n_docs, 1)
        if avgdl <= 0:
            return [0.0 for _ in docs]

        df: Dict[str, int] = {}
        for toks in doc_tokens:
            for tok in set(toks):
                df[tok] = df.get(tok, 0) + 1

        qtf: Dict[str, int] = {}
        for tok in query_tokens:
            qtf[tok] = qtf.get(tok, 0) + 1

        raw_scores: List[float] = []
        for toks in doc_tokens:
            dl = max(len(toks), 1)
            tf: Dict[str, int] = {}
            for tok in toks:
                tf[tok] = tf.get(tok, 0) + 1
            score = 0.0
            for tok, q_count in qtf.items():
                term_df = df.get(tok, 0)
                if term_df <= 0:
                    continue
                idf = math.log(1.0 + ((n_docs - term_df + 0.5) / (term_df + 0.5)))
                term_tf = tf.get(tok, 0)
                if term_tf <= 0:
                    continue
                denom = term_tf + k1 * (1.0 - b + (b * (dl / avgdl)))
                if denom <= 0:
                    continue
                bm25_term = idf * ((term_tf * (k1 + 1.0)) / denom)
                score += bm25_term * float(q_count)
            raw_scores.append(score)

        max_score = max(raw_scores) if raw_scores else 0.0
        if max_score <= 0:
            return [0.0 for _ in docs]
        return [float(s / max_score) for s in raw_scores]

    def _hybrid_lexical_scores(
        self,
        query: str,
        docs: List[str],
        bm25_mix: float = 0.75,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> List[float]:
        """Blend normalized BM25 and overlap into one lexical signal."""
        if not docs:
            return []
        bm25 = self._bm25_normalized_scores(query=query, docs=docs, k1=k1, b=b)
        overlap = [self._lexical_overlap_score(query, doc) for doc in docs]
        blend = max(0.0, min(1.0, float(bm25_mix)))
        return [(blend * bm) + ((1.0 - blend) * ov) for bm, ov in zip(bm25, overlap)]

    def _get_cognitive_advice_keyword(self, tool_name: str, context: str) -> List[Advice]:
        """Get advice from cognitive insights using keyword matching."""
        advice = []

        # Query insights relevant to this context
        insights = self.cognitive.get_insights_for_context(context, limit=30, with_keys=True)

        # Also get tool-specific insights
        tool_insights = self.cognitive.get_insights_for_context(tool_name, limit=5, with_keys=True)

        # Combine and dedupe
        seen = set()
        for insight_key, insight in insights + tool_insights:
            key = insight_key or insight.insight[:50]
            if key in seen:
                continue
            seen.add(key)

            if insight.reliability < MIN_RELIABILITY_FOR_ADVICE:
                continue
            if hasattr(self.cognitive, "is_noise_insight") and self.cognitive.is_noise_insight(insight.insight):
                continue

            # Calculate context match
            context_match = self._calculate_context_match(insight.context, context)

            # Task #13: Extract reason from evidence
            reason = ""
            if hasattr(insight, 'evidence') and insight.evidence:
                reason = insight.evidence[0][:100] if insight.evidence[0] else ""
            elif hasattr(insight, 'context') and insight.context:
                reason = f"From context: {insight.context[:80]}"

            advice.append(Advice(
                advice_id=self._generate_advice_id(
                    insight.insight, insight_key=insight_key, source="cognitive"
                ),
                insight_key=insight_key,
                text=insight.insight,
                confidence=insight.reliability,
                source="cognitive",
                context_match=context_match,
                reason=reason,
                advisory_quality=getattr(insight, "advisory_quality", None) or {},
            ))

        return advice

    def _get_bank_advice(self, context: str) -> List[Advice]:
        """Get advice from memory banks (project/global)."""
        advice: List[Advice] = []
        try:
            project_key = infer_project_key()
            memories = bank_retrieve(context, project_key=project_key, limit=5)
        except Exception:
            return advice

        for mem in memories:
            text = (mem.get("text") or "").strip()
            if not text:
                continue
            if hasattr(self.cognitive, "is_noise_insight") and self.cognitive.is_noise_insight(text):
                continue
            # Filter metadata patterns like "X: Y = Z" (Task #16)
            if self._is_metadata_pattern(text):
                continue
            if text.startswith("You are Spark Intelligence, observing a live coding session"):
                # Local memory banks sometimes cache bootstrap prompts (policy/system text).
                # These are not operator learnings and should not surface as advice.
                continue
            context_match = self._calculate_context_match(text, context)

            # Add reason from memory metadata (always provide a reason)
            reason = "From memory bank"  # Default fallback
            if mem.get("project_key"):
                reason = f"From project: {mem.get('project_key')}"
            elif mem.get("created_at"):
                created = mem.get('created_at', '')
                if isinstance(created, str):
                    reason = f"Stored: {created[:10]}"

            advice.append(Advice(
                advice_id=self._generate_advice_id(
                    text, insight_key=f"bank:{mem.get('entry_id', '')}", source="bank"
                ),
                insight_key=f"bank:{mem.get('entry_id', '')}",
                text=text[:200],
                confidence=0.65,
                source="bank",
                context_match=context_match,
                reason=reason,
            ))

        return advice

    def _get_mind_advice(self, context: str) -> List[Advice]:
        """Get advice from Mind persistent memory."""
        advice = []

        try:
            if hasattr(self.mind, "_check_mind_health") and not self.mind._check_mind_health():
                return advice
            memories = self.mind.retrieve_relevant(context, limit=5)

            seen_texts: set = set()
            for mem in memories:
                content = mem.get("content", "")
                salience = mem.get("salience", 0.5)
                mem_meta = mem.get("meta")
                if not isinstance(mem_meta, dict):
                    mem_meta = {}
                advisory_quality = mem.get("advisory_quality")
                if not isinstance(advisory_quality, dict):
                    advisory_quality = mem_meta.get("advisory_quality")
                if not isinstance(advisory_quality, dict):
                    advisory_quality = {}
                advisory_readiness = self._coerce_payload_readiness(
                    {
                        "advisory_readiness": mem.get("advisory_readiness"),
                        "advisory_quality": advisory_quality,
                    },
                    fallback=salience or 0.0,
                )

                if salience < MIND_MIN_SALIENCE:
                    continue
                if hasattr(self.cognitive, "is_noise_insight") and self.cognitive.is_noise_insight(content):
                    continue
                # Deduplicate identical or near-identical Mind memories
                dedup_key = content[:150].strip().lower()
                if dedup_key in seen_texts:
                    continue
                seen_texts.add(dedup_key)

                # Task #13: Add reason from Mind metadata
                reason = f"Salience: {salience:.1f}"
                if mem.get("temporal_level"):
                    levels = {1: "immediate", 2: "situational", 3: "seasonal", 4: "identity"}
                    reason = f"{levels.get(mem['temporal_level'], 'memory')} level memory"

                advice.append(Advice(
                    advice_id=self._generate_advice_id(
                        content, insight_key=f"mind:{mem.get('memory_id', 'unknown')[:12]}", source="mind"
                    ),
                    insight_key=f"mind:{mem.get('memory_id', 'unknown')[:12]}",
                    text=content[:200],
                    confidence=salience,
                    source="mind",
                    context_match=0.7,  # Mind already does semantic matching
                    reason=reason,
                    advisory_quality=advisory_quality,
                    advisory_readiness=advisory_readiness,
                ))
        except Exception:
            pass  # Mind unavailable, gracefully skip

        return advice

    def _insight_mentions_tool(self, tool_name: str, *texts: Any) -> bool:
        """Return True when text mentions the tool as a token, not a substring."""
        tool = str(tool_name or "").strip().lower()
        if not tool:
            return False

        token_pattern = re.compile(rf"(?<![a-z0-9]){re.escape(tool)}(?![a-z0-9])")
        normalized_tool = re.sub(r"[_\-\s]+", " ", tool).strip()
        normalized_pattern = None
        if normalized_tool and normalized_tool != tool:
            normalized_pattern = re.compile(
                rf"(?<![a-z0-9]){re.escape(normalized_tool)}(?![a-z0-9])"
            )

        for raw in texts:
            text = str(raw or "").strip().lower()
            if not text:
                continue
            if token_pattern.search(text):
                return True
            if normalized_pattern is not None:
                normalized_text = re.sub(r"[_\-\s]+", " ", text)
                if normalized_pattern.search(normalized_text):
                    return True
        return False

    def _get_tool_specific_advice(self, tool_name: str) -> List[Advice]:
        """Get advice specific to a tool based on past failures."""
        advice = []
        seen_texts = set()

        # Get self-awareness insights about this tool
        for insight in self.cognitive.get_self_awareness_insights():
            insight_text = str(getattr(insight, "insight", "") or "").strip()
            if not insight_text:
                continue
            if self._is_low_signal_struggle_text(insight_text):
                continue
            if hasattr(self.cognitive, "is_noise_insight") and self.cognitive.is_noise_insight(insight_text):
                continue
            reliability = float(getattr(insight, "reliability", 0.0) or 0.0)
            if reliability < MIN_RELIABILITY_FOR_ADVICE:
                continue
            if not self._insight_mentions_tool(
                tool_name,
                insight_text,
                getattr(insight, "context", ""),
            ):
                continue

            dedupe_key = re.sub(r"\s+", " ", insight_text.lower())
            if dedupe_key in seen_texts:
                continue
            seen_texts.add(dedupe_key)

            # Task #13: Add validation count as reason
            reason = (
                f"Validated {insight.times_validated}x"
                if hasattr(insight, "times_validated")
                else ""
            )

            advice.append(Advice(
                advice_id=self._generate_advice_id(
                    f"[Caution] {insight_text}",
                    insight_key=f"tool:{tool_name}",
                    source="self_awareness",
                ),
                insight_key=f"tool:{tool_name}",
                text=f"[Caution] {insight_text}",
                confidence=reliability,
                source="self_awareness",
                context_match=1.0,  # Direct tool match
                reason=reason,
            ))

        return advice

    def _get_opportunity_advice(
        self,
        *,
        tool_name: str,
        context_raw: str,
        task_context: str = "",
    ) -> List[Advice]:
        """Generate Socratic opportunity prompts for user-facing guidance."""
        try:
            from .opportunity_scanner_adapter import generate_user_opportunities
        except Exception:
            return []

        try:
            rows = generate_user_opportunities(
                tool_name=tool_name,
                context=context_raw,
                task_context=task_context,
                session_id="default",
                persist=False,
            )
        except Exception:
            return []
        if not rows:
            return []

        out: List[Advice] = []
        for row in rows:
            question = str(row.get("question") or "").strip()
            next_step = str(row.get("next_step") or "").strip()
            if not question:
                continue
            text = f"[Opportunity] Ask: {question}"
            if next_step:
                text = f"{text} Next: {next_step}"
            out.append(
                Advice(
                    advice_id=self._generate_advice_id(
                        f"opportunity:{tool_name}:{question}",
                        insight_key=f"opportunity:{str(row.get('category') or 'general')}",
                        source="opportunity",
                    ),
                    insight_key=f"opportunity:{str(row.get('category') or 'general')}",
                    text=text,
                    confidence=float(row.get("confidence") or 0.65),
                    source="opportunity",
                    context_match=max(
                        0.55,
                        float(
                            row.get("context_match")
                            or self._calculate_context_match(question, context_raw)
                        ),
                    ),
                    reason=str(
                        row.get("rationale")
                        or "Opportunity scanner: Socratic improvement prompt"
                    ),
                )
            )
        return out

    def _get_chip_advice(self, context: str) -> List[Advice]:
        """Get advice from recent high-quality chip insights."""
        advice: List[Advice] = []
        if not _chips_enabled():
            return advice
        if not CHIP_INSIGHTS_DIR.exists():
            return advice

        candidates: List[Dict[str, Any]] = []
        files = sorted(
            CHIP_INSIGHTS_DIR.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )[:CHIP_ADVICE_MAX_FILES]

        for file_path in files:
            for raw in _tail_jsonl(file_path, CHIP_ADVICE_FILE_TAIL):
                try:
                    row = json.loads(raw)
                except Exception:
                    continue
                quality = (row.get("captured_data") or {}).get("quality_score") or {}
                score = float(quality.get("total", 0.0) or 0.0)
                conf = float(row.get("confidence") or score or 0.0)
                if score < CHIP_ADVICE_MIN_SCORE and conf < MIN_RELIABILITY_FOR_ADVICE:
                    continue
                text = str(
                    row.get("content")
                    or row.get("insight")
                    or row.get("text")
                    or row.get("summary")
                    or ""
                ).strip()
                if not text:
                    continue
                chip_id = str(row.get("chip_id") or file_path.stem).strip()
                if self._is_telemetry_chip_row(chip_id, text):
                    continue
                if hasattr(self.cognitive, "is_noise_insight") and self.cognitive.is_noise_insight(text):
                    continue
                if self._is_metadata_pattern(text):
                    continue
                context_match = self._calculate_context_match(text, context)
                domain_bonus = self._chip_domain_bonus(chip_id, context)
                if context_match < 0.08 and domain_bonus < 0.05:
                    continue
                if context_match < 0.05 and score < (CHIP_ADVICE_MIN_SCORE + 0.1):
                    continue
                candidates.append(
                    {
                        "chip_id": chip_id,
                        "observer": row.get("observer_name") or "observer",
                        "text": text,
                        "score": score,
                        "confidence": conf,
                        "context_match": context_match,
                        "rank": (0.45 * score) + (0.35 * conf) + (0.20 * context_match) + domain_bonus,
                    }
                )

        # Rank and dedupe.
        seen = set()
        candidates.sort(key=lambda x: (x["rank"], x["score"], x["confidence"]), reverse=True)
        for item in candidates:
            key = item["text"][:180].strip().lower()
            if key in seen:
                continue
            seen.add(key)
            context_match = float(item.get("context_match") or 0.0)
            reason = f"{item['chip_id']}/{item['observer']} quality={item['score']:.2f}"
            advice.append(
                Advice(
                    advice_id=self._generate_advice_id(
                        f"[Chip:{item['chip_id']}] {item['text'][:220]}",
                        insight_key=f"chip:{item['chip_id']}:{item['observer']}",
                        source="chip",
                    ),
                    insight_key=f"chip:{item['chip_id']}:{item['observer']}",
                    text=f"[Chip:{item['chip_id']}] {item['text'][:220]}",
                    confidence=min(1.0, max(item["confidence"], item["score"])),
                    source="chip",
                    context_match=context_match,
                    reason=reason,
                )
            )
            if len(advice) >= CHIP_ADVICE_LIMIT * 3:
                break  # Collect up to 3x limit for cross-encoder reranking

        # Cross-encoder rerank chip candidates when reranker is available.
        # Replaces keyword-only ranking with semantic relevance for final selection.
        if len(advice) > CHIP_ADVICE_LIMIT:
            try:
                from .cross_encoder_reranker import get_reranker
                ce = get_reranker()
                if ce:
                    ce_ranked = ce.rerank(context, [a.text for a in advice], top_k=CHIP_ADVICE_LIMIT)
                    advice = [advice[idx] for idx, _sc in ce_ranked]
            except Exception:
                pass

        return advice[:CHIP_ADVICE_LIMIT]

    def _is_telemetry_chip_row(self, chip_id: str, text: str) -> bool:
        chip = str(chip_id or "").strip().lower()
        if chip in CHIP_TELEMETRY_BLOCKLIST:
            return True
        payload = str(text or "").strip().lower()
        if not payload:
            return True
        if any(marker in payload for marker in CHIP_TELEMETRY_MARKERS):
            return True
        return False

    def _chip_domain_bonus(self, chip_id: str, context: str) -> float:
        chip = str(chip_id or "").strip().lower()
        text = str(context or "").strip().lower()
        if not _chips_enabled():
            return 0.0
        if not chip or not text:
            return 0.0

        coding_query = any(t in text for t in ("code", "refactor", "test", "debug", "python", "module"))
        marketing_query = any(t in text for t in ("marketing", "campaign", "conversion", "audience", "brand"))
        memory_query = any(t in text for t in ("memory", "retrieval", "cross-session", "stale", "distillation"))

        coding_chip = any(t in chip for t in ("vibecoding", "api-design", "game_dev"))
        marketing_chip = any(t in chip for t in ("marketing", "market-intel", "biz-ops"))

        bonus = 0.0
        if coding_query and coding_chip:
            bonus += 0.12
        if marketing_query and marketing_chip:
            bonus += 0.12
        if memory_query and coding_chip:
            bonus += 0.06
        return bonus

    def _get_surprise_advice(self, tool_name: str, context: str) -> List[Advice]:
        """Get advice from past surprises (unexpected failures)."""
        advice = []

        try:
            from .aha_tracker import get_aha_tracker
            aha = get_aha_tracker()

            # Get recent surprises related to this tool/context
            for surprise in aha.get_recent_surprises(30):
                if surprise.surprise_type != "unexpected_failure":
                    continue
                if tool_name.lower() not in str(surprise.context).lower():
                    continue
                lesson = surprise.lesson_extracted or "Be careful - this failed unexpectedly before"

                # Add reason with timestamp and context
                reason = f"Failed on {surprise.timestamp[:10] if hasattr(surprise, 'timestamp') else 'recently'}"
                if hasattr(surprise, 'context') and surprise.context:
                    reason += f" in {str(surprise.context)[:30]}"

                advice.append(Advice(
                    advice_id=self._generate_advice_id(
                        f"[Past Failure] {lesson}",
                        insight_key=f"surprise:{surprise.surprise_type}",
                        source="surprise",
                    ),
                    insight_key=f"surprise:{surprise.surprise_type}",
                    text=f"[Past Failure] {lesson}",
                    confidence=0.8,
                    source="surprise",
                    context_match=0.9,
                    reason=reason,
                ))
        except Exception:
            pass  # aha_tracker might not be available

        return advice

    def _get_skill_advice(self, context: str) -> List[Advice]:
        """Get hints from relevant skills."""
        advice: List[Advice] = []
        try:
            from .skills_router import recommend_skills
            skills = recommend_skills(context, limit=3)
        except Exception:
            return advice

        for s in skills:
            sid = s.get("skill_id") or s.get("name") or "unknown-skill"
            desc = (s.get("description") or "").strip()
            if desc:
                text = f"Consider skill [{sid}]: {desc[:120]}"
            else:
                text = f"Consider skill [{sid}]"

            # Add reason from skill relevance
            reason = f"Matched: {s.get('match_reason', 'context keywords')}" if s.get('match_reason') else "Relevant to context"

            advice.append(Advice(
                advice_id=self._generate_advice_id(text, insight_key=f"skill:{sid}", source="skill"),
                insight_key=f"skill:{sid}",
                text=text,
                confidence=0.6,
                source="skill",
                context_match=0.7,
                reason=reason,
            ))

        return advice

    def _load_recent_eidos_priority_map(self) -> Dict[str, float]:
        """Load priority_score from recent EIDOS distillations, keyed by action text.

        Returns a dict mapping lowercased action text → priority_score.
        Lightweight: reads only the last 2 KB of the JSONL file.
        """
        cache_attr = "_eidos_priority_cache"
        cache_ts_attr = "_eidos_priority_cache_ts"
        now = time.time()
        # Cache for 60 s to avoid re-reading on every call
        if (
            hasattr(self, cache_attr)
            and hasattr(self, cache_ts_attr)
            and (now - getattr(self, cache_ts_attr, 0.0)) < 60.0
        ):
            return getattr(self, cache_attr) or {}

        result: Dict[str, float] = {}
        try:
            eidos_file = Path.home() / ".spark" / "eidos_distillations.jsonl"
            if not eidos_file.exists():
                return result
            raw = eidos_file.read_bytes()
            # Only parse the tail (last ~4 KB) for speed
            tail = raw[-4096:] if len(raw) > 4096 else raw
            for line in tail.decode("utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                for it in (entry.get("insights") or []):
                    if not isinstance(it, dict):
                        continue
                    ps = it.get("priority_score")
                    action = str(it.get("action") or "").strip().lower()
                    if action and ps is not None:
                        try:
                            result[action] = float(ps)
                        except Exception:
                            pass
        except Exception:
            pass
        setattr(self, cache_attr, result)
        setattr(self, cache_ts_attr, now)
        return result

    def _get_eidos_advice(self, tool_name: str, context: str) -> List[Advice]:
        """Get advice from EIDOS distillations (extracted rules from patterns)."""
        advice = []

        if not HAS_EIDOS:
            return advice

        try:
            retriever = get_retriever()

            # Build intent from tool and context
            intent = f"{tool_name} {context[:80]}"

            # Get distillations for this intent (includes policies, heuristics, anti-patterns)
            distillations = retriever.retrieve_for_intent(intent)

            # Load recent emotional priority metadata for bridging
            priority_map = self._load_recent_eidos_priority_map()

            for d in distillations[:5]:
                # Determine advice type label based on distillation type
                type_label = d.type.value.upper() if hasattr(d.type, 'value') else str(d.type)
                advisory_quality = {}
                base_statement = (getattr(d, "refined_statement", "") or d.statement or "").strip()
                stored_quality = getattr(d, "advisory_quality", None) or {}
                advice_text = base_statement or d.statement

                # Prefer persisted advisory quality from EIDOS store.
                if isinstance(stored_quality, dict) and stored_quality:
                    if stored_quality.get("suppressed"):
                        continue
                    if float(stored_quality.get("unified_score", 0.0) or 0.0) < 0.35:
                        continue
                    advisory_quality = stored_quality
                    advice_text = str(stored_quality.get("advisory_text") or advice_text or d.statement)
                else:
                    # Fallback for legacy rows without persisted quality metadata.
                    try:
                        aq = _transform_distillation(advice_text or d.statement, source="eidos")
                        if aq.suppressed:
                            continue  # Skip distillations that fail advisory quality
                        advice_text = aq.advisory_text or advice_text or d.statement
                        advisory_quality = aq.to_dict()
                    except Exception:
                        advice_text = advice_text or d.statement

                # Add reason from distillation confidence and proven effectiveness
                reason = f"Confidence: {d.confidence:.0%}"
                if d.times_used > 0:
                    reason += f", effective {d.effectiveness:.0%} ({d.times_helped}/{d.times_used})"
                if d.validation_count > 0:
                    reason += f", {d.validation_count} validations"

                # Compute real context match instead of hardcoding 0.85
                eidos_match = self._calculate_context_match(advice_text, context)

                # Bridge emotional priority: try exact match on action text,
                # else try substring match on statement
                ep = 0.0
                stmt_lower = (advice_text or d.statement or "").strip().lower()
                if stmt_lower in priority_map:
                    ep = priority_map[stmt_lower]
                else:
                    for action_key, ps in priority_map.items():
                        if action_key and action_key in stmt_lower:
                            ep = max(ep, ps)
                            break

                # Blend confidence with proven effectiveness:
                # Unknown (eff=0.5) → *0.85, Proven (eff=1.0) → *1.0, Failing (eff=0.0) → *0.7
                blended_conf = min(1.0, d.confidence * (0.7 + d.effectiveness * 0.3))

                advice.append(Advice(
                    advice_id=self._generate_advice_id(
                        f"[EIDOS {type_label}] {advice_text}",
                        insight_key=f"eidos:{d.type.value}:{d.distillation_id[:8]}",
                        source="eidos",
                    ),
                    insight_key=f"eidos:{d.type.value}:{d.distillation_id[:8]}",
                    text=f"[EIDOS {type_label}] {advice_text}",
                    confidence=blended_conf,
                    source="eidos",
                    context_match=eidos_match,
                    reason=reason,
                    emotional_priority=ep,
                    advisory_quality=advisory_quality,
                ))
                # Usage tracking now handled by meta_ralph outcome feedback loop
                # (see _apply_outcome_to_cognitive in meta_ralph.py)

        except Exception:
            pass  # Don't break advice flow if EIDOS retrieval fails

        return advice

    def _get_niche_advice(self, tool_name: str, context: str) -> List[Advice]:
        """Get niche intelligence advice.

        Activates for X user profile tools or engagement contexts.
        Surfaces active opportunities and relationship context.
        """
        if not _premium_tools_enabled():
            return []
        advice: List[Advice] = []

        niche_signals = [
            "profile", "user", "follower", "following", "engage",
            "x-twitter", "community", "niche", "network", "relationship",
        ]
        if not any(s in context for s in niche_signals):
            return advice

        try:
            from lib.niche_mapper import get_niche_mapper

            mapper = get_niche_mapper()

            # Surface active high-urgency opportunities
            opps = mapper.get_active_opportunities(min_urgency=4)
            for opp in opps[:2]:
                text = (
                    f"[NicheNet] Opportunity: engage @{opp.target} - "
                    f"{opp.reason} (urgency {opp.urgency}/5, "
                    f"tone: {opp.suggested_tone})"
                )
                advice.append(Advice(
                    advice_id=self._generate_advice_id(
                        text, insight_key=f"niche:opp:{opp.target}", source="niche"
                    ),
                    insight_key=f"niche:opp:{opp.target}",
                    text=text,
                    confidence=min(0.8, opp.urgency * 0.15),
                    source="niche",
                    context_match=0.7,
                    reason=opp.reason,
                ))

            # Surface warm relationship context for relevant handles
            for handle in list(mapper.accounts.keys())[:100]:
                if handle in context:
                    acct = mapper.accounts[handle]
                    if acct.warmth in ("warm", "hot", "ally"):
                        text = (
                            f"[NicheNet] @{handle} is {acct.warmth} "
                            f"({acct.interaction_count} interactions, "
                            f"topics: {', '.join(acct.topics[:3])})"
                        )
                        advice.append(Advice(
                            advice_id=self._generate_advice_id(
                                text, insight_key=f"niche:warmth:{handle}", source="niche"
                            ),
                            insight_key=f"niche:warmth:{handle}",
                            text=text,
                            confidence=0.75,
                            source="niche",
                            context_match=0.9,
                            reason=f"Relationship: {acct.warmth}",
                        ))
                        break  # Only one relationship hint per call

        except Exception:
            pass

        return advice

    def _get_engagement_advice(self, tool_name: str, context: str) -> List[Advice]:
        """Get engagement pulse advice.

        Activates when posting tweets or checking engagement.
        Surfaces prediction accuracy and recent surprises.
        """
        if not _premium_tools_enabled():
            return []
        advice: List[Advice] = []

        engagement_signals = [
            "tweet", "post", "engagement", "likes", "performance",
            "x-twitter", "viral", "thread",
        ]
        if not any(s in context for s in engagement_signals):
            return advice

        try:
            from lib.engagement_tracker import get_engagement_tracker

            tracker = get_engagement_tracker()
            stats = tracker.get_stats()

            # Surface prediction accuracy if we have data
            accuracy = stats.get("prediction_accuracy", {})
            if accuracy.get("total_predictions", 0) >= 5:
                acc_pct = accuracy.get("accuracy", 0)
                text = (
                    f"[Pulse] Engagement prediction accuracy: {acc_pct}% "
                    f"(avg ratio: {accuracy.get('avg_ratio', 0)}x)"
                )
                advice.append(Advice(
                    advice_id=self._generate_advice_id(
                        text, insight_key="engagement:accuracy", source="engagement"
                    ),
                    insight_key="engagement:accuracy",
                    text=text,
                    confidence=0.7,
                    source="engagement",
                    context_match=0.7,
                    reason=f"Based on {accuracy.get('total_predictions', 0)} predictions",
                ))

            # Surface recent surprises
            surprises = [
                t for t in tracker.tracked.values() if t.surprise_detected
            ]
            for s in surprises[-2:]:
                text = (
                    f"[Pulse] Recent {s.surprise_type}: "
                    f"'{s.content_preview[:60]}' ({s.surprise_ratio}x prediction)"
                )
                advice.append(Advice(
                    advice_id=self._generate_advice_id(
                        text,
                        insight_key=f"engagement:surprise:{s.tweet_id[:8]}",
                        source="engagement",
                    ),
                    insight_key=f"engagement:surprise:{s.tweet_id[:8]}",
                    text=text,
                    confidence=0.65,
                    source="engagement",
                    context_match=0.6,
                    reason=f"Surprise ratio: {s.surprise_ratio}x",
                ))

        except Exception:
            pass

        return advice

    def _get_convo_advice(self, tool_name: str, context: str) -> List[Advice]:
        """Get conversation intelligence advice from ConvoIQ.

        Only activates for X/Twitter reply tools or when context mentions
        replies, conversations, or engagement.
        """
        if not _premium_tools_enabled():
            return []
        advice: List[Advice] = []

        # Only trigger for relevant contexts
        convo_signals = [
            "reply", "respond", "tweet", "thread", "engagement",
            "x-twitter", "conversation", "quote", "mention",
        ]
        if not any(s in context for s in convo_signals):
            return advice

        try:
            from lib.convo_analyzer import get_convo_analyzer

            analyzer = get_convo_analyzer()
            analyzer.get_stats()

            # Surface top DNA patterns as advice
            for dna_key, dna in list(analyzer.dna_patterns.items())[:3]:
                if dna.engagement_score >= 5.0 and dna.times_seen >= 2:
                    text = (
                        f"[ConvoIQ] {dna.hook_type} hooks with {dna.tone} tone "
                        f"work well (engagement {dna.engagement_score:.0f}/10, "
                        f"seen {dna.times_seen}x)"
                    )
                    ctx_match = self._calculate_context_match(
                        f"{dna.hook_type} {dna.tone} {dna.pattern_type}",
                        context,
                    )
                    advice.append(Advice(
                        advice_id=self._generate_advice_id(
                            text, insight_key=f"convo:dna:{dna_key}", source="convo"
                        ),
                        insight_key=f"convo:dna:{dna_key}",
                        text=text,
                        confidence=min(0.9, 0.5 + dna.times_seen * 0.1),
                        source="convo",
                        context_match=ctx_match,
                        reason=f"DNA pattern validated {dna.times_seen}x",
                    ))

            # If replying to someone, recommend best hook
            if "reply" in context or "respond" in context:
                # Extract parent text hint from context if available
                rec = analyzer.get_best_hook(context[:200])
                text = (
                    f"[ConvoIQ] Try {rec.hook_type} hook with {rec.tone} tone: "
                    f"{rec.reasoning}"
                )
                advice.append(Advice(
                    advice_id=self._generate_advice_id(
                        text, insight_key=f"convo:hook:{rec.hook_type}", source="convo"
                    ),
                    insight_key=f"convo:hook:{rec.hook_type}",
                    text=text,
                    confidence=rec.confidence,
                    source="convo",
                    context_match=0.8,
                    reason=rec.reasoning,
                ))

        except Exception:
            pass  # Don't break advice flow if ConvoIQ isn't available

        return advice

    def _calculate_context_match(self, insight_context: str, current_context: str) -> float:
        """Calculate how well an insight's context matches current context."""
        if not insight_context or not current_context:
            return 0.5

        insight_words = set(insight_context.lower().split())
        current_words = set(current_context.lower().split())

        if not insight_words:
            return 0.5

        overlap = len(insight_words & current_words)
        return min(1.0, overlap / max(len(insight_words), 1) + 0.3)

    def _replay_extract_tool(self, record: Any) -> str:
        """Best-effort tool extraction for replay counterfactuals."""
        learning_id = str(getattr(record, "learning_id", "") or "").strip()
        if learning_id.lower().startswith("tool:"):
            return learning_id[5:].strip().lower()

        evidence = str(getattr(record, "outcome_evidence", "") or "").strip()
        if evidence:
            for token in evidence.split():
                if token.startswith("tool="):
                    return token.split("=", 1)[1].strip().lower()

        content = str(getattr(record, "learning_content", "") or "").strip()
        if content.lower().startswith("tool:"):
            return content[5:].strip().lower()
        return ""

    def _replay_outcome_ts(self, record: Any) -> Optional[float]:
        ts = _parse_iso_ts(getattr(record, "outcome_at", None))
        if ts is not None:
            return ts
        return _parse_iso_ts(getattr(record, "retrieved_at", None))

    def _is_replay_strict(self, record: Any) -> bool:
        retrieve_trace = str(getattr(record, "trace_id", "") or "").strip()
        outcome_trace = str(getattr(record, "outcome_trace_id", "") or "").strip()
        if not (retrieve_trace and outcome_trace and retrieve_trace == outcome_trace):
            return False

        latency = getattr(record, "outcome_latency_s", None)
        try:
            latency_s = float(latency)
        except Exception:
            started = _parse_iso_ts(getattr(record, "retrieved_at", None))
            ended = _parse_iso_ts(getattr(record, "outcome_at", None))
            if started is None or ended is None:
                return False
            latency_s = float(ended - started)
        if latency_s < 0:
            return False
        return latency_s <= max(0, int(REPLAY_STRICT_WINDOW_S))

    def _replay_preview_text(self, text: str, limit: int = 96) -> str:
        body = re.sub(r"^\[[^\]]+\]\s*", "", str(text or "").strip())
        body = re.sub(r"\s+", " ", body)
        if len(body) <= limit:
            return body
        return body[: max(20, limit - 3)].rstrip() + "..."

    def _get_replay_counterfactual_advice(
        self,
        *,
        tool_name: str,
        context_raw: str,
        existing_advice: List[Advice],
    ) -> List[Advice]:
        """Generate one replay advisory backed by strict historical outcomes."""
        if not REPLAY_ADVISORY_ENABLED:
            return []

        tool = str(tool_name or "").strip().lower()
        if not tool:
            return []

        try:
            from .meta_ralph import get_meta_ralph

            ralph = get_meta_ralph()
            records = list((getattr(ralph, "outcome_records", {}) or {}).values())
        except Exception:
            return []
        if not records:
            return []

        now = time.time()
        window = records[-max(1, int(REPLAY_MAX_RECORDS)) :]
        buckets: Dict[str, Dict[str, Any]] = {}

        for rec in window:
            if not bool(getattr(rec, "acted_on", False)):
                continue
            outcome = str(getattr(rec, "outcome", "") or "").strip().lower()
            if outcome not in {"good", "bad"}:
                continue
            if self._replay_extract_tool(rec) != tool:
                continue

            outcome_ts = self._replay_outcome_ts(rec)
            if outcome_ts is not None and (now - outcome_ts) > max(0, int(REPLAY_MAX_AGE_S)):
                continue

            insight_key = str(getattr(rec, "insight_key", "") or "").strip()
            learning_id = str(getattr(rec, "learning_id", "") or "").strip()
            bucket_key = insight_key or learning_id
            if not bucket_key:
                continue

            content = str(getattr(rec, "learning_content", "") or "").strip()
            if self._is_low_signal_struggle_text(content):
                continue
            if self._is_transcript_artifact(content):
                continue

            row = buckets.setdefault(
                bucket_key,
                {
                    "key": bucket_key,
                    "insight_key": insight_key,
                    "text": "",
                    "good": 0,
                    "bad": 0,
                    "strict_good": 0,
                    "strict_bad": 0,
                    "strict_total": 0,
                    "context_match": 0.0,
                    "last_ts": 0.0,
                },
            )
            if outcome == "good":
                row["good"] += 1
            else:
                row["bad"] += 1

            strict_ok = self._is_replay_strict(rec)
            if strict_ok:
                row["strict_total"] += 1
                if outcome == "good":
                    row["strict_good"] += 1
                else:
                    row["strict_bad"] += 1

            if content:
                row["context_match"] = max(
                    float(row.get("context_match") or 0.0),
                    self._calculate_context_match(content, context_raw),
                )
                if not row.get("text"):
                    row["text"] = content

            if outcome_ts is not None and outcome_ts > float(row.get("last_ts") or 0.0):
                row["last_ts"] = outcome_ts

        min_strict = max(1, int(REPLAY_MIN_STRICT_SAMPLES))
        candidates = [r for r in buckets.values() if int(r.get("strict_total") or 0) >= min_strict]
        if len(candidates) < 2:
            return []

        def _strict_rate(row: Dict[str, Any]) -> float:
            total = max(int(row.get("strict_total") or 0), 1)
            return float(row.get("strict_good") or 0) / total

        candidates.sort(
            key=lambda r: (
                _strict_rate(r),
                int(r.get("strict_total") or 0),
                float(r.get("context_match") or 0.0),
                float(r.get("last_ts") or 0.0),
            ),
            reverse=True,
        )
        best = candidates[0]

        baseline = None
        for adv in existing_advice:
            key = str(getattr(adv, "insight_key", "") or "").strip()
            if key and key in buckets:
                row = buckets[key]
                if int(row.get("strict_total") or 0) >= min_strict:
                    baseline = row
                    break

        if baseline is None:
            alternatives = [r for r in candidates if r.get("key") != best.get("key")]
            if not alternatives:
                return []
            baseline = min(
                alternatives,
                key=lambda r: (
                    _strict_rate(r),
                    int(r.get("strict_total") or 0),
                    -float(r.get("context_match") or 0.0),
                ),
            )

        if baseline.get("key") == best.get("key"):
            return []

        best_rate = _strict_rate(best)
        base_rate = _strict_rate(baseline)
        delta = best_rate - base_rate
        if delta < float(REPLAY_MIN_IMPROVEMENT_DELTA):
            return []

        if (
            float(best.get("context_match") or 0.0) < float(REPLAY_MIN_CONTEXT_MATCH)
            and float(baseline.get("context_match") or 0.0) < float(REPLAY_MIN_CONTEXT_MATCH)
        ):
            return []

        best_n = int(best.get("strict_total") or 0)
        base_n = int(baseline.get("strict_total") or 0)
        best_preview = self._replay_preview_text(str(best.get("text") or best.get("key") or "alternative"))
        base_preview = self._replay_preview_text(str(baseline.get("text") or baseline.get("key") or "current pattern"))

        last_ts = float(best.get("last_ts") or 0.0)
        if last_ts > 0:
            try:
                last_seen = datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d")
            except Exception:
                last_seen = "recently"
        else:
            last_seen = "recently"

        confidence = min(
            0.95,
            max(
                0.62,
                0.45
                + (best_rate * 0.30)
                + (min(best_n, 12) / 80.0)
                + (min(max(delta, 0.0), 0.4) * 0.40),
            ),
        )
        context_match = max(0.55, float(best.get("context_match") or 0.0))
        alt_key = str(best.get("key") or "")
        base_key = str(baseline.get("key") or "")
        replay_key = f"replay:{tool}:{hashlib.md5((base_key + '->' + alt_key).encode()).hexdigest()[:12]}"

        text = (
            f"[Replay] Similar {tool_name} pattern: '{base_preview}' worked {base_rate:.0%} "
            f"({base_n} strict cases). Alternative '{best_preview}' worked {best_rate:.0%} "
            f"({best_n}). Try the alternative?"
        )
        reason = f"Strict outcome replay; last seen {last_seen}; delta +{delta:.0%}."

        return [
            Advice(
                advice_id=self._generate_advice_id(
                    f"{tool}:{base_key}->{alt_key}",
                    insight_key=replay_key,
                    source="replay",
                ),
                insight_key=replay_key,
                text=text,
                confidence=confidence,
                source="replay",
                context_match=context_match,
                reason=reason,
            )
        ]

    def _is_metadata_pattern(self, text: str) -> bool:
        """Detect metadata patterns that aren't actionable advice.

        Filters patterns like:
        - "User communication style: detail_level = concise"
        - "X: Y = Z" key-value metadata
        - Incomplete sentence fragments
        """
        import re

        text_stripped = text.strip()

        # Pattern 1: Key-value metadata "X: Y = Z" or "X: Y"
        # e.g., "User communication style: detail_level = concise"
        if re.match(r'^[A-Za-z\s]+:\s*[a-z_]+\s*=\s*.+$', text_stripped):
            return True

        # Pattern 2: Simple "Label: value" metadata without actionable content
        # e.g., "Principle: it is according to..."
        if re.match(r'^(Principle|Style|Setting|Config|Meta|Mode|Level|Type):\s*', text_stripped, re.I):
            # Only filter if it doesn't contain action verbs
            action_verbs = ['use', 'avoid', 'check', 'verify', 'ensure', 'always',
                           'never', 'remember', "don't", 'prefer', 'try', 'run']
            if not any(v in text_stripped.lower() for v in action_verbs):
                return True

        # Pattern 3: Underscore-style metadata keys
        # e.g., "detail_level", "code_style", "response_format"
        if re.match(r'^[a-z_]+\s*[:=]\s*.+$', text_stripped):
            return True

        # Pattern 4: Very short fragments (likely metadata, not advice)
        if len(text_stripped) < 15 and ':' in text_stripped:
            return True

        # Pattern 5: Incomplete sentences ending with conjunctions/prepositions
        incomplete_endings = [' that', ' the', ' a', ' an', ' of', ' to', ' for',
                             ' with', ' and', ' or', ' but', ' in', ' on', ' we']
        if any(text_stripped.lower().endswith(e) for e in incomplete_endings):
            return True

        return False

    def _score_actionability(self, text: str) -> float:
        """Score actionability on 4 dimensions (0.0 to 1.0).

        Dimensions:
            has_directive   - Contains imperative verb (use, avoid, check, ensure, prefer)
            has_condition   - Contains when/if/before/after trigger
            has_specificity - References concrete tools, files, patterns, or tech
            not_observation - NOT a passive observation, quote, log, or code snippet

        Items scoring below ACTIONABILITY_GATE (0.3) are functionally dropped
        by the rank_score multiplier (0.5 + score), giving them 0.5x-0.8x weight.
        """
        text_lower = text.lower()
        text_stripped = text.strip()

        # ----- Dimension 1: Observation detection (hard disqualifiers) -----
        not_observation = 1.0

        # Retweet / X research
        if text_stripped.startswith("RT @") or re.search(r"\(eng:\d+\)", text):
            not_observation = 0.0
        # DEPTH training log
        elif text_stripped.startswith("[DEPTH:") and "reasoning:" in text_lower:
            not_observation = 0.1
        elif re.search(r"Strong (?:Socratic|CONNECTIONS|PARADOX|CONSCIOUSNESS|VOID|IDENTITY|DECOMPOSE|OPTIMIZE|SIMPLIFY)", text):
            not_observation = 0.1
        # Verbatim user quotes
        elif re.match(r"^(User prefers |Now, can we|Can you now|lets make sure|by the way|instead of this|I think we|I'd say)", text):
            not_observation = 0.15
        # Code snippet (>50% non-alpha chars in first 100 chars)
        elif len(text_stripped) > 20:
            sample = text_stripped[:100]
            alpha_ratio = sum(1 for c in sample if c.isalpha()) / max(1, len(sample))
            if alpha_ratio < 0.4:
                not_observation = 0.1
        # X social tags
        if re.match(r"^\[(vibe_coding|bittensor|ai agents|X Strategy)\]", text):
            not_observation = 0.1
        # Ship it / launch artifact
        if text_stripped.startswith("Ship it:"):
            not_observation = 0.2
        # Chip observation (not directive)
        if re.match(r"^\[Chip:\w+\].*(?:snapshot|mood|cultural_mood|engagement_snapshot)", text):
            not_observation = 0.2

        # ----- Dimension 2: Has directive verb -----
        has_directive = 0.0
        directive_verbs = [
            'use ', 'avoid ', 'check ', 'verify ', 'ensure ', 'always ',
            'never ', 'remember ', "don't ", 'prefer ', 'try ', 'run ',
            'validate ', 'test ', 'confirm ', 'apply ', 'set ', 'configure ',
            'wrap ', 'handle ', 'catch ', 'return ', 'raise ', 'log ',
        ]
        if any(text_lower.startswith(v) or f" {v}" in text_lower for v in directive_verbs):
            has_directive = 0.8
        # EIDOS/Caution tags = pre-validated directives
        if text_stripped.startswith('[EIDOS') or text_stripped.startswith('[Caution]'):
            has_directive = max(has_directive, 0.9)
        # "Applied advisory:" prefix = actionable
        if text_stripped.startswith("Applied advisory:"):
            has_directive = max(has_directive, 0.6)

        # ----- Dimension 3: Has condition/trigger -----
        has_condition = 0.0
        conditional_patterns = ['when ', 'if ', 'before ', 'after ', 'instead of ', 'unless ']
        if any(p in text_lower for p in conditional_patterns):
            has_condition = 0.7

        # ----- Dimension 4: Has specificity -----
        has_specificity = 0.0
        specificity_markers = [
            r'\b\w+\.py\b',           # Python file reference
            r'\b\w+\.json\b',         # JSON file reference
            r'\b\w+\.yaml\b',         # YAML file reference
            r'\b(?:Edit|Write|Bash|Read|Grep|Glob)\b',  # Tool names
            r'\b(?:pytest|git|pip|npm|docker)\b',  # CLI tools
            r'\b(?:auth|token|jwt|session|cookie)\b',  # Domain terms
            r'\b(?:port|endpoint|API|URL|HTTP)\b',  # Infra terms
        ]
        specificity_hits = sum(1 for pat in specificity_markers if re.search(pat, text, re.IGNORECASE))
        has_specificity = min(1.0, specificity_hits * 0.35)

        # ----- Final score: weighted average -----
        score = (
            not_observation * 0.40 +
            has_directive * 0.30 +
            has_condition * 0.15 +
            has_specificity * 0.15
        )

        return max(0.05, min(1.0, score))

    def _is_low_signal_struggle_text(self, text: str) -> bool:
        sample = str(text or "").strip().lower()
        if not sample:
            return False
        normalized = re.sub(r"^\[[^\]]+\]\s*", "", sample)
        if any(rx.search(normalized) for rx in _LOW_SIGNAL_STRUGGLE_PATTERNS):
            return True
        if "i struggle with" not in normalized:
            return False
        noisy_tokens = (
            "_error",
            "mcp__",
            "command_not_found",
            "permission_denied",
            "file_not_found",
            "syntax_error",
            "fails with other",
        )
        return any(tok in normalized for tok in noisy_tokens)

    def _is_transcript_artifact(self, text: str) -> bool:
        sample = str(text or "").strip()
        if not sample:
            return False
        lowered = sample.lower()
        if any(rx.match(sample) for rx in _TRANSCRIPT_ARTIFACT_PATTERNS):
            return True
        if lowered.startswith("from lib.") and " import " in lowered:
            return True
        return False

    def _should_drop_advice(self, advice: Advice, tool_name: str = "") -> bool:
        text = str(getattr(advice, "text", "") or "").strip()
        adv_q = getattr(advice, "advisory_quality", None) or {}
        if not text:
            record_quarantine_item(
                source=str(getattr(advice, "source", "unknown")),
                stage="advisor_should_drop",
                reason="empty_text",
                text=text,
                advisory_quality=getattr(advice, "advisory_quality", None),
                advisory_readiness=getattr(advice, "advisory_readiness", None),
                extras={"tool_name": tool_name},
            )
            return True
        if self._is_inventory_style_text(text):
            record_quarantine_item(
                source=str(getattr(advice, "source", "unknown")),
                stage="advisor_should_drop",
                reason="inventory_style",
                text=text,
                advisory_quality=adv_q if isinstance(adv_q, dict) else None,
                advisory_readiness=getattr(advice, "advisory_readiness", None),
                extras={"tool_name": tool_name},
            )
            return True
        # Drop advice suppressed by distillation transformer
        if isinstance(adv_q, dict) and adv_q.get("suppressed"):
            record_quarantine_item(
                source=str(getattr(advice, "source", "unknown")),
                stage="advisor_should_drop",
                reason=f"transformer:{adv_q.get('suppression_reason') or 'suppressed'}",
                text=text,
                advisory_quality=adv_q,
                advisory_readiness=getattr(advice, "advisory_readiness", None),
                extras={"tool_name": tool_name},
            )
            return True
        if self._is_low_signal_struggle_text(text):
            record_quarantine_item(
                source=str(getattr(advice, "source", "unknown")),
                stage="advisor_should_drop",
                reason="low_signal_struggle",
                text=text,
                advisory_quality=adv_q if isinstance(adv_q, dict) else None,
                advisory_readiness=getattr(advice, "advisory_readiness", None),
                extras={"tool_name": tool_name},
            )
            return True
        if self._is_transcript_artifact(text):
            record_quarantine_item(
                source=str(getattr(advice, "source", "unknown")),
                stage="advisor_should_drop",
                reason="transcript_artifact",
                text=text,
                advisory_quality=adv_q if isinstance(adv_q, dict) else None,
                advisory_readiness=getattr(advice, "advisory_readiness", None),
                extras={"tool_name": tool_name},
            )
            return True
        if (
            advice.source in {"bank", "mind", "cognitive", "semantic", "semantic-hybrid", "semantic-agentic"}
            and self._is_metadata_pattern(text)
        ):
            record_quarantine_item(
                source=str(getattr(advice, "source", "unknown")),
                stage="advisor_should_drop",
                reason="metadata_pattern",
                text=text,
                advisory_quality=adv_q if isinstance(adv_q, dict) else None,
                advisory_readiness=getattr(advice, "advisory_readiness", None),
                extras={"tool_name": tool_name},
            )
            return True
        text_lower = text.lower()
        if any(
            token in text_lower
            for token in (
                "read before edit",
                "read a file before edit",
                "read file before edit",
                "before edit to verify",
            )
        ):
            if str(tool_name or "").strip() not in {"Read", "Edit", "Write"}:
                record_quarantine_item(
                    source=str(getattr(advice, "source", "unknown")),
                    stage="advisor_should_drop",
                    reason="context_read_before_edit",
                    text=text,
                    advisory_quality=adv_q if isinstance(adv_q, dict) else None,
                    advisory_readiness=getattr(advice, "advisory_readiness", None),
                    extras={"tool_name": tool_name},
                )
                return True
        if text_lower.startswith("constraint:") and "one state" in text_lower:
            if str(tool_name or "").strip() not in {"Task", "EnterPlanMode", "ExitPlanMode"}:
                record_quarantine_item(
                    source=str(getattr(advice, "source", "unknown")),
                    stage="advisor_should_drop",
                    reason="context_constraint_state",
                    text=text,
                    advisory_quality=adv_q if isinstance(adv_q, dict) else None,
                advisory_readiness=getattr(advice, "advisory_readiness", None),
                extras={"tool_name": tool_name},
            )
            return True
        return False

    def _is_inventory_style_text(self, text: str) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False
        return any(
            marker in normalized
            for marker in (
                "learned insights (from past sessions):",
                "you are spark intelligence, observing a live coding session",
                "system inventory (what actually exists",
                "system inventory (what actually exists — do not reference anything outside this list)",
                "\n- services:",
                "cycle summary:",
                "service inventory",
                "services:",
                "<task-notification",
                "<task-id>",
                "<status>",
                "<summary>",
            )
        )

    # Source quality tiers — normalized 0-1 for additive scoring
    _SOURCE_QUALITY = {
        "eidos": 0.90,            # EIDOS distillations are validated patterns
        "replay": 0.85,           # Strict outcome-backed counterfactual replay
        "self_awareness": 0.80,   # Tool-specific cautions from past failures
        "trigger": 0.75,          # Explicit trigger rules
        "opportunity": 0.72,      # Socratic opportunity prompts
        "convo": 0.70,            # Conversation intelligence (ConvoIQ)
        "engagement": 0.65,       # Engagement pulse predictions
        "mind": 0.65,             # Mind memories
        "chip": 0.65,             # Domain-specific chip intelligence
        "semantic-agentic": 0.62, # Agentic retrieval over semantic shortlist
        "niche": 0.60,            # Niche intelligence network
        "semantic-hybrid": 0.58,  # Hybrid retrieval
        "semantic": 0.55,         # Semantic retrieval of cognitive insights
        "cognitive": 0.50,        # Standard cognitive insights
        "bank": 0.35,             # Memory banks (less curated, noisiest source per benchmark)
    }

    def _rank_score(self, a: Advice) -> float:
        """Compute a relevance score using 3-factor additive model.

        Three independent dimensions (tuned via scoring benchmark 2026-02-22):
          - Relevance (0.50): Is this about what the user is doing right now?
          - Quality   (0.25): Is this a well-structured, actionable insight?
          - Trust     (0.25): Has this been proven/validated to work?

        Relevance-heavy weighting reduces noise by ~28% vs equal weighting
        (benchmark: h_relevance_heavy composite=0.7419 vs i_quality_heavy=0.6053).

        Noise penalties applied multiplicatively AFTER the additive blend,
        so garbage still gets crushed to near-zero.
        """
        # --- Dimension 1: Relevance (context_match) ---
        relevance = max(0.0, min(1.0, float(a.context_match or 0.0)))

        # --- Dimension 2: Quality (best of actionability/unified_score + source tier) ---
        adv_q = getattr(a, "advisory_quality", None) or {}
        if isinstance(adv_q, dict) and adv_q.get("unified_score"):
            text_quality = float(adv_q["unified_score"])
        else:
            text_quality = self._score_actionability(a.text)

        source_quality_map = getattr(self, "_SOURCE_BOOST", self._SOURCE_QUALITY)
        if not isinstance(source_quality_map, dict):
            source_quality_map = self._SOURCE_QUALITY
        source_quality = float(source_quality_map.get(a.source, 0.50))
        quality = max(text_quality, source_quality)

        # --- Dimension 3: Trust (best of confidence, effectiveness) ---
        trust = max(0.0, min(1.0, float(a.confidence or 0.0)))

        # Check ralph insight-level effectiveness
        try:
            from .meta_ralph import get_meta_ralph
            ralph = get_meta_ralph()
        except Exception:
            ralph = None
        if ralph and a.insight_key:
            insight_eff = ralph.get_insight_effectiveness(a.insight_key)
            if insight_eff > 0:
                trust = max(trust, insight_eff)

        # Check EIDOS store effectiveness (richer signal for eidos items)
        if a.source == "eidos" and a.insight_key and a.insight_key.startswith("eidos:"):
            try:
                from .eidos.store import get_store as _get_eidos_store
                _estore = _get_eidos_store()
                _parts = a.insight_key.split(":")
                if len(_parts) >= 3:
                    _fid = _estore.find_distillation_by_prefix(_parts[2])
                    if _fid:
                        _dist = _estore.get_distillation(_fid)
                        if _dist:
                            trust = max(trust, _dist.effectiveness)
                            if _dist.validation_count >= 5:
                                trust = min(1.0, trust + 0.10)
            except Exception:
                pass

        # Source-level effectiveness from implicit + explicit feedback loop
        try:
            from .feedback_effectiveness_cache import get_feedback_cache
            _fb_eff = get_feedback_cache().get_source_effectiveness(a.source)
            if _fb_eff >= 0:
                trust = max(trust, _fb_eff)
        except Exception:
            pass

        # Default trust when no data: 0.5 (neutral, not penalizing)
        if trust < 0.1:
            trust = 0.50

        # --- Additive blend (relevance-heavy, tuned 2026-02-22) ---
        score = (0.50 * relevance) + (0.25 * quality) + (0.25 * trust)

        # --- Category boost (demonstrated utility from feedback data) ---
        try:
            cat = self._advice_category(a)
            cat_boost = self._category_boost_from_effectiveness(cat)
            # Blend with feedback-based category signal
            from .feedback_effectiveness_cache import get_feedback_cache
            fb_cat_boost = get_feedback_cache().get_category_boost(cat)
            # Average existing + feedback-based when both available
            if fb_cat_boost != 1.0:
                cat_boost = (cat_boost + fb_cat_boost) / 2.0
            score *= max(0.9, min(1.2, cat_boost))
        except Exception:
            pass

        # --- Noise penalties (multiplicative, crush garbage to near-zero) ---
        if self._is_low_signal_struggle_text(a.text):
            score *= 0.05
        elif self._is_transcript_artifact(a.text):
            score *= 0.40
        elif self._is_metadata_pattern(a.text):
            score *= 0.60

        return score

    def _rank_advice(self, advice_list: List[Advice]) -> List[Advice]:
        """Rank advice by relevance, actionability, and effectiveness."""
        return sorted(advice_list, key=self._rank_score, reverse=True)

    def _apply_mind_slot_reserve(self, advice_list: List[Advice], *, max_items: int) -> List[Advice]:
        """Reserve a bounded number of top slots for strong Mind items."""
        reserve = max(0, int(MIND_RESERVE_SLOTS or 0))
        cap = max(0, int(max_items or 0))
        if reserve <= 0 or cap <= 0:
            return advice_list
        if not advice_list:
            return advice_list

        head = list(advice_list[:cap])
        if not head:
            return advice_list

        score_cache: Dict[int, float] = {}

        def _score(item: Advice) -> float:
            key = id(item)
            if key not in score_cache:
                score_cache[key] = float(self._rank_score(item))
            return score_cache[key]

        qualified_mind = [
            item
            for item in advice_list
            if str(getattr(item, "source", "") or "").lower() == "mind" and _score(item) >= MIND_RESERVE_MIN_RANK
        ]
        if not qualified_mind:
            return advice_list

        current_mind = sum(1 for item in head if str(getattr(item, "source", "") or "").lower() == "mind")
        target_mind = min(reserve, len(qualified_mind))
        needed = target_mind - current_mind
        if needed <= 0:
            return advice_list

        inserted = {id(item) for item in head}
        candidates = [item for item in qualified_mind if id(item) not in inserted]
        if not candidates:
            return advice_list

        changed = False
        for candidate in candidates:
            if needed <= 0:
                break
            replace_indexes = [
                idx
                for idx, item in enumerate(head)
                if str(getattr(item, "source", "") or "").lower() != "mind"
            ]
            if not replace_indexes:
                break
            worst_idx = min(replace_indexes, key=lambda idx: _score(head[idx]))
            head[worst_idx] = candidate
            needed -= 1
            changed = True

        if not changed:
            return advice_list
        return self._rank_advice(head)

    @staticmethod
    def _build_minimax_rerank_prompt(query: str, candidates: List[Advice], top_k: int) -> str:
        top_k = max(4, int(top_k or 4))
        rows = []
        for idx, adv in enumerate(candidates[:top_k]):
            source = str(getattr(adv, "source", "") or "").strip().lower() or "unknown"
            context_match = float(getattr(adv, "context_match", 0.0) or 0.0)
            conf = float(getattr(adv, "confidence", 0.0) or 0.0)
            rows.append(
                f"{idx}. source={source} context_match={context_match:.3f} conf={conf:.3f} text={str(getattr(adv,'text','') or '')[:180].replace(chr(10),' ')}"
            )
        if not rows:
            return ""
        return f"""You are a strict ranking engine for actionable developer advice.

Return ONLY compact JSON.
You must return strict JSON: {{"order":[...],"reason":"..."}}

Inputs:
query: {str(query or "").strip()[:320]}

Candidates (index is fixed by position):
{chr(10).join(rows)}

Task:
Return the best ordering for the top {top_k} candidates by likely immediate usefulness for the query.
Output only JSON with `order` as a list of 0-based indices (descending by relevance)."""

    @staticmethod
    def _parse_minimax_rerank_response(raw: str, max_items: int) -> List[int]:
        if not raw:
            return []
        cleaned = str(raw).strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned).strip()
        parsed = None
        try:
            parsed = json.loads(cleaned)
        except Exception:
            parsed = None

        candidates = []
        if isinstance(parsed, dict):
            for key in ("order", "indices", "ranking", "rerank"):
                value = parsed.get(key)
                if isinstance(value, list) and value:
                    candidates = value
                    break
            if isinstance(parsed.get("items"), list):
                item_payload = [item for item in parsed.get("items", []) if isinstance(item, dict)]
                parsed_order = []
                for item in item_payload:
                    idx = item.get("index")
                    if idx is None:
                        continue
                    parsed_order.append(idx)
                if parsed_order:
                    candidates = parsed_order
        elif isinstance(parsed, list):
            candidates = parsed

        if not candidates:
            # Fall back to first-run number extraction (e.g., "2, 0, 5")
            candidates = [int(v) for v in re.findall(r"\d+", cleaned)]
            if not candidates:
                return []

        order: List[int] = []
        seen = set()
        for v in candidates:
            try:
                idx = int(v)
            except Exception:
                continue
            if idx < 0 or idx >= max_items:
                continue
            if idx in seen:
                continue
            seen.add(idx)
            order.append(idx)
        return order

    def _minimax_fast_rerank(
        self,
        query: str,
        advice_list: List[Advice],
        policy: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> Tuple[List[Advice], Dict[str, Any]]:
        if not isinstance(advice_list, list) or len(advice_list) < 2:
            return advice_list, {
                "used": False,
                "reason": "insufficient_items",
                "trace_id": str(trace_id or "").strip(),
            }
        if not policy:
            policy = {}

        if not bool(policy.get("minimax_fast_rerank", False)):
            return advice_list, {
                "used": False,
                "reason": "disabled",
                "trace_id": str(trace_id or "").strip(),
            }

        min_items = max(6, int(policy.get("minimax_fast_rerank_min_items", 12) or 12))
        if len(advice_list) < min_items:
            return advice_list, {
                "used": False,
                "reason": "below_min_items",
                "trace_id": str(trace_id or "").strip(),
            }

        top_k = max(min_items, int(policy.get("minimax_fast_rerank_top_k", 16) or 16))
        top_k = min(top_k, len(advice_list))

        cooldown = max(0.0, float(policy.get("minimax_fast_rerank_cooldown_s", 30.0) or 0.0))
        now = time.time()
        if cooldown > 0 and (now - self._last_minimax_rerank_ts) < cooldown:
            return advice_list, {
                "used": False,
                "reason": "cooldown",
                "trace_id": str(trace_id or "").strip(),
            }

        start = time.perf_counter()
        model = str(policy.get("minimax_fast_rerank_model", "MiniMax-M2.5") or "MiniMax-M2.5").strip()
        timeout_s = max(2.0, float(policy.get("minimax_fast_rerank_timeout_s", 7.0) or 7.0))

        prompt = self._build_minimax_rerank_prompt(query, advice_list, top_k)
        if not prompt:
            return advice_list, {
                "used": False,
                "reason": "empty_prompt",
                "trace_id": str(trace_id or "").strip(),
            }

        try:
            from .advisory_synthesizer import _query_minimax
        except Exception:
            return advice_list, {
                "used": False,
                "reason": "synth_import_error",
                "trace_id": str(trace_id or "").strip(),
            }

        try:
            response = _query_minimax(prompt, model=model, timeout_s=timeout_s)
        except Exception:
            return advice_list, {
                "used": False,
                "reason": "query_failed",
                "trace_id": str(trace_id or "").strip(),
            }

        if not response:
            return advice_list, {
                "used": False,
                "reason": "empty_response",
                "trace_id": str(trace_id or "").strip(),
            }

        order = self._parse_minimax_rerank_response(response, len(advice_list))
        if not order:
            return advice_list, {
                "used": False,
                "reason": "bad_order",
                "trace_id": str(trace_id or "").strip(),
            }

        seen = set()
        top_order: List[Advice] = []
        for idx in order[:top_k]:
            if idx in seen:
                continue
            if idx < 0 or idx >= len(advice_list):
                continue
            seen.add(idx)
            top_order.append(advice_list[idx])
        # Keep unknown tail in original order for safety.
        remaining = [adv for idx, adv in enumerate(advice_list) if idx not in seen]
        merged = top_order + remaining
        self._last_minimax_rerank_ts = now
        return (
            merged,
            {
                "used": True,
                "model": model,
                "top_k": top_k,
                "order_len": len(order),
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
                "trace_id": str(trace_id or "").strip(),
            },
        )

    def _cross_encoder_rerank(self, query: str, advice_list: List[Advice]) -> List[Advice]:
        """Rerank advice using cross-encoder for precise relevance scoring.

        Only called when there are more candidates than MAX_ADVICE_ITEMS.
        Silently falls back to the original list if the reranker is unavailable.
        """
        try:
            from .cross_encoder_reranker import get_reranker
            reranker = get_reranker()
            if reranker is None:
                return advice_list
            texts = [a.text for a in advice_list]
            # Rerank to get double the final limit (cross-encoder picks best, then
            # MIN_RANK_SCORE and MAX_ADVICE_ITEMS do the final cut)
            top_k = min(MAX_ADVICE_ITEMS * 2, len(advice_list))
            ranked = reranker.rerank(query, texts, top_k=top_k)
            return [advice_list[idx] for idx, _score in ranked]
        except Exception:
            return advice_list

    def _log_advice(
        self,
        advice_list: List[Advice],
        tool: str,
        context: str,
        trace_id: Optional[str] = None,
        log_recent: bool = True,
    ):
        """Log advice given for later analysis."""
        if not advice_list:
            return

        categories = [self._coerce_advisory_category(self._advice_category(a), fallback="general") for a in advice_list]
        readiness_values = [self._advice_readiness_score(a) for a in advice_list]
        quality_values = [self._advice_quality_summary(a) for a in advice_list]
        category_summary: Dict[str, Dict[str, Any]] = {}
        for idx, cat in enumerate(categories):
            bucket = category_summary.setdefault(
                cat,
                {
                    "count": 0,
                    "readiness_sum": 0.0,
                    "readiness_max": 0.0,
                    "readiness_min": 1.0,
                    "quality_sum": 0.0,
                    "quality_count": 0,
                },
            )
            readiness = float(readiness_values[idx] if idx < len(readiness_values) else 0.0)
            quality = quality_values[idx] if idx < len(quality_values) else {}
            score = float(quality.get("unified_score", 0.0) or 0.0) if isinstance(quality, dict) else 0.0
            bucket["count"] += 1
            bucket["readiness_sum"] += readiness
            bucket["readiness_max"] = max(bucket["readiness_max"], readiness)
            bucket["readiness_min"] = min(bucket["readiness_min"], readiness)
            bucket["quality_sum"] += score
            bucket["quality_count"] += 1
        entry = {
            "timestamp": datetime.now().isoformat(),
            "tool": tool,
            "context": context[:100],
            "trace_id": trace_id,
            "advice_ids": [a.advice_id for a in advice_list],
            "advice_texts": [a.text[:100] for a in advice_list],
            "insight_keys": [a.insight_key for a in advice_list],
            "sources": [a.source for a in advice_list],
            "categories": categories,
            "confidences": [round(a.confidence, 3) for a in advice_list],
            "advisory_readiness": [round(float(r), 4) for r in readiness_values],
            "advisory_quality": quality_values,
            "context_matches": [round(a.context_match, 3) for a in advice_list],
            "category_summary": category_summary,
        }

        _append_jsonl_capped(ADVICE_LOG, entry, max_lines=4000)

        self.effectiveness["total_advice_given"] += len(advice_list)

        if log_recent:
            # Default direct-advisor semantics: advice retrieved is assumed delivered.
            record_recent_delivery(
                tool=tool,
                advice_list=advice_list,
                trace_id=trace_id,
                route="advisor",
                delivered=True,
                categories=categories,
                advisory_readiness=readiness_values,
                advisory_quality=quality_values,
            )

            self._record_category_delivery(
                categories=categories,
                advisory_readiness=readiness_values,
                advisory_quality=quality_values,
            )

        self._save_effectiveness()

    def _record_category_delivery(
        self,
        categories: List[str],
        advisory_readiness: List[float],
        advisory_quality: List[Dict[str, Any]],
    ) -> None:
        """Accumulate per-category surfaced/advice readiness+quality aggregates."""
        if not categories:
            return
        if not isinstance(self.effectiveness, dict):
            return

        buckets = self.effectiveness.setdefault("by_category", {})
        now = time.time()
        for idx, cat in enumerate(categories):
            c_key = self._coerce_advisory_category(cat, fallback="general")
            bucket = self._coerce_category_bucket(buckets.get(c_key, {}))
            bucket["surfaced"] += 1
            readiness = float(advisory_readiness[idx] if idx < len(advisory_readiness) else 0.0)
            readiness = max(0.0, min(1.0, readiness))
            bucket["readiness_sum"] += readiness
            bucket["readiness_count"] += 1 if idx < len(advisory_readiness) else 0
            q = advisory_quality[idx] if idx < len(advisory_quality) else {}
            if isinstance(q, dict):
                q_score = float(q.get("unified_score", 0.0) or 0.0)
                bucket["quality_sum"] += max(0.0, min(1.0, q_score))
                bucket["quality_count"] += 1
            bucket["last_ts"] = now
            buckets[c_key] = self._coerce_category_bucket(bucket)

    def _get_recent_advice_entry(
        self,
        tool_name: str,
        trace_id: Optional[str] = None,
        allow_task_fallback: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Return the most recent advice entry for a tool within TTL.

        Uses fuzzy matching to handle tool name variations:
        - "Bash" matches "Bash command"
        - "Edit" matches "Edit file"
        - "Read" matches "Read code"
        """
        if not RECENT_ADVICE_LOG.exists():
            return None
        try:
            lines = _tail_jsonl(RECENT_ADVICE_LOG, RECENT_ADVICE_MAX_LINES)
        except Exception:
            return None

        now = time.time()
        tool_lower = (tool_name or "").strip().lower()  # Case-insensitive matching
        if not tool_lower:
            return None
        task_fallback = None  # Track most recent task advice as fallback
        prefix_match = None  # Track prefix matches (e.g., "Bash" in "Bash command")
        trace_match = None

        for line in reversed(lines[-RECENT_ADVICE_MAX_LINES:]):
            try:
                entry = json.loads(line)
            except Exception:
                continue

            ts = float(entry.get("ts") or 0.0)
            if now - ts > RECENT_ADVICE_MAX_AGE_S:
                continue  # Too old

            entry_trace = (entry.get("trace_id") or "").strip()
            if trace_id and entry_trace and entry_trace == str(trace_id).strip():
                trace_match = entry
                break

            entry_tool = entry.get("tool", "").lower()

            # Exact tool match - return immediately
            if entry_tool == tool_lower:
                return entry

            # Prefix match: "Bash" matches "bash command", "Edit" matches "edit file"
            if prefix_match is None:
                if entry_tool.startswith(tool_lower + " ") or entry_tool.startswith(tool_lower + "_"):
                    prefix_match = entry
                elif tool_lower.startswith(entry_tool + " ") or tool_lower.startswith(entry_tool + "_"):
                    prefix_match = entry

            # Optional fallback for explicit Task-tool flows.
            if entry_tool == "task" and task_fallback is None:
                task_fallback = entry

        # Prefer exact trace match; otherwise use tool/prefix fallback.
        if trace_match:
            return trace_match
        if prefix_match:
            return prefix_match
        if allow_task_fallback or tool_lower == "task":
            return task_fallback
        return None

    def _find_recent_advice_by_id(self, advice_id: str) -> Optional[Dict[str, Any]]:
        """Find recent advice entry containing a specific advice_id."""
        if not RECENT_ADVICE_LOG.exists() or not advice_id:
            return None
        try:
            lines = _tail_jsonl(RECENT_ADVICE_LOG, RECENT_ADVICE_MAX_LINES)
        except Exception:
            return None
        for line in reversed(lines[-RECENT_ADVICE_MAX_LINES:]):
            try:
                entry = json.loads(line)
            except Exception:
                continue
            ids = entry.get("advice_ids") or []
            if advice_id in ids:
                return entry
        return None

    # ============= Outcome Tracking =============

    def report_outcome(
        self,
        advice_id: str,
        was_followed: bool,
        was_helpful: Optional[bool] = None,
        notes: str = "",
        trace_id: Optional[str] = None,
    ):
        """
        Report whether advice was followed and if it helped.

        This closes the feedback loop - we learn which advice actually works.

        Args:
            advice_id: ID of the advice
            was_followed: Did the user/agent follow this advice?
            was_helpful: If followed, did it help? (None if unclear)
            notes: Optional notes about the outcome
        """
        outcome = AdviceOutcome(
            advice_id=advice_id,
            was_followed=was_followed,
            was_helpful=was_helpful,
            outcome_notes=notes,
        )

        # Update effectiveness stats
        category = None
        try:
            entry = self._find_recent_advice_by_id(advice_id)
            if entry:
                ids = entry.get("advice_ids") or []
                idx = ids.index(advice_id) if advice_id in ids else -1
                cats = entry.get("categories") or []
                if 0 <= idx < len(cats):
                    category = cats[idx]
                srcs = entry.get("sources") or []
                if not category and 0 <= idx < len(srcs):
                    category = srcs[idx]
        except Exception:
            category = None

        inc_followed, inc_helpful = self._mark_outcome_counted(
            advice_id=advice_id,
            was_followed=was_followed,
            was_helpful=was_helpful,
            category=category,
        )
        if inc_followed:
            self.effectiveness["total_followed"] += 1
        if inc_helpful:
            self.effectiveness["total_helpful"] += 1

        self._save_effectiveness()
        self._record_cognitive_helpful(advice_id, was_helpful)

        # Track outcome in Meta-Ralph
        try:
            from .meta_ralph import get_meta_ralph
            ralph = get_meta_ralph()
            outcome_str = (
                "good" if was_helpful is True
                else ("bad" if was_helpful is False else None)
            )
            # Avoid overwriting an existing explicit outcome with "unknown".
            if outcome_str:
                # Best-effort: enrich with insight_key/source and trace binding so outcomes
                # can flow back to the correct learning and be strictly attributable.
                ik = None
                src = None
                derived_trace = None
                try:
                    entry = self._find_recent_advice_by_id(advice_id)
                    if entry:
                        ids = entry.get("advice_ids") or []
                        idx = ids.index(advice_id) if advice_id in ids else -1
                        if idx >= 0:
                            iks = entry.get("insight_keys") or []
                            srcs = entry.get("sources") or []
                            if idx < len(iks):
                                ik = iks[idx]
                            if idx < len(srcs):
                                src = srcs[idx]
                        derived_trace = entry.get("trace_id")
                except Exception:
                    pass

                ralph.track_outcome(
                    advice_id,
                    outcome_str,
                    notes,
                    # Prefer the explicit trace_id when provided (so trace-mismatched
                    # outcomes remain weak-only). Fall back to the retrieval trace from
                    # the recent advice log when callers don't provide a trace_id.
                    trace_id=trace_id or derived_trace,
                    insight_key=ik,
                    source=src or "advisor_unlinked",
                )
        except Exception:
            pass  # Don't break outcome flow if tracking fails


        # Log outcome
        with open(ADVICE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"outcome": asdict(outcome)}) + "\n")

    def report_action_outcome(
        self,
        tool_name: str,
        success: bool,
        advice_was_relevant: bool = False,
        trace_id: Optional[str] = None,
    ):
        """
        Simplified outcome reporting after any action.

        Call this after each tool execution to build the feedback loop.
        """
        # Update source effectiveness based on whether advice helped
        entry = self._get_recent_advice_entry(tool_name, trace_id=trace_id)

        # Use actual source from recent advice (not hardcoded "cognitive")
        source = "cognitive"  # Default fallback
        if entry:
            sources = entry.get("sources") or []
            if sources:
                source = sources[0]  # Primary source

        if source not in self.effectiveness.get("by_source", {}):
            self.effectiveness.setdefault("by_source", {})[source] = {
                "total": 0, "helpful": 0
            }

        self.effectiveness["by_source"][source]["total"] += 1
        if success and advice_was_relevant:
            self.effectiveness["by_source"][source]["helpful"] += 1

        self._save_effectiveness()

        # Report outcome to Meta-Ralph for feedback loop.
        # Track ALL outcomes, not just ones with prior advice.
        outcome_str = "good" if success else "bad"
        evidence = f"tool={tool_name} success={success}"

        try:
            from .meta_ralph import get_meta_ralph
            ralph = get_meta_ralph()

            # If there was prior advice, link outcomes to those advice IDs
            # CRITICAL: propagate insight_keys so outcomes link to actual insights
            if entry:
                advice_ids = entry.get("advice_ids") or []
                insight_keys = entry.get("insight_keys") or []
                entry_sources = entry.get("sources") or []
                for i, aid in enumerate(advice_ids):
                    # Propagate insight_key to Meta-Ralph so outcome records
                    # can flow back to cognitive insight reliability scoring
                    ik = insight_keys[i] if i < len(insight_keys) else None
                    src = entry_sources[i] if i < len(entry_sources) else None
                    ralph.track_outcome(
                        aid, outcome_str, evidence,
                        trace_id=trace_id,
                        insight_key=ik,
                        source=src,
                    )
                    # Record that advice was seen, but do NOT auto-mark as
                    # helpful just because the tool succeeded.  Only explicit
                    # feedback (advice_was_relevant=True) or failure-after-advice
                    # (False) should count.  None = unknown.
                    was_followed = bool(advice_was_relevant)
                    was_helpful = (
                        True if (advice_was_relevant and success)
                        else (False if (advice_was_relevant and not success) else None)
                    )
                    self.report_outcome(
                        aid,
                        was_followed=was_followed,
                        was_helpful=was_helpful,
                        notes=f"Auto-linked from {tool_name}",
                        trace_id=trace_id,
                    )

            # Also track tool-level outcome (even without specific advice)
            tool_outcome_id = f"tool:{tool_name}"
            ralph.track_outcome(tool_outcome_id, outcome_str, evidence, trace_id=trace_id)
        except Exception:
            pass

    def record_advice_feedback(
        self,
        helpful: Optional[bool],
        notes: str = "",
        tool: Optional[str] = None,
        advice_id: Optional[str] = None,
        followed: bool = True,
    ) -> Dict[str, Any]:
        """Record explicit feedback on advice helpfulness.

        If advice_id is provided, records outcome for that advice.
        Else if tool is provided, uses the most recent advice entry for that tool.
        """
        if advice_id:
            self.report_outcome(advice_id, was_followed=followed, was_helpful=helpful, notes=notes or "")
            try:
                entry = self._find_recent_advice_by_id(advice_id)
                insight_keys = []
                sources = []
                tool_name = tool
                entry_trace_id = None
                entry_run_id = None
                entry_session_id = None
                if entry:
                    tool_name = tool_name or entry.get("tool")
                    ids = entry.get("advice_ids") or []
                    idx = ids.index(advice_id) if advice_id in ids else -1
                    ik = entry.get("insight_keys") or []
                    src = entry.get("sources") or []
                    if 0 <= idx < len(ik):
                        insight_keys = [ik[idx]]
                    if 0 <= idx < len(src):
                        sources = [src[idx]]
                    entry_trace_id = entry.get("trace_id")
                    entry_run_id = entry.get("run_id")
                    entry_session_id = entry.get("session_id")
                from .advice_feedback import record_feedback
                record_feedback(
                    advice_ids=[advice_id],
                    tool=tool_name,
                    helpful=helpful,
                    followed=followed,
                    notes=notes or "",
                    insight_keys=insight_keys,
                    sources=sources,
                    trace_id=(str(entry_trace_id) if entry_trace_id else None),
                    run_id=(str(entry_run_id) if entry_run_id else None),
                    session_id=(str(entry_session_id) if entry_session_id else None),
                )
            except Exception:
                pass
            return {"status": "ok", "advice_ids": [advice_id], "tool": tool}

        if tool:
            entry = self._get_recent_advice_entry(tool)
            if not entry:
                return {"status": "not_found", "message": "No recent advice found for tool", "tool": tool}
            advice_ids = entry.get("advice_ids") or []
            if not advice_ids:
                return {"status": "not_found", "message": "Recent advice had no advice_ids", "tool": tool}
            for aid in advice_ids:
                self.report_outcome(aid, was_followed=followed, was_helpful=helpful, notes=notes or "")
            try:
                insight_keys = entry.get("insight_keys") or []
                sources = entry.get("sources") or []
                entry_trace_id = entry.get("trace_id")
                entry_run_id = entry.get("run_id")
                entry_session_id = entry.get("session_id")
                from .advice_feedback import record_feedback
                record_feedback(
                    advice_ids=advice_ids,
                    tool=tool,
                    helpful=helpful,
                    followed=followed,
                    notes=notes or "",
                    insight_keys=insight_keys,
                    sources=sources,
                    trace_id=(str(entry_trace_id) if entry_trace_id else None),
                    run_id=(str(entry_run_id) if entry_run_id else None),
                    session_id=(str(entry_session_id) if entry_session_id else None),
                )
            except Exception:
                pass
            return {"status": "ok", "advice_ids": advice_ids, "tool": tool}

        return {"status": "error", "message": "Provide advice_id or tool"}

    # ============= Quick Access Methods =============

    def get_quick_advice(self, tool_name: str) -> Optional[str]:
        """
        Get single most relevant piece of advice for a tool.

        This is the simplest integration point - just call this before any action.
        """
        advice_list = self.advise(tool_name, {}, include_mind=False)
        if advice_list:
            return advice_list[0].text
        return None

    def should_be_careful(self, tool_name: str) -> Tuple[bool, str]:
        """
        Quick check: should we be extra careful with this tool?

        Returns (should_be_careful, reason)
        """
        # Check self-awareness for struggles with this tool
        for insight in self.cognitive.get_self_awareness_insights():
            insight_text = str(getattr(insight, "insight", "") or "").strip()
            if not insight_text:
                continue
            if self._is_low_signal_struggle_text(insight_text):
                continue
            if not self._insight_mentions_tool(tool_name, insight_text, getattr(insight, "context", "")):
                continue
            lowered = insight_text.lower()
            if "struggle" in lowered or "fail" in lowered:
                return True, insight_text

        return False, ""

    def get_effectiveness_report(self) -> Dict:
        """Get report on how effective advice has been."""
        total = self.effectiveness.get("total_advice_given", 0)
        followed = self.effectiveness.get("total_followed", 0)
        helpful = self.effectiveness.get("total_helpful", 0)
        by_category = self.effectiveness.get("by_category", {}) if isinstance(self.effectiveness.get("by_category"), dict) else {}
        category_report = {}
        for category, row in by_category.items():
            if not isinstance(row, dict):
                continue
            surfaced = float(row.get("surfaced", 0) or 0.0)
            total_seen = float(row.get("total", 0) or 0.0)
            helpful_seen = float(row.get("helpful", 0) or 0.0)
            readiness_sum = float(row.get("readiness_sum", 0.0) or 0.0)
            readiness_count = float(row.get("readiness_count", 0) or 0.0)
            quality_sum = float(row.get("quality_sum", 0.0) or 0.0)
            quality_count = float(row.get("quality_count", 0) or 0.0)
            category_boost = self._category_boost_from_effectiveness(str(category))
            category_report[str(category)] = {
                "surfaced": int(surfaced),
                "followed": int(total_seen),
                "helpful": int(helpful_seen),
                "follow_rate": round(total_seen / max(1.0, surfaced), 4) if surfaced else 0.0,
                "helpful_rate": round(helpful_seen / max(1.0, total_seen), 4) if total_seen else 0.0,
                "avg_readiness": round(readiness_sum / max(1.0, readiness_count), 4),
                "avg_quality": round(quality_sum / max(1.0, quality_count), 4),
                "category_boost": round(category_boost, 4),
            }

        return {
            "total_advice_given": total,
            "follow_rate": followed / max(total, 1),
            "helpfulness_rate": helpful / max(followed, 1) if followed > 0 else 0,
            "by_source": self.effectiveness.get("by_source", {}),
            "by_category": category_report,
        }

    def compute_contrast_effectiveness(self) -> Dict[str, Any]:
        """
        Compute advice effectiveness by contrasting tool outcomes WITH vs WITHOUT advice.

        This is a background analysis that provides a true measure of advice value
        by comparing success rates when advice was present vs absent.

        Returns:
            Dict with per-tool contrast ratios and overall effectiveness estimate.
        """
        try:
            from .meta_ralph import get_meta_ralph
            ralph = get_meta_ralph()
        except Exception:
            return {"error": "Meta-Ralph unavailable"}

        # Collect outcome records that have insight_keys (advice was present)
        with_advice = {"good": 0, "bad": 0}
        without_advice = {"good": 0, "bad": 0}
        by_tool: Dict[str, Dict[str, Dict[str, int]]] = {}

        for rec in ralph.outcome_records.values():
            outcome = ralph._normalize_outcome(rec.outcome)
            if outcome not in ("good", "bad"):
                continue

            # Determine if this was a tool-level record or advice-linked
            lid = rec.learning_id or ""
            tool_name = ""
            has_advice = bool(rec.insight_key)

            if lid.startswith("tool:"):
                tool_name = lid[5:]
            elif rec.outcome_evidence:
                # Extract tool from evidence "tool=X success=Y"
                for part in rec.outcome_evidence.split():
                    if part.startswith("tool="):
                        tool_name = part[5:]
                        break

            if not tool_name:
                continue

            if tool_name not in by_tool:
                by_tool[tool_name] = {
                    "with_advice": {"good": 0, "bad": 0},
                    "without_advice": {"good": 0, "bad": 0},
                }

            if has_advice:
                with_advice[outcome] += 1
                by_tool[tool_name]["with_advice"][outcome] += 1
            else:
                without_advice[outcome] += 1
                by_tool[tool_name]["without_advice"][outcome] += 1

        # Compute contrast ratios
        wa_total = with_advice["good"] + with_advice["bad"]
        wo_total = without_advice["good"] + without_advice["bad"]

        wa_rate = with_advice["good"] / max(wa_total, 1)
        wo_rate = without_advice["good"] / max(wo_total, 1)

        # Contrast ratio: how much better is success WITH advice vs WITHOUT
        contrast = wa_rate - wo_rate if (wa_total >= 5 and wo_total >= 5) else None

        per_tool = {}
        for tool, data in by_tool.items():
            wt = data["with_advice"]["good"] + data["with_advice"]["bad"]
            wot = data["without_advice"]["good"] + data["without_advice"]["bad"]
            if wt >= 3 and wot >= 3:
                wr = data["with_advice"]["good"] / max(wt, 1)
                wor = data["without_advice"]["good"] / max(wot, 1)
                per_tool[tool] = {
                    "with_advice_rate": round(wr, 3),
                    "without_advice_rate": round(wor, 3),
                    "contrast": round(wr - wor, 3),
                    "samples": wt + wot,
                }

        return {
            "overall_contrast": round(contrast, 3) if contrast is not None else None,
            "with_advice": with_advice,
            "without_advice": without_advice,
            "per_tool": per_tool,
            "sufficient_data": wa_total >= 5 and wo_total >= 5,
        }

    def repair_effectiveness_counters(self) -> Dict[str, Any]:
        """Normalize persisted effectiveness counters and return before/after."""
        before = {
            "total_advice_given": int(self.effectiveness.get("total_advice_given", 0) or 0),
            "total_followed": int(self.effectiveness.get("total_followed", 0) or 0),
            "total_helpful": int(self.effectiveness.get("total_helpful", 0) or 0),
        }
        self.effectiveness = self._normalize_effectiveness(self.effectiveness)
        self._save_effectiveness()
        after = {
            "total_advice_given": int(self.effectiveness.get("total_advice_given", 0) or 0),
            "total_followed": int(self.effectiveness.get("total_followed", 0) or 0),
            "total_helpful": int(self.effectiveness.get("total_helpful", 0) or 0),
        }
        return {"before": before, "after": after}

    # ============= Context Generation =============

    def generate_context_block(self, tool_name: str, task_context: str = "", include_mind: bool = False) -> str:
        """
        Generate a context block that can be injected into prompts.

        This is how learnings become actionable in the LLM context.
        """
        advice_list = self.advise(tool_name, {}, task_context, include_mind=include_mind)

        if not advice_list:
            return ""

        lines = ["## Spark Advisor Notes"]

        # Add cautions first
        cautions = [a for a in advice_list if "[Caution]" in a.text or "[Past Failure]" in a.text]
        if cautions:
            lines.append("### Cautions")
            for a in cautions[:2]:
                lines.append(f"- {a.text}")

        # Add recommendations
        recs = [a for a in advice_list if a not in cautions]
        if recs:
            lines.append("### Relevant Learnings")
            for a in recs[:3]:
                conf_str = f"({a.confidence:.0%} confident)" if a.confidence >= 0.7 else ""
                lines.append(f"- {a.text} {conf_str}")

        return "\n".join(lines)


# ============= Singleton =============
_advisor: Optional[SparkAdvisor] = None

def get_advisor() -> SparkAdvisor:
    """Get the global advisor instance."""
    global _advisor
    if _advisor is None:
        _advisor = SparkAdvisor()
    return _advisor


# ============= Convenience Functions =============
def advise_on_tool(
    tool_name: str,
    tool_input: Dict = None,
    context: str = "",
    include_mind: bool = True,
    track_retrieval: bool = True,
    log_recent: bool = True,
    trace_id: Optional[str] = None,
) -> List[Advice]:
    """Get advice before using a tool."""
    return get_advisor().advise(
        tool_name,
        tool_input or {},
        context,
        include_mind=include_mind,
        track_retrieval=track_retrieval,
        log_recent=log_recent,
        trace_id=trace_id,
    )


def get_quick_advice(tool_name: str) -> Optional[str]:
    """Get single most relevant advice for a tool."""
    return get_advisor().get_quick_advice(tool_name)


def should_be_careful(tool_name: str) -> Tuple[bool, str]:
    """Check if we should be careful with this tool."""
    return get_advisor().should_be_careful(tool_name)


def report_outcome(
    tool_name: str,
    success: bool,
    advice_helped: bool = False,
    trace_id: Optional[str] = None,
):
    """Report action outcome to close the feedback loop."""
    get_advisor().report_action_outcome(tool_name, success, advice_helped, trace_id=trace_id)


def record_advice_feedback(
    helpful: Optional[bool],
    notes: str = "",
    tool: Optional[str] = None,
    advice_id: Optional[str] = None,
    followed: bool = True,
):
    """Record explicit feedback on advice helpfulness."""
    return get_advisor().record_advice_feedback(
        helpful=helpful,
        notes=notes,
        tool=tool,
        advice_id=advice_id,
        followed=followed,
    )


def generate_context(tool_name: str, task: str = "") -> str:
    """Generate injectable context block."""
    return get_advisor().generate_context_block(tool_name, task)


def repair_effectiveness_counters() -> Dict[str, Any]:
    """Repair advisor effectiveness counters on disk."""
    return get_advisor().repair_effectiveness_counters()
