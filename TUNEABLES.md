# Spark Intelligence Tuneable Parameters

All configurable thresholds, limits, and weights across the system.
Use this to test and optimize learning quality.
Navigation hub: `docs/GLOSSARY.md`

---

## Configuration Precedence (Canonical)

Spark runtime now resolves tuneables using a single authority model:

1. `lib/tuneables_schema.py` defaults
2. `config/tuneables.json` baseline
3. `~/.spark/tuneables.json` runtime overrides
4. Explicit env overrides (allowlisted per key)

Reference: `docs/CONFIG_AUTHORITY.md`

Core runtime sections now routed through this model:
- `advisory_engine`, `advisory_gate`, `advisor`, `synthesizer`, `semantic`, `triggers`
- `meta_ralph`, `eidos`, `promotion`, `memory_emotion`, `memory_learning`, `memory_retrieval_guard`
- `bridge_worker`, `queue`, `pipeline`, `values`
- `advisory_packet_store`, `advisory_prefetch`, `sync`, `production_gates`
- `chip_merge`, `memory_capture`, `request_tracker`, `observatory`, `advisory_preferences`

---

## 0. Advisor Retrieval Router (Carmack Path)

**File:** `lib/advisor.py`

This controls when advisor stays on fast embeddings retrieval versus escalating to hybrid-agentic retrieval.

Canonical routing tuneables surface:
- Live: `~/.spark/tuneables.json` -> `retrieval.overrides.*`
- Benchmark overlays: also use `retrieval.overrides.*` (same schema)

### Core Strategy

- Fast path first: semantic retrieval on primary query.
- `auto` mode default gate (minimal):
  - escalate on weak primary count
  - escalate on weak primary top score
  - escalate on high-risk query terms
- Bounded escalation:
  - rate cap (`agentic_rate_limit`)
  - hard deadline (`agentic_deadline_ms`)

### Parameters

| Parameter | Default (Level 2) | Description |
|-----------|-------------------|-------------|
| `retrieval.level` | `"2"` | Profile baseline (`1` local-free, `2` balanced, `3` quality-max). |
| `retrieval.overrides.mode` | `auto` | `auto`, `embeddings_only`, or `hybrid_agentic`. |
| `retrieval.overrides.gate_strategy` | `minimal` | `minimal` uses weak_count/weak_score/high_risk; `extended` also uses complexity+trigger gates. |
| `retrieval.overrides.min_results_no_escalation` | `4` | If primary result count is below this, escalate. |
| `retrieval.overrides.min_top_score_no_escalation` | `0.72` | If primary top fusion score is below this, escalate. |
| `retrieval.overrides.escalate_on_high_risk` | `true` | Escalate when high-risk terms are present. |
| `retrieval.overrides.escalate_on_trigger` | `false` (L2) | Trigger-based escalation (mostly for extended/high-quality profiles). |
| `retrieval.overrides.agentic_rate_limit` | `0.20` | Max fraction of recent queries allowed to escalate agentically. |
| `retrieval.overrides.agentic_rate_window` | `80` | Rolling window size for rate cap. |
| `retrieval.overrides.agentic_deadline_ms` | `700` | Deadline for agentic facet fanout; stop on timeout. |
| `retrieval.overrides.fast_path_budget_ms` | `250` | Target budget marker for primary retrieval path telemetry. |
| `retrieval.overrides.prefilter_enabled` | `true` | Enables metadata/token prefilter before semantic retrieval. |
| `retrieval.overrides.prefilter_max_insights` | `500` | Max candidate insights after prefilter. |
| `retrieval.overrides.semantic_limit` | `10` | Number of semantic candidates returned from each retrieval call. |
| `retrieval.overrides.max_queries` | `3` | Max total retrieval queries (primary + facets). |
| `retrieval.overrides.agentic_query_limit` | `3` | Max extracted facet queries before clipping by `max_queries`. |
| `retrieval.overrides.lexical_weight` | `0.28` | Weight applied to lexical blend during rerank. |
| `retrieval.overrides.bm25_k1` | `1.2` | BM25 TF saturation parameter. |
| `retrieval.overrides.bm25_b` | `0.75` | BM25 length normalization parameter. |
| `retrieval.overrides.bm25_mix` | `0.75` | Blend ratio: BM25 vs overlap lexical signal. |
| `retrieval.overrides.semantic_context_min` | `0.18` | Minimum semantic similarity to treat a candidate as a context match. |
| `retrieval.overrides.semantic_lexical_min` | `0.05` | Minimum lexical overlap to keep a candidate when semantic similarity is weak. |
| `retrieval.overrides.semantic_strong_override` | `0.92` | If semantic similarity is this strong, keep the candidate even if lexical overlap is weak. |

---
## 0.5 Memory Emotion Fusion

**Files:** `lib/memory_banks.py`, `lib/memory_store.py`

This controls how emotional state is attached to memory writes and reused as a retrieval rerank signal.

Tuneable surface:
- Live: `~/.spark/tuneables.json` -> `memory_emotion.*`
- Environment overrides:
  - `SPARK_MEMORY_EMOTION_WRITE_CAPTURE`
  - `SPARK_MEMORY_EMOTION_ENABLED`
  - `SPARK_MEMORY_EMOTION_WEIGHT`
  - `SPARK_MEMORY_EMOTION_MIN_SIM`
  - `SPARK_ADVISORY_MEMORY_EMOTION_ENABLED`
  - `SPARK_ADVISORY_MEMORY_EMOTION_WEIGHT`
  - `SPARK_ADVISORY_MEMORY_EMOTION_MIN_SIM`

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `memory_emotion.enabled` | `true` | Master switch for retrieval-time emotion/state rerank in memory retrieval. |
| `memory_emotion.write_capture_enabled` | `true` | Attach current emotion snapshot (`meta.emotion`) when writing memory-bank entries. |
| `memory_emotion.retrieval_state_match_weight` | `0.22` | Additive score weight applied to state similarity during retrieval rerank. |
| `memory_emotion.retrieval_min_state_similarity` | `0.30` | Minimum similarity required before state-match contributes to score. |
| `memory_emotion.advisory_rerank_weight` | `0.15` | Additive weight for emotion-state similarity in live advisory semantic reranking. |
| `memory_emotion.advisory_min_state_similarity` | `0.30` | Minimum similarity threshold before advisory rerank applies emotion boost. |

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Emotion signal overpowers relevance | Lower `retrieval_state_match_weight` (e.g. `0.10-0.18`) |
| Emotion signal has no practical effect | Raise `retrieval_state_match_weight` (e.g. `0.30-0.45`) |
| Too many weak emotional matches | Raise `retrieval_min_state_similarity` (e.g. `0.45`) |
| Want broader emotional recall | Lower `retrieval_min_state_similarity` (e.g. `0.15-0.25`) |

---
## 1. Memory Gate (Pattern → EIDOS)

**File:** `lib/pattern_detection/memory_gate.py`

The Memory Gate decides which Steps and Distillations are worth persisting to long-term memory. It prevents noise from polluting the knowledge base by scoring each item against multiple quality signals.

### How It Works

Every Step or Distillation is scored from 0.0 to 1.0+ based on weighted signals. Only items scoring above the `threshold` are persisted.

```
Final Score = Σ(signal_present × signal_weight)
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold` | **0.5** | **The gate cutoff.** Items scoring below this are discarded. At 0.5, an item needs at least 2-3 positive signals to pass. |
| `WEIGHTS["impact"]` | 0.30 | **Progress signal.** Did this action unblock progress or advance toward the goal? High when a stuck situation was resolved. |
| `WEIGHTS["novelty"]` | 0.20 | **New pattern signal.** Is this something we haven't seen before? Detects first-time tool combinations, new error types, or unique approaches. |
| `WEIGHTS["surprise"]` | 0.30 | **Prediction error signal.** Did the outcome differ from what was predicted? Surprises indicate learning opportunities - the system's model was wrong. |
| `WEIGHTS["recurrence"]` | 0.20 | **Frequency signal.** Has this pattern appeared 3+ times? Recurring patterns are likely stable and worth remembering. |
| `WEIGHTS["irreversible"]` | 0.60 | **Stakes signal.** Is this a high-stakes action (production deploy, security change, data deletion)? Irreversible actions get dominant weight because mistakes are costly. Raised from 0.40. |
| `WEIGHTS["evidence"]` | 0.10 | **Validation signal.** Is there concrete evidence (test pass, user confirmation) supporting this? Evidence-backed items are more trustworthy. |

### Scoring Examples

**High score (passes gate):**
```
Step: "Fixed authentication bug by adding token refresh"
- impact: 0.30 (unblocked login flow)
- surprise: 0.30 (expected different root cause)
- evidence: 0.10 (tests now pass)
Total: 0.70 ✓ PASSES
```

**Low score (rejected):**
```
Step: "Read config file"
- novelty: 0.0 (common action)
- impact: 0.0 (no progress made)
- surprise: 0.0 (expected outcome)
Total: 0.0 ✗ REJECTED
```

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Too much noise in memory | Raise `threshold` to 0.6-0.7 |
| Missing important learnings | Lower `threshold` to 0.4 |
| Want more emphasis on errors | Raise `surprise` weight |
| Learning too slowly | Lower `recurrence` weight |
| High-stakes project (finance, security) | Weight already at 0.60, raise to 0.7+ if needed |

