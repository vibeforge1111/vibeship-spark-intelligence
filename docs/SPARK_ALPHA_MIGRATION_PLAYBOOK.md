# Spark Alpha Migration Playbook

Date: 2026-02-27  
Branch target: `feat/spark-alpha` -> `main`

## Scope

This playbook defines the exact rollout path from mixed legacy/alpha surfaces to alpha-primary runtime with explicit rollback points.

## Preconditions (must all pass)

1. `python scripts/production_loop_report.py` returns `READY` for 3 consecutive runs.
2. `python scripts/spark_alpha_replay_arena.py --episodes 20 --seed 42` returns `promotion_gate_pass=true` for 3 consecutive runs.
3. `python -m lib.tuneables_schema` returns `ok=True`, `unknown=0`.
4. `python scripts/memory_json_consumer_gate.py --max-runtime-hits 0 --max-total-hits 80 --required-streak 3` returns `ready_for_runtime_json_retirement=true`.

## Phase A: Runtime Lock

1. Runtime routing is alpha-only (no route toggle).
2. Verify alpha runtime log is active:
   - `~/.spark/advisory_engine_alpha.jsonl`
3. Run smoke workload:
   - `python scripts/advisory_controlled_delta.py --rounds 20 --label alpha_lock --out benchmarks/out/advisory_delta_alpha_lock.json`

Rollback A:
1. Restore previous commit/tag and re-run smoke workload.

## Phase B: Storage Lock

1. SQLite packet lookup is canonical (no runtime toggle).
2. Run packet/retrieval regression slice:
   - `pytest tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py -q`
3. Verify parity gates:
   - `python scripts/memory_spine_parity_report.py --list-limit 5`

Rollback B:
1. Restore prior commit/tag if packet-spine regression is detected.
2. Re-run regression slice.

## Phase C: Legacy Surface Removal

1. Remove legacy advisory compatibility module and legacy-only tests (done in alpha branch):
   - `lib/advisory_engine.py`
   - `tests/test_advisory_engine_evidence.py`
   - `tests/test_advisory_engine_lineage.py`
2. Keep replay arena champion as orchestrator, challenger as alpha.
3. Run alpha advisory regression slice:
   - `pytest tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py -q`

Rollback C:
1. Restore deleted suites/scripts from prior commit tag if specific diagnostics are needed.

## Phase D: Merge Gate

1. Record the final evidence bundle:
   - replay arena report JSON/MD
   - production loop report output
   - tuneables schema validation output
   - packet/retrieval regression test outputs
2. Merge only if:
   - no guardrail regressions
   - no trace-integrity regression
   - no unresolved runtime errors from smoke workloads

## Post-Merge Watch (24h)

1. Run `production_loop_report.py` every 2h.
2. Run replay arena every 6h (`--episodes 20 --seed 42`).
3. If two consecutive runs fail promotion/safety/trace gates, revert to previous champion commit.
