# Spark Alpha Implementation Status

Last updated: 2026-02-27 (local branch snapshot, post PR-07 replay arena implementation)
Branch: feat/spark-alpha

## Done so far

### Code commits completed

1. `59865e8` - `feat(alpha): lock metric contract and add baseline rehydrate/drift tooling`
- Added shared metric contract (`lib/metric_contract.py`) and wired it into gates/observability.
- Added baseline repair and drift checks (`scripts/rehydrate_alpha_baseline.py`, `scripts/cross_surface_drift_checker.py`).

2. `051d6de` - `feat(alpha-noise): add unified noise classifier scaffold with tests`
- Added `lib/noise_classifier.py` and initial tests for unified classification behavior.

3. `86a33ee` - `feat(alpha-noise): shadow unified classifier across promoter/meta/cognitive`
- Integrated unified noise classifier in shadow mode across:
  - `lib/meta_ralph.py`
  - `lib/cognitive_learner.py`
  - `lib/promoter.py`
- Added disagreement shadow logging and enforcement toggle path.

4. `11c1808` - `feat(alpha-memory): add contextual envelope backfill for cognitive insights`
- Added write-time context envelope builder (`lib/context_envelope.py`).
- Added backfill utility for existing cognitive contexts (`scripts/backfill_context_envelopes.py`).

5. `4b3e4df` - `feat(alpha-advisory): restore one repeat-suppressed candidate to avoid no-emit loops`
- Added bounded repeat-cooldown escape logic in advisory emission quality filter to reduce no-emit loops without bypassing safety/noise filters.

6. `734bddf` - `feat(alpha-loop): repair strict trace binding and refresh packet freshness`
- Improved trace propagation in feedback paths (`lib/advisor.py`, `lib/advisory_engine.py`).
- Added strict-trace data repair utility (`scripts/rebind_outcome_traces.py`).
- Added advisory packet freshness repair utility (`scripts/refresh_packet_freshness.py`).
- Added production gate guard so Meta-Ralph quality band remains telemetry-only unless explicitly env-enabled.

7. `(working tree)` - `feat(alpha-meta): add dual scoring challenger path (shadow + enforce gate)`
- Added compact challenger scorer module (`lib/meta_alpha_scorer.py`).
- Integrated dual-score execution in `lib/meta_ralph.py`:
  - Legacy scorer + challenger scorer run side-by-side when shadow is enabled.
  - Default primary remains legacy.
  - Enforce toggle (`SPARK_META_DUAL_SCORE_ENFORCE=1`) switches primary to challenger.
  - Disagreement telemetry now logs to `~/.spark/meta_dual_score_shadow.jsonl`.
- Added scorer metadata in roast records (`result.scoring`) and dual-score counters in `get_stats()`.
- Added tests for shadow/enforce paths in `tests/test_meta_ralph.py`.

8. `(working tree)` - `feat(alpha-memory): add SQLite memory spine dual-write for cognitive insights`
- Added SQLite spine module (`lib/spark_memory_spine.py`) with:
  - Cognitive insight snapshot dual-write (`dual_write_cognitive_insights`)
  - Optional JSON-missing read fallback (`load_cognitive_insights_snapshot`)
- Integrated cognitive learner persistence path (`lib/cognitive_learner.py`):
  - JSON remains canonical write/read path.
  - SQLite receives full-snapshot dual-write on save.
  - Optional read fallback from SQLite when JSON is unavailable.
- Added focused tests (`tests/test_memory_spine_sqlite.py`).

9. `(working tree)` - `feat(alpha-retrieval): add deterministic RRF rerank signal`
- Added normalized reciprocal-rank-fusion scoring to advisory retrieval (`lib/advisor.py`):
  - Fuses semantic rank + lexical rank + support rank.
  - Injected as an explicit rerank feature (`rrf_fusion`) with policy weight (`rrf_weight`).
- Added the same deterministic RRF helper to the retrieval A/B harness (`benchmarks/memory_retrieval_ab.py`).
- Added tests for cross-signal RRF behavior:
  - `tests/test_advisor.py`
  - `tests/test_memory_retrieval_ab.py`

10. `23ef06a` - `feat(alpha-advisory): add advisory alpha vertical slice + route orchestrator`
- Added compact alpha hot path (`lib/advisory_engine_alpha.py`) for:
  - retrieve -> gate -> synthesize -> emit
  - strict trace-bound delivery metadata
  - context/text repeat suppression and deduped emission candidates