---

## 2. Pattern Distiller

**File:** `lib/pattern_detection/distiller.py`

The Pattern Distiller analyzes completed Steps to extract reusable rules (Distillations). It looks for patterns in successes, failures, and user behavior to create actionable guidance.

### How It Works

1. Collects completed Steps from the Request Tracker
2. Groups by pattern type (user preferences, tool usage, surprises)
3. Requires minimum evidence before creating a Distillation
4. Passes Distillations through Memory Gate before storage

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_occurrences` | **2** | **Evidence threshold.** A pattern must appear at least this many times before being distilled into a rule. Lowered from 3 for faster learning. |
| `min_occurrences_critical` | **1** | **Fast-track for CRITICAL tier.** Critical importance items (explicit "remember this", corrections) are learned from a single occurrence. |
| `min_confidence` | **0.6** | **Success rate threshold.** For heuristics (if X then Y), the pattern must have worked at least 60% of the time. Filters out unreliable patterns. |
| `gate_threshold` | **0.5** | **Memory gate threshold** (inherited from Memory Gate). Distillations must score above this to be stored. |

### Distillation Types Created

| Type | What It Captures | Example |
|------|------------------|---------|
| `HEURISTIC` | "When X, do Y" patterns | "When file not found, check path case sensitivity first" |
| `ANTI_PATTERN` | "Don't do X because Y" | "Don't use sed on Windows - syntax differs" |
| `SHARP_EDGE` | Gotchas and pitfalls | "Python venv activation differs between shells" |
| `PLAYBOOK` | Multi-step procedures | "To debug imports: 1. Check PYTHONPATH, 2. Verify __init__.py" |
| `POLICY` | User-defined rules | "Always run tests before committing" |

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Learning too slowly | Lower `min_occurrences` to 1 |
| Distillations are unreliable | Raise `min_occurrences` to 4-5 |
| Too many weak heuristics | Raise `min_confidence` to 0.7-0.8 |
| Missing edge case patterns | Lower `min_confidence` to 0.5 |
| Want more one-shot learning | Lower `min_occurrences_critical` (already at 1) |

---

## 3. Request Tracker

**File:** `lib/pattern_detection/request_tracker.py`

The Request Tracker wraps every user request in an EIDOS Step envelope, tracking the full lifecycle from intent → action → outcome. This creates the structured data needed for learning.

### How It Works

```
User Message → Step Created (with intent, hypothesis, prediction)
     ↓
Action Taken → Step Updated (with decision, tool used)
     ↓
Outcome Observed → Step Completed (with result, evaluation, lesson)
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_pending` | **50** | **Concurrent request limit.** Maximum unresolved requests being tracked. Prevents memory bloat from abandoned requests. When exceeded, oldest pending requests are dropped. |
| `max_completed` | **200** | **Completed history limit.** How many completed Steps to retain for distillation analysis. Older completed Steps are pruned. |
| `max_age_seconds` | **3600** | **Timeout (1 hour).** Pending requests older than this are auto-closed as "timed_out". Prevents zombie requests from lingering forever. |

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Long-running sessions with many requests | Raise `max_pending` to 100 |
| Memory-constrained environment | Lower both limits |
| Want more history for distillation | Raise `max_completed` to 500 |
| Requests timing out too quickly | Raise `max_age_seconds` to 7200 (2 hours) |

---

## 4. Pattern Aggregator

**File:** `lib/pattern_detection/aggregator.py`

The Pattern Aggregator coordinates all pattern detectors (correction, sentiment, repetition, semantic, why) and routes detected patterns to the learning system. It's the central hub for pattern detection.

### How It Works

```
Event → All Detectors Run → Patterns Collected → Corroboration Check → Learning Triggered
                                    ↓
                         (Every N events) → Distillation Run
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `CONFIDENCE_THRESHOLD` | **0.6** | **Learning trigger threshold.** Patterns must have at least 60% confidence to trigger learning. Lowered from 0.7 to let importance scorer do quality filtering. |
| `DEDUPE_TTL_SECONDS` | **600** | **Deduplication window (10 min).** The same pattern won't be processed twice within this window. Prevents spammy patterns from flooding the system. |
| `DISTILLATION_INTERVAL` | **20** | **Batch size for distillation.** After every 20 events processed, the distiller runs to analyze completed Steps. Lower = more frequent distillation. |

### Corroboration Boost

When multiple detectors agree, confidence is boosted:
- Correction + Frustration detected together → +15% confidence
- Repetition + Frustration detected together → +10% confidence

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Missing subtle patterns | Lower `CONFIDENCE_THRESHOLD` to 0.6 |
| Too many false positives | Raise `CONFIDENCE_THRESHOLD` to 0.8 |
| Same insight appearing repeatedly | Raise `DEDUPE_TTL_SECONDS` to 1800 (30 min) |
| Want faster learning cycles | Lower `DISTILLATION_INTERVAL` to 10 |
| System too slow | Raise `DISTILLATION_INTERVAL` to 50 |

---

## 5. EIDOS Budget (Episode Limits)

**File:** `lib/eidos/models.py` → `Budget` class

The EIDOS Budget enforces hard limits on episodes to prevent rabbit holes. When any limit is exceeded, the episode transitions to DIAGNOSE or HALT phase.

### How It Works

These are **circuit breakers** - when tripped, they force the system to stop and reassess rather than continuing blindly.

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_steps` | **25** (code) / **40** (tuneables) | **Step limit per episode.** After N actions without completing the goal, force DIAGNOSE phase. Canonical key is `values.max_steps` (legacy `eidos.max_steps` may still be read if present in older runtime files). |
| `max_time_seconds` | **720** (code) / **1200** (tuneables) | **Time limit.** Episodes taking longer than this are force-stopped. Wired to `eidos.max_time_seconds`. |
| `max_retries_per_error` | **2** (code) / **3** (tuneables) | **Error retry limit.** Wired to `eidos.max_retries_per_error` (also reads `values.max_retries_per_error`). |
| `max_file_touches` | **3** (code) / **5** (tuneables) | **File modification limit.** Wired to `eidos.max_file_touches` (also reads `values.max_file_touches`). |
| `no_evidence_limit` | **5** (code) / **6** (tuneables) | **Evidence requirement.** After N steps without new evidence, force DIAGNOSE. Wired to `eidos.no_evidence_limit` (also reads `values.no_evidence_steps`). |

### What Happens When Limits Hit

| Limit Exceeded | Transition | Behavior |
|----------------|------------|----------|
| `max_steps` | → HALT | Episode ends, escalate to user |
| `max_time_seconds` | → HALT | Episode ends, escalate to user |
| `max_retries_per_error` | → DIAGNOSE | Stop modifying, only observe |
| `max_file_touches` | → DIAGNOSE | File frozen, must find another approach |
| `no_evidence_limit` | → DIAGNOSE | Must gather evidence before acting |

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Complex tasks need more steps | Raise `max_steps` to 40 |
| Want faster failure detection | Lower `max_steps` to 15 |
| Legitimate long-running tasks | Raise `max_time_seconds` to 1800 (30 min) |
| Frequent file thrashing | Lower `max_file_touches` to 1 |
| Tasks require iteration | Raise `max_file_touches` to 3 |

---

## 6. EIDOS Watchers

**File:** `lib/eidos/control_plane.py`

Watchers are real-time monitors that detect specific stuck patterns. When triggered, they force phase transitions to break out of unproductive loops.

### How It Works

Each watcher monitors a specific metric. When the threshold is exceeded, it fires an alert that triggers a phase transition (usually to DIAGNOSE).

### Watchers

| Watcher | Threshold | What It Detects | Response |
|---------|-----------|-----------------|----------|
| **Repeat Error** | **2** | Same error signature appearing twice. | → DIAGNOSE. Stop modifying, investigate root cause. |
| **No New Info** | **5** | Five consecutive steps without gathering new evidence. | → DIAGNOSE. Must read/test before acting. |
| **Diff Thrash** | **4** | Same file modified four times (after max_file_touches=3). | → SIMPLIFY. Freeze file, find alternative. |
| **Confidence Stagnation** | **0.05 × 3** | Confidence delta < 5% for three steps. | → PLAN. Step back, reconsider approach. |
| **Memory Bypass** | **1** | Action taken without citing retrieved memory. | BLOCK. Must acknowledge memory or declare absent. |
| **Budget Half No Progress** | **50%** | Budget >50% consumed with no progress. | → SIMPLIFY. Reduce scope, focus on core. |
| **Scope Creep** | varies | Plan grows but progress doesn't. | → PLAN. Re-scope to original goal. |
| **Validation Gap** | **2** | More than 2 steps without validation. | → VALIDATE. Must test before continuing. |

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| False positives on error detection | Raise repeat error threshold to 3 |
| Missing repeated mistakes | Lower repeat error threshold to 1 |
| Tasks legitimately require file iteration | Raise diff thrash to 4-5 |
| Want stricter evidence requirements | Lower no new info to 3 |

---

## 7. Cognitive Learner (Decay)

**File:** `lib/cognitive_learner.py`

The Cognitive Learner stores insights with time-based decay. Older insights gradually lose reliability, ensuring the system stays current and doesn't over-rely on stale knowledge.

### How It Works

```
Effective Reliability = Base Reliability × 2^(-age_days / half_life)
```

After one half-life period, reliability drops to 50%. After two half-lives, 25%, etc.

### Half-Life by Category

| Category | Half-Life | Rationale |
|----------|-----------|-----------|
| `WISDOM` | **180 days** | Principles and wisdom are timeless, decay slowly. "Ship fast, iterate faster" stays true. |
| `META_LEARNING` | **120 days** | How to learn itself changes slowly. Learning strategies remain valid. |
| `USER_UNDERSTANDING` | **90 days** | User preferences are fairly stable but can evolve. |
| `COMMUNICATION` | **90 days** | Communication style preferences are sticky but not permanent. |
| `SELF_AWARENESS` | **60 days** | Blind spots need regular reassessment. What I struggled with before may not apply now. |
| `REASONING` | **60 days** | Assumptions and reasoning patterns should be questioned regularly. |
| `CREATIVITY` | **60 days** | Novel approaches may become stale as tech evolves. |
| `CONTEXT` | **45 days** | Environment-specific context changes frequently. Project structure, team practices, etc. |

### Pruning Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_age_days` | **365** | **Maximum age.** Insights older than 1 year are pruned regardless of reliability. |
| `min_effective` | **0.2** | **Minimum effective reliability.** When decay brings reliability below 20%, the insight is pruned. |

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Fast-changing project | Lower CONTEXT half-life to 30 days |
| Stable long-term project | Raise half-lives across the board |
| Want insights to last longer | Raise `max_age_days` to 730 (2 years) |
| Memory getting cluttered | Lower `min_effective` to 0.3 |

