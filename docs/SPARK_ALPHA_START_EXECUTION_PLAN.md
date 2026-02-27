# Spark Alpha Start Execution Plan

Date: 2026-02-27  
Branch: `feat/spark-alpha`  
Mode: autonomous sequence (no-stop execution order)

## Objective

Ship a stable Spark Alpha start state now, with a repeatable proof command that verifies:

1. production gates remain green
2. replay arena keeps promoting alpha
3. advisory loop remains healthy under controlled load
4. core alpha regression tests keep passing

## Current baseline (locked before this plan)

Latest measured signals:

1. `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
2. `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke`
   - winner: `alpha`
   - promotion gate: `true`
   - eligible for cutover: `true`
   - streak: `19`
3. `python scripts/advisory_controlled_delta.py --rounds 2 --label smoke_alpha --out benchmarks/out/advisory_delta_smoke_alpha.json` -> pass
4. broad alpha regression slice -> `245 passed`

## Deep audit contract (must stay visible in this plan)

### Verified done

1. Alpha runtime is live and stable:
   - `production_loop_report.py` -> `READY (19/19 passed)`
   - replay smoke -> winner `alpha`, `promotion_gate_pass=true`, streak `19`
   - controlled delta smoke -> pass
2. Broad regression slice is green:
   - `245 passed` across alpha/replay/memory/gates/LLM/tuneables tests
3. Orchestrator removal is complete:
   - `lib/advisory_orchestrator.py` removed
   - no runtime imports of `lib.advisory_orchestrator` remain

### Verified not done

1. Full advisory collapse not complete:
   - still `14` `lib/*advisory*.py` files
2. Config surface still large:
   - `lib/tuneables_schema.py` -> `40` sections, `415` keys
3. Single-store consolidation still partial:
   - SQLite path exists, but JSON/JSONL surface remains broad
4. Memory compaction still partial:
   - ACT-R compaction exists, but no unified advisory-store compaction layer
5. Distillation simplification not complete:
   - `5` distillation files remain
6. VibeForge evolve lane deferred:
   - current implementation is tuneable proposal/rollback (no code-evolve lane in this repo)

## Alpha-start definition (what "ready to start alpha" means)

All must hold in one run:

1. production gates: `READY`
2. replay batch promotion pass rate: `>= 1.0` for configured seeds/episodes
3. controlled-delta run: success
4. alpha core test slice: green

## Ordered task queue

### Phase A: Proof command (execute now)

Goal: replace manual checking with one reproducible command and artifacts.

Tasks:

1. Add `scripts/alpha_start_readiness.py` orchestrator:
   - runs production gates
   - runs replay evidence batch
   - runs controlled delta smoke
   - runs alpha core pytest slice
   - writes JSON + Markdown report to `benchmarks/out/alpha_start/`
2. Add focused helper tests for parsing/summarization logic.
3. Run the new command and capture artifacts.

Exit criteria:

1. command exits `0`
2. report includes pass/fail per stage and final `ready=true`

Rollback:

1. delete new script/tests and continue with existing manual scripts

### Phase B: Alpha surface freeze (execute after Phase A)

Goal: prevent drift while testing alpha.

Tasks:

1. Freeze alpha start command contract in docs.
2. Add "required artifact set" checklist for every alpha run.
3. Keep existing runtime path alpha-only (already done) and avoid adding new fallback paths.
4. Add and run `scripts/alpha_gap_audit.py` each cycle so pending-gap counters are machine-generated (advisory files, tuneable keys, JSONL surface, distillation files, VibeForge lane flags).

Exit criteria:

1. every run produces the same artifact schema and pass/fail summary

Rollback:

1. use direct individual commands if orchestrator script fails

### Phase C: First structural reduction wave (post alpha-start)

Goal: reduce maintenance surface without destabilizing alpha.

Tasks:

1. advisory module compaction wave 1:
   - target reduction from current `14` advisory files by merging low-value wrappers
2. config reduction wave 1:
   - cut unused tuneable keys from current `415`
3. distillation path wave 1:
   - collapse duplicated distillation steps behind one execution flow

Exit criteria:

1. no gate regression
2. replay batch pass rate unchanged
3. reduced file/key counts recorded in status

Rollback:

1. revert each reduction commit independently (small-batch commits only)

### Phase D: Gap-closure waves (after alpha-start command is stable)

Goal: close the six verified-not-done gaps with measurable cuts.

Tasks:

1. Advisory collapse wave:
   - reduce advisory file count below `14` in bounded merge/deletion batches
2. Tuneables reduction wave:
   - reduce schema keys below `415` by removing unused/dead surfaces with usage evidence
3. Store consolidation wave:
   - remove additional JSON/JSONL runtime dependencies where SQLite equivalents exist
4. Compaction unification wave:
   - extend compaction actions beyond cognitive-only scope
5. Distillation collapse wave:
   - reduce distillation file count below `5` with one execution spine
6. VibeForge evolve scope decision:
   - keep deferred for this repo unless explicitly promoted from private project

Exit criteria:

1. each wave reports before/after counts
2. no production gate regressions
3. replay evidence remains promotion-pass green

Rollback:

1. revert per-wave commit set independently

## Non-goals for alpha start

These are explicitly out of current start gate:

1. full VibeForge code-evolve lane
2. total one-store migration across all historical JSONL surfaces
3. full advisory 17->3 collapse in a single jump

## Execution command (target)

```powershell
python scripts/alpha_start_readiness.py --emit-report --strict
```

## Required artifacts

1. `benchmarks/out/alpha_start/alpha_start_readiness_latest.json`
2. `benchmarks/out/alpha_start/alpha_start_readiness_latest.md`
3. replay evidence files referenced by the JSON report
4. controlled-delta output referenced by the JSON report
5. `benchmarks/out/alpha_start/alpha_gap_audit_latest.json`
6. `benchmarks/out/alpha_start/alpha_gap_audit_latest.md`
