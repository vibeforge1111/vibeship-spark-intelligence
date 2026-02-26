# Advisory System Architecture

The advisory system delivers contextual guidance to Claude Code before every tool call. It converts learnings (cognitive insights, EIDOS distillations, mind, chips) into actionable, timely advice.

**Current emission rate**: ~5.6% of tool calls (target: 5-15%).

---

## Data Flow

```
Hook: on_pre_tool(session_id, tool_name, tool_input, trace_id)
  |
  v
1. Safety Check — abort early if tool is in safety bypass list
  |
  v
2. Session State (advisory_state.py)
   Load/create session, detect task phase, check cooldowns
  |
  v
3. Text Repeat Guard — suppress if same context text was recently emitted
  |
  v
4. Emission Budget Check — skip retrieval if budget already exhausted
  |
  v
5. Advisory Packet Store (advisory_packet_store.py)
   Read/watch advisory packet cache and watchtower metadata
  |
  v
   - if packet stale, invalid, or low-confidence: continue
   - else route through packet-based advisory emission
   - on miss/fallback: go live retrieval below
  |
  v
6. Retrieve (advisor.py)
   Query 7 sources -> rank by 3-factor model -> top 8 items
  |
  v
7. Quality Gate (advisory_gate.py)
   Score each item -> assign authority -> gate absorbs advice_id dedupe -> emit top 2
  |
  v
8. Synthesize (advisory_synthesizer.py)
   Compose text (programmatic or AI-assisted)
  |
  v
9. Emit (advisory_emitter.py)
   Print to stdout: "[SPARK] advice text"
  |
  v
10. Post-Emit (advisory_state.py + advisory_engine.py)
    Mark shown (TTL), update fingerprint, log diagnostics
```

> **Note**: Steps 1-4 are cheap checks that run before any retrieval. This reorder
> (Intelligence Flow Evolution, Batch 2) prevents unnecessary retrieval when the
> result would be suppressed anyway.

### Write Path: validate_and_store

All cognitive insight writes now route through `validate_and_store_insight()` (`lib/validate_and_store.py`):

```
caller (bridge_cycle, hypothesis_tracker, etc.)
  |
  v
validate_and_store_insight(text, source, category, ...)
  |
  v
Meta-Ralph quality gate
  |
  ├─ pass  → cognitive_learner.add_insight()
  ├─ reject → return False (logged)
  └─ exception → quarantine to insight_quarantine.jsonl AND add_insight() (fail-open)
```

**Rollback**: Set `flow.validate_and_store_enabled = false` in tuneables to bypass.

### Fallback Handling

Legacy fallback budget controls were removed from runtime and schema. Advisory behavior is now
governed by explicit gate suppression, cooldowns, and route/freshness controls.

---

## Modules

### 1. Session State (`lib/advisory_state.py`)

Tracks session context across hook invocations via JSON files in `~/.spark/advisory_state/`.

**Key fields on `SessionState`:**

| Field | Type | Purpose |
|-------|------|---------|
| `recent_tools` | List[dict] | Last 20 tool calls |
| `user_intent` | str | From UserPromptSubmit |
| `task_phase` | str | exploration/planning/implementation/testing/debugging/deployment |
| `shown_advice_ids` | Dict[str, float] | advice_id -> timestamp (TTL-based, 600s re-eligibility) |
| `suppressed_tools` | Dict[str, float] | tool -> until_timestamp |
| `consecutive_failures` | int | For debugging phase detection |

**Phase detection**: Maps tool usage to likely phase. `Read/Glob/Grep` -> exploration, `Edit/Write` -> implementation, `pytest/jest` -> testing. 2+ consecutive failures override to debugging.

**Constants:**
- `STATE_TTL_SECONDS = 7200` (2h session expiry)
- `SHOWN_ADVICE_TTL_S = 600` (10min re-eligibility)
- `MAX_RECENT_TOOLS = 20`

### 2. Advisor (`lib/advisor.py`)

Core retrieval engine. Queries 7 sources, ranks results, returns top items.

**Entry point**: `advise(tool_name, tool_input, task_context) -> List[Advice]`

**7 retrieval sources:**
1. **Cognitive insights** (`cognitive_learner.py`) — Spark's learned patterns
2. **EIDOS distillations** (`eidos/store.py`) — Outcome-linked predictions
3. **Mind memories** (`mind_bridge.py`) — Cross-session persistent memory
4. **Domain chips** (`chips/`) — X social, DEPTH, game_dev, etc.
5. **Trigger rules** — Explicit if/then rules per tool/domain
6. **Replay history** — Past success/failure patterns
7. **Memory banks** — Less curated, broader recall