---

## 8. Structural Retriever

**File:** `lib/eidos/retriever.py`

The Structural Retriever fetches relevant Distillations before actions. Unlike text similarity search, it prioritizes by EIDOS structure (policies > playbooks > sharp edges > heuristics).

### How It Works

```
Intent/Error → Keyword Extraction → Match Against Distillations → Sort by Type Priority → Return Top N
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_results` | **10** | **Result limit.** Maximum Distillations returned per query. More results = more context but also more noise. |
| `min_overlap` | **2** | **Keyword threshold.** Minimum number of keywords that must overlap between query and Distillation. Filters out weak matches. |

### Type Priority Order

1. **POLICY** (highest) - User-defined rules always come first
2. **PLAYBOOK** - Multi-step procedures for known situations
3. **SHARP_EDGE** - Gotchas and pitfalls to avoid
4. **HEURISTIC** - General "if X then Y" patterns
5. **ANTI_PATTERN** (lowest) - What not to do

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Retrieval returning irrelevant results | Raise `min_overlap` to 3 |
| Missing relevant Distillations | Lower `min_overlap` to 1 |
| Too much context overwhelming decisions | Lower `max_results` to 5 |
| Complex tasks need more guidance | Raise `max_results` to 15-20 |

---

## 9. Importance Scorer (Signal Detection)

**File:** `lib/importance_scorer.py`

The Importance Scorer evaluates incoming text at **ingestion time** (not promotion time) to determine what's worth learning. This ensures critical one-time insights are captured even if they never repeat.

### How It Works

Text is analyzed for signal patterns that indicate importance:
1. Check for CRITICAL signals (explicit requests, corrections)
2. Check for HIGH signals (preferences, principles)
3. Check for MEDIUM signals (observations, context)
4. Check for LOW signals (noise indicators)
5. Apply domain relevance boost
6. Apply first-mention elevation

### Importance Tiers

| Tier | Score Range | Behavior | Examples |
|------|-------------|----------|----------|
| **CRITICAL** | 0.9+ | Learn immediately, bypass normal thresholds | "Remember this", corrections, "never do X" |
| **HIGH** | 0.7-0.9 | Should learn, prioritize | Preferences, principles, reasoned explanations |
| **MEDIUM** | 0.5-0.7 | Consider learning | Observations, context, weak preferences |
| **LOW** | 0.3-0.5 | Store but don't promote | Acknowledgments, trivial statements |
| **IGNORE** | <0.3 | Don't store | Tool sequences, metrics, operational noise |

### Critical Signals (Immediate Learning)

| Pattern | Signal Type | Why It's Critical |
|---------|-------------|-------------------|
| "remember this" | explicit_remember | User explicitly requesting persistence |
| "always do it this way" | explicit_preference | Strong user directive |
| "never do this" | explicit_prohibition | Important constraint |
| "no, I meant..." | correction | User correcting misunderstanding |
| "because this works" | reasoned_decision | Outcome with explanation |

### High Signals

| Pattern | Signal Type |
|---------|-------------|
| "I prefer" | preference |
| "let's go with" | preference |
| "the key is" | principle |
| "the pattern here is" | pattern_recognition |
| "in general" | generalization |

### Low Signals (Noise)

| Pattern | Signal Type |
|---------|-------------|
| "Bash → Edit" | tool_sequence |
| "45% success" | metric |
| "timeout" | operational |
| "okay", "got it" | acknowledgment |

### When to Tune

Add domain-specific patterns to `DOMAIN_WEIGHTS` for your use case. See Section 15 for domain weight configuration.

---

## 10. Context Sync Defaults

**File:** `lib/context_sync.py`

Context Sync synchronizes high-value insights to Mind (persistent memory) for cross-session retrieval.

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `DEFAULT_MIN_RELIABILITY` | **0.7** | **Quality threshold.** Only sync insights with 70%+ reliability to Mind. |
| `DEFAULT_MIN_VALIDATIONS` | **3** | **Evidence threshold.** Insights must be validated 3+ times before syncing. |
| `DEFAULT_MAX_ITEMS` | **12** | **Batch limit.** Maximum items to sync per operation. |
| `DEFAULT_MAX_PROMOTED` | **6** | **Promotion limit.** Maximum items to mark as "promoted" per sync. |

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Mind getting cluttered | Raise thresholds |
| Missing important context | Lower `DEFAULT_MIN_VALIDATIONS` to 2 |
| Want more cross-session memory | Raise `DEFAULT_MAX_ITEMS` to 20 |

---

## 11. Advisor (Action Guidance)

**File:** `lib/advisor.py`

The Advisor queries relevant insights **before** actions are taken, making stored knowledge actionable. It bridges the gap between learning and decision-making.

### How It Works

```
Tool + Context → Query Memory Banks + Cognitive Insights + Mind → Rank by Relevance → Return Advice
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MIN_RELIABILITY_FOR_ADVICE` | **0.5** | **Quality filter.** Only include insights with 50%+ reliability in advice. Lowered from 0.6 for more advice coverage. Wired to `tuneables.json` -> `advisor.min_reliability`. |
| `MIN_VALIDATIONS_FOR_STRONG_ADVICE` | **2** | **Strong advice threshold.** Insights validated 2+ times are marked as "strong" advice. Wired to `advisor.min_validations_strong`. |
| `MAX_ADVICE_ITEMS` | **3** | **Advice limit.** Runtime reads `advisor.max_items`. Keep `advisor.max_advice_items` mirrored for auto-tuner compatibility. |
| `ADVICE_CACHE_TTL_SECONDS` | **120** | **Cache duration (2 min).** Same query within 2 minutes returns cached advice. Wired to `advisor.cache_ttl` (also reads `values.advice_cache_ttl`). |
| `MIN_RANK_SCORE` | **0.55** | **Rank cutoff.** Drop advice below this score after ranking; prefer fewer, higher-quality items. Wired to `advisor.min_rank_score`. |
| `MIND_MAX_STALE_SECONDS` | **0** | **Mind freshness gate.** `0` disables staleness blocking; positive values block stale Mind retrieval when newer local evidence exists. Wired to `advisor.mind_max_stale_s`. |
| `MIND_STALE_ALLOW_IF_EMPTY` | **true** | **Cross-session fallback.** If Mind is stale but no other advice exists, still allow Mind retrieval. Wired to `advisor.mind_stale_allow_if_empty`. |
| `MIND_MIN_SALIENCE` | **0.5** | **Mind quality floor.** Ignore low-salience Mind memories below this threshold. Wired to `advisor.mind_min_salience`. |

Compatibility note:
- Runtime advisor uses `advisor.max_items`.
- Auto-tuner recommendation logic currently targets `advisor.max_advice_items`.
- Keep both keys equal to avoid drift.

### Advice Sources

| Source | What It Provides |
|--------|------------------|
| `cognitive` | Insights from cognitive_learner (preferences, self-awareness) |
| `mind` | Memories from Mind persistent storage |
| `bank` | Project/global memory banks |
| `self_awareness` | Cautions about known struggles |
| `surprise` | Warnings from past unexpected failures |
| `skill` | Relevant skill recommendations |

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Getting too much advice | Lower `advisor.max_items` (and mirror `advisor.max_advice_items`) to 3 |
| Missing relevant warnings | Lower `MIN_RELIABILITY_FOR_ADVICE` to 0.5 |
| Advice is stale | Lower `ADVICE_CACHE_TTL_SECONDS` to 60 (already lowered to 120) |
| Performance issues | Raise cache TTL to 600 (10 min) |

