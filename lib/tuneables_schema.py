"""
Central schema and validator for Spark tuneables.

Single source of truth for every tuneable section, key, type, default,
min/max bounds, and description. No external dependencies.

Usage:
    from lib.tuneables_schema import validate_tuneables, SCHEMA
    result = validate_tuneables(data)
    if result.warnings:
        for w in result.warnings:
            print(f"[WARN] {w}")
    clean_data = result.data
"""

from __future__ import annotations

import json
from collections import namedtuple
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --------------- Schema Primitives ---------------

TuneableSpec = namedtuple("TuneableSpec", [
    "type",          # "int", "float", "bool", "str", "dict", "list"
    "default",       # Default value
    "min_val",       # Minimum (None if unbounded or non-numeric)
    "max_val",       # Maximum (None if unbounded or non-numeric)
    "description",   # Human-readable description
    "enum_values",   # Optional list of valid string values (for str type)
], defaults=[None, None, "", None])


@dataclass
class ValidationResult:
    """Result of validating a tuneables dict against the schema."""
    data: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)
    clamped: List[str] = field(default_factory=list)
    defaults_applied: List[str] = field(default_factory=list)
    unknown_keys: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.warnings) == 0


# --------------- Full Schema Definition ---------------
# Every section and key from config/tuneables.json is defined here.
# Dynamic sub-dicts (source_boosts, domain_profiles) are typed as "dict"
# with inner validation left to their consuming modules.

