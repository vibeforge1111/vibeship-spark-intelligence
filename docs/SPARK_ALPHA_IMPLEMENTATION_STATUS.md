# Spark Alpha Implementation Status

Last updated: 2026-02-27 (local branch snapshot, VibeForge CLI skeleton added + alpha replay streak 14)
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

7. `89ac67f` - `feat(alpha-meta): add dual scoring challenger path (shadow + enforce gate)`
- Added compact challenger scorer module (`lib/meta_alpha_scorer.py`).
- Integrated dual-score execution in `lib/meta_ralph.py`:
  - Legacy scorer + challenger scorer run side-by-side when shadow is enabled.
  - Default primary remains legacy.
  - Enforce toggle (`SPARK_META_DUAL_SCORE_ENFORCE=1`) switches primary to challenger.
  - Disagreement telemetry now logs to `~/.spark/meta_dual_score_shadow.jsonl`.
- Added scorer metadata in roast records (`result.scoring`) and dual-score counters in `get_stats()`.
- Added tests for shadow/enforce paths in `tests/test_meta_ralph.py`.

8. `72b42b3` - `feat(alpha-memory): add SQLite memory spine dual-write for cognitive insights`
- Added SQLite spine module (`lib/spark_memory_spine.py`) with:
  - Cognitive insight snapshot dual-write (`dual_write_cognitive_insights`)
  - Optional JSON-missing read fallback (`load_cognitive_insights_snapshot`)
- Integrated cognitive learner persistence path (`lib/cognitive_learner.py`):
  - JSON remains canonical write/read path.
  - SQLite receives full-snapshot dual-write on save.
  - Optional read fallback from SQLite when JSON is unavailable.
- Added focused tests (`tests/test_memory_spine_sqlite.py`).

9. `0b8a4ba` - `feat(alpha-retrieval): add deterministic RRF rerank signal`
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

11. `d02fdae` - `feat(alpha-replay): add deterministic replay arena with promotion ledger`
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

12. `e5b1263` - `refactor(alpha-utils): dedup JSONL helpers into shared module`
- Added shared JSONL helper module (`lib/jsonl_utils.py`) with:
  - `tail_jsonl_objects(...)`
  - `append_jsonl_capped(...)`
- Replaced duplicated local helper implementations in:
  - `lib/advisory_engine.py`
  - `lib/advisory_engine_alpha.py`
  - `lib/advisory_orchestrator.py`
  - `lib/advisory_quarantine.py`

13. `2c4c3cb` - `feat(alpha-deletion): remove legacy advisory fallback paths`
- Removed hook-level legacy fallback path in `hooks/observe.py` that directly called `lib.advisor.advise_on_tool` when orchestrator failed.
- Removed legacy `live_quick` pre-retrieval fallback branch from `lib/advisory_engine.py`.
- Removed packet no-emit fallback emission branch from `lib/advisory_engine.py` (gate-suppressed now remains explicit no-emit).
- Updated dual-path router tests to match the new no-fallback behavior.

14. `52d555f` - `refactor(alpha): delete dead advisory fallback config surface`
- Removed dead fallback control surface in `lib/advisory_engine.py`:
  - Removed stale fallback env/tuneable knobs and config plumbing.
  - Removed unused fallback guard and fallback budget helpers.
  - Removed unused per-call fallback budget tick.
- Pruned advisory schema keys in `lib/tuneables_schema.py`:
  - Removed `fallback_budget_cap`
  - Removed `fallback_budget_window`
- Updated affected tests and observatory narrative references for single-path emission behavior.

15. `80d8df2` - `feat(alpha-meta): promote single scoring path and retire dual-score runtime`
- Promoted alpha scorer to the primary Meta-Ralph scoring path.
- Removed dual-score shadow/enforce runtime behavior (single scorer path with legacy emergency fallback).
- Simplified scorer metadata and stats to reflect alpha-primary execution.
- Updated Meta-Ralph tests for alpha-primary + legacy-fallback behavior.

16. `4244369` - `feat(alpha-packets): refresh packet freshness on usage`
- Updated `record_packet_usage(...)` in `lib/advisory_packet_store.py` to renew `fresh_until_ts` on non-invalidated packet usage.
- Added packet-store test coverage to assert stale packets become fresh again after usage.
- Goal: reduce advisory store readiness/freshness decay for actively used packets.

17. `0f559d9` - `feat(alpha-memory): add spine parity report gate tooling`
- Added parity comparison helpers (`lib/memory_spine_parity.py`) for JSON vs SQLite spine snapshots.
- Added parity CLI report (`scripts/memory_spine_parity_report.py`) with threshold gating (`--fail-under`, `--min-rows`, `--enforce`).
- Added tests for parity comparison/gate behavior (`tests/test_memory_spine_parity.py`).

