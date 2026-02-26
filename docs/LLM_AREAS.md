# LLM Areas: 30 Configurable LLM-Assisted Hooks

Spark Intelligence has 30 optional LLM-assisted areas spread across the learning pipeline and system architecture. Each area is individually configurable: enable/disable, choose a provider, set timeout and max output length.

**All areas default to disabled (opt-in).** When disabled, each area returns its input unchanged with zero LLM cost.

---

## Quick Start

### Enable a single area

Edit `~/.spark/tuneables.json`:

```json
{
  "llm_areas": {
    "archive_rewrite_enabled": true,
    "archive_rewrite_provider": "minimax"
  }
}
```

### Enable all areas at once

```python
from lib.intelligence_llm_preferences import apply_runtime_llm_preferences
apply_runtime_llm_preferences(llm_areas_enable=True, provider="minimax")
```

### Enable specific areas

```python
from lib.intelligence_llm_preferences import apply_runtime_llm_preferences
apply_runtime_llm_preferences(
    llm_areas_enable=True,
    llm_areas_list=["archive_rewrite", "meta_ralph_remediate", "retrieval_rewrite"],
    provider="ollama",
)
```

### Check status

```python
from lib.llm_dispatch import get_all_area_configs
configs = get_all_area_configs()
for area_id, cfg in configs.items():
    if cfg["enabled"]:
        print(f"  {area_id}: {cfg['provider']} ({cfg['timeout_s']}s)")
```

Or view the Observatory page: `_observatory/llm_areas_status.md` in your Obsidian vault.

---

## Architecture

```
Caller (meta_ralph.py, advisor.py, etc.)
    |
    v
llm_area_call(area_id, prompt, fallback=...)    # lib/llm_dispatch.py
    |
    +-- resolve_section("llm_areas")             # config_authority.py
    |      reads: config/tuneables.json (baseline)
    |              ~/.spark/tuneables.json (runtime)
    |
    +-- if disabled -> return fallback immediately
    |
    +-- _dispatch_provider(provider, prompt, timeout)
    |      delegates to advisory_synthesizer._query_provider()
    |      or ask_claude() for "claude" provider
    |
    v
LLMAreaResult(text, used_llm, provider, latency_ms, area_id)
```

### Key files

| File | Purpose |
| --- | --- |
| `lib/llm_dispatch.py` | Central dispatch, config resolution, area registry |
| `lib/llm_area_prompts.py` | System prompts and templates for all 30 areas |
| `config/tuneables.json` | Baseline defaults (version-controlled) |
| `~/.spark/tuneables.json` | Runtime overrides (user-local) |
| `lib/tuneables_schema.py` | Schema with TuneableSpec entries for validation |
| `lib/intelligence_llm_preferences.py` | CLI helper for bulk enable/disable |
| `lib/observatory/llm_areas_status.py` | Obsidian Observatory status page |

### Config resolution

Each area has 4 config keys under the `llm_areas` section:

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `{area_id}_enabled` | bool | `false` | Enable/disable this area |
| `{area_id}_provider` | string | `minimax` | LLM provider |
| `{area_id}_timeout_s` | float | varies (4-10s) | Max wait time |
| `{area_id}_max_chars` | int | varies (100-600) | Max output length |

### Valid providers

`auto`, `minimax`, `ollama`, `gemini`, `openai`, `anthropic`, `claude`

- `auto` resolves to `minimax` (cheapest/fastest default)
- `claude` calls `ask_claude()` via CLI (uses Claude credits)

### Hot-reload

The `llm_areas` section supports hot-reload via `tuneables_reload`. Changes to `~/.spark/tuneables.json` take effect on the next `llm_area_call()` without restarting services (config is read fresh each call).

---

## Learning System Areas (20)

### 1. Archive Recovery Chain

These form the archive recovery pipeline for suppressed items.