- Added route orchestrator (`lib/advisory_orchestrator.py`) with:
  - route modes: `engine | alpha | canary`
  - deterministic canary routing via `SPARK_ADVISORY_ALPHA_CANARY_PERCENT`
  - alpha-to-engine fallback on route errors
  - route decision telemetry (`~/.spark/advisory_route_decisions.jsonl`)
- Wired all hook entry points to orchestrator (`hooks/observe.py`):
  - pre-tool
  - post-tool
  - user-prompt
- Added alpha-vs-engine comparison script (`scripts/advisory_alpha_quality_report.py`).
- Added explicit legacy deletion candidate manifest for PR-10 (`docs/SPARK_ALPHA_PR06_LEGACY_DELETION_CANDIDATES.md`).

11. `(working tree)` - `feat(alpha-replay): add deterministic replay arena with promotion ledger`
- Added deterministic champion/challenger replay harness (`scripts/spark_alpha_replay_arena.py`):
  - Same episode set for both routes (legacy vs alpha) from a fixed seed or explicit episode file.
  - Per-route scorecards on utility, safety, trace integrity, and latency.
  - Weighted winner computation with explicit coefficients.
  - Regression diff artifact generation vs previous run.
- Added promotion ledger (`~/.spark/alpha_replay_promotion_ledger.jsonl`) with:
  - run-level alpha win status
  - safety/trace gate pass flags
  - consecutive pass streak tracking
- Added replay arena unit tests (`tests/test_spark_alpha_replay_arena.py`).

### Runtime/data repairs applied in local Spark state

- `scripts/backfill_context_envelopes.py --apply`
- `scripts/rebind_outcome_traces.py --apply` (rebound 61 strict-window mismatches)
- `scripts/refresh_packet_freshness.py --apply` (refreshed 5 packet freshness windows)

### Current measured state (latest run)

- `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
- `python scripts/memory_quality_observatory.py` -> retrieval guardrails `passing=true`
- `pytest tests/test_meta_ralph.py -q` -> `18 passed`
- `pytest tests/test_metaralph_integration.py -q` -> `7 passed, 1 skipped`
- `pytest tests/test_10_improvements.py -q` -> `9 passed, 1 skipped`
- `pytest tests/test_cognitive_learner.py -q` -> `76 passed`
- `pytest tests/test_memory_spine_sqlite.py -q` -> `2 passed`
- `pytest tests/test_advisor.py -q` -> `97 passed`
- `pytest tests/test_memory_retrieval_ab.py -q` -> `11 passed`
- `pytest tests/test_advisory_orchestrator.py -q` -> `5 passed`
- `pytest tests/test_spark_alpha_replay_arena.py -q` -> `4 passed`
- `python scripts/spark_alpha_replay_arena.py --episodes 5 --seed 42` -> alpha winner, promotion gate pass, streak reached `4/3`
- Replay artifacts:
  - `benchmarks/out/replay_arena/spark_alpha_replay_arena_20260227_011352.json`
  - `benchmarks/out/replay_arena/spark_alpha_replay_arena_20260227_011352.md`
  - `benchmarks/out/replay_arena/spark_alpha_replay_scorecards_20260227_011352.json`
  - `benchmarks/out/replay_arena/spark_alpha_replay_arena_diff_20260227_011352.json`

Notable metrics now:
- `context.p50`: 230
- `advisory.emit_rate`: 0.194
- `strict_trace_coverage`: 0.5985
- `strict_acted_on_rate`: 0.2193

## Not done yet

These are still pending relative to the broader Simplification/Fast-Track goals:

1. Full advisory collapse (17 modules -> compact 3-module architecture) is not implemented.
2. Storage consolidation to single SQLite-first memory/advisory store is not implemented.
3. Memory compaction engine (ACT-R decay + Mem0-style add/update/delete/noop) is not implemented.
4. Thompson-sampling source selector is not implemented.
5. Large config surface reduction (hard pruning to minimal knobs) is not implemented.
6. Distillation pipeline collapse to minimal observe->filter->score->store->promote flow is not implemented.
7. Broad file/function deletion pass to reach Carmack-size target is not done.
8. Final migration playbook for old paths/deprecated modules is not done.
9. PR-03 deletion commitment is still pending (legacy scorer path removal after replay wins).
10. PR-04 deletion commitment is still pending (JSONL/legacy path retirement after parity criteria).
11. PR-05 deletion commitment is still pending (retire superseded rank paths after replay/canary wins).
12. PR-06 deletion commitment is still pending (remove legacy advisory path files after replay + live canary pass).
13. PR-07 now exists, but its criteria still need repeated run evidence on larger episode sets before using it as sole cutover authority.

## In progress right now

- No active in-progress patch; PR-07 replay arena is checkpointed and awaiting commit plus extended-run evidence collection.