### Semantic Retrieval (Optional)

Semantic retrieval augments Advisor with embeddings + trigger rules. It is
**disabled by default** unless enabled in `~/.spark/tuneables.json` or via
`SPARK_SEMANTIC_ENABLED=1`.

| Parameter | Default | Description |
|----------|---------|-------------|
| `semantic.enabled` | **false** | Enable semantic retrieval for cognitive insights |
| `semantic.min_similarity` | **0.6** | Min cosine similarity to allow semantic candidates |
| `semantic.min_fusion_score` | **0.5** | Final decision threshold after fusion |
| `semantic.weight_recency` | **0.2** | Recency boost weight |
| `semantic.weight_outcome` | **0.3** | Outcome effectiveness boost weight |
| `semantic.mmr_lambda` | **0.5** | Diversity balance (1.0 = relevance only) |
| `semantic.dedupe_similarity` | **0.92** | Dedupe near-duplicate results by embedding cosine |
| `semantic.index_on_write` | **true** | Index embeddings on insight write |
| `semantic.index_on_read` | **true** | Backfill missing embeddings at retrieval time |
| `semantic.index_backfill_limit` | **300** | Max insights to backfill per run |
| `semantic.index_cache_ttl_seconds` | **120** | Cache duration for vector index |
| `semantic.exclude_categories` | **[]** | Categories to exclude from semantic results (e.g., `["context"]`) |
| `semantic.log_retrievals` | **true** | Log semantic retrieval events to `~/.spark/logs/semantic_retrieval.jsonl` |

Trigger rules (YAML):

| Parameter | Default | Description |
|----------|---------|-------------|
| `triggers.enabled` | **false** | Enable explicit trigger rules |
| `triggers.rules_file` | **~/.spark/trigger_rules.yaml** | YAML rules file |

Environment overrides:
- `SPARK_SEMANTIC_ENABLED=1`
- `SPARK_TRIGGERS_ENABLED=1`

---

## 12. Memory Capture

**File:** `lib/memory_capture.py`

Memory Capture scans user messages for statements worth persisting. It uses keyword triggers and heuristics to identify preferences, rules, and decisions.

### How It Works

```
User Message → Score Against Triggers → Above Auto-Save? → Save Automatically
                                     → Above Suggest? → Queue for Review
                                     → Below Suggest? → Ignore
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `AUTO_SAVE_THRESHOLD` | **0.82** | **Auto-save cutoff.** Statements scoring 82%+ are saved without confirmation. High threshold ensures only clear signals auto-save. |
| `SUGGEST_THRESHOLD` | **0.55** | **Suggestion cutoff.** Statements scoring 55-82% are queued for user review. Below 55% is ignored. |
| `MAX_CAPTURE_CHARS` | **2000** | **Length limit.** Maximum characters to capture. Longer statements are truncated. |

### Hard Triggers (Explicit Signals)

These keywords trigger high scores immediately:

| Trigger Phrase | Score | Why |
|----------------|-------|-----|
| "remember this" | 1.0 | Explicit persistence request |
| "don't forget" | 0.95 | Strong persistence signal |
| "lock this in" | 0.95 | Commitment language |
| "non-negotiable" | 0.95 | Boundary/constraint |
| "hard rule" | 0.95 | Explicit rule definition |
| "hard boundary" | 0.95 | Constraint definition |
| "from now on" | 0.85 | Future-oriented preference |
| "always" | 0.65 | Generalization signal |
| "never" | 0.65 | Prohibition signal |

### Soft Triggers (Implicit Signals)

| Trigger | Score | Interpretation |
|---------|-------|----------------|
| "I prefer" | 0.55 | Preference |
| "I hate" | 0.75 | Strong negative preference |
| "I need" | 0.50 | Requirement |
| "design constraint" | 0.65 | Technical constraint |
| "for this project" | 0.65 | Project-specific context |

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Too many auto-saves | Raise `AUTO_SAVE_THRESHOLD` to 0.90 |
| Missing important preferences | Lower `AUTO_SAVE_THRESHOLD` to 0.75 |
| Too many suggestions to review | Raise `SUGGEST_THRESHOLD` to 0.65 |
| Long statements getting cut off | Raise `MAX_CAPTURE_CHARS` to 3000 |

---

## 13. Event Queue

**File:** `lib/queue.py`

The Event Queue captures all Spark events (tool calls, user prompts, errors) with < 10ms latency. Background processing handles the heavy lifting.

### How It Works

```
Event → Quick Capture (< 10ms) → Append to JSONL File → Background Processing
                                           ↓
                              Rotate when MAX_EVENTS exceeded
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_EVENTS` | **10000** | **Rotation threshold.** When queue exceeds 10,000 events, oldest half is discarded. Balances history retention vs file size. |
| `TAIL_CHUNK_BYTES` | **65536** | **Read chunk size (64KB).** When reading recent events, reads this much at a time. Larger = faster for big files, more memory. |

### Queue Location

```
~/.spark/queue/events.jsonl
```

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Need more history | Raise `MAX_EVENTS` to 50000 |
| Disk space constrained | Lower `MAX_EVENTS` to 5000 |
| Large events (long outputs) | Raise `TAIL_CHUNK_BYTES` to 131072 (128KB) |
| Memory constrained | Lower `TAIL_CHUNK_BYTES` to 32768 (32KB) |

---

## 14. Promoter (Insight → CLAUDE.md)

**File:** `lib/promoter.py`

The Promoter automatically promotes high-quality insights to project documentation (CLAUDE.md, AGENTS.md, etc.) where they'll be loaded every session.

### How It Works

```
Cognitive Insights → Filter by Reliability/Validations → Filter Operational Noise → Filter Safety → Write to Target File
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `DEFAULT_PROMOTION_THRESHOLD` | **0.65** | **Reliability requirement.** Insights must have 65%+ reliability to be promoted. (Lowered from 0.7 for faster learning) |
| `DEFAULT_MIN_VALIDATIONS` | **2** | **Validation requirement.** Insights must be validated 2+ times before promotion. (Lowered from 3 for faster learning) |

### Safety Filters

**Operational patterns blocked** (tool telemetry, not human-useful):
- Tool sequences: `"Bash → Edit"`, `"Read → Write"`
- Usage counts: `"42 calls"`, `"heavy usage"`
- Metrics: `"success rate"`, `"error rate"`

**Safety patterns blocked** (harmful content):
- Deception-related language
- Manipulation-related language
- Harassment-related language

### Promotion Targets

| Target File | Categories | What Goes There |
|-------------|------------|-----------------|
| CLAUDE.md | WISDOM, REASONING, CONTEXT | Project conventions, gotchas, patterns |
| AGENTS.md | META_LEARNING, SELF_AWARENESS | Workflow patterns, blind spots |
| TOOLS.md | CONTEXT | Tool-specific insights |
| SOUL.md | USER_UNDERSTANDING, COMMUNICATION | User preferences, communication style |

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| CLAUDE.md getting cluttered | Raise both thresholds |
| Important insights not promoting | Lower `DEFAULT_MIN_VALIDATIONS` to 2 |
| Want only high-confidence | Raise `DEFAULT_PROMOTION_THRESHOLD` to 0.8 |

---

## 15. Importance Scorer (Weights & Domains)

**File:** `lib/importance_scorer.py`

Extended configuration for domain-specific importance weighting.

### Default Keyword Weights

These keywords boost importance scores across all domains:

```python
DEFAULT_WEIGHTS = {
    "user": 1.3,        # User-related content is important
    "preference": 1.4,  # Explicit preferences highly valued
    "decision": 1.3,    # Decisions should be remembered
    "principle": 1.3,   # Principles guide future actions
    "style": 1.2,       # Style preferences matter
}
```

### Domain-Specific Weights

When a domain is active, these keywords get boosted:

**Game Development (`game_dev`):**
```python
{
    "balance": 1.5,     # Game balance is critical
    "feel": 1.5,        # Game feel is critical
    "gameplay": 1.4,    # Gameplay decisions
    "physics": 1.3,     # Physics tuning
    "collision": 1.2,   # Collision behavior
    "spawn": 1.2,       # Spawn mechanics
    "difficulty": 1.3,  # Difficulty tuning
    "player": 1.3,      # Player experience
}
```

**Finance/Fintech (`fintech`):**
```python
{
    "compliance": 1.5,   # Regulatory requirements
    "security": 1.5,     # Security is paramount
    "transaction": 1.4,  # Transaction handling
    "risk": 1.4,         # Risk management
    "audit": 1.3,        # Audit requirements
    "validation": 1.3,   # Data validation
}
```

