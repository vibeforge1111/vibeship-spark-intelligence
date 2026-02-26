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
4. Prefer simple self-tuning first (EMA/Thompson). RL governor is optional, not on critical path.
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

Current measured state:
1. `production_loop_report.py`: `NOT READY (16/19 passed)`
2. `memory_quality_observatory.py`: retrieval guardrails passing
3. Key metrics: `context.p50=230`, `advisory.emit_rate=0.194`, `strict_trace_coverage=0.5985`
4. Replay arena latest (`scripts/spark_alpha_replay_arena.py --episodes 20 --seed 42`):
   - winner: `alpha`
   - `promotion_gate_pass=true`
   - `consecutive_pass_streak=9`

## Gap vs V2 Simplification Scope
1. Storage consolidation (128 files -> single spine): partial
2. Unified noise classifier: done (shadowed, enforce-capable)
3. Advisory collapse (17 files -> 3): partial
4. Memory compaction (ACT-R + Mem0 protocol): pending
5. Delivery-time retrieval improvement: partial
6. Thompson sampling self-tuning: pending
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

### PR-04 Memory Spine + Contextual Write  (Partial)
1. Contextual write path is done.
2. SQLite dual-write path for cognitive insights is now implemented (shadow lane).
3. Remaining: extend spine coverage across advisory/memory surfaces and add parity checks.
4. Deletion commitment: remove JSONL writes after parity >= 99.5% for 3 runs.

### PR-05 Retrieval Fusion (RRF + Contextual Retrieval)  (Partial)
1. Hybrid retrieval now includes deterministic RRF fusion (semantic + lexical + support ranks).
2. Improve dominant-key and low-sim behavior.
3. Remaining: replay/canary validation before replacing old ranking paths.
4. Deletion commitment: remove superseded single-path rank logic after replay pass.

### PR-06 Advisory Alpha Vertical Slice  (Partial)
1. Emission reliability and trace binding improved.
2. Added compact `advisory_engine_alpha` pre-tool path (retrieve -> gate -> synthesize -> emit).
3. Added route orchestrator for pre/post/prompt flows with canary routing and fallback.
4. Remaining: expand alpha ownership for post-tool and prompt paths (currently delegated) and validate via replay/canary.
5. Deletion commitment: remove legacy advisory path files once replay arena + live canary pass.

### PR-07 Replay Arena (Champion/Challenger)  (Implemented)
1. Added `scripts/spark_alpha_replay_arena.py` for deterministic replay on identical episodes.
2. Added route scorecards (legacy champion vs alpha challenger) with utility/safety/trace integrity/latency metrics.
3. Added weighted winner gate and promotion ledger with 3-consecutive-pass tracking.
4. Added regression diff artifacts in `benchmarks/out/replay_arena/`.
5. Remaining: run larger deterministic episode windows as ongoing evidence before irreversible deletions.

### PR-08 Reserved Risk Slot  (Pending, User-Defined)
1. Reserved for the additional high-risk module the user wants to add at finalization.
2. Constraint: must be behind route flag and reversible in one commit.
3. Not required for baseline alpha cutover.

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

## Methods Decision (RL Governor vs Thompson)
Default path for alpha:
1. Use Thompson Sampling + EMA for lightweight online self-tuning.
2. Keep Daily Governor/RL as optional experiment lane only after alpha is stable.

Reason:
1. Matches current scale and structured event regime.
2. Avoids adding a new control system before deletion milestones are complete.

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