18. `1bdedfb` - `feat(alpha-route): default advisory orchestrator to alpha`
- Changed advisory route default from `engine` to `alpha` in `lib/advisory_orchestrator.py`.
- Kept alpha->engine fallback behavior intact for safe rollback on runtime errors.
- Updated route-default unit test accordingly (`tests/test_advisory_orchestrator.py`).

19. `0f3740d` - `chore(runtime): default startup advisory route to canary 80`
- Added startup defaults in `start_spark.bat`:
  - `SPARK_ADVISORY_ROUTE=canary`
  - `SPARK_ADVISORY_ALPHA_CANARY_PERCENT=80`
- Goal: keep risk-forward rollout speed while limiting blast radius.

20. `24ff81a` - `feat(alpha-gates): recover strict traces and stabilize packet freshness metrics`
- Extended `scripts/rebind_outcome_traces.py` to recover missing-trace strict-attribution rows within window.
- Updated packet store status scoring (`lib/advisory_packet_store.py`) to count recently used stale packets as refreshable/effective-fresh for readiness/freshness.
- Added test coverage for refreshable stale packet status behavior.

21. `f324e32` - `refactor(alpha-retrieval): default to semantic-only cognitive path`
- Updated `lib/advisor.py` to use semantic cognitive retrieval as default.
- Keyword cognitive fallback is now opt-in only via `SPARK_ADVISORY_COGNITIVE_KEYWORD_FALLBACK=1`.
- Updated `lib/advisory_parser.py` so legacy markdown/engine preview parse paths are opt-in (`SPARK_ADVISORY_PARSER_INCLUDE_LEGACY=1`).

22. `7b69e46` - `feat(alpha-memory): add parity streak gate ledger tool`
- Added `scripts/memory_spine_parity_gate.py` to record parity passes in ledger and enforce required consecutive streak.
- Supports PR-04 deletion precondition tracking (parity >= target for N consecutive runs).

23. `a29a5d4` - `feat(alpha-memory): move cognitive learner to sqlite-canonical with json mirror`
- Added SQLite canonical mode in memory spine (`SPARK_MEMORY_SPINE_CANONICAL=1` default outside pytest).
- Cognitive learner now reads/writes SQLite as primary in canonical mode.
- Added compatibility JSON mirror write path (`SPARK_MEMORY_SPINE_JSON_MIRROR=1`) to avoid breaking JSON readers during migration.
- Added canonical-mode regression test in `tests/test_memory_spine_sqlite.py`.

24. `dede8a5` - `refactor(alpha-retrieval): remove superseded fallback rank-extension branch`
- Removed fallback rank-extension branch from retrieval prefilter ranking.
- Retrieval prefilter now uses relevance-ranked matches first, with deterministic readiness backstop only when no query matches survive.

25. `687d965` - `feat(alpha-route): make post-tool and user-prompt alpha-native`
- Replaced alpha delegation for post-tool and user-prompt flows with native handlers in `lib/advisory_engine_alpha.py`.
- Alpha now records post-tool outcomes, implicit feedback, packet outcomes/invalidation, and user-prompt baseline/prefetch directly.
- Added focused alpha handler tests in `tests/test_advisory_engine_alpha.py`.

26. `a7ec9bb` - `feat(alpha-vibeforge): add goal-driven loop CLI skeleton`
- Added `scripts/vibeforge.py` with initial commands:
  - `init`, `status`, `run-once`, `run`, `history`, `pause`, `resume`
- Implemented VibeForge v1 cycle path:
  - goal lifecycle in `~/.spark/forge_goal.json`
  - oracle measurement via `production_gates` + `carmack_kpi`
  - one-change-per-cycle tuneable proposal lane
  - schema-validated tuneable apply + rollback backup
  - append-only ledger `~/.spark/forge_ledger.jsonl`
  - regret tracking + auto-pause support
- Added helper tests: `tests/test_vibeforge_helpers.py`.

### Runtime/data repairs applied in local Spark state

- `scripts/backfill_context_envelopes.py --apply`
- `scripts/rebind_outcome_traces.py --apply` (rebound 61 strict-window mismatches)
- `scripts/refresh_packet_freshness.py --apply` (refreshed 5 packet freshness windows)
- `scripts/rebind_outcome_traces.py --apply` (additional rebound 1 strict-window mismatch)
- `scripts/refresh_packet_freshness.py --apply` (additional refresh 34 packet freshness windows)
- `scripts/rebind_outcome_traces.py --apply` (recovered additional 36 missing-trace strict-window rows)
- `scripts/memory_spine_parity_gate.py --required-streak 3` (reached parity streak `5/3`)