SCHEMA: Dict[str, Dict[str, TuneableSpec]] = {
    # ---- values: base operational constants ----
    "values": {
        "min_occurrences": TuneableSpec("int", 1, 1, 100, "Min observations before learning"),
        "min_occurrences_critical": TuneableSpec("int", 1, 1, 100, "Min observations for critical insights"),
        "confidence_threshold": TuneableSpec("float", 0.6, 0.0, 1.0, "Confidence threshold for acceptance"),
        "gate_threshold": TuneableSpec("float", 0.45, 0.0, 1.0, "Quality gate threshold"),
        "max_retries_per_error": TuneableSpec("int", 3, 1, 20, "Max retries per error type"),
        "max_file_touches": TuneableSpec("int", 5, 1, 50, "Max file modifications per episode"),
        "no_evidence_steps": TuneableSpec("int", 6, 1, 30, "Steps without evidence before DIAGNOSE"),
        "max_steps": TuneableSpec("int", 40, 5, 200, "Max episode steps"),
        "advice_cache_ttl": TuneableSpec("int", 180, 10, 3600, "Advice cache TTL in seconds"),
        "queue_batch_size": TuneableSpec("int", 100, 50, 1000, "Event queue batch processing size"),
    },

    # ---- pipeline: runtime pipeline behavior ----
    "pipeline": {
        "importance_sampling_enabled": TuneableSpec(
            "bool", False, None, None, "Enable backlog importance sampling",
        ),
        "low_priority_keep_rate": TuneableSpec(
            "float", 0.25, 0.0, 1.0, "Retention rate for low-priority events when sampling",
        ),
        "macros_enabled": TuneableSpec(
            "bool", False, None, None, "Enable macro workflow mining",
        ),
        "macro_min_count": TuneableSpec(
            "int", 3, 2, 20, "Min pattern count for macro extraction",
        ),
        "min_insights_floor": TuneableSpec(
            "int", 1, 0, 3, "Minimum insights generated on high-volume cycles",
        ),
        "floor_events_threshold": TuneableSpec(
            "int", 20, 1, 200, "Event threshold to apply min_insights_floor",
        ),
        "floor_soft_min_events": TuneableSpec(
            "int", 2, 1, 50, "Soft minimum events for floor eligibility",
        ),
    },

    # ---- semantic: semantic retrieval tuning ----
    "semantic": {
        "enabled": TuneableSpec("bool", True, None, None, "Enable semantic retrieval"),
        "min_similarity": TuneableSpec("float", 0.5, 0.0, 1.0, "Min cosine similarity for retrieval"),
        "min_fusion_score": TuneableSpec("float", 0.5, 0.0, 1.0, "Min fusion score for advisory ranking"),
        "weight_recency": TuneableSpec("float", 0.1, 0.0, 1.0, "Recency weight in fusion scoring"),
        "weight_outcome": TuneableSpec("float", 0.45, 0.0, 1.0, "Outcome weight in fusion scoring"),
        "mmr_lambda": TuneableSpec("float", 0.5, 0.0, 1.0, "MMR diversity parameter"),
        "dedupe_similarity": TuneableSpec("float", 0.88, 0.0, 1.0, "Similarity threshold for deduplication"),
        "index_on_write": TuneableSpec("bool", True, None, None, "Index new entries on write"),
        "index_on_read": TuneableSpec("bool", True, None, None, "Rebuild index on read if stale"),
        "index_backfill_limit": TuneableSpec("int", 500, 0, 10000, "Max entries to backfill on index build"),
        "index_cache_ttl_seconds": TuneableSpec("int", 120, 10, 3600, "Index cache TTL"),
        "exclude_categories": TuneableSpec("list", [], None, None, "Categories to exclude from retrieval"),
        "category_caps": TuneableSpec("dict", {}, None, None, "Per-category result limits"),
        "category_exclude": TuneableSpec("list", [], None, None, "Categories to exclude"),
        "log_retrievals": TuneableSpec("bool", True, None, None, "Log retrieval operations"),
        "rescue_min_similarity": TuneableSpec("float", 0.3, 0.0, 1.0, "Rescue path minimum similarity"),
        "rescue_min_fusion_score": TuneableSpec("float", 0.2, 0.0, 1.0, "Rescue path minimum fusion score"),
    },

    # ---- triggers: trigger rule system ----
    "triggers": {
        "enabled": TuneableSpec("bool", True, None, None, "Enable trigger rules"),
        "rules_file": TuneableSpec("str", "", None, None, "Path to trigger rules YAML"),
    },

    # ---- promotion: auto-promotion adapter budgets ----
    "promotion": {
        "adapter_budgets": TuneableSpec("dict", {}, None, None, "Per-adapter max item budgets"),
        "confidence_floor": TuneableSpec("float", 0.9, 0.0, 1.0, "Min confidence for promotion"),
        "min_age_hours": TuneableSpec("float", 2.0, 0.0, 168.0, "Min age in hours before promotion"),
        "auto_interval_s": TuneableSpec("int", 3600, 300, 86400, "Auto-promotion check interval"),
        "threshold": TuneableSpec("float", 0.5, 0.0, 1.0, "Promotion threshold score"),
    },

    # ---- synthesizer: AI synthesis provider config ----
    "synthesizer": {
        "mode": TuneableSpec("str", "auto", None, None, "Synthesis mode",
                             ["auto", "ai_only", "programmatic"]),
        "ai_timeout_s": TuneableSpec("float", 10.0, 0.5, 60.0, "AI synthesis timeout"),
        "cache_ttl_s": TuneableSpec("int", 120, 0, 3600, "Synthesis cache TTL"),
        "max_cache_entries": TuneableSpec("int", 50, 1, 500, "Max cached synthesis results"),
        "preferred_provider": TuneableSpec("str", "minimax", None, None, "Preferred AI provider",
                                           ["minimax", "ollama", "gemini", "openai", "anthropic"]),
        "minimax_model": TuneableSpec("str", "MiniMax-M2.5", None, None, "MiniMax model name"),
    },

    # ---- flow: intelligence flow pipeline ----
    "flow": {
        "validate_and_store_enabled": TuneableSpec("bool", True, None, None,
            "Enable unified validate_and_store_insight entry point. "
            "When False, callers bypass Meta-Ralph and write directly to cognitive store"),
    },

    # ---- advisory_engine: engine behavior ----
    "advisory_engine": {
        "enabled": TuneableSpec("bool", True, None, None, "Enable the advisory engine"),
        "max_ms": TuneableSpec("float", 4000, 250, 20000, "Max advisory engine time budget in ms"),
        "include_mind": TuneableSpec("bool", False, None, None, "Include Mind memory in advisory"),
        "prefetch_queue_enabled": TuneableSpec("bool", False, None, None, "Enable prefetch queue"),
        "prefetch_inline_enabled": TuneableSpec("bool", True, None, None, "Enable inline prefetch"),
        "prefetch_inline_max_jobs": TuneableSpec("int", 1, 0, 10, "Max inline prefetch jobs"),
        "delivery_stale_s": TuneableSpec("float", 600, 60, 86400, "Delivery staleness threshold (s)"),
        "advisory_text_repeat_cooldown_s": TuneableSpec("float", 300, 30, 86400,
            "Text repeat cooldown (s). Prevents identical text from re-emitting. "
            "See also: advisory_gate.advice_repeat_cooldown_s (same advice_id), "
            "advisory_gate.shown_advice_ttl_s (shown-state marker)"),
        "global_dedupe_cooldown_s": TuneableSpec("float", 600, 0, 86400,
            "Cross-session global dedupe cooldown (s). Prevents same insight across sessions. "
            "Distinct from text_repeat (exact text) and advice_repeat (same ID)"),
        "actionability_enforce": TuneableSpec("bool", True, None, None, "Enforce actionability scoring"),
        "force_programmatic_synth": TuneableSpec("bool", False, None, None, "Force programmatic synthesis"),
        "selective_ai_synth_enabled": TuneableSpec("bool", True, None, None, "Enable selective AI synthesis"),
        "selective_ai_min_remaining_ms": TuneableSpec("float", 1800, 0, 20000, "Min ms remaining for AI synth"),
        "selective_ai_min_authority": TuneableSpec("str", "whisper", None, None, "Min authority for AI synth",
                                                   ["silent", "whisper", "note", "warning", "block"]),
        "fallback_budget_cap": TuneableSpec("int", 1, 0, 10,
            "Max fallback emissions per budget window. 0 = unlimited (old behavior)"),
        "fallback_budget_window": TuneableSpec("int", 5, 1, 100,
            "Number of tool calls per fallback budget window"),
    },

    # ---- advisory_gate: emission gating ----
    "advisory_gate": {
        "max_emit_per_call": TuneableSpec("int", 2, 1, 10, "Max advice items emitted per tool call"),
        "tool_cooldown_s": TuneableSpec("int", 15, 1, 3600, "Same-tool suppression cooldown (s)"),
        "advice_repeat_cooldown_s": TuneableSpec("int", 300, 5, 86400,
            "Repeated advice cooldown (s). Prevents same advice_id from re-emitting. "
            "See also: advisory_engine.advisory_text_repeat_cooldown_s (exact text), "
            "shown_advice_ttl_s (shown-state marker with source TTL scaling)"),
        "agreement_gate_enabled": TuneableSpec(
            "bool", False, None, None,
            "Escalate warnings only when multiple sources agree",
        ),
        "agreement_min_sources": TuneableSpec(
            "int", 2, 1, 5, "Minimum agreeing sources for escalation when agreement gate is enabled",
        ),
        "shown_advice_ttl_s": TuneableSpec("int", 600, 5, 86400,
            "Shown-advice suppression TTL (s). Base TTL for shown-state markers; "
            "scaled per-source via source_ttl_multipliers and per-category via "
            "category_cooldown_multipliers. Primary suppression mechanism (~69% of all suppressions)"),
        "category_cooldown_multipliers": TuneableSpec(
            "dict",
            {},
            None,
            None,
            "Per-category cooldown multipliers (e.g., {\"security\": 2.0, \"mind\": 0.5})",
        ),
        "source_ttl_multipliers": TuneableSpec("dict", {}, None, None,
            "Per-source shown TTL scale factors. Low-value sources (baseline=0.5x) "
            "get shorter TTL; high-quality sources (cognitive=1.0x) keep full TTL"),
        "tool_cooldown_multipliers": TuneableSpec("dict", {}, None, None,
            "Per-tool cooldown scale factors. Exploration tools (Read=0.5x) get shorter "
            "cooldown; mutation tools (Edit=1.2x) keep longer cooldown"),
        "warning_threshold": TuneableSpec("float", 0.68, 0.2, 0.99, "Score threshold for WARNING authority"),
        "note_threshold": TuneableSpec("float", 0.38, 0.1, 0.95, "Score threshold for NOTE authority"),
        "whisper_threshold": TuneableSpec("float", 0.27, 0.01, 0.9, "Score threshold for WHISPER authority"),
        "emit_whispers": TuneableSpec("bool", True, None, None, "Whether to emit WHISPER-level advice"),
    },

    # ---- advisory_packet_store: packet storage ----
    "advisory_packet_store": {
        "packet_ttl_s": TuneableSpec("int", 600, 60, 7200, "Packet time-to-live (s)"),
        "max_index_packets": TuneableSpec("int", 2000, 100, 50000, "Max packets in index"),
        "relaxed_effectiveness_weight": TuneableSpec("float", 2.0, 0.0, 10.0, "Effectiveness weight (relaxed mode)"),
        "relaxed_low_effectiveness_threshold": TuneableSpec("float", 0.3, 0.0, 1.0, "Low effectiveness threshold"),
        "relaxed_low_effectiveness_penalty": TuneableSpec("float", 0.5, 0.0, 1.0, "Low effectiveness penalty"),
        "relaxed_max_candidates": TuneableSpec("int", 6, 1, 30, "Top N rows to consider in relaxed match"),
        "packet_lookup_candidates": TuneableSpec("int", 6, 1, 30, "Top N relaxed match candidates to score"),
        "packet_lookup_llm_enabled": TuneableSpec("bool", False, None, None, "Enable LLM-assisted relaxed lookup rerank"),
        "packet_lookup_llm_provider": TuneableSpec("str", "minimax", None, None, "LLM provider for packet rerank"),
        "packet_lookup_llm_timeout_s": TuneableSpec("float", 1.2, 0.2, 10.0, "Packet lookup LLM timeout (s)"),
        "packet_lookup_llm_top_k": TuneableSpec("int", 3, 1, 20, "LLM rerank top-K responses"),
        "packet_lookup_llm_min_candidates": TuneableSpec("int", 2, 1, 20, "Min candidate count before LLM rerank"),
        "packet_lookup_llm_context_chars": TuneableSpec("int", 220, 40, 5000, "Max context chars sent to lookup LLM"),
        "packet_lookup_llm_provider_url": TuneableSpec(
            "str",
            "https://api.minimax.io/v1",
            None,
            None,
            "Base URL for lookup LLM provider",
        ),
        "packet_lookup_llm_model": TuneableSpec("str", "MiniMax-M2.5", None, None, "Model for lookup LLM"),
        "obsidian_enabled": TuneableSpec("bool", False, None, None, "Enable advisory packet export to Obsidian"),
        "obsidian_auto_export": TuneableSpec("bool", False, None, None, "Auto-export packet payloads to Obsidian"),
        "obsidian_export_max_packets": TuneableSpec("int", 300, 1, 5000, "Max Obsidian packet exports to retain"),
        "obsidian_export_dir": TuneableSpec("str", "", None, None, "Override Obsidian export directory (empty = ~/.spark/advice_packets/obsidian)"),
    },

    # ---- advisory_prefetch: prefetch worker ----
    "advisory_prefetch": {
        "worker_enabled": TuneableSpec("bool", False, None, None, "Enable background prefetch worker"),
        "max_jobs_per_run": TuneableSpec("int", 2, 1, 50, "Max prefetch jobs per cycle"),
        "max_tools_per_job": TuneableSpec("int", 3, 1, 10, "Max tools to prefetch per job"),
        "min_probability": TuneableSpec("float", 0.25, 0.0, 1.0, "Min probability threshold for prefetch"),
    },

    # ---- advisor: core advisor settings ----
    "advisor": {
        "min_reliability": TuneableSpec("float", 0.6, 0.0, 1.0, "Min reliability for advice"),
        "min_validations_strong": TuneableSpec("int", 2, 1, 20, "Min validations for strong advice"),
        "max_items": TuneableSpec("int", 4, 1, 20, "Max advice items per call"),
        "cache_ttl": TuneableSpec("int", 180, 10, 3600, "Advice cache TTL (s)"),
        "min_rank_score": TuneableSpec("float", 0.4, 0.0, 1.0, "Min fusion rank score"),
        "max_advice_items": TuneableSpec("int", 5, 1, 20, "Max advice items (alternate key)"),
        "mind_max_stale_s": TuneableSpec("int", 86400, 0, 604800, "Max Mind staleness (s)"),
        "mind_stale_allow_if_empty": TuneableSpec("bool", False, None, None, "Allow stale Mind if empty"),
        "mind_min_salience": TuneableSpec("float", 0.55, 0.0, 1.0, "Min Mind memory salience"),
        "mind_reserve_slots": TuneableSpec("int", 1, 0, 4, "Reserved top advice slots for Mind"),
        "mind_reserve_min_rank": TuneableSpec("float", 0.45, 0.0, 1.0, "Min rank score for reserved Mind slots"),
        "replay_enabled": TuneableSpec("bool", True, None, None, "Enable replay advisory"),
        "replay_min_strict": TuneableSpec("int", 5, 1, 100, "Min strict samples for replay"),
        "replay_min_delta": TuneableSpec("float", 0.25, 0.0, 1.0, "Min improvement delta for replay"),
        "replay_max_age_s": TuneableSpec("int", 1209600, 3600, 2592000, "Max replay age (s, default 14d)"),
        "replay_strict_window_s": TuneableSpec("int", 1500, 60, 86400, "Strict replay window (s)"),
        "replay_min_context": TuneableSpec("float", 0.24, 0.0, 1.0, "Min context match for replay"),
        "replay_max_records": TuneableSpec("int", 2500, 100, 50000, "Max replay records"),
        "replay_mode": TuneableSpec("str", "standard", None, None, "Replay mode",
                                    ["off", "standard", "replay"]),
        "guidance_style": TuneableSpec("str", "balanced", None, None, "Guidance verbosity",
                                       ["concise", "balanced", "coach"]),
        # source_weights: removed (Batch 5) — never read by any code
    },

    # ---- retrieval: retrieval routing ----
    "retrieval": {
        "level": TuneableSpec("str", "2", None, None, "Retrieval complexity level"),
        "overrides": TuneableSpec("dict", {}, None, None, "Retrieval parameter overrides"),
        "domain_profile_enabled": TuneableSpec("bool", True, None, None, "Enable domain-specific profiles"),
        "domain_profiles": TuneableSpec("dict", {}, None, None, "Per-domain retrieval profiles"),
    },

    # ---- meta_ralph: quality gate ----
    "meta_ralph": {
        "quality_threshold": TuneableSpec("float", 4.5, 0.0, 10.0, "Score floor for promotion"),
        "needs_work_threshold": TuneableSpec("int", 2, 0, 10, "Score range for refinement"),
        "needs_work_close_delta": TuneableSpec("float", 0.5, 0.0, 3.0, "Proximity threshold for close-to-passing"),
        "min_outcome_samples": TuneableSpec("int", 5, 1, 100, "Min outcomes before quality scoring"),
        "min_tuneable_samples": TuneableSpec("int", 50, 5, 1000, "Min samples for tuneable validation"),
        "min_needs_work_samples": TuneableSpec("int", 5, 1, 100, "Min samples for needs_work verdict"),
        "min_source_samples": TuneableSpec("int", 15, 1, 200, "Min samples per source"),
        "attribution_window_s": TuneableSpec("int", 1800, 60, 86400, "Time window for attribution (s)"),
        "strict_attribution_require_trace": TuneableSpec("bool", True, None, None, "Require trace for strict attribution"),
    },

    # ---- eidos: episode/distillation budget ----
    "eidos": {
        # max_steps: removed (Batch 5) — duplicate of values.max_steps
        "max_time_seconds": TuneableSpec("int", 1200, 60, 7200, "Max episode time (s)"),
        "max_retries_per_error": TuneableSpec("int", 3, 1, 20, "Retry limit per error type"),
        "max_file_touches": TuneableSpec("int", 5, 1, 50, "Max times to modify same file"),
        "no_evidence_limit": TuneableSpec("int", 6, 1, 30, "Force DIAGNOSE after N steps without evidence"),
    },

    # ---- auto_tuner: self-tuning engine ----
    "auto_tuner": {
        "enabled": TuneableSpec("bool", True, None, None, "Enable auto-tuner"),
        "mode": TuneableSpec("str", "apply", None, None, "Tuner mode",
                             ["apply", "suggest"]),
        "last_run": TuneableSpec("str", "", None, None, "Timestamp of last run"),
        "run_interval_s": TuneableSpec("int", 43200, 3600, 604800, "Run interval (s, default 12h)"),
        "max_change_per_run": TuneableSpec("float", 0.15, 0.01, 0.5, "Max boost change per run"),
        "source_boosts": TuneableSpec("dict", {}, None, None, "Per-source boost multipliers"),
        "min_boost": TuneableSpec("float", 0.2, 0.0, 2.0,
            "Floor for source boost — prevents auto-tuner from dampening proven sources below this value"),
        "max_boost": TuneableSpec("float", 2.0, 0.5, 2.0,
            "Ceiling for source boost — prevents runaway amplification of any single source"),
        "source_effectiveness": TuneableSpec("dict", {}, None, None, "Computed effectiveness rates"),
        "tuning_log": TuneableSpec("list", [], None, None, "Recent tuning events (max 50)"),
        "max_changes_per_cycle": TuneableSpec("int", 4, 1, 20, "Max source adjustments per cycle"),
        "apply_cross_section_recommendations": TuneableSpec(
            "bool", False, None, None,
            "Allow auto-tuner to write recommendations outside auto_tuner.source_boosts",
        ),
        "recommendation_sections_allowlist": TuneableSpec(
            "list", [], None, None,
            "Optional allowlist of sections auto-tuner may update when cross-section writes are enabled",
        ),
    },

    # ---- chip_merge: chip deduplication ----
    "chip_merge": {
        "duplicate_churn_ratio": TuneableSpec("float", 0.95, 0.5, 1.0, "Churn ratio for duplicate detection"),
        "duplicate_churn_min_processed": TuneableSpec("int", 20, 1, 1000, "Min processed before churn check"),
        "duplicate_churn_cooldown_s": TuneableSpec("int", 300, 30, 3600, "Churn check cooldown (s)"),
        "min_cognitive_value": TuneableSpec("float", 0.24, 0.0, 1.0, "Min cognitive value score"),
        "min_actionability": TuneableSpec("float", 0.18, 0.0, 1.0, "Min actionability score"),
        "min_transferability": TuneableSpec("float", 0.15, 0.0, 1.0, "Min transferability score"),
        "min_statement_len": TuneableSpec("int", 18, 5, 200, "Min statement length (chars)"),
    },

    # ---- advisory_quality: synthesis quality profile ----
    "advisory_quality": {
        "profile": TuneableSpec("str", "enhanced", None, None, "Quality profile name",
                                ["basic", "enhanced", "premium"]),
        "preferred_provider": TuneableSpec("str", "minimax", None, None, "Preferred provider"),
        "ai_timeout_s": TuneableSpec("float", 15.0, 0.5, 60.0, "AI timeout for quality synthesis"),
        "minimax_model": TuneableSpec("str", "MiniMax-M2.5", None, None, "MiniMax model name"),
        "source": TuneableSpec("str", "", None, None, "Config source identifier"),
        "updated_at": TuneableSpec("str", "", None, None, "Last update timestamp"),
    },

    # ---- advisory_preferences: user preference settings ----
    "advisory_preferences": {
        "memory_mode": TuneableSpec("str", "standard", None, None, "Memory mode",
                                    ["off", "standard", "replay"]),
        "guidance_style": TuneableSpec("str", "balanced", None, None, "Guidance style",
                                       ["concise", "balanced", "coach"]),
        "source": TuneableSpec("str", "", None, None, "Config source identifier"),
        "updated_at": TuneableSpec("str", "", None, None, "Last update timestamp"),
    },

    # ---- memory_emotion: emotional state matching ----
    "memory_emotion": {
        "enabled": TuneableSpec("bool", True, None, None, "Enable emotion context in retrieval"),
        "write_capture_enabled": TuneableSpec("bool", True, None, None, "Capture emotion on write"),
        "retrieval_state_match_weight": TuneableSpec("float", 0.22, 0.0, 1.0, "Weight for emotion state matching"),
        "retrieval_min_state_similarity": TuneableSpec("float", 0.3, 0.0, 1.0, "Min similarity for emotion match"),
    },

    # ---- memory_learning: learning signal weights ----
    "memory_learning": {
        "enabled": TuneableSpec("bool", True, None, None, "Enable learning signal in retrieval"),
        "retrieval_learning_weight": TuneableSpec("float", 0.25, 0.0, 1.0, "Weight for learning signal"),
        "retrieval_min_learning_signal": TuneableSpec("float", 0.2, 0.0, 1.0, "Min learning signal for match"),
        "calm_mode_bonus": TuneableSpec("float", 0.08, 0.0, 1.0, "Bonus for calm emotional state"),
    },

    # ---- memory_retrieval_guard: retrieval score guards ----
    "memory_retrieval_guard": {
        "enabled": TuneableSpec("bool", True, None, None, "Enable retrieval guard scoring"),
        "base_score_floor": TuneableSpec("float", 0.30, 0.0, 1.0, "Minimum base score before boosts"),
        "max_total_boost": TuneableSpec("float", 0.42, 0.0, 2.0, "Cap on total score boost"),
    },

    # ---- bridge_worker ----
    "bridge_worker": {
        "enabled": TuneableSpec("bool", True, None, None, "Enable bridge worker"),
        "mind_sync_enabled": TuneableSpec("bool", True, None, None, "Enable incremental Mind sync each cycle"),
        "mind_sync_limit": TuneableSpec("int", 20, 0, 200, "Max cognitive insights to sync to Mind per cycle"),
        "mind_sync_min_readiness": TuneableSpec("float", 0.45, 0.0, 1.0, "Min advisory readiness for Mind sync"),
        "mind_sync_min_reliability": TuneableSpec("float", 0.35, 0.0, 1.0, "Min reliability for Mind sync"),
        "mind_sync_max_age_s": TuneableSpec("int", 1209600, 0, 31536000, "Max insight age for Mind sync (s)"),
        "mind_sync_drain_queue": TuneableSpec("bool", True, None, None, "Drain bounded Mind offline queue each cycle"),
        "mind_sync_queue_budget": TuneableSpec("int", 25, 0, 1000, "Max offline queue entries drained per cycle"),
    },

    # ---- sync ----
    "sync": {
        "mode": TuneableSpec("str", "core", None, None, "Sync adapter mode", ["core", "all"]),
        "adapters_enabled": TuneableSpec("list", [], None, None, "Optional explicit sync target allowlist"),
        "adapters_disabled": TuneableSpec("list", [], None, None, "Optional sync target denylist"),
        "mind_limit": TuneableSpec("int", 2, 0, 6, "Max Mind highlights included in sync context"),
    },

    # ---- queue ----
    "queue": {
        "max_events": TuneableSpec("int", 10000, 100, 1000000, "Rotate queue after this many events"),
        "max_queue_bytes": TuneableSpec("int", 10485760, 1048576, 1073741824, "Max queue file size in bytes"),
        "compact_head_bytes": TuneableSpec("int", 5242880, 1048576, 134217728, "Head compaction target size in bytes"),
        "tail_chunk_bytes": TuneableSpec("int", 65536, 4096, 4194304, "Tail read chunk size in bytes"),
    },

    # ---- memory_capture ----
    "memory_capture": {
        "enabled": TuneableSpec("bool", True, None, None, "Enable memory capture"),
        "auto_save_threshold": TuneableSpec(
            "float", 0.65, 0.1, 1.0, "Importance threshold for auto-save",
        ),
        "suggest_threshold": TuneableSpec(
            "float", 0.55, 0.05, 0.99, "Importance threshold for suggestion queue",
        ),
        "max_capture_chars": TuneableSpec(
            "int", 2000, 200, 20000, "Max characters captured from source text",
        ),
    },

    # ---- request_tracker ----
    "request_tracker": {
        "max_pending": TuneableSpec("int", 50, 10, 500, "Max pending requests tracked"),
        "max_completed": TuneableSpec("int", 200, 50, 5000, "Max completed requests retained"),
        "max_age_seconds": TuneableSpec("float", 3600.0, 60.0, 604800.0, "Pending request timeout window"),
    },

    # ---- observatory: Obsidian pipeline visualization ----
    "observatory": {
        "enabled": TuneableSpec("bool", True, None, None, "Enable observatory generation"),
        "auto_sync": TuneableSpec("bool", True, None, None, "Auto-sync on bridge cycle"),
        "sync_cooldown_s": TuneableSpec("int", 120, 10, 3600, "Min seconds between auto-syncs"),
        "vault_dir": TuneableSpec("str", "", None, None, "Obsidian vault directory path"),
        "generate_canvas": TuneableSpec("bool", True, None, None, "Generate .canvas spatial view"),
        "max_recent_items": TuneableSpec("int", 20, 5, 100, "Max recent items per stage page"),
        "explore_cognitive_max": TuneableSpec("int", 200, 1, 5000, "Max cognitive insights to export as detail pages"),
        "explore_distillations_max": TuneableSpec("int", 200, 1, 5000, "Max EIDOS distillations to export"),
        "explore_episodes_max": TuneableSpec("int", 100, 1, 2000, "Max EIDOS episodes to export"),
        "explore_verdicts_max": TuneableSpec("int", 100, 1, 5000, "Max Meta-Ralph verdicts to export"),
        "explore_promotions_max": TuneableSpec("int", 200, 1, 5000, "Max promotion log entries to export"),
        "explore_advice_max": TuneableSpec("int", 200, 1, 5000, "Max advisory log entries to export"),
        "explore_routing_max": TuneableSpec("int", 100, 1, 5000, "Max retrieval routing decisions to export"),
        "explore_tuning_max": TuneableSpec("int", 200, 1, 5000, "Max tuneable evolution entries to export"),
        "explore_decisions_max": TuneableSpec("int", 200, 1, 5000, "Max advisory decision ledger entries to export"),
        "explore_feedback_max": TuneableSpec("int", 200, 1, 5000, "Max implicit feedback entries to export"),
    },

    # ---- production_gates: quality enforcement ----
    "production_gates": {
        "enforce_meta_ralph_quality_band": TuneableSpec("bool", True, None, None, "Enforce quality band check"),
        "min_quality_samples": TuneableSpec("int", 50, 5, 1000, "Min samples for quality gate"),
        "min_quality_rate": TuneableSpec("float", 0.3, 0.0, 1.0, "Min quality rate (floor)"),
        "max_quality_rate": TuneableSpec("float", 0.6, 0.0, 1.0, "Max quality rate (ceiling)"),
        "min_advisory_readiness_ratio": TuneableSpec("float", 0.40, 0.0, 1.0, "Min advisory store readiness ratio"),
        "min_advisory_freshness_ratio": TuneableSpec("float", 0.35, 0.0, 1.0, "Min advisory store freshness ratio"),
        "max_advisory_inactive_ratio": TuneableSpec("float", 0.40, 0.0, 1.0, "Max advisory inactive ratio"),
        "min_advisory_avg_effectiveness": TuneableSpec("float", 0.35, 0.0, 1.0, "Min advisory avg effectiveness"),
        "max_advisory_store_queue_depth": TuneableSpec("int", 1200, 0, 100000, "Max advisory prefetch queue depth"),
        "max_advisory_top_category_concentration": TuneableSpec("float", 0.85, 0.0, 1.0, "Max top category concentration"),
    },
}