**Marketing (`marketing`):**
```python
{
    "audience": 1.5,     # Target audience
    "conversion": 1.5,   # Conversion optimization
    "messaging": 1.4,    # Message crafting
    "channel": 1.3,      # Channel strategy
    "campaign": 1.3,     # Campaign management
    "roi": 1.4,          # ROI considerations
}
```

**Product (`product`):**
```python
{
    "user": 1.5,        # User focus
    "feature": 1.4,     # Feature decisions
    "feedback": 1.4,    # User feedback
    "priority": 1.3,    # Prioritization
    "roadmap": 1.3,     # Roadmap planning
}
```

### Adding New Domains

To add a new domain, add to `DOMAIN_WEIGHTS` dict in `lib/importance_scorer.py`:

```python
DOMAIN_WEIGHTS["healthcare"] = {
    "hipaa": 1.5,
    "patient": 1.5,
    "clinical": 1.4,
    "ehr": 1.3,
}
```

---

## 16. Environment Variables

System-wide configuration via environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `SPARK_NO_WATCHDOG` | `false` | **Disable watchers.** Set to `true` to turn off all watcher enforcement. Use for debugging only. |
| `SPARK_OUTCOME_AUTO_LINK` | `true` | **Auto-link outcomes.** Automatically link outcomes to their originating Steps. |
| `SPARK_AGENT_CONTEXT_MAX_CHARS` | `1200` | **Agent context char budget.** Canonical max chars for injected compact context. |
| `SPARK_AGENT_CONTEXT_LIMIT` | alias | Backward-compatible alias for `SPARK_AGENT_CONTEXT_MAX_CHARS`. |
| `SPARK_AGENT_CONTEXT_ITEM_LIMIT` | unset | Optional max number of compact context items (falls back to function default). |
| `SPARK_DEBUG` | `false` | **Debug mode.** Enables verbose logging across all components. |
| `SPARK_MIND_PORT` | `8080` | **Mind API port.** Port for Mind persistent memory service. |
| `SPARKD_PORT` | `8787` | **sparkd port.** Port for ingest/health. |
| `SPARK_PULSE_PORT` | `8765` | **Spark Pulse port.** |
| `SPARK_LOG_DIR` | `~/.spark/logs` | **Log directory.** Overrides log output directory. |
| `SPARK_LOG_MAX_BYTES` | `10485760` | **Log rotation size.** Bytes before rotating. |
| `SPARK_LOG_BACKUPS` | `5` | **Log rotation backups.** Number of rotated files to keep. |
| `SPARK_QUEUE_MAX_EVENTS` | `10000` | **Queue event cap.** Rotate after this many events. |
| `SPARK_QUEUE_MAX_BYTES` | `10485760` | **Queue size cap.** Rotate after this many bytes. |

### Usage

```bash
# Disable watchers for debugging
export SPARK_NO_WATCHDOG=true

# Enable debug logging
export SPARK_DEBUG=true

# Use non-default Mind port
export SPARK_MIND_PORT=8081
```

---

## 17. Chips (Activation & Validation)

**Files:** `lib/chips/loader.py`, `lib/chips/registry.py`, `lib/chips/schema.py`, `lib/metalearning/strategist.py`

Chip behavior is influenced by activation policy, auto-activation sensitivity, and schema validation mode.

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `chip.activation` | **auto / opt_in** | **Per-chip activation policy** in YAML. `auto` chips can be auto-activated from content. `opt_in` chips require explicit activation. |
| `auto_activate_threshold` | **0.7** | **Metalearning auto-activation sensitivity.** Higher = fewer auto-activations. |
| `trigger_deprecation_threshold` | **0.2** | **Deprecation threshold** for weak triggers in metalearning strategy. |
| `provisional_chip_confidence` | **0.3** | **Minimum confidence** to promote a provisional chip. |
| `SPARK_CHIP_SCHEMA_VALIDATION` | **warn** | **Schema validation mode**: `warn` (default) or `block` to reject invalid chips. |

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Too many chips auto-activating | Raise `auto_activate_threshold` or set more chips to `opt_in` |
| Trigger noise persists | Raise `trigger_deprecation_threshold` |
| Provisional chips too aggressive | Raise `provisional_chip_confidence` |
| CI wants strict validation | Set `SPARK_CHIP_SCHEMA_VALIDATION=block` |

---

## 18. Opportunity Scanner (Self-Socratic Evolution Loop)

**File:** `lib/opportunity_scanner.py`

The Opportunity Scanner generates self-Socratic prompts, tracks acted outcomes with strict trace linkage, and promotes high-performing opportunity patterns into EIDOS distillation observations.

### Parameters (Environment Variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `SPARK_OPPORTUNITY_SCANNER` | `1` | Master enable/disable for scanner runtime. |
| `SPARK_OPPORTUNITY_SELF_MAX` | `3` | Max self-opportunities emitted per cycle. |
| `SPARK_OPPORTUNITY_USER_MAX` | `2` | Max user-facing opportunities when user scan is enabled. |
| `SPARK_OPPORTUNITY_USER_SCAN` | `0` | Opt-in switch for user-facing opportunity prompts. Self-scan remains active by default. |
| `SPARK_OPPORTUNITY_HISTORY_MAX` | `500` | Max retained JSONL lines per scanner file. |
| `SPARK_OPPORTUNITY_SELF_DEDUP_WINDOW_S` | `14400` | Recent-window de-dup horizon for self-opportunity questions. |
| `SPARK_OPPORTUNITY_SELF_RECENT_LOOKBACK` | `240` | Number of recent rows inspected for de-dup checks. |
| `SPARK_OPPORTUNITY_SELF_CATEGORY_CAP` | `1` | Per-cycle cap per category during diversity selection. |
| `SPARK_OPPORTUNITY_OUTCOME_WINDOW_S` | `21600` | Max age window for evaluating acted outcomes against recent opportunities. |
| `SPARK_OPPORTUNITY_OUTCOME_LOOKBACK` | `200` | Number of recent opportunities/outcomes scanned for attribution. |
| `SPARK_OPPORTUNITY_PROMOTION_MIN_SUCCESSES` | `2` | Minimum good outcomes required before promotion candidate generation. |
| `SPARK_OPPORTUNITY_PROMOTION_MIN_EFFECTIVENESS` | `0.66` | Minimum good/acted ratio for promotion eligibility. |
| `SPARK_OPPORTUNITY_PROMOTION_LOOKBACK` | `400` | Rows scanned when building promotion candidates. |
| `SPARK_OPPORTUNITY_LLM_ENABLED` | `1` | Enable LLM-backed opportunity proposal path (deterministic path still runs as fallback). |
| `SPARK_OPPORTUNITY_LLM_PROVIDER` | `auto` | Preferred provider for scanner LLM path (`minimax`, `ollama`, `openai`, `anthropic`, `gemini`). |
| `SPARK_OPPORTUNITY_LLM_TIMEOUT_S` | `2.5` | Per-provider timeout for scanner LLM synthesis. |
| `SPARK_OPPORTUNITY_LLM_MAX_ITEMS` | `3` | Max sanitized LLM opportunity candidates merged each cycle. |

### Operational Checks

```bash
# Status summary (enabled, adoption_rate, recent files)
python -c "from lib.opportunity_scanner import get_scanner_status; import json; print(json.dumps(get_scanner_status(), indent=2))"

# Recent self-opportunities
python -c "from lib.opportunity_scanner import get_recent_self_opportunities; import json; print(json.dumps(get_recent_self_opportunities(limit=5), indent=2))"

# Bridge heartbeat includes scanner stats
python -c "import json; from pathlib import Path; p=Path.home()/'.spark'/'bridge_worker_heartbeat.json'; d=json.loads(p.read_text(encoding='utf-8')); print(json.dumps((d.get('stats') or {}).get('opportunity_scanner') or {}, indent=2))"

# Raw scanner artifacts (self, outcomes, promotions)
python -c "from pathlib import Path; b=Path.home()/'.spark'/'opportunity_scanner'; print('self', (b/'self_opportunities.jsonl').exists(), 'outcomes', (b/'outcomes.jsonl').exists(), 'promotions', (b/'promoted_opportunities.jsonl').exists())"
```

---

## Monitoring Commands

```bash
# Check distillation stats
spark eidos --stats

# View recent distillations
spark eidos --distillations

# Check memory gate stats
python -c "from lib.pattern_detection import get_memory_gate; print(get_memory_gate().get_stats())"

# Check aggregator stats
python -c "from lib.pattern_detection import get_aggregator; print(get_aggregator().get_stats())"

# View EIDOS store stats
python -c "from lib.eidos import get_store; print(get_store().get_stats())"

# Check importance scorer stats
python -c "from lib.importance_scorer import get_importance_scorer; print(get_importance_scorer().get_feedback_stats())"

# Check advisor effectiveness
python -c "from lib.advisor import get_advisor; print(get_advisor().get_effectiveness_report())"

# Check promoter status
python -c "from lib.promoter import get_promotion_status; print(get_promotion_status())"

# Check queue stats
python -c "from lib.queue import get_queue_stats; print(get_queue_stats())"
```

---

## Quick Parameter Index

### Learning Quality Pipeline

