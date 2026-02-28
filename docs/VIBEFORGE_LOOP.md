# VibeVibeForge Loop: Goal-Directed Self-Improvement

> *"Strengthen the verifier, not the generator."*
> -- Variance Inequality paper (arXiv:2512.02731)

> *"The secret to optimization is changing the problem to make it easier to optimize!"*
> -- John Carmack

**Date**: 2026-02-26
**Status**: Design Document + Implementation Spec
**Target**: Single-script CLI with future dashboard hookup

---

## What This Is

A goal-directed self-improvement loop for Spark Intelligence. You write one goal in plain text. The loop measures where you are, proposes one change (code edit or tuneable adjustment), tests it against an oracle evaluator, and promotes winners. One goal, one loop, one ledger.

It replaces:
- The auto-tuner daemon (800 lines, clamped to near-no-op)
- The executive loop (50+ files in a separate repo, ran once successfully)
- The planned Thompson Sampling source selector (150 lines)
- The planned Daily Governor from the 8-PR plan (500+ lines)

With ~400 lines of Python in one script, backed by existing measurement infrastructure.

---

## Research Foundations

This design draws from five proven systems:

### AlphaEvolve (DeepMind, May 2025)
- LLM proposes code changes within bounded blocks
- Evaluation cascades filter weak candidates cheaply
- MAP-Elites maintains diverse champions (not just global best)
- **Result**: 0.7% recovery of Google's worldwide compute via better Borg scheduling
- *Source*: arXiv:2506.13131

### FunSearch (DeepMind, Nature 2023)
- Evolve programs (code), not solutions directly
- Executable evaluation = unfoolable oracle
- Volume of candidates matters more than quality per candidate
- *Source*: Nature 2023, github.com/google-deepmind/funsearch

### Factory Signals (Factory.ai, 2025)
- Daily batch: detect friction patterns in agent sessions
- Auto-file tickets, auto-create PRs
- Human approval gate before merge
- **Result**: Detection-to-PR in <4 hours
- *Source*: factory.ai/news/factory-signals

### Darwin Godel Machine (Sakana AI, 2025)
- Agent modifies its own Python codebase
- Archive-based evolution with lineage tracking
- **Critical failure**: Agent falsified test results to game metrics
- **Lesson**: Oracle evaluator must be outside the agent's reach
- *Source*: arXiv:2505.22954

### Variance Inequality (arXiv:2512.02731, Dec 2025)
- Mathematical proof of when self-improvement converges vs. thrashes
- Key factors: evaluator alignment (rho), generation noise, verification noise
- **Rule**: Ensemble/oracle verifiers are non-negotiable. Same-model self-evaluation almost never converges.
- Four mechanisms that force convergence: ensemble verifiers, oracle verifiers, group normalization, cold verifiers

---

## Architecture

```
                    goal.json
                       │
          ┌────────────▼────────────┐
          │       1. MEASURE        │
          │   (oracle evaluator)    │
          │   carmack_kpi +         │
          │   production_gates +    │
          │   benchmark runner      │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │       2. DIAGNOSE       │
          │   gap = target - current│
          │   if gap <= 0: done     │
          │   pick biggest gap      │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │       3. PROPOSE        │
          │   LLM generates ONE     │
          │   change within         │
          │   EVOLVE-BLOCKs         │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │       4. TEST           │
          │   git branch            │
          │   apply change          │
          │   re-run oracle         │
          │   check constraints     │
          └──────┬───────────┬──────┘
                 │           │
            improved?    regressed?
                 │           │
          ┌──────▼──┐  ┌─────▼─────┐
          │ PROMOTE │  │ ROLLBACK  │
          │ (merge) │  │ (revert)  │
          └──────┬──┘  └─────┬─────┘
                 │           │
          ┌──────▼───────────▼──────┐
          │       5. RECORD         │
          │   update ledger         │
          │   update regret         │
          │   update goal.json      │
          └─────────────────────────┘
```

### Component Responsibilities

| Component | What It Does | Lines | Existing Code? |
|-----------|-------------|-------|:---:|
| Goal parser | Read goal.json, extract metric + target + constraints | ~40 | No |
| Measure | Snapshot all metrics via existing APIs | ~50 | Yes (carmack_kpi, production_gates) |
| Diagnose | Compare metrics to goal, find gap | ~30 | No |
| Propose | LLM call with context, bounded by EVOLVE-BLOCKs | ~80 | Partially (ask_claude exists) |
| Test | Git branch, apply, re-measure, compare | ~80 | Partially (snapshot exists) |
| Record | Ledger append, regret update, dashboard update | ~60 | No |
| CLI | Argument parsing, command dispatch | ~60 | No |
| **Total** | | **~400** | |