| # | Area ID | Host Module | Hook Point | What it does |
| --- | --- | --- | --- | --- |
| 1 | `archive_rewrite` | distillation_refiner.py | After component composition | Rewrites suppressed statements to pass quality gates |
| 2 | `archive_rescue` | distillation_refiner.py | Low-unified-score items | Evaluates if suppressed items contain genuine insight |
| 15 | `unsuppression_score` | meta_ralph.py | After suppression | Scores rescue potential (0.0-1.0) for suppressed items |
| 16 | `soft_promotion_triage` | promoter.py | Before promotion decision | Decides if an insight is ready for CLAUDE.md promotion |

### 2. Meta-Ralph Quality Loop

Improve the quality gate feedback loop.

| # | Area ID | Host Module | Hook Point | What it does |
| --- | --- | --- | --- | --- |
| 11 | `meta_ralph_remediate` | meta_ralph.py | After NEEDS_WORK verdict | Generates specific fix suggestions for failed items |
| 14 | `reasoning_patch` | distillation_transformer.py | During reasoning scoring | Improves causal reasoning chains |

### 3. Statement Enhancement

Boost statement quality before the quality gate.

| # | Area ID | Host Module | Hook Point | What it does |
| --- | --- | --- | --- | --- |
| 12 | `actionability_boost` | distillation_transformer.py | During actionability scoring | Adds concrete action verbs to vague insights |
| 13 | `specificity_augment` | distillation_transformer.py | During specificity scoring | Adds specific details (paths, versions, values) |
| 3 | `system28_reformulate` | distillation_transformer.py | After structure extraction | Restructures to WHEN/DO/BECAUSE format |

### 4. Memory Pipeline

Improve memory capture and storage quality.

| # | Area ID | Host Module | Hook Point | What it does |
| --- | --- | --- | --- | --- |
| 5 | `evidence_compress` | cognitive_learner.py | Before storing insight | Compresses verbose evidence to key facts |
| 6 | `novelty_score` | memory_capture.py | During importance scoring | Semantic novelty check against existing memories |
| 10 | `generic_demotion` | cognitive_learner.py | During retrieval | Classifies and demotes too-generic entries |

### 5. Retrieval Enhancement

Better retrieval through query rewriting and result annotation.

| # | Area ID | Host Module | Hook Point | What it does |
| --- | --- | --- | --- | --- |
| 8 | `retrieval_rewrite` | advisor.py | Before retrieval execution | Expands queries with related terms |
| 9 | `retrieval_explain` | advisor.py | After retrieval | Annotates results with relevance explanations |

### 6. Conflict & Signal Detection

Handle contradictions and rescue missed signals.

| # | Area ID | Host Module | Hook Point | What it does |
| --- | --- | --- | --- | --- |
| 4 | `conflict_resolve` | cognitive_learner.py | When insight contradicts existing | Resolves contradictions (merge/pick/conditional) |
| 7 | `missed_signal_detect` | memory_capture.py | At low-score filter | Gives a second chance to items scored too low |

### 7. Feedback & Outcomes

Better outcome tracking and implicit feedback extraction.

| # | Area ID | Host Module | Hook Point | What it does |
| --- | --- | --- | --- | --- |
| 17 | `outcome_link_reconstruct` | eidos/distillation_engine.py | During distillation | Links orphaned outcomes to originating actions |
| 18 | `implicit_feedback_interpret` | advisory_engine.py | After session | Extracts helpful/unhelpful signals from behavior |

### 8. System-Level Learning

Weekly summaries and policy recommendations.

| # | Area ID | Host Module | Hook Point | What it does |
| --- | --- | --- | --- | --- |
| 19 | `curriculum_gap_summarize` | eidos_distillation_curriculum.py | During rebuild | Summarizes stagnating learning loops |
| 20 | `policy_autotuner_recommend` | auto_tuner.py | During tuner cycle | Generates tuneable change recommendations |

---

## Architecture Areas (10)

### 9. Advisory Pipeline