# Sections with internal _doc keys that should not trigger unknown-key warnings
_DOC_KEY_SECTIONS: set = set()

# Module consumer map (which module reads which section)
SECTION_CONSUMERS: Dict[str, List[str]] = {
    "values": ["lib/pipeline.py", "lib/advisor.py", "lib/eidos/models.py"],
    "pipeline": ["lib/pipeline.py"],
    "semantic": ["lib/semantic_retriever.py", "lib/advisor.py"],
    "triggers": ["lib/advisor.py"],
    "promotion": ["lib/promoter.py", "lib/auto_promote.py"],
    "synthesizer": ["lib/advisory_synthesizer.py"],
    "advisory_engine": ["lib/advisory_engine.py"],
    "advisory_gate": ["lib/advisory_gate.py", "lib/advisory_state.py"],
    "advisory_packet_store": ["lib/advisory_packet_store.py"],
    "advisory_prefetch": ["lib/advisory_prefetch_worker.py"],
    "advisor": ["lib/advisor.py"],
    "retrieval": ["lib/advisor.py", "lib/semantic_retriever.py"],
    "meta_ralph": ["lib/meta_ralph.py"],
    "eidos": ["lib/eidos/models.py"],
    "auto_tuner": ["lib/auto_tuner.py"],
    "chip_merge": ["lib/chips/runtime.py", "lib/chip_merger.py"],
    "advisory_quality": ["lib/advisory_synthesizer.py"],
    "advisory_preferences": ["lib/advisory_preferences.py"],
    "memory_emotion": ["lib/memory_store.py", "lib/memory_banks.py"],
    "memory_learning": ["lib/memory_store.py"],
    "memory_retrieval_guard": ["lib/memory_store.py"],
    "bridge_worker": ["lib/bridge_cycle.py"],
    "sync": ["lib/context_sync.py"],
    "queue": ["lib/queue.py"],
    "memory_capture": ["lib/memory_capture.py"],
    "request_tracker": ["lib/pattern_detection/request_tracker.py"],
    "observatory": ["lib/observatory/config.py"],
    "production_gates": ["lib/production_gates.py"],
}