---

## The Goal File: `goal.json`

One file drives everything. Human-writable, machine-parseable.

```json
{
  "version": 1,
  "goal": "Improve advisory retrieval rate to 85%",
  "metric": {
    "name": "retrieval_rate",
    "source": "production_gates",
    "field": "retrieval_rate"
  },
  "baseline": 0.671,
  "target": 0.85,
  "constraints": [
    {
      "name": "garbage_leakage",
      "source": "production_gates",
      "field": "quality_rate",
      "operator": ">=",
      "threshold": 0.30,
      "description": "Meta-Ralph quality rate must not drop"
    },
    {
      "name": "advisory_latency",
      "source": "carmack_kpi",
      "field": "current.total_events",
      "operator": ">=",
      "threshold": 0,
      "description": "System must remain operational"
    }
  ],
  "evolve_blocks": [
    "lib/advisory_engine.py",
    "lib/noise_classifier.py",
    "lib/cognitive_learner.py",
    "config/tuneables.json"
  ],
  "max_cycles": 20,
  "status": "active",
  "created_at": "2026-02-26T12:00:00Z"
}
```

### Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `goal` | string | Human-readable goal statement |
| `metric.name` | string | Identifier for the target metric |
| `metric.source` | string | Where to read it: `production_gates`, `carmack_kpi`, `benchmark` |
| `metric.field` | string | Dot-path to the specific value |
| `baseline` | float | Value at goal creation time |
| `target` | float | Target value to reach |
| `constraints` | array | Metrics that must NOT regress |
| `evolve_blocks` | array | Files the loop is allowed to modify |
| `max_cycles` | int | Maximum improvement attempts |
| `status` | string | `active`, `paused`, `reached`, `failed` |

### Preset Goals

Common goals for quick setup via `vibeforge init <preset>`:

```
retrieval     -> "Improve advisory retrieval rate to 85%"
precision     -> "Improve retrieval precision P@5 to 40%"
noise         -> "Reduce garbage leakage below 3%"
duplicates    -> "Reduce duplicate memories below 5%"
latency       -> "Reduce advisory latency p95 below 30ms"
```

---

## EVOLVE-BLOCKs

Files that the loop can modify must contain explicit markers. The LLM can only modify code between these markers:

```python
# --- EVOLVE-BLOCK-START: retrieval_scoring ---
def score_retrieval_match(query_tokens, candidate_tokens, effectiveness=0.0):
    """Score a candidate's relevance to a query.

    This function is evolved by the VibeForge Loop.
    Do not add dependencies outside stdlib + numpy.
    """
    overlap = len(query_tokens & candidate_tokens)
    token_score = overlap / max(len(query_tokens), 1)
    eff_bonus = effectiveness * 0.3
    return token_score + eff_bonus
# --- EVOLVE-BLOCK-END ---
```

### Rules