```
User Input → Memory Capture (0.82 auto-save)
         → Pattern Detection (0.7 confidence)
         → Distillation (3 occurrences, 0.6 success rate)
         → Memory Gate (0.5 threshold)
         → Cognitive Storage
         → Promotion (0.7 reliability, 3 validations)
         → CLAUDE.md
```

### Stuck Detection Pipeline

```
Action → Budget Check (25 steps, 12 min)
     → Watcher Check (repeat error 2x, no evidence 5x)
     → Phase Transition → DIAGNOSE/HALT
```

### Memory Decay Pipeline

```
Insight Created → Daily Decay (category half-life)
              → Effective Reliability Drops
              → Below 0.2? → Pruned
              → Over 365 days? → Pruned
```

---

## Testing Recommendations

### 1. Memory Gate Testing
```python
from lib.pattern_detection import get_memory_gate
gate = get_memory_gate()

# Create test step with known quality
# Verify gate.score_step() returns expected score
# Check gate.get_stats() for pass/reject rates
```

### 2. Distillation Quality Testing
```python
from lib.pattern_detection import get_pattern_distiller
distiller = get_pattern_distiller()

# Process known patterns
# Verify distillation statements make sense
# Check confidence scores match expectations
```

### 3. Watcher Testing
```python
from lib.eidos import get_elevated_control_plane
control = get_elevated_control_plane()

# Simulate stuck scenarios
# Verify watchers trigger at thresholds
# Check phase transitions happen correctly
```

### 4. Importance Scorer Testing
```bash
# Test specific text
spark importance --text "Remember this: always use dark theme"

# Should return CRITICAL tier

spark importance --text "okay got it"

# Should return LOW/IGNORE tier
```

### 5. End-to-End Learning Test
1. Send user message with "remember this" trigger
2. Verify auto-save in cognitive_insights.json
3. Validate 3 times
4. Check promotion to CLAUDE.md
5. Verify retrieval in next session

---

## 9. Meta-Ralph (Telemetry + Optional Gate)

**Files:** `lib/meta_ralph.py`, `lib/production_gates.py` (vibeship-spark)

Meta-Ralph remains active for scoring/telemetry of proposed learnings. Production readiness gating on Meta-Ralph quality-band is now optional and controlled from production gate tuneables.

### How It Works

Every learning is scored 0-10 on five dimensions. The total score determines the verdict:

```
Total = actionability + novelty + reasoning + specificity + outcome_linked
```

### Thresholds

| Parameter | Default | Description |
|-----------|---------|-------------|
| `quality_threshold` | **3.8** (runtime baseline) / **4.5** (schema fallback) | Items scoring >= threshold pass as QUALITY. Runtime baseline was lowered after over-filtering; schema fallback remains conservative if runtime config is missing. Wired to `meta_ralph.quality_threshold`. |
| `needs_work_threshold` | **2** | Items scoring 2-3 are NEEDS_WORK (refinable). Wired to `meta_ralph.needs_work_threshold`. |
| `primitive_threshold` | **<2** | Items scoring < 2 are PRIMITIVE (rejected). |

Production gate behavior:
- `production_gates.enforce_meta_ralph_quality_band` defaults to `false` (telemetry-only mode).
- When set to `true`, readiness enforces the quality band once `production_gates.min_quality_samples` is met.

### Scoring Dimensions

Each dimension scores 0-2:

| Dimension | 0 | 1 | 2 |
|-----------|---|---|---|
| **Actionability** | Can't act on it | Vague guidance | Specific action |
| **Novelty** | Already obvious | Somewhat new | Genuine insight |
| **Reasoning** | No "why" | Implied "why" | Explicit "because" |
| **Specificity** | Generic | Domain-specific | Context-specific |
| **Outcome Linked** | No outcome | Implied outcome | Validated outcome |

### Scoring Examples

**QUALITY (score 7) - Passes:**
```
"User prefers dark theme because it reduces eye strain during late night coding"
- actionability: 2 (specific: use dark theme)
- novelty: 2 (learned this about user)
- reasoning: 2 (explicit "because")
- specificity: 1 (domain-specific)
- outcome_linked: 0 (no validation)
Total: 7 PASSES
```

**NEEDS_WORK (score 6) - Previously blocked, now passes:**
```
"For authentication, use OAuth with PKCE because it prevents token interception"
- actionability: 2 (specific: use PKCE)
- novelty: 1 (known best practice)
- reasoning: 2 (explicit "because")
- specificity: 0 (generic advice)
- outcome_linked: 1 (implied security outcome)
Total: 6 PASSES (after threshold lowered to 5)
```

**PRIMITIVE (score 3) - Correctly rejected:**
```
"For read tasks, use standard approach"
- actionability: 2 (action: use standard)
- novelty: 0 (obvious)
- reasoning: 0 (no "why")
- specificity: 1 (task-specific)
- outcome_linked: 0 (no outcome)
Total: 3 REJECTED
```

### Tuneable Analysis

Meta-Ralph continuously analyzes its own filter performance and recommends adjustments:

| Metric | Healthy Range | Issue | Recommendation |
|--------|--------------|-------|----------------|
| Pass rate | 15-40% | <10% | Lower threshold |
| Pass rate | 15-40% | >60% | Raise threshold |
| Primitive rate | 30-70% | <20% | Filter too loose |
| Primitive rate | 30-70% | >80% | Filter too tight |

### When to Tune

| Scenario | Adjustment |
|----------|------------|
| Valuable insights being blocked | Lower `quality_threshold` to 4-5 |
| Too much noise passing through | Raise `quality_threshold` to 6-7 |
| Want more reasoning-based learning | Raise reasoning weight |
| Need faster learning | Lower novelty requirements |

### History

| Date | Change | Reason |
|------|--------|--------|
| 2026-02-03 | quality_threshold 7→5 | Over-filtering (2.8% pass rate) blocking valuable insights like OAuth/PKCE advice |
| 2026-02-04 | quality_threshold 5→4 | Still over-filtering after iterative Ralph loop analysis |
| 2026-02-05 | All tuneables wired to `tuneables.json` | Audit found most constants were hard-coded and ignored config |

### Monitoring

```bash
# Check Meta-Ralph stats
python -c "from lib.meta_ralph import get_meta_ralph; print(get_meta_ralph().get_stats())"

# Check tuneable recommendations
python -c "from lib.meta_ralph import get_meta_ralph; import json; print(json.dumps(get_meta_ralph().analyze_tuneables(), indent=2))"

# Dashboard (if running)
curl http://localhost:8788/api/stats
```

---

## 10. Advisory Foundation (Predictive Layer)

**Files:** `lib/advisory_engine.py`, `lib/advisory_packet_store.py`, `lib/advisory_memory_fusion.py`, `lib/advisory_intent_taxonomy.py`, `lib/advisory_synthesizer.py`

This is the active hot-path advisory stack used by hooks:

1. `PreToolUse` -> `advisory_engine.on_pre_tool`
2. intent/plane mapping -> packet lookup (`exact`, then `relaxed`)
3. fallback to live advisor retrieval when packet miss
4. gate + synthesis + stdout emission
5. packet writeback + post-tool outcome feedback + invalidation

### Core Runtime Knobs (env)

| Variable | Default | Effect |
|----------|---------|--------|
| `SPARK_ADVISORY_ENGINE` | `1` | Master on/off for advisory engine path. |
| `SPARK_ADVISORY_MAX_MS` | `4000` | Total budget for one advisory hook execution. |
| `SPARK_ADVISORY_STALE_S` | `900` | Delivery badge stale window for `live|fallback|blocked|stale` classification. |
| `SPARK_ADVISORY_TEXT_REPEAT_COOLDOWN_S` | `1800` | Suppress re-emitting same advisory text during cooldown window. |
| `SPARK_ADVISORY_REQUIRE_ACTION` | `1` | Enforce actionable next-check text when advisory is too generic. |
| `SPARK_ADVISORY_FORCE_PROGRAMMATIC_SYNTH` | `1` | Force programmatic synthesis (no AI/network) on the pre-tool hot path. Tuneable `advisory_engine.force_programmatic_synth` (if set) overrides this. |
| `SPARK_ADVISORY_SESSION_KEY_INCLUDE_RECENT_TOOLS` | `0` | Include recent tool sequence in packet exact-keying (higher specificity, lower cache hit rate). Tuneable `advisory_engine.session_key_include_recent_tools` (if set) overrides this. |
| `SPARK_ADVISORY_PREFETCH_QUEUE` | `1` | Enables enqueueing background prefetch jobs from user prompts. |
| `SPARK_ADVISORY_PACKET_FALLBACK_EMIT` | `0` | Enables packet no-emit deterministic fallback emission. Default `0` keeps fallback output opt-in. |
| `SPARK_ADVISORY_FALLBACK_RATE_GUARD` | `1` | Enables rate guard for packet no-emit fallback emissions. |
| `SPARK_ADVISORY_FALLBACK_RATE_MAX_RATIO` | `0.55` | Maximum allowed fallback share in recent delivered advisories. |
| `SPARK_ADVISORY_FALLBACK_RATE_WINDOW` | `80` | Rolling advisory event window used by fallback rate guard. |
| `SPARK_ADVISORY_INCLUDE_MIND` | `0` | Default for Mind retrieval inclusion. Tuneable `advisory_engine.include_mind` (if set) overrides this. |
| `SPARK_ADVISORY_EMIT` | `1` | Enables writing advisory text to stdout hook output. |
| `SPARK_ADVISORY_MAX_CHARS` | `500` | Caps emitted advisory length. |
| `SPARK_ADVISORY_FORMAT` | `inline` | Advisory formatting style (`inline` or `block`). |