| # | Area ID | Host Module | Hook Point | What it does |
| --- | --- | --- | --- | --- |
| A1 | `suppression_triage` | advisory_engine.py | After no-emit decision | Classifies suppressions as fixable vs valid |
| A2 | `dedupe_optimize` | advisory_engine.py | Per-intent dedupe | Refines dedupe key strategy with semantic intent |
| A3 | `packet_rerank` | advisory_packet_store.py | Before emit | Reranks advisory candidates by relevance |

### 10. Drift & Dedupe

| # | Area ID | Host Module | Hook Point | What it does |
| --- | --- | --- | --- | --- |
| A5 | `drift_diagnose` | cross_surface_drift_checker.py | After drift detection | Explains metric mismatches with root-cause hints |

### 11. Operator Tools

| # | Area ID | Host Module | Hook Point | What it does |
| --- | --- | --- | --- | --- |
| A4 | `operator_now_synth` | observatory/__init__.py | During generation | Synthesizes operator-facing system state summary |
| A7 | `error_translate` | error_translator.py | On demand | Translates technical errors to plain-language steps |
| A8 | `config_advise` | observatory/tuneables_deep_dive.py | During analysis | Suggests safe tuneable changes with risk notes |

### 12. Decision Assistants

| # | Area ID | Host Module | Hook Point | What it does |
| --- | --- | --- | --- | --- |
| A6 | `dead_widget_plan` | observatory/stage_pages.py | During pulse health | Maps dead widgets to fallback endpoints |
| A9 | `canary_decide` | canary_assistant.py | On demand | Evaluates canary deployment pass/fail/hold |
| A10 | `canvas_enrich` | observatory/__init__.py | During canvas gen | Adds annotations to Obsidian canvas nodes |

---

## Fallback Behavior

Every area follows the same pattern:

1. If `{area_id}_enabled` is `false` -> return `fallback` immediately (zero cost)
2. If the LLM call fails or returns empty -> return `fallback`
3. If the LLM returns a response -> truncate to `max_chars`, return as `text`

This means:
- Existing behavior is preserved when all areas are disabled
- No code path requires conditional handling for enabled/disabled
- The system is safe to enable/disable areas at any time

## Prompt Templates

All prompt templates live in `lib/llm_area_prompts.py`. Each area has:

- **system**: The system-level instruction (personality/format guidance)
- **template**: The user-facing template with `{placeholders}`

Templates use safe formatting: missing placeholders become empty strings instead of raising errors.

## Monitoring

### Observatory

The Observatory automatically generates `_observatory/llm_areas_status.md` showing:
- Summary counts (enabled/disabled/provider distribution)
- Per-area status table (enabled, provider, timeout, max_chars, host module)
- Prompt previews
- Configuration guide

### Diagnostics

Each LLM area call logs via `diagnostics.log_debug("llm_dispatch", ...)`:
- Provider dispatch failures
- Empty responses from LLM
- Unknown area IDs

### LLMAreaResult

Every call returns an `LLMAreaResult` dataclass:

```python
@dataclass(frozen=True)
class LLMAreaResult:
    text: str           # LLM response or fallback
    used_llm: bool      # True if LLM was called (even if empty response)
    provider: str       # "minimax", "ollama", etc. or "none" if disabled
    latency_ms: float   # Wall-clock time
    area_id: str        # Which area triggered this
```

---

## Recommended Enable Order

If you want to start enabling areas incrementally, here's the recommended order based on impact:

1. **Start with archive recovery**: `archive_rewrite`, `archive_rescue` - rescues suppressed but valuable insights
2. **Add quality loop**: `meta_ralph_remediate`, `reasoning_patch` - improves quality gate feedback
3. **Boost statements**: `actionability_boost`, `specificity_augment` - raises statement quality
4. **Improve retrieval**: `retrieval_rewrite` - better query expansion for advisory
5. **System-level**: `curriculum_gap_summarize` - visibility into learning health
6. **Architecture**: `suppression_triage`, `operator_now_synth` - operational visibility

Each area adds ~4-10s latency per invocation (depending on provider and timeout). Start small and expand based on value observed.