# --------------- Validation ---------------

def _validate_value(
    section: str, key: str, value: Any, spec: TuneableSpec,
) -> Tuple[Any, Optional[str]]:
    """Validate and coerce a single value. Returns (value, warning_or_None)."""
    if spec.type == "int":
        try:
            coerced = int(value)
        except (ValueError, TypeError):
            return spec.default, f"{section}.{key}: cannot convert {value!r} to int, using default {spec.default}"
        if spec.min_val is not None and coerced < spec.min_val:
            return spec.min_val, f"{section}.{key}: {coerced} below min {spec.min_val}, clamped"
        if spec.max_val is not None and coerced > spec.max_val:
            return spec.max_val, f"{section}.{key}: {coerced} above max {spec.max_val}, clamped"
        return coerced, None

    elif spec.type == "float":
        try:
            coerced = float(value)
        except (ValueError, TypeError):
            return spec.default, f"{section}.{key}: cannot convert {value!r} to float, using default {spec.default}"
        if spec.min_val is not None and coerced < spec.min_val:
            return float(spec.min_val), f"{section}.{key}: {coerced} below min {spec.min_val}, clamped"
        if spec.max_val is not None and coerced > spec.max_val:
            return float(spec.max_val), f"{section}.{key}: {coerced} above max {spec.max_val}, clamped"
        return coerced, None

    elif spec.type == "bool":
        if isinstance(value, bool):
            return value, None
        if isinstance(value, (int, float)):
            return bool(value), None
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True, None
        if text in ("0", "false", "no", "off"):
            return False, None
        return spec.default, f"{section}.{key}: cannot parse {value!r} as bool, using default {spec.default}"

    elif spec.type == "str":
        coerced = str(value).strip()
        if spec.enum_values and coerced not in spec.enum_values:
            return spec.default, f"{section}.{key}: {coerced!r} not in {spec.enum_values}, using default {spec.default!r}"
        return coerced, None

    elif spec.type in ("dict", "list"):
        expected_type = dict if spec.type == "dict" else list
        if isinstance(value, expected_type):
            return value, None
        return spec.default, f"{section}.{key}: expected {spec.type}, got {type(value).__name__}, using default"

    return value, None