### Context Sync Target Policy (env)

| Variable | Default | Effect |
|----------|---------|--------|
| `SPARK_SYNC_MODE` | `core` | Sync adapter mode: `core` writes only `openclaw` + `exports`; `all` enables all adapters. |
| `SPARK_SYNC_TARGETS` | _(unset)_ | Explicit comma-list of enabled adapters (overrides mode). |
| `SPARK_SYNC_DISABLE_TARGETS` | _(unset)_ | Comma-list of adapters to force-disable after mode/list resolution. |

### Synthesis Route Knobs (env + tuneables)

| Variable/Key | Default | Effect |
|--------------|---------|--------|
| `SPARK_SYNTH_MODE` / `synthesizer.mode` | `auto` | `auto`, `ai_only`, or `programmatic`. |
| `SPARK_SYNTH_TIMEOUT` / `synthesizer.ai_timeout_s` | `3.0` | AI synthesis timeout ceiling. |
| `SPARK_OLLAMA_MODEL` | `phi4-mini` | Default local model for synthesis. |
| `SPARK_OLLAMA_API` | `http://localhost:11434` | Local Ollama endpoint. |
| `SPARK_SYNTH_PREFERRED_PROVIDER` | _(unset)_ | Env override for preferred provider (`ollama`, `gemini`, `minimax`, `openai`, `anthropic`). |
| `SPARK_MINIMAX_MODEL` | `MiniMax-M2.5` | MiniMax model for synthesis when provider route is `minimax`. |
| `SPARK_MINIMAX_BASE_URL` | `https://api.minimax.io/v1` | MiniMax OpenAI-compatible base URL. |
| `MINIMAX_API_KEY` | _(unset)_ | Enables MiniMax synthesis provider when set. |
| `synthesizer.preferred_provider` | `auto` | Provider preference (`ollama`, `gemini`, `minimax`, `openai`, `anthropic`). |
| `synthesizer.cache_ttl_s` | `120` | Synthesis cache TTL. |
| `synthesizer.max_cache_entries` | `50` | Synthesis cache size cap. |

### Packet Store Defaults

| Constant | Default | Effect |
|----------|---------|--------|
| `DEFAULT_PACKET_TTL_S` | `900` | Packet freshness TTL in seconds. |
| `MAX_INDEX_PACKETS` | `2000` | Max packet metadata entries retained. |

### Recommended `~/.spark/tuneables.json` block

```json
{
  "preset": "custom",
  "values": {
    "min_occurrences": 1,
    "min_occurrences_critical": 1,
    "confidence_threshold": 0.6,
    "gate_threshold": 0.45,
    "max_retries_per_error": 3,
    "max_file_touches": 5,
    "no_evidence_steps": 6,
    "min_confidence_delta": 0.08,
    "weight_impact": 0.25,
    "weight_novelty": 0.25,
    "weight_surprise": 0.35,
    "weight_irreversible": 0.45,
    "max_steps": 40,
    "episode_timeout_minutes": 20,
    "advice_cache_ttl": 180,
    "queue_batch_size": 100
  },
  "semantic": {
    "enabled": true,
    "min_similarity": 0.58,
    "min_fusion_score": 0.5,
    "weight_recency": 0.1,
    "weight_outcome": 0.35,
    "mmr_lambda": 0.5,
    "dedupe_similarity": 0.92,
    "index_on_write": true,
    "index_on_read": true,
    "index_backfill_limit": 500,
    "index_cache_ttl_seconds": 120,
    "exclude_categories": [],
    "category_caps": {
      "cognitive": 3,
      "trigger": 2,
      "default": 2,
      "user_understanding": 2,
      "context": 2,
      "self_awareness": 2,
      "meta_learning": 1,
      "wisdom": 2,
      "reasoning": 2
    },
    "category_exclude": [],
    "log_retrievals": true
  },
  "triggers": {
    "enabled": true,
    "rules_file": "~/.spark/trigger_rules.yaml"
  },
  "promotion": {
    "adapter_budgets": {
      "CLAUDE.md": {
        "max_items": 40
      },
      "AGENTS.md": {
        "max_items": 30
      },
      "TOOLS.md": {
        "max_items": 25
      },
      "SOUL.md": {
        "max_items": 25
      },
      ".cursorrules": {
        "max_items": 40
      },
      ".windsurfrules": {
        "max_items": 40
      }
    },
    "confidence_floor": 0.9,
    "min_age_hours": 2.0,
    "auto_interval_s": 3600,
    "threshold": 0.5
  },
  "synthesizer": {
    "mode": "auto",
    "ai_timeout_s": 12,
    "cache_ttl_s": 120,
    "max_cache_entries": 50,
    "preferred_provider": "auto"
  },
  "advisory_engine": {
    "enabled": true,
    "max_ms": 3500,
    "include_mind": true,
    "prefetch_queue_enabled": true,
    "prefetch_inline_enabled": true,
    "prefetch_inline_max_jobs": 1,
    "delivery_stale_s": 900,
    "advisory_text_repeat_cooldown_s": 9000,
    "actionability_enforce": true
  },
  "advisory_gate": {
    "max_emit_per_call": 1,
    "tool_cooldown_s": 150,
    "advice_repeat_cooldown_s": 5400,
    "warning_threshold": 0.8,
    "note_threshold": 0.5,
    "whisper_threshold": 0.35
  },
  "advisory_packet_store": {
    "packet_ttl_s": 600,
    "max_index_packets": 2000,
    "relaxed_effectiveness_weight": 2.0,
    "relaxed_low_effectiveness_threshold": 0.3,
    "relaxed_low_effectiveness_penalty": 0.5
  },
  "advisory_prefetch": {
    "worker_enabled": true,
    "max_jobs_per_run": 2,
    "max_tools_per_job": 3,
    "min_probability": 0.25
  },
  "advisor": {
    "min_reliability": 0.5,
    "min_validations_strong": 2,
    "max_items": 3,
    "cache_ttl": 180,
    "min_rank_score": 0.55,
    "max_advice_items": 3,
    "mind_max_stale_s": 172800,
    "mind_stale_allow_if_empty": true,
    "mind_min_salience": 0.55
  },
  "retrieval": {
    "level": "2",
    "overrides": {
      "mode": "auto",
      "gate_strategy": "minimal",
      "semantic_limit": 10,
      "max_queries": 3,
      "agentic_query_limit": 3,
      "agentic_deadline_ms": 700,
      "agentic_rate_limit": 0.2,
      "agentic_rate_window": 80,
      "fast_path_budget_ms": 250,
      "prefilter_enabled": true,
      "prefilter_max_insights": 500,
      "lexical_weight": 0.28,
      "bm25_k1": 1.2,
      "bm25_b": 0.75,
      "bm25_mix": 0.75,
      "complexity_threshold": 2,
      "min_results_no_escalation": 4,
      "min_top_score_no_escalation": 0.72,
      "escalate_on_high_risk": true,
      "escalate_on_trigger": false,
      "semantic_context_min": 0.18,
      "semantic_lexical_min": 0.05,
      "semantic_strong_override": 0.92
    }
  },
  "chip_merge": {
    "duplicate_churn_ratio": 0.8,
    "duplicate_churn_min_processed": 10,
    "duplicate_churn_cooldown_s": 1800,
    "min_cognitive_value": 0.25,
    "min_actionability": 0.15,
    "min_transferability": 0.15,
    "min_statement_len": 20
  },
  "auto_tuner": {
    "enabled": true,
    "mode": "suggest",
    "max_changes_per_cycle": 2,
    "run_interval_s": 86400,
    "max_change_per_run": 0.15
  },
  "meta_ralph": {
    "quality_threshold": 3.8,
    "needs_work_threshold": 2,
    "needs_work_close_delta": 0.5,
    "min_outcome_samples": 5,
    "min_tuneable_samples": 50,
    "min_needs_work_samples": 5,
    "min_source_samples": 15,
    "attribution_window_s": 1200,
    "strict_attribution_require_trace": true
  },
  "production_gates": {
    "enforce_meta_ralph_quality_band": false,
    "min_quality_samples": 50,
    "min_quality_rate": 0.30,
    "max_quality_rate": 0.60
  },
  "eidos": {
    "max_time_seconds": 1200,
    "max_retries_per_error": 3,
    "max_file_touches": 5,
    "no_evidence_limit": 6
  },
  "scheduler": {
    "enabled": true,
    "mention_poll_interval": 600,
    "engagement_snapshot_interval": 1800,
    "daily_research_interval": 86400,
    "niche_scan_interval": 21600,
    "mention_poll_enabled": true,
    "engagement_snapshot_enabled": true,
    "daily_research_enabled": true,
    "niche_scan_enabled": true,
    "advisory_review_interval": 43200,
    "advisory_review_enabled": true,
    "advisory_review_window_hours": 12
  }
}
```