1. Each block has a unique name after `EVOLVE-BLOCK-START:`
2. The LLM sees the full file but can only propose changes within blocks
3. Changes outside blocks are rejected before testing
4. `config/tuneables.json` is implicitly one big EVOLVE-BLOCK (any value can change, but the schema must validate)
5. New files cannot be created (prevents unbounded expansion)
6. Blocks should be pure-ish functions with clear inputs/outputs (Carmack's principle: pure functions are trivial to test)

### For Tuneable Changes

Tuneables don't need EVOLVE-BLOCK markers. The loop can propose any tuneable change. The existing `tuneables_schema.py` validates the change. The existing snapshot mechanism provides rollback.

```json
{
  "type": "tuneable",
  "section": "retrieval",
  "key": "bm25_k1",
  "current": 1.2,
  "proposed": 1.5,
  "reason": "Higher k1 increases term frequency saturation, benefiting longer queries"
}
```

---

## The Oracle Evaluator

The evaluator is the most important component. It must be:
- **External** to the LLM (the LLM cannot modify evaluation code)
- **Deterministic** (same inputs = same outputs)
- **Fast enough** to run after every change (~10-30 seconds)

### Evaluation Cascade (cheap first, expensive only for survivors)

```
Stage 1: Quick check (~2s)
├── Does the code parse? (ast.parse)
├── Do imports resolve?
├── Does tuneables schema validate?
└── FAIL FAST if any check fails

Stage 2: Gate metrics (~5s)
├── production_gates.load_live_metrics()
├── production_gates.evaluate_gates()
├── carmack_kpi.build_scorecard()
└── Compare to pre-change snapshot

Stage 3: Benchmark (optional, ~30s)
├── Run targeted benchmark on changed subsystem
├── E.g., if noise_classifier changed, run noise benchmark only
└── Full benchmark only for major changes
```

Stage 1 eliminates obviously broken proposals for free. Stage 2 catches regressions. Stage 3 provides ground truth for complex changes.

### Metric Resolution

The oracle reads metrics from existing sources:

```python
def resolve_metric(source: str, field: str) -> float:
    """Resolve a metric value from its source."""
    if source == "production_gates":
        metrics = load_live_metrics()
        return getattr(metrics, field)
    elif source == "carmack_kpi":
        scorecard = build_scorecard(window_hours=4.0)
        return _dot_get(scorecard, field)
    elif source == "benchmark":
        # Run targeted benchmark, return specific metric
        return run_targeted_benchmark(field)
    else:
        raise ValueError(f"Unknown metric source: {source}")
```

---

## The Proposal Engine

Uses `ask_claude()` from existing `lib/llm.py` (no API key needed, uses Claude Code CLI with OAuth).

### Proposal Prompt Template

```
You are a code evolution engine for Spark Intelligence, a self-improving AI learning system.

## Current Goal
{goal.goal}

## Current Metric
{metric.name}: {current_value} (target: {goal.target}, gap: {gap})

## Constraints (must not regress)
{formatted_constraints}

## Previous Attempts
{formatted_history}  # last 5 attempts with outcomes

## Files You Can Modify
{evolve_block_contents}

## Instructions
Propose exactly ONE change that moves the metric toward the target.

If proposing a CODE change:
- Return the full EVOLVE-BLOCK with your modification
- Keep changes minimal -- one function, one logic change
- Do not add dependencies
- Explain WHY this change should improve the metric

If proposing a TUNEABLE change:
- Return the section, key, current value, proposed value
- Explain the expected effect

Return your proposal in this format:
```json
{
  "type": "code" | "tuneable",
  "file": "path/to/file.py",
  "block_name": "retrieval_scoring",  // for code changes
  "section": "retrieval",             // for tuneable changes
  "key": "bm25_k1",                   // for tuneable changes
  "proposed_value": 1.5,              // for tuneable changes
  "new_code": "...",                  // for code changes
  "reason": "Why this should help",
  "expected_delta": "+3-5%"
}
```
```

### Rate Limiting

`ask_claude()` is capped at 30 calls/hour. Each VibeForge Loop cycle uses 1 call. Running 5 cycles uses 5 calls. This is well within budget.

For higher throughput (e.g., overnight evolution runs), switch to Ollama local via `llm_dispatch.py`:

```python
def propose_change(context: str, use_local: bool = False) -> dict:
    if use_local:
        # Use Ollama phi4-mini (unlimited, local)
        from lib.llm_dispatch import llm_area_call
        result = llm_area_call("forge_propose", context, fallback="{}")
        return json.loads(result.text)
    else:
        # Use Claude CLI (30/hr, higher quality)
        from lib.llm import ask_claude
        result = ask_claude(context, timeout_s=90)
        return json.loads(result) if result else None
```

---

## The Ledger

Every cycle records its outcome to `~/.spark/forge_ledger.jsonl`:

```json
{
  "cycle": 7,
  "timestamp": "2026-02-26T14:30:00Z",
  "goal": "Improve advisory retrieval rate to 85%",
  "metric_before": 0.723,
  "metric_after": 0.741,
  "delta": 0.018,
  "outcome": "promoted",
  "proposal": {
    "type": "code",
    "file": "lib/advisory_engine.py",
    "block_name": "retrieval_scoring",
    "reason": "Add file-path token overlap bonus to retrieval scoring"
  },
  "constraints_checked": [
    {"name": "garbage_leakage", "value": 0.32, "threshold": 0.30, "ok": true}
  ],
  "cumulative_regret": 0.142,
  "regret_rate": 0.38
}
```

---

## Regret Tracking

Regret measures whether the loop is actually learning:

```python
def update_regret(ledger_path: Path, reward: float):
    """Update cumulative regret after a cycle.

    reward = metric_after - metric_before (positive = improvement)
    best_possible = target - metric_before (what perfect would look like)
    regret = best_possible - reward (how far from perfect this cycle was)
    """
    entries = load_ledger(ledger_path)
    best_possible = max(reward, 0.01)  # avoid div-by-zero
    cycle_regret = max(0, best_possible - reward)

    cumulative = sum(e.get("cycle_regret", 0) for e in entries) + cycle_regret
    n = len(entries) + 1

    if cumulative <= 0 or n <= 1:
        rate = 0.0
    else:
        rate = math.log(cumulative + 1) / math.log(n + 1)

    return cumulative, rate
```

### Interpretation

| Regret Rate | Meaning | Action |
|-------------|---------|--------|
| < 0.5 | Learning rapidly | Continue |
| 0.5 - 0.7 | Learning, slowing | Continue, watch for plateau |
| 0.7 - 1.0 | Plateau | Consider changing strategy or EVOLVE-BLOCKs |
| > 1.0 | Diverging | **Auto-pause**, flag for human review |

When regret rate exceeds 1.0, the loop writes `"status": "paused"` to `goal.json` and prints a warning. Human must review and either change the goal, expand EVOLVE-BLOCKs, or reset.

---

## Guardrails

### 1. Oracle Evaluator Is Untouchable
The LLM cannot modify files outside `evolve_blocks`. The evaluator code (`carmack_kpi.py`, `production_gates.py`, benchmark files) is never in an EVOLVE-BLOCK. This prevents the DGM failure mode (agent deleting its own safety checks).

### 2. One Change Per Cycle
Never compound changes. If something regresses, you know exactly what caused it. The proposal engine returns exactly one change. Multiple changes in a single proposal are rejected.

### 3. Constraint Checks Are Non-Negotiable
Every constraint in `goal.json` is checked after every change. A change that improves the target metric by 10% but regresses a constraint by 0.1% is rolled back. No exceptions.

### 4. Syntax Validation Before Testing
Before applying a code change, parse it with `ast.parse()`. If it doesn't parse, reject immediately without running benchmarks. This prevents wasting evaluation budget on garbage.

### 5. Git Branch Isolation
Every proposed change is applied on a temporary branch. If anything goes wrong, the branch is deleted. The main working tree is never at risk.

### 6. Regret Auto-Pause
If regret rate > 1.0, the loop pauses automatically. This prevents runaway degradation from a series of bad proposals.

### 7. Ledger Is Append-Only
The forge ledger cannot be modified by the LLM. It is append-only, providing a tamper-evident audit trail of all changes.

### 8. Snapshot Before Every Tuneable Change
Before modifying `tuneables.json`, the existing auto-tuner snapshot mechanism saves a timestamped copy. The last 5 snapshots are retained for manual rollback.

---

## CLI Interface

### Command: `vibeforge`

The primary entry point. All commands operate on the goal file at `~/.spark/forge_goal.json` (or a custom path with `--goal`).

```
Usage: python scripts/vibeforge.py <command> [options]

Commands:
  init [preset]     Create a new goal (interactive or from preset)
  status            Show current goal, progress, regret, and last 5 cycles
  run               Run one improvement cycle
  run --cycles N    Run up to N improvement cycles
  run --local       Use Ollama local model instead of Claude CLI
  history           Show full evolution history
  rollback          Rollback the last promoted change
  pause             Pause the loop
  resume            Resume a paused loop
  reset             Reset regret counter and cycle count (keep goal)
  diff              Show code diff of all promoted changes vs baseline
```

### Example Session

```bash
# 1. Initialize a goal from preset
$ python scripts/vibeforge.py init retrieval

  Goal created: "Improve advisory retrieval rate to 85%"
  Baseline measured: 67.1%
  Target: 85.0%
  EVOLVE-BLOCKs: 4 files
  Constraints: 2 guard metrics

# 2. Check status
$ python scripts/vibeforge.py status

  VIBEFORGE LOOP
  ================
  Goal:     Improve advisory retrieval rate to 85%
  Status:   active
  Progress: [==========>-----------] 67.1% / 85.0%
  Gap:      17.9pp remaining
  Cycles:   0 run, 0 promoted, 0 rolled back
  Regret:   n/a (no cycles yet)

  Constraints:
    quality_rate     >= 0.30  current: 0.32  OK
    total_events     >= 0     current: 847   OK

  EVOLVE-BLOCKs:
    lib/advisory_engine.py       2 blocks
    lib/noise_classifier.py      1 block
    lib/cognitive_learner.py     1 block
    config/tuneables.json        (all sections)

# 3. Run 5 improvement cycles
$ python scripts/vibeforge.py run --cycles 5

  Cycle 1/5: MEASURE
    retrieval_rate = 0.671 (target: 0.850, gap: 0.179)

  Cycle 1/5: PROPOSE
    LLM proposing change... (using Claude CLI)
    Proposal: tuneable change retrieval.bm25_k1: 1.2 -> 1.4
    Reason: "Higher k1 increases term frequency saturation for multi-word queries"

  Cycle 1/5: TEST
    Applying to branch forge/cycle-001...
    Stage 1 (syntax): PASS
    Stage 2 (gates):  retrieval_rate = 0.689 (+0.018)
    Constraints:      quality_rate 0.33 >= 0.30 OK

  Cycle 1/5: PROMOTED  67.1% -> 68.9% (+1.8pp)
  --------------------------------------------------

  Cycle 2/5: MEASURE
    retrieval_rate = 0.689 (target: 0.850, gap: 0.161)

  Cycle 2/5: PROPOSE
    LLM proposing change... (using Claude CLI)
    Proposal: code change lib/advisory_engine.py:retrieval_scoring
    Reason: "Add file-path token overlap to boost context-relevant results"

  Cycle 2/5: TEST
    Applying to branch forge/cycle-002...
    Stage 1 (syntax): PASS
    Stage 2 (gates):  retrieval_rate = 0.723 (+0.034)
    Constraints:      quality_rate 0.31 >= 0.30 OK

  Cycle 2/5: PROMOTED  68.9% -> 72.3% (+3.4pp)
  --------------------------------------------------

  Cycle 3/5: MEASURE
    retrieval_rate = 0.723 (target: 0.850, gap: 0.127)

  Cycle 3/5: PROPOSE
    LLM proposing change... (using Claude CLI)
    Proposal: code change lib/noise_classifier.py:noise_rules
    Reason: "Relax operational metric filter to not catch legitimate process insights"

  Cycle 3/5: TEST
    Applying to branch forge/cycle-003...
    Stage 1 (syntax): PASS
    Stage 2 (gates):  retrieval_rate = 0.718 (-0.005)

  Cycle 3/5: ROLLED BACK  (no improvement)
  --------------------------------------------------

  Cycle 4/5: MEASURE
    retrieval_rate = 0.723 (target: 0.850, gap: 0.127)

  ...

  Summary after 5 cycles:
    Started:   67.1%
    Current:   74.1%
    Promoted:  3 / Rolled back: 2
    Regret:    0.42 (learning)

# 4. Check history
$ python scripts/vibeforge.py history

  FORGE EVOLUTION HISTORY
  =======================
  Cycle  Outcome     Before  After   Delta   Change
  1      promoted    67.1%   68.9%   +1.8pp  tuneable: retrieval.bm25_k1 1.2->1.4
  2      promoted    68.9%   72.3%   +3.4pp  code: advisory_engine.py:retrieval_scoring
  3      rolled_back 72.3%   71.8%   -0.5pp  code: noise_classifier.py:noise_rules
  4      promoted    72.3%   74.1%   +1.8pp  tuneable: retrieval.semantic_context_min 0.3->0.25
  5      rolled_back 74.1%   73.9%   -0.2pp  code: cognitive_learner.py:insight_scoring

  Regret rate: 0.42 (learning)
  Total improvement: +7.0pp (67.1% -> 74.1%)

# 5. Rollback last change if needed
$ python scripts/vibeforge.py rollback

  Rolling back cycle 4 (tuneable: retrieval.semantic_context_min 0.25 -> 0.3)
  Restored tuneables snapshot from 2026-02-26T14:28:00Z
  Current retrieval_rate: 72.3%
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (goal reached, or cycles completed normally) |
| 1 | Error (invalid goal, LLM failure, etc.) |
| 2 | Paused (regret rate > 1.0, human review needed) |
| 3 | Goal already reached |

---

## Integration With Existing Infrastructure

### What We Reuse (zero new code needed)

| Component | Existing Module | Function |
|-----------|----------------|----------|
| KPI snapshot | `lib/carmack_kpi` | `build_scorecard(window_hours=4.0)` |
| Health alerts | `lib/carmack_kpi` | `build_health_alert(scorecard)` |
| Loop metrics | `lib/production_gates` | `load_live_metrics()` -> `LoopMetrics` |
| Gate evaluation | `lib/production_gates` | `evaluate_gates(metrics)` -> pass/fail |
| System health | `lib/auto_tuner` | `AutoTuner().measure_system_health()` -> `SystemHealth` |
| Tuneable snapshot | `lib/auto_tuner` | `apply_recommendations()` auto-snapshots |
| LLM calls | `lib/llm` | `ask_claude(prompt, timeout_s=90)` |
| Outcome prediction | `lib/outcome_predictor` | `predict(tool_name, intent, phase)` |
| Schema validation | `lib/tuneables_schema` | Validates tuneable changes |
| Config resolution | `lib/config_authority` | Reads live tuneables |

### What We Build New (~400 lines)

| Component | Lines | Purpose |
|-----------|-------|---------|
| Goal parser | ~40 | Read/write `goal.json`, validate schema |
| Metric resolver | ~50 | Bridge between goal config and existing APIs |
| Proposal engine | ~80 | Build prompt, call LLM, parse response, validate EVOLVE-BLOCK bounds |
| Change applier | ~60 | Git branch, apply code/tuneable change, validate syntax |
| Oracle runner | ~50 | Run evaluation cascade (syntax -> gates -> benchmark) |
| Regret tracker | ~30 | Update cumulative regret + rate |
| Ledger manager | ~30 | Append to JSONL, read history |
| CLI dispatcher | ~60 | argparse commands: init, status, run, history, rollback, pause, resume, reset, diff |

---

## Dashboard Hookup (Future)

The CLI is designed to be dashboard-ready. Every command produces structured output that a web dashboard can consume:

### JSON Output Mode

```bash
# All commands support --json for machine-readable output
$ python scripts/vibeforge.py status --json
{
  "goal": "Improve advisory retrieval rate to 85%",
  "status": "active",
  "current": 0.741,
  "target": 0.85,
  "gap": 0.109,
  "cycles_run": 5,
  "cycles_promoted": 3,
  "cycles_rolled_back": 2,
  "regret_rate": 0.42,
  "constraints": [...],
  "last_cycle": {...}
}
```

### Dashboard Data Contract

When a web dashboard is built, it reads from:

| Data Source | Format | Updated By |
|-------------|--------|-----------|
| `~/.spark/forge_goal.json` | JSON | CLI `init`, `pause`, `resume`, `reset` |
| `~/.spark/forge_ledger.jsonl` | JSONL (append-only) | CLI `run` (after each cycle) |
| `~/.spark/forge_evolve_blocks.json` | JSON | CLI `init` (lists blocks + line ranges) |

The dashboard renders:
- **Goal card**: goal text, progress bar, regret curve
- **Evolution timeline**: one row per cycle (outcome, delta, change description)
- **Constraint status**: green/red badges per constraint
- **EVOLVE-BLOCK inventory**: which files/functions are evolvable
- **Controls**: Pause, Resume, Change Goal, Force Rollback

No Streamlit. When we build it, it'll be a simple HTML + JS page (like the existing `dashboard/social_intel/index.html`) that polls the JSON files, or a FastAPI endpoint that serves them.

---

## Presets Reference

### `retrieval` -- Improve Advisory Retrieval

```json
{
  "goal": "Improve advisory retrieval rate to 85%",
  "metric": {"name": "retrieval_rate", "source": "production_gates", "field": "retrieval_rate"},
  "baseline": null,
  "target": 0.85,
  "constraints": [
    {"name": "quality_rate", "source": "production_gates", "field": "quality_rate", "operator": ">=", "threshold": 0.30},
    {"name": "effectiveness", "source": "production_gates", "field": "effectiveness_rate", "operator": ">=", "threshold": 0.40}
  ],
  "evolve_blocks": ["lib/advisory_engine.py", "lib/cognitive_learner.py", "config/tuneables.json"]
}
```

### `precision` -- Improve Retrieval Precision

```json
{
  "goal": "Improve retrieval precision P@5 to 40%",
  "metric": {"name": "precision_at_5", "source": "benchmark", "field": "retrieval_precision_p5"},
  "baseline": null,
  "target": 0.40,
  "constraints": [
    {"name": "retrieval_rate", "source": "production_gates", "field": "retrieval_rate", "operator": ">=", "threshold": 0.60}
  ],
  "evolve_blocks": ["lib/semantic_retriever.py", "lib/advisory_engine.py", "config/tuneables.json"]
}
```

### `noise` -- Reduce Garbage Leakage

```json
{
  "goal": "Reduce garbage leakage below 3%",
  "metric": {"name": "garbage_leakage", "source": "benchmark", "field": "garbage_leakage_rate"},
  "baseline": null,
  "target": 0.03,
  "constraints": [
    {"name": "useful_pass_rate", "source": "benchmark", "field": "useful_pass_rate", "operator": ">=", "threshold": 0.55}
  ],
  "evolve_blocks": ["lib/noise_classifier.py", "lib/meta_ralph.py", "config/tuneables.json"]
}
```

### `custom` -- Define Your Own

```bash
$ python scripts/vibeforge.py init
  What is your goal? > Improve EIDOS distillation yield to 5 per session
  Which metric tracks this? > distillations (from production_gates)
  What is the target value? > 5
  Which files should be evolvable? > lib/eidos/integration.py, lib/pattern_detection/distiller.py
  Any constraints? > retrieval_rate >= 0.60, quality_rate >= 0.30
```

---

## Safety Comparison

| Risk | How AlphaEvolve Handles It | How VibeForge Loop Handles It |
|------|--------------------------|--------------------------|
| Agent corrupts evaluator | Evaluators are separate processes | Evaluator files excluded from EVOLVE-BLOCKs |
| Agent games metrics | Evaluation cascades filter cheap tricks | AST parse + gate checks + constraint checks |
| Compounding bad changes | MAP-Elites maintains diversity | One change per cycle + immediate rollback |
| Stale evaluation signals | Regular population refresh | Regret tracking detects divergence |
| Runaway degradation | Population-based (bad individuals die) | Auto-pause at regret rate > 1.0 |
| Loss of lineage | Archive retention | Append-only JSONL ledger |
| Unbounded action space | EVOLVE-BLOCK markers | EVOLVE-BLOCK markers (same pattern) |

---

## What This Replaces

| System | Current | After VibeForge Loop |
|--------|---------|-----------------|
| Auto-tuner | 800 lines, clamped to near-no-op, 34 config params | Tuneable proposals within the VibeForge Loop |
| Executive Loop | 50+ files in separate repo, 8 safety gates, ran once | VibeForge Loop with 8 guardrails in ~400 lines |
| Thompson Sampling | Planned, 150 lines, only adjusts numbers | VibeForge Loop (superset: numbers + code) |
| Daily Governor | Planned, 500+ lines, 12-knob RL policy | VibeForge Loop (simpler, one goal, one change) |
| Config evolution | 34 auto-tuner params + 576 tuneables | Goal.json + EVOLVE-BLOCKs |

---

## References

| Source | Key Insight |
|--------|-----------|
| [AlphaEvolve (arXiv:2506.13131)](https://arxiv.org/abs/2506.13131) | EVOLVE-BLOCK pattern, evaluation cascades, MAP-Elites |
| [OpenEvolve (GitHub)](https://github.com/algorithmicsuperintelligence/openevolve) | Open-source implementation of AlphaEvolve pattern |
| [FunSearch (Nature 2023)](https://www.nature.com/articles/s41586-023-06924-6) | Evolve programs, not solutions; executable eval is key |
| [Darwin Godel Machine (arXiv:2505.22954)](https://arxiv.org/abs/2505.22954) | Agent modified own codebase; falsified tests as failure mode |
| [Variance Inequality (arXiv:2512.02731)](https://arxiv.org/abs/2512.02731) | Mathematical proof: strengthen verifier, not generator |
| [ECO at Google (arXiv:2503.15669)](https://arxiv.org/abs/2503.15669) | Production self-improving code: 25K lines changed, 99.5% success |
| [Factory Signals](https://factory.ai/news/factory-signals) | Detection-to-PR in <4 hours, human approval gate |
| [OpenAI Self-Evolving Cookbook](https://developers.openai.com/cookbook/examples/partners/self_evolving_agents/autonomous_agent_retraining/) | 4-grader evaluation, versioned prompts, aggregate selection |
| [Group-Evolving Agents (arXiv:2602.04837)](https://arxiv.org/abs/2602.04837) | 71% SWE-bench via group experience sharing |
| John Carmack | "If you're willing to restrict flexibility, you can almost always do something better" |
