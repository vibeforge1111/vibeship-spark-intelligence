# Spark Alpha Structural Reduction Waves Plan

Date: 2026-02-27  
Branch: `feat/spark-alpha`  
Status: execution-ready (post alpha-start readiness lock)

## Goal

Close the remaining six alpha gaps with small, reversible waves while keeping:

1. `production_loop_report.py` at `READY`
2. replay evidence promotion pass rate at `1.0`
3. strict alpha-start readiness (`scripts/alpha_start_readiness.py --emit-report --strict`) green

## Locked baseline counters (from machine audit)

Source: `scripts/alpha_gap_audit.py` + `scripts/tuneables_usage_audit.py`

1. advisory files: `14`
2. tuneable schema: `40` sections / `415` keys
3. lib JSONL refs: `375`
4. distillation files: `5`
5. orchestrator module present: `false`
6. vibeforge code-evolve lane: `false`

## Hard safety contract (applies to every wave)

Each wave must:

1. ship in small commits (one concern per commit)
2. run alpha-start strict readiness before merge
3. update implementation status with before/after counters
4. keep rollback path to previous commit set

Automatic fail/rollback trigger:

1. `production_loop_report.py` not `READY`
2. replay batch promotion pass rate < `1.0`
3. strict readiness command returns non-zero

## Wave 1: Advisory surface compaction (low-medium risk)

Target outcome:

1. reduce advisory files from `14` to `10-11` without behavior change

Primary candidates (in order):

1. merge `advisory_log_paths.py` into direct callers (tiny indirection removal)
2. fold `advisory_parser.py` helpers into script-local parser module or one shared diagnostics helper
3. fold `advisory_quarantine.py` path/append helper into one shared reliability util
4. evaluate `advisory_intent_taxonomy.py` merge into `advisory_engine_alpha.py` if only used in two call sites

Deliverables:

1. import graph snapshot (before/after)
2. advisory file count delta via `alpha_gap_audit`
3. no regression in advisory core tests

Gate:

1. strict readiness green + advisory file count reduced

Rollback:

1. revert latest advisory compaction commit batch

## Wave 2: Config reduction wave 1 (medium risk)

Target outcome:

1. reduce tuneable keys from `415` to `<=340` in first pass

Method:

1. classify keys by usage tier from `tuneables_usage_audit`:
   - Tier A: high usage (keep)
   - Tier B: low usage (candidate merge/rename)
   - Tier C: dead/legacy aliases (remove)
2. remove Tier C keys in bounded section-by-section patches
3. keep compatibility for one cycle only where required, then delete shim

Deliverables:

1. key-deletion manifest in docs (per section)
2. schema and config loader updates
3. tuneables count delta reported by `alpha_gap_audit`

Gate:

1. strict readiness green + no schema validation failures

Rollback:

1. revert section-specific config commit

## Wave 3: Store consolidation wave 1 (medium risk)

Target outcome:

1. reduce `lib` JSONL references from `375` to `<=300` in first pass

Method:

1. separate runtime-critical logs vs observability-only logs
2. consolidate duplicated JSONL read/write helpers and dead paths
3. retire JSONL paths already superseded by SQLite lookups (no behavior branch resurrection)

Deliverables:

1. JSONL path inventory (before/after)
2. helper consolidation commits
3. no packet lookup/regression failures

Gate:

1. strict readiness green + JSONL ref count reduction

Rollback:

1. revert latest consolidation commit

## Wave 4: Compaction unification (medium-high risk)

Target outcome:

1. extend compaction beyond cognitive-only to advisory memory surfaces safely

Method:

1. define one compaction action contract (`update/delete/noop`) for advisory packet metadata candidates
2. add dry-run + apply modes with explicit artifacts
3. keep bounded apply caps per run

Deliverables:

1. unified compaction planner/report output
2. advisory-surface compaction preview artifacts
3. no negative trend in readiness/freshness/effectiveness gates

Gate:

1. strict readiness green after at least 2 compaction cycles

Rollback:

1. disable apply mode and keep preview-only

## Wave 5: Distillation collapse wave 1 (medium-high risk)

Target outcome:

1. reduce distillation files from `5` to `3` with one execution spine

Method:

1. define one canonical flow: observe -> filter -> score -> store -> promote
2. collapse duplicate transforms/refiners into one module with clearly scoped helpers
3. keep old modules only as temporary compatibility wrappers, then delete

Deliverables:

1. distillation flow map (before/after)
2. file-count reduction via `alpha_gap_audit`
3. no drop in distillation floor gate

Gate:

1. strict readiness green + distillation_floor gate preserved

Rollback:

1. revert latest distillation collapse commit set

## Wave 6: VibeForge boundary and promotion policy (low risk)

Target outcome:

1. keep this repo tuneable-only while codifying code-evolve boundary

Method:

1. document explicit non-goal for in-repo code-evolve lane
2. enforce boundary in alpha-start docs/checklist
3. only consume externally validated evolve deltas through reviewed PRs

Deliverables:

1. boundary policy update in alpha-start docs
2. `alpha_gap_audit` continues reporting `vibeforge_has_code_evolve_lane=false`

Gate:

1. docs + audit consistency verified

Rollback:

1. remove policy doc changes if strategy changes

## Execution cadence

For each wave:

1. run baseline audits (`alpha_gap_audit`, `tuneables_usage_audit`)
2. implement one reduction batch
3. run strict readiness
4. commit code
5. update implementation status with evidence and counters
6. commit docs

## Completion definition

Alpha structural reduction wave set is considered complete when:

1. advisory files <= `10`
2. tuneable keys <= `280`
3. lib JSONL refs <= `220`
4. distillation files <= `3`
5. strict readiness green for 3 consecutive runs after final wave