**3-Factor Additive Ranking (`_rank_score`):**

```
score = 0.45 * relevance + 0.30 * quality + 0.25 * trust
```

| Dimension | Weight | Components |
|-----------|--------|------------|
| Relevance | 0.45 | `context_match` (semantic similarity to current tool+task) |
| Quality | 0.30 | `max(text_quality, source_quality)` — best of actionability score or source tier |
| Trust | 0.25 | `max(confidence, effectiveness)` — best of learning confidence or proven outcome |

**Source quality tiers** (`_SOURCE_QUALITY`, normalized 0-1):

| Source | Score | |
|--------|-------|--|
| eidos | 0.90 | Validated outcome-linked patterns |
| replay | 0.85 | Past success evidence |
| self_awareness | 0.80 | Tool-specific cautions |
| trigger | 0.75 | Explicit rules |
| opportunity | 0.72 | Socratic prompts |
| convo | 0.70 | Conversation intelligence |
| engagement/mind/chip | 0.65 | Domain + cross-session |
| semantic-agentic | 0.62 | Multi-hop retrieval |
| niche | 0.60 | Network intelligence |
| semantic-hybrid | 0.58 | BM25 + embedding |
| semantic | 0.55 | Embedding-only |
| cognitive | 0.50 | Standard insights |
| bank | 0.40 | Memory banks |

**Noise penalties** (multiplicative, applied after additive blend):
- Low-signal struggle text: `*0.05`
- Transcript artifacts: `*0.40`
- Metadata patterns: `*0.60`

**Key thresholds:**
- `MIN_RANK_SCORE = 0.35` (items below are dropped before gate)
- `MAX_ADVICE_ITEMS = 8` (max retrieved per call)
- `ADVICE_CACHE_TTL_SECONDS = 120`

### 3. Advisory Gate (`lib/advisory_gate.py`)

Decides IF and WHEN to surface advice. Converts scores to authority levels.

**Authority levels:**

| Level | Threshold | Output |
|-------|-----------|--------|
| BLOCK | >= 0.95 | EIDOS blocks action (safety-critical) |
| WARNING | >= 0.80 | `[SPARK ADVISORY] text` |
| NOTE | >= 0.42 | `[SPARK] text` |
| WHISPER | >= 0.30 | `(spark: text)` (if enabled) |
| SILENT | < 0.30 | Log only |

**Gate base score** (additive, aligned with advisor):
```
base_score = 0.45 * context_match + 0.25 * confidence + 0.15
```
The 0.15 floor reflects that items reaching the gate already passed Meta-Ralph + cognitive filter + advisor ranking.

**Score adjustments:**
- Phase relevance boost (e.g., `self_awareness * 1.4` during implementation)
- Emotional priority boost (capped +15%)
- Negative advisory boost (`*1.3` for "avoid" / "never" advice)
- Failure-context boost (`*1.5` for cautions during debugging)
- Outcome risk boost (from outcome predictor, if available)

**Filters (in order):**

| # | Filter | Cooldown |
|---|--------|----------|
| 1 | Already shown (TTL) | 600s re-eligibility |
| 2 | Tool suppressed | 10s per tool type |
| 3 | Obvious-from-context | Pattern-based |
| 4 | Budget cap | Max 2 per tool call |

### 4. Distillation Transformer (`lib/distillation_transformer.py`)

Scores advisory quality across 5 dimensions. Applied to insights before they enter the advisory store.

**5 quality dimensions** (weights for unified_score):

| Dimension | Weight | Meaning |
|-----------|--------|---------|
| Actionability | 0.30 | Has verb + object ("use X", "avoid Y") |
| Reasoning | 0.20 | Has causal link ("because", "since") |
| Outcome-linked | 0.20 | Tied to measurable result |
| Specificity | 0.15 | Names tools, files, versions |
| Novelty | 0.15 | Not obvious or repeated |

