# Spark V2: The Simplification Plan

> *"It is not that uncommon for the cost of an abstraction to outweigh the benefit it delivers. Kill one today!"*
> -- John Carmack

> *"The code for artificial general intelligence is going to be tens of thousands of lines of code -- not millions."*
> -- John Carmack, Lex Fridman Podcast #309

**Date**: 2026-02-26
**Status**: Implementation Plan
**Scope**: Reduce Spark Intelligence from 101K lines to ~30-35K while improving output quality

---

## Table of Contents

1. [The Problem Statement](#1-the-problem-statement)
2. [Landscape Analysis: What Others Do With Less](#2-landscape-analysis)
3. [The Carmack Lens](#3-the-carmack-lens)
4. [Gap Analysis: Where We're Over-Engineered](#4-gap-analysis)
5. [Gap Analysis: Where We're Under-Delivering](#5-gap-analysis-under-delivering)
6. [Proven Techniques From Research](#6-proven-techniques)
7. [The Implementation Plan](#7-the-implementation-plan)
8. [Phase 1: Storage Consolidation](#phase-1-storage-consolidation)
9. [Phase 2: Unified Noise Classifier](#phase-2-unified-noise-classifier)
10. [Phase 3: Advisory Collapse](#phase-3-advisory-collapse)
11. [Phase 4: Memory Compaction Engine](#phase-4-memory-compaction-engine)
12. [Phase 5: Delivery-Time Memory Improvement](#phase-5-delivery-time-improvement)
13. [Phase 6: Thompson Sampling Self-Tuning](#phase-6-thompson-sampling)
14. [Phase 7: Config Reduction](#phase-7-config-reduction)
15. [Phase 8: Distillation Simplification](#phase-8-distillation-simplification)
16. [Phase 9: Test Overhaul](#phase-9-test-overhaul)
17. [Phase 10: Shared Utilities Extraction](#phase-10-shared-utilities)
18. [Expected Outcomes](#expected-outcomes)
19. [References](#references)

---

## 1. The Problem Statement

Spark Intelligence is a 101,459-line Python system across 507 files that does one thing: **observe an AI agent's actions, filter noise, store learnings, and surface advice.** The system works. But it has grown organically over 30 days and 973 commits without consolidation. The result:

| Metric | Current | Healthy Target |
|--------|---------|----------------|
| Core library lines | 101,459 | ~30,000-35,000 |
| Advisory system | 19,121 lines / 17 files | ~3,000 lines / 3 files |
| Storage paths in ~/.spark/ | 128 unique files | 1 SQLite + ~5 state |
| Config parameters | 576 tuneables | ~60-80 |
| Noise filter implementations | 5 separate systems | 1 unified classifier |
| `_tail_jsonl()` copies | 10 | 1 |
| Pipeline stages (observe to advise) | 12 files, 562 functions | 5-6 files, ~80 functions |
| Test mock density | 70% heavy-mock | 70% behavioral |
| Conversion rate | 200 events -> 25 stored -> 2-3 promoted | Same rate, less machinery |

The system's complexity exceeds the complexity of what it does. This plan addresses that.

---

## 2. Landscape Analysis

### What Others Achieve With Less

| System | Lines | Key Capability | Result |
|--------|-------|---------------|--------|
| **SimpleMem** (2026) | ~3,000 | 3-stage compress-synthesize-retrieve | +26.4% F1 over Mem0, 30x token savings |
| **Reflexion** (NeurIPS 2023) | ~2,500 | Verbal reflect -> store -> improve | 91% pass@1 on HumanEval |
| **smolagents** (HuggingFace) | ~1,000 core | Code-based agent actions | 30% fewer steps than JSON agents |
| **RuVector hooks** | ~1,100 | Q-learning + memory + error patterns + file prediction | Full intelligence in single file |
| **ACT-R decay** | ~20 lines | Importance-weighted forgetting | 40 years of empirical validation |
| **RRF fusion** | ~10 lines | Multi-strategy retrieval fusion | Consistent gains across all benchmarks |

The pattern is clear: the highest-impact techniques are often the simplest. SimpleMem's 3 stages beat Mem0's more complex pipeline. ACT-R's 20-line decay formula outperforms multi-stage importance scoring. RRF's 10-line fusion outperforms single-strategy retrieval.

### SAFLA: The Anti-Lesson

SAFLA (133 stars, 226 Python files) appears similar in ambition but the code reveals:
- No real embeddings (MD5 hashes padded to 768-dim)
- No persistence (all in-memory, dies with process)
- No quality gates, no noise filtering
- ML models are mocked (`train_ml_models()` returns hardcoded accuracy values)
- "Self-awareness" is `psutil.cpu_percent()`

**SAFLA is not the compact system that achieves our goals with fewer files.** It achieves far less. But RuVector (by the same developer) contains genuinely useful design patterns worth adapting.

---

## 3. The Carmack Lens

John Carmack's engineering principles, applied to our system:

### Principle 1: "Abstraction trades real complexity for perceived complexity"

Our 17 advisory modules (advisor.py, advisory_engine.py, advisory_packet_store.py, advisory_synthesizer.py, advisory_gate.py, advisory_memory_fusion.py, advisory_state.py, advisory_preferences.py, prefetch_worker.py, advisory_emitter.py, advisory_packet_feedback.py, advisory_packet_llm_reranker.py, advisory_intent_taxonomy.py, advisory_parser.py, advisory_quarantine.py, advisory_prefetch_planner.py) create perceived modularity while creating real complexity. Nobody can trace data flow across 17 files. The abstraction cost exceeds the benefit.

> *"An exercise I try to do is to 'step a frame', starting at some major point, and step into every function to walk the complete code coverage. This usually gets rather depressing long before you get to the end."*

### Principle 2: "If you're willing to restrict the flexibility of your approach, you can almost always do something better"

576 configurable parameters means 576 dimensions of untested state space. Most have never been changed from defaults. Each one is a conditional branch, a lookup, a potential misconfiguration. The prescription: pick the best value, hardcode it, delete the parameter.

> *"You can prematurely optimize maintainability, flexibility, security, and robustness just like you can performance."*

### Principle 3: "Most bugs are a result of the execution state not being exactly what you think it is"

128 storage files in ~/.spark/ means 128 potential points of state corruption. Our advisory feedback alone uses 6 files. Our outcome tracking uses 7 files. Each file is a state dimension that can drift, corrupt, or go stale independently.

### Principle 4: "The function that is least likely to cause a problem is one that doesn't exist"

10 copies of `_tail_jsonl()`. 5 separate noise filtering systems. 4 separate config loading patterns. These exist because each module was added independently. The cure is deletion, not more abstraction.

### Principle 5: "Make functions pure -- take explicit inputs and return explicit outputs"

Our pipeline is deeply stateful. `bridge_cycle.py` reads from ~15 different global/file-based state sources. Tests need 432 mocks because the code is untestable by construction. Making the core pipeline pure (input events, output insights) would make it both testable and debuggable.

### Principle 6: "The secret to optimization is changing the problem to make it easier to optimize"

Instead of optimizing 576 config parameters with an auto-tuner daemon, we should ask: what if there were only 60 parameters that didn't need auto-tuning? Instead of building a prediction loop to detect "surprise," we should ask: does surprise detection produce enough actionable insights to justify its 757 lines?

---

## 4. Gap Analysis: Where We're Over-Engineered

### Gap 1: The Advisory System (19,121 lines for retrieval + display)

**Current**: 17 files, 19,121 lines. `advisor.py` alone has 139 functions and claims "KISS Principle" on line 17.

**What it actually does**: Retrieve relevant past learnings. Show them before a tool runs.

**What it should be**: A retrieval function, a relevance scorer, and a display formatter. ~3,000 lines across 3 files.

**Root cause**: Each new capability (packets, prefetch, synthesis, LLM reranking, quarantine, Obsidian export) was added as a new file without consolidation.

### Gap 2: Five Separate Noise Filtering Systems

**Current**:
- `lib/primitive_filter.py` (36 lines) -- arrows, tool sequences
- `lib/noise_patterns.py` (100+ lines) -- shared patterns
- `meta_ralph.py` PRIMITIVE_PATTERNS (15 patterns, lines 337-355)
- `cognitive_learner.py` `_is_noise_insight()` (51 patterns, 400+ lines)
- `promoter.py` OPERATIONAL_PATTERNS (33 patterns, lines 63-113)

**What it should be**: One `NoiseClassifier` with a unified pattern set. The 51 patterns in cognitive_learner collapse to ~14 consolidated rules. The 5 systems become 1.

### Gap 3: 128 Storage Paths

**Current**: 69 JSONL files, 129 JSON state files, 5 SQLite databases, 34+ directories. Advisory feedback uses 6 files. Outcomes use 7 files.

**What it should be**: One SQLite database with ~20 tables. One file instead of 128.

### Gap 4: Config Sprawl (576 Parameters, 2,716 Lines of Infrastructure)

**Current**: `tuneables.json` (576 values) + `tuneables_schema.py` (1,101 lines) + `tuneables_reload.py` (369 lines) + `tuneables_drift.py` (226 lines) + `config_authority.py` + `feature_flags.py` + 65 `SPARK_*` environment variables.

**What it should be**: ~60-80 parameters in one JSON file with one loader. No hot-reload infrastructure (restart on config change). No drift detection. No per-key env overrides.

### Gap 5: Utility Duplication

**Current**: `_tail_jsonl()` copied 10 times. `_append_jsonl_capped()` copied 7 times. `_safe_float()` copied 7 times. `_parse_bool()` copied 5 times.

**What it should be**: One `lib/io_utils.py` (~200 lines).

### Gap 6: The Prediction/Validation/Opportunity Loop

**Current**: `prediction_loop.py` (757 lines), `validation_loop.py` (300+ lines), `opportunity_scanner.py` (1,625 lines). These predict tool outcomes, validate if advice was followed, and scan for system improvement opportunities.

**Actual value**: The prediction loop produces few actionable insights (most tool calls are Read/Edit/Bash with predictable outcomes). The validation loop has a 1200s attribution window that's too broad for reliable cause-effect links. The opportunity scanner is self-referential (the system improving itself).

**What it should be**: A lightweight feedback signal: did the user's action succeed after advice was shown? Binary signal, EMA-tracked. ~100 lines.

---

## 5. Gap Analysis: Where We're Under-Delivering

### Gap A: No Memory Compaction

**Current**: Memories accumulate forever in JSONL files. No compression, no merging, no temporal consolidation. Old memories stay at full detail. The cognitive store reaches 143 entries before someone manually cleans it.

**What research shows**: SimpleMem achieves 30x token savings and +26.4% F1 through write-time compression. ACT-R power-law decay (20 lines of Python) naturally handles temporal compression. MaRS framework shows importance-aware policies dramatically outperform temporal-only eviction.

**What we need**: Memories should compress over time. Three related insights about "always validate input" should merge into one. Memories accessed rarely should decay. Memories never retrieved should eventually be evicted.

### Gap B: No Memory Improvement at Delivery

**Current**: Memories are stored as-is and retrieved as-is. A memory stored as "the thing with the auth broke" stays that way even when we have full context about what "the thing" was.

**What research shows**: Anthropic's Contextual Retrieval (Sep 2024) reduces retrieval failures by 67% by prepending 50-100 tokens of context to each chunk at storage time. SimpleMem's atomic fact compression turns vague memories into self-contained facts. The enrichment should happen at write time, not read time.

**What we need**: At storage time, enrich memories with context (tool name, file being edited, session goal). At retrieval time, re-rank based on current context. This is the difference between "something broke" and "Auth middleware in api/auth.py throws 401 when JWT token has expired claims."

### Gap C: No Cross-Domain Transfer

**Current**: Chips are siloed. A game_dev insight about "balance values using playtesting feedback loops" never informs marketing's "test campaign variations with A/B loops." Knowledge stays in the domain where it was learned.

**What research shows**: RuVector's dampened prior transfer (`sqrt()` dampening) enables cross-domain knowledge flow without overconfidence. Thompson Sampling contextual bandits naturally balance exploitation (use what works) with exploration (try cross-domain knowledge).

**What we need**: When a chip learns a high-confidence pattern, seed related chips with a dampened version. Track whether cross-domain transfers improve outcomes.

### Gap D: No Learning Health Metric

**Current**: We have no way to know if the advisory system is converging (getting better over time) or stuck (repeating the same advice without improvement). The auto-tuner adjusts parameters but doesn't measure whether adjustments helped.

**What research shows**: Regret tracking (cumulative regret = sum of best_possible - actual_chosen) is the standard measure. If regret grows sublinearly (rate < 0.7), the system is learning. If linearly (rate ~1.0), it's stuck. This is one counter per source.

### Gap E: Distillation Is Complex But Low-Yield

**Current**: 25-30 files touch the distillation pipeline. The conversion rate is 200 raw events -> 25 stored insights -> 2-3 promoted. That's a 1% raw-to-promoted rate through a 21,676-line pipeline.

**The minimum viable pipeline** needs 5 files: observe, filter, score, store, promote. The 20+ additional files handle edge cases, self-optimization, and meta-improvement that produce marginal gains at significant complexity cost.

---

## 6. Proven Techniques From Research

These are the specific techniques this plan uses, each backed by papers or production implementations:

### 6.1 ACT-R Base-Level Activation (Memory Decay)

From 40+ years of cognitive science research. The formula:

```python
B_i = ln(sum(t_j ** (-d) for t_j in access_times))
# d = 0.5 (decay parameter)
# t_j = time since j-th access (in hours)
```

This naturally handles both recency and frequency: a memory accessed 10 times yesterday has higher activation than one accessed once today. Power-law decay means old memories decay more slowly than exponential -- important memories survive longer.

**Implementation**: ~20 lines of Python. Replaces multi-stage importance scoring.

*Source: Anderson & Lebiere, "The Atomic Components of Thought" (1998); Springer 2023 review*

### 6.2 Write-Time Atomic Fact Compression (SimpleMem)

Three-stage pipeline:
1. **Semantic Structured Compression**: Convert observations into self-contained atomic facts via coreference resolution and temporal normalization
2. **Online Semantic Synthesis**: Merge related fragments during write ("User wants coffee" + "prefers oat milk" + "likes it hot" → "User prefers hot coffee with oat milk")
3. **Intent-Aware Retrieval Planning**: Decompose query into optimized sub-queries for each index layer

**Result**: +26.4% F1 over baselines, 30x token savings.

*Source: arXiv:2601.02553 (Jan 2026)*

### 6.3 SQLite FTS5 + sqlite-vec Hybrid Search

SQLite FTS5 implements BM25 natively (k1=1.2, b=0.75). Combined with sqlite-vec for vector search and Reciprocal Rank Fusion:

```sql
WITH fts AS (
  SELECT rowid, rank FROM memories_fts WHERE memories_fts MATCH ?
),
vec AS (
  SELECT rowid, distance FROM memories_vec WHERE embedding MATCH ?
)
SELECT *, (1.0/(60+fts.rank))*0.5 + (1.0/(60+vec.distance))*0.5 as score
FROM fts JOIN vec USING(rowid)
ORDER BY score DESC LIMIT 10
```

Handles ~50K documents in under 1 second on a laptop. No external services. Single file.

*Source: Alex Garcia, "Hybrid full-text search and vector search with SQLite" (Oct 2024)*

### 6.4 Thompson Sampling for Source Selection

Replace static boost multipliers with Beta distributions per source per context:

```python
class SourceSelector:
    def __init__(self):
        self.priors = defaultdict(lambda: {"alpha": 1.0, "beta": 1.0})

    def select(self, sources, context_key):
        scores = {}
        for source in sources:
            p = self.priors[f"{source}:{context_key}"]
            scores[source] = np.random.beta(p["alpha"], p["beta"])
        return max(scores, key=scores.get)

    def update(self, source, context_key, success: bool):
        p = self.priors[f"{source}:{context_key}"]
        if success:
            p["alpha"] += 1.0
        else:
            p["beta"] += 1.0
```

Self-tuning, context-aware, needs no auto-tuner daemon. Exploration happens naturally through Beta variance.

*Source: RuVector domain expansion (crates/ruvector-domain-expansion/src/transfer.rs)*

### 6.5 Dampened Prior Transfer (Cross-Domain)

When transferring knowledge between domains, apply sqrt dampening:

```python
dampened_alpha = 1.0 + math.sqrt(source_alpha - 1.0)
dampened_beta = 1.0 + math.sqrt(source_beta - 1.0)
```

If source has Beta(100, 10) (very confident), target gets Beta(~11, ~4) -- informative but not overconfident. Verify transfers don't regress the source domain.

*Source: RuVector domain expansion*

### 6.6 EMA for Quality Tracking

```python
score = alpha * observation + (1 - alpha) * score  # alpha = 0.1
```

Competitive with state-of-the-art methods. O(1) per update, O(1) memory. Naturally handles noisy feedback.

*Source: arXiv:2411.18704 (Nov 2024) -- "EMA is competitive with state-of-the-art methods despite its striking simplicity"*

### 6.7 ReasoningBank Eviction Formula

```python
eviction_score = quality * math.log(usage_count + 1)
```

Rewards both quality AND actual usage. Insights that score high but never get retrieved eventually die. Insights that get used frequently survive even at moderate quality. One line of code.

*Source: RuVector SONA (crates/ruvector-dag/src/sona/reasoning_bank.rs)*

### 6.8 Mem0 Four-Operation Update Protocol

For each new memory candidate, retrieve top-10 similar existing memories. Classify relationship:
- **ADD**: No semantic match. Insert as new.
- **UPDATE**: Augments existing memory. Merge and store the richer version.
- **DELETE**: Contradicts existing memory. Remove the outdated one.
- **NOOP**: Duplicate. Skip.

This prevents memory bloat at the source, rather than cleaning up after the fact.

*Source: arXiv:2504.19413 (Apr 2025) -- Mem0: Building Production-Ready AI Agent Memory*

### 6.9 Anthropic Contextual Retrieval

At storage time, prepend 50-100 tokens of context to each memory chunk before embedding:

> *"Please give a short succinct context to situate this chunk within the overall document."*

**Result**: 67% reduction in retrieval failures (with BM25 + reranking).

*Source: Anthropic blog, "Introducing Contextual Retrieval" (Sep 2024)*

### 6.10 Regret Tracking for Learning Health

```python
cumulative_regret += best_possible_reward - actual_reward
regret_growth_rate = math.log(cumulative_regret + 1) / math.log(num_observations + 1)
# < 0.7 = learning (sublinear growth)
# ~ 1.0 = stuck (linear growth)
# > 1.0 = getting worse (superlinear growth)
```

One counter per source. Instant diagnosis of whether the system is improving.

*Source: RuVector meta-learning engine (crates/ruvector-domain-expansion/src/meta_learning.rs)*

---

## 7. The Implementation Plan

### Phasing Strategy

The plan is structured so that **each phase is independently valuable** -- you can stop after any phase and have a better system than before. Later phases build on earlier ones but don't require them.

**Dependency graph**:
```
Phase 1 (Storage) ─────────────┐
Phase 2 (Noise Classifier) ────┤──> Phase 3 (Advisory Collapse)
Phase 10 (Shared Utils) ───────┘
Phase 4 (Memory Compaction) ──────> Phase 5 (Delivery Improvement)
Phase 6 (Thompson Sampling) ──────> Phase 7 (Config Reduction)
Phase 8 (Distillation) ──────────> Phase 9 (Test Overhaul)
```

Phases 1-3 are structural cleanup (reduce lines, consolidate storage, eliminate duplication).
Phases 4-6 are capability upgrades (compaction, delivery improvement, self-tuning).
Phases 7-10 are quality of life (config simplification, simpler distillation, better tests, shared utils).

**Estimated total effort**: 8-12 focused sessions.

---

## Phase 1: Storage Consolidation

**Goal**: 128 file paths -> 1 SQLite database + FTS5 + sqlite-vec

### What Changes

Replace all JSONL append-logs and JSON state files with a single `spark.db`:

```sql
-- Core tables
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    tool_name TEXT,
    session_id TEXT,
    content TEXT NOT NULL,
    importance REAL DEFAULT 0.0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE insights (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,  -- reasoning, wisdom, meta_learning, etc.
    content TEXT NOT NULL,
    reliability REAL DEFAULT 0.5,
    validations INTEGER DEFAULT 0,
    usage_count INTEGER DEFAULT 0,
    last_accessed TEXT,
    activation REAL DEFAULT 1.0,  -- ACT-R base-level activation
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE advisory_decisions (
    id INTEGER PRIMARY KEY,
    tool_name TEXT NOT NULL,
    context_key TEXT,
    items_shown TEXT,  -- JSON array of insight IDs
    outcome TEXT,      -- helpful/ignored/harmful
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE feedback (
    id INTEGER PRIMARY KEY,
    insight_id INTEGER REFERENCES insights(id),
    signal TEXT NOT NULL,  -- positive/negative/neutral
    source TEXT,           -- implicit/explicit/outcome
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- FTS5 for BM25 text search
CREATE VIRTUAL TABLE insights_fts USING fts5(content, category, key);

-- Triggers to keep FTS in sync
CREATE TRIGGER insights_ai AFTER INSERT ON insights BEGIN
    INSERT INTO insights_fts(rowid, content, category, key)
    VALUES (new.id, new.content, new.category, new.key);
END;
```

### What Gets Deleted

- All `_tail_jsonl()` usage (10 copies)
- All `_append_jsonl_capped()` usage (7 copies)
- All JSONL rotation/capping logic
- `queue.py` JSONL file management (becomes `INSERT INTO events`)
- Individual JSON state files (become rows in `state` table)
- 5 separate SQLite databases (become 1)

### Migration Path

1. Create `lib/spark_db.py` (~300 lines) with connection management, migration system, and CRUD operations
2. Add a `migrate_from_jsonl()` function that reads existing JSONL/JSON files and imports into SQLite
3. Update `observe.py` to write to SQLite instead of JSONL
4. Update `bridge_cycle.py` to read from SQLite
5. Update `cognitive_learner.py` to use SQLite instead of `cognitive_insights.json`
6. Run migration, verify data integrity, delete old JSONL code

### Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| Storage files | 128 | 1 |
| `_tail_jsonl()` copies | 10 | 0 |
| JSONL rotation code | ~500 lines across 10 files | 0 |
| Query capability | Sequential file scan | SQL indexes + FTS5 BM25 |
| Deduplication | Manual per-file | `UNIQUE` constraints + triggers |

---

## Phase 2: Unified Noise Classifier

**Goal**: 5 noise filtering systems -> 1 data-driven classifier

### Current State (5 Systems)

1. `primitive_filter.py` -- 15 patterns
2. `noise_patterns.py` -- shared patterns module
3. `meta_ralph.py` PRIMITIVE_PATTERNS -- 15 patterns (lines 337-355)
4. `cognitive_learner.py` `_is_noise_insight()` -- 51 patterns (lines 1075-1485)
5. `promoter.py` OPERATIONAL_PATTERNS -- 33 patterns (lines 63-113)

### Consolidated Design

One `lib/noise_classifier.py` (~200 lines) with a data-driven pattern table:

```python
NOISE_RULES = [
    # (name, compiled_regex, description)
    ("tool_sequence", re.compile(r"(?:→|->|=>).*(?:→|->|=>)", re.I), "Tool chain arrows"),
    ("tool_telemetry", re.compile(r"\b(?:Read|Edit|Bash|Glob|Grep)\b.*\b(?:Read|Edit|Bash|Glob|Grep)\b"), "Tool-heavy text"),
    ("chip_diagnostic", re.compile(r"(?:chip[_:]|triggered.by|diagnostic|telemetry)", re.I), "Chip/diagnostic output"),
    ("conversational", re.compile(r"^(?:let'?s|do you think|i think we|can we|should we)", re.I), "Conversational fragment"),
    ("code_artifact", re.compile(r"^(?:\s{4,}|\t)(?:def |class |import |from |#)", re.M), "Code dump"),
    ("doc_artifact", re.compile(r"^#{1,3}\s|^\|.*\|$|^```", re.M), "Markdown artifact"),
    ("operational", re.compile(r"\b(?:cycle|batch|queue|pipeline|process(?:ed|ing))\b.*\d+", re.I), "Operational metric"),
    ("timing_metric", re.compile(r"\d+(?:\.\d+)?(?:ms|s|sec|min)\b", re.I), "Timing data"),
    ("too_short", re.compile(r"^.{0,25}$"), "Too short to be actionable"),
    ("garbled", re.compile(r"[^\x20-\x7E]{3,}|(?:\?\?){2,}", re.I), "Garbled/corrupted text"),
    ("vague_start", re.compile(r"^(?:might be|probably|seems like|appears to)", re.I), "Hedging without substance"),
    ("tautology", None, "Same concept in both halves"),  # custom function
    ("platitude", re.compile(r"\b(?:best practice|industry standard|always use|never do)\b", re.I), "Generic platitude"),
    ("circular", None, "Reasoning references itself"),  # custom function
]

def classify(text: str) -> tuple[bool, str | None]:
    """Returns (is_noise, matched_rule_name)."""
    for name, pattern, _ in NOISE_RULES:
        if pattern and pattern.search(text):
            return True, name
    if _is_tautology(text):
        return True, "tautology"
    if _is_circular(text):
        return True, "circular"
    return False, None
```

### What Gets Deleted

- `lib/primitive_filter.py` (entire file)
- `lib/noise_patterns.py` (entire file)
- `meta_ralph.py` lines 337-355 (replaced with `noise_classifier.classify()` call)
- `cognitive_learner.py` lines 1075-1485 (~400 lines, replaced with single call)
- `promoter.py` lines 63-113 (replaced with single call)

### Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| Noise pattern implementations | 5 files, ~114 individual patterns | 1 file, 14 consolidated rules |
| Lines of noise filtering code | ~900 across 5 files | ~200 in 1 file |
| Pattern overlap/duplication | High | Zero |
| Maintainability | Add pattern in 5 places | Add one row to table |

---

## Phase 3: Advisory Collapse

**Goal**: 17 advisory files (19,121 lines) -> 3 files (~3,000 lines)

### Target Architecture

**`lib/advisory_store.py`** (~1,200 lines): Storage + retrieval + feedback
- Replaces: advisory_packet_store.py, advisory_quarantine.py, advisory_packet_feedback.py, advisory_parser.py, advisory_intent_taxonomy.py, advisory_preferences.py, advisory_memory_fusion.py, advisory_state.py
- Core operations: store advisory item, retrieve by context, record feedback, track effectiveness
- Uses SQLite (from Phase 1) instead of JSONL files
- Intent taxonomy becomes a dict constant (~30 lines, not a file)

**`lib/advisory_engine.py`** (~1,200 lines): Orchestration + synthesis + emission
- Replaces: advisor.py (6,029 lines!), advisory_engine.py (current), advisory_synthesizer.py, advisory_emitter.py, prefetch_worker.py, advisory_prefetch_planner.py, advisory_packet_llm_reranker.py
- Core flow: receive tool context -> query store -> rank results -> format output -> emit
- No prefetch (eliminate entire subsystem -- the 4ms query time doesn't justify prefetch complexity)
- Template-based synthesis for 80% of cases, optional LLM for complex synthesis

**`lib/advisory_gate.py`** (~600 lines): Gating + cooldowns + fatigue
- Keep largely as-is (it's the cleanest of the 17 files)
- Simplify tool-family cooldowns (one function, not per-tool config)
- Merge source-aware TTL into the gate logic

### Migration Strategy

1. Create new `advisory_store.py` backed by SQLite
2. Migrate packet data from JSONL to SQLite tables
3. Create new `advisory_engine.py` with simplified retrieval pipeline
4. Wire `bridge_cycle.py` to use new modules
5. Run side-by-side comparison (old vs new) on 100 advisory queries
6. Delete old files when new modules match or exceed quality

### What Gets Deleted

All 17 current advisory files are replaced by 3 new ones. The single largest deletion: `advisor.py` (6,029 lines, 139 functions).

---

## Phase 4: Memory Compaction Engine

**Goal**: Memories compress and consolidate over time instead of accumulating forever

### Design

New `lib/memory_compactor.py` (~300 lines) implementing three strategies:

#### Strategy 1: ACT-R Activation Decay

Every memory gets an activation score that decays with time and boosts with access:

```python
def activation(access_times: list[float], now: float, decay: float = 0.5) -> float:
    """ACT-R base-level activation. access_times in hours-since-epoch."""
    if not access_times:
        return -float('inf')
    return math.log(sum((now - t) ** (-decay) for t in access_times if now > t) + 1e-10)
```

Memories with activation below a threshold (e.g., -2.0) are candidates for compaction or eviction.

#### Strategy 2: Semantic Merge (SimpleMem-inspired)

When storing a new memory, check for semantically similar existing memories (using FTS5 or embedding similarity). Apply Mem0's four-operation protocol:

- **ADD**: No match above threshold. Insert as new.
- **UPDATE**: Similar memory exists. Merge: keep the more specific/actionable version, incorporate any unique details from the other.
- **DELETE**: New memory contradicts existing. Replace with the newer, more specific one.
- **NOOP**: Duplicate. Skip storage, boost access count of existing.

#### Strategy 3: Periodic Consolidation

Run every N cycles (e.g., every 10 bridge cycles):

1. Find all memories in same category with activation < threshold
2. Group by semantic similarity (3-gram Jaccard > 0.5)
3. For each group of 2+: generate a merged summary that preserves all key details
4. Replace group with single consolidated memory, carrying forward highest reliability score and combined validation count

### Eviction Formula

Adapt RuVector's ReasoningBank eviction:

```python
eviction_score = reliability * math.log(usage_count + 1) * activation
# Lowest eviction_score gets evicted when store exceeds max capacity
```

### Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| Cognitive store growth | Unbounded (manually cleaned at 143) | Self-limiting (target: 60-80 active) |
| Memory quality over time | Degrades (noise accumulates) | Improves (consolidation refines) |
| Retrieval precision | 22.7% | Target: 35%+ (fewer, better memories) |
| Duplicate memories | 26.7% (benchmark) | Target: <5% |

---

## Phase 5: Delivery-Time Memory Improvement

**Goal**: Memories are enriched at storage and sharpened at retrieval

### Write-Time Enrichment

When storing a memory, prepend contextual metadata (Anthropic's Contextual Retrieval pattern):

```python
def enrich_at_storage(raw_content: str, context: dict) -> str:
    """Add context that makes the memory self-contained."""
    prefix_parts = []
    if context.get("tool_name"):
        prefix_parts.append(f"[{context['tool_name']}]")
    if context.get("file_path"):
        prefix_parts.append(f"in {context['file_path']}")
    if context.get("session_goal"):
        prefix_parts.append(f"while {context['session_goal']}")

    prefix = " ".join(prefix_parts)
    return f"{prefix}: {raw_content}" if prefix else raw_content
```

This turns "the auth thing broke" into "[Edit] in api/auth.py while fixing login flow: the auth thing broke" -- immediately more useful at retrieval time.

### Retrieval-Time Sharpening

When retrieving memories for advisory, re-rank based on current context overlap:

```python
def sharpen_for_context(memories: list, current_tool: str, current_file: str) -> list:
    """Boost memories that match current context."""
    for mem in memories:
        boost = 0.0
        if current_tool and current_tool.lower() in mem.content.lower():
            boost += 0.3
        if current_file and any(part in mem.content for part in current_file.split("/")):
            boost += 0.5
        mem.retrieval_score = mem.base_score + boost
    return sorted(memories, key=lambda m: m.retrieval_score, reverse=True)
```

### Cross-Reference Linking (A-MEM inspired)

When storing a new memory, find the top-3 related existing memories and store bidirectional links:

```sql
CREATE TABLE memory_links (
    source_id INTEGER REFERENCES insights(id),
    target_id INTEGER REFERENCES insights(id),
    link_type TEXT,  -- semantic, temporal, causal
    strength REAL DEFAULT 0.5,
    PRIMARY KEY (source_id, target_id)
);
```

At retrieval time, follow links one hop to surface related memories that might not match the query directly but provide valuable context.

### Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| Memory self-containedness | Low (vague references) | High (context prepended) |
| Retrieval relevance | 67.1% advisory retrieval rate | Target: 80%+ |
| Cross-memory discovery | None | 1-hop graph traversal |

---

## Phase 6: Thompson Sampling Self-Tuning

**Goal**: Replace static boost multipliers and auto-tuner with self-tuning Beta priors

### What It Replaces

Current system: static source boosts in tuneables.json (`cognitive: 1.65`, `micro: 0.5`, etc.) adjusted by an auto-tuner daemon (34 config values, 12-hour cycles, 4 changes per cycle).

New system: each advisory source has a Beta(alpha, beta) distribution per context bucket. The system self-tunes through usage without an external daemon.

### Implementation

New `lib/source_selector.py` (~150 lines):

```python
class SourceSelector:
    """Thompson Sampling for advisory source selection."""

    def __init__(self, db: SparkDB):
        self.db = db  # persists priors to SQLite

    def rank_sources(self, sources: list[str], context: str) -> list[tuple[str, float]]:
        """Rank sources by Thompson-sampled scores."""
        bucket = self._context_bucket(context)
        scored = []
        for source in sources:
            prior = self._get_prior(source, bucket)
            sample = np.random.beta(prior["alpha"], prior["beta"])
            scored.append((source, sample))
        return sorted(scored, key=lambda x: x[1], reverse=True)

    def record_outcome(self, source: str, context: str, helpful: bool):
        """Update Beta prior based on outcome."""
        bucket = self._context_bucket(context)
        prior = self._get_prior(source, bucket)
        if helpful:
            prior["alpha"] += 1.0
        else:
            prior["beta"] += 1.0
        # Apply DecayingBeta (prevent calcification)
        decay = 0.995
        prior["alpha"] = 1.0 + (prior["alpha"] - 1.0) * decay
        prior["beta"] = 1.0 + (prior["beta"] - 1.0) * decay
        self._save_prior(source, bucket, prior)

    def transfer_prior(self, from_source: str, to_source: str, context: str):
        """Dampened prior transfer between sources/domains."""
        bucket = self._context_bucket(context)
        source_prior = self._get_prior(from_source, bucket)
        dampened = {
            "alpha": 1.0 + math.sqrt(max(0, source_prior["alpha"] - 1.0)),
            "beta": 1.0 + math.sqrt(max(0, source_prior["beta"] - 1.0)),
        }
        self._save_prior(to_source, bucket, dampened)

    def regret(self, source: str) -> float:
        """Regret growth rate. < 0.7 = learning, ~1.0 = stuck."""
        history = self._get_outcome_history(source)
        if len(history) < 10:
            return 0.0  # not enough data
        cumulative = 0.0
        best_rate = max(sum(h) / len(h) for h in [history])  # best arm's mean
        for i, outcome in enumerate(history):
            cumulative += best_rate - outcome
        if cumulative <= 0:
            return 0.0
        return math.log(cumulative + 1) / math.log(len(history) + 1)
```

### What Gets Deleted

- `lib/auto_tuner.py` (entire file -- its 34 config parameters become unnecessary)
- `tuneables.json` auto_tuner section (34 values)
- All per-source boost multipliers in tuneables
- All per-source effectiveness tracking in advisory_engine (replaced by Beta priors)
- The executive loop's config evolution for source boosts (replaced by self-tuning)

### Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| Source selection mechanism | Static boosts + auto-tuner daemon | Self-tuning Beta priors |
| Config values for source tuning | ~50 | 3 (decay rate, initial alpha, initial beta) |
| Adaptation speed | 12-hour auto-tuner cycles | Every advisory outcome |
| Learning health visibility | None | Regret metric per source |
| Cross-domain transfer | None | Dampened prior transfer |

---

## Phase 7: Config Reduction

**Goal**: 576 tuneable parameters -> ~60-80

### Methodology

For each of the 576 parameters:
1. Has it ever been changed from its default? If no -> **hardcode and delete**
2. Is it used by a deleted subsystem (auto-tuner, prefetch, etc.)? -> **delete**
3. Is it a per-tool/per-source variant of a general parameter? -> **collapse to one parameter**
4. Does it meaningfully affect behavior? -> **keep**

### Predicted Deletions by Section

| Tuneable Section | Current Values | Expected After | Reason |
|------------------|---------------|---------------|--------|
| auto_tuner | 34 | 0 | Replaced by Thompson Sampling |
| llm_areas | 121 | ~20 | Most are disabled, hardcode the 20 that matter |
| advisory_gate | 32 | ~10 | Collapse per-tool/per-source variants |
| retrieval | 56 | ~15 | Simplify to one profile (not three) |
| advisor | 48 | ~10 | Most are edge-case handling |
| meta_ralph | 28 | ~10 | Hardcode noise thresholds |
| eidos | 36 | ~10 | Simplify step/episode management |
| semantic | 18 | 5 | Core similarity thresholds only |
| promotion | 14 | 5 | Reliability/validation thresholds |
| values | 12 | 5 | Core importance thresholds |
| Other sections | ~177 | ~0-10 | Most support deleted subsystems |

### What Gets Deleted

- `lib/tuneables_reload.py` (369 lines) -- no hot-reload, restart on config change
- `lib/tuneables_drift.py` (226 lines) -- no drift detection needed with fewer params
- Most of `lib/tuneables_schema.py` (1,101 lines -> ~300 lines)
- 65 `SPARK_*` environment variables (reduce to ~10 essential ones)

### Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| Tuneable parameters | 576 | ~60-80 |
| Config infrastructure lines | 2,716 | ~500 |
| Config files/systems | 6 | 2 (one JSON + one loader) |
| Untested state space | 576-dimensional | 60-dimensional |

---

## Phase 8: Distillation Simplification

**Goal**: 25-30 pipeline files -> 5-6 core files with same or better conversion rate

### Current Pipeline (12+ files, 21,676 lines)

```
observe.py -> queue.py -> pipeline.py -> bridge_cycle.py -> memory_capture.py
-> cognitive_learner.py -> meta_ralph.py -> advisor.py -> advisory_engine.py
-> advisory_gate.py -> advisory_synthesizer.py -> advisory_emitter.py
```

Plus: prediction_loop.py, validation_loop.py, opportunity_scanner.py, pattern_detection/ (10 files), distillation_transformer.py, distillation_refiner.py, elevation.py

### Simplified Pipeline (6 files, ~5,000 lines)

```
observe.py -> spark_db.py -> noise_classifier.py -> scorer.py
-> cognitive_store.py -> advisory_engine.py
```

1. **`hooks/observe.py`** (keep, ~800 lines): Capture events, write to SQLite
2. **`lib/spark_db.py`** (new, ~300 lines): SQLite connection + CRUD + FTS5
3. **`lib/noise_classifier.py`** (new, ~200 lines): Unified noise filter (Phase 2)
4. **`lib/scorer.py`** (new, ~200 lines): Simplified quality scoring
5. **`lib/cognitive_store.py`** (refactored, ~500 lines): Insight management + compaction
6. **`lib/advisory_engine.py`** (refactored, ~1,200 lines): Retrieval + ranking + emission

### The Simplified Scorer

Replace Meta-Ralph's 290-line `_score_learning()` with a simpler pre-filter + signal count:

```python
def score(text: str) -> tuple[float, list[str]]:
    """Score a learning candidate. Returns (score 0-1, quality signals found)."""
    # Pre-filter: noise classifier catches garbage
    is_noise, rule = noise_classifier.classify(text)
    if is_noise:
        return 0.0, [f"noise:{rule}"]

    # Count positive quality signals
    signals = []
    text_lower = text.lower()

    # Reasoning: explains WHY
    if any(w in text_lower for w in ["because", "since", "due to", "leads to", "causes"]):
        signals.append("reasoning")

    # Specificity: contains concrete details
    if re.search(r'\d+(?:\.\d+)?(?:%|ms|s|x|px|mb|kb|loc)', text_lower):
        signals.append("quantitative")
    if re.search(r'[A-Z][a-z]+(?:Error|Exception|Warning|Module|Service)', text):
        signals.append("specific_entity")

    # Actionability: prescribes an action
    if any(w in text_lower for w in ["use", "avoid", "prefer", "always", "never", "when", "instead"]):
        signals.append("actionable")

    # Context: situation-specific
    if any(w in text_lower for w in ["in python", "for react", "when editing", "during deploy"]):
        signals.append("contextual")

    # Decision: records a choice
    if any(w in text_lower for w in ["decided", "chose", "switched to", "migrated from"]):
        signals.append("decision")

    score = min(1.0, len(signals) / 3.0)  # 3+ signals = max score
    return score, signals
```

This is ~40 lines vs. 290 lines. The noise classifier (Phase 2) handles garbage rejection. The scorer only needs to detect quality signals. 3+ signals = pass. Simple, auditable, no threshold tuning needed.

### What Gets Deleted/Merged

| Current | Lines | Fate |
|---------|-------|------|
| bridge_cycle.py orchestration | 1,530 | Simplify to ~300 lines (remove 15 sub-steps, keep 5) |
| meta_ralph.py | 2,766 | Replace with scorer.py (~200 lines) + noise_classifier.py (~200 lines) |
| prediction_loop.py | 757 | Delete (low-value output) |
| validation_loop.py | 300 | Replace with EMA feedback tracker (~50 lines) |
| opportunity_scanner.py | 1,625 | Delete (self-referential improvement) |
| pattern_detection/ (10 files) | ~4,100 | Consolidate to 1 file (~400 lines) |
| distillation_transformer.py | ~500 | Merge into cognitive_store.py |
| distillation_refiner.py | ~400 | Delete (16 disabled LLM calls) |
| elevation.py | ~300 | Keep top 4 transforms, inline into scorer.py |
| primitive_filter.py | 36 | Delete (merged into noise_classifier) |
| noise_patterns.py | 100 | Delete (merged into noise_classifier) |

---

## Phase 9: Test Overhaul

**Goal**: Replace mock-heavy unit tests with behavioral integration tests

### Problem

Current test suite: 159 files, 27,896 lines, 70% heavy-mock. `test_advisor.py` has 432 mock references across 96 tests. `test_advisor_mind_gate.py` has 120 mocks across 4 tests (30 per test). These tests verify wiring, not behavior.

### Carmack's Testing Principle

> *"Pure functions are trivial to test; the tests look like something right out of a textbook, where you build some inputs and look at the output."*

The solution is not better tests -- it's **more testable code**. The pipeline functions from Phase 8 should be pure: input events, output insights. No global state reads. No side effects. Then testing is trivial.

### New Test Architecture

**`tests/test_pipeline_behavioral.py`** (~500 lines): The core test file.

```python
def test_good_insight_survives_pipeline():
    """A genuine learning passes all stages and gets stored."""
    event = make_event(
        content="Use connection pooling in PostgreSQL because individual "
                "connections cost 1.3MB each and pool reuse cuts p95 from 200ms to 40ms",
        tool_name="Edit",
        file_path="db/connection.py"
    )
    result = run_pipeline(event)
    assert result.stored is True
    assert "reasoning" in result.signals
    assert "quantitative" in result.signals

def test_garbage_gets_filtered():
    """Tool sequences, timing metrics, and tautologies get rejected."""
    garbage_events = [
        make_event("Read -> Edit -> Bash -> Read"),
        make_event("Processing took 4.2ms for 3 items"),
        make_event("The system works because the system is working"),
        make_event("Best practices are important for quality"),
    ]
    for event in garbage_events:
        result = run_pipeline(event)
        assert result.stored is False, f"Should have filtered: {event.content[:50]}"

def test_duplicate_gets_merged():
    """Semantically similar memories merge instead of duplicating."""
    event1 = make_event("Always validate user input in API endpoints because XSS")
    event2 = make_event("Validate all user input at API boundaries to prevent XSS")

    run_pipeline(event1)
    result = run_pipeline(event2)

    assert result.action == "UPDATE"  # Merged, not added
    assert count_insights() == 1  # Only one stored

def test_advice_is_relevant_to_tool():
    """Advisory retrieves memories relevant to current tool + file."""
    store_insight("Use parameterized queries in SQL to prevent injection", tool="Edit", file="db/")
    store_insight("React useState batches updates in event handlers", tool="Edit", file="components/")

    advice = get_advisory(tool_name="Edit", file_path="db/queries.py")
    assert any("SQL" in a.content for a in advice)
    assert not any("React" in a.content for a in advice)

def test_retrieval_latency_under_budget():
    """Advisory retrieval completes within 50ms with 1000 stored insights."""
    for i in range(1000):
        store_insight(f"Insight {i} about topic {i % 20} with detail {i * 7}")

    start = time.monotonic()
    advice = get_advisory(tool_name="Edit", file_path="lib/foo.py")
    elapsed_ms = (time.monotonic() - start) * 1000

    assert elapsed_ms < 50, f"Advisory took {elapsed_ms:.1f}ms (budget: 50ms)"
```

### What Gets Deleted

All heavily-mocked test files that test internal wiring rather than behavior. The 432-mock `test_advisor.py` is replaced by 5-10 behavioral tests that run the actual pipeline.

---

## Phase 10: Shared Utilities Extraction

**Goal**: Eliminate all utility function duplication

### New `lib/io_utils.py` (~200 lines)

```python
"""Shared I/O utilities. Single source of truth."""

def safe_float(val, default=0.0) -> float: ...
def safe_int(val, default=0) -> int: ...
def parse_bool(val, default=False) -> bool: ...
def tail_jsonl(path, n=50, parse=True) -> list: ...
def append_jsonl_capped(path, record, max_lines=500): ...
def load_json_safe(path, default=None): ...
def save_json_atomic(path, data): ...
def chips_enabled() -> bool: ...
def premium_tools_enabled() -> bool: ...
```

### What Gets Deleted

- 10 copies of `_tail_jsonl()` across 10 files
- 7 copies of `_append_jsonl_capped()` across 7 files
- 7 copies of `_safe_float()` across 7 files
- 5 copies of `_parse_bool()` across 5 files
- 4 copies of `_premium_tools_enabled()` across 4 files
- 3 copies of `_chips_enabled()` across 3 files

**Total: ~42 function copies -> 10 canonical implementations.**

---

## Expected Outcomes

### Line Count Projection

| Component | Current Lines | After V2 | Reduction |
|-----------|-------------|----------|-----------|
| Advisory system | 19,121 | ~3,000 | -84% |
| Meta-Ralph + noise filters | 3,700 | ~400 | -89% |
| Bridge cycle orchestration | 1,530 | ~300 | -80% |
| Config infrastructure | 2,716 | ~500 | -82% |
| Prediction/validation/opportunity | 2,682 | ~100 | -96% |
| Pattern detection | 4,100 | ~400 | -90% |
| Utility duplication | ~3,000 (42 copies) | ~200 (10 originals) | -93% |
| Storage management | ~2,000 | ~300 | -85% |
| **Estimated core lib/ total** | **~101,000** | **~30,000-35,000** | **-65%** |

### Quality Projections

| Metric | Current | Target | Mechanism |
|--------|---------|--------|-----------|
| Retrieval precision (P@5) | 22.7% | 35%+ | Fewer/better memories + RRF + context enrichment |
| Advisory retrieval rate | 67.1% | 80%+ | SQLite FTS5 + delivery-time sharpening |
| Garbage leakage | 6.5% | <3% | Unified noise classifier + Mem0 dedup |
| Duplicate memories | 26.7% | <5% | Write-time Mem0 protocol + Bloom filter |
| Config parameters | 576 | ~70 | Hardcode defaults, delete unused |
| Storage files | 128 | 1 | SQLite consolidation |
| Pipeline traceability | 12+ files to trace | 6 files, linear flow | Carmack "step a frame" |

### What Stays the Same

- The hook-based observation model (observe.py)
- The core quality insight: most raw events are noise, filter aggressively
- The promotion model (high-reliability insights -> CLAUDE.md)
- The chip system (domain-specific learning modules)
- The EIDOS episodic model (prediction -> outcome -> evaluation)
- The observatory (Obsidian visualization)

---

## References

### Research Papers

| Paper | Year | Key Technique |
|-------|------|--------------|
| SimpleMem (arXiv:2601.02553) | 2026 | Write-time atomic compression, 30x token savings |
| Mem0 (arXiv:2504.19413) | 2025 | 4-operation update protocol (ADD/UPDATE/DELETE/NOOP) |
| Hindsight (arXiv:2512.12818) | 2025 | 4-strategy retrieval fusion, epistemic separation |
| MaRS (arXiv:2512.12856) | 2025 | 6 forgetting policies, hybrid importance-aware decay |
| A-MEM (arXiv:2502.12110) | 2025 | Zettelkasten memory linking |
| AgeMem (arXiv:2601.01885) | 2026 | RL-trained memory management outperforms heuristics |
| MemGPT/Letta (arXiv:2310.08560) | 2023 | OS-inspired memory hierarchy |
| Reflexion (arXiv:2303.11366) | 2023 | Verbal reinforcement learning |
| EMA in Deep Learning (arXiv:2411.18704) | 2024 | EMA competitive with SOTA, O(1) memory |
| Memory in AI Agents Survey (arXiv:2512.13564) | 2025 | Comprehensive taxonomy and benchmarks |

### Industry Sources

| Source | Key Insight |
|--------|------------|
| Anthropic "Contextual Retrieval" (Sep 2024) | 67% retrieval failure reduction from context prepending |
| Anthropic "Building Effective Agents" (Dec 2024) | "Most successful implementations used simple, composable patterns" |
| Alex Garcia "SQLite Hybrid Search" (Oct 2024) | FTS5 + sqlite-vec + RRF in ~30 lines of SQL |
| HuggingFace smolagents (Dec 2024) | ~1K lines core, 30% fewer steps |
| Glicko-2 Rating System | Self-correcting quality scores, no threshold tuning |
| LMSYS Chatbot Arena | Bradley-Terry pairwise ranking at scale |

### Carmack Sources

| Source | Key Quote |
|--------|----------|
| 2007 Email on Inlined Code | "The function that is least likely to cause a problem is one that doesn't exist" |
| Lex Fridman Podcast #309 | "AGI will be tens of thousands of lines, not millions" |
| X/Twitter May 2025 | "Rebuild microservice-based products into monolithic native codebases" |
| X/Twitter May 2025 | "AI can help make codebases more beautiful... a tireless assistant pouring over everything" |
| Upper Bound 2025 | "LLMs can know everything without learning anything" |
| Various | "If you're willing to restrict flexibility, you can almost always do something better" |
| Various | "You can prematurely optimize maintainability just like you can performance" |

### Codebase Sources

| Project | Key Pattern Borrowed |
|---------|---------------------|
| RuVector SONA (crates/ruvector-dag/src/sona/) | ReasoningBank eviction formula, EWC++ importance |
| RuVector Domain Expansion (crates/ruvector-domain-expansion/) | Thompson Sampling, dampened sqrt transfer, regret tracking |
| RuVector Nervous System (crates/ruvector-nervous-system/) | Global Workspace, circadian duty cycling, WTA ranking |
| RuVector Hooks (crates/ruvector-cli/src/cli/hooks.rs) | State composition for context keys, single-file intelligence |
| ACT-R (Anderson & Lebiere 1998) | Power-law decay formula for memory activation |

---

## Appendix: The Carmack Verdict

> *"The system has all the hallmarks of organic growth where every problem was solved by adding another module, another config parameter, another storage file. The right response to complexity is not more complexity -- it is deletion. You don't need 17 advisory modules. You need 3 that you understand completely. You don't need 576 tuneable parameters. You need 20 that you've actually measured. The cost of every abstraction, every indirection layer, every configuration option is not just the code -- it is the obstacle it creates for the next person trying to understand what this system actually does."*

> *"Abstraction trades an increase in real complexity for a decrease in perceived complexity. That isn't always a win."*

The goal is not a smaller system for its own sake. The goal is a system where you can "step a frame" -- trace one learning from observation to advice -- and understand everything that happens along the way. That is the foundation for a system that can be trusted, debugged, and improved.
