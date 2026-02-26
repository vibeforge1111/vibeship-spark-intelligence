# Spark Alpha Fusion Plan (Status + V2 Destination)

Date: 2026-02-27
Branch: `feat/spark-alpha`

## Purpose
Merge three things into one executable plan:
1. Current implementation status ([SPARK_ALPHA_IMPLEMENTATION_STATUS.md](./SPARK_ALPHA_IMPLEMENTATION_STATUS.md))
2. V2 simplification destination ([SPARK_V2_SIMPLIFICATION_PLAN.md](./SPARK_V2_SIMPLIFICATION_PLAN.md))
3. Migration discipline from the 8-PR risk-on plan (shadow/dual-write/champion-challenger/replay)

## Non-Negotiables
1. No big-bang rewrite.
2. Every new alpha path must have a paired deletion path.
3. Measurement contract remains authoritative before and after cutovers.
4. Use the VibeForge goal-directed self-improvement loop for tuning/evolution; RL governor remains optional and off critical path.
5. Cutover only with replay wins + live gate pass.

## Current Reality (Already Completed)
Completed commits:
1. `59865e8` metric contract + baseline tooling
2. `051d6de` unified noise classifier scaffold
3. `86a33ee` classifier shadow integration across promoter/meta/cognitive
4. `11c1808` contextual memory envelope + backfill tooling
5. `4b3e4df` advisory no-emit loop fix (bounded repeat escape)
6. `734bddf` strict trace binding repairs + packet freshness repair + quality-band telemetry guard
7. `89ac67f` PR-03 dual scoring challenger integration (shadow + enforce gated)
8. `72b42b3` PR-04 SQLite dual-write for cognitive insights (JSON still canonical)
9. `0b8a4ba` PR-05 deterministic RRF retrieval fusion signal (runtime + AB harness)
10. `23ef06a` PR-06 advisory alpha vertical slice route + canary orchestration
11. `d02fdae` PR-07 deterministic replay arena + promotion ledger
12. `e5b1263` PR-09 utility dedup: shared JSONL helper extraction
13. `2c4c3cb` PR-10 initial legacy fallback deletion sweep
14. `52d555f` PR-10 follow-up: dead fallback config surface deletion + schema prune
15. `80d8df2` PR-03 promotion: single-score primary path, dual runtime retired
16. `4244369` PR-05 follow-up: packet freshness extension on usage
17. `0f559d9` PR-04 follow-up: memory spine parity report + gate tooling
18. `1bdedfb` PR-06 follow-up: advisory route default cutover to alpha
19. `0f3740d` runtime default: startup canary route at 80% alpha
20. `24ff81a` gate stabilization: strict trace recovery + effective packet freshness metrics
21. `f324e32` retrieval collapse: semantic-first cognitive path with legacy fallback opt-in only
22. `7b69e46` PR-04 follow-up: parity streak ledger gate tool
23. `a29a5d4` PR-04 promotion: cognitive learner moved to SQLite-canonical mode with JSON mirror compatibility
24. `dede8a5` PR-05 follow-up: removed superseded fallback rank-extension branch in retrieval prefilter
25. `687d965` PR-06 follow-up: alpha-native post-tool and user-prompt handlers (legacy delegation removed)
26. `a7ec9bb` PR-08 start: VibeForge loop CLI skeleton (`init/status/run-once/run/history/pause/resume`)
27. `291d3cb` PR-08 hardening: tuneable loop gets adaptive proposer ranking + `rollback/reset/diff` + cycle budget enforcement
28. `824fb62` PR-08 follow-up: momentum proposer extension + schema-bounded candidate values
29. `e9a9335` PR-08 follow-up: benchmark metric source support (`path` or `command` + stdout JSON)

Current measured state:
1. `production_loop_report.py`: `READY (19/19 passed)`
2. `memory_quality_observatory.py`: retrieval guardrails passing
3. Key metrics: `context.p50=230`, `advisory.emit_rate=0.194`, `strict_trace_coverage=0.7883`
4. Replay arena latest (`scripts/spark_alpha_replay_arena.py --episodes 20 --seed 42`):
   - winner: `alpha`
   - `promotion_gate_pass=true`
   - `consecutive_pass_streak=13`

## Gap vs V2 Simplification Scope
1. Storage consolidation (128 files -> single spine): partial
2. Unified noise classifier: done (shadowed, enforce-capable)
3. Advisory collapse (17 files -> 3): partial
4. Memory compaction (ACT-R + Mem0 protocol): pending
5. Delivery-time retrieval improvement: partial
6. VibeForge self-improvement loop (goal + oracle + propose/test/promote ledger): partial
7. Config reduction (576 -> ~70): pending
8. Distillation pipeline collapse: pending
9. Test overhaul (behavioral/replay dominant): partial
10. Shared utility extraction + duplicate deletion: pending

## Upgraded Roadmap (10 PRs)

### PR-01 Baseline Contract Lock  (Done)
1. Measurement contract versioning and drift checks.
2. Baseline rehydrate tooling.

### PR-02 Unified Noise Classifier (Shadow-First)  (Done)
1. Unified classifier introduced.
2. Legacy-vs-unified disagreement logging.

### PR-03 Dual Scoring (Meta)  (Done)
1. Promotion criteria met (replay streak above gate); alpha scorer is now primary.
2. Dual-score shadow/enforce runtime path is retired.
3. Legacy scorer remains only as emergency fallback on scorer errors.