**7 suppression rules** (`should_suppress`):
1. Training artifact prefixes (RT @, [DEPTH:, Strong Socratic...)
2. Verbatim user quotes
3. Regex noise patterns
4. Code artifacts (>60% non-alpha)
5. Pure observation (no action + no reasoning)
6. Tautology (generic without context, <80 chars)
7. Unified score < 0.20

### 5. Synthesizer (`lib/advisory_synthesizer.py`)

Composes advice text. Two tiers:

| Tier | Mode | Latency | When |
|------|------|---------|------|
| Programmatic | Template composition | <5ms | Default / always available |
| AI-enhanced | Ollama phi4-mini or cloud | 2-8s | High-authority, enough budget |

**Programmatic template**: `"When {context}: {action}. Because {reasoning}."`

**AI synthesis**: Enabled via `SELECTIVE_AI_SYNTH_ENABLED`, requires `>= 1800ms` remaining budget and `>= NOTE` authority.

### 6. Emitter (`lib/advisory_emitter.py`)

Writes advice to stdout (visible to Claude Code).

**Output format by authority:**
- WARNING: `[SPARK ADVISORY] text`
- NOTE: `[SPARK] text`
- WHISPER: `(spark: text)`

**Limit**: 500 chars max per emission.

### 7. Packet Store (`lib/advisory_packet_store.py`)

Caches advisory packets for faster subsequent delivery. Stored at `~/.spark/advice_packets/`.
Acts as the single source of truth for delivery-ready advisory content.

**Lookup order**: Exact match (session+tool+intent+plane) -> Relaxed match (weighted scoring across dimensions).

**Packet TTL**: 900s (15min freshness).

**Watchtower metadata (Obsidian export payload)**:

- readiness and staleness signals
- `ready_for_use` and `fresh` flags
- invalidation state and reason
- usage and freshness remaining indicators
- forced sync on invalidation updates when export is enabled
- Obsidian watchtower index also includes decision-ledger tails so suppression and emission behavior is visible at a glance.

### 8. Engine Orchestrator (`lib/advisory_engine.py`)

Ties everything together. Contains the outer try/except, timing budget, and cross-session dedupe.

**Cross-session dedupe** (text_sig only):
- Same text fingerprint blocked globally for 600s
- Prevents the same advice from repeating across different sessions within 10 minutes

**Timing budget**: `MAX_ENGINE_MS = 4000` (4s). Retrieval, gate, synthesis, and emission must complete within budget.

---

## Suppression Summary

The system has ~15 suppression points across 5 layers. Each serves a purpose:

| Layer | Points | Purpose |
|-------|--------|---------|
| Distillation transformer | 7 | Quality floor — garbage never enters store |
| Advisor ranking | 1 | `MIN_RANK_SCORE = 0.35` — low scores dropped |
| Advisory gate | 4 | Authority, cooldowns, budget, repeats |
| Engine dedupe | 1 | Cross-session text_sig (600s) |
| Engine safety | 1 | `is_unsafe_insight()` final check |

---

## Configuration

All tunable via `~/.spark/tuneables.json` (sections: `advisor`, `advisory_engine`, `advisory_gate`, `synthesizer`).

### Key tunables

| Tunable | Default | Effect |
|---------|---------|--------|
| `advisor.min_rank_score` | 0.35 | Retrieval score floor |
| `advisor.max_items` | 8 | Max items per retrieval |
| `advisory_engine.max_ms` | 4000 | Time budget (ms) |
| `advisory_engine.delivery_stale_s` | 900 | Packet freshness window |
| `advisory_engine.advisory_text_repeat_cooldown_s` | 600 | Text repeat window |
| `advisory_gate.tool_cooldown_s` | 10 | Per-tool cooldown |
| `advisory_gate.advice_repeat_cooldown_s` | 300 | Per-advice cooldown |
| `advisory_gate.emit_whispers` | true | Surface low-confidence items |
| `advisory_gate.max_emit_per_call` | 2 | Budget cap per call |

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SPARK_ADVISORY_ENGINE` | 1 | Enable/disable engine |
| `SPARK_ADVISORY_EMIT_WHISPERS` | 1 | Surface whisper-level advice |
| `SPARK_ADVISORY_GLOBAL_DEDUPE` | 1 | Cross-session dedupe |
| `SPARK_ADVISORY_GLOBAL_DEDUPE_COOLDOWN_S` | 600 | Dedupe window |

## Obsidian Watchtower (Observation Tower)

The watchtower is the packet-first observability layer: every emitted advisory packet is exported as Markdown for easy review in Obsidian.

- Packet export is controlled in `advisory_packet_store` tuneables:
  - `obsidian_enabled`
  - `obsidian_auto_export`
  - `obsidian_export_dir`
  - `obsidian_export_max_packets`
- Exports land under:
- `<obsidian_export_dir>\packets\` (with `index.md` and packet notes)
- `<obsidian_export_dir>\watchtower.md` (watchtower dashboard)

### Setup on Windows

1. Create/open your vault folder path.
2. Set Spark export target:
   - `python scripts/set_obsidian_watchtower.py --vault-dir "C:\\Users\\USER\\Documents\\Obsidian Vault\\Spark-Intelligence-Observatory" --enable --auto-export --write`
3. Open Obsidian and add/open that folder as a vault/subfolder.
4. Open `packets\\index.md` from that same folder.

### Quick checks

- Show current settings:
  - `python scripts/set_obsidian_watchtower.py --show`
- Repoint without writing:
  - `python scripts/set_obsidian_watchtower.py --vault-dir "<new-path>"`
- Apply changes:
  - add `--write`
- Disable temporarily:
  - `python scripts/set_obsidian_watchtower.py --disable --write`
- Enable temporarily:
  - `python scripts/set_obsidian_watchtower.py --enable --write`

### Expected output

- `.\Spark-Intelligence-Observatory\watchtower.md` updates with:
  - summary
  - suppression/reason trend view
  - decision-ledger tail
  - project/tool/intent distributions
  - cross-packet trace health pane (required/optional systems, missing systems, hot systems)
  - trace-system heatmap for packet coverage by trace source
- `.\Spark-Intelligence-Observatory\packets\index.md` remains the packet catalog.
- Per-packet files appear as:
  - `<packet_id>.md` (current export naming; no `pkt_` prefix)

For best-practice usage (daily/weekly workflows, triage pattern, and noise control),
see: `docs/ADVISORY_OBSIDIAN_PLAYBOOK.md`.

### Quick health check command

Run:

```bash
python scripts/check_obsidian_watchtower.py
```

to validate watchtower directory, config, and dashboard file sync in one pass.

--- 

## Log Files

| File | Content | Cap |
|------|---------|-----|
| `~/.spark/advisory_engine.jsonl` | Engine events (retrieve, gate, emit, errors) | 500 lines |
| `~/.spark/advisory_emit.jsonl` | What was emitted to stdout | 500 lines |
| `~/.spark/outcomes.jsonl` | Outcome tracker rows (linked to trace IDs/insights) | 5000 lines |
| `~/.spark/outcome_links.jsonl` | Outcome-to-insight linkage rows | 5000 lines |
| `~/.spark/advisor/implicit_feedback.jsonl` | Implicit outcome tracker rows for advisory post-tool signals | 5000 lines |
| `~/.spark/advisor/retrieval_router.jsonl` | Which sources hit per query | 800 lines |
| `~/.spark/advisor/advice_log.jsonl` | All advice retrieval | 500 lines |
| `~/.spark/advisor/recent_advice.jsonl` | Last 20min deliveries | 200 lines |
| `~/.spark/advisory_global_dedupe.jsonl` | Cross-session dedupe log | 5000 lines |
| `~/.spark/advisory_state/*.json` | Per-session state files | 2h TTL |
| `~/.spark/advice_packets/index.json` | Packet registry | 2000 packets |

---

## Benchmark

**Benchmark script**: `benchmarks/comprehensive_pipeline_benchmark.py`

5000 memories (3000 useful across 6 quality layers + 2000 garbage across 10 types), 520 advisory queries across 17 domains. Seed=42 for reproducibility.

**8 phases**: importance_score -> Meta-Ralph -> cognitive filter -> inject -> advisor retrieval -> on_pre_tool emission -> gap analysis -> cleanup.

**Latest results** (2026-02-21):

| Stage | Useful | Garbage |
|-------|--------|---------|
| Input | 3000 | 2000 |
| importance_score | 267 | 27 |
| Meta-Ralph | 293 | 54 |
| Cognitive filter | 228 | 54 |
| Advisor retrieval | 726 | 0 |
| on_pre_tool emitted | 29 | 0 |

**Key metrics**: 5.6% emission rate, 100% retrieval, 0 garbage leakage.

---

## File Reference

| File | Lines | Role |
|------|-------|------|
| `lib/advisory_engine.py` | ~2100 | Orchestrator, timing, dedupe |
| `lib/advisor.py` | ~5600 | Retrieval, ranking, 7 sources |
| `lib/advisory_gate.py` | ~750 | Authority assignment, emission decision |
| `lib/advisory_state.py` | ~400 | Session state, phase detection |
| `lib/advisory_synthesizer.py` | ~600 | Text composition (programmatic + AI) |
| `lib/advisory_emitter.py` | ~300 | Stdout output, formatting |
| `lib/advisory_packet_store.py` | ~1500 | Packet caching, lookup |
| `lib/distillation_transformer.py` | ~500 | Quality scoring, 5 dimensions |
| `tests/test_advisor.py` | ~700 | Unit tests for ranking, filtering |
| `benchmarks/comprehensive_pipeline_benchmark.py` | ~610 | E2E benchmark |
| `docs/reports/WHY_ADVISORY_EMISSIONS_ARE_LOW.md` | ~260 | Emission analysis report |