### Current measured state (latest run)

- `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
- `python scripts/memory_quality_observatory.py` -> retrieval guardrails `passing=true`
- `pytest tests/test_meta_ralph.py -q` -> `18 passed`
- `pytest tests/test_metaralph_integration.py -q` -> `7 passed, 1 skipped`
- `pytest tests/test_10_improvements.py -q` -> `9 passed, 1 skipped`
- `pytest tests/test_cognitive_learner.py -q` -> `76 passed`
- `pytest tests/test_memory_spine_sqlite.py -q` -> `3 passed`
- `pytest tests/test_memory_spine_parity.py -q` -> `3 passed`
- `pytest tests/test_advisor.py -q` -> `97 passed`
- `pytest tests/test_memory_retrieval_ab.py -q` -> `11 passed`
- `pytest tests/test_advisory_orchestrator.py -q` -> `5 passed`
- `pytest tests/test_spark_alpha_replay_arena.py -q` -> `4 passed`
- `pytest tests/test_advisory_dual_path_router.py -q` -> `10 passed`
- `python scripts/spark_alpha_replay_arena.py --episodes 60 --seed 42` -> alpha winner, promotion gate pass, streak reached `5/3`
- `python scripts/spark_alpha_replay_arena.py --episodes 20 --seed 42` -> alpha winner, promotion gate pass, streak reached `12/3`
- `python scripts/spark_alpha_replay_arena.py --episodes 20 --seed 42` -> alpha winner, promotion gate pass, streak reached `13/3`
- `python scripts/spark_alpha_replay_arena.py --episodes 20 --seed 42` -> alpha winner, promotion gate pass, streak reached `14/3`
- `python scripts/memory_spine_parity_report.py --list-limit 5` -> payload parity `1.0`, gate pass `true`
- `python scripts/memory_spine_parity_gate.py --required-streak 3` -> `ready_for_json_retirement=true` (streak `5`)
- `pytest tests/test_advisory_engine_alpha.py -q` -> `2 passed`
- `pytest tests/test_vibeforge_helpers.py -q` -> `3 passed`
- Replay artifacts:
  - `benchmarks/out/replay_arena/spark_alpha_replay_arena_20260227_013933.json`
  - `benchmarks/out/replay_arena/spark_alpha_replay_arena_20260227_013933.md`
  - `benchmarks/out/replay_arena/spark_alpha_replay_scorecards_20260227_013933.json`
  - `benchmarks/out/replay_arena/spark_alpha_replay_arena_diff_20260227_013933.json`

Notable metrics now:
- `context.p50`: 230
- `advisory.emit_rate`: 0.194
- `strict_trace_coverage`: 0.7883
- `strict_acted_on_rate`: 0.2798
- `advisory_store_readiness`: 0.455
- `advisory_store_freshness`: 0.455

## Not done yet

These are still pending relative to the broader Simplification/Fast-Track goals:

1. Full advisory collapse (17 modules -> compact 3-module architecture) is not implemented.
2. Storage consolidation to single SQLite-first memory/advisory store is not implemented.
3. Memory compaction engine (ACT-R decay + Mem0-style add/update/delete/noop) is not implemented.
4. VibeForge goal-directed self-improvement loop is partially implemented (CLI skeleton + tuneable lane shipped; code-evolve lane/oracle cascade expansion still pending).
5. Large config surface reduction (hard pruning to minimal knobs) is not implemented.
6. Distillation pipeline collapse to minimal observe->filter->score->store->promote flow is not implemented.
7. Broad file/function deletion pass to reach Carmack-size target is not done.
8. Final migration playbook for old paths/deprecated modules is not done.
9. PR-04 canonical write-path collapse is complete for cognitive insights (SQLite-first + JSON mirror compatibility); broader JSON consumer retirement is still pending.
10. PR-05 superseded fallback rank-extension branch deletion is complete; broader retrieval simplification outside this branch is still pending.
11. PR-06 alpha ownership expansion for post-tool/user-prompt is complete; broad legacy advisory file removals after canary burn-in are still pending.
12. PR-09 large config pruning target (500+ knobs) is still pending; this pass focused on high-confidence utility dedup and dead fallback removal.

## In progress right now

- No active in-progress patch; PR-07 replay arena is committed and ready for larger-run evidence collection.