### Operational Notes

- Predictive advisory requires `PreToolUse` hook wiring in Claude Code.
- With `mode=auto`, advisory remains deterministic-safe when AI is slow or unavailable.
- First-turn coverage is improved by baseline packets generated on `UserPromptSubmit`.

### Auto-Tuner Modes (Important)

Valid `auto_tuner.mode` values:
- `suggest`: log-only recommendations (safest default)
- `conservative`: apply only high-confidence, low-impact recommendations
- `moderate`: apply recommendations with confidence > 0.5
- `aggressive`: apply all selected recommendations

Legacy value `data_driven` is not a recognized mode in runtime apply logic and can behave like aggressive fallback. Do not use it.

---

## Tuneable Wiring Summary

All tuneables are now loaded from `~/.spark/tuneables.json` at module import time.
Components fall back to hard-coded defaults when a key is absent.

### tuneables.json Section Map

| JSON Section | Component | Keys |
|-------------|-----------|------|
| `preset` | Tuneables preset selection | Preset id string (e.g., `custom`) |
| `updated_at` | Tuneables metadata | ISO timestamp string (written by some automated updaters) |
| `values` | Pattern distiller, memory gate, EIDOS (fallback) | `min_occurrences`, `confidence_threshold`, `gate_threshold`, `min_confidence_delta`, `max_steps`, `max_retries_per_error`, `max_file_touches`, `no_evidence_steps`, `queue_batch_size`, `advice_cache_ttl` |
| `semantic` | Semantic retriever | `enabled`, `min_similarity`, `min_fusion_score`, `weight_recency`, `weight_outcome`, `mmr_lambda`, `category_caps`, etc. |
| `triggers` | Trigger rules | `enabled`, `rules_file` |
| `promotion` | Promoter + auto-promotion interval | `adapter_budgets`, `confidence_floor`, `min_age_hours`, `auto_interval_s` |
| `synthesizer` | Advisory synthesizer | `mode`, `preferred_provider`, `ai_timeout_s`, `cache_ttl_s`, `max_cache_entries` |
| `advisor` | Advisor | `min_reliability`, `min_validations_strong`, `max_items`, `max_advice_items` (compat), `cache_ttl`, `min_rank_score`, `mind_max_stale_s`, `mind_stale_allow_if_empty`, `mind_min_salience` |
| `retrieval` | Advisor retrieval router | `level`, `overrides.*` (mode/gates/budgets, lexical blend, and routing thresholds like `semantic_context_min`) |
| `advisory_engine` | Predictive advisory orchestration | `enabled`, `max_ms`, `include_mind`, `prefetch_queue_enabled`, `prefetch_inline_enabled`, `prefetch_inline_max_jobs`, `packet_fallback_emit_enabled`, `fallback_rate_guard_enabled`, `fallback_rate_max_ratio`, `fallback_rate_window`, `delivery_stale_s`, `advisory_text_repeat_cooldown_s`, `actionability_enforce` |
| `advisory_gate` | Advisory emission policy | `max_emit_per_call`, `tool_cooldown_s`, `advice_repeat_cooldown_s`, `warning_threshold`, `note_threshold`, `whisper_threshold` |
| `advisory_packet_store` | Packet lifecycle + relaxed lookup weighting | `packet_ttl_s`, `max_index_packets`, `relaxed_effectiveness_weight`, `relaxed_low_effectiveness_threshold`, `relaxed_low_effectiveness_penalty` |
| `advisory_prefetch` | Prefetch worker planning limits | `worker_enabled`, `max_jobs_per_run`, `max_tools_per_job`, `min_probability` |
| `sync` | Context sync output targets (optional) | `mode`, `adapters_enabled`, `adapters_disabled` |
| `chip_merge` | Chip merge duplicate churn + learning distillation quality gates | `duplicate_churn_ratio`, `duplicate_churn_min_processed`, `duplicate_churn_cooldown_s`, `min_cognitive_value`, `min_actionability`, `min_transferability`, `min_statement_len` |
| `auto_tuner` | Feedback-driven tune recommendations and bounded apply | `enabled`, `mode`, `max_changes_per_cycle`, `run_interval_s`, `max_change_per_run`, `source_boosts` |
| `request_tracker` | EIDOS request envelope retention + timeout policy (optional) | `max_pending`, `max_completed`, `max_age_seconds` |
| `memory_capture` | Conversational memory auto-save/suggestion policy (optional) | `auto_save_threshold`, `suggest_threshold`, `max_capture_chars` |
| `queue` | Queue growth + read safety limits (optional) | `max_events`, `tail_chunk_bytes` |
| `meta_ralph` | Meta-Ralph scoring thresholds | `quality_threshold`, `needs_work_threshold`, `needs_work_close_delta`, `min_outcome_samples`, `min_tuneable_samples` |
| `production_gates` | Production readiness gate thresholds | `enforce_meta_ralph_quality_band`, `min_quality_samples`, `min_quality_rate`, `max_quality_rate`, plus any `LoopThresholds` key override |
| `eidos` | EIDOS Budget defaults | `max_time_seconds`, `max_retries_per_error`, `max_file_touches`, `no_evidence_limit` |
| `scheduler` | Spark scheduler automation | `enabled`, `mention_poll_interval`, `engagement_snapshot_interval`, `daily_research_interval`, `niche_scan_interval`, `advisory_review_interval`, `advisory_review_window_hours`, `*_enabled` task flags |

### Backward Compatibility

Some keys have legacy/fallback compatibility paths across sections:

- `values.max_steps` -> EIDOS step budget (canonical key; legacy `eidos.max_steps` may still be read if present)
- `values.max_retries_per_error` -> `eidos.max_retries_per_error`
- `values.max_file_touches` -> `eidos.max_file_touches`
- `values.no_evidence_steps` -> `eidos.no_evidence_limit` (key renamed)
- `values.min_confidence_delta` -> EIDOS confidence stagnation threshold
- `values.advice_cache_ttl` -> `advisor.cache_ttl`
- `values.queue_batch_size` -> pipeline `DEFAULT_BATCH_SIZE`

### Config Load Pattern

Each component loads tuneables at import time **and** registers a hot-reload callback:

```python
# 1. Import-time load (backwards compatible)
def _load_X_config():
    tuneables = Path.home() / ".spark" / "tuneables.json"
    data = json.loads(tuneables.read_text())
    cfg = data.get("section_name") or {}
    # Override module-level constants from cfg

_load_X_config()

# 2. Hot-reload registration (new — auto-applies on file change)
def reload_X_from(cfg: dict):
    # Update module globals from cfg dict
    ...

try:
    from lib.tuneables_reload import register_reload
    register_reload("section_name", reload_X_from)
except ImportError:
    pass
```

The coordinator (`lib/tuneables_reload.py`) checks file mtime each bridge cycle. When `tuneables.json` changes, it validates via schema (`lib/tuneables_schema.py`), then dispatches changed sections to registered callbacks.

### Tuneables Infrastructure

| Module | Purpose |
|--------|---------|
| `lib/tuneables_schema.py` | Central schema. Validates types, bounds, defaults, and clamps out-of-bounds values. |
| `lib/tuneables_reload.py` | Mtime-based hot-reload coordinator. Modules register callbacks; `check_and_reload()` dispatches changes. |
| `lib/tuneables_drift.py` | Drift distance metric. Compares runtime vs `config/tuneables.json` baseline. Alerts when drift > 0.3. |

### Hot-reload registered modules

| Section | Module | Callback |
|---------|--------|----------|
| `meta_ralph` | `lib/meta_ralph.py` | Quality thresholds, attribution window, suppression settings |
| `eidos` | `lib/eidos/models.py` | Budget constraints (max_time, max_retries, file touch/no-evidence limits) |
| `values` | `lib/pipeline.py` | Batch size (queue_batch_size) |
| `queue` | `lib/queue.py` | Max events, tail chunk bytes |
| `advisory_gate` | `lib/advisory_gate.py` | Emit limits, cooldowns, authority thresholds |
| `advisor` | `lib/advisor.py` | Replay config, ranking params, advice limits |

### Hot-apply vs restart-required (operator quick matrix)

| Area | Hot-apply | Restart required |
|------|-----------|------------------|
| `meta_ralph`, `eidos`, `advisor`, `advisory_gate`, `queue`, `values` (pipeline) | Yes (bridge cycle hot-reload) | No |
| `advisory_engine`, `advisory_packet_store`, `advisory_prefetch` | Yes (Pulse runtime apply) | No |
| `synthesizer` section | Yes (file mtime reload in synthesizer) | No |
| `auto_tuner` section | N/A (auto_tuner writes, not reads) | N/A |
| Environment variables (`SPARK_*`) | No (after process starts) | Yes |

Practical rule: most sections now hot-apply every bridge cycle. Edit `~/.spark/tuneables.json`, wait one cycle (~60s), changes take effect.