def validate_tuneables(
    data: Dict[str, Any],
    *,
    schema: Optional[Dict[str, Dict[str, TuneableSpec]]] = None,
) -> ValidationResult:
    """Validate a tuneables dict against the schema.

    - Unknown sections: preserved with warning
    - Unknown keys within known sections: preserved with warning
    - Missing sections: filled with defaults from schema
    - Missing keys: filled with defaults
    - Out-of-bounds numeric values: clamped to min/max with warning
    - Wrong types: coerced where possible, warned, or default-filled
    """
    schema = schema or SCHEMA
    result = ValidationResult(data={})

    # 1) Process each known section
    for section_name, section_spec in schema.items():
        if section_name not in data:
            defaults = {k: spec.default for k, spec in section_spec.items()}
            result.data[section_name] = defaults
            result.defaults_applied.append(f"section:{section_name}")
            continue

        raw_section = data[section_name]
        if not isinstance(raw_section, dict):
            result.warnings.append(
                f"{section_name}: expected dict, got {type(raw_section).__name__}"
            )
            defaults = {k: spec.default for k, spec in section_spec.items()}
            result.data[section_name] = defaults
            continue

        cleaned_section: Dict[str, Any] = {}

        # 2) Validate each known key
        for key, spec in section_spec.items():
            if key not in raw_section:
                cleaned_section[key] = spec.default
                result.defaults_applied.append(f"{section_name}.{key}")
                continue

            raw_val = raw_section[key]
            validated_val, warning = _validate_value(section_name, key, raw_val, spec)
            cleaned_section[key] = validated_val
            if warning:
                result.warnings.append(warning)
                if "clamped" in warning.lower():
                    result.clamped.append(f"{section_name}.{key}")

        # 3) Preserve unknown keys with warning
        allow_doc_keys = section_name in _DOC_KEY_SECTIONS
        for key in raw_section:
            if key not in section_spec:
                cleaned_section[key] = raw_section[key]
                if key.startswith("_") or (allow_doc_keys and key == "_doc"):
                    continue  # Skip _doc, _comment etc.
                result.unknown_keys.append(f"{section_name}.{key}")
                result.warnings.append(
                    f"{section_name}.{key}: unknown key (possible typo?)"
                )

        result.data[section_name] = cleaned_section

    # 4) Preserve unknown top-level sections
    for section_name in data:
        if section_name not in schema and section_name != "updated_at":
            result.data[section_name] = data[section_name]
            if not section_name.startswith("_"):
                result.unknown_keys.append(f"section:{section_name}")
                result.warnings.append(
                    f"section:{section_name}: unknown section (possible typo?)"
                )

    # Always preserve updated_at
    if "updated_at" in data:
        result.data["updated_at"] = data["updated_at"]

    return result