### PR-04 Memory Spine + Contextual Write  (Done for Cognitive Surface)
1. Contextual write path is done.
2. SQLite dual-write path for cognitive insights is implemented and promoted to SQLite-canonical mode in learner.
3. Added parity tooling (`memory_spine_parity_report.py`) with threshold gate semantics.
4. Added parity streak ledger gate (`memory_spine_parity_gate.py`) and reached `5/3` consecutive passes.
5. JSON writes are now compatibility mirror only (`SPARK_MEMORY_SPINE_JSON_MIRROR`), not canonical source.
6. Remaining: extend SQLite-first coverage across advisory/memory surfaces beyond cognitive learner.

### PR-05 Retrieval Fusion (RRF + Contextual Retrieval)  (Done for Current Scope)
1. Hybrid retrieval now includes deterministic RRF fusion (semantic + lexical + support ranks).
2. Improve dominant-key and low-sim behavior.
3. Added packet freshness extension on usage to reduce stale-store decay for active advisory packets.
4. Added semantic-only default for cognitive advice (keyword fallback now opt-in via env).
5. Removed superseded fallback rank-extension branch in prefilter ranking path.
6. Remaining: broader retrieval simplification and post-cutover deletion pass outside this branch.

### PR-06 Advisory Alpha Vertical Slice  (Near Complete)
1. Emission reliability and trace binding improved.
2. Added compact `advisory_engine_alpha` pre-tool path (retrieve -> gate -> synthesize -> emit).
3. Added route orchestrator for pre/post/prompt flows with canary routing and fallback.
4. Route default is now `alpha` (with engine fallback retained for rollback safety).
5. Startup runtime default is now `canary` at 80% alpha for controlled burn-in.
6. Expanded alpha ownership for post-tool and user-prompt (legacy delegation removed in alpha handlers).
7. Remaining: broad legacy advisory file deletion once replay arena + live canary pass.

### PR-07 Replay Arena (Champion/Challenger)  (Implemented)
1. Added `scripts/spark_alpha_replay_arena.py` for deterministic replay on identical episodes.
2. Added route scorecards (legacy champion vs alpha challenger) with utility/safety/trace integrity/latency metrics.
3. Added weighted winner gate and promotion ledger with 3-consecutive-pass tracking.
4. Added regression diff artifacts in `benchmarks/out/replay_arena/`.
5. Remaining: run larger deterministic episode windows as ongoing evidence before irreversible deletions.

### PR-08 VibeForge Loop (Partial)
1. Initial CLI landed in `scripts/vibeforge.py` with `init/status/run-once/run/history/pause/resume`.
2. Tuneable proposal lane ships with schema validation, backup/rollback, and append-only ledger.
3. Added operational controls for tuneable lane: `rollback`, `reset`, and `diff`.
4. Added adaptive candidate ordering from ledger outcomes (lightweight exploration/exploitation scoring).
5. Added momentum continuation lane from recent promoted tuneable moves.
6. Added schema-bounded candidate shaping before apply to reduce invalid/no-op attempts.
7. Added max-cycle budget enforcement (`max_cycles`) with explicit terminal outcome tracking.
8. Added safer promotion criteria and failure handling:
   - promotion requires objective improvement + constraint pass + gates-ready
   - apply/measure exceptions auto-rollback and emit explicit `error_rolled_back` row
9. Added benchmark-source metric resolution for goals:
   - file-backed benchmark payloads via `metric.path`
   - command-refreshed payloads via `metric.command`
   - optional stdout JSON parse via `metric.json_from_stdout=true`
10. Remaining: EVOLVE-BLOCK code patch lane and richer benchmark-stage oracle cascade policy.

### PR-09 Config Reduction + Utility Dedup  (Partial)
1. Consolidated duplicated JSONL helpers into shared `lib/jsonl_utils.py`.
2. Replaced local helper copies in advisory engine/orchestrator/alpha/quarantine modules.
3. Removed dead advisory fallback tuneables (`fallback_budget_cap/window`) from schema after fallback lane deletion.
4. Remaining: broad tuneable pruning and additional utility dedup across non-advisory surfaces.

### PR-10 Legacy Deletion Sweep (Mandatory)  (Partial)
1. Removed hook-level legacy fallback (`observe.py` direct `advisor.advise_on_tool` fallback).
2. Removed legacy `live_quick` fallback route from advisory engine.
3. Removed packet no-emit fallback emission path; gate suppression now stays explicit no-emit.
4. Removed dead fallback control surface (unused fallback env/tuneable plumbing + dead helper functions).
5. Remaining: larger advisory-stack file deletion set after live canary pass.
6. Pending broader sweep once PR-03/04/05/06 are proven:
   - Legacy advisory stack (targeting 17-file collapse from V2)
   - Redundant noise filters no longer used
   - Legacy storage write paths replaced by SQLite spine
7. Output required: explicit deleted file list + LOC removed + rollback tag.

## Methods Decision (RL Governor vs VibeForge Loop)
Default path for alpha:
1. Use VibeForge loop as the primary self-improvement mechanism (code+tuneables, oracle-gated).
2. Keep Daily Governor/RL as optional experiment lane only after alpha is stable.

Reason:
1. Higher leverage than Thompson-only tuning because it can evolve both code and tuneables.
2. Maintains Carmack discipline via bounded change surface, deterministic gates, and explicit rollback.

## Anti Dual-Path Trap Rules
1. Any PR that adds an alpha path must specify the exact legacy path scheduled for removal.
2. No alpha feature is "done" until its paired deletion PR lands.
3. Release candidate cannot ship with both champion and challenger permanently active.

## Cutover Requirements (Hard)
Alpha cutover to default only if all hold:
1. `production_loop_report.py` remains `READY` for 3 consecutive runs.
2. Replay arena: alpha wins 3 consecutive runs.
3. No safety regression and no guardrail regression.
4. Deletion PRs for replaced legacy paths are merged (not deferred).
