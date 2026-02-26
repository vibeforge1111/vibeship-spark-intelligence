# Spark Alpha Fusion Plan (Status + V2 Destination)

Date: 2026-02-26
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
7. `(working tree)` PR-03 dual scoring challenger integration (shadow + enforce gated)

Current measured state:
1. `production_loop_report.py`: `READY (19/19 passed)`
2. `memory_quality_observatory.py`: retrieval guardrails passing
3. Key metrics: `context.p50=230`, `advisory.emit_rate=0.194`, `strict_trace_coverage=0.5985`

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

### PR-03 Dual Scoring (Meta)  (Partial: Implemented, Replay Promotion Pending)
1. Run legacy + alpha scorer side-by-side.
2. Challenger scoring is now shadowed by default with an explicit enforce flag.
3. Promote decisions from challenger only after replay win criteria.
4. Deletion commitment: remove legacy scorer path after 3 consecutive replay wins.

### PR-04 Memory Spine + Contextual Write  (Partial)
1. Contextual write path is done.
2. Remaining: SQLite-first dual-write spine.
3. Deletion commitment: remove JSONL writes after parity >= 99.5% for 3 runs.

### PR-05 Retrieval Fusion (RRF + Contextual Retrieval)  (Pending)
1. Hybrid retrieval with deterministic fusion.
2. Improve dominant-key and low-sim behavior.
3. Deletion commitment: remove superseded single-path rank logic after replay pass.

### PR-06 Advisory Alpha Vertical Slice  (Partial)
1. Emission reliability and trace binding improved.
2. Remaining: consolidated alpha path coverage across all tool routes.
3. Deletion commitment: remove legacy advisory path files once replay arena + live canary pass.

### PR-07 Replay Arena (Champion/Challenger)  (Pending, Required)
1. Deterministic replay on identical episodes.
2. Scores: utility, safety, trace integrity, latency.
3. Promotion rule: alpha must win weighted score in 3 consecutive runs.

### PR-08 Reserved Risk Slot  (Pending, User-Defined)
1. Reserved for the additional high-risk module the user wants to add at finalization.
2. Constraint: must be behind route flag and reversible in one commit.
3. Not required for baseline alpha cutover.

### PR-09 Config Reduction + Utility Dedup  (Pending)
1. Remove low-value knobs and dead tuneables.
2. Consolidate duplicated helpers (`_tail_jsonl`, `_append_jsonl_capped`, float/bool parsers).
3. Deletion commitment: remove at least 500 tuneables and 30+ duplicate utility copies.

### PR-10 Legacy Deletion Sweep (Mandatory)  (Pending)
1. Delete deprecated dual paths once PR-03/04/05/06 are proven.
2. Candidate deletion set includes:
   - Legacy advisory stack (targeting 17-file collapse from V2)
   - Redundant noise filters no longer used
   - Legacy storage write paths replaced by SQLite spine
3. Output required: explicit deleted file list + LOC removed + rollback tag.

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
