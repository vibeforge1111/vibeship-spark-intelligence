# Tuneables Reference

Auto-generated from `lib/tuneables_schema.py`. Do not edit manually.

**Sections:** 31
**Total keys:** 231

## Overview

All tuneables follow a **4-layer precedence model** managed by `lib/config_authority.py`:

1. **Schema defaults** (`lib/tuneables_schema.py`) — hardcoded baseline
2. **Versioned baseline** (`config/tuneables.json`) — checked into git
3. **Runtime overrides** (`~/.spark/tuneables.json`) — local machine state
4. **Environment overrides** — opt-in per key, highest priority

For the full architectural contract, see [`docs/CONFIG_AUTHORITY.md`](CONFIG_AUTHORITY.md).

- **Canonical reader**: `lib/config_authority.py` — all modules use `resolve_section()`
- **Validation**: `lib/tuneables_schema.py` validates on load
- **Hot-reload**: `lib/tuneables_reload.py` watches for file changes and notifies registered callbacks
- **Drift tracking**: `lib/tuneables_drift.py` monitors distance from baseline

## Reading Config in Code

Use `resolve_section()` from `lib/config_authority.py`. **Do not** read `tuneables.json` directly — direct reads bypass env overrides and schema defaults.

```python
from lib.config_authority import resolve_section, env_float, env_bool

# Basic usage — returns ResolvedSection(data, sources, warnings)
section = resolve_section("advisory_gate")
ttl = section.data.get("shown_advice_ttl_s", 600)

# With environment override support
section = resolve_section(
    "meta_ralph",
    env_overrides={
        "quality_threshold": env_float("SPARK_QUALITY_THRESHOLD", lo=0.0, hi=10.0),
    },
)
threshold = float(section.data.get("quality_threshold", 4.5))

# Source attribution — know where each value came from
for key, source in section.sources.items():
    print(f"  {key}: {source}")  # "schema", "baseline", "runtime", or "env:VAR_NAME"
```

**Env override helpers:** `env_bool()`, `env_int()`, `env_float()`, `env_str()` — each returns an `EnvOverride` with a parser that validates and clamps the value.

**Empty string fallback pattern:** When a schema default is `""` (meaning "use code default"), use `or` not `get(..., default)`:
```python
# Correct — empty string falls through to code default
vault_dir = str(section.data.get("vault_dir") or DEFAULT_PATH)

# Wrong — schema always provides the key, so fallback never triggers
vault_dir = str(section.data.get("vault_dir", DEFAULT_PATH))
```

## Section Index