# --------------- Helpers ---------------

def get_section_defaults(section_name: str) -> Dict[str, Any]:
    """Return default values for a section."""
    spec = SCHEMA.get(section_name, {})
    return {k: s.default for k, s in spec.items()}


def get_full_defaults() -> Dict[str, Any]:
    """Return a complete tuneables dict with all defaults."""
    return {section: get_section_defaults(section) for section in SCHEMA}


# --------------- Reference Doc Generator ---------------

def generate_reference_doc() -> str:
    """Generate a markdown reference document from the schema."""
    lines = [
        "# Tuneables Reference",
        "",
        "Auto-generated from `lib/tuneables_schema.py`. Do not edit manually.",
        "",
        f"**Sections:** {len(SCHEMA)}",
        f"**Total keys:** {sum(len(v) for v in SCHEMA.values())}",
        "",
        "## Overview",
        "",
        "All tuneables are stored in `~/.spark/tuneables.json` (runtime) and "
        "`config/tuneables.json` (version-controlled baseline).",
        "",
        "- **Validation**: `lib/tuneables_schema.py` validates on load",
        "- **Hot-reload**: `lib/tuneables_reload.py` watches for file changes",
        "- **Drift tracking**: `lib/tuneables_drift.py` monitors distance from baseline",
        "",
        "## Section Index",
        "",
    ]

    # Table of contents
    for section_name in SCHEMA:
        consumers = SECTION_CONSUMERS.get(section_name, [])
        consumer_str = ", ".join(f"`{c}`" for c in consumers) if consumers else "—"
        key_count = len(SCHEMA[section_name])
        lines.append(f"- [`{section_name}`](#{section_name}) ({key_count} keys) — {consumer_str}")
    lines.append("")

    # Section details
    for section_name, section_spec in SCHEMA.items():
        consumers = SECTION_CONSUMERS.get(section_name, [])
        consumer_str = ", ".join(f"`{c}`" for c in consumers) if consumers else "—"

        lines.append(f"## `{section_name}`")
        lines.append("")
        lines.append(f"**Consumed by:** {consumer_str}")
        lines.append("")
        lines.append("| Key | Type | Default | Min | Max | Description |")
        lines.append("|-----|------|---------|-----|-----|-------------|")

        for key, spec in section_spec.items():
            min_str = str(spec.min_val) if spec.min_val is not None else "—"
            max_str = str(spec.max_val) if spec.max_val is not None else "—"
            desc = spec.description
            if spec.enum_values:
                desc += f" ({', '.join(spec.enum_values)})"
            default_str = f"`{spec.default}`" if spec.default != "" else '`""`'
            lines.append(
                f"| `{key}` | {spec.type} | {default_str} | {min_str} | {max_str} | {desc} |"
            )
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # CLI: validate config/tuneables.json
    config_path = Path(__file__).resolve().parent.parent / "config" / "tuneables.json"
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        r = validate_tuneables(data)
        print(f"Validated: ok={r.ok}, warnings={len(r.warnings)}, "
              f"clamped={len(r.clamped)}, defaults_applied={len(r.defaults_applied)}, "
              f"unknown={len(r.unknown_keys)}")
        for w in r.warnings:
            print(f"  [WARN] {w}")
    else:
        print(f"Config not found: {config_path}")