- [`values`](#values) (10 keys) — `lib/pipeline.py`, `lib/advisor.py`, `lib/eidos/models.py`
- [`pipeline`](#pipeline) (7 keys) — `lib/pipeline.py`
- [`semantic`](#semantic) (17 keys) — `lib/semantic_retriever.py`, `lib/advisor.py`
- [`triggers`](#triggers) (2 keys) — `lib/advisor.py`
- [`promotion`](#promotion) (5 keys) — `lib/promoter.py`, `lib/auto_promote.py`
- [`synthesizer`](#synthesizer) (6 keys) — `lib/advisory_synthesizer.py`
- [`flow`](#flow) (1 keys) — —
- [`advisory_engine`](#advisory_engine) (16 keys) — `lib/advisory_engine.py`
- [`advisory_gate`](#advisory_gate) (13 keys) — `lib/advisory_gate.py`, `lib/advisory_state.py`
- [`advisory_packet_store`](#advisory_packet_store) (19 keys) — `lib/advisory_packet_store.py`
- [`advisory_prefetch`](#advisory_prefetch) (4 keys) — `lib/advisory_prefetch_worker.py`
- [`advisor`](#advisor) (20 keys) — `lib/advisor.py`
- [`retrieval`](#retrieval) (4 keys) — `lib/advisor.py`, `lib/semantic_retriever.py`
- [`meta_ralph`](#meta_ralph) (9 keys) — `lib/meta_ralph.py`
- [`eidos`](#eidos) (4 keys) — `lib/eidos/models.py`
- [`scheduler`](#scheduler) (1 keys) — `lib/bridge_cycle.py`
- [`source_roles`](#source_roles) (3 keys) — `lib/advisory_engine.py`, `lib/auto_tuner.py`
- [`auto_tuner`](#auto_tuner) (13 keys) — `lib/auto_tuner.py`
- [`chip_merge`](#chip_merge) (7 keys) — `lib/chips/runtime.py`, `lib/chip_merger.py`
- [`advisory_quality`](#advisory_quality) (6 keys) — `lib/advisory_synthesizer.py`
- [`advisory_preferences`](#advisory_preferences) (4 keys) — `lib/advisory_preferences.py`
- [`memory_emotion`](#memory_emotion) (4 keys) — `lib/memory_store.py`, `lib/memory_banks.py`
- [`memory_learning`](#memory_learning) (4 keys) — `lib/memory_store.py`
- [`memory_retrieval_guard`](#memory_retrieval_guard) (3 keys) — `lib/memory_store.py`
- [`bridge_worker`](#bridge_worker) (8 keys) — `lib/bridge_cycle.py`
- [`sync`](#sync) (4 keys) — `lib/context_sync.py`
- [`queue`](#queue) (4 keys) — `lib/queue.py`
- [`memory_capture`](#memory_capture) (4 keys) — `lib/memory_capture.py`
- [`request_tracker`](#request_tracker) (3 keys) — `lib/pattern_detection/request_tracker.py`
- [`observatory`](#observatory) (16 keys) — `lib/observatory/config.py`
- [`production_gates`](#production_gates) (10 keys) — `lib/production_gates.py`

## `values`

**Consumed by:** `lib/pipeline.py`, `lib/advisor.py`, `lib/eidos/models.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `min_occurrences` | int | `1` | 1 | 100 | Min observations before learning |
| `min_occurrences_critical` | int | `1` | 1 | 100 | Min observations for critical insights |
| `confidence_threshold` | float | `0.6` | 0.0 | 1.0 | Confidence threshold for acceptance |
| `gate_threshold` | float | `0.45` | 0.0 | 1.0 | Quality gate threshold |
| `max_retries_per_error` | int | `3` | 1 | 20 | Max retries per error type |
| `max_file_touches` | int | `5` | 1 | 50 | Max file modifications per episode |
| `no_evidence_steps` | int | `6` | 1 | 30 | Steps without evidence before DIAGNOSE |
| `max_steps` | int | `40` | 5 | 200 | Max episode steps |
| `advice_cache_ttl` | int | `180` | 10 | 3600 | Advice cache TTL in seconds |
| `queue_batch_size` | int | `100` | 50 | 1000 | Event queue batch processing size |

## `pipeline`

**Consumed by:** `lib/pipeline.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `importance_sampling_enabled` | bool | `False` | — | — | Enable backlog importance sampling |
| `low_priority_keep_rate` | float | `0.25` | 0.0 | 1.0 | Retention rate for low-priority events when sampling |
| `macros_enabled` | bool | `False` | — | — | Enable macro workflow mining |
| `macro_min_count` | int | `3` | 2 | 20 | Min pattern count for macro extraction |
| `min_insights_floor` | int | `1` | 0 | 3 | Minimum insights generated on high-volume cycles |
| `floor_events_threshold` | int | `20` | 1 | 200 | Event threshold to apply min_insights_floor |
| `floor_soft_min_events` | int | `2` | 1 | 50 | Soft minimum events for floor eligibility |

## `semantic`

**Consumed by:** `lib/semantic_retriever.py`, `lib/advisor.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `enabled` | bool | `True` | — | — | Enable semantic retrieval |
| `min_similarity` | float | `0.5` | 0.0 | 1.0 | Min cosine similarity for retrieval |
| `min_fusion_score` | float | `0.5` | 0.0 | 1.0 | Min fusion score for advisory ranking |
| `weight_recency` | float | `0.1` | 0.0 | 1.0 | Recency weight in fusion scoring |
| `weight_outcome` | float | `0.45` | 0.0 | 1.0 | Outcome weight in fusion scoring |
| `mmr_lambda` | float | `0.5` | 0.0 | 1.0 | MMR diversity parameter |
| `dedupe_similarity` | float | `0.88` | 0.0 | 1.0 | Similarity threshold for deduplication |
| `index_on_write` | bool | `True` | — | — | Index new entries on write |
| `index_on_read` | bool | `True` | — | — | Rebuild index on read if stale |
| `index_backfill_limit` | int | `500` | 0 | 10000 | Max entries to backfill on index build |
| `index_cache_ttl_seconds` | int | `120` | 10 | 3600 | Index cache TTL |
| `exclude_categories` | list | `[]` | — | — | Categories to exclude from retrieval |
| `category_caps` | dict | `{}` | — | — | Per-category result limits |
| `category_exclude` | list | `[]` | — | — | Categories to exclude |
| `log_retrievals` | bool | `True` | — | — | Log retrieval operations |
| `rescue_min_similarity` | float | `0.3` | 0.0 | 1.0 | Rescue path minimum similarity |
| `rescue_min_fusion_score` | float | `0.2` | 0.0 | 1.0 | Rescue path minimum fusion score |

## `triggers`

**Consumed by:** `lib/advisor.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `enabled` | bool | `True` | — | — | Enable trigger rules |
| `rules_file` | str | `""` | — | — | Path to trigger rules YAML |

## `promotion`

**Consumed by:** `lib/promoter.py`, `lib/auto_promote.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `adapter_budgets` | dict | `{}` | — | — | Per-adapter max item budgets |
| `confidence_floor` | float | `0.9` | 0.0 | 1.0 | Min confidence for promotion |
| `min_age_hours` | float | `2.0` | 0.0 | 168.0 | Min age in hours before promotion |
| `auto_interval_s` | int | `3600` | 300 | 86400 | Auto-promotion check interval |
| `threshold` | float | `0.5` | 0.0 | 1.0 | Promotion threshold score |

## `synthesizer`

**Consumed by:** `lib/advisory_synthesizer.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `mode` | str | `auto` | — | — | Synthesis mode (auto, ai_only, programmatic) |
| `ai_timeout_s` | float | `10.0` | 0.5 | 60.0 | AI synthesis timeout |
| `cache_ttl_s` | int | `120` | 0 | 3600 | Synthesis cache TTL |
| `max_cache_entries` | int | `50` | 1 | 500 | Max cached synthesis results |
| `preferred_provider` | str | `minimax` | — | — | Preferred AI provider (minimax, ollama, gemini, openai, anthropic) |
| `minimax_model` | str | `MiniMax-M2.5` | — | — | MiniMax model name |

## `flow`

**Consumed by:** —

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `validate_and_store_enabled` | bool | `True` | — | — | Enable unified validate_and_store_insight entry point. When False, callers bypass Meta-Ralph and write directly to cognitive store |

## `advisory_engine`

**Consumed by:** `lib/advisory_engine.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `enabled` | bool | `True` | — | — | Enable the advisory engine |
| `max_ms` | float | `4000` | 250 | 20000 | Max advisory engine time budget in ms |
| `include_mind` | bool | `False` | — | — | Include Mind memory in advisory |
| `prefetch_queue_enabled` | bool | `False` | — | — | Enable prefetch queue |
| `prefetch_inline_enabled` | bool | `True` | — | — | Enable inline prefetch |
| `prefetch_inline_max_jobs` | int | `1` | 0 | 10 | Max inline prefetch jobs |
| `delivery_stale_s` | float | `600` | 60 | 86400 | Delivery staleness threshold (s) |
| `advisory_text_repeat_cooldown_s` | float | `300` | 30 | 86400 | Text repeat cooldown (s). Prevents identical text from re-emitting. See also: advisory_gate.advice_repeat_cooldown_s (same advice_id), advisory_gate.shown_advice_ttl_s (shown-state marker) |
| `global_dedupe_cooldown_s` | float | `600` | 0 | 86400 | Cross-session global dedupe cooldown (s). Prevents same insight across sessions. Distinct from text_repeat (exact text) and advice_repeat (same ID) |
| `actionability_enforce` | bool | `True` | — | — | Enforce actionability scoring |
| `force_programmatic_synth` | bool | `False` | — | — | Force programmatic synthesis |
| `selective_ai_synth_enabled` | bool | `True` | — | — | Enable selective AI synthesis |
| `selective_ai_min_remaining_ms` | float | `1800` | 0 | 20000 | Min ms remaining for AI synth |
| `selective_ai_min_authority` | str | `whisper` | — | — | Min authority for AI synth (silent, whisper, note, warning, block) |
| `fallback_budget_cap` | int | `1` | 0 | 10 | Max fallback emissions per budget window. 0 = unlimited (old behavior) |
| `fallback_budget_window` | int | `5` | 1 | 100 | Number of tool calls per fallback budget window |

## `advisory_gate`

**Consumed by:** `lib/advisory_gate.py`, `lib/advisory_state.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `max_emit_per_call` | int | `2` | 1 | 10 | Max advice items emitted per tool call |
| `tool_cooldown_s` | int | `15` | 1 | 3600 | Same-tool suppression cooldown (s) |
| `advice_repeat_cooldown_s` | int | `300` | 5 | 86400 | Repeated advice cooldown (s). Prevents same advice_id from re-emitting. See also: advisory_engine.advisory_text_repeat_cooldown_s (exact text), shown_advice_ttl_s (shown-state marker with source TTL scaling) |
| `agreement_gate_enabled` | bool | `False` | — | — | Escalate warnings only when multiple sources agree |
| `agreement_min_sources` | int | `2` | 1 | 5 | Minimum agreeing sources for escalation when agreement gate is enabled |
| `shown_advice_ttl_s` | int | `600` | 5 | 86400 | Shown-advice suppression TTL (s). Base TTL for shown-state markers; scaled per-source via source_ttl_multipliers and per-category via category_cooldown_multipliers. Primary suppression mechanism (~69% of all suppressions) |
| `category_cooldown_multipliers` | dict | `{}` | — | — | Per-category cooldown multipliers (e.g., {"security": 2.0, "mind": 0.5}) |
| `source_ttl_multipliers` | dict | `{}` | — | — | Per-source shown TTL scale factors. Low-value sources (baseline=0.5x) get shorter TTL; high-quality sources (cognitive=1.0x) keep full TTL |
| `tool_cooldown_multipliers` | dict | `{}` | — | — | Per-tool cooldown scale factors. Exploration tools (Read=0.5x) get shorter cooldown; mutation tools (Edit=1.2x) keep longer cooldown |
| `warning_threshold` | float | `0.68` | 0.2 | 0.99 | Score threshold for WARNING authority |
| `note_threshold` | float | `0.38` | 0.1 | 0.95 | Score threshold for NOTE authority |
| `whisper_threshold` | float | `0.27` | 0.01 | 0.9 | Score threshold for WHISPER authority |
| `emit_whispers` | bool | `True` | — | — | Whether to emit WHISPER-level advice |

## `advisory_packet_store`

**Consumed by:** `lib/advisory_packet_store.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `packet_ttl_s` | int | `600` | 60 | 7200 | Packet time-to-live (s) |
| `max_index_packets` | int | `2000` | 100 | 50000 | Max packets in index |
| `relaxed_effectiveness_weight` | float | `2.0` | 0.0 | 10.0 | Effectiveness weight (relaxed mode) |
| `relaxed_low_effectiveness_threshold` | float | `0.3` | 0.0 | 1.0 | Low effectiveness threshold |
| `relaxed_low_effectiveness_penalty` | float | `0.5` | 0.0 | 1.0 | Low effectiveness penalty |
| `relaxed_max_candidates` | int | `6` | 1 | 30 | Top N rows to consider in relaxed match |
| `packet_lookup_candidates` | int | `6` | 1 | 30 | Top N relaxed match candidates to score |
| `packet_lookup_llm_enabled` | bool | `False` | — | — | Enable LLM-assisted relaxed lookup rerank |
| `packet_lookup_llm_provider` | str | `minimax` | — | — | LLM provider for packet rerank |
| `packet_lookup_llm_timeout_s` | float | `1.2` | 0.2 | 10.0 | Packet lookup LLM timeout (s) |
| `packet_lookup_llm_top_k` | int | `3` | 1 | 20 | LLM rerank top-K responses |
| `packet_lookup_llm_min_candidates` | int | `2` | 1 | 20 | Min candidate count before LLM rerank |
| `packet_lookup_llm_context_chars` | int | `220` | 40 | 5000 | Max context chars sent to lookup LLM |
| `packet_lookup_llm_provider_url` | str | `https://api.minimax.io/v1` | — | — | Base URL for lookup LLM provider |
| `packet_lookup_llm_model` | str | `MiniMax-M2.5` | — | — | Model for lookup LLM |
| `obsidian_enabled` | bool | `False` | — | — | Enable advisory packet export to Obsidian |
| `obsidian_auto_export` | bool | `False` | — | — | Auto-export packet payloads to Obsidian |
| `obsidian_export_max_packets` | int | `300` | 1 | 5000 | Max Obsidian packet exports to retain |
| `obsidian_export_dir` | str | `` | — | — | Override Obsidian export directory (empty = ~/.spark/advice_packets/obsidian) |

## `advisory_prefetch`

**Consumed by:** `lib/advisory_prefetch_worker.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `worker_enabled` | bool | `False` | — | — | Enable background prefetch worker |
| `max_jobs_per_run` | int | `2` | 1 | 50 | Max prefetch jobs per cycle |
| `max_tools_per_job` | int | `3` | 1 | 10 | Max tools to prefetch per job |
| `min_probability` | float | `0.25` | 0.0 | 1.0 | Min probability threshold for prefetch |

## `advisor`

**Consumed by:** `lib/advisor.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `min_reliability` | float | `0.6` | 0.0 | 1.0 | Min reliability for advice |
| `min_validations_strong` | int | `2` | 1 | 20 | Min validations for strong advice |
| `max_items` | int | `4` | 1 | 20 | Max advice items per call |
| `cache_ttl` | int | `180` | 10 | 3600 | Advice cache TTL (s) |
| `min_rank_score` | float | `0.4` | 0.0 | 1.0 | Min fusion rank score |
| `max_advice_items` | int | `5` | 1 | 20 | Max advice items (alternate key) |
| `mind_max_stale_s` | int | `86400` | 0 | 604800 | Max Mind staleness (s) |
| `mind_stale_allow_if_empty` | bool | `False` | — | — | Allow stale Mind if empty |
| `mind_min_salience` | float | `0.55` | 0.0 | 1.0 | Min Mind memory salience |
| `mind_reserve_slots` | int | `1` | 0 | 4 | Reserved top advice slots for Mind |
| `mind_reserve_min_rank` | float | `0.45` | 0.0 | 1.0 | Min rank score for reserved Mind slots |
| `replay_enabled` | bool | `True` | — | — | Enable replay advisory |
| `replay_min_strict` | int | `5` | 1 | 100 | Min strict samples for replay |
| `replay_min_delta` | float | `0.25` | 0.0 | 1.0 | Min improvement delta for replay |
| `replay_max_age_s` | int | `1209600` | 3600 | 2592000 | Max replay age (s, default 14d) |
| `replay_strict_window_s` | int | `1500` | 60 | 86400 | Strict replay window (s) |
| `replay_min_context` | float | `0.24` | 0.0 | 1.0 | Min context match for replay |
| `replay_max_records` | int | `2500` | 100 | 50000 | Max replay records |
| `replay_mode` | str | `standard` | — | — | Replay mode (off, standard, replay) |
| `guidance_style` | str | `balanced` | — | — | Guidance verbosity (concise, balanced, coach) |

## `retrieval`

**Consumed by:** `lib/advisor.py`, `lib/semantic_retriever.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `level` | str | `2` | — | — | Retrieval complexity level |
| `overrides` | dict | `{}` | — | — | Retrieval parameter overrides |
| `domain_profile_enabled` | bool | `True` | — | — | Enable domain-specific profiles |
| `domain_profiles` | dict | `{}` | — | — | Per-domain retrieval profiles |

## `meta_ralph`

**Consumed by:** `lib/meta_ralph.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `quality_threshold` | float | `4.5` | 0.0 | 10.0 | Score floor for promotion |
| `needs_work_threshold` | int | `2` | 0 | 10 | Score range for refinement |
| `needs_work_close_delta` | float | `0.5` | 0.0 | 3.0 | Proximity threshold for close-to-passing |
| `min_outcome_samples` | int | `5` | 1 | 100 | Min outcomes before quality scoring |
| `min_tuneable_samples` | int | `50` | 5 | 1000 | Min samples for tuneable validation |
| `min_needs_work_samples` | int | `5` | 1 | 100 | Min samples for needs_work verdict |
| `min_source_samples` | int | `15` | 1 | 200 | Min samples per source |
| `attribution_window_s` | int | `1800` | 60 | 86400 | Time window for attribution (s) |
| `strict_attribution_require_trace` | bool | `True` | — | — | Require trace for strict attribution |

## `eidos`

**Consumed by:** `lib/eidos/models.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `max_time_seconds` | int | `1200` | 60 | 7200 | Max episode time (s) |
| `max_retries_per_error` | int | `3` | 1 | 20 | Retry limit per error type |
| `max_file_touches` | int | `5` | 1 | 50 | Max times to modify same file |
| `no_evidence_limit` | int | `6` | 1 | 30 | Force DIAGNOSE after N steps without evidence |

## `scheduler`

**Consumed by:** `lib/bridge_cycle.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `enabled` | bool | `True` | — | — | Enable the scheduler |

## `source_roles`

**Consumed by:** `lib/advisory_engine.py`, `lib/auto_tuner.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `distillers` | dict | `{}` | — | — | Sources that distill/learn (not advisory) |
| `direct_advisory` | dict | `{}` | — | — | Sources that advise directly |
| `disabled_from_advisory` | dict | `{}` | — | — | Sources removed from advisory |

## `auto_tuner`

**Consumed by:** `lib/auto_tuner.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `enabled` | bool | `True` | — | — | Enable auto-tuner |
| `mode` | str | `apply` | — | — | Tuner mode (apply, suggest) |
| `last_run` | str | `""` | — | — | Timestamp of last run |
| `run_interval_s` | int | `43200` | 3600 | 604800 | Run interval (s, default 12h) |
| `max_change_per_run` | float | `0.15` | 0.01 | 0.5 | Max boost change per run |
| `source_boosts` | dict | `{}` | — | — | Per-source boost multipliers |
| `min_boost` | float | `0.2` | 0.0 | 2.0 | Floor for source boost — prevents auto-tuner from dampening proven sources below this value |
| `max_boost` | float | `2.0` | 0.5 | 2.0 | Ceiling for source boost — prevents runaway amplification of any single source |
| `source_effectiveness` | dict | `{}` | — | — | Computed effectiveness rates |
| `tuning_log` | list | `[]` | — | — | Recent tuning events (max 50) |
| `max_changes_per_cycle` | int | `4` | 1 | 20 | Max source adjustments per cycle |
| `apply_cross_section_recommendations` | bool | `False` | — | — | Allow auto-tuner to write recommendations outside auto_tuner.source_boosts |
| `recommendation_sections_allowlist` | list | `[]` | — | — | Optional allowlist of sections auto-tuner may update when cross-section writes are enabled |

## `chip_merge`

**Consumed by:** `lib/chips/runtime.py`, `lib/chip_merger.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `duplicate_churn_ratio` | float | `0.95` | 0.5 | 1.0 | Churn ratio for duplicate detection |
| `duplicate_churn_min_processed` | int | `20` | 1 | 1000 | Min processed before churn check |
| `duplicate_churn_cooldown_s` | int | `300` | 30 | 3600 | Churn check cooldown (s) |
| `min_cognitive_value` | float | `0.24` | 0.0 | 1.0 | Min cognitive value score |
| `min_actionability` | float | `0.18` | 0.0 | 1.0 | Min actionability score |
| `min_transferability` | float | `0.15` | 0.0 | 1.0 | Min transferability score |
| `min_statement_len` | int | `18` | 5 | 200 | Min statement length (chars) |

## `advisory_quality`

**Consumed by:** `lib/advisory_synthesizer.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `profile` | str | `enhanced` | — | — | Quality profile name (basic, enhanced, premium) |
| `preferred_provider` | str | `minimax` | — | — | Preferred provider |
| `ai_timeout_s` | float | `15.0` | 0.5 | 60.0 | AI timeout for quality synthesis |
| `minimax_model` | str | `MiniMax-M2.5` | — | — | MiniMax model name |
| `source` | str | `""` | — | — | Config source identifier |
| `updated_at` | str | `""` | — | — | Last update timestamp |

## `advisory_preferences`

**Consumed by:** `lib/advisory_preferences.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `memory_mode` | str | `standard` | — | — | Memory mode (off, standard, replay) |
| `guidance_style` | str | `balanced` | — | — | Guidance style (concise, balanced, coach) |
| `source` | str | `""` | — | — | Config source identifier |
| `updated_at` | str | `""` | — | — | Last update timestamp |

## `memory_emotion`

**Consumed by:** `lib/memory_store.py`, `lib/memory_banks.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `enabled` | bool | `True` | — | — | Enable emotion context in retrieval |
| `write_capture_enabled` | bool | `True` | — | — | Capture emotion on write |
| `retrieval_state_match_weight` | float | `0.22` | 0.0 | 1.0 | Weight for emotion state matching |
| `retrieval_min_state_similarity` | float | `0.3` | 0.0 | 1.0 | Min similarity for emotion match |

## `memory_learning`

**Consumed by:** `lib/memory_store.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `enabled` | bool | `True` | — | — | Enable learning signal in retrieval |
| `retrieval_learning_weight` | float | `0.25` | 0.0 | 1.0 | Weight for learning signal |
| `retrieval_min_learning_signal` | float | `0.2` | 0.0 | 1.0 | Min learning signal for match |
| `calm_mode_bonus` | float | `0.08` | 0.0 | 1.0 | Bonus for calm emotional state |

## `memory_retrieval_guard`

**Consumed by:** `lib/memory_store.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `enabled` | bool | `True` | — | — | Enable retrieval guard scoring |
| `base_score_floor` | float | `0.3` | 0.0 | 1.0 | Minimum base score before boosts |
| `max_total_boost` | float | `0.42` | 0.0 | 2.0 | Cap on total score boost |

## `bridge_worker`

**Consumed by:** `lib/bridge_cycle.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `enabled` | bool | `True` | — | — | Enable bridge worker |
| `mind_sync_enabled` | bool | `True` | — | — | Enable incremental Mind sync each cycle |
| `mind_sync_limit` | int | `20` | 0 | 200 | Max cognitive insights to sync to Mind per cycle |
| `mind_sync_min_readiness` | float | `0.45` | 0.0 | 1.0 | Min advisory readiness for Mind sync |
| `mind_sync_min_reliability` | float | `0.35` | 0.0 | 1.0 | Min reliability for Mind sync |
| `mind_sync_max_age_s` | int | `1209600` | 0 | 31536000 | Max insight age for Mind sync (s) |
| `mind_sync_drain_queue` | bool | `True` | — | — | Drain bounded Mind offline queue each cycle |
| `mind_sync_queue_budget` | int | `25` | 0 | 1000 | Max offline queue entries drained per cycle |

## `sync`

**Consumed by:** `lib/context_sync.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `mode` | str | `core` | — | — | Sync adapter mode (core, all) |
| `adapters_enabled` | list | `[]` | — | — | Optional explicit sync target allowlist |
| `adapters_disabled` | list | `[]` | — | — | Optional sync target denylist |
| `mind_limit` | int | `2` | 0 | 6 | Max Mind highlights included in sync context |

## `queue`

**Consumed by:** `lib/queue.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `max_events` | int | `10000` | 100 | 1000000 | Rotate queue after this many events |
| `max_queue_bytes` | int | `10485760` | 1048576 | 1073741824 | Max queue file size in bytes |
| `compact_head_bytes` | int | `5242880` | 1048576 | 134217728 | Head compaction target size in bytes |
| `tail_chunk_bytes` | int | `65536` | 4096 | 4194304 | Tail read chunk size in bytes |

## `memory_capture`

**Consumed by:** `lib/memory_capture.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `enabled` | bool | `True` | — | — | Enable memory capture |
| `auto_save_threshold` | float | `0.65` | 0.1 | 1.0 | Importance threshold for auto-save |
| `suggest_threshold` | float | `0.55` | 0.05 | 0.99 | Importance threshold for suggestion queue |
| `max_capture_chars` | int | `2000` | 200 | 20000 | Max characters captured from source text |

## `request_tracker`

**Consumed by:** `lib/pattern_detection/request_tracker.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `max_pending` | int | `50` | 10 | 500 | Max pending requests tracked |
| `max_completed` | int | `200` | 50 | 5000 | Max completed requests retained |
| `max_age_seconds` | float | `3600.0` | 60.0 | 604800.0 | Pending request timeout window |

## `observatory`

**Consumed by:** `lib/observatory/config.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `enabled` | bool | `True` | — | — | Enable observatory generation |
| `auto_sync` | bool | `True` | — | — | Auto-sync on bridge cycle |
| `sync_cooldown_s` | int | `120` | 10 | 3600 | Min seconds between auto-syncs |
| `vault_dir` | str | `""` | — | — | Obsidian vault directory path |
| `generate_canvas` | bool | `True` | — | — | Generate .canvas spatial view |
| `max_recent_items` | int | `20` | 5 | 100 | Max recent items per stage page |
| `explore_cognitive_max` | int | `200` | 1 | 5000 | Max cognitive insights to export as detail pages |
| `explore_distillations_max` | int | `200` | 1 | 5000 | Max EIDOS distillations to export |
| `explore_episodes_max` | int | `100` | 1 | 2000 | Max EIDOS episodes to export |
| `explore_verdicts_max` | int | `100` | 1 | 5000 | Max Meta-Ralph verdicts to export |
| `explore_promotions_max` | int | `200` | 1 | 5000 | Max promotion log entries to export |
| `explore_advice_max` | int | `200` | 1 | 5000 | Max advisory log entries to export |
| `explore_routing_max` | int | `100` | 1 | 5000 | Max retrieval routing decisions to export |
| `explore_tuning_max` | int | `200` | 1 | 5000 | Max tuneable evolution entries to export |
| `explore_decisions_max` | int | `200` | 1 | 5000 | Max advisory decision ledger entries to export |
| `explore_feedback_max` | int | `200` | 1 | 5000 | Max implicit feedback entries to export |

## `production_gates`

**Consumed by:** `lib/production_gates.py`

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `enforce_meta_ralph_quality_band` | bool | `True` | — | — | Enforce quality band check |
| `min_quality_samples` | int | `50` | 5 | 1000 | Min samples for quality gate |
| `min_quality_rate` | float | `0.3` | 0.0 | 1.0 | Min quality rate (floor) |
| `max_quality_rate` | float | `0.6` | 0.0 | 1.0 | Max quality rate (ceiling) |
| `min_advisory_readiness_ratio` | float | `0.4` | 0.0 | 1.0 | Min advisory store readiness ratio |
| `min_advisory_freshness_ratio` | float | `0.35` | 0.0 | 1.0 | Min advisory store freshness ratio |
| `max_advisory_inactive_ratio` | float | `0.4` | 0.0 | 1.0 | Max advisory inactive ratio |
| `min_advisory_avg_effectiveness` | float | `0.35` | 0.0 | 1.0 | Min advisory avg effectiveness |
| `max_advisory_store_queue_depth` | int | `1200` | 0 | 100000 | Max advisory prefetch queue depth |
| `max_advisory_top_category_concentration` | float | `0.85` | 0.0 | 1.0 | Max top category concentration |

